"""Tests for building an unlabelled, leakage-aware local chip manifest."""
import tempfile
import unittest
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin

from src.prepare_cv_dataset import build_manifest, write_manifest


class PrepareCVDatasetTests(unittest.TestCase):
    def _write_chip(self, path: Path, offset: int = 0):
        path.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(path, "w", driver="GTiff", width=4, height=4, count=4,
                           dtype="uint16", crs="EPSG:32645",
                           transform=from_origin(400000, 2620000, 10, 10)) as ds:
            ds.write(np.full((4, 4, 4), 100 + offset, dtype="uint16"))

    def _write_scl(self, path: Path):
        with rasterio.open(path, "w", driver="GTiff", width=4, height=4, count=1,
                           dtype="uint8", crs="EPSG:32645",
                           transform=from_origin(400000, 2620000, 10, 10)) as ds:
            ds.write(np.array([[4, 5, 6, 8]] * 4, dtype="uint8"), 1)

    def test_manifest_deduplicates_content_pairs_scl_and_keeps_labels_unknown(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            name = "chip_S2A_45QVG_20260811_1_L2A_4band_10m.tif"
            chip = root / "run_a" / name
            duplicate = root / "run_b" / name
            self._write_chip(chip)
            self._write_chip(duplicate)
            scl = chip.with_name(name.replace("_4band_10m.tif", "_scl_10m.tif"))
            self._write_scl(scl)
            rows = build_manifest([root])
            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(row["duplicate_copy_count"], 1)
            self.assertEqual(row["scene_item_id"], "S2A_45QVG_20260811_1_L2A")
            self.assertTrue(row["scl_path"])
            self.assertEqual(row["scl_clear_fraction_of_valid_pixels"], 0.75)
            self.assertEqual(row["label_status"], "unlabelled")
            self.assertFalse(row["independent_label_verified"])
            self.assertFalse(row["is_training_sample"])
            self.assertEqual(row["dataset_split"], "unassigned_no_credible_labels")
            self.assertTrue(row["geo_scene_leakage_group"].startswith("geo_scene_"))

    def test_same_scene_or_tile_is_joined_into_one_leakage_group(self):
        from src.prepare_cv_dataset import _leakage_groups
        rows = [
            {"chip_sha256": "a", "scene_item_id": "scene1", "spatial_group_id": "tile1"},
            {"chip_sha256": "b", "scene_item_id": "scene1", "spatial_group_id": "tile2"},
            {"chip_sha256": "c", "scene_item_id": "scene2", "spatial_group_id": "tile2"},
            {"chip_sha256": "d", "scene_item_id": "scene3", "spatial_group_id": "tile3"},
        ]
        groups = _leakage_groups(rows)
        self.assertEqual(groups[0], groups[1])
        self.assertEqual(groups[1], groups[2])
        self.assertNotEqual(groups[2], groups[3])

    def test_writer_refuses_to_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "manifest.csv"
            output.write_text("keep", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                write_manifest([{"x": 1}], output)
            self.assertEqual(output.read_text(encoding="utf-8"), "keep")


if __name__ == "__main__":
    unittest.main()
