"""Tests for the Jharkhand region and state-boundary interfaces."""
import unittest

import geopandas as gpd
from shapely.geometry import LineString, Point, Polygon, box

from src.fetch_osm_pilot import intersect_region
from src.match_firms_osm_pilot import json_safe
from src.prepare_jharkhand_boundary import select_boundary
from src.regions import coordinate_in_region, get_region, tile_for_coordinate


class JharkhandWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.region = get_region("jharkhand")

    def test_boundary_contains_pilot_and_rejects_outside_point(self):
        self.assertTrue(coordinate_in_region(86.4, 23.8, self.region))
        self.assertFalse(coordinate_in_region(82.9, 23.8, self.region))

    def test_shared_tile_edge_has_one_eastward_owner(self):
        edge_lon = 85.3281137
        tile = tile_for_coordinate(edge_lon, 23.5, self.region)
        self.assertIsNotNone(tile)
        self.assertEqual(tile["tile_id"], "jharkhand_r01_c02")

    def test_tiles_choose_local_crs_on_both_sides_of_utm_zone_edge(self):
        west = tile_for_coordinate(83.6, 23.97, self.region)
        east = tile_for_coordinate(86.4, 23.8, self.region)
        self.assertEqual(west["projected_crs"], "EPSG:32644")
        self.assertEqual(east["projected_crs"], "EPSG:32645")

    def test_boundary_selection_requires_valid_admin_level_four_polygon(self):
        frame = gpd.GeoDataFrame(
            {
                "osm_id": ["relation/1960191", "relation/other"],
                "name": ["Jharkhand", "Jharkhand"],
                "boundary": ["administrative", "administrative"],
                "admin_level": ["4", "5"],
            },
            geometry=[box(83, 22, 88, 25), box(84, 23, 85, 24)],
            crs="EPSG:4326",
        )
        selected = select_boundary(frame)
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected.iloc[0].osm_id, "relation/1960191")
        invalid = frame.copy()
        invalid.loc[0, "geometry"] = Polygon([(0, 0), (1, 1), (1, 0), (0, 1), (0, 0)])
        with self.assertRaisesRegex(ValueError, "invalid"):
            select_boundary(invalid)

    def test_osm_selection_keeps_intersecting_full_geometry(self):
        region = box(0, 0, 1, 1)
        outside = Point(2, 2)
        crossing_line = LineString([(-1, 0.5), (2, 0.5)])
        crossing_polygon = box(0.5, 0.5, 2, 2)
        frame = gpd.GeoDataFrame({"id": [1, 2, 3]}, geometry=[outside, crossing_line, crossing_polygon], crs="EPSG:4326")
        selected = intersect_region(frame, region)
        self.assertEqual(selected.id.tolist(), [2, 3])
        self.assertEqual(selected.geometry.iloc[0].bounds, (-1.0, 0.5, 2.0, 0.5))

    def test_summary_json_normalizes_missing_category_keys(self):
        import json
        import numpy as np
        import pandas as pd
        normalized = json_safe({pd.NA: np.int64(3), "bad": np.float64(float("nan"))})
        self.assertEqual(normalized, {"unknown": 3, "bad": None})
        self.assertEqual(json.loads(json.dumps(normalized)), {"unknown": 3, "bad": None})


if __name__ == "__main__":
    unittest.main()
