"""Small synthetic tests for tile assignment, CRS choice, and global recurrence."""
import unittest
import json
import tempfile
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

from src.engineer_features import add_past_only_recurrence
from src import match_firms_osm_pilot as matcher
from src.match_firms_osm_pilot import combine_tile_results
from src.regions import (
    assign_recurrence_grid, assign_tile_ids, get_region, tile_for_coordinate,
)


class TiledProcessingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.india = get_region("india")

    def test_shared_tile_edges_have_one_owner(self):
        # India tiling begins at 68.1E/6.5N, with 3 degree cells.
        ids = assign_tile_ids([71.09999, 71.1, 97.4], [21.5, 21.5, 37.1], self.india)
        self.assertEqual(len(ids), 3)
        self.assertEqual(ids[0], "india_r05_c00")
        self.assertEqual(ids[1], "india_r05_c01")  # shared east edge belongs to the eastern tile
        self.assertIsNone(ids[2])  # rectangle corner lies outside the country polygon
        self.assertEqual(len(set(ids[:2])), 2)

    def test_tiles_choose_local_crs_from_tile_center(self):
        west = tile_for_coordinate(70.5, 21.5, self.india)
        east = tile_for_coordinate(97.3, 28.0, self.india)
        self.assertEqual(west["projected_crs"], "EPSG:32642")
        self.assertEqual(east["projected_crs"], "EPSG:32647")
        self.assertNotEqual(west["projected_crs"], east["projected_crs"])

    def test_combining_tiles_rejects_duplicate_observations(self):
        a = pd.DataFrame({"firms_source_row": [0], "firms_observation_id": ["obs-1"], "tile_id": ["tile-a"]})
        b = pd.DataFrame({"firms_source_row": [1], "firms_observation_id": ["obs-2"], "tile_id": ["tile-b"]})
        combined = combine_tile_results([a, b])
        self.assertEqual(combined.firms_observation_id.tolist(), ["obs-1", "obs-2"])
        duplicate = b.assign(firms_observation_id="obs-1")
        with self.assertRaisesRegex(ValueError, "duplicate firms_observation_id"):
            combine_tile_results([a, duplicate])

    def test_recurrence_uses_one_global_grid_across_a_tile_edge(self):
        west_lon, east_lon = 71.09998, 71.10002
        tile_ids = assign_tile_ids([west_lon, east_lon], [21.5, 21.5], self.india)
        self.assertNotEqual(tile_ids[0], tile_ids[1])
        cells = assign_recurrence_grid([west_lon, east_lon], [21.5, 21.5], self.india, 250.0)
        self.assertEqual(cells[0], cells[1])
        frame = pd.DataFrame({
            "firms_source_row": [0, 1], "firms_observation_id": ["a", "b"],
            "tile_id": tile_ids, "hotspot_cell_id": cells,
            "acq_date": ["2026-01-01", "2026-01-02"], "frp": [2.0, 3.0],
        })
        featured = add_past_only_recurrence(frame)
        self.assertEqual(featured.cell_prior_detection_count.tolist(), [0, 1])
        self.assertEqual(featured.cell_prior_distinct_acquisition_dates.tolist(), [0, 1])
        self.assertFalse(bool(featured.cell_prior_recurring_flag.iloc[1]))

    def test_matching_processes_osm_windows_in_tile_crs_and_combines_once(self):
        coordinates = [(71.0999, 21.5), (71.1001, 21.5)]
        firms = pd.DataFrame({"longitude": [p[0] for p in coordinates], "latitude": [p[1] for p in coordinates],
                              "acq_date": ["2026-01-01", "2026-01-02"], "acq_time": ["1000", "1000"],
                              "satellite": ["SNPP", "SNPP"], "instrument": ["VIIRS", "VIIRS"], "frp": [1.0, 1.0]})
        osm = gpd.GeoDataFrame({
            "osm_id": ["101", "102"], "osm_way_id": [None, None],
            "source_layer": ["points", "points"],
            "all_tags": [json.dumps({"industrial": "yes", "name": "Synthetic site"})] * 2,
        }, geometry=[Point(*p) for p in coordinates], crs="EPSG:4326")
        with tempfile.TemporaryDirectory() as temporary:
            gpkg = Path(temporary) / "osm.gpkg"
            osm.to_file(gpkg, layer="points", driver="GPKG", index=False)
            prior_state = (matcher.TILED_MODE, matcher.BOUNDS, matcher.DISTANCE_CRS,
                           matcher.BOUNDS_MAX_INCLUSIVE, matcher.BOUNDS_EAST_INCLUSIVE,
                           matcher.BOUNDS_NORTH_INCLUSIVE)
            try:
                matcher.TILED_MODE = True
                combined, metadata = matcher.match_firms_by_tiles(
                    firms, gpkg, Path(temporary), Path(temporary), self.india, "india"
                )
            finally:
                (matcher.TILED_MODE, matcher.BOUNDS, matcher.DISTANCE_CRS,
                 matcher.BOUNDS_MAX_INCLUSIVE, matcher.BOUNDS_EAST_INCLUSIVE,
                 matcher.BOUNDS_NORTH_INCLUSIVE) = prior_state
        self.assertEqual(combined.firms_source_row.tolist(), [0, 1])
        self.assertEqual(combined.firms_observation_id.nunique(), 2)
        self.assertEqual(combined.distance_crs.tolist(), ["EPSG:32642", "EPSG:32643"])
        self.assertTrue(combined.match_status_100m.eq("ambiguous_proximity").all())
        self.assertTrue(combined.osm_nearest_distance_m.eq(0).all())
        self.assertEqual(metadata["tile_count_used"], 2)

    def test_matching_can_restrict_a_trial_to_selected_tiles(self):
        coordinates = [(70.5, 21.5), (71.2, 21.5)]
        firms = pd.DataFrame({"longitude": [p[0] for p in coordinates], "latitude": [p[1] for p in coordinates],
                              "acq_date": ["2026-01-01", "2026-01-02"], "acq_time": ["1000", "1000"],
                              "satellite": ["SNPP", "SNPP"], "instrument": ["VIIRS", "VIIRS"], "frp": [1.0, 1.0]})
        osm = gpd.GeoDataFrame({"osm_id": ["101"], "osm_way_id": [None], "source_layer": ["points"],
                                "all_tags": ['{"industrial":"yes"}']},
                               geometry=[Point(*coordinates[0])], crs="EPSG:4326")
        with tempfile.TemporaryDirectory() as temporary:
            gpkg = Path(temporary) / "osm.gpkg"
            osm.to_file(gpkg, layer="points", driver="GPKG", index=False)
            prior = (matcher.TILED_MODE, matcher.BOUNDS, matcher.DISTANCE_CRS,
                     matcher.BOUNDS_MAX_INCLUSIVE, matcher.BOUNDS_EAST_INCLUSIVE, matcher.BOUNDS_NORTH_INCLUSIVE)
            try:
                matcher.TILED_MODE = True
                result, metadata = matcher.match_firms_by_tiles(
                    firms, gpkg, Path(temporary), Path(temporary), self.india, "india",
                    selected_tile_ids=["india_r05_c00"])
            finally:
                (matcher.TILED_MODE, matcher.BOUNDS, matcher.DISTANCE_CRS,
                 matcher.BOUNDS_MAX_INCLUSIVE, matcher.BOUNDS_EAST_INCLUSIVE,
                 matcher.BOUNDS_NORTH_INCLUSIVE) = prior
        self.assertEqual(result.tile_id.tolist(), ["india_r05_c00"])
        self.assertEqual(result.firms_source_row.tolist(), [0])
        self.assertEqual(metadata["selected_tile_ids"], ["india_r05_c00"])
        self.assertEqual(metadata["tile_count_used"], 1)


if __name__ == "__main__":
    unittest.main()
