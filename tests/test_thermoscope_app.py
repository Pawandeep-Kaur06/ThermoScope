import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from affine import Affine
from PIL import Image
from rasterio.io import MemoryFile
from shapely.geometry import Point

from src.thermoscope_app.core import (EvidenceRepository, UploadError, cv_inference,
                                      inspect_upload, load_jharkhand_map_data)


class ImageUploadTests(unittest.TestCase):
    def test_local_map_boundary_is_valid_and_carries_provenance(self):
        from shapely.geometry import shape
        result = load_jharkhand_map_data()
        geometry = shape(result["geometry"])
        self.assertTrue(geometry.is_valid)
        self.assertTrue(geometry.covers(Point(85.3, 23.6)))
        self.assertFalse(geometry.covers(Point(77.2, 28.6)))
        self.assertIn("OpenStreetMap", result["source"])
        self.assertIn("bbox_wgs84", result)

    def test_png_upload_validates_and_builds_preview(self):
        import io
        stream = io.BytesIO()
        Image.fromarray(np.full((20, 30, 3), 80, dtype=np.uint8)).save(stream, format="PNG")
        result = inspect_upload("scene.png", stream.getvalue())
        self.assertEqual((result["width"], result["height"], result["bands"]), (30, 20, 3))
        self.assertTrue(result["preview_data_url"].startswith("data:image/png;base64,"))
        self.assertIsNone(result["longitude"])

    def test_geotiff_metadata_is_extracted(self):
        data = np.arange(3 * 32 * 24, dtype=np.uint16).reshape(3, 24, 32)
        with MemoryFile() as mem:
            with mem.open(driver="GTiff", width=32, height=24, count=3, dtype="uint16",
                          crs="EPSG:32645", transform=Affine(10, 0, 400000, 0, -10, 2600000)) as dst:
                dst.write(data)
                dst.update_tags(ACQUISITION_DATE="2026-05-08T05:00:00Z")
            payload = mem.read()
        result = inspect_upload("uploaded.tif", payload)
        self.assertEqual(result["acquisition_date"], "2026-05-08")
        self.assertEqual(result["crs"], "EPSG:32645")
        self.assertIsNotNone(result["longitude"])
        self.assertIsNotNone(result["latitude"])
        self.assertEqual(len(result["bounds_wgs84"]), 4)

    def test_unsupported_corrupt_and_oversized_files_rejected(self):
        with self.assertRaises(UploadError):
            inspect_upload("image.bmp", b"not an image")
        with self.assertRaises(UploadError):
            inspect_upload("image.png", b"not an image")
        with self.assertRaises(UploadError):
            inspect_upload("image.png", b"x" * (25 * 1024 * 1024 + 1))

    def test_model_interface_does_not_fabricate_prediction(self):
        result = cv_inference("unused")
        self.assertEqual(result["status"], "unavailable")
        self.assertIsNone(result["prediction"])

    def test_satellite_context_requires_upload_date(self):
        repo = EvidenceRepository(Path("unused"), Path("unused"), Path("unused"), Path("unused"))
        result = repo._sentinel_context(86.0, 23.0, None)
        self.assertEqual(result["status"], "date_required_for_temporal_eligibility")
        self.assertIsNone(result["record"])

    def test_satellite_context_excludes_same_day_and_future_scenes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            chip = root / "prior.tif"
            with rasterio.open(chip, "w", driver="GTiff", width=16, height=16, count=3,
                               dtype="uint16", crs="EPSG:32645", transform=Affine(10, 0, 400000, 0, -10, 2600000)) as dst:
                dst.write(np.ones((3, 16, 16), dtype=np.uint16))
            metadata = root / "scene_metadata.csv"
            pd.DataFrame([
                {"hotspot_cell_id": "prior", "status": "chip_created", "scene_datetime_utc": "2026-05-07T05:00:00Z", "selected_stac_item": "prior-scene", "chip_path": str(chip), "eo_cloud_cover_percent_scene_level": 10, "local_scl_cloud_shadow_percent": 0},
                {"hotspot_cell_id": "same", "status": "chip_created", "scene_datetime_utc": "2026-05-08T05:00:00Z", "selected_stac_item": "same-day-scene", "chip_path": str(chip), "eo_cloud_cover_percent_scene_level": 10, "local_scl_cloud_shadow_percent": 0},
                {"hotspot_cell_id": "future", "status": "chip_created", "scene_datetime_utc": "2026-05-09T05:00:00Z", "selected_stac_item": "future-scene", "chip_path": str(chip), "eo_cloud_cover_percent_scene_level": 10, "local_scl_cloud_shadow_percent": 0},
            ]).to_csv(metadata, index=False)
            pd.DataFrame([
                {"hotspot_cell_id": "prior", "centroid_longitude": 86.0, "centroid_latitude": 23.0},
                {"hotspot_cell_id": "same", "centroid_longitude": 86.0, "centroid_latitude": 23.0},
                {"hotspot_cell_id": "future", "centroid_longitude": 86.0, "centroid_latitude": 23.0},
            ]).to_csv(root / "selected_investigation_cells.csv", index=False)
            repo = EvidenceRepository(Path("unused"), Path("unused"), Path("unused"), metadata)
            result = repo._sentinel_context(86.0, 23.0, "2026-05-08")
            self.assertEqual(result["status"], "context_only")
            self.assertEqual(result["record"]["scene_item_id"], "prior-scene")


class EvidenceTests(unittest.TestCase):
    def test_firms_spatial_filter_and_strictly_past_recurrence(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw_path = Path(tmp) / "firms.csv"
            feature_path = Path(tmp) / "features.csv.gz"
            lon, lat = 85.5, 23.5
            rows = pd.DataFrame([
                {"firms_observation_id": "past-1", "latitude": lat, "longitude": lon,
                 "acq_date": "2026-01-01", "acq_time": 100, "frp": 2.0, "confidence": "n"},
                {"firms_observation_id": "past-2", "latitude": lat + 0.0002, "longitude": lon,
                 "acq_date": "2026-01-03", "acq_time": 200, "frp": 3.0, "confidence": "h"},
                {"firms_observation_id": "same-day", "latitude": lat, "longitude": lon,
                 "acq_date": "2026-01-05", "acq_time": 100, "frp": 4.0, "confidence": "h"},
                {"firms_observation_id": "future", "latitude": lat, "longitude": lon,
                 "acq_date": "2026-01-06", "acq_time": 100, "frp": 5.0, "confidence": "h"},
                {"firms_observation_id": "far", "latitude": lat + 0.1, "longitude": lon,
                 "acq_date": "2026-01-04", "acq_time": 100, "frp": 6.0, "confidence": "h"},
            ])
            base = rows[["firms_observation_id", "latitude", "longitude", "acq_date", "acq_time", "frp", "confidence"]]
            base.to_csv(raw_path, index=False)
            rows.assign(cell_prior_detection_count=1, cell_prior_distinct_acquisition_dates=1).to_csv(feature_path, index=False, compression="gzip")
            repo = EvidenceRepository(raw_path, Path("unused"), feature_path, Path("unused"))
            evidence = repo._firms_evidence(lon, lat, "2026-01-05", 1_000, 30)
            ids = {row["firms_observation_id"] for row in evidence["records"]}
            self.assertEqual(ids, {"past-1", "past-2", "same-day"})
            self.assertEqual(evidence["prior_count_within_250m"], 2)
            self.assertEqual(evidence["prior_distinct_dates_within_250m"], 2)

    def test_recurrence_unknown_without_image_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw_path = Path(tmp) / "firms.csv"
            feature_path = Path(tmp) / "features.csv.gz"
            row = {"firms_observation_id": "one", "latitude": 23.5, "longitude": 85.5, "acq_date": "2026-01-01"}
            pd.DataFrame([row]).to_csv(raw_path, index=False)
            pd.DataFrame([row]).to_csv(feature_path, index=False, compression="gzip")
            repo = EvidenceRepository(raw_path, Path("unused"), feature_path, Path("unused"))
            evidence = repo._firms_evidence(85.5, 23.5, None, 1_000, 30)
            self.assertIsNone(evidence["prior_count_within_250m"])
            self.assertIsNone(evidence["prior_distinct_dates_within_250m"])

    def test_prediction_stays_unknown_when_model_and_evidence_inputs_are_missing(self):
        repo = EvidenceRepository(Path("missing-firms.csv"), Path("missing-osm.gpkg"),
                                  Path("missing-features.csv.gz"), Path("missing-scenes.csv"))
        result = repo.analyze(85.5, 23.5, "2026-01-01")
        self.assertTrue(result["within_study_area"])
        self.assertEqual(result["cv"]["status"], "unavailable")
        self.assertIsNone(result["cv"]["prediction"])
        self.assertEqual(result["assessment"], "insufficient_evidence_to_classify")
        self.assertTrue(result["data_warnings"])

    def test_osm_nearest_features_separate_site_and_grid_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            gpkg = Path(tmp) / "osm.gpkg"
            points = gpd.GeoDataFrame({"osm_id": ["1", "2"],
                "all_tags": ['{"landuse":"industrial","name":"Works"}', '{"power":"tower"}']},
                geometry=[Point(85.5, 23.5), Point(85.501, 23.5)], crs="EPSG:4326")
            points.to_file(gpkg, layer="points", driver="GPKG")
            repo = EvidenceRepository(Path("unused"), gpkg, Path("unused"), Path("unused"))
            result = repo._osm_evidence(85.5, 23.5, 1_000)
            groups = {row["context_group"] for row in result["features"]}
            self.assertEqual(groups, {"industrial_or_generation_context", "general_power_infrastructure"})
            self.assertEqual(result["features"][0]["distance_m"], 0)
            self.assertAlmostEqual(result["features"][0]["longitude"], 85.5, places=5)
            self.assertAlmostEqual(result["features"][0]["latitude"], 23.5, places=5)


class MapSearchApiTests(unittest.TestCase):
    def test_map_area_search_passes_selected_center_radius_and_date(self):
        from src.thermoscope_app.server import Handler, ROOT

        class FakeRepository:
            def __init__(self):
                self.arguments = None

            def analyze(self, longitude, latitude, acquisition_date, radius_m, lookback_days):
                self.arguments = (longitude, latitude, acquisition_date, radius_m, lookback_days)
                return {"within_study_area": True, "firms": {"records": []}, "osm": {"features": []}}

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.repository = FakeRepository()
        server.smoke_model_path = ROOT / "missing-smoke-model.pth"
        server.smoke_segmentation_model_path = ROOT / "missing-smoke-segmentation.pth"
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            payload = {"longitude": 86.2, "latitude": 22.8, "radius_m": 1250,
                       "lookback_days": 30, "acquisition_date": "2026-09-03"}
            request = Request(f"http://127.0.0.1:{server.server_port}/api/area-evidence",
                              data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"},
                              method="POST")
            with urlopen(request) as response:
                result = json.load(response)
            self.assertTrue(result["map_selection"])
            self.assertEqual(server.repository.arguments, (86.2, 22.8, "2026-09-03", 1250.0, 30))

            payload["radius_m"] = 20_000
            request = Request(f"http://127.0.0.1:{server.server_port}/api/area-evidence",
                              data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"},
                              method="POST")
            with self.assertRaises(HTTPError) as error:
                urlopen(request)
            self.assertEqual(error.exception.code, 400)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
