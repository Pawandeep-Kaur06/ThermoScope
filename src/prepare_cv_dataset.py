"""Build a local, deduplicated manifest of existing Sentinel-2 CV candidate chips.

This inventory does not assign ground-truth labels, create negatives, copy imagery,
or designate train/validation/test splits. It only reads local GeoTIFFs and metadata.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Iterable

import numpy as np
import rasterio
from rasterio.warp import transform

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.regions import get_region, tile_for_coordinate

DEFAULT_INPUT_ROOTS = [ROOT / "data" / "processed"]
DEFAULT_OUTPUT = ROOT / "data" / "processed" / "cv_dataset" / "manifest.csv"
SCENE_RE = re.compile(r"(S2[ABC]_[A-Z0-9]+_\d{8}_\d+_L2A)")
BANDS = ["B04_red_10m", "B03_green_10m", "B02_blue_10m", "B11_swir16_native20m_resampled10m"]
SCL_CLEAR_CLASSES = {4, 5, 6}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def relative_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _read_scene_metadata(roots: Iterable[Path]) -> dict[str, dict]:
    metadata: dict[str, dict] = {}
    hashes: dict[Path, str] = {}
    for root in roots:
        for path in root.rglob("scene_metadata.csv"):
            try:
                with path.open(newline="", encoding="utf-8-sig") as handle:
                    for row in csv.DictReader(handle):
                        item = (row.get("selected_stac_item") or row.get("item_id") or "").strip()
                        if item:
                            # Prefer the most complete record but keep source paths in the manifest.
                            current = metadata.get(item, {})
                            hashes.setdefault(path, sha256(path))
                            metadata[item] = {
                                **current,
                                **{k: v for k, v in row.items() if v not in (None, "")},
                                "_metadata_path": relative_path(path),
                                "_metadata_sha256": hashes[path],
                            }
            except (OSError, csv.Error):
                continue
    return metadata


def _leakage_groups(records: list[dict]) -> list[str]:
    """Connected components joining chips that share a scene OR spatial tile."""
    parent = list(range(len(records)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    owners: dict[tuple[str, str], int] = {}
    for i, record in enumerate(records):
        for key in ("scene_item_id", "spatial_group_id"):
            value = record.get(key, "")
            if value:
                prior = owners.setdefault((key, value), i)
                union(i, prior)
    members: dict[int, list[str]] = defaultdict(list)
    for i, record in enumerate(records):
        members[find(i)].append(record["chip_sha256"])
    ids = {root: "geo_scene_" + hashlib.sha256("|".join(sorted(values)).encode()).hexdigest()[:16]
           for root, values in members.items()}
    return [ids[find(i)] for i in range(len(records))]


def build_manifest(input_roots: Iterable[Path | str], region_id: str = "jharkhand") -> list[dict]:
    roots = [Path(root).resolve() for root in input_roots]
    for root in roots:
        if not root.exists():
            raise FileNotFoundError(f"Input imagery root does not exist: {root}")
    region = get_region(region_id)
    metadata = _read_scene_metadata(roots)
    groups: dict[str, list[Path]] = defaultdict(list)
    for root in roots:
        for chip in sorted(root.rglob("*_4band_10m.tif")):
            groups[sha256(chip)].append(chip)

    records: list[dict] = []
    for digest, copies in sorted(groups.items()):
        copies = sorted(copies, key=lambda p: p.as_posix().casefold())
        primary = copies[0]
        match = SCENE_RE.search(primary.name)
        scene_id = match.group(1) if match else ""
        scene_meta = metadata.get(scene_id, {})
        try:
            with rasterio.open(primary) as ds:
                if ds.count != 4:
                    continue
                center_x = (ds.bounds.left + ds.bounds.right) / 2
                center_y = (ds.bounds.bottom + ds.bounds.top) / 2
                lon_values, lat_values = transform(ds.crs, "EPSG:4326", [center_x], [center_y])
                longitude, latitude = float(lon_values[0]), float(lat_values[0])
                tile = tile_for_coordinate(longitude, latitude, region)
                mask = ds.read_masks()
                valid_fraction = float(np.all(mask > 0, axis=0).mean())
                width, height, crs, dtypes, resolution = ds.width, ds.height, ds.crs, ds.dtypes, ds.res
                image_bytes = primary.stat().st_size
        except Exception as exc:
            raise ValueError(f"Could not inspect raster {primary}: {exc}") from exc

        scl_candidates = []
        for image_path in copies:
            candidate = image_path.with_name(image_path.name.replace("_4band_10m.tif", "_scl_10m.tif"))
            if candidate.is_file():
                scl_candidates.append(candidate)
        scl_path = sorted(scl_candidates, key=lambda p: p.as_posix().casefold())[0] if scl_candidates else None
        scl_valid_fraction = clear_fraction = None
        scl_hash = ""
        if scl_path:
            scl_hash = sha256(scl_path)
            with rasterio.open(scl_path) as scl:
                values = scl.read(1)
                valid = (scl.read_masks(1) > 0) & (values > 0)
                scl_valid_fraction = float(valid.mean())
                clear_fraction = float(np.isin(values[valid], list(SCL_CLEAR_CLASSES)).mean()) if valid.any() else None

        datetime = scene_meta.get("scene_datetime_utc", "")
        date = (datetime[:10] if len(datetime) >= 10 else
                (scene_id.split("_")[2][:4] + "-" + scene_id.split("_")[2][4:6] + "-" + scene_id.split("_")[2][6:8]
                 if scene_id and len(scene_id.split("_")) > 2 else ""))
        records.append({
            "chip_id": "s2_" + digest[:16],
            "chip_path": relative_path(primary),
            "duplicate_chip_paths_json": json.dumps([relative_path(p) for p in copies], separators=(",", ":")),
            "duplicate_copy_count": len(copies) - 1,
            "chip_sha256": digest,
            "file_size_bytes": image_bytes,
            "sensor": scene_meta.get("sensor", "Sentinel-2; sensor inferred from item ID" if scene_id else "Sentinel-2; item ID unavailable"),
            "scene_item_id": scene_id,
            "scene_datetime_utc": datetime,
            "acquisition_date": date,
            "scene_metadata_path": scene_meta.get("_metadata_path", ""),
            "scene_metadata_sha256": scene_meta.get("_metadata_sha256", ""),
            "stac_catalog_url": scene_meta.get("catalog_url", ""),
            "stac_asset_urls_json": scene_meta.get("asset_urls", ""),
            "scene_cloud_cover_percent": scene_meta.get("eo_cloud_cover_percent_scene_level", ""),
            "chip_width_pixels": width,
            "chip_height_pixels": height,
            "band_count": 4,
            "band_order_json": json.dumps(BANDS, separators=(",", ":")),
            "band_data_types_json": json.dumps(list(dtypes), separators=(",", ":")),
            "native_pixel_size_x_m": abs(float(resolution[0])),
            "native_pixel_size_y_m": abs(float(resolution[1])),
            "crs": str(crs),
            "center_longitude_wgs84": longitude,
            "center_latitude_wgs84": latitude,
            "region_id": region_id,
            "tile_id": tile["tile_id"] if tile else "outside_configured_region",
            "spatial_group_id": tile["tile_id"] if tile else f"outside_{latitude:.2f}_{longitude:.2f}",
            "image_valid_pixel_fraction": valid_fraction,
            "scl_path": relative_path(scl_path) if scl_path else "",
            "scl_sha256": scl_hash,
            "scl_valid_pixel_fraction": scl_valid_fraction,
            "scl_clear_fraction_of_valid_pixels": clear_fraction,
            "label_class": "",
            "label_status": "unlabelled",
            "label_source": "",
            "label_rationale": "No independent image-level reference label is available locally.",
            "independent_label_verified": False,
            "is_training_sample": False,
            "dataset_split": "unassigned_no_credible_labels",
        })
    for record, group_id in zip(records, _leakage_groups(records)):
        record["geo_scene_leakage_group"] = group_id
    return records


def write_manifest(records: list[dict], output_path: Path) -> None:
    if output_path.exists():
        raise FileExistsError(f"Refusing to overwrite existing CV dataset manifest: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not records:
        raise ValueError("No valid four-band Sentinel-2 chips found in the input roots")
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", action="append", type=Path, help="Local root to scan; repeat as needed (default: data/processed)")
    parser.add_argument("--region", default="jharkhand")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    roots = args.input_root or DEFAULT_INPUT_ROOTS
    output = args.output if args.output.is_absolute() else ROOT / args.output
    records = build_manifest(roots, args.region)
    write_manifest(records, output)
    print(json.dumps({"manifest": relative_path(output), "unique_image_chips": len(records),
                      "distinct_scene_ids": len({r['scene_item_id'] for r in records if r['scene_item_id']}),
                      "labelled_samples": sum(bool(r['independent_label_verified']) for r in records)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
