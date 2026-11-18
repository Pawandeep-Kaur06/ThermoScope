"""Tests for leakage-safe Sentinel-2 metadata and pixel sampling."""

import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from rasterio.transform import from_origin
from pyproj import Transformer

from src.engineer_features import add_sentinel_features, discover_satellite_run
from src.investigate_satellite_pilot import latest_firms_timestamp_utc, select_investigation_cells
from src.regions import get_region


class SentinelIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "data/processed/satellite_investigation").mkdir(parents=True)
        self.sat = self.root / "data/processed/satellite_investigation/run_20260101T000000Z"
        self.sat.mkdir()
        tx = Transformer.from_crs("EPSG:4326", "EPSG:32645", always_xy=True)
        self.x, self.y = tx.transform(86.0, 23.5)
        self.transform = from_origin(self.x - 10, self.y + 10, 10, 10)
        with rasterio.open(self.sat / "chip.tif", "w", driver="GTiff", height=2, width=2,
                           count=4, dtype="uint16", crs="EPSG:32645", transform=self.transform,
                           nodata=0) as ds:
            ds.write(np.full((4, 2, 2), 125, dtype=np.uint16))
        self.write_scl(np.full((2, 2), 4, dtype=np.uint8))
        self.write_metadata("2026-01-20T04:00:00Z", 0, include_scl=True)

    def tearDown(self):
        self.temp.cleanup()

    def write_scl(self, classes):
        with rasterio.open(self.sat / "scl.tif", "w", driver="GTiff", height=2, width=2,
                           count=1, dtype="uint8", crs="EPSG:32645", transform=self.transform,
                           nodata=0) as ds:
            ds.write(classes, 1)

    def write_metadata(self, scene_time, cloud, include_scl):
        row = {
            "hotspot_cell_id": "cell-a", "status": "chip_created", "chip_path": "chip.tif",
            "scene_datetime_utc": scene_time, "selected_stac_item": "test-item",
            "eo_cloud_cover_percent_scene_level": 12.0,
            "local_scl_cloud_shadow_percent": cloud,
        }
        if include_scl:
            row["scl_chip_path"] = "scl.tif"
        pd.DataFrame([row]).to_csv(self.sat / "scene_metadata.csv", index=False)

    def frame(self, dates=("2026-01-20 05:00",)):
        return pd.DataFrame({
            "hotspot_cell_id": ["cell-a"] * len(dates),
            "longitude": [86.0] * len(dates), "latitude": [23.5] * len(dates),
            "acquisition_datetime_utc": pd.to_datetime(list(dates), utc=True),
        })

    def test_loads_compatible_metadata_and_chip_with_clear_scl(self):
        features, counts = add_sentinel_features(self.frame(), self.sat, self.root)
        self.assertTrue(features.loc[0, "s2_pixel_valid"])
        self.assertEqual(features.loc[0, "s2_b04_red_dn"], 125)
        self.assertEqual(features.loc[0, "s2_scl_class"], 4)
        self.assertEqual(counts["rows_with_valid_causal_spectral_samples"], 1)

    def test_future_scene_is_withheld(self):
        self.write_metadata("2026-01-20T06:00:00Z", 0, include_scl=True)
        features, _ = add_sentinel_features(self.frame(("2026-01-20 05:00",)), self.sat, self.root)
        self.assertFalse(features.loc[0, "s2_temporally_eligible"])
        self.assertEqual(features.loc[0, "s2_spectral_data_status"], "post_detection_imagery_withheld")
        self.assertTrue(pd.isna(features.loc[0, "s2_b04_red_dn"]))

    def test_missing_metadata_is_explicit(self):
        features, counts = add_sentinel_features(self.frame(), None, self.root)
        self.assertFalse(features.loc[0, "s2_pixel_valid"])
        self.assertTrue(pd.isna(features.loc[0, "s2_b04_red_dn"]))
        self.assertEqual(features.loc[0, "s2_spectral_data_status"], "not_available_no_scene_metadata")
        self.assertEqual(counts["metadata_available"], 0)

    def test_cloud_or_shadow_scl_class_is_masked(self):
        self.write_scl(np.full((2, 2), 9, dtype=np.uint8))
        features, counts = add_sentinel_features(self.frame(), self.sat, self.root)
        self.assertFalse(features.loc[0, "s2_pixel_valid"])
        self.assertEqual(features.loc[0, "s2_spectral_data_status"], "cloud_shadow_contaminated_or_unverified")
        self.assertTrue(pd.isna(features.loc[0, "s2_b04_red_dn"]))
        self.assertEqual(counts["rows_with_cloud_or_unverifiable_pixel_screen"], 1)

    def test_legacy_cloudy_chip_is_conservatively_unusable(self):
        self.write_metadata("2026-01-20T04:00:00Z", 8.5, include_scl=False)
        features, _ = add_sentinel_features(self.frame(), self.sat, self.root)
        self.assertFalse(features.loc[0, "s2_pixel_valid"])
        self.assertEqual(features.loc[0, "s2_pixel_cloud_screen_status"], "legacy_chip_point_quality_unverifiable")

    def test_legacy_zero_cloud_chip_can_be_sampled(self):
        self.write_metadata("2026-01-20T04:00:00Z", 0, include_scl=False)
        features, _ = add_sentinel_features(self.frame(), self.sat, self.root)
        self.assertTrue(features.loc[0, "s2_pixel_valid"])
        self.assertEqual(features.loc[0, "s2_pixel_cloud_screen_status"], "legacy_chip_zero_cloud_fraction")

    def test_latest_compatible_satellite_run_is_discovered(self):
        self.assertEqual(discover_satellite_run(self.root), self.sat)

    def test_firms_time_is_parsed_as_utc_before_satellite_cutoff(self):
        source = pd.DataFrame({"acq_date": ["2026-01-20"], "acq_time": [53]})
        self.assertEqual(latest_firms_timestamp_utc(source).isoformat(), "2026-01-20T00:53:00+00:00")

    def test_cell_selection_stratifies_and_spreads_over_tiles(self):
        region = get_region("jharkhand")
        recurrence = pd.DataFrame({
            "hotspot_cell_id": ["industrial-cell", "power-cell", "other-cell"],
            "centroid_longitude": [86.4, 85.3, 83.6],
            "centroid_latitude": [23.8, 23.3, 23.97],
            "distinct_acquisition_dates": [8, 6, 4], "detection_observations": [20, 12, 7],
        })
        ranking = pd.DataFrame({
            "hotspot_cell_id": ["industrial-cell", "power-cell", "other-cell"],
            "candidate_category": [
                "persistent_thermal_with_nearby_relevant_industrial_context",
                "persistent_thermal_near_general_power_infrastructure_only",
                "other_thermal_observation_review",
            ],
            "candidate_evidence_score": [0.8, 0.6, 0.4], "firms_source_row": [1, 2, 3],
            "cell_prior_distinct_acquisition_dates": [4, 3, 1],
        })
        selected = select_investigation_cells(recurrence, pd.DataFrame(), ranking, region, 3, "jharkhand")
        self.assertEqual(set(selected), {"industrial-cell", "power-cell", "other-cell"})
        self.assertEqual(len(selected), len(set(selected)))


if __name__ == "__main__":
    unittest.main()
