import unittest

from src.download_worldcover_reference_sample import worldcover_tile_for_bounds


class WorldCoverSampleTests(unittest.TestCase):
    def test_tile_for_dhanbad_longitude_and_south_latitude(self):
        self.assertEqual(worldcover_tile_for_bounds((85.54, 23.77, 85.56, 23.79)), "N21E084")

    def test_tile_for_northern_jharkhand_chip(self):
        self.assertEqual(worldcover_tile_for_bounds((87.38, 25.03, 87.40, 25.04)), "N24E087")

    def test_chip_crossing_source_tile_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "cross"):
            worldcover_tile_for_bounds((83.99, 23.9, 84.01, 23.92))


if __name__ == "__main__":
    unittest.main()
