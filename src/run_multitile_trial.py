"""Run and validate a bounded India tile trial using only local FIRMS/OSM inputs."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.engineer_features import add_past_only_recurrence, discover_satellite_run
from src.pipeline_cache import file_fingerprint
from src.regions import (DEFAULT_REGION_CONFIG, assign_tile_ids, contains_coordinates,
                         get_region, tile_for_coordinate)

DEFAULT_TILES = ["india_r05_c05", "india_r05_c06"]


def directory_bytes(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file()) if path.exists() else 0


def run_measured(command: list[str], run_dir: Path, stage: str) -> dict:
    started = time.perf_counter()
    peak = directory_bytes(run_dir)
    with tempfile.TemporaryFile(mode="w+b") as error_log:
        process = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=error_log)
        while process.poll() is None:
            peak = max(peak, directory_bytes(run_dir))
            time.sleep(0.1)
        peak = max(peak, directory_bytes(run_dir))
        error_log.seek(0)
        error = error_log.read().decode("utf-8", errors="replace")
    elapsed = time.perf_counter() - started
    if process.returncode:
        # Avoid echoing arbitrary machine-specific paths from child tracebacks.
        raise RuntimeError(f"{stage} failed with exit code {process.returncode}: {error[-3000:].replace(str(ROOT), '<repo>')}")
    return {"runtime_seconds": round(elapsed, 3), "peak_run_directory_bytes_sampled": peak,
            "final_run_directory_bytes": directory_bytes(run_dir)}


def relative_or_name(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.name


def content_only(value):
    if isinstance(value, dict):
        return {key: content_only(item) for key, item in value.items() if key != "mtime_ns"}
    if isinstance(value, list):
        return [content_only(item) for item in value]
    return value


def fingerprint_inputs(firms_path: Path, osm_path: Path, gem_dir: Path,
                       matching_dir: Path, satellite_dir: Path | None) -> dict:
    paths = {"firms": firms_path, "osm": osm_path,
             "region_config": ROOT / "config/regions.json",
             "matching_csv": matching_dir / "firms_pilot_osm_proximity.csv"}
    if gem_dir.is_dir():
        paths.update({f"gem:{path.name}": path for path in sorted(gem_dir.glob("*.json"))})
    if satellite_dir is not None:
        metadata = satellite_dir / "scene_metadata.csv"
        if metadata.is_file():
            paths["satellite_metadata"] = metadata
            try:
                scenes = pd.read_csv(metadata)
                for column in ("chip_path", "scl_chip_path"):
                    for value in scenes.get(column, pd.Series(dtype=str)).dropna().astype(str):
                        raw = Path(value.replace("\\", "/"))
                        candidates = [raw] if raw.is_absolute() else [satellite_dir / raw, satellite_dir / raw.name, ROOT / raw]
                        chip = next((candidate for candidate in candidates if candidate.is_file()), None)
                        if chip:
                            paths[f"{column}:{chip.name}"] = chip
            except (OSError, pd.errors.ParserError):
                pass
    return {name: {key: value for key, value in file_fingerprint(path).items() if key not in {"path", "mtime_ns"}}
            for name, path in paths.items() if path.is_file()}


def validate_outputs(firms_path: Path, matching_dir: Path, features_dir: Path,
                     region_id: str, tile_ids: list[str]) -> dict:
    region = get_region(region_id)
    matches_path = matching_dir / "firms_pilot_osm_proximity.csv"
    features_path = features_dir / "feature_table.csv.gz"
    matches = pd.read_csv(matches_path, low_memory=False)
    features = pd.read_csv(features_path, low_memory=False)
    longitude = pd.to_numeric(matches.longitude, errors="coerce")
    latitude = pd.to_numeric(matches.latitude, errors="coerce")
    in_boundary = contains_coordinates(longitude, latitude, region)
    expected_tiles = assign_tile_ids(longitude.to_numpy(), latitude.to_numpy(), region)
    expected_tile_set = set(tile_ids)
    tile_matches = matches.tile_id.astype(str).tolist() == expected_tiles
    crs_valid = True
    for tile_id, indices in matches.groupby("tile_id", sort=False).groups.items():
        tile = tile_for_coordinate(float(longitude.iloc[indices[0]]), float(latitude.iloc[indices[0]]), region)
        crs_valid &= tile is not None and tile["tile_id"] == tile_id
        crs_valid &= set(matches.loc[indices, "distance_crs"].astype(str)) == {tile["projected_crs"]}
    duplicate_ids = int(matches.firms_observation_id.duplicated().sum())
    assigned_tiles = set(matches.tile_id.astype(str))
    # Recompute recurrence over the combined, selected-tile observations and compare
    # it with the delivered feature table, including cells that span tile IDs.
    recurrence_check = add_past_only_recurrence(matches)
    recurrence_columns = ["cell_prior_detection_count", "cell_prior_distinct_acquisition_dates",
                         "cell_prior_recurring_flag", "cell_first_observed_in_source_window"]
    joined = features.set_index("firms_source_row").sort_index()
    expected = recurrence_check.set_index("firms_source_row").sort_index()
    recurrence_equal = len(joined) == len(expected)
    for column in recurrence_columns:
        recurrence_equal &= column in joined and column in expected and joined[column].astype(str).equals(expected[column].astype(str))
    shared_cells = matches.groupby("hotspot_cell_id").tile_id.nunique()
    cross_tile_cells = int((shared_cells > 1).sum())
    checks = {
        "all_observations_covered_by_india_boundary": bool(in_boundary.all()),
        "tile_assignment_matches_shared_region_function": bool(tile_matches),
        "only_requested_tiles_present": assigned_tiles == expected_tile_set,
        "observation_ids_unique": duplicate_ids == 0,
        "per_tile_crs_matches_tile_configuration": bool(crs_valid),
        "feature_recurrence_matches_combined_past_only_recalculation": bool(recurrence_equal),
        "recurrence_cells_crossing_tile_boundaries": cross_tile_cells,
    }
    failures = [name for name, value in checks.items() if value is False]
    if failures:
        raise ValueError(f"Trial validation failed: {failures}")
    summary_path = matching_dir / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    tile_statuses = [{**tile, "processing_status": "completed"} for tile in summary["tile_processing"]["tiles"]]
    if {tile["tile_id"] for tile in tile_statuses} != expected_tile_set:
        raise ValueError("Matching summary tile list does not agree with selected trial tiles")
    input_rows = len(pd.read_csv(firms_path, usecols=["latitude", "longitude"]))
    checks["input_observations"] = input_rows
    checks["retained_trial_observations"] = len(matches)
    checks["duplicate_observation_ids"] = duplicate_ids
    checks["cross_tile_recurrence_cells"] = cross_tile_cells
    checks["selected_tile_counts"] = matches.groupby("tile_id").size().astype(int).to_dict()
    return {"checks": checks, "tiles": tile_statuses, "matching_csv": matches_path,
            "features_path": features_path, "matching_cache_hits": summary["tile_processing"].get("completed_tile_cache_hits", 0)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--firms", type=Path, default=Path("data/processed/firms_pilot.csv"))
    parser.add_argument("--osm", type=Path, default=Path("data/processed/osm/dhanbad_jharia_bokaro_osm.gpkg"))
    parser.add_argument("--gem-dir", type=Path, default=Path("data/processed/gem"))
    parser.add_argument("--region", default="india")
    parser.add_argument("--tiles", nargs="+", default=DEFAULT_TILES)
    parser.add_argument("--run-dir", type=Path, help="dedicated output directory; default is timestamped")
    parser.add_argument("--resume", action="store_true", help="resume the matching stage in the existing run directory")
    args = parser.parse_args(argv)
    def rooted(path: Path) -> Path:
        return path.resolve() if path.is_absolute() else (ROOT / path).resolve()
    firms_path, osm_path, gem_dir = map(rooted, (args.firms, args.osm, args.gem_dir))
    for path in (firms_path, osm_path):
        if not path.is_file():
            raise FileNotFoundError(f"Trial input missing: {relative_or_name(path)}")
    if not args.tiles or len(args.tiles) != len(set(args.tiles)):
        parser.error("--tiles must contain one or more unique India tile IDs")
    if args.run_dir:
        run_dir = rooted(args.run_dir)
    else:
        stamp = datetime.now(timezone.utc).strftime("run_%Y%m%dT%H%M%SZ")
        run_dir = ROOT / "data/processed/multi_tile_validation" / stamp
    if args.resume:
        if not run_dir.is_dir():
            raise FileNotFoundError(f"Cannot resume missing trial run: {relative_or_name(run_dir)}")
    else:
        run_dir.mkdir(parents=True, exist_ok=False)
    matching_dir, features_dir = run_dir / "spatial_matching", run_dir / "feature_engineering"
    satellite_dir = discover_satellite_run(ROOT)
    match_command = [sys.executable, str(ROOT / "src/match_firms_osm_pilot.py"),
                     "--repo", str(ROOT), "--region", args.region, "--firms", str(firms_path),
                     "--osm", str(osm_path), "--gem-dir", str(gem_dir), "--tile-ids", *args.tiles,
                     "--output-dir", str(matching_dir)]
    if args.resume:
        match_command.append("--resume")
    metrics = {"stage_matching": run_measured(match_command, run_dir, "matching")}
    existing_report = run_dir / "trial_validation.json"
    current_feature_inputs = fingerprint_inputs(firms_path, osm_path, gem_dir, matching_dir, satellite_dir)
    feature_code_sha = file_fingerprint(ROOT / "src/engineer_features.py")["sha256"]
    if features_dir.exists():
        # Do not replace feature outputs. A completed trial report can establish a
        # cache hit; partial/unmanifested feature output requires a new run folder.
        if not existing_report.is_file():
            raise FileExistsError(f"Feature output exists without a complete trial manifest: {relative_or_name(features_dir)}")
        old = json.loads(existing_report.read_text(encoding="utf-8"))
        if (old.get("matching_csv_sha256") != file_fingerprint(matching_dir / "firms_pilot_osm_proximity.csv")["sha256"]
                or content_only(old.get("feature_stage_inputs")) != content_only(current_feature_inputs)
                or old.get("feature_code_sha256") != feature_code_sha):
            raise ValueError("Matching output changed since prior feature run; choose a new run directory to preserve old results")
        for rel, digest in old.get("feature_artifact_sha256", {}).items():
            if not (run_dir / rel).is_file() or file_fingerprint(run_dir / rel)["sha256"] != digest:
                raise ValueError(f"Feature cache is missing or corrupt: {rel}")
        metrics["stage_features"] = {"cache_hit": True, "runtime_seconds": 0,
                                      "final_run_directory_bytes": directory_bytes(run_dir),
                                      "peak_run_directory_bytes_sampled": directory_bytes(run_dir)}
    else:
        feature_command = [sys.executable, str(ROOT / "src/engineer_features.py"), "--repo", str(ROOT),
                           "--region", args.region, "--firms", str(firms_path), "--osm", str(osm_path),
                           "--gem-dir", str(gem_dir), "--matching-dir", str(matching_dir),
                           "--output-dir", str(features_dir)]
        if satellite_dir is not None:
            feature_command.extend(["--satellite-dir", str(satellite_dir)])
        metrics["stage_features"] = run_measured(feature_command, run_dir, "features")
    validated = validate_outputs(firms_path, matching_dir, features_dir, args.region, args.tiles)
    feature_artifacts = {}
    for path in features_dir.rglob("*"):
        if path.is_file():
            feature_artifacts[path.relative_to(run_dir).as_posix()] = file_fingerprint(path)["sha256"]
    match_sha = file_fingerprint(validated["matching_csv"])["sha256"]
    file_sizes = {path.relative_to(run_dir).as_posix(): path.stat().st_size
                  for path in run_dir.rglob("*") if path.is_file()}
    report = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "region_id": args.region, "selected_tile_ids": args.tiles,
        "inputs": {"firms": relative_or_name(firms_path), "osm": relative_or_name(osm_path),
                   "gem_directory": relative_or_name(gem_dir)},
        "metrics": metrics, "output_file_sizes_bytes": file_sizes,
        "observation_counts_and_validation": validated["checks"],
        "per_tile_status": validated["tiles"],
        "matching_completed_tile_cache_hits": validated["matching_cache_hits"],
        "matching_csv_sha256": match_sha, "feature_artifact_sha256": feature_artifacts,
        "feature_stage_inputs": current_feature_inputs, "feature_code_sha256": feature_code_sha,
        "satellite_run_used": relative_or_name(satellite_dir) if satellite_dir else None,
        "measure_note": "Peak run-directory bytes are sampled every 100 ms; short-lived spikes between samples may be missed.",
    }
    report_path = (run_dir / f"trial_validation_resume_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
                   if args.resume else run_dir / "trial_validation.json")
    report_path.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"run_dir": relative_or_name(run_dir), "retained_observations": validated["checks"]["retained_trial_observations"],
                      "tiles": validated["tiles"], "matching_cache_hits": validated["matching_cache_hits"],
                      "checks": validated["checks"], "metrics": metrics,
                      "report": relative_or_name(report_path)}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
