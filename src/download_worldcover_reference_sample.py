"""Download tiny, chip-footprint WorldCover 2021 reference windows.

This creates raw categorical map crops only. It does not align masks to
Sentinel-2 pixels, assign class labels to image chips, or approve samples.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from rasterio.windows import Window, from_bounds
from rasterio.warp import transform_bounds


BASE_URL = "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/ESA_WorldCover_10m_2021_v200_"
VALID_CODES = {0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 95, 100}
REQUIRED_COLUMNS = {"sample_id", "chip_path", "chip_sha256", "image_acquisition_date"}


def worldcover_tile_for_bounds(bounds: tuple[float, float, float, float]) -> str:
    """Return the 3x3 degree ESA tile containing bounds; reject tile crossings."""
    west, south, east, north = bounds
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise ValueError(f"Invalid WGS84 bounds: {bounds}")
    tile_west = math.floor(west / 3) * 3
    tile_south = math.floor(south / 3) * 3
    eps = 1e-10
    if east > tile_west + 3 + eps or north > tile_south + 3 + eps:
        raise ValueError("Chip bounds cross an ESA WorldCover 3-degree tile edge")
    return f"N{tile_south:02d}E{tile_west:03d}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _head(url: str) -> dict[str, str]:
    request = urllib.request.Request(url, method="HEAD")
    with urllib.request.urlopen(request, timeout=30) as response:
        return {
            "content_length": response.headers.get("Content-Length", ""),
            "etag": response.headers.get("ETag", ""),
            "last_modified": response.headers.get("Last-Modified", ""),
            "accept_ranges": response.headers.get("Accept-Ranges", ""),
        }


def download_sample(register: pd.DataFrame, output_dir: Path) -> tuple[pd.DataFrame, dict]:
    missing = REQUIRED_COLUMNS - set(register.columns)
    if missing:
        raise ValueError(f"Review register missing required columns: {sorted(missing)}")
    if output_dir.exists():
        raise FileExistsError(f"Refusing to overwrite existing sample directory: {output_dir}")
    if register.empty or register["sample_id"].duplicated().any():
        raise ValueError("Register must contain unique sample IDs")

    output_dir.mkdir(parents=True)
    out_rows = []
    tile_meta: dict[str, dict] = {}
    opened: dict[str, rasterio.io.DatasetReader] = {}
    try:
        for row in register.itertuples(index=False):
            chip_path = Path(row.chip_path)
            if not chip_path.is_file():
                raise FileNotFoundError(f"Sentinel chip does not exist: {chip_path}")
            with rasterio.open(chip_path) as chip:
                bounds = transform_bounds(chip.crs, "EPSG:4326", *chip.bounds, densify_pts=21)
                wc_bounds = (bounds[0], bounds[1], bounds[2], bounds[3])
                tile_id = worldcover_tile_for_bounds(wc_bounds)
                url = f"{BASE_URL}{tile_id}_Map.tif"
                if url not in opened:
                    head = _head(url)
                    if head["accept_ranges"].lower() != "bytes" or not head["content_length"]:
                        raise RuntimeError(f"COG range access/size unavailable for {url}")
                    opened[url] = rasterio.open("/vsicurl/" + url)
                    src = opened[url]
                    if src.crs is None or src.crs.to_epsg() != 4326 or src.count != 1 or src.dtypes[0] != "uint8":
                        raise ValueError(f"Unexpected WorldCover COG schema for {tile_id}")
                    if src.width != 36000 or src.height != 36000:
                        raise ValueError(f"Unexpected WorldCover tile dimensions for {tile_id}: {src.width}x{src.height}")
                    tile_meta[tile_id] = {
                        "url": url,
                        "content_length_bytes": int(head["content_length"]),
                        "etag": head["etag"],
                        "last_modified": head["last_modified"],
                        "accept_ranges": head["accept_ranges"],
                        "crs": src.crs.to_string(),
                        "resolution_degrees": list(src.res),
                        "source_block_shape": list(src.block_shapes[0]),
                    }
                src = opened[url]
                src_bounds = (src.bounds.left, src.bounds.bottom, src.bounds.right, src.bounds.top)
                if not (src_bounds[0] <= wc_bounds[0] and src_bounds[1] <= wc_bounds[1]
                        and src_bounds[2] >= wc_bounds[2] and src_bounds[3] >= wc_bounds[3]):
                    raise ValueError(f"Chip footprint outside selected COG {tile_id}: {wc_bounds}")
                float_window = from_bounds(*wc_bounds, transform=src.transform)
                col0, row0 = math.floor(float_window.col_off), math.floor(float_window.row_off)
                col1 = math.ceil(float_window.col_off + float_window.width)
                row1 = math.ceil(float_window.row_off + float_window.height)
                window = Window(col0, row0, col1 - col0, row1 - row0)
                values = src.read(1, window=window)
                unexpected = set(np.unique(values).tolist()) - VALID_CODES
                if unexpected:
                    raise ValueError(f"Unexpected WorldCover class codes: {sorted(unexpected)}")

                filename = f"{row.sample_id}_{tile_id}_worldcover_2021_v200.tif"
                dest = output_dir / filename
                profile = src.profile.copy()
                profile.update(
                    driver="GTiff", width=values.shape[1], height=values.shape[0],
                    transform=src.window_transform(window), compress="DEFLATE",
                    predictor=1, tiled=False, nodata=0,
                )
                with rasterio.open(dest, "w", **profile) as dst:
                    dst.write(values, 1)
                    dst.update_tags(
                        source="ESA WorldCover 2021 v200", source_tile=tile_id,
                        source_url=url, reference_year="2021", label_role="weak_reference_only",
                        license="CC BY 4.0", sentinel_chip_id=str(row.sample_id),
                        sentinel_acquisition_date=str(row.image_acquisition_date),
                        warning="Not a verified label; do not infer industrial, mine, or fire class.",
                    )
                with rasterio.open(dest) as check:
                    if check.crs.to_epsg() != 4326 or check.count != 1 or check.dtypes[0] != "uint8":
                        raise RuntimeError(f"Written sample validation failed: {dest}")
                    sample_bounds = check.bounds
                    if (check.shape != values.shape
                            or sample_bounds.left > wc_bounds[0]
                            or sample_bounds.bottom > wc_bounds[1]
                            or sample_bounds.right < wc_bounds[2]
                            or sample_bounds.top < wc_bounds[3]):
                        raise RuntimeError(f"Sample does not overlap target chip: {dest}")
                class_counts = {str(int(k)): int(v) for k, v in zip(*np.unique(values, return_counts=True))}
                out_rows.append({
                    "sample_id": row.sample_id,
                    "chip_path": str(chip_path),
                    "chip_sha256": row.chip_sha256,
                    "sentinel_acquisition_date": row.image_acquisition_date,
                    "reference_year": 2021,
                    "temporal_gap_years": 2026 - 2021,
                    "worldcover_tile": tile_id,
                    "source_url": url,
                    "source_wgs84_bounds": json.dumps([round(float(v), 9) for v in wc_bounds]),
                    "sample_path": str(dest).replace("\\", "/"),
                    "sample_sha256": _sha256(dest),
                    "sample_size_bytes": dest.stat().st_size,
                    "width": values.shape[1],
                    "height": values.shape[0],
                    "crs": src.crs.to_string(),
                    "pixel_size_degrees": json.dumps(list(src.res)),
                    "class_counts_json": json.dumps(class_counts, sort_keys=True),
                    "label_role": "weak_reference_only_not_chip_label",
                })
    except Exception:
        # Keep any completed raw downloads for inspection; never silently remove data.
        raise
    finally:
        for dataset in opened.values():
            dataset.close()

    manifest = pd.DataFrame(out_rows)
    manifest.to_csv(output_dir / "sample_manifest.csv", index=False)
    provenance = {
        "source": "ESA WorldCover 10 m 2021 v200",
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "license": "CC BY 4.0",
        "attribution": "© ESA WorldCover project 2021 / Contains modified Copernicus Sentinel data (2021) processed by ESA WorldCover consortium",
        "citation_doi": "10.5281/zenodo.7254221",
        "sample_count": len(manifest),
        "source_tiles": tile_meta,
        "sample_files_total_bytes": int(manifest.sample_size_bytes.sum()),
        "source_transfer_bytes": "See GDAL HTTP range logs; HEAD length is not a download.",
        "method": "read only source COG windows intersecting six existing chip footprints; no full tile download; no resampling or target labels produced",
        "limits": [
            "2021 map is a weak reference for 2026 imagery, not independent 2026 ground truth",
            "WorldCover is derived from Sentinel-1 and Sentinel-2; same-family source dependence applies",
            "generic built-up and bare classes do not mean industrial or mining",
            "no FIRMS or OSM field is used as a target label",
        ],
    }
    (output_dir / "provenance.json").write_text(json.dumps(provenance, indent=2), encoding="utf-8")
    return manifest, provenance


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--register", default="data/processed/cv_dataset/reference_review_register.csv")
    parser.add_argument("--output-dir", default="data/raw/cv_reference/worldcover_2021_sample_validated")
    args = parser.parse_args()
    register_path, output_dir = Path(args.register), Path(args.output_dir)
    if not register_path.is_file():
        parser.error(f"Review register not found: {register_path}")
    manifest, _ = download_sample(pd.read_csv(register_path), output_dir)
    print(f"Wrote {len(manifest)} source-grid weak-reference crops to {output_dir}")
    print(f"Cropped file bytes: {manifest.sample_size_bytes.sum()}; no Sentinel labels or masks generated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
