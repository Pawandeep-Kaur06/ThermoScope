import tempfile
import unittest
from pathlib import Path

import numpy as np
import rasterio
from affine import Affine

from src.prepare_weak_labeled_chips import (
    IGNORE,
    assess_grouped_split_feasibility,
    make_weak_mask,
    reproject_to_chip_grid,
    validate_group_split_separation,
)


class WeakChipPreparationTests(unittest.TestCase):
    def test_worldcover_aligns_to_exact_target_grid(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "source.tif"
            transform = Affine.translation(0, 2) @ Affine.scale(1, -1)
            with rasterio.open(
                path, "w", driver="GTiff", width=2, height=2, count=1,
                dtype="uint8", crs="EPSG:4326", transform=transform, nodata=0,
            ) as ds:
                ds.write(np.array([[10, 40], [50, 60]], dtype="uint8"), 1)
            aligned, meta = reproject_to_chip_grid(path, "EPSG:4326", transform, 2, 2)
            np.testing.assert_array_equal(aligned, [[10, 40], [50, 60]])
            self.assertEqual(meta["source_crs"], "EPSG:4326")

    def test_cloud_shadow_and_invalid_image_pixels_are_ignored(self):
        wc = np.array([[10, 40, 50, 60, 80]], dtype="uint8")
        scl = np.array([[4, 8, 6, 3, 5]], dtype="uint8")
        valid = np.array([[1, 1, 0, 1, 1]], dtype=bool)
        mask = make_weak_mask(wc, scl, valid)
        np.testing.assert_array_equal(mask, [[1, IGNORE, IGNORE, IGNORE, 5]])

    def test_shape_mismatch_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "share one pixel grid"):
            make_weak_mask(np.ones((2, 2)), np.ones((2, 2)), np.ones((1, 2)))

    def test_group_crossing_partitions_is_rejected(self):
        import pandas as pd

        rows = pd.DataFrame({
            "geo_scene_leakage_group": ["group_a", "group_a", "group_b"],
            "dataset_split": ["train", "test", "validation"],
        })
        with self.assertRaisesRegex(ValueError, "multiple splits"):
            validate_group_split_separation(rows)

    def test_group_exclusive_partitions_pass(self):
        import pandas as pd

        rows = pd.DataFrame({
            "geo_scene_leakage_group": ["group_a", "group_a", "group_b"],
            "dataset_split": ["train", "train", "test"],
        })
        validate_group_split_separation(rows)

    def test_two_pixels_in_a_second_group_do_not_enable_meaningful_holdout(self):
        import pandas as pd

        manifest = pd.DataFrame({
            "geo_scene_leakage_group": ["large", "tiny"],
            "weak_label_pixels": [4036, 2],
            "weak_label_pixel_counts_json": [
                '{"vegetation":3158,"cropland":813,"built_up":49,"bare_sparse":16,"water":0}',
                '{"vegetation":2,"cropland":0,"built_up":0,"bare_sparse":0,"water":0}',
            ],
        })
        result = assess_grouped_split_feasibility(manifest)
        self.assertEqual(result["groups_with_any_weak_labels"], 2)
        self.assertEqual(result["groups_with_minimum_weak_pixels"], 1)
        self.assertFalse(result["grouped_train_test_feasible"])


if __name__ == "__main__":
    unittest.main()
