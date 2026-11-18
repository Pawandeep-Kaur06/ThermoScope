import tempfile
import unittest
from pathlib import Path

import numpy as np
import rasterio
from affine import Affine

from src.inventory_cv_model_data import inventory


class CVModelDataInventoryTests(unittest.TestCase):
    def test_inventory_records_raster_schema_checksum_and_nonlabel_semantics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / "data/processed/sample_4band.tif"
            image.parent.mkdir(parents=True)
            with rasterio.open(image, "w", driver="GTiff", width=8, height=8, count=4,
                               dtype="uint16", crs="EPSG:32645",
                               transform=Affine(10, 0, 400000, 0, -10, 2600000)) as dst:
                dst.write(np.ones((4, 8, 8), dtype=np.uint16))
            frame = inventory(root)
            self.assertEqual(len(frame), 1)
            row = frame.iloc[0]
            self.assertEqual(row.raster_kind, "sentinel2_multispectral_chip")
            self.assertEqual(row.label_status, "unlabelled")
            self.assertEqual(row.band_count, 4)
            self.assertEqual(len(row.sha256), 64)


if __name__ == "__main__":
    unittest.main()
