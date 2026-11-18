import unittest

import pandas as pd

from src.prepare_reference_review_register import (
    REVIEW_COLUMNS,
    build_review_register,
    validate_review_register,
)


def example_manifest():
    return pd.DataFrame([
        {
            "chip_id": f"chip_{i}", "chip_path": f"state/run/chip_{i}.tif",
            "chip_sha256": f"hash_{i}", "scene_item_id": f"scene_{i}",
            "acquisition_date": "2026-06-01", "center_longitude_wgs84": 85.0 + i,
            "center_latitude_wgs84": 23.0 + i, "tile_id": f"tile_{i}",
            "scl_path": f"state/run/scl_{i}.tif",
            "scl_clear_fraction_of_valid_pixels": 0.8,
            "geo_scene_leakage_group": f"group_{i}",
        }
        for i in range(2)
    ])


class ReferenceReviewRegisterTests(unittest.TestCase):
    def test_builder_leaves_labels_and_splits_unassigned(self):
        result = build_review_register(example_manifest(), "state/run/")
        self.assertEqual(list(result.columns), REVIEW_COLUMNS)
        self.assertTrue(result["label_class"].isna().all())
        self.assertTrue(result["reviewer_status"].eq("pending_source_review").all())
        self.assertTrue(result["dataset_split"].eq("unassigned_unlabelled").all())
        validate_review_register(result)

    def test_accepted_label_requires_auditable_evidence(self):
        row = build_review_register(example_manifest(), "state/run/").iloc[[0]].copy()
        row.loc[:, "reviewer_status"] = "accepted"
        row.loc[:, "label_class"] = "built_up"
        with self.assertRaisesRegex(ValueError, "Accepted labels require"):
            validate_review_register(row)

    def test_unlabelled_row_cannot_have_class(self):
        row = build_review_register(example_manifest(), "state/run/").iloc[[0]].copy()
        row.loc[:, "label_class"] = "vegetation"
        with self.assertRaisesRegex(ValueError, "Pending samples"):
            validate_review_register(row)

    def test_geographic_or_scene_group_cannot_cross_splits(self):
        rows = build_review_register(example_manifest(), "state/run/")
        rows.loc[:, "reviewer_status"] = "accepted"
        rows.loc[:, "reference_source_name"] = "Independent map"
        rows.loc[:, "reference_source_url_or_id"] = "https://example.test/map"
        rows.loc[:, "reference_acquisition_or_mapping_date"] = "2025"
        rows.loc[:, "label_class"] = "vegetation"
        rows.loc[:, "confidence"] = "high"
        rows.loc[:, "reviewer_id"] = "reviewer_a"
        rows.loc[0, "geo_scene_leakage_group"] = "shared_group"
        rows.loc[1, "geo_scene_leakage_group"] = "shared_group"
        rows.loc[0, "dataset_split"] = "train"
        rows.loc[1, "dataset_split"] = "test"
        with self.assertRaisesRegex(ValueError, "crosses splits"):
            validate_review_register(rows)


if __name__ == "__main__":
    unittest.main()
