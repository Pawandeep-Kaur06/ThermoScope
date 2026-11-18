"""Select deterministic, evidence-only FIRMS case studies from a ranking table."""

from __future__ import annotations

import argparse
import csv
import hashlib
from pathlib import Path
from typing import Callable


DEFAULT_INPUT = Path("data/processed/final_pilot_experiment/run_001/candidate_ranking/candidate_ranking.csv")
OUTPUT_NAME = "selected_case_studies.csv"
REPORT_NAME = "selection_report.md"

CASE_SPECS: tuple[tuple[str, str, Callable[[dict[str, str]], bool], Callable[[dict[str, str]], tuple]], ...] = (
    (
        "high_recurrence_near_mining",
        "At least 50 strictly prior distinct acquisition dates; mining extraction area within 250 m.",
        lambda r: _category(r) == "persistent_thermal_with_nearby_relevant_industrial_context"
        and _role(r) == "mining_extraction_area"
        and _prior_dates(r) >= 50
        and _distance(r, "osm_nearest_relevant_distance_m") <= 250,
        lambda r: (_prior_dates(r), _score(r)),
    ),
    (
        "minimum_persistent_near_mining",
        "Exactly three strictly prior distinct acquisition dates; mining extraction area within 250 m.",
        lambda r: _category(r) == "persistent_thermal_with_nearby_relevant_industrial_context"
        and _role(r) == "mining_extraction_area"
        and _prior_dates(r) == 3
        and _distance(r, "osm_nearest_relevant_distance_m") <= 250,
        lambda r: (_score(r),),
    ),
    (
        "persistent_mining_context_beyond_250m",
        "Persistent cell with 20+ prior dates and nearest mapped mining extraction area 250–1,000 m away.",
        lambda r: _category(r) == "persistent_thermal_without_nearby_relevant_osm_context"
        and _role(r) == "mining_extraction_area"
        and 250 < _distance(r, "osm_nearest_relevant_distance_m") <= 1000
        and _prior_dates(r) >= 20,
        lambda r: (_prior_dates(r), _score(r)),
    ),
    (
        "first_observation_near_mining",
        "No strictly prior distinct dates in the 250 m cell; mining extraction area within 250 m.",
        lambda r: _category(r) == "other_thermal_observation_review"
        and _role(r) == "mining_extraction_area"
        and _prior_dates(r) == 0
        and _distance(r, "osm_nearest_relevant_distance_m") <= 250,
        lambda r: (_score(r),),
    ),
    (
        "elevated_near_industrial_landuse",
        "Elevated thermal evidence category with mapped industrial landuse within 250 m.",
        lambda r: _category(r) == "elevated_thermal_with_nearby_relevant_industrial_context"
        and _role(r) == "industrial_landuse"
        and _distance(r, "osm_nearest_relevant_distance_m") <= 250,
        lambda r: (_prior_dates(r), _score(r)),
    ),
    (
        "persistent_near_general_power_infrastructure",
        "Persistent cell near general power infrastructure, without a relevant industrial OSM match.",
        lambda r: _category(r) == "persistent_thermal_near_general_power_infrastructure_only"
        and _prior_dates(r) >= 10
        and _number(r.get("nearest_general_power_infrastructure_distance_m")) is not None,
        lambda r: (_score(r),),
    ),
    (
        "persistent_without_nearby_relevant_osm",
        "Persistent cell with 10+ prior dates and no nearest relevant OSM role recorded.",
        lambda r: _category(r) == "persistent_thermal_without_nearby_relevant_osm_context"
        and not _role(r)
        and _prior_dates(r) >= 10,
        lambda r: (_prior_dates(r), _score(r)),
    ),
    (
        "elevated_without_nearby_relevant_osm",
        "Elevated thermal evidence category, no prior dates in the cell, and no nearest relevant OSM role recorded.",
        lambda r: _category(r) == "elevated_thermal_without_nearby_relevant_osm_context"
        and not _role(r)
        and _prior_dates(r) == 0,
        lambda r: (_score(r),),
    ),
)

FIELDS = (
    "case_id",
    "selection_rule",
    "review_priority_rank",
    "firms_source_row",
    "latitude",
    "longitude",
    "acq_date",
    "acq_time",
    "satellite",
    "instrument",
    "hotspot_cell_id",
    "candidate_category",
    "candidate_review_priority_band",
    "candidate_evidence_score",
    "cell_prior_detection_count",
    "cell_prior_distinct_acquisition_dates",
    "cell_prior_last_acquisition_date",
    "osm_nearest_relevant_role",
    "osm_nearest_relevant_category",
    "osm_nearest_relevant_distance_m",
    "nearest_general_power_infrastructure_distance_m",
    "s2_spectral_data_status",
    "sentinel2_clear_pre_detection_spectrum_available",
    "firms_detection_label",
    "candidate_interpretation",
)


def _number(value: str | None) -> float | None:
    try:
        number = float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None
    return number if number is not None else None


def _score(row: dict[str, str]) -> float:
    return _number(row.get("candidate_evidence_score")) or 0.0


def _prior_dates(row: dict[str, str]) -> int:
    return int(_number(row.get("cell_prior_distinct_acquisition_dates")) or 0)


def _distance(row: dict[str, str], key: str) -> float:
    value = _number(row.get(key))
    return value if value is not None else float("inf")


def _category(row: dict[str, str]) -> str:
    return row.get("candidate_category", "")


def _role(row: dict[str, str]) -> str:
    return row.get("osm_nearest_relevant_role", "")


def select_cases(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Return one best-ranked, unique-grid-cell record for each available case spec."""
    required = {
        "firms_source_row", "latitude", "longitude", "acq_date", "hotspot_cell_id",
        "candidate_category", "candidate_evidence_score", "cell_prior_distinct_acquisition_dates",
        "osm_nearest_relevant_role", "osm_nearest_relevant_distance_m",
        "nearest_general_power_infrastructure_distance_m", "firms_detection_label",
    }
    missing = sorted(required - set(rows[0] if rows else ()))
    if missing:
        raise ValueError(f"Ranking input is missing required columns: {', '.join(missing)}")
    source_rows = [row.get("firms_source_row", "") for row in rows]
    if len(source_rows) != len(set(source_rows)):
        raise ValueError("Ranking input contains duplicate firms_source_row values")

    selections: list[dict[str, str]] = []
    used_cells: set[str] = set()
    for case_id, rationale, predicate, score_key in CASE_SPECS:
        candidates = [r for r in rows if predicate(r)]
        # Use source-row ID as the final, stable tie breaker rather than relying
        # on CSV row order when evidence scores tie.
        candidates.sort(
            key=lambda r: (*score_key(r), -int(r["firms_source_row"])),
            reverse=True,
        )
        chosen = next((r for r in candidates if r.get("hotspot_cell_id") and r["hotspot_cell_id"] not in used_cells), None)
        if chosen is None:
            raise ValueError(f"No unique 250 m cell satisfies case selection rule: {case_id}")
        cell = chosen["hotspot_cell_id"]
        if not (-90 <= float(chosen["latitude"]) <= 90 and -180 <= float(chosen["longitude"]) <= 180):
            raise ValueError(f"Invalid coordinates in selected source row {chosen['firms_source_row']}")
        used_cells.add(cell)
        selections.append({"case_id": case_id, "selection_rule": rationale, **{key: chosen.get(key, "") for key in FIELDS if key not in ("case_id", "selection_rule")}})

    if any(row.get("firms_detection_label") != "unknown_unlinked" for row in selections):
        raise ValueError("Selected records must remain unknown_unlinked; case selection cannot assign labels")
    return selections


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help=f"Candidate ranking CSV (default: {DEFAULT_INPUT})")
    parser.add_argument("--output-dir", type=Path, required=True, help="New output directory; existing files will not be overwritten")
    args = parser.parse_args()
    if not args.input.is_file():
        parser.error(f"Ranking input does not exist: {args.input}")
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        parser.error(f"Output directory is not empty; refusing to overwrite: {args.output_dir}")

    with args.input.open("r", encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    try:
        selected = select_cases(rows)
    except (ValueError, KeyError) as exc:
        parser.error(str(exc))

    args.output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = args.output_dir / OUTPUT_NAME
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(selected)

    report_path = args.output_dir / REPORT_NAME
    input_sha256 = hashlib.sha256(args.input.read_bytes()).hexdigest()
    lines = [
        "# Candidate case-study selection",
        "",
        "This is a deterministic, purposive review sample selected from the saved candidate-ranking table. It is not a probability sample, a validation set, or ground truth. Each selected row is one FIRMS observation from a unique 250 m recurrence cell; recurrence describes observations in a grid cell, not a confirmed persistent physical source.",
        "",
        f"- Input: `{args.input.as_posix()}`",
        f"- Input SHA-256: `{input_sha256}`",
        f"- Input candidate observations: {len(rows)}",
        f"- Reproduction command: `python src/select_case_studies.py --input {args.input.as_posix()} --output-dir {args.output_dir.as_posix()}`",
        f"- Selected cases: {len(selected)}; unique cells: {len({r['hotspot_cell_id'] for r in selected})}",
        f"- FIRMS labels: {', '.join(sorted({r['firms_detection_label'] for r in selected}))}",
        "- Selection uses only saved evidence fields and keeps Sentinel-2 status as recorded; missing, cloudy, or post-detection imagery is not negative evidence.",
        "",
        "| Case | Date | FIRMS source row | 250 m cell | Candidate evidence category | Prior distinct dates | Nearest relevant OSM role | OSM distance (m) | Sentinel-2 status |",
        "|---|---|---:|---|---|---:|---|---:|---|",
    ]
    for row in selected:
        distance = row["osm_nearest_relevant_distance_m"] or "—"
        role = row["osm_nearest_relevant_role"] or "none recorded"
        lines.append(
            f"| {row['case_id']} | {row['acq_date']} | {row['firms_source_row']} | {row['hotspot_cell_id']} | {row['candidate_category']} | {row['cell_prior_distinct_acquisition_dates']} | {role} | {distance} | {row['s2_spectral_data_status']} |"
        )
    lines += [
        "",
        "## Interpretation limits",
        "",
        "OSM features are mapped context, not proof of the heat source. Grid recurrence is spatially aggregated and may combine distinct nearby sources. Candidate scores and categories are prioritization evidence only. None of these records is a verified industrial fire or source classification; independent dated incident evidence and review are still required.",
        "",
    ]
    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Selected {len(selected)} unique-cell cases; wrote {csv_path} and {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
