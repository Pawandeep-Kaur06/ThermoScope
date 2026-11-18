"""GEM acquisition cache checks are offline and checksum-aware."""
import json
import tempfile
import unittest
from pathlib import Path

from src.fetch_gem_references import DATASETS, existing_gem_cache_is_valid
from src.pipeline_cache import artifact_record, atomic_json


class GemCacheTests(unittest.TestCase):
    def test_valid_local_snapshot_skips_api_and_corruption_invalidates(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw_dir, processed = root / "raw", root / "processed"
            raw_dir.mkdir(); processed.mkdir()
            manifest = {"source": "Global Energy Monitor (GEM) Assets API", "retrieved_at_utc": "2026-01-01T00:00:00Z", "datasets": {}}
            for key, config in DATASETS.items():
                record = {"asset_id": key, "country": "India", "state_province": "Jharkhand", "latitude": 23.5, "longitude": 86.0}
                raw_path = raw_dir / config["raw_file"]
                filtered_path = processed / config["filtered_file"]
                raw_path.write_text(json.dumps({"results": [record]}), encoding="utf-8")
                filtered_path.write_text(json.dumps({"record_count": 1, "records": [record]}), encoding="utf-8")
                manifest["datasets"][config["name"]] = {"state_record_count": 1, "filtered_record_count": 1}
                atomic_json(raw_dir / (config["raw_file"] + ".cache.json"), {
                    "artifacts": {"raw": artifact_record(raw_path), "filtered": artifact_record(filtered_path)}})
            (raw_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            self.assertTrue(existing_gem_cache_is_valid(raw_dir, processed))
            (processed / DATASETS["coal-mine"]["filtered_file"]).write_text("truncated", encoding="utf-8")
            self.assertFalse(existing_gem_cache_is_valid(raw_dir, processed))


if __name__ == "__main__":
    unittest.main()
