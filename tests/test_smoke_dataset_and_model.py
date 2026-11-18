import io
import tempfile
import unittest
from pathlib import Path

import numpy as np
import rasterio
import tarfile
import torch
from affine import Affine
from rasterio.io import MemoryFile

from src.extract_industrial_smoke_dataset import safe_extract
from src.prepare_smoke_dataset import _location_split, build_manifest
from src.train_smoke_segmentation import rasterize_labelstudio_mask
from src.thermoscope_app.smoke_model import (
    CHANNEL_MEANS, MODEL_BAND_INDEXES, SmokeInputError, predict_smoke_upload,
    build_tiny_smoke_cnn, prepare_stack_from_dataset, validate_band_order,
)


class SmokeDatasetTests(unittest.TestCase):
    def test_grouped_split_assigns_each_site_to_exactly_one_partition(self):
        records = []
        for site in range(624):
            for label in (0, 1 if site % 2 else 0):
                records.append({"site_group_id": str(site), "label": label})
        assignments = _location_split(records, seed=42)
        self.assertEqual(set(assignments), {str(i) for i in range(624)})
        self.assertEqual(set(assignments.values()), {"train", "validation", "test"})

    def test_build_manifest_accepts_119_pixel_chip_and_keeps_site_split(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "images" / "positive").mkdir(parents=True)
            (root / "images" / "negative").mkdir(parents=True)
            (root / "segmentation_labels").mkdir()
            for site in range(10):
                for label, seq in (("negative", 0), ("positive", 1)):
                    width = 119 if site == 0 and label == "negative" else 120
                    path = root / "images" / label / f"{site}_2019-02-03T10_11_12.5Z_{seq}.tif"
                    with rasterio.open(path, "w", driver="GTiff", width=width, height=120,
                                       count=13, dtype="uint16", crs="EPSG:32631",
                                       transform=Affine(10, 0, 550000, 0, -10, 5700000)) as dst:
                        dst.write(np.zeros((13, 120, width), dtype=np.uint16))
            rows, quality = build_manifest(root)
            self.assertEqual(len(rows), 20)
            self.assertEqual(quality["unique_site_count"], 10)
            self.assertIn("by site", quality["split_method"])
            self.assertTrue(all(row["band_count"] == 13 for row in rows))
            self.assertEqual(sum(row["width"] == 119 for row in rows), 1)
            site_sets = {split: {str(r["site_group_id"]) for r in rows if r["split"] == split}
                         for split in ("train", "validation", "test")}
            self.assertFalse(site_sets["train"] & site_sets["validation"])
            self.assertFalse(site_sets["train"] & site_sets["test"])
            self.assertFalse(site_sets["validation"] & site_sets["test"])

    def test_extractor_maps_windows_invalid_characters_and_rejects_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "safe.tar.gz"
            data = b"test"
            with tarfile.open(archive, "w:gz") as tar:
                info = tarfile.TarInfo("positive/site_2019-01-01T10:11:12Z_0.tif")
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
            out = root / "extracted"
            rows = safe_extract(archive, out)
            mapped = out / "positive/site_2019-01-01T10_11_12Z_0.tif"
            self.assertEqual(mapped.read_bytes(), data)
            self.assertEqual(rows[0]["archive_path"], "positive/site_2019-01-01T10:11:12Z_0.tif")
            self.assertEqual(rows[0]["relative_path"], "positive/site_2019-01-01T10_11_12Z_0.tif")
            bad_archive = root / "bad.tar.gz"
            with tarfile.open(bad_archive, "w:gz") as tar:
                info = tarfile.TarInfo("../outside.txt")
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
            with self.assertRaises(ValueError):
                safe_extract(bad_archive, root / "bad_out")
            self.assertFalse((root / "outside.txt").exists())


class SmokeModelInputTests(unittest.TestCase):
    def test_rejects_rgb_or_four_band_input(self):
        with self.assertRaises(SmokeInputError):
            validate_band_order((None, None, None, None), confirmed=True)

    def test_rejects_unidentified_13_band_input_without_explicit_confirmation(self):
        with self.assertRaises(SmokeInputError):
            validate_band_order((None,) * 13)
        self.assertEqual(validate_band_order((None,) * 13, confirmed=True),
                         "uploader_confirmed_published_band_order")

    def test_validates_named_band_order(self):
        names = tuple(f"B{i:02d}" for i in range(1, 13))
        names = names[:8] + ("B8A", "B09", "B10", "B11", "B12")
        self.assertEqual(validate_band_order(names), "band_descriptions_verified")
        wrong = list(names)
        wrong[0], wrong[1] = wrong[1], wrong[0]
        with self.assertRaises(SmokeInputError):
            validate_band_order(tuple(wrong))

    def test_preprocessing_selects_12_channels_pads_and_normalizes(self):
        data = np.zeros((13, 120, 119), dtype=np.uint16)
        data[0] = 1000
        with MemoryFile() as memory:
            with memory.open(driver="GTiff", width=119, height=120, count=13, dtype="uint16",
                             crs="EPSG:32631", transform=Affine(10, 0, 500000, 0, -10, 5700000)) as dst:
                dst.write(data)
            with memory.open() as dataset:
                array, source = prepare_stack_from_dataset(dataset, band_order_confirmed=True, crop_size=90)
        self.assertEqual(array.shape, (12, 90, 90))
        self.assertEqual(source, "uploader_confirmed_published_band_order")
        expected = (1000 - CHANNEL_MEANS[0]) / 441.8
        self.assertAlmostEqual(float(array[0, 0, 0]), float(expected), places=5)
        self.assertNotIn(11, MODEL_BAND_INDEXES)
        self.assertIn(12, MODEL_BAND_INDEXES)

    def test_inference_interface_reports_missing_weights_and_raster_requirement(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = predict_smoke_upload("scene.png", b"not-raster", checkpoint_path=Path(tmp) / "missing.pth")
            self.assertEqual(result["status"], "unsupported_input")
            result = predict_smoke_upload("scene.tif", b"not-raster", checkpoint_path=Path(tmp) / "missing.pth")
            self.assertEqual(result["status"], "unavailable")
            self.assertIsNone(result["prediction"])

    def test_tiny_model_accepts_12_band_input(self):
        model = build_tiny_smoke_cnn().eval()
        with torch.inference_mode():
            output = model(torch.zeros((1, 12, 90, 90)))
        self.assertEqual(tuple(output.shape), (1, 1))
        self.assertTrue(torch.isfinite(output).all())

    def test_rasterizes_only_manual_smoke_polygons_using_documented_scale(self):
        with tempfile.TemporaryDirectory() as tmp:
            annotation = Path(tmp) / "sample.json"
            annotation.write_text('{"completions":[{"result":[{"value":{"points":[[10,10],[20,10],[20,20],[10,20]],"polygonlabels":["smoke"]}}]}]}')
            mask = rasterize_labelstudio_mask(annotation)
            self.assertEqual(mask.shape, (120, 120))
            self.assertEqual(mask.dtype, np.uint8)
            self.assertGreater(mask.sum(), 0)
            self.assertEqual(int(mask[15, 15]), 1)

    def test_tiny_unet_outputs_spatial_mask(self):
        from src.thermoscope_app.smoke_model import build_tiny_smoke_unet
        model = build_tiny_smoke_unet().eval()
        with torch.inference_mode():
            output = model(torch.zeros((1, 12, 90, 90)))
        self.assertEqual(tuple(output.shape), (1, 1, 90, 90))

    def test_checkpoint_inference_returns_smoke_output_not_fire_label(self):
        from src.thermoscope_app.smoke_model import build_tiny_smoke_cnn
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            checkpoint = root / "model.pth"
            torch.save(build_tiny_smoke_cnn().state_dict(), checkpoint)
            checkpoint.with_suffix(".json").write_text('{"architecture":"thermoscope_tiny_cnn_12band","decision_threshold":0.5}')
            data = np.zeros((13, 120, 120), dtype=np.uint16)
            with MemoryFile() as memory:
                with memory.open(driver="GTiff", width=120, height=120, count=13, dtype="uint16",
                                 crs="EPSG:32631", transform=Affine(10, 0, 500000, 0, -10, 5700000)) as dst:
                    dst.write(data)
                payload = memory.read()
            result = predict_smoke_upload("chip.tif", payload, checkpoint_path=checkpoint,
                                          band_order_confirmed=True)
        self.assertEqual(result["status"], "available")
        self.assertIn(result["prediction"], {"visible_smoke_cue", "no_visible_smoke_cue"})
        self.assertNotIn("industrial_fire", result["prediction"])


if __name__ == "__main__":
    unittest.main()
