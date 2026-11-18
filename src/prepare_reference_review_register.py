"""Prepare an auditable, explicitly unlabelled reference-review register.

This utility selects the existing Jharkhand run_001 chip locations only. It
never assigns classes or reviewer decisions. Reference fields remain empty
until a human has obtained and cited an appropriate source.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


REQUIRED_MANIFEST_COLUMNS = {
    "chip_id", "chip_path", "chip_sha256", "scene_item_id",
    "acquisition_date", "center_longitude_wgs84", "center_latitude_wgs84",
    "tile_id", "scl_path", "scl_clear_fraction_of_valid_pixels",
    "geo_scene_leakage_group",
}
REVIEW_COLUMNS = [
    "sample_id", "chip_id", "chip_path", "chip_sha256", "scene_item_id",
    "image_acquisition_date", "longitude_wgs84", "latitude_wgs84", "tile_id",
    "scl_path", "scl_clear_fraction", "reference_source_name",
    "reference_source_url_or_id", "reference_source_type",
    "reference_acquisition_or_mapping_date", "reference_date_precision",
    "label_class", "confidence", "reviewer_id", "reviewer_status",
    "review_notes", "geo_scene_leakage_group", "dataset_split",
]
VALID_REVIEW_STATUSES = {"pending_source_review", "accepted", "rejected", "unresolved"}
VALID_SPLITS = {"train", "validation", "test"}


def validate_review_register(frame: pd.DataFrame) -> None:
    """Reject fabricated/incomplete accepted labels and leakage across splits."""
    missing = set(REVIEW_COLUMNS) - set(frame.columns)
    if missing:
        raise ValueError(f"Review register is missing columns: {sorted(missing)}")
    if frame["sample_id"].isna().any() or frame["sample_id"].duplicated().any():
        raise ValueError("sample_id must be present and unique")
    invalid_status = set(frame["reviewer_status"].dropna()) - VALID_REVIEW_STATUSES
    if invalid_status:
        raise ValueError(f"Invalid reviewer_status values: {sorted(invalid_status)}")

    accepted = frame["reviewer_status"].eq("accepted")
    required_for_accepted = [
        "reference_source_name", "reference_source_url_or_id",
        "reference_acquisition_or_mapping_date", "label_class", "confidence",
        "reviewer_id",
    ]
    if frame.loc[accepted, required_for_accepted].isna().any().any() or (
        frame.loc[accepted, required_for_accepted].astype(str).apply(
            lambda col: col.str.strip().eq("")
        ).any().any()
    ):
        raise ValueError("Accepted labels require source, date, class, confidence, and reviewer")

    pending = frame["reviewer_status"].eq("pending_source_review")
    if frame.loc[pending, "label_class"].notna().any():
        raise ValueError("Pending samples must not contain a label_class")

    assigned = frame["dataset_split"].isin(VALID_SPLITS)
    if frame.loc[assigned, "reviewer_status"].ne("accepted").any():
        raise ValueError("Only human-accepted samples may be assigned to dataset splits")
    split_rows = frame.loc[assigned]
    for group_column in ("geo_scene_leakage_group", "scene_item_id", "tile_id"):
        if group_column not in split_rows or split_rows[group_column].isna().any():
            raise ValueError(f"Split rows require {group_column}")
        split_counts = split_rows.groupby(group_column)["dataset_split"].nunique()
        if split_counts.gt(1).any():
            raise ValueError(f"Geographic/scene leakage: {group_column} crosses splits")


def build_review_register(manifest: pd.DataFrame, chip_root: str) -> pd.DataFrame:
    missing = REQUIRED_MANIFEST_COLUMNS - set(manifest.columns)
    if missing:
        raise ValueError(f"Chip manifest is missing columns: {sorted(missing)}")
    selected = manifest[manifest["chip_path"].astype(str).str.startswith(chip_root)].copy()
    if selected.empty:
        raise ValueError(f"No chips found under configured root: {chip_root}")
    if selected["chip_id"].duplicated().any():
        raise ValueError("Selected chips contain duplicate chip_id values")

    out = pd.DataFrame({
        "sample_id": selected["chip_id"],
        "chip_id": selected["chip_id"],
        "chip_path": selected["chip_path"],
        "chip_sha256": selected["chip_sha256"],
        "scene_item_id": selected["scene_item_id"],
        "image_acquisition_date": selected["acquisition_date"],
        "longitude_wgs84": selected["center_longitude_wgs84"],
        "latitude_wgs84": selected["center_latitude_wgs84"],
        "tile_id": selected["tile_id"],
        "scl_path": selected["scl_path"],
        "scl_clear_fraction": selected["scl_clear_fraction_of_valid_pixels"],
        "reference_source_name": pd.NA,
        "reference_source_url_or_id": pd.NA,
        "reference_source_type": "not_yet_selected",
        "reference_acquisition_or_mapping_date": pd.NA,
        "reference_date_precision": pd.NA,
        "label_class": pd.NA,
        "confidence": pd.NA,
        "reviewer_id": pd.NA,
        "reviewer_status": "pending_source_review",
        "review_notes": "No label assigned; obtain dated reference and human-review per pixel.",
        "geo_scene_leakage_group": selected["geo_scene_leakage_group"],
        "dataset_split": "unassigned_unlabelled",
    })
    out = out[REVIEW_COLUMNS].reset_index(drop=True)
    validate_review_register(out)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default="data/processed/cv_dataset/manifest.csv")
    parser.add_argument(
        "--chip-root",
        default="data/processed/jharkhand_analysis/run_001/satellite_investigation/",
        help="Select chip paths under this existing run-relative directory.",
    )
    parser.add_argument(
        "--output", default="data/processed/cv_dataset/reference_review_register.csv"
    )
    args = parser.parse_args()

    manifest_path, output_path = Path(args.manifest), Path(args.output)
    if not manifest_path.is_file():
        parser.error(f"Chip manifest does not exist: {manifest_path}")
    if output_path.exists():
        parser.error(f"Refusing to overwrite existing review register: {output_path}")
    frame = pd.read_csv(manifest_path)
    register = build_review_register(frame, args.chip_root)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    register.to_csv(output_path, index=False)
    print(f"Wrote {len(register)} unlabelled review rows to {output_path}")
    print("All samples remain pending; no labels or dataset splits were assigned.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
