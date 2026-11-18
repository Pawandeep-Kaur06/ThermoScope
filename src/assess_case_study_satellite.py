"""Assess local Sentinel-2 chip coverage and optionally query public STAC metadata only."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
import rasterio
from pyproj import Transformer


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES = Path("data/processed/final_pilot_experiment/case_studies/run_20261116T094126Z/selected_case_studies.csv")
DEFAULT_SCENE_METADATA = Path("data/processed/satellite_investigation/run_20261018T212303Z/scene_metadata.csv")
STAC_URL = "https://earth-search.aws.element84.com/v1/search"
COLLECTION = "sentinel-2-l2a"
CLOUD_SHADOW_SCL = {3, 8, 9, 10}


def project_path(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def safe_path(path: Path) -> str:
    """Return a repository-relative path or a neutral basename for external input."""
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return f"[external]/{path.name}"


def utc_observation_time(row: dict[str, str]) -> datetime:
    date = datetime.strptime(row["acq_date"], "%Y-%m-%d").date()
    hhmm = str(row.get("acq_time", "")).zfill(4)
    if len(hhmm) != 4 or not hhmm.isdigit():
        raise ValueError(f"Invalid FIRMS UTC acquisition time for {row.get('firms_source_row')}: {hhmm!r}")
    return datetime(date.year, date.month, date.day, int(hhmm[:2]), int(hhmm[2:]), tzinfo=timezone.utc)


def local_chip_matches(case: dict[str, str], scene: dict[str, str]) -> dict[str, str]:
    chip_path = project_path(Path(scene.get("chip_path", "")))
    scl_path = project_path(Path(scene.get("scl_chip_path", "")))
    if not chip_path.is_file() or not scl_path.is_file():
        return {}
    with rasterio.open(chip_path) as src:
        to_chip = Transformer.from_crs("EPSG:4326", src.crs, always_xy=True)
        x, y = to_chip.transform(float(case["longitude"]), float(case["latitude"]))
        row, col = src.index(x, y)
        inside = 0 <= row < src.height and 0 <= col < src.width
    if not inside:
        return {}
    with rasterio.open(scl_path) as scl:
        row, col = scl.index(x, y)
        klass = int(scl.read(1, window=((row, row + 1), (col, col + 1)))[0, 0])
    try:
        scene_time = datetime.fromisoformat(scene["scene_datetime_utc"].replace("Z", "+00:00"))
    except (KeyError, ValueError):
        scene_time = None
    obs_time = utc_observation_time(case)
    eligible = scene_time is not None and scene_time <= obs_time
    return {
        "local_chip_cell_id": scene.get("hotspot_cell_id", ""),
        "local_chip_scene_id": scene.get("selected_stac_item", ""),
        "local_chip_scene_datetime_utc": scene.get("scene_datetime_utc", ""),
        "local_chip_scene_cloud_percent": scene.get("eo_cloud_cover_percent_scene_level", ""),
        "local_chip_fraction_cloud_shadow": scene.get("local_scl_cloud_shadow_fraction", ""),
        "local_chip_scl_class_at_detection": str(klass),
        "local_chip_pixel_cloud_shadow": str(klass in CLOUD_SHADOW_SCL),
        "local_chip_temporally_eligible": str(eligible),
        "local_chip_offset_hours": f"{(scene_time - obs_time).total_seconds()/3600:.3f}" if scene_time else "",
    }


def stac_metadata(case: dict[str, str], lookback_days: int, limit: int, session: requests.Session) -> dict[str, str]:
    obs_time = utc_observation_time(case)
    lon, lat = float(case["longitude"]), float(case["latitude"])
    half = 0.003
    body = {
        "collections": [COLLECTION],
        "bbox": [lon - half, lat - half, lon + half, lat + half],
        "datetime": f"{(obs_time - timedelta(days=lookback_days)).isoformat().replace('+00:00', 'Z')}/{obs_time.isoformat().replace('+00:00', 'Z')}",
        "limit": limit,
        "fields": {"include": ["id", "collection", "properties.datetime", "properties.eo:cloud_cover", "properties.platform"]},
    }
    response = session.post(STAC_URL, json=body, timeout=45)
    response.raise_for_status()
    features = response.json().get("features", [])
    items = []
    for feature in features:
        props = feature.get("properties", {})
        raw_time = props.get("datetime")
        if not raw_time:
            continue
        scene_time = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
        if scene_time <= obs_time:
            items.append({
                "id": feature.get("id", ""),
                "datetime": scene_time,
                "cloud": props.get("eo:cloud_cover"),
                "platform": props.get("platform", ""),
            })
    items.sort(key=lambda item: (abs((obs_time - item["datetime"]).total_seconds()), float(item["cloud"] if item["cloud"] is not None else 100)))
    nearest = items[0] if items else None
    clear_items = [item for item in items if item["cloud"] is not None and float(item["cloud"]) <= 20]
    clear = min(clear_items, key=lambda item: abs((obs_time - item["datetime"]).total_seconds())) if clear_items else None
    out = {
        "stac_status": "metadata_query_ok",
        "stac_items_temporally_eligible": str(len(items)),
        "stac_clear_scene_count_cloud_le_20_percent": str(len(clear_items)),
        "stac_nearest_scene_id": nearest["id"] if nearest else "",
        "stac_nearest_scene_datetime_utc": nearest["datetime"].isoformat() if nearest else "",
        "stac_nearest_scene_cloud_percent": str(nearest["cloud"]) if nearest and nearest["cloud"] is not None else "",
        "stac_nearest_scene_offset_days": f"{(nearest['datetime']-obs_time).total_seconds()/86400:.3f}" if nearest else "",
        "stac_nearest_clear_scene_id": clear["id"] if clear else "",
        "stac_nearest_clear_scene_datetime_utc": clear["datetime"].isoformat() if clear else "",
        "stac_nearest_clear_scene_cloud_percent": str(clear["cloud"]) if clear else "",
        "stac_nearest_clear_scene_offset_days": f"{(clear['datetime']-obs_time).total_seconds()/86400:.3f}" if clear else "",
        "stac_platform_nearest": nearest["platform"] if nearest else "",
        "stac_query_response_bytes": str(len(response.content)),
    }
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--scene-metadata", type=Path, default=DEFAULT_SCENE_METADATA)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--query-stac", action="store_true", help="Query catalog metadata only; never open or download imagery assets")
    parser.add_argument("--lookback-days", type=int, default=30)
    parser.add_argument("--max-items", type=int, default=20)
    args = parser.parse_args()
    cases_path, metadata_path, outdir = map(project_path, (args.cases, args.scene_metadata, args.output_dir))
    if not cases_path.is_file() or not metadata_path.is_file():
        parser.error("Case CSV and existing scene metadata must both exist")
    if args.lookback_days < 1 or not 1 <= args.max_items <= 100:
        parser.error("--lookback-days must be positive and --max-items must be 1..100")
    if outdir.exists() and any(outdir.iterdir()):
        parser.error(f"Output directory is not empty; refusing to overwrite: {outdir}")
    with cases_path.open(encoding="utf-8-sig", newline="") as stream:
        cases = list(csv.DictReader(stream))
    with metadata_path.open(encoding="utf-8-sig", newline="") as stream:
        scenes = list(csv.DictReader(stream))

    results = []
    session = requests.Session()
    for case in cases:
        result = {key: case.get(key, "") for key in ("case_id", "firms_source_row", "acq_date", "acq_time", "latitude", "longitude", "hotspot_cell_id", "s2_spectral_data_status", "sentinel2_clear_pre_detection_spectrum_available")}
        local_matches = [match for scene in scenes if (match := local_chip_matches(case, scene))]
        eligible_local = [match for match in local_matches if match["local_chip_temporally_eligible"] == "True"]
        eligible_local.sort(key=lambda match: abs(float(match["local_chip_offset_hours"])))
        chosen_local = eligible_local[0] if eligible_local else (local_matches[0] if local_matches else {})
        result["local_chip_footprints_containing_point"] = str(len(local_matches))
        result["local_chip_eligible_footprints"] = str(len(eligible_local))
        result.update(chosen_local)
        if args.query_stac:
            try:
                result.update(stac_metadata(case, args.lookback_days, args.max_items, session))
            except requests.RequestException as exc:
                result.update({"stac_status": f"query_failed:{type(exc).__name__}", "stac_error": str(exc)[:400]})
        else:
            result["stac_status"] = "not_queried"
        results.append(result)

    outdir.mkdir(parents=True, exist_ok=True)
    table_path = outdir / "case_study_satellite_coverage.csv"
    fields = list(dict.fromkeys(key for row in results for key in row))
    with table_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)
    successful = sum(row.get("stac_status") == "metadata_query_ok" for row in results)
    total_response_bytes = sum(int(row.get("stac_query_response_bytes", 0) or 0) for row in results)
    usable_existing_samples = sum(row.get("sentinel2_clear_pre_detection_spectrum_available", "").lower() == "true" for row in results)
    low_cloud_candidates_without_sample = sum(
        bool(row.get("stac_nearest_clear_scene_id"))
        and row.get("sentinel2_clear_pre_detection_spectrum_available", "").lower() != "true"
        for row in results
    )
    chip_pairs = []
    for scene in scenes:
        chip, scl = project_path(Path(scene.get("chip_path", ""))), project_path(Path(scene.get("scl_chip_path", "")))
        if chip.is_file() and scl.is_file():
            chip_pairs.append(chip.stat().st_size + scl.stat().st_size)
    typical_chip_pair_bytes = int(statistics.median(chip_pairs)) if chip_pairs else 0
    manifest = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "cases_csv": safe_path(cases_path),
        "cases_csv_sha256": hashlib.sha256(cases_path.read_bytes()).hexdigest(),
        "scene_metadata_csv": safe_path(metadata_path),
        "scene_metadata_csv_sha256": hashlib.sha256(metadata_path.read_bytes()).hexdigest(),
        "stac_queried": args.query_stac,
        "stac_endpoint": STAC_URL if args.query_stac else None,
        "collection": COLLECTION if args.query_stac else None,
        "metadata_only_no_raster_assets_fetched": True,
        "lookback_days": args.lookback_days if args.query_stac else None,
        "stac_limit_per_case": args.max_items if args.query_stac else None,
        "cases": len(cases),
        "stac_queries_succeeded": successful if args.query_stac else 0,
        "stac_metadata_response_bytes_total": total_response_bytes,
        "existing_clear_pre_detection_samples_in_selected_cases": usable_existing_samples,
        "additional_cases_with_scene_level_cloud_le_20_candidate": low_cloud_candidates_without_sample,
        "median_local_chip_plus_scl_bytes": typical_chip_pair_bytes,
        "estimated_extra_chip_output_for_cases_without_eligible_local_chip_bytes": typical_chip_pair_bytes * sum(int(row["local_chip_eligible_footprints"]) == 0 for row in results),
        "estimated_chip_output_for_additional_low_cloud_candidates_bytes": typical_chip_pair_bytes * low_cloud_candidates_without_sample,
        "assets_downloaded": False,
    }
    (outdir / "query_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Sentinel-2 coverage assessment for selected cases", "",
        "The existing local chip inventory was checked against the precise FIRMS point, acquisition timestamp, and chip footprint. The optional STAC step queried catalog metadata only; no raster asset was opened or downloaded.", "",
        f"- Cases: {len(cases)}; local metadata-only workflow used `{safe_path(metadata_path)}`.",
        f"- Public catalog metadata queries successful: {successful}/{len(cases)}" if args.query_stac else "- Public catalog was not queried.",
        f"- STAC metadata response payloads: {total_response_bytes:,} bytes total; imagery downloads: 0.",
        f"- Selected cases already carrying usable clear pre-detection spectra: {usable_existing_samples}/{len(cases)}; additional cases with a scene-level cloud-cover <=20% candidate within the lookback: {low_cloud_candidates_without_sample}.",
        f"- Typical existing chip + SCL pair: {typical_chip_pair_bytes:,} bytes; approximate output storage for one additional chip pair per uncovered case: {manifest['estimated_extra_chip_output_for_cases_without_eligible_local_chip_bytes']:,} bytes. This estimates compressed local output only; remote COG range-read traffic may be larger and is not measured.",
        f"- Approximate compressed output for those additional low-cloud candidates: {manifest['estimated_chip_output_for_additional_low_cloud_candidates_bytes']:,} bytes; scene-level cloud cover is only a screen and must be checked against pixel-level SCL after retrieval.",
        "",
        "| Case | FIRMS date/time UTC | Eligible local chips covering point | Local eligible scene / SCL | Nearest pre-detection scene | Scene cloud % | Nearest <=20% cloud scene | Days before FIRMS |",
        "|---|---|---:|---|---|---:|---|---:|",
    ]
    for row in results:
        local_coverage = row.get("local_chip_eligible_footprints", "0")
        local_scl = (
            f"{row.get('local_chip_scene_datetime_utc', '')[:10]} / SCL {row.get('local_chip_scl_class_at_detection', '')}"
            if row.get("local_chip_temporally_eligible") == "True" else "none"
        )
        nearest = row.get("stac_nearest_scene_datetime_utc", "") or "none found"
        cloud = row.get("stac_nearest_scene_cloud_percent", "") or "—"
        clear = row.get("stac_nearest_clear_scene_datetime_utc", "") or "none found"
        raw_offset = row.get("stac_nearest_clear_scene_offset_days", "") or row.get("stac_nearest_scene_offset_days", "")
        offset = f"{abs(float(raw_offset)):.3f}" if raw_offset else "—"
        lines.append(f"| {row['case_id']} | {row['acq_date']} {row['acq_time']} | {local_coverage} | SCL {local_scl} | {nearest} | {cloud} | {clear} | {offset} |")
    lines += [
        "", "## Interpretation limits", "",
        "A scene listed as temporally eligible was acquired before the FIRMS observation time; it remains optical context, not a thermal confirmation. Catalog scene cloud cover is a scene-level estimate. Pixel-level cloud/shadow screening is available only for local chips. Even a low-cloud scene on another date can miss short-lived activity, and a coarse thermal detection footprint cannot be resolved to a precise source using 10–20 m optical bands alone.", "",
        "If a case has no eligible local chip, retrieval should be a separate approved step using the recorded STAC item ID, a small 640 m chip window, B04/B03/B02 at 10 m, B11 at 20 m resampled for display, and SCL cloud/shadow screening. Do not retrieve complete Sentinel granules.", "",
    ]
    (outdir / "assessment.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote metadata-only assessment for {len(results)} cases to {outdir}; STAC imagery assets downloaded: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
