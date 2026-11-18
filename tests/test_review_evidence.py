import csv
from argparse import Namespace
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.review_evidence import append_review, date_overlap_report, event_register


class EvidenceReviewTests(unittest.TestCase):
    def test_date_overlap_is_a_candidate_count_not_a_detection_link(self):
        events = event_register()
        features = pd.DataFrame(
            {
                "firms_source_row": [10, 11, 12],
                "acq_date": ["2026-01-22", "2026-01-22", "2026-06-10"],
                "latitude": [23.70, 23.71, 23.76],
                "longitude": [86.4, 86.41, 86.39],
            }
        )
        report = date_overlap_report(events, features).set_index("evidence_id")
        self.assertEqual(report.loc["akashvani_dhanbad_warehouse_2026_01_22", "firms_rows_on_event_date_window"], 2)
        self.assertEqual(report.loc["akashvani_dhanbad_warehouse_2026_01_22", "detection_link_status"], "not_linkable_from_current_record")
        self.assertEqual(report.loc["akashvani_dhanbad_warehouse_2026_01_22", "candidate_firms_source_row"], "")
        self.assertTrue(report.detection_label.eq("unknown_unlinked").all())


    @staticmethod
    def _review_run(tmp_path):
        pd.DataFrame(
            [
                {
                    "evidence_id": "evt1",
                    "source_id": "s1",
                    "event_date_start": "2026-06-10",
                    "event_date_end": "2026-06-10",
                }
            ]
        ).to_csv(tmp_path / "event_register.csv", index=False)
        (tmp_path / "human_review_log.csv").write_text(
            "reviewed_at_utc,evidence_id,scope,decision,firms_source_row,reviewer,reason,source_reference\n",
            encoding="utf-8",
        )
        return tmp_path


    def test_event_acceptance_is_only_event_review_and_is_audited(self):
        with tempfile.TemporaryDirectory() as temp:
            run = self._review_run(Path(temp))
            args = Namespace(
                review_run=run,
                evidence_id="evt1",
                scope="event",
                decision="accepted",
                firms_source_row=None,
                reviewer="reviewer-a",
                reason="Source confirms event but not a FIRMS link.",
                source_reference="https://example.org/report",
                features=None,
            )
            append_review(args)
            with (run / "human_review_log.csv").open(encoding="utf-8", newline="") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["decision"], "accepted")
            self.assertEqual(rows[0]["scope"], "event")
            self.assertEqual(rows[0]["firms_source_row"], "")


    def test_detection_link_review_requires_row_and_event_date(self):
        with tempfile.TemporaryDirectory() as temp:
            run = self._review_run(Path(temp))
            features = Path(temp) / "features.csv"
            pd.DataFrame({"firms_source_row": [5], "acq_date": ["2026-06-10"]}).to_csv(features, index=False)
            args = Namespace(
                review_run=run,
                evidence_id="evt1",
                scope="detection_link",
                decision="unresolved",
                firms_source_row=5,
                reviewer="reviewer-a",
                reason="Inspect location evidence.",
                source_reference="https://example.org/report",
                features=features,
            )
            append_review(args)
            logged = pd.read_csv(run / "human_review_log.csv")
            self.assertEqual(logged.loc[0, "firms_source_row"], 5)
            self.assertEqual(logged.loc[0, "decision"], "unresolved")

            pd.DataFrame({"firms_source_row": [6], "acq_date": ["2026-06-11"]}).to_csv(features, index=False)
            args.firms_source_row = 6
            with self.assertRaisesRegex(ValueError, "outside event date interval"):
                append_review(args)


    def test_detection_link_review_requires_explicit_source_reference(self):
        with tempfile.TemporaryDirectory() as temp:
            run = self._review_run(Path(temp))
            features = Path(temp) / "features.csv"
            pd.DataFrame({"firms_source_row": [5], "acq_date": ["2026-06-10"]}).to_csv(features, index=False)
            args = Namespace(
                review_run=run,
                evidence_id="evt1",
                scope="detection_link",
                decision="accepted",
                firms_source_row=5,
                reviewer="reviewer-a",
                reason="Date and location reviewed.",
                source_reference="",
                features=features,
            )
            with self.assertRaisesRegex(ValueError, "requires --source-reference"):
                append_review(args)


if __name__ == "__main__":
    unittest.main()
