import unittest

import pandas as pd

from src.create_pilot_case_studies import classify_osm, parse_dict, select_representative_cases


class PilotCaseStudyTests(unittest.TestCase):
    def test_category_balanced_quantile_selection_is_not_top_only(self):
        rows = []
        for category in ("persistent", "elevated", "other"):
            for i in range(20):
                rows.append({"candidate_category": category, "review_priority_rank": i + 1,
                             "firms_source_row": f"{category}-{i}", "hotspot_cell_id": f"{category}-cell-{i}"})
        selected = select_representative_cases(pd.DataFrame(rows))
        self.assertEqual(len(selected), 6)
        self.assertEqual(selected.groupby("candidate_category").size().to_dict(),
                         {"elevated": 2, "other": 2, "persistent": 2})
        self.assertTrue((selected.review_priority_rank > 1).all())
        self.assertTrue(selected.firms_source_row.is_unique)

    def test_osm_towers_and_quarries_are_separate_categories(self):
        tower = pd.Series({"all_tags": "{'power': 'tower'}", "feature_groups": '["power_infrastructure"]'})
        quarry = pd.Series({"all_tags": "{'landuse': 'quarry'}", "feature_groups": '["mining_extraction"]'})
        self.assertEqual(classify_osm(tower), "power transmission tower")
        self.assertEqual(classify_osm(quarry), "mining extraction")
        self.assertEqual(parse_dict("not a tag dictionary"), {})

    def test_existing_chip_can_be_selected_near_second_quantile(self):
        frame = pd.DataFrame({
            "candidate_category": ["category"] * 20,
            "review_priority_rank": list(range(1, 21)),
            "firms_source_row": list(range(20)),
            "hotspot_cell_id": [f"cell-{i}" for i in range(20)],
            "s2_chip_available_for_context": [False] * 19 + [True],
        })
        selected = select_representative_cases(frame)
        self.assertEqual(len(selected), 2)
        self.assertTrue(bool(selected.iloc[1].s2_chip_available_for_context))
        self.assertIn("75th percentile", selected.iloc[1].case_stratum_position)


if __name__ == "__main__":
    unittest.main()
