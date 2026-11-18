"""Align WorldCover weak classes to existing Sentinel-2 chips and SCL-mask them.

Outputs are explicitly weak reference masks. This script never trains a model,
assigns independent labels, or creates random train/validation/test splits.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from rasterio.warp import reproject, Resampling


WORLD_COVER_TO_TARGET = {10: 1, 20: 1, 30: 1, 40: 2, 50: 3, 60: 4, 80: 5}
TARGET_CLASSES = {
    1: "vegetation",
    2: "cropland",
    3: "built_up",
    4: "bare_sparse",
    5: "water",
}
IGNORE = 255
CLEAR_SCL_CODES = (4, 5, 6)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def reproject_to_chip_grid(
    source_path: Path,
    destination_crs,
    destination_transform,
    width: int,
    height: int,
    *,
    destination_nodata: int = 0,
) -> tuple[np.ndarray, dict]:
    """Nearest-neighbor align a categorical raster to one chip's exact grid."""
    with rasterio.open(source_path) as source:
        if source.count != 1 or source.crs is None:
            raise ValueError(f"Expected a georeferenced single-band raster: {source_path}")
        array = np.full((height, width), destination_nodata, dtype=source.dtypes[0])
        reproject(
            source=rasterio.band(source, 1),
            destination=array,
            src_transform=source.transform,
            src_crs=source.crs,
            src_nodata=source.nodata,
            dst_transform=destination_transform,
            dst_crs=destination_crs,
            dst_nodata=destination_nodata,
            resampling=Resampling.nearest,
        )
        metadata = {
            "source_crs": source.crs.to_string(),
            "source_transform": list(source.transform)[:6],
            "source_resolution": list(source.res),
            "source_width": source.width,
            "source_height": source.height,
            "source_nodata": source.nodata,
        }
    return array, metadata


def make_weak_mask(
    worldcover_codes: np.ndarray,
    scl_codes: np.ndarray,
    image_valid: np.ndarray,
    *,
    clear_scl_codes: tuple[int, ...] = CLEAR_SCL_CODES,
    class_map: dict[int, int] | None = None,
    ignore_value: int = IGNORE,
) -> np.ndarray:
    """Map broad WorldCover classes and ignore cloudy/invalid/unsupported pixels."""
    if worldcover_codes.shape != scl_codes.shape or worldcover_codes.shape != image_valid.shape:
        raise ValueError("WorldCover, SCL, and image-valid arrays must share one pixel grid")
    mapping = class_map or WORLD_COVER_TO_TARGET
    output = np.full(worldcover_codes.shape, ignore_value, dtype=np.uint8)
    valid = image_valid.astype(bool) & np.isin(scl_codes, clear_scl_codes)
    for source_code, target_code in mapping.items():
        output[valid & (worldcover_codes == source_code)] = target_code
    return output


def validate_group_split_separation(rows: pd.DataFrame) -> None:
    """Ensure connected geo/scene groups do not cross assigned partitions."""
    required = {"geo_scene_leakage_group", "dataset_split"}
    if not required.issubset(rows.columns):
        raise ValueError(f"Split table missing: {sorted(required - set(rows.columns))}")
    assigned = rows[~rows.dataset_split.isin(["unassigned", "unassigned_unlabelled", ""])]
    counts = assigned.groupby("geo_scene_leakage_group").dataset_split.nunique()
    if counts.gt(1).any():
        raise ValueError("A geography/scene leakage group is assigned to multiple splits")


def assess_grouped_split_feasibility(
    manifest: pd.DataFrame, *, minimum_pixels_per_group: int = 256
) -> dict:
    """Assess whether nontrivial labeled groups can populate independent splits."""
    group_totals = manifest.groupby("geo_scene_leakage_group").weak_label_pixels.sum()
    nonempty = group_totals[group_totals > 0]
    adequate = nonempty[nonempty >= minimum_pixels_per_group]
    class_groups: dict[str, int] = {}
    for class_name in TARGET_CLASSES.values():
        groups = 0
        for group, rows in manifest.groupby("geo_scene_leakage_group"):
            pixels = 0
            for value in rows.weak_label_pixel_counts_json:
                counts = json.loads(value)
                pixels += int(counts.get(class_name, 0))
            if pixels >= minimum_pixels_per_group:
                groups += 1
        class_groups[class_name] = groups
    return {
        "minimum_pixels_per_group": minimum_pixels_per_group,
        "groups_with_any_weak_labels": int(len(nonempty)),
        "groups_with_minimum_weak_pixels": int(len(adequate)),
        "grouped_train_test_feasible": bool(len(adequate) >= 2),
        "grouped_train_validation_test_feasible": bool(len(adequate) >= 3),
        "groups_with_at_least_minimum_pixels_per_class": class_groups,
    }


def build_weak_masks(register: pd.DataFrame, sample_manifest: pd.DataFrame, output_dir: Path):
    required_register = {
        "sample_id", "chip_path", "scene_item_id", "image_acquisition_date",
        "scl_path", "geo_scene_leakage_group", "tile_id",
    }
    required_samples = {"sample_id", "sample_path", "sample_sha256", "reference_year"}
    if required_register - set(register.columns):
        raise ValueError(f"Review register missing {sorted(required_register - set(register.columns))}")
    if required_samples - set(sample_manifest.columns):
        raise ValueError(f"Reference sample manifest missing {sorted(required_samples - set(sample_manifest.columns))}")
    if output_dir.exists():
        raise FileExistsError(f"Refusing to overwrite existing weak-mask output: {output_dir}")
    if register.sample_id.duplicated().any() or sample_manifest.sample_id.duplicated().any():
        raise ValueError("Sample IDs must be unique")
    output_dir.mkdir(parents=True)
    mask_dir = output_dir / "masks"
    mask_dir.mkdir()

    sample_lookup = sample_manifest.set_index("sample_id")
    manifest_rows = []
    for row in register.itertuples(index=False):
        if row.sample_id not in sample_lookup.index:
            raise ValueError(f"No WorldCover sample for chip {row.sample_id}")
        image_path, scl_path = Path(row.chip_path), Path(row.scl_path)
        source_path = Path(sample_lookup.loc[row.sample_id, "sample_path"])
        for path in (image_path, scl_path, source_path):
            if not path.is_file():
                raise FileNotFoundError(f"Required raster missing: {path}")
        with rasterio.open(image_path) as image:
            if image.count != 4:
                raise ValueError(f"Expected four-band Sentinel chip: {image_path}")
            image_valid = np.all(image.read_masks() > 0, axis=0)
            image_profile = image.profile.copy()
            worldcover, worldcover_meta = reproject_to_chip_grid(
                source_path, image.crs, image.transform, image.width, image.height,
                destination_nodata=0,
            )
            with rasterio.open(scl_path) as scl:
                scl_codes, scl_meta = reproject_to_chip_grid(
                    scl_path, image.crs, image.transform, image.width, image.height,
                    destination_nodata=0,
                )
                scl_valid = np.ones(scl_codes.shape, dtype=bool)
                # Treat SCL no-data as invalid even if its class code were altered.
                if scl.crs is None:
                    raise ValueError(f"SCL raster has no CRS: {scl_path}")
                scl_valid &= scl_codes != 0
            mask = make_weak_mask(worldcover, scl_codes, image_valid & scl_valid)

            mask_path = mask_dir / f"{row.sample_id}_worldcover_weak_mask.tif"
            profile = image_profile.copy()
            profile.update(driver="GTiff", count=1, dtype="uint8", nodata=IGNORE, compress="DEFLATE")
            with rasterio.open(mask_path, "w", **profile) as destination:
                destination.write(mask, 1)
                destination.update_tags(
                    reference="ESA WorldCover 2021 v200",
                    label_origin="worldcover_2021_weak_reference",
                    license="CC BY 4.0",
                    source_code_mapping=json.dumps(WORLD_COVER_TO_TARGET, sort_keys=True),
                    target_class_names=json.dumps(TARGET_CLASSES, sort_keys=True),
                    clear_scl_codes=",".join(str(x) for x in CLEAR_SCL_CODES),
                    temporal_warning="Reference year 2021; Sentinel chip is later. Not independent truth.",
                )
            pixel_counts = {
                TARGET_CLASSES[int(code)]: int((mask == code).sum())
                for code in TARGET_CLASSES
            }
            manifest_rows.append({
                "sample_id": row.sample_id,
                "chip_path": str(image_path).replace("\\", "/"),
                "chip_scene_id": row.scene_item_id,
                "chip_date": row.image_acquisition_date,
                "reference_source": "ESA WorldCover 2021 v200",
                "reference_year": int(sample_lookup.loc[row.sample_id, "reference_year"]),
                "reference_sample_path": str(source_path).replace("\\", "/"),
                "reference_sample_sha256": sample_lookup.loc[row.sample_id, "sample_sha256"],
                "weak_mask_path": str(mask_path).replace("\\", "/"),
                "weak_mask_sha256": sha256_file(mask_path),
                "width": image.width,
                "height": image.height,
                "crs": image.crs.to_string(),
                "pixel_size_m": json.dumps(list(image.res)),
                "image_valid_pixels": int(image_valid.sum()),
                "scl_clear_pixels": int((np.isin(scl_codes, CLEAR_SCL_CODES) & scl_valid).sum()),
                "weak_label_pixels": int((mask != IGNORE).sum()),
                "weak_label_pixel_counts_json": json.dumps(pixel_counts, sort_keys=True),
                "scl_path": str(scl_path).replace("\\", "/"),
                "geo_scene_leakage_group": row.geo_scene_leakage_group,
                "tile_id": row.tile_id,
                "dataset_split": "unassigned_no_feasible_split",
                "label_status": "weak_reference_only_not_verified",
                "worldcover_alignment": "nearest_neighbor_to_exact_chip_grid",
                "worldcover_source_crs": worldcover_meta["source_crs"],
                "scl_source_crs": scl_meta["source_crs"],
            })

    manifest = pd.DataFrame(manifest_rows)
    validate_group_split_separation(manifest)
    manifest.to_csv(output_dir / "weak_sample_manifest.csv", index=False)
    group_feasibility = assess_grouped_split_feasibility(manifest)
    readiness = {
        "sample_count": int(len(manifest)),
        "total_weak_label_pixels_after_scl": int(manifest.weak_label_pixels.sum()),
        "samples_with_any_weak_label_pixels": int((manifest.weak_label_pixels > 0).sum()),
        **group_feasibility,
        "split_status": (
            "blocked_insufficient_nontrivial_clear_groups"
            if not group_feasibility["grouped_train_test_feasible"]
            else "requires_group_assignment"
        ),
        "independent_test_truth_available": False,
        "model_trained": False,
        "class_map": WORLD_COVER_TO_TARGET,
        "class_names": TARGET_CLASSES,
        "scl_clear_codes": CLEAR_SCL_CODES,
        "ignore_value": IGNORE,
        "warning": "Masks are WorldCover 2021 weak references for 2026 Sentinel imagery, not independent labels.",
    }
    (output_dir / "readiness.json").write_text(json.dumps(readiness, indent=2), encoding="utf-8")
    return manifest, readiness


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--register", default="data/processed/cv_dataset/reference_review_register.csv")
    parser.add_argument(
        "--sample-manifest",
        default="data/raw/cv_reference/worldcover_2021_sample_validated/sample_manifest.csv",
    )
    parser.add_argument(
        "--output-dir", default="data/processed/cv_dataset/worldcover_weak_alignment_v001"
    )
    args = parser.parse_args()
    register_path, sample_path, output_dir = map(Path, (args.register, args.sample_manifest, args.output_dir))
    for path in (register_path, sample_path):
        if not path.is_file():
            parser.error(f"Input file not found: {path}")
    manifest, readiness = build_weak_masks(pd.read_csv(register_path), pd.read_csv(sample_path), output_dir)
    print(f"Prepared {len(manifest)} weak-mask chips, {readiness['total_weak_label_pixels_after_scl']} usable pixels")
    print(f"Leakage-safe train/test possible: {readiness['grouped_train_test_feasible']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
