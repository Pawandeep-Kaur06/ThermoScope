import unittest

import pandas as pd

from src.evaluate_final_pilot import CATEGORIES, classify_at_thresholds


class FinalPilotEvaluationTests(unittest.TestCase):
    def test_counterfactual_thresholds_preserve_rows_and_reproduce_250m_categories(self):
        ranking = pd.DataFrame({
            "candidate_category": [
                CATEGORIES[0], CATEGORIES[0], CATEGORIES[4], CATEGORIES[4], CATEGORIES[5]
            ],
            "thermal_frp_mw": [2.0, 2.0, 6.0, 6.0, 1.0],
            "cell_prior_distinct_acquisition_dates": [5, 5, 0, 0, 0],
            "osm_nearest_relevant_distance_m": [50.0, 200.0, 500.0, None, None],
            "nearest_general_power_infrastructure_distance_m": [None, 900.0, None, None, None],
        })
        result = classify_at_thresholds(ranking, thresholds=(100, 250, 500))
        self.assertEqual(len(result), len(ranking) * 3)
        at_250 = result.loc[result.threshold_m.eq(250), "candidate_category"].tolist()
        self.assertEqual(at_250, ranking.candidate_category.tolist())
        at_500 = result.loc[result.threshold_m.eq(500), "candidate_category"].tolist()
        self.assertEqual(at_500[2], CATEGORIES[3])

    def test_unknown_distance_does_not_create_mapped_context(self):
        ranking = pd.DataFrame({
            "candidate_category": [CATEGORIES[4]], "thermal_frp_mw": [8.0],
            "cell_prior_distinct_acquisition_dates": [0],
            "osm_nearest_relevant_distance_m": [float("nan")],
            "nearest_general_power_infrastructure_distance_m": [float("nan")],
        })
        result = classify_at_thresholds(ranking, thresholds=(1000,))
        self.assertEqual(result.candidate_category.iloc[0], CATEGORIES[4])


if __name__ == "__main__":
    unittest.main()
