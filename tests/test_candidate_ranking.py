"""Tests for the transparent non-supervised candidate evidence rules."""
import unittest

import numpy as np
import pandas as pd

from src.rank_firms_candidates import build_candidate_ranking


def example(**updates):
    row = {
        "firms_source_row": 10, "latitude": 23.5, "longitude": 86.0,
        "acq_date": "2026-08-20", "acq_time": 600,
        "acquisition_datetime_utc": "2026-08-20T06:00:00Z",
        "thermal_frp_mw": 6.0, "thermal_brightness_k": 330.0,
        "thermal_brightness_t31_k": 300.0, "confidence": "n", "daynight": "D",
        "hotspot_cell_id": "utm45n_1_1", "cell_prior_detection_count": 12,
        "cell_prior_distinct_acquisition_dates": 4,
        "cell_prior_last_acquisition_date": "2026-08-19", "cell_days_since_prior_observation": 1,
        "osm_nearest_relevant_distance_m": 100.0, "osm_nearest_relevant_role": "mining_extraction_area",
        "osm_nearest_relevant_category": "mining_extraction", "osm_evidence_status_250m": "proximity_candidate",
        "nearest_power_transmission_tower_distance_m": 600.0,
        "nearest_power_transmission_line_distance_m": 550.0,
        "nearest_power_transmission_other_distance_m": np.nan,
        "nearest_power_distribution_distance_m": np.nan, "nearest_power_other_distance_m": np.nan,
        "gem_nearest_distance_m": 400.0, "gem_nearest_name": "Example mine", "gem_nearest_type": "Mine",
        "s2_spectral_data_status": "not_available_no_chip", "s2_pixel_valid": False,
        "s2_spectral_predictor_eligible": False, "s2_scene_datetime_utc": pd.NA,
        "s2_scene_offset_hours": np.nan, "s2_scene_cloud_cover_percent": np.nan,
        "s2_chip_scl_cloud_shadow_percent": np.nan, "s2_pixel_cloud_screen_status": "no_sentinel_metadata",
        "s2_b04_red_dn": np.nan, "s2_b03_green_dn": np.nan,
        "s2_b02_blue_dn": np.nan, "s2_b11_swir16_dn": np.nan,
    }
    row.update(updates)
    return pd.DataFrame([row])


class CandidateRankingTests(unittest.TestCase):
    def test_rules_create_candidate_evidence_category_but_never_label(self):
        ranked = build_candidate_ranking(example())
        self.assertEqual(ranked.loc[0, "candidate_category"], "persistent_thermal_with_nearby_relevant_industrial_context")
        self.assertEqual(ranked.loc[0, "firms_detection_label"], "unknown_unlinked")
        self.assertIn("at least 3 strictly prior distinct detection dates", ranked.loc[0, "evidence_rationale"])
        self.assertGreaterEqual(ranked.loc[0, "candidate_evidence_score"], 0)
        self.assertLessEqual(ranked.loc[0, "candidate_evidence_score"], 1)

    def test_missing_imagery_is_explicit_and_does_not_change_evidence_score(self):
        without_satellite = example().drop(columns=[
            "s2_b04_red_dn", "s2_b03_green_dn", "s2_b02_blue_dn", "s2_b11_swir16_dn",
            "s2_pixel_valid", "s2_spectral_predictor_eligible", "s2_spectral_data_status",
        ])
        a = build_candidate_ranking(example())
        b = build_candidate_ranking(without_satellite)
        self.assertFalse(a.loc[0, "sentinel2_clear_pre_detection_spectrum_available"])
        self.assertEqual(a.loc[0, "sentinel2_review_context"], "not_available_no_chip")
        self.assertEqual(a.loc[0, "candidate_evidence_score"], b.loc[0, "candidate_evidence_score"])

    def test_ambiguous_osm_context_is_flagged_and_downweighted(self):
        clear = build_candidate_ranking(example())
        ambiguous = build_candidate_ranking(example(osm_evidence_status_250m="ambiguous_proximity"))
        self.assertTrue(ambiguous.loc[0, "osm_match_ambiguous_flag"])
        self.assertEqual(ambiguous.loc[0, "osm_context_evidence_quality"], "ambiguous_mapped_context")
        self.assertAlmostEqual(ambiguous.loc[0, "mapped_relevant_context_component"],
                               clear.loc[0, "mapped_relevant_context_component"] * 0.5)
        self.assertEqual(ambiguous.loc[0, "firms_detection_label"], "unknown_unlinked")

    def test_general_power_infrastructure_is_not_industrial_context(self):
        ranked = build_candidate_ranking(example(
            cell_prior_distinct_acquisition_dates=0,
            cell_prior_last_acquisition_date=pd.NA,
            osm_nearest_relevant_distance_m=np.nan,
            osm_nearest_relevant_role=pd.NA,
            osm_evidence_status_250m="unknown_no_relevant_osm_within_250m",
            nearest_power_transmission_tower_distance_m=20.0,
        ))
        self.assertTrue(ranked.loc[0, "power_infrastructure_only_context_flag"])
        self.assertFalse(ranked.loc[0, "osm_relevant_context_within_250m"])
        self.assertEqual(ranked.loc[0, "candidate_category"], "elevated_thermal_without_nearby_relevant_osm_context")

    def test_recurrence_leakage_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Temporal leakage"):
            build_candidate_ranking(example(cell_prior_last_acquisition_date="2026-08-20"))

    def test_future_sentinel_spectrum_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Temporal leakage"):
            build_candidate_ranking(example(
                s2_pixel_valid=True, s2_spectral_predictor_eligible=True,
                s2_spectral_data_status="sampled_pre_detection_image",
                s2_scene_datetime_utc="2026-08-20T07:00:00Z",
                s2_b04_red_dn=100, s2_b03_green_dn=100, s2_b02_blue_dn=100, s2_b11_swir16_dn=100,
            ))

    def test_valid_sentinel_sample_is_exposed_without_changing_candidate_class_rule(self):
        data = example(
            s2_pixel_valid=True, s2_spectral_predictor_eligible=True,
            s2_spectral_data_status="sampled_pre_detection_image",
            s2_scene_datetime_utc="2026-08-20T05:30:00Z",
            s2_b04_red_dn=100, s2_b03_green_dn=120, s2_b02_blue_dn=80, s2_b11_swir16_dn=200,
        )
        ranked = build_candidate_ranking(data)
        self.assertTrue(ranked.loc[0, "sentinel2_clear_pre_detection_spectrum_available"])
        self.assertEqual(ranked.loc[0, "candidate_category"], "persistent_thermal_with_nearby_relevant_industrial_context")
        self.assertEqual(ranked.loc[0, "firms_detection_label"], "unknown_unlinked")


if __name__ == "__main__":
    unittest.main()
