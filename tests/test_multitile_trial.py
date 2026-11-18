"""Offline checks for the bounded trial output validator."""
import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.engineer_features import add_past_only_recurrence
from src.regions import assign_recurrence_grid, assign_tile_ids, get_region, tile_for_coordinate
from src.run_multitile_trial import validate_outputs


class MultiTileTrialTests(unittest.TestCase):
    def _write_trial(self, root: Path):
        region = get_region("india")
        longitude, latitude = [86.09995, 86.10005], [23.5, 23.5]
        tiles = assign_tile_ids(longitude, latitude, region)
        rows = pd.DataFrame({
            "firms_source_row": [0, 1], "firms_observation_id": ["obs-0", "obs-1"],
            "longitude": longitude, "latitude": latitude, "tile_id": tiles,
            "distance_crs": [tile_for_coordinate(x, y, region)["projected_crs"] for x, y in zip(longitude, latitude)],
            "hotspot_cell_id": assign_recurrence_grid(longitude, latitude, region),
            "acq_date": ["2026-01-01", "2026-01-02"], "frp": [1.0, 2.0],
        })
        matching = root / "matching"; features = root / "features"
        matching.mkdir(); features.mkdir()
        rows.to_csv(matching / "firms_pilot_osm_proximity.csv", index=False)
        add_past_only_recurrence(rows).to_csv(features / "feature_table.csv.gz", index=False, compression="gzip")
        report_tiles = []
        for tile_id, group in rows.groupby("tile_id"):
            tile = tile_for_coordinate(float(group.longitude.iloc[0]), float(group.latitude.iloc[0]), region)
            report_tiles.append({"tile_id": tile_id, "distance_crs": tile["projected_crs"],
                                 "bbox_wgs84": tile["bbox_wgs84"], "firms_rows": len(group)})
        (matching / "summary.json").write_text(json.dumps({"tile_processing": {"tiles": report_tiles}}), encoding="utf-8")
        firms = root / "firms.csv"
        rows[["longitude", "latitude"]].to_csv(firms, index=False)
        return firms, matching, features, sorted(set(tiles))

    def test_valid_boundary_edge_trial_outputs_and_recurrence_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            firms, matching, features, tiles = self._write_trial(Path(temp))
            result = validate_outputs(firms, matching, features, "india", tiles)
        self.assertTrue(result["checks"]["all_observations_covered_by_india_boundary"])
        self.assertTrue(result["checks"]["tile_assignment_matches_shared_region_function"])
        self.assertTrue(result["checks"]["per_tile_crs_matches_tile_configuration"])
        self.assertTrue(result["checks"]["feature_recurrence_matches_combined_past_only_recalculation"])
        self.assertEqual(result["checks"]["recurrence_cells_crossing_tile_boundaries"], 1)

    def test_duplicate_ids_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            firms, matching, features, tiles = self._write_trial(Path(temp))
            path = matching / "firms_pilot_osm_proximity.csv"
            frame = pd.read_csv(path)
            frame.loc[1, "firms_observation_id"] = frame.loc[0, "firms_observation_id"]
            frame.to_csv(path, index=False)
            with self.assertRaisesRegex(ValueError, "observation_ids_unique"):
                validate_outputs(firms, matching, features, "india", tiles)


if __name__ == "__main__":
    unittest.main()
