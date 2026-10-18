"""Acquire and locally filter the Dhanbad–Jharia–Bokaro OSM pilot extract.

No Overpass requests are made. A pinned Geofabrik Eastern Zone PBF is fetched
only when --download is supplied, then GDAL's OSM driver reads the PBF locally.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

PBF_URL = "https://download.geofabrik.de/asia/india/eastern-zone-261016.osm.pbf"
MD5_URL = PBF_URL + ".md5"
EXPECTED_BYTES = 247_316_001
BOUNDS = (85.75, 23.25, 86.75, 24.00)  # west, south, east, north; WGS84
RAW_PBF_NAME = "geofabrik_eastern-zone_261016.osm.pbf"
RAW_MD5_NAME = RAW_PBF_NAME + ".md5"
OUTPUT_NAME = "dhanbad_jharia_bokaro_osm.gpkg"
MANIFEST_NAME = "manifest.json"
LAYERS = ("points", "lines", "multilinestrings", "multipolygons", "other_relations")

# GDAL will expose every source tag in `all_tags` as JSON. The PBF itself is
# retained unchanged as the source of truth; this config affects only conversion.
OSM_CONFIG = """[general]
closed_ways_are_polygons=aeroway,amenity,boundary,building,craft,geological,historic,land_area,landuse,leisure,military,natural,office,place,shop,sport,tourism,power,industrial,man_made,plant,railway
report_all_tags=yes
tags_format=json

[points]
osm_id=yes
all_tags=yes

[lines]
osm_id=yes
all_tags=yes

[multilinestrings]
osm_id=yes
all_tags=yes

[multipolygons]
osm_id=yes
all_tags=yes

[other_relations]
osm_id=yes
all_tags=yes
"""


def fetch_small(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "ThermoScope academic OSM pilot"})
    try:
        with urlopen(request, timeout=60) as response:
            return response.read()
    except HTTPError as exc:
        detail = exc.read(1000).decode("utf-8", errors="replace")
        raise RuntimeError(f"Geofabrik returned HTTP {exc.code} for {url}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"Geofabrik unavailable at {url}: {exc.reason}") from exc


def file_md5(path: Path) -> str:
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_extract(path: Path, md5_path: Path, overwrite: bool) -> str:
    if path.exists() and not overwrite:
        if path.stat().st_size != EXPECTED_BYTES:
            raise RuntimeError(f"Existing extract has unexpected size ({path.stat().st_size} bytes): {path}")
        sidecar = md5_path.read_bytes() if md5_path.exists() else fetch_small(MD5_URL)
        expected_match = re.search(rb"\b([0-9a-fA-F]{32})\b", sidecar)
        if expected_match is None:
            raise RuntimeError(f"Could not parse the published MD5 from {MD5_URL}")
        digest = file_md5(path)
        if digest.lower() != expected_match.group(1).decode("ascii").lower():
            raise RuntimeError(f"Existing extract failed Geofabrik MD5 verification: {path}")
        if not md5_path.exists():
            md5_path.write_bytes(sidecar)
        print(f"Using verified existing extract: {path} ({path.stat().st_size} bytes)")
        return digest

    # Confirm the publisher's checksum before transferring the larger PBF.
    sidecar = fetch_small(MD5_URL)
    expected_match = re.search(rb"\b([0-9a-fA-F]{32})\b", sidecar)
    if expected_match is None:
        raise RuntimeError(f"Could not parse the published MD5 from {MD5_URL}")
    expected_md5 = expected_match.group(1).decode("ascii").lower()
    print(f"Downloading pinned Geofabrik extract ({EXPECTED_BYTES:,} bytes; about 235.8 MiB): {PBF_URL}", flush=True)
    part = path.with_suffix(path.suffix + ".part")
    offset = part.stat().st_size if part.exists() else 0
    if offset > EXPECTED_BYTES:
        raise RuntimeError(f"Partial download is larger than the expected extract: {part}")
    digest = hashlib.md5(usedforsecurity=False)
    if offset:
        with part.open("rb") as existing:
            for chunk in iter(lambda: existing.read(1024 * 1024), b""):
                digest.update(chunk)
        print(f"Resuming verified-source transfer at byte {offset:,} of {EXPECTED_BYTES:,}", flush=True)
    headers = {"User-Agent": "ThermoScope academic OSM pilot"}
    if offset:
        headers["Range"] = f"bytes={offset}-"
    request = Request(PBF_URL, headers=headers)
    received = offset
    next_notice = ((offset // (25 * 1024 * 1024)) + 1) * (25 * 1024 * 1024)
    try:
        with urlopen(request, timeout=180) as response:
            status = response.getcode()
            if offset and status != 206:
                raise RuntimeError(f"Geofabrik did not honor resume range (HTTP {status}); partial file was preserved")
            if not offset and status != 200:
                raise RuntimeError(f"Unexpected Geofabrik response status: HTTP {status}")
            content_length = response.headers.get("Content-Length")
            expected_remaining = EXPECTED_BYTES - offset
            if content_length and int(content_length) != expected_remaining:
                raise RuntimeError(f"Geofabrik Content-Length changed: expected {expected_remaining}, received {content_length}")
            content_range = response.headers.get("Content-Range")
            if offset and content_range and not content_range.startswith(f"bytes {offset}-"):
                raise RuntimeError(f"Geofabrik returned an unexpected Content-Range: {content_range}")
            with part.open("ab" if offset else "wb") as target:
                while True:
                    chunk = response.read1(1024 * 1024)
                    if not chunk:
                        break
                    target.write(chunk)
                    target.flush()
                    digest.update(chunk)
                    received += len(chunk)
                    if received >= next_notice:
                        print(f"Downloaded {received:,} of {EXPECTED_BYTES:,} bytes", flush=True)
                        next_notice += 25 * 1024 * 1024
        if received != EXPECTED_BYTES:
            raise RuntimeError(f"Incomplete Geofabrik download: expected {EXPECTED_BYTES} bytes, received {received}; partial file retained for resume")
        actual_md5 = digest.hexdigest()
        if actual_md5.lower() != expected_md5:
            raise RuntimeError(f"Geofabrik MD5 mismatch: expected {expected_md5}, received {actual_md5}")
        path.parent.mkdir(parents=True, exist_ok=True)
        part.replace(path)
        md5_path.write_bytes(sidecar)
        return actual_md5
    except (HTTPError, URLError) as exc:
        if part.exists():
            part.unlink()
        raise RuntimeError(f"Geofabrik PBF download failed: {exc}") from exc
    except Exception:
        if part.exists():
            part.unlink()
        raise


def tag_dict(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return value
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def feature_groups(tags: dict[str, object]) -> list[str]:
    groups: set[str] = set()
    if tags.get("landuse") == "industrial":
        groups.add("industrial_landuse")
    if "industrial" in tags or tags.get("building") in {"industrial", "factory", "works", "boiler_house"} or tags.get("man_made") == "works":
        groups.add("industrial_facility")
    if "power" in tags or "plant" in tags or any(key.startswith("generator:") for key in tags):
        groups.add("power_infrastructure")
    if tags.get("landuse") == "quarry" or tags.get("man_made") in {"mine", "mineshaft", "adit"}:
        groups.add("mining_extraction")
    if tags.get("man_made") in {"flare", "chimney", "storage_tank", "gasometer", "works"}:
        groups.add("industrial_structure")
    if tags.get("railway") in {"industrial", "yard", "spur", "siding"}:
        groups.add("industrial_rail")
    if tags.get("landuse") == "landfill" or tags.get("amenity") in {"waste_disposal", "waste_transfer_station", "recycling"}:
        groups.add("waste_facility")
    if tags.get("landuse") in {"forest", "farmland", "grass", "meadow", "orchard", "vineyard", "plant_nursery"} or tags.get("natural") in {"wood", "scrub", "heath", "grassland", "wetland", "shrubbery"} or tags.get("landcover") in {"trees", "grass", "scrub", "wetland", "cropland"}:
        groups.add("vegetation_context")
    return sorted(groups)


def process_extract(pbf_path: Path, output_path: Path, manifest_path: Path, overwrite: bool, md5: str | None) -> None:
    try:
        import geopandas as gpd
        import pyogrio
        from shapely.geometry import box
    except ImportError as exc:
        raise RuntimeError("OSM processing needs the project's GeoPandas, Shapely, and Pyogrio packages") from exc
    if pyogrio.list_drivers(read=True).get("OSM") != "r":
        raise RuntimeError("The installed GDAL/Pyogrio build has no readable OSM driver; no alternate source was used")
    if not pbf_path.exists():
        raise RuntimeError(f"OSM extract not found: {pbf_path}. Use --download to fetch the pinned Geofabrik extract.")
    if md5 is None:
        md5 = file_md5(pbf_path)
    if (output_path.exists() or manifest_path.exists()) and not overwrite:
        raise RuntimeError(f"Generated output already exists; use --overwrite to replace only {output_path.name} and {manifest_path.name}")
    if overwrite:
        for path in (output_path, manifest_path):
            if path.exists():
                path.unlink()

    bounds_geom = box(*BOUNDS)
    layer_counts: dict[str, dict[str, int]] = {}
    total_features = 0
    temp_dir_path = Path(tempfile.mkdtemp(prefix="thermoscope_gdal_", dir=pbf_path.parent))
    config_path = pbf_path.parent / "osmconf_pilot.ini"
    config_path.write_text(OSM_CONFIG, encoding="utf-8")
    config_keys = {"OSM_CONFIG_FILE": str(config_path), "OGR_INTERLEAVED_READING": "YES", "OSM_MAX_TMPFILE_SIZE": "256", "CPL_TMPDIR": str(temp_dir_path)}
    previous = {key: pyogrio.get_gdal_config_option(key) for key in config_keys}
    try:
        pyogrio.set_gdal_config_options(config_keys)
        available_layers = {str(row[0]) for row in pyogrio.list_layers(pbf_path)}
        for source_layer in LAYERS:
            if source_layer not in available_layers:
                continue
            frame = pyogrio.read_dataframe(
                pbf_path,
                layer=source_layer,
                bbox=BOUNDS,
                use_arrow=False,
                INTERLEAVED_READING="YES",
            )
            if frame.empty or "all_tags" not in frame.columns:
                layer_counts[source_layer] = {"bbox_candidates": len(frame), "kept": 0}
                continue
            frame = frame.loc[frame.geometry.notna() & frame.geometry.intersects(bounds_geom)].copy()
            parsed = frame["all_tags"].map(tag_dict)
            groups = parsed.map(feature_groups)
            keep = groups.map(bool)
            frame = frame.loc[keep].copy()
            if frame.empty:
                layer_counts[source_layer] = {"bbox_candidates": int(len(parsed)), "kept": 0}
                continue
            frame["source_layer"] = source_layer
            frame["feature_groups"] = groups.loc[keep].map(lambda values: json.dumps(values, ensure_ascii=False))
            # Keep full OSM geometries (including parts extending beyond the bbox); the
            # spatial selection is bbox intersection, not geometry clipping.
            pyogrio.write_dataframe(
                frame,
                output_path,
                layer=f"osm_{source_layer}",
                driver="GPKG",
                geometry_type="Unknown",
                append=output_path.exists(),
                layer_metadata={"source": "OpenStreetMap via Geofabrik", "selection_bbox_wgs84": json.dumps(BOUNDS)},
            )
            layer_counts[source_layer] = {"bbox_candidates": int(len(parsed)), "kept": int(len(frame))}
            total_features += len(frame)
    finally:
        pyogrio.set_gdal_config_options(previous)
        config_path.unlink(missing_ok=True)
        shutil.rmtree(temp_dir_path, ignore_errors=True)

    if total_features == 0:
        raise RuntimeError("No relevant tagged OSM features were found in the pilot bounding box; no labels were created")
    source_bytes = pbf_path.stat().st_size
    sha256 = hashlib.sha256()
    with pbf_path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            sha256.update(chunk)
    manifest = {
        "source": "OpenStreetMap contributors, downloaded from Geofabrik",
        "source_url": PBF_URL,
        "source_md5_url": MD5_URL,
        "source_extract_snapshot": "eastern-zone-261016; OSM data through 2026-10-16 per Geofabrik",
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "license": "Open Database License (ODbL) 1.0; attribute OpenStreetMap contributors",
        "raw_file": str(pbf_path.relative_to(pbf_path.parents[3])).replace("\\", "/"),
        "raw_size_bytes": source_bytes,
        "raw_md5": md5,
        "raw_sha256": sha256.hexdigest(),
        "pilot_bbox_wgs84": {"west": BOUNDS[0], "south": BOUNDS[1], "east": BOUNDS[2], "north": BOUNDS[3]},
        "filter_method": "GDAL OSM/PBF reader bbox selection followed by exact geometry intersection and local tag-category filtering; Overpass was not used.",
        "retained_geometry": "Original full feature geometries are retained; features crossing the pilot bbox are not clipped.",
        "tag_preservation": "GDAL all_tags JSON field retains source OSM tags on selected features; osm_id and source geometry layer are retained.",
        "retained_feature_groups": ["industrial_landuse", "industrial_facility", "power_infrastructure", "mining_extraction", "industrial_structure", "industrial_rail", "waste_facility", "vegetation_context"],
        "output_file": str(output_path.relative_to(output_path.parents[3])).replace("\\", "/"),
        "feature_count": total_features,
        "counts_by_source_layer": layer_counts,
        "limitations": ["OSM coverage and tagging are incomplete and uneven.", "The extract is a snapshot, not historical OSM for each FIRMS acquisition date.", "Spatial proximity is supporting evidence, not causal proof."],
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {total_features} tagged OSM features to {output_path}")
    print(f"Manifest: {manifest_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--download", action="store_true", help="download the pinned 235.8 MiB extract, then process it")
    action.add_argument("--process-only", action="store_true", help="process the already-downloaded pinned PBF")
    parser.add_argument("--overwrite", action="store_true", help="replace only the generated PBF/GPKG/manifest targets")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    raw_dir, processed_dir = repo / "data" / "raw" / "osm", repo / "data" / "processed" / "osm"
    pbf_path, md5_path = raw_dir / RAW_PBF_NAME, raw_dir / RAW_MD5_NAME
    output_path, manifest_path = processed_dir / OUTPUT_NAME, processed_dir / MANIFEST_NAME
    raw_dir.mkdir(parents=True, exist_ok=True)
    processed_dir.mkdir(parents=True, exist_ok=True)
    md5 = None
    if args.download:
        md5 = download_extract(pbf_path, md5_path, args.overwrite)
    process_extract(pbf_path, output_path, manifest_path, args.overwrite, md5)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
