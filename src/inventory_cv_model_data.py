"""Create a checksum and raster-metadata inventory of local CV imagery.

The script is read-only with respect to source rasters and refuses to overwrite
its CSV output. It does not download data or assign labels.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd
import rasterio

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "docs/cv_model_dataset_inventory.csv"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _path_key(value: object, root: Path) -> str:
    path = Path(str(value).replace("\\", "/"))
    if not path.is_absolute():
        path = root / path
    return str(path.resolve()).casefold()


def _metadata_maps(root: Path) -> tuple[dict[str, dict], dict[str, dict], dict[str, dict]]:
    manifest_path = root / "data/processed/cv_dataset/manifest.csv"
    weak_path = root / "data/processed/cv_dataset/worldcover_weak_alignment_v001/weak_sample_manifest.csv"
    reference_path = root / "data/raw/cv_reference/worldcover_2021_sample_validated/sample_manifest.csv"
    image, weak, reference = {}, {}, {}
    if manifest_path.is_file():
        for row in pd.read_csv(manifest_path).to_dict("records"):
            for column in ("chip_path", "duplicate_chip_paths_json", "scl_path"):
                raw = row.get(column)
                paths = []
                if column == "duplicate_chip_paths_json" and isinstance(raw, str) and raw:
                    try:
                        paths = json.loads(raw)
                    except json.JSONDecodeError:
                        paths = []
                elif isinstance(raw, str) and raw and raw.lower() != "nan":
                    paths = [raw]
                for value in paths:
                    image[_path_key(value, root)] = row
    if weak_path.is_file():
        for row in pd.read_csv(weak_path).to_dict("records"):
            for column in ("weak_mask_path", "scl_path", "chip_path"):
                raw = row.get(column)
                if isinstance(raw, str) and raw and raw.lower() != "nan":
                    weak[_path_key(raw, root)] = row
    if reference_path.is_file():
        for row in pd.read_csv(reference_path).to_dict("records"):
            raw = row.get("sample_path")
            if isinstance(raw, str) and raw:
                reference[_path_key(raw, root)] = row
    return image, weak, reference


def inventory(root: Path = ROOT) -> pd.DataFrame:
    image_meta, weak_meta, reference_meta = _metadata_maps(root)
    paths = sorted(
        [* (root / "data/processed").rglob("*.tif"), * (root / "data/processed").rglob("*.tiff"),
         * (root / "data/raw/cv_reference").rglob("*.tif"), * (root / "data/raw/cv_reference").rglob("*.tiff")],
        key=lambda p: p.as_posix().casefold(),
    )
    rows = []
    for path in paths:
        key = str(path.resolve()).casefold()
        image = image_meta.get(key, {})
        weak = weak_meta.get(key, {})
        reference = reference_meta.get(key, {})
        with rasterio.open(path) as src:
            bounds = list(map(float, src.bounds))
            crs = src.crs.to_string() if src.crs else ""
            width, height, count = src.width, src.height, src.count
            dtype = ";".join(src.dtypes)
            pixel_size = list(map(float, src.res))
            tags = src.tags()
        if reference:
            kind = "worldcover_2021_reference_window"
            label_status = "weak_reference_source_not_ground_truth"
            provenance = "ESA WorldCover 2021 v200; CC BY 4.0"
            acquisition = str(reference.get("reference_year", "2021"))
            scene_id = str(reference.get("worldcover_tile", ""))
        elif weak and ("weak_mask_path" in weak and _path_key(weak.get("weak_mask_path"), root) == key):
            kind = "worldcover_weak_mask"
            label_status = "weak_worldcover_2021_mask_not_independent_truth"
            provenance = "Nearest-neighbor alignment of ESA WorldCover 2021 v200; SCL clear classes 4/5/6"
            acquisition = str(weak.get("chip_date", ""))
            scene_id = str(weak.get("chip_scene_id", ""))
        elif count == 4:
            kind = "sentinel2_multispectral_chip"
            label_status = str(image.get("label_status", "unlabelled"))
            provenance = "ESA/Copernicus Sentinel-2 L2A investigation chip; B04/B03/B02/B11"
            acquisition = str(image.get("acquisition_date", ""))
            scene_id = str(image.get("scene_item_id", ""))
        elif "scl" in path.name.lower() or str(tags.get("AREA_OR_POINT", "")).lower() == "area" and "scl" in path.stem.lower():
            kind = "sentinel2_scene_classification_layer"
            label_status = "quality_mask_not_target_label"
            provenance = "Sentinel-2 SCL; cloud/shadow/land masking only"
            acquisition = str(image.get("acquisition_date", weak.get("chip_date", "")))
            scene_id = str(image.get("scene_item_id", weak.get("chip_scene_id", "")))
        elif "worldcover" in path.name.lower():
            kind = "worldcover_2021_reference_window"
            label_status = "weak_reference_source_not_ground_truth"
            provenance = "ESA WorldCover 2021 v200; CC BY 4.0"
            acquisition = "2021"
            scene_id = str(tags.get("source_tile", ""))
        else:
            kind = "other_single_band_raster"
            label_status = "not_a_training_label"
            provenance = "See source run manifest and raster tags"
            acquisition = ""
            scene_id = ""
        rows.append({
            "relative_path": path.relative_to(root).as_posix(),
            "file_size_bytes": path.stat().st_size,
            "sha256": sha256_file(path),
            "content_duplicate_group_sha256": sha256_file(path),
            "raster_kind": kind,
            "width": width, "height": height, "band_count": count,
            "data_types": dtype, "crs": crs,
            "pixel_size": json.dumps(pixel_size),
            "bounds_in_raster_crs": json.dumps(bounds),
            "acquisition_date_or_reference_year": acquisition,
            "scene_or_reference_tile_id": scene_id,
            "label_status": label_status,
            "provenance": provenance,
        })
    return pd.DataFrame(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    root = args.root.resolve()
    output = args.output if args.output.is_absolute() else root / args.output
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite existing inventory: {output}")
    frame = inventory(root)
    output.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output, index=False)
    print(f"Inventoried {len(frame)} local rasters ({frame.file_size_bytes.sum():,} bytes) to {output}")
    print(frame.groupby(["raster_kind", "label_status"], dropna=False).size().to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
