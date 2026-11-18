"""Small, network-free tests for FIRMS pilot preparation."""

import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.prepare_firms_pilot import InputValidationError, prepare
from src.regions import RegionConfigurationError, get_region, select_projected_crs


ARCHIVE_COLUMNS = [
    "latitude", "longitude", "brightness", "scan", "track", "acq_date",
    "acq_time", "satellite", "instrument", "confidence", "version",
    "bright_t31", "frp", "daynight", "type",
]
NRT_COLUMNS = [column for column in ARCHIVE_COLUMNS if column != "type"]


def record(latitude, longitude, *, date="2026-01-20", time="0005", version="2", scan="0.5", track="0.6"):
    return {
        "latitude": latitude, "longitude": longitude, "brightness": "340.1",
        "scan": scan, "track": track, "acq_date": date, "acq_time": time,
        "satellite": "SNPP", "instrument": "VIIRS", "confidence": "n",
        "version": version, "bright_t31": "300.0", "frp": "3.2",
        "daynight": "N", "type": "0",
    }


class PrepareFirmsPilotTests(unittest.TestCase):
    def test_filters_bounds_preserves_source_and_deduplicates_overlap(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive_rows = [
                record("23.25", "85.75"),
                record("23.50", "86.00", date="2026-01-21", time="0100"),
                record("bad-coordinate", "86.00"),
                record("95.0", "86.00"),
                record("22.9", "86.00"),
            ]
            nrt_rows = [
                record("23.250000", "85.750000", version="2.0NRT"),
                record("24.00", "86.75", date="2026-01-22", time="2000"),
                record("", "86.00"),
            ]
            archive, nrt = root / "archive.csv", root / "nrt.csv"
            pd.DataFrame(archive_rows, columns=ARCHIVE_COLUMNS).to_csv(archive, index=False)
            pd.DataFrame(nrt_rows, columns=NRT_COLUMNS).to_csv(nrt, index=False)
            output = root / "prepared.csv"

            report = prepare(archive, nrt, output, chunksize=2)

            prepared = pd.read_csv(output, dtype=str, keep_default_na=False)
            self.assertEqual(len(prepared), 3)
            self.assertEqual(report["deduplication"]["duplicate_input_rows_removed"], 1)
            self.assertEqual(report["deduplication"]["cross_source_overlap_rows"], 1)
            self.assertEqual(report["coordinate_validation"]["invalid_or_missing_coordinate_rows_excluded"], 2)
            self.assertEqual(report["coordinate_validation"]["out_of_geographic_range_rows_excluded"], 1)
            self.assertEqual(report["output"]["date_coverage"]["distinct_acquisition_dates"], 3)

            lower = prepared[(prepared.latitude == "23.25") & (prepared.longitude == "85.75")].iloc[0]
            upper = prepared[(prepared.latitude == "24.00") & (prepared.longitude == "86.75")].iloc[0]
            self.assertEqual(lower.firms_sources, "archive+nrt")
            self.assertEqual(lower.version, "2")  # Archive attributes are canonical.
            self.assertEqual(lower.duplicate_record_count, "1")
            self.assertEqual(upper.firms_sources, "nrt")
            self.assertEqual(upper.type, "")  # Missing source-only field remains missing.
            quality = json.loads(output.with_suffix(".csv.quality.json").read_text(encoding="utf-8"))
            self.assertEqual(quality["output"]["row_count"], 3)

    def test_missing_input_and_missing_required_columns_fail_clearly(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            absent = root / "absent.csv"
            good = root / "good.csv"
            pd.DataFrame([record("23.5", "86.0")], columns=ARCHIVE_COLUMNS).to_csv(good, index=False)
            with self.assertRaisesRegex(InputValidationError, "does not exist"):
                prepare(absent, good, root / "missing.csv")

            bad = root / "bad.csv"
            pd.DataFrame([{"lat": 23.5, "lon": 86.0}]).to_csv(bad, index=False)
            with self.assertRaisesRegex(InputValidationError, "missing required column"):
                prepare(good, bad, root / "invalid.csv")

    def test_existing_output_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive, nrt = root / "archive.csv", root / "nrt.csv"
            pd.DataFrame([record("23.5", "86.0")], columns=ARCHIVE_COLUMNS).to_csv(archive, index=False)
            pd.DataFrame([record("23.5", "86.0")], columns=NRT_COLUMNS).to_csv(nrt, index=False)
            output = root / "prepared.csv"
            output.write_text("keep me", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                prepare(archive, nrt, output)
            self.assertEqual(output.read_text(encoding="utf-8"), "keep me")

    def test_valid_cache_is_reused_and_changed_input_is_archived_before_rebuild(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive, nrt, output = root / "archive.csv", root / "nrt.csv", root / "prepared.csv"
            pd.DataFrame([record("23.5", "86.0")], columns=ARCHIVE_COLUMNS).to_csv(archive, index=False)
            pd.DataFrame([], columns=NRT_COLUMNS).to_csv(nrt, index=False)
            first = prepare(archive, nrt, output)
            original_bytes = output.read_bytes()
            cached = prepare(archive, nrt, output)
            self.assertEqual(cached["output"]["row_count"], first["output"]["row_count"])
            self.assertEqual(output.read_bytes(), original_bytes)
            pd.DataFrame([record("23.5", "86.0"), record("23.6", "86.1", date="2026-01-21")],
                         columns=ARCHIVE_COLUMNS).to_csv(archive, index=False)
            rebuilt = prepare(archive, nrt, output)
            self.assertEqual(rebuilt["output"]["row_count"], 2)
            self.assertTrue(list(root.glob("prepared.csv.stale_*")))

    def test_pilot_region_default_and_stable_observation_id(self):
        region = get_region("dhanbad_jharia_bokaro")
        self.assertEqual(region["bbox_wgs84"], {"west": 85.75, "south": 23.25, "east": 86.75, "north": 24.0})
        self.assertEqual(select_projected_crs(region), "EPSG:32645")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive, nrt = root / "archive.csv", root / "nrt.csv"
            row = record("23.25", "85.75")
            pd.DataFrame([row], columns=ARCHIVE_COLUMNS).to_csv(archive, index=False)
            pd.DataFrame([], columns=NRT_COLUMNS).to_csv(nrt, index=False)
            output = root / "pilot.csv"
            report = prepare(archive, nrt, output)
            result = pd.read_csv(output, dtype=str)
            self.assertEqual(report["region"]["id"], "dhanbad_jharia_bokaro")
            self.assertEqual(len(result), 1)
            self.assertEqual(len(result.loc[0, "firms_observation_id"]), 64)

    def test_india_mode_and_invalid_region(self):
        india = get_region("india")
        self.assertEqual(india["projected_crs_strategy"], "utm_per_tile")
        with self.assertRaisesRegex(RegionConfigurationError, "multiple UTM zones"):
            select_projected_crs(india)
        self.assertEqual(select_projected_crs(india, longitude=86.0, latitude=23.5), "EPSG:32645")
        with self.assertRaisesRegex(RegionConfigurationError, "Unknown region ID"):
            get_region("not_a_region")

    def test_india_wide_preparation_retains_points_outside_pilot(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive, nrt, output = root / "archive.csv", root / "nrt.csv", root / "india.csv"
            pd.DataFrame([record("28.61", "77.20"), record("3.0", "77.0"),
                          record("27.717", "85.324", date="2026-01-21")], columns=ARCHIVE_COLUMNS).to_csv(archive, index=False)
            pd.DataFrame([], columns=NRT_COLUMNS).to_csv(nrt, index=False)
            report = prepare(archive, nrt, output, region_id="india")
            prepared = pd.read_csv(output, dtype=str)
            self.assertEqual(len(prepared), 1)
            self.assertEqual(prepared.loc[0, "region_id"], "india")
            self.assertEqual(report["region"]["id"], "india")
            self.assertEqual(report["coordinate_validation"]["region_membership"],
                             "configured country polygon covers point, in addition to the stable region/tile-grid bounding extent")

    def test_maximum_boundary_policy(self):
        import pandas as pd
        from src.regions import contains_coordinates
        pilot = get_region("dhanbad_jharia_bokaro")
        lon = pd.Series([85.75, 86.75, 86.75001])
        lat = pd.Series([23.25, 24.0, 24.0])
        self.assertEqual(contains_coordinates(lon, lat, pilot).tolist(), [True, True, False])

    def test_adjacent_region_tile_owns_shared_edge_once(self):
        import pandas as pd
        from src.regions import contains_coordinates
        west_tile = {"bbox_wgs84": {"west": 75, "south": 18, "east": 76, "north": 20}, "max_inclusive": False}
        east_tile = {"bbox_wgs84": {"west": 76, "south": 18, "east": 77, "north": 20}, "max_inclusive": True}
        lon, lat = pd.Series([76.0]), pd.Series([19.0])
        self.assertFalse(bool(contains_coordinates(lon, lat, west_tile).iloc[0]))
        self.assertTrue(bool(contains_coordinates(lon, lat, east_tile).iloc[0]))

    def test_custom_regions_need_no_pipeline_code_change(self):
        import json
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "regions.json"
            config = json.loads(Path("config/regions.json").read_text(encoding="utf-8"))
            config["regions"]["example_region"] = {
                "name": "Example region", "boundary_type": "bbox",
                "bbox_wgs84": {"west": 75, "south": 18, "east": 77, "north": 20},
                "max_inclusive": False, "projected_crs_strategy": "utm_from_region_center"
            }
            path.write_text(json.dumps(config), encoding="utf-8")
            self.assertEqual(select_projected_crs(get_region("example_region", path)), "EPSG:32643")


if __name__ == "__main__":
    unittest.main()
