import unittest

import pandas as pd

from src.generate_final_pilot_analysis import parse_tags, validate_inputs


class FinalPilotAnalysisTests(unittest.TestCase):
    def frames(self):
        n = 9220
        ids = [f"obs-{i}" for i in range(n)]
        firms = pd.DataFrame({
            "latitude": [23.6] * n, "longitude": [86.3] * n,
            "acq_date": ["2026-01-01"] * n, "frp": [1.0] * n,
            "confidence": ["n"] * n, "firms_observation_id": ids,
        })
        matching = pd.DataFrame({
            "latitude": [23.6] * n, "longitude": [86.3] * n,
            "firms_observation_id": ids, "distance_crs": ["EPSG:32645"] * n,
        })
        features = pd.DataFrame({
            "latitude": [23.6] * n, "longitude": [86.3] * n,
            "acq_date": ["2026-01-01"] * n, "firms_observation_id": ids,
            "hotspot_cell_id": ["cell-1"] * n,
            "cell_prior_distinct_acquisition_dates": [0] * n,
            "s2_spectral_data_status": ["not_available_no_chip"] * n,
        })
        ranking = pd.DataFrame({
            "latitude": [23.6] * n, "longitude": [86.3] * n,
            "acq_date": ["2026-01-01"] * n, "firms_source_row": list(range(n)),
            "candidate_category": ["review"] * n,
            "firms_detection_label": ["unknown_unlinked"] * n,
        })
        return firms, matching, features, ranking

    def test_parse_osm_tag_dict_formats(self):
        self.assertEqual(parse_tags("{'power': 'tower'}"), {"power": "tower"})
        self.assertEqual(parse_tags('{"landuse":"quarry"}'), {"landuse": "quarry"})
        self.assertEqual(parse_tags("not tags"), {})

    def test_aligned_observation_interfaces_validate(self):
        summary = validate_inputs(*self.frames())
        self.assertEqual(summary["rows"], 9220)
        self.assertEqual(summary["unique_ids"], 9220)
        self.assertEqual(summary["matching_crs"], ["EPSG:32645"])

    def test_out_of_region_coordinates_are_rejected(self):
        firms, matching, features, ranking = self.frames()
        firms.loc[0, "latitude"] = 24.1
        with self.assertRaisesRegex(ValueError, "outside the configured pilot bbox"):
            validate_inputs(firms, matching, features, ranking)

    def test_duplicate_observation_ids_are_rejected(self):
        firms, matching, features, ranking = self.frames()
        firms.loc[1, "firms_observation_id"] = firms.loc[0, "firms_observation_id"]
        with self.assertRaisesRegex(ValueError, "missing or duplicated"):
            validate_inputs(firms, matching, features, ranking)


if __name__ == "__main__":
    unittest.main()
