"""Interface-level tests for the prepared-FIRMS -> match -> feature workflow."""

import unittest
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from pyproj import Transformer
from shapely.geometry import Point

from src.engineer_features import (
    add_gem_traceability, add_industrial_context, add_past_only_recurrence,
    add_sentinel_features, add_thermal_features, build_parser as feature_parser,
    validate_source_alignment,
)
from src.match_firms_osm_pilot import analyze_recurrence, build_parser as match_parser, do_matching


class PipelineInterfaceTests(unittest.TestCase):
    def test_match_cli_accepts_prepared_csv_and_explicit_inputs_outputs(self):
        args = match_parser().parse_args([
            "--repo", "C:/workspace", "--firms", "data/processed/firms_pilot.csv",
            "--osm", "data/processed/osm/pilot.gpkg", "--gem-dir", "data/processed/gem",
            "--region", "dhanbad_jharia_bokaro",
            "--output-dir", "data/processed/spatial_matching/test_run",
        ])
        self.assertEqual(args.firms, Path("data/processed/firms_pilot.csv"))
        self.assertEqual(args.osm, Path("data/processed/osm/pilot.gpkg"))
        self.assertEqual(args.output_dir, Path("data/processed/spatial_matching/test_run"))
        self.assertEqual(args.region, "dhanbad_jharia_bokaro")

    def test_matching_preserves_firms_provenance_columns(self):
        firms = pd.DataFrame([{
            "latitude": 23.5, "longitude": 86.0, "acq_date": "2026-01-20",
            "acq_time": "0010", "satellite": "SNPP", "instrument": "VIIRS",
            "brightness": 340.0, "bright_t31": 300.0, "frp": 4.0,
            "confidence": "n", "daynight": "N", "type": np.nan,
            "version": "2.0NRT",
            "firms_sources": "archive+nrt", "duplicate_record_count": 1,
        }])
        tx = Transformer.from_crs("EPSG:4326", "EPSG:32645", always_xy=True)
        x, y = tx.transform(86.0, 23.5)
        osm = gpd.GeoDataFrame([{
            "osm_feature_id": "node42", "osm_source_id": "42", "osm_element_type": "node",
            "feature_label": "Test industry", "feature_category": "industrial_facility",
            "feature_role": "industrial_facility", "tag_signature": "industrial=yes",
            "source_layer": "points",
        }], geometry=[Point(x, y)], crs="EPSG:32645")
        gem = gpd.GeoDataFrame(columns=["name", "asset_type", "geometry"], geometry="geometry", crs="EPSG:4326")

        matched, _ = do_matching(firms, osm, gem)

        self.assertEqual(matched.loc[0, "firms_sources"], "archive+nrt")
        self.assertEqual(matched.loc[0, "duplicate_record_count"], 1)
        self.assertEqual(matched.loc[0, "firms_source_row"], 0)
        matched, _ = analyze_recurrence(matched)
        matched = validate_source_alignment(firms, matched)
        features = add_thermal_features(matched)
        features = add_past_only_recurrence(features)
        features = add_industrial_context(features)
        features = add_gem_traceability(features, pd.DataFrame())
        features, _ = add_sentinel_features(features, satellite_dir=None)
        self.assertEqual(features.loc[0, "firms_sources"], "archive+nrt")
        self.assertEqual(features.loc[0, "duplicate_record_count"], 1)
        self.assertEqual(features.loc[0, "version"], "2.0NRT")

    def test_feature_join_validates_and_retains_provenance(self):
        source = pd.DataFrame({
            "latitude": [23.5], "longitude": [86.0], "firms_sources": ["archive+nrt"],
            "duplicate_record_count": [1],
        })
        matched = source.assign(firms_source_row=[0], match_status=["proximity_candidate"])

        joined = validate_source_alignment(source, matched)

        self.assertEqual(joined.loc[0, "firms_sources"], "archive+nrt")
        self.assertEqual(joined.loc[0, "duplicate_record_count"], 1)
        self.assertEqual(joined.loc[0, "match_status"], "proximity_candidate")

    def test_feature_cli_requires_matching_dir_and_accepts_run_inputs(self):
        args = feature_parser().parse_args([
            "--firms", "data/processed/firms_pilot.csv", "--osm", "pilot.gpkg",
            "--matching-dir", "matching/run_a", "--satellite-dir", "satellite/run_b",
            "--region", "dhanbad_jharia_bokaro",
            "--output-dir", "features/run_c",
        ])
        self.assertEqual(args.matching_dir, Path("matching/run_a"))
        self.assertEqual(args.satellite_dir, Path("satellite/run_b"))
        self.assertEqual(args.output_dir, Path("features/run_c"))
        self.assertEqual(args.region, "dhanbad_jharia_bokaro")

    def test_features_work_without_satellite_inputs_and_mark_them_missing(self):
        frame = pd.DataFrame({"hotspot_cell_id": ["cell-a"]})

        featured, counts = add_sentinel_features(frame, satellite_dir=None)

        self.assertEqual(counts["metadata_available"], 0)
        self.assertFalse(featured.loc[0, "s2_chip_available_for_context"])
        self.assertEqual(featured.loc[0, "s2_spectral_data_status"], "not_available_no_scene_metadata")


if __name__ == "__main__":
    unittest.main()
