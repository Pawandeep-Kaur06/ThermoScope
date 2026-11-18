"""Tests for checksum-backed stage caches and tile checkpoint resumption."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

from src import match_firms_osm_pilot as matcher
from src.pipeline_cache import cache_hit, cache_key, file_fingerprint, write_manifest
from src.regions import get_region


class PipelineCacheTests(unittest.TestCase):
    def test_cache_hit_and_corruption_invalidation(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "source.csv"
            output = Path(temp) / "prepared.csv"
            source.write_text("a\n1\n", encoding="utf-8")
            key = cache_key(stage="test", inputs={"source": file_fingerprint(source)}, configuration={"x": 1})
            output.write_text("result\n", encoding="utf-8")
            write_manifest(output, key=key, source=str(source))
            self.assertTrue(cache_hit(output, key))
            self.assertFalse(cache_hit(output, "different-key"))
            output.write_text("corrupted\n", encoding="utf-8")
            self.assertFalse(cache_hit(output, key))

    def test_source_change_invalidates_key(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "source.csv"
            source.write_text("one", encoding="utf-8")
            first = cache_key(stage="test", inputs={"source": file_fingerprint(source)}, configuration={})
            source.write_text("two", encoding="utf-8")
            second = cache_key(stage="test", inputs={"source": file_fingerprint(source)}, configuration={})
            self.assertNotEqual(first, second)

    def test_touching_unchanged_input_does_not_invalidate_content_cache(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "source.csv"
            source.write_text("same bytes", encoding="utf-8")
            first = cache_key(stage="test", inputs={"source": file_fingerprint(source)}, configuration={})
            source.touch()
            second = cache_key(stage="test", inputs={"source": file_fingerprint(source)}, configuration={})
            self.assertEqual(first, second)

    def test_completed_tiles_resume_without_rereading_osm_and_combine_once(self):
        region = get_region("india")
        coordinates = [(71.0999, 21.5), (71.1001, 21.5)]
        firms = pd.DataFrame({"longitude": [p[0] for p in coordinates], "latitude": [p[1] for p in coordinates],
                              "acq_date": ["2026-01-01", "2026-01-02"], "acq_time": ["1000", "1000"],
                              "satellite": ["SNPP", "SNPP"], "instrument": ["VIIRS", "VIIRS"], "frp": [1.0, 1.0]})
        osm = gpd.GeoDataFrame({"osm_id": ["101", "102"], "osm_way_id": [None, None],
                                "source_layer": ["points", "points"],
                                "all_tags": ['{"industrial":"yes"}', '{"industrial":"yes"}']},
                               geometry=[Point(*p) for p in coordinates], crs="EPSG:4326")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            gpkg = root / "osm.gpkg"
            osm.to_file(gpkg, layer="points", driver="GPKG", index=False)
            checkpoints = root / "run" / ".intermediate" / "tiles"
            prior = (matcher.TILED_MODE, matcher.BOUNDS, matcher.DISTANCE_CRS,
                     matcher.BOUNDS_MAX_INCLUSIVE, matcher.BOUNDS_EAST_INCLUSIVE, matcher.BOUNDS_NORTH_INCLUSIVE)
            try:
                matcher.TILED_MODE = True
                first, _ = matcher.match_firms_by_tiles(firms, gpkg, root, root, region, "india", checkpoints)
                with patch.object(matcher, "load_osm", side_effect=AssertionError("cache miss repeated OSM work")):
                    resumed, metadata = matcher.match_firms_by_tiles(firms, gpkg, root, root, region, "india", checkpoints)
                self.assertEqual(metadata["completed_tile_cache_hits"], 2)
                self.assertEqual(resumed.firms_observation_id.tolist(), first.firms_observation_id.tolist())
                self.assertEqual(resumed.firms_observation_id.nunique(), len(resumed))
                # A damaged checkpoint is rejected and only that tile is rebuilt.
                damaged = next(checkpoints.glob("*.pkl"))
                damaged.write_bytes(b"partial")
                original_load = matcher.load_osm
                calls = []
                def counted_load(*args, **kwargs):
                    calls.append(1)
                    return original_load(*args, **kwargs)
                with patch.object(matcher, "load_osm", side_effect=counted_load):
                    repaired, metadata = matcher.match_firms_by_tiles(firms, gpkg, root, root, region, "india", checkpoints)
                self.assertEqual(len(calls), 1)
                self.assertEqual(metadata["completed_tile_cache_hits"], 1)
                self.assertEqual(repaired.firms_observation_id.nunique(), len(repaired))
            finally:
                (matcher.TILED_MODE, matcher.BOUNDS, matcher.DISTANCE_CRS,
                 matcher.BOUNDS_MAX_INCLUSIVE, matcher.BOUNDS_EAST_INCLUSIVE,
                 matcher.BOUNDS_NORTH_INCLUSIVE) = prior

    def test_interrupted_tile_loop_resumes_to_same_combined_result(self):
        region = get_region("india")
        coordinates = [(70.5, 21.5), (71.2, 21.5)]
        firms = pd.DataFrame({"longitude": [p[0] for p in coordinates], "latitude": [p[1] for p in coordinates],
                              "acq_date": ["2026-01-01", "2026-01-02"], "acq_time": ["1000", "1000"],
                              "satellite": ["SNPP", "SNPP"], "instrument": ["VIIRS", "VIIRS"], "frp": [1.0, 1.0]})
        osm = gpd.GeoDataFrame({"osm_id": ["101", "102"], "osm_way_id": [None, None],
                                "source_layer": ["points", "points"],
                                "all_tags": ['{"industrial":"yes"}', '{"industrial":"yes"}']},
                               geometry=[Point(*p) for p in coordinates], crs="EPSG:4326")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); gpkg = root / "osm.gpkg"
            osm.to_file(gpkg, layer="points", driver="GPKG", index=False)
            prior = (matcher.TILED_MODE, matcher.BOUNDS, matcher.DISTANCE_CRS,
                     matcher.BOUNDS_MAX_INCLUSIVE, matcher.BOUNDS_EAST_INCLUSIVE, matcher.BOUNDS_NORTH_INCLUSIVE)
            original = matcher.do_matching
            call_count = 0
            def fail_on_second_tile(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 2:
                    raise RuntimeError("synthetic interruption after first completed tile")
                return original(*args, **kwargs)
            try:
                matcher.TILED_MODE = True
                resume_dir = root / "resume"
                with patch.object(matcher, "do_matching", side_effect=fail_on_second_tile):
                    with self.assertRaisesRegex(RuntimeError, "synthetic interruption"):
                        matcher.match_firms_by_tiles(firms, gpkg, root, root, region, "india", resume_dir)
                resumed, resumed_meta = matcher.match_firms_by_tiles(firms, gpkg, root, root, region, "india", resume_dir)
                clean, _ = matcher.match_firms_by_tiles(firms, gpkg, root, root, region, "india", root / "clean")
            finally:
                (matcher.TILED_MODE, matcher.BOUNDS, matcher.DISTANCE_CRS,
                 matcher.BOUNDS_MAX_INCLUSIVE, matcher.BOUNDS_EAST_INCLUSIVE,
                 matcher.BOUNDS_NORTH_INCLUSIVE) = prior
        self.assertEqual(resumed_meta["completed_tile_cache_hits"], 1)
        columns = ["firms_observation_id", "tile_id", "distance_crs", "osm_nearest_distance_m", "match_status"]
        pd.testing.assert_frame_equal(resumed[columns].reset_index(drop=True), clean[columns].reset_index(drop=True))


if __name__ == "__main__":
    unittest.main()
