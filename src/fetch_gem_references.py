"""Fetch Jharkhand coal mine and coal plant reference records from GEM's API.

The script keeps the state-filtered API payloads in data/raw/gem/ and writes
bounding-box subsets to data/processed/gem/. It uses only Python's standard
library and does not call OSM/Overpass.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API_BASE = "https://api.globalenergymonitor.org"
API_DOCS = f"{API_BASE}/openapi.json"
BOUNDS = {"min_latitude": 23.25, "max_latitude": 24.00,
          "min_longitude": 85.75, "max_longitude": 86.75}
LIMIT = 500
DATASETS = {
    "coal-mine": {
        "name": "coal_mines",
        "raw_file": "coal_mines_jharkhand.json",
        "filtered_file": "coal_mines_dhanbad_jharia_bbox.json",
        "tracker_page": "https://globalenergymonitor.org/projects/global-coal-mine-tracker",
        "release": "August 2026",
    },
    "coal-plant": {
        "name": "coal_plants",
        "raw_file": "coal_plants_jharkhand.json",
        "filtered_file": "coal_plants_dhanbad_jharia_bbox.json",
        "tracker_page": "https://globalenergymonitor.org/projects/global-coal-plant-tracker",
        "release": "July 2026",
    },
}


def request_page(asset_type: str, offset: int) -> tuple[dict[str, Any], str]:
    params = {
        "asset_type": asset_type,
        "country": "India",
        "state_province": "Jharkhand",
        "limit": LIMIT,
        "offset": offset,
    }
    url = f"{API_BASE}/assets?{urlencode(params)}"
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "ThermoScope academic project"})
    try:
        with urlopen(request, timeout=45) as response:
            body = response.read()
    except HTTPError as exc:
        detail = exc.read(1000).decode("utf-8", errors="replace")
        raise RuntimeError(f"GEM API returned HTTP {exc.code} for {url}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"GEM API unavailable for {url}: {exc.reason}") from exc
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"GEM API returned non-JSON data for {url}: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise RuntimeError(f"Unexpected GEM API response for {url}; expected an object with a results list")
    return payload, url


def retrieve(asset_type: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    offset = 0
    payloads: list[dict[str, Any]] = []
    urls: list[str] = []
    records: list[dict[str, Any]] = []
    expected_total: int | None = None
    while expected_total is None or offset < expected_total:
        payload, url = request_page(asset_type, offset)
        payloads.append(payload)
        urls.append(url)
        page = payload["results"]
        records.extend(page)
        expected_total = int(payload.get("total_asset_count", payload.get("total", len(records))))
        if not page:
            break
        offset += len(page)
    if expected_total is not None and len(records) != expected_total:
        raise RuntimeError(f"Incomplete GEM response for {asset_type}: received {len(records)} of {expected_total} records")
    return records, payloads, urls


def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def in_bounds(record: dict[str, Any]) -> bool:
    lat, lon = record.get("latitude"), record.get("longitude")
    return (is_number(lat) and is_number(lon)
            and BOUNDS["min_latitude"] <= lat <= BOUNDS["max_latitude"]
            and BOUNDS["min_longitude"] <= lon <= BOUNDS["max_longitude"])


def write_json(path: Path, value: Any, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise RuntimeError(f"Refusing to overwrite existing file: {path} (use --overwrite to replace it)")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--overwrite", action="store_true", help="replace this script's generated GEM files")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    raw_dir, processed_dir = repo / "data" / "raw" / "gem", repo / "data" / "processed" / "gem"
    retrieved_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    manifest: dict[str, Any] = {
        "source": "Global Energy Monitor (GEM) Assets API",
        "api_endpoint": f"{API_BASE}/assets",
        "api_documentation": API_DOCS,
        "retrieved_at_utc": retrieved_at,
        "state_query": {"country": "India", "state_province": "Jharkhand"},
        "pilot_bbox_wgs84": BOUNDS,
        "filter_rule": "Inclusive latitude/longitude bounds; records with missing or nonnumeric coordinates are excluded from the filtered copy.",
        "datasets": {},
    }
    completed: list[tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[str]]] = []
    # Fetch and validate both datasets before writing any output.
    for asset_type, config in DATASETS.items():
        records, payloads, urls = retrieve(asset_type)
        for record in records:
            if record.get("country") != "India" or record.get("state_province") != "Jharkhand":
                raise RuntimeError(f"GEM returned an out-of-scope record for {asset_type}: {record.get('asset_id')}")
        selected = [record for record in records if in_bounds(record)]
        field_names = sorted({key for record in records for key in record})
        precision_fields = [key for key in field_names if any(term in key.lower() for term in ("precision", "accuracy", "approx", "exact"))]
        coordinate_records = [r for r in records if is_number(r.get("latitude")) and is_number(r.get("longitude"))]
        missing_coordinate_records = len(records) - len(coordinate_records)
        manifest["datasets"][config["name"]] = {
            "asset_type_filter": asset_type,
            "tracker_page": config["tracker_page"],
            "tracker_release": config["release"],
            "request_urls": urls,
            "state_record_count": len(records),
            "state_unique_location_count": len({r.get("location_id") for r in records if r.get("location_id")}),
            "filtered_record_count": len(selected),
            "pilot_unique_location_count": len({r.get("location_id") for r in selected if r.get("location_id")}),
            "state_records_with_numeric_latitude_and_longitude": len(coordinate_records),
            "state_records_missing_or_nonnumeric_coordinates": missing_coordinate_records,
            "state_records_outside_pilot_bbox": len(records) - len(selected) - missing_coordinate_records,
            "response_fields": field_names,
            "location_precision_fields_present": precision_fields,
            "location_precision_note": "No structured precision field is emitted by the bulk Assets API when this script runs. GEM directs users to each asset's GEM.wiki Project Details for exact/approximate location information.",
        }
        completed.append((config, records, selected, payloads, urls))

    for config, records, selected, payloads, urls in completed:
        raw_payload: Any = payloads[0] if len(payloads) == 1 else {"pages": payloads}
        write_json(raw_dir / config["raw_file"], raw_payload, args.overwrite)
        filtered_payload = {
            "source": "Global Energy Monitor (GEM) Assets API",
            "retrieved_at_utc": retrieved_at,
            "request_urls": urls,
            "tracker_page": config["tracker_page"],
            "tracker_release": config["release"],
            "state_query": {"country": "India", "state_province": "Jharkhand"},
            "pilot_bbox_wgs84": BOUNDS,
            "filter_inclusive": True,
            "record_count": len(selected),
            "records": selected,
        }
        write_json(processed_dir / config["filtered_file"], filtered_payload, args.overwrite)

    write_json(raw_dir / "manifest.json", manifest, args.overwrite)
    for name, stats in manifest["datasets"].items():
        print(f"{name}: state={stats['state_record_count']} records/{stats['state_unique_location_count']} locations, coords={stats['state_records_with_numeric_latitude_and_longitude']}, missing_coords={stats['state_records_missing_or_nonnumeric_coordinates']}, bbox={stats['filtered_record_count']} records/{stats['pilot_unique_location_count']} locations, precision_fields={stats['location_precision_fields_present']}")
    print(f"Manifest: {raw_dir / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
