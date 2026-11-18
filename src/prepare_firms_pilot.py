#!/usr/bin/env python3
"""Validate archive/NRT FIRMS CSVs and create a deduplicated regional dataset.

Input files are streamed in chunks. FIRMS records are retained only when their
coordinates fall in a configured WGS84 bounding box (the pilot is the default). Archive and
NRT provenance is retained in ``firms_sources``; when the same observation is
present in both sources, the archive row supplies the canonical attributes.
"""

from __future__ import annotations

import argparse
import csv
import json
import hashlib
import math
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from collections import Counter
from contextlib import closing
from pathlib import Path
from typing import Any

import pandas as pd
try:  # Supports both ``python src/script.py`` and package imports in tests.
    from src.regions import DEFAULT_REGION_CONFIG, RegionConfigurationError, contains_coordinates, get_region, bounds_tuple
except ImportError:  # pragma: no cover - exercised by direct script invocation
    from regions import DEFAULT_REGION_CONFIG, RegionConfigurationError, contains_coordinates, get_region, bounds_tuple
try:
    from src.pipeline_cache import cache_hit, cache_key, file_fingerprint, write_manifest
except ImportError:  # pragma: no cover
    from pipeline_cache import cache_hit, cache_key, file_fingerprint, write_manifest


DEFAULT_REGION_ID = "dhanbad_jharia_bokaro"
REQUIRED_COLUMNS = {
    "latitude", "longitude", "acq_date", "acq_time", "satellite", "instrument"
}
SOURCES = ("archive", "nrt")
OUTPUT_COLUMNS = ("firms_sources", "duplicate_record_count", "firms_observation_id", "region_id")
MISSING_TOKENS = {"", "na", "n/a", "nan", "null", "none"}


class InputValidationError(ValueError):
    """Raised when a FIRMS input cannot safely be prepared."""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Stream and validate NASA FIRMS archive/NRT CSVs, filter to a configured region, "
            "and deduplicate overlapping observations."
        )
    )
    parser.add_argument("--archive", type=Path, default=Path("data/raw/archive.csv"),
                        help="FIRMS archive CSV (default: data/raw/archive.csv)")
    parser.add_argument("--nrt", type=Path, default=Path("data/raw/nrt.csv"),
                        help="FIRMS NRT CSV (default: data/raw/nrt.csv)")
    parser.add_argument("--region", default=DEFAULT_REGION_ID,
                        help=f"configured region ID (default: {DEFAULT_REGION_ID})")
    parser.add_argument("--region-config", type=Path, default=DEFAULT_REGION_CONFIG,
                        help="shared JSON region configuration")
    parser.add_argument("--output", type=Path,
                        help="new prepared CSV path (defaults to region-specific path under data/processed)")
    parser.add_argument("--chunksize", type=int, default=100_000,
                        help="rows read per CSV chunk (default: 100000)")
    return parser.parse_args(argv)


def _header(path: Path) -> list[str]:
    if not path.is_file():
        raise InputValidationError(f"FIRMS input file does not exist or is not a file: {path}")
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            columns = next(csv.reader(handle), None)
        if not columns:
            raise InputValidationError(f"FIRMS input CSV is empty or has no header: {path}")
        columns = [column.strip() for column in columns]
        if any(not column for column in columns):
            raise InputValidationError(f"FIRMS input CSV has an empty column name: {path}")
        if len(columns) != len(set(columns)):
            raise InputValidationError(f"FIRMS input CSV has duplicate column names: {path}")
        return columns
    except InputValidationError:
        raise
    except Exception as exc:
        raise InputValidationError(f"Could not read CSV header from {path}: {exc}") from exc


def _normalise_date(value: str) -> str | None:
    try:
        return pd.to_datetime(value, errors="raise", format="mixed").date().isoformat()
    except (ValueError, TypeError, OverflowError):
        return None


def _normalise_time(value: str) -> str:
    text = value.strip()
    if text.isdigit():
        return text.zfill(4)[-4:]
    return text


def _identity_key(row: dict[str, Any], columns: set[str]) -> str:
    """Stable cross-export key, excluding changing version/source-only fields."""
    lat = float(row["latitude"])
    lon = float(row["longitude"])
    # FIRMS exports commonly use 5 decimal places; eight decimals preserve any
    # finer precision without relying on CSV float formatting differences.
    components = [
        f"{lat:.8f}", f"{lon:.8f}", _normalise_date(row["acq_date"]) or row["acq_date"].strip(),
        _normalise_time(row["acq_time"]), row["satellite"].strip().upper(),
        row["instrument"].strip().upper(),
    ]
    for optional in ("scan", "track"):
        components.append(row.get(optional, "").strip() if optional in columns else "")
    return "\x1f".join(components)


def _empty_source_stats(path: Path, columns: list[str]) -> dict[str, Any]:
    return {
        "path": str(path), "columns": columns, "input_rows": 0,
        "region_rows_before_deduplication": 0, "missing_values": Counter(),
        "invalid_or_missing_coordinates": 0, "out_of_geographic_range": 0,
        "invalid_acquisition_dates": 0, "region_date_min": None, "region_date_max": None,
        "identity_duplicates_within_source": 0,
    }


def _update_date_range(stats: dict[str, Any], value: str) -> None:
    parsed = _normalise_date(value)
    if parsed is None:
        stats["invalid_acquisition_dates"] += 1
        return
    if stats["region_date_min"] is None or parsed < stats["region_date_min"]:
        stats["region_date_min"] = parsed
    if stats["region_date_max"] is None or parsed > stats["region_date_max"]:
        stats["region_date_max"] = parsed


def prepare(archive: Path, nrt: Path, output: Path, chunksize: int = 100_000,
            region_id: str = DEFAULT_REGION_ID, region_config: Path | str = DEFAULT_REGION_CONFIG) -> dict[str, Any]:
    """Create the prepared CSV and a JSON quality report beside it."""
    if chunksize < 1:
        raise InputValidationError("--chunksize must be a positive integer")
    try:
        region = get_region(region_id, region_config)
    except RegionConfigurationError as exc:
        raise InputValidationError(str(exc)) from exc
    west, south, east, north = bounds_tuple(region)
    archive, nrt, output = archive.resolve(), nrt.resolve(), output.resolve()
    if archive == nrt:
        raise InputValidationError("--archive and --nrt must refer to different files")
    source_paths = {"archive": archive, "nrt": nrt}
    headers = {name: _header(path) for name, path in source_paths.items()}
    for source, columns in headers.items():
        missing = sorted(REQUIRED_COLUMNS.difference(columns))
        if missing:
            raise InputValidationError(
                f"{source} FIRMS CSV is missing required column(s) {missing}: {source_paths[source]}"
            )
        if len(columns) != len(set(columns)):
            raise InputValidationError(f"{source} FIRMS CSV has duplicate column names: {source_paths[source]}")

    input_fingerprints = {name: file_fingerprint(path) for name, path in source_paths.items()}
    region_config_path = Path(region_config).resolve()
    configuration_fingerprint = file_fingerprint(region_config_path)
    key = cache_key(stage="firms_prepare", inputs={**input_fingerprints, "region_config": configuration_fingerprint},
                    configuration={"region_id": region_id, "chunksize": chunksize}, code_path=Path(__file__))

    output.parent.mkdir(parents=True, exist_ok=True)
    report_path = output.with_suffix(output.suffix + ".quality.json")
    if cache_hit(output, key) and report_path.is_file():
        try:
            cached_report = json.loads(report_path.read_text(encoding="utf-8"))
            if cached_report.get("output", {}).get("row_count") is not None:
                return cached_report
        except (OSError, ValueError, KeyError):
            pass
    cache_sidecar = Path(str(output) + ".cache.json")
    if cache_sidecar.exists() and (output.exists() or report_path.exists()):
        # Preserve invalidated generated artifacts for audit; never replace their bytes.
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        for stale in (output, report_path, cache_sidecar):
            if stale.exists():
                archived = stale.with_name(stale.name + f".stale_{stamp}")
                stale.replace(archived)
    if output.exists() or report_path.exists():
        raise FileExistsError(
            f"Output already exists; choose a new --output path (no files overwritten): "
            f"{output if output.exists() else report_path}"
        )
    union_columns = list(dict.fromkeys(headers["archive"] + headers["nrt"]))
    reserved_collisions = sorted(set(union_columns).intersection(OUTPUT_COLUMNS))
    if reserved_collisions:
        raise InputValidationError(f"Input uses reserved output column name(s): {reserved_collisions}")
    shared_columns = set(headers["archive"]).intersection(headers["nrt"])
    # Extra source fields are appended after original FIRMS fields.
    output_fields = union_columns + list(OUTPUT_COLUMNS)
    source_stats = {key: _empty_source_stats(source_paths[key], headers[key]) for key in SOURCES}
    output_missing: Counter[str] = Counter()
    retained_dates: set[str] = set()
    total_duplicates = 0
    cross_source_duplicates = 0
    output_rows = 0

    # Only configured-region records enter SQLite, so the deduplication index stays
    # much smaller than either global source CSV and does not grow in RAM.
    with tempfile.TemporaryDirectory(prefix="thermoscope-firms-") as temporary:
        db_path = Path(temporary) / "dedupe.sqlite"
        with closing(sqlite3.connect(db_path)) as db:
            db.execute(
                "CREATE TABLE observations (identity TEXT PRIMARY KEY, payload TEXT NOT NULL, "
                "archive_count INTEGER NOT NULL, nrt_count INTEGER NOT NULL, total_count INTEGER NOT NULL)"
            )
            for source in SOURCES:
                stats = source_stats[source]
                source_columns = headers[source]
                try:
                    chunks = pd.read_csv(
                        source_paths[source], chunksize=chunksize, dtype=str,
                        keep_default_na=False, encoding="utf-8-sig", on_bad_lines="error",
                    )
                    for chunk in chunks:
                        stats["input_rows"] += len(chunk)
                        for column in source_columns:
                            values = chunk[column].astype(str).str.strip().str.lower()
                            stats["missing_values"][column] += int(values.isin(MISSING_TOKENS).sum())
                        lat = pd.to_numeric(chunk["latitude"].str.strip(), errors="coerce")
                        lon = pd.to_numeric(chunk["longitude"].str.strip(), errors="coerce")
                        coord_missing = (
                            chunk["latitude"].str.strip().str.lower().isin(MISSING_TOKENS)
                            | chunk["longitude"].str.strip().str.lower().isin(MISSING_TOKENS)
                        )
                        finite = lat.map(math.isfinite) & lon.map(math.isfinite)
                        numeric_coord = ~coord_missing & finite
                        valid_range = lat.between(-90, 90) & lon.between(-180, 180)
                        valid_coord = numeric_coord & valid_range
                        stats["invalid_or_missing_coordinates"] += int((~numeric_coord).sum())
                        stats["out_of_geographic_range"] += int((numeric_coord & ~valid_range).sum())
                        in_region = valid_coord & contains_coordinates(lon, lat, region)
                        candidates = chunk.loc[in_region]
                        stats["region_rows_before_deduplication"] += len(candidates)
                        for values in candidates.itertuples(index=False, name=None):
                            row = dict(zip(source_columns, values))
                            _update_date_range(stats, row["acq_date"])
                            key = _identity_key(row, shared_columns)
                            payload = {column: row.get(column, "") for column in union_columns}
                            previous = db.execute(
                                "SELECT archive_count, nrt_count, total_count FROM observations WHERE identity=?",
                                (key,),
                            ).fetchone()
                            if previous is None:
                                db.execute(
                                    "INSERT INTO observations VALUES (?, ?, ?, ?, 1)",
                                    (key, json.dumps(payload, ensure_ascii=False), int(source == "archive"), int(source == "nrt")),
                                )
                            else:
                                archive_count, nrt_count, total_count = previous
                                # Archive is processed first and remains canonical.
                                db.execute(
                                    "UPDATE observations SET archive_count=?, nrt_count=?, total_count=? WHERE identity=?",
                                    (archive_count + int(source == "archive"),
                                     nrt_count + int(source == "nrt"), total_count + 1, key),
                                )
                                stats["identity_duplicates_within_source"] += int(
                                    (source == "archive" and archive_count > 0)
                                    or (source == "nrt" and nrt_count > 0)
                                )
                                total_duplicates += 1
                                cross_source_duplicates += int(
                                    (source == "archive" and nrt_count > 0)
                                    or (source == "nrt" and archive_count > 0)
                                )
                except (pd.errors.ParserError, UnicodeDecodeError, OSError, ValueError) as exc:
                    raise InputValidationError(f"Failed while reading {source} CSV {source_paths[source]}: {exc}") from exc

            db.commit()
            output.parent.mkdir(parents=True, exist_ok=True)
            try:
                output_created = False
                with output.open("x", encoding="utf-8", newline="") as handle:
                    output_created = True
                    writer = csv.DictWriter(handle, fieldnames=output_fields, extrasaction="ignore")
                    writer.writeheader()
                    cursor = db.execute(
                        "SELECT identity, payload, archive_count, nrt_count, total_count FROM observations ORDER BY rowid"
                    )
                    for key, payload_text, archive_count, nrt_count, total_count in cursor:
                        row = json.loads(payload_text)
                        row["firms_sources"] = "+".join(
                            name for name, count in (("archive", archive_count), ("nrt", nrt_count)) if count
                        )
                        row["duplicate_record_count"] = total_count - 1
                        row["firms_observation_id"] = hashlib.sha256(key.encode("utf-8")).hexdigest()
                        row["region_id"] = region_id
                        writer.writerow(row)
                        output_rows += 1
                        for field in output_fields:
                            value = row.get(field, "")
                            if value is None or str(value).strip().lower() in MISSING_TOKENS:
                                output_missing[field] += 1
                        parsed = _normalise_date(str(row.get("acq_date", "")))
                        if parsed:
                            retained_dates.add(parsed)
            except Exception:
                # A partial output is not presented as a valid prepared dataset.
                if locals().get("output_created", False):
                    output.unlink(missing_ok=True)
                raise

    report = {
        "dataset": str(output),
        "report": str(report_path),
        "region": {"id": region_id, "name": region.get("name"), "bounding_box_wgs84": region["bbox_wgs84"],
                   "max_inclusive": bool(region.get("max_inclusive", False)),
                   "country_boundary": ({key: value for key, value in region["country_boundary"].items()
                                         if key not in {"geometry_path"}} | {"geometry_path": region["country_boundary"]["geometry_path"]}
                                        if region.get("country_boundary") else None),
                   "configuration": str(Path(region_config).resolve())},
        "bounding_box_wgs84": {"west": west, "south": south, "east": east, "north": north},
        "input_format": "NASA FIRMS CSV archive and NRT exports; one header row; UTF-8; coordinates in decimal degrees",
        "required_columns": sorted(REQUIRED_COLUMNS),
        "deduplication": {
            "identity_fields": ["latitude", "longitude", "acq_date", "acq_time", "satellite", "instrument", "scan (if present)", "track (if present)"],
            "canonical_record_policy": "Archive row wins when an observation is present in both inputs; FIRMS source-only fields are preserved as blank where absent.",
            "source_provenance_column": "firms_sources (archive, nrt, or archive+nrt)",
            "duplicate_count_column": "duplicate_record_count (number of additional input rows represented by the output row)",
            "duplicate_input_rows_removed": total_duplicates,
            "cross_source_overlap_rows": cross_source_duplicates,
            "output_rows": output_rows,
        },
        "sources": {
            name: {
                **{key: value for key, value in stats.items() if key != "missing_values"},
                "missing_values": dict(sorted(stats["missing_values"].items())),
            }
            for name, stats in source_stats.items()
        },
        "output": {
            "row_count": output_rows,
            "date_coverage": {
                "minimum": min(retained_dates) if retained_dates else None,
                "maximum": max(retained_dates) if retained_dates else None,
                "distinct_acquisition_dates": len(retained_dates),
            },
            "missing_values": dict(sorted(output_missing.items())),
        },
        "coordinate_validation": {
            "coordinate_system": "WGS84 longitude/latitude (EPSG:4326)",
            "region_membership": "configured country polygon covers point, in addition to the stable region/tile-grid bounding extent" if region.get("country_boundary") else "configured rectangular region bounds",
            "invalid_or_missing_coordinate_rows_excluded": sum(s["invalid_or_missing_coordinates"] for s in source_stats.values()),
            "out_of_geographic_range_rows_excluded": sum(s["out_of_geographic_range"] for s in source_stats.values()),
            "region_bounds_inclusive_minima": True,
            "region_max_bounds_inclusive": bool(region.get("max_inclusive", False)),
            "boundary_deduplication": "firms_observation_id is a stable SHA-256 of the canonical observation identity; merge regional outputs with this ID to deduplicate boundary observations.",
        },
    }
    report_created = False
    try:
        with report_path.open("x", encoding="utf-8", newline="\n") as handle:
            report_created = True
            json.dump(report, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
    except Exception:
        if report_created:
            report_path.unlink(missing_ok=True)
        output.unlink(missing_ok=True)
        raise
    write_manifest(output, key=key, source="NASA FIRMS archive and NRT local CSV inputs",
                   metadata={"inputs": input_fingerprints, "region_id": region_id,
                             "quality_report": str(report_path), "row_count": output_rows})
    return report


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        output = args.output or Path("data/processed") / (
            "firms_pilot.csv" if args.region == DEFAULT_REGION_ID else f"firms_{args.region}.csv"
        )
        report = prepare(args.archive, args.nrt, output, args.chunksize, args.region, args.region_config)
    except (InputValidationError, FileExistsError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(
        f"Prepared {report['output']['row_count']:,} unique detections for {report['region']['id']} at {report['dataset']}\n"
        f"Quality report: {report['report']}\n"
        f"Input duplicate rows removed: {report['deduplication']['duplicate_input_rows_removed']:,} "
        f"({report['deduplication']['cross_source_overlap_rows']:,} archive/NRT overlaps)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
