"""Country polygon membership, invalid geometry and tile-edge behavior."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd
from shapely.geometry import Polygon, mapping

from src.prepare_country_boundary import validate_polygon
from src.regions import (RegionConfigurationError, coordinate_in_region, contains_coordinates,
                         get_region, load_country_boundary, tile_for_coordinate)


class IndiaBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.india = get_region("india")

    def test_real_boundary_accepts_india_and_excludes_nearby_foreign_points(self):
        # Delhi is well inside India; Kathmandu lies outside the India POV polygon.
        self.assertTrue(coordinate_in_region(77.209, 28.614, self.india))
        self.assertFalse(coordinate_in_region(85.324, 27.717, self.india))
        mask = contains_coordinates(pd.Series([77.209, 85.324]), pd.Series([28.614, 27.717]), self.india)
        self.assertEqual(mask.tolist(), [True, False])

    def test_boundary_line_is_inclusive_and_nearby_outside_point_is_excluded(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            geometry = Polygon([(70, 10), (72, 10), (72, 12), (70, 12), (70, 10)])
            boundary_path = root / "boundary.geojson"
            boundary_path.write_text(json.dumps({"type": "FeatureCollection", "crs": {"type": "name", "properties": {"name": "OGC:CRS84"}},
                                                 "features": [{"type": "Feature", "properties": {}, "geometry": mapping(geometry)}]}), encoding="utf-8")
            region = {"name": "synthetic", "boundary_type": "bbox_with_country_polygon",
                      "bbox_wgs84": {"west": 69, "south": 9, "east": 73, "north": 13},
                      "max_inclusive": True, "country_boundary": {"geometry_path": str(boundary_path),
                      "prepared_sha256": hashlib.sha256(boundary_path.read_bytes()).hexdigest()}, "_config_root": root}
            self.assertTrue(coordinate_in_region(70.0, 11.0, region))  # exact boundary
            self.assertTrue(coordinate_in_region(70.000001, 11.0, region))
            self.assertFalse(coordinate_in_region(69.999999, 11.0, region))

    def test_internal_tile_edge_has_one_stable_east_north_owner(self):
        # 71.1E is an internal 3-degree tile edge; 21.5N is within India.
        tile = tile_for_coordinate(71.1, 21.5, self.india)
        self.assertIsNotNone(tile)
        self.assertEqual(tile["tile_id"], "india_r05_c01")

    def test_invalid_country_geometry_is_rejected_explicitly(self):
        bowtie = Polygon([(0, 0), (2, 2), (0, 2), (2, 0), (0, 0)])
        with self.assertRaisesRegex(ValueError, "invalid"):
            validate_polygon(bowtie)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "invalid.geojson"
            path.write_text(json.dumps({"type": "FeatureCollection", "crs": {"type": "name", "properties": {"name": "OGC:CRS84"}},
                                        "features": [{"type": "Feature", "properties": {}, "geometry": mapping(bowtie)}]}), encoding="utf-8")
            region = {"name": "bad", "country_boundary": {"geometry_path": str(path),
                      "prepared_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}, "_config_root": Path(temp)}
            with self.assertRaisesRegex(RegionConfigurationError, "invalid"):
                load_country_boundary(region)


if __name__ == "__main__":
    unittest.main()
