"""Build an auditable, human-led review queue for external incident evidence.

Event records and detection links are reviewed separately. A review decision
never changes a FIRMS label and never creates a negative example.

Initialize a new evidence-review run from the repository root::

    python src/review_evidence.py --repo .

Append an event/link review to that run's audit log::

    python src/review_evidence.py --review-run data/processed/label_evidence_review/<run> \
        --evidence-id akashvani_dhanbad_warehouse_2026_01_22 \
        --scope event --decision accepted --reviewer "Name" \
        --reason "Primary source confirms event/date; locality remains approximate." \
        --source-reference "https://newsonair.gov.in/..."

An accepted event is event-level evidence only. A detection_link review also
requires a FIRMS source row and a cited source; it is still an adjudication
record, not a training label. Keep source evidence and all review history.
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FEATURES = ROOT / "data/processed/feature_engineering/sentinel2_pilot_validation_002/feature_table.csv.gz"
OUTPUT_PARENT = ROOT / "data/processed/label_evidence_review"
PILOT_START = "2026-01-20"
PILOT_END = "2026-09-05"


def source_inventory() -> pd.DataFrame:
    """Sources reviewed, including date/location precision and limits."""
    rows = [
        {
            "source_id": "mha_ndmi_dhanbad_mine_fire",
            "source_type": "official disaster incident report",
            "organization": "National Disaster Management Information / Ministry of Home Affairs; report attributes information to DC Dhanbad and DDMO",
            "url": "https://ndmindia.mha.gov.in/ndmi/viewUploadedDocument?uid=NEW2785",
            "publication_date": "not stated in extracted report",
            "event_or_observation_dates": "2025-12-03 around 11:00 local",
            "location_precision": "Named settlement and police-station area (Rajpoot Basti, Kenduadih); no coordinates or event polygon",
            "reliability": "High for an officially reported event; source is an administrative incident summary rather than a georeferenced incident record",
            "firms_matchability": "No: event date precedes FIRMS pilot coverage (2026-01-20 to 2026-09-05); no point/polygon",
            "limitations": "Event-scale verification only; not a detection label.",
        },
        {
            "source_id": "bccl_nrsc_jharia_fire_2022_2024",
            "source_type": "official remote-sensing mine-fire assessment referenced in compliance report",
            "organization": "BCCL environmental compliance report citing NRSC",
            "url": "https://bcclweb.in/EC_Compliance_1stOctober2025_to_31stMarch26/Cluster%209%20March%2026.pdf",
            "publication_date": "reported as submitted May 2025",
            "event_or_observation_dates": "2022–2024 imagery/assessment period; latest summary gives 2022 versus 2024 area change",
            "location_precision": "Named collieries and area totals; map annexures may depict areas, but no machine-readable georeferenced incident points were established in this review",
            "reliability": "High for the stated official assessment and area-level findings; secondary source is a BCCL compliance filing referring to NRSC",
            "firms_matchability": "Not as a time-specific individual-detection label: historical mine-fire areas may support site-level context after map georeferencing, but are stale relative to 2026 and not incident timestamps",
            "limitations": "No large PDF retrieval or map digitization was done. Fire extent can change; an old mapped polygon cannot establish a fire on a 2026 overpass.",
        },
        {
            "source_id": "dgms_kankanee_fiery_seam_2025_01_05",
            "source_type": "official mine safety alert; related thermal hazard, not a fire-detection report",
            "organization": "Directorate General of Mines Safety, Government of India",
            "url": "https://www.dgms.gov.in/writereaddata/UploadFile/3FA_30012025.pdf",
            "publication_date": "2025-01-12 (alert dateline; PDF file name dated 2025-01-30)",
            "event_or_observation_dates": "2025-01-05 12:10 PM local",
            "location_precision": "Mine-level (Kankanee Colliery, Dhanbad); no coordinates or accident point",
            "reliability": "High for the documented occupational accident and fiery-seam context; not proof of a satellite-detectable fire",
            "firms_matchability": "No: out of pilot date range and mine-level only",
            "limitations": "The alert concerns burn injuries from hot steam while extracting fiery coal, not a georeferenced mine-fire perimeter or FIRMS thermal observation.",
        },
        {
            "source_id": "akashvani_dhanbad_electricity_warehouse_2026_01_22",
            "source_type": "credible public-service broadcaster incident report",
            "organization": "News On AIR / Akashvani (Prasar Bharati)",
            "url": "https://newsonair.gov.in/jharkhand-massive-fire-engulfs-electricity-department-warehouse-in-dhanbad/",
            "publication_date": "2026-01-22 16:58 IST",
            "event_or_observation_dates": "2026-01-22, described as early that morning; no exact incident time",
            "location_precision": "Road/locality level (electricity warehouse on Baliapur Road, Saraidhela); no address, coordinates or footprint",
            "reliability": "Moderate-high for event occurrence as reported by a government public-service broadcaster; cause was explicitly undetermined",
            "firms_matchability": "Date-compatible only: the pilot has 86 FIRMS rows on 2026-01-22. No spatial/overpass link is defensible without site coordinates and a narrower incident time.",
            "limitations": "The article says cause was not yet ascertained. Day-level coincidence does not link any of the 86 observations to this event.",
        },
        {
            "source_id": "hindustan_bhowra_transformer_2026_06_10",
            "source_type": "single local-news incident report",
            "organization": "Hindustan / Live Hindustan",
            "url": "https://www.livehindustan.com/jharkhand/dhanbad/story-750-kva-transformer-fire-in-bccl-east-jharia-local-anger-over-power-crisis-201781035792165.html",
            "publication_date": "2026-06-10",
            "event_or_observation_dates": "2026-06-10; exact time not established",
            "location_precision": "Locality/operating-area level (Bhowra, BCCL East Jharia); no coordinates or footprint",
            "reliability": "Moderate for an incident lead from one established local outlet; not independently corroborated in the reviewed materials",
            "firms_matchability": "Date-compatible only: 2 FIRMS rows occur on 2026-06-10. No georeferenced event point or precise time; not a detection label.",
            "limitations": "Report's facility locality is too broad for pixel matching; transformer proximity is not proof of cause.",
        },
        {
            "source_id": "hindustan_bokaro_sector4f_transformer_panel_2026_06_25",
            "source_type": "single local-news incident report",
            "organization": "Hindustan / Live Hindustan",
            "url": "https://www.livehindustan.com/jharkhand/bokaro/story-fire-in-transformer-panel-causes-18-hour-power-outage-in-sector-4f-201782498123873.amp.html",
            "publication_date": "2026-06-26 23:52 IST",
            "event_or_observation_dates": "2026-06-25 around 22:30 local (article published June 26; restoration June 26)",
            "location_precision": "Neighborhood/sector block (Sector 4F, 6000-series area, Bokaro); exact panel/cable location was not found",
            "reliability": "Moderate for a reported electrical fire/panel incident from a local outlet; report says the exact fault location was initially unclear",
            "firms_matchability": "Date-window overlap only: 32 FIRMS rows on 2026-06-25 and 49 on 2026-06-26. Local-time/UTC timing and event location do not support row linkage.",
            "limitations": "Not an industrial-source confirmation; broad residential sector context and uncertain event footprint/time.",
        },
        {
            "source_id": "jagran_bokaro_steel_admin_fire_2026_08_23_24",
            "source_type": "single local-news incident report",
            "organization": "Dainik Jagran",
            "url": "https://www.jagran.com/jharkhand/bokaro-bokaro-steel-plant-admin-building-fire-short-circuit-suspected-40350546.html",
            "publication_date": "2026-08-24 13:32 IST",
            "event_or_observation_dates": "2026-08-23 late night / 2026-08-24 about 02:00; article date and wording imply Sunday night",
            "location_precision": "Named building within Bokaro Steel Plant, but no building coordinates/footprint or georeferenced report",
            "reliability": "Moderate for reported building fire from one established outlet; cause reported as suspected short circuit",
            "firms_matchability": "Date-compatible only: 35 rows on Aug 23 and 49 on Aug 24. No georeferenced building/time-overpass match; indoor room fire may be below sensor detectability.",
            "limitations": "No pixel-level linkage or verified detection label.",
        },
        {
            "source_id": "nbt_jharia_barari6_2026_09_03",
            "source_type": "single local-news incident report",
            "organization": "Navbharat Times",
            "url": "https://navbharattimes.indiatimes.com/state/jharkhand/dhanbad/jharia-barari-number-6-settlement-land-subsidence-with-massive-blast-fire-and-toxic-smoke-spew-out/articleshow/133736919.cms",
            "publication_date": "2026-09-03",
            "event_or_observation_dates": "2026-09-03; exact onset/observation time not established",
            "location_precision": "Settlement/block locality (Barari Number 6, Jharia); no coordinates or footprint",
            "reliability": "Low-moderate for an event lead from one secondary outlet; source attribution and event extent need corroboration",
            "firms_matchability": "Date-compatible only: 36 FIRMS rows occur on 2026-09-03. Locality-only evidence cannot identify a row.",
            "limitations": "News description of subsidence/fire does not establish persistence or which satellite detection, if any, corresponds to it.",
        },
    ]
    return pd.DataFrame(rows)


def event_register() -> pd.DataFrame:
    """Event-level evidence; coordinate fields stay empty unless sourced."""
    rows = [
        ("ndmi_dhanbad_kenduadih_2025_12_03", "mha_ndmi_dhanbad_mine_fire", "gas leakage attributed to underground mine fire", "verified_event_only", "2025-12-03", "2025-12-03", "around 11:00 local", "Rajpoot Basti, under Kenduadih police station, Dhanbad", "settlement/police-station locality; no coordinates", "high event-report reliability; no detection linkage"),
        ("akashvani_dhanbad_warehouse_2026_01_22", "akashvani_dhanbad_electricity_warehouse_2026_01_22", "fire at electricity-department warehouse; cause undetermined", "credible_event_lead", "2026-01-22", "2026-01-22", "early morning, unspecified", "Baliapur Road, Saraidhela, Dhanbad", "road/locality; no site coordinates", "credible broadcaster, but no cause/site point/time precise enough for row link"),
        ("hindustan_bhowra_transformer_2026_06_10", "hindustan_bhowra_transformer_2026_06_10", "750 kVA transformer fire; short circuit reported", "weak_candidate_event", "2026-06-10", "2026-06-10", "not stated", "Bhowra, BCCL East Jharia area, Dhanbad", "locality/operating area; no coordinates", "single media source; no detection linkage"),
        ("hindustan_bokaro_sector4f_panel_2026_06_25", "hindustan_bokaro_sector4f_transformer_panel_2026_06_25", "fire involving transformer panel/cable; power outage", "weak_candidate_event", "2026-06-25", "2026-06-26", "around 22:30 local per article", "Sector 4F, 6000-series area, Bokaro", "sector block; exact equipment location unknown", "single media source; no detection linkage"),
        ("jagran_bokaro_admin_fire_2026_08_23_24", "jagran_bokaro_steel_admin_fire_2026_08_23_24", "fire in Bokaro Steel Plant administrative-office room", "weak_candidate_event", "2026-08-23", "2026-08-24", "late night/about 02:00 local", "Administrative building, Bokaro Steel Plant", "facility/building description without coordinates or footprint", "single media source; no row linkage"),
        ("nbt_jharia_barari6_2026_09_03", "nbt_jharia_barari6_2026_09_03", "reported flames/smoke associated with subsidence and underground fire", "weak_candidate_event", "2026-09-03", "2026-09-03", "not stated", "Barari Number 6 settlement, Jharia", "settlement locality; no coordinates", "single media source; no row linkage"),
    ]
    columns = ["evidence_id", "source_id", "event_class_as_reported", "evidence_tier", "event_date_start", "event_date_end", "event_time_local", "location_as_reported", "location_precision", "reliability_note"]
    return pd.DataFrame(rows, columns=columns)


def date_overlap_report(events: pd.DataFrame, features: pd.DataFrame) -> pd.DataFrame:
    required = {"firms_source_row", "acq_date", "latitude", "longitude"}
    missing = required - set(features.columns)
    if missing:
        raise ValueError(f"Feature table lacks required FIRMS fields: {sorted(missing)}")
    f = features.copy()
    f["acq_date"] = pd.to_datetime(f["acq_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    counts = f.dropna(subset=["acq_date"]).groupby("acq_date").size().to_dict()
    out = []
    for event in events.itertuples(index=False):
        start, end = pd.Timestamp(event.event_date_start), pd.Timestamp(event.event_date_end)
        dates = pd.date_range(start, end, freq="D").strftime("%Y-%m-%d").tolist()
        n = sum(int(counts.get(d, 0)) for d in dates)
        in_window = start <= pd.Timestamp(PILOT_END) and end >= pd.Timestamp(PILOT_START)
        out.append({
            "evidence_id": event.evidence_id,
            "event_date_start": event.event_date_start,
            "event_date_end": event.event_date_end,
            "firms_rows_on_event_date_window": n,
            "pilot_date_overlap": bool(in_window and n > 0),
            "candidate_firms_source_row": "",
            "detection_link_status": "not_linkable_from_current_record" if n else "no_date_overlap",
            "detection_label": "unknown_unlinked",
            "reason": "Date-only overlap is not a spatial/overpass match; event record lacks a sourced point/polygon and adequate event-time precision.",
        })
    return pd.DataFrame(out)


def make_run_dir(parent: Path, explicit: Path | None = None) -> Path:
    if explicit:
        out = explicit.resolve()
        out.mkdir(parents=True, exist_ok=False)
        return out
    parent.mkdir(parents=True, exist_ok=True)
    out = parent / datetime.now(timezone.utc).strftime("run_%Y%m%dT%H%M%SZ")
    out.mkdir(exist_ok=False)
    return out


def write_csv(frame: pd.DataFrame, path: Path) -> None:
    frame.to_csv(path, index=False, quoting=csv.QUOTE_MINIMAL)


def initialize_run(repo: Path, feature_path: Path, output: Path | None = None) -> Path:
    if not feature_path.is_absolute():
        feature_path = repo / feature_path
    if not feature_path.is_file():
        raise FileNotFoundError(f"FIRMS feature table not found: {feature_path}")
    features = pd.read_csv(feature_path, usecols=lambda c: c in {"firms_source_row", "acq_date", "latitude", "longitude"})
    events = event_register()
    sources = source_inventory()
    overlaps = date_overlap_report(events, features)
    out = make_run_dir(repo / OUTPUT_PARENT.relative_to(ROOT), output)
    write_csv(sources, out / "source_inventory.csv")
    write_csv(events, out / "event_register.csv")
    write_csv(overlaps, out / "detection_link_review_queue.csv")
    # Event-level review is deliberately separate from a detection link.
    queue = events[["evidence_id", "source_id", "evidence_tier", "event_class_as_reported", "location_precision"]].copy()
    queue["review_scope"] = "event_record"
    queue["review_decision"] = "unresolved"
    queue["review_reason"] = ""
    queue["source_reference"] = ""
    queue["reviewer"] = ""
    write_csv(queue, out / "human_review_queue.csv")
    (out / "human_review_log.csv").write_text("reviewed_at_utc,evidence_id,scope,decision,firms_source_row,reviewer,reason,source_reference\n", encoding="utf-8")
    date_min = pd.to_datetime(features.acq_date, errors="coerce").min()
    date_max = pd.to_datetime(features.acq_date, errors="coerce").max()
    checks = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "feature_input": str(feature_path),
        "feature_rows": int(len(features)),
        "firms_date_min": date_min.strftime("%Y-%m-%d") if pd.notna(date_min) else None,
        "firms_date_max": date_max.strftime("%Y-%m-%d") if pd.notna(date_max) else None,
        "events_reviewed": int(len(events)),
        "source_records": int(len(sources)),
        "date_overlapping_events": int(overlaps.pilot_date_overlap.sum()),
        "date_compatible_firms_rows_not_links": int(overlaps.firms_rows_on_event_date_window.sum()),
        "genuinely_linkable_to_firms_rows": 0,
        "verified_detection_labels_created": 0,
        "weak_detection_labels_created": 0,
        "negative_examples_created": 0,
        "reason_no_detection_links": "Current event records lack adequate event georeferencing and/or time precision; day-level coincidence is insufficient.",
    }
    (out / "validation.json").write_text(json.dumps(checks, indent=2), encoding="utf-8")
    (out / "methodology.md").write_text(methodology(out, overlaps, checks), encoding="utf-8")
    return out


def methodology(out: Path, overlaps: pd.DataFrame, checks: dict) -> str:
    table_rows = [
        "| Evidence ID | FIRMS rows in event-date window | Link status |",
        "| --- | ---: | --- |",
    ]
    for row in overlaps.itertuples(index=False):
        table_rows.append(
            f"| {row.evidence_id} | {row.firms_rows_on_event_date_window} | {row.detection_link_status} |"
        )
    table = "\n".join(table_rows)
    return f"""# ThermoScope evidence source and review feasibility\n\nRun: `{out.name}`  \nFIRMS coverage: {checks['firms_date_min']} to {checks['firms_date_max']} ({checks['feature_rows']:,} pilot rows).\n\n## Feasibility finding\n\nThe inspected sources support several event-level records and useful mine-fire context, but **no current source establishes a georeferenced, time-specific link to an individual FIRMS observation**. The reviewed FIRMS pilot starts {checks['firms_date_min']}; the official MHA mine-fire/gas incident is dated 2025-12-03 and is outside that interval. Local media incidents have dates that overlap FIRMS observations, but only at date level; they lack an event point/polygon and, in several cases, precise ignition/observation time. For these records the count below is a count of same-date FIRMS rows, emphatically not matched detections.\n\n## Date-only overlap audit\n\n{table}\n\nAcross these event records, {checks['date_overlapping_events']} have at least one same-date FIRMS observation window, representing {checks['date_compatible_firms_rows_not_links']} date-compatible rows. **Genuinely linkable FIRMS detections: 0.** Coordinates from facility context, OSM proximity, approximate locality geocoding, or an old mine-fire map are not substituted for event coordinates.\n\n## Source findings\n\n- **BCCL/NRSC Jharia coal-fire assessment:** strongest authoritative persistent-source reference. Current BCCL compliance material describes NRSC mapping for 2022–2024 and reports changing area totals by named collieries. This may become a site-level lead after inspecting/digitizing map annexures, but the maps are historical, area-level, and not proof of a 2026 hotspot's cause. No large PDF was downloaded in this run.\n- **MHA/NDMI, Rajpoot Basti/Kenduadih:** official event-level mine-fire-related report dated 2025-12-03, locality only, no coordinates; before FIRMS pilot coverage.\n- **DGMS Kankanee alert:** authoritative record of a 2025-01-05 hot-steam injury while handling fiery coal, at mine-level precision. This is a related hazard, not itself a mine-fire detection label, and predates the FIRMS window.\n- **News On AIR Dhanbad warehouse, 2026-01-22:** reported fire at an electricity-department warehouse on Baliapur Road; the broadcaster says cause had not been established. There are 86 FIRMS rows on that date, but location/time precision is insufficient to link any row.\n- **Local press leads:** Bhowra transformer fire (June 10), Bokaro Sector 4F transformer/cable incident (June 25–26), Bokaro Steel administrative-room fire (Aug 23–24), and Barari Number 6 event (Sep 3). Dates overlap FIRMS rows, but no row-level geolocation/time linkage is justified. These remain event leads only.\n\n## Human review protocol\n\n`human_review_queue.csv` starts unresolved. Reviewers append decisions with `--decision accepted|rejected|unresolved`, a reason, reviewer name, and source reference. `--scope event` accepts/rejects the event record's credibility/identity only. `--scope detection_link` additionally requires a FIRMS `firms_source_row` whose acquisition date falls within the reported event date interval. This audit log records a human link decision, but **does not assign or export a FIRMS ground-truth label**; a verified detection label requires a separate adjudication step with adequate spatial/time evidence. `rejected` means reject the event/link candidate, never a negative/no-fire example.\n\n## Limitations and next practical step\n\n1. Seek event coordinates and time from district fire-service logs, police investigation records, BCCL mine/fire operations, or facility incident reports for the date-compatible reports.\n2. Request machine-readable or georeferenced BCCL/NRSC 2022–2024 mine-fire polygons; use them only as historical persistent-source context, not 2026 incident truth.\n3. Require documented event location uncertainty and convert event local time to UTC before comparing to FIRMS acquisition timestamps. Then manually review the sensor pixel footprint and independent evidence.\n4. Keep all unmatched detections unknown; do not construct negatives from no-report cases.\n\nNo detection labels, negative examples, model metrics, or large downloads were created.\n"""


def append_review(args: argparse.Namespace) -> None:
    run_dir = args.review_run.resolve()
    if not run_dir.is_dir():
        raise FileNotFoundError(f"Evidence review run not found: {run_dir}")
    events = pd.read_csv(run_dir / "event_register.csv", dtype=str).fillna("")
    match = events[events.evidence_id.eq(args.evidence_id)]
    if match.empty:
        raise ValueError(f"Unknown evidence_id: {args.evidence_id}")
    if args.scope == "event" and args.firms_source_row is not None:
        raise ValueError("--firms-source-row is only valid with --scope detection_link")
    if args.scope == "detection_link":
        if args.firms_source_row is None:
            raise ValueError("--scope detection_link requires --firms-source-row")
        if not args.source_reference:
            raise ValueError("A detection-link review requires --source-reference")
        if not args.features:
            raise ValueError("A detection-link review requires --features to validate row/date")
        feature_path = args.features.resolve()
        if not feature_path.is_file():
            raise FileNotFoundError(f"Feature table not found: {feature_path}")
        f = pd.read_csv(feature_path, usecols=["firms_source_row", "acq_date"], dtype={"firms_source_row": "Int64"})
        row = f[f.firms_source_row.eq(args.firms_source_row)]
        if row.empty:
            raise ValueError(f"FIRMS source row not found: {args.firms_source_row}")
        event = match.iloc[0]
        date = pd.to_datetime(row.iloc[0].acq_date).date()
        start, end = pd.Timestamp(event.event_date_start).date(), pd.Timestamp(event.event_date_end).date()
        if not start <= date <= end:
            raise ValueError(f"FIRMS row date {date} is outside event date interval {start}..{end}")
    if not args.reason.strip() or not args.reviewer.strip() or not args.source_reference.strip():
        raise ValueError("--reason, --reviewer and --source-reference are required")
    log = run_dir / "human_review_log.csv"
    record = {
        "reviewed_at_utc": datetime.now(timezone.utc).isoformat(),
        "evidence_id": args.evidence_id,
        "scope": args.scope,
        "decision": args.decision,
        "firms_source_row": "" if args.firms_source_row is None else args.firms_source_row,
        "reviewer": args.reviewer.strip(),
        "reason": args.reason.strip(),
        "source_reference": args.source_reference.strip(),
    }
    pd.DataFrame([record]).to_csv(log, mode="a", header=False, index=False, quoting=csv.QUOTE_MINIMAL)
    print(json.dumps({"appended_review": record, "labels_changed": False}, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=ROOT, help="Repository root for initializing a new review run")
    parser.add_argument("--features", type=Path, default=DEFAULT_FEATURES, help="FIRMS feature table CSV/CSV.GZ")
    parser.add_argument("--output-dir", type=Path, help="New run directory; must not already exist")
    parser.add_argument("--review-run", type=Path, help="Append a review decision to an existing run instead of initializing")
    parser.add_argument("--evidence-id")
    parser.add_argument("--scope", choices=["event", "detection_link"])
    parser.add_argument("--decision", choices=["accepted", "rejected", "unresolved"])
    parser.add_argument("--firms-source-row", type=int)
    parser.add_argument("--reviewer")
    parser.add_argument("--reason")
    parser.add_argument("--source-reference")
    return parser


def main(argv: Iterable[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if args.review_run:
        required = [args.evidence_id, args.scope, args.decision, args.reviewer, args.reason, args.source_reference]
        if not all(required):
            raise SystemExit("Review mode requires --evidence-id, --scope, --decision, --reviewer, --reason, and --source-reference")
        if args.scope == "detection_link":
            args.features = args.features if args.features.is_absolute() else args.repo / args.features
        append_review(args)
        return
    out = initialize_run(args.repo.resolve(), args.features, args.output_dir)
    print(json.dumps({"output": str(out), "files": sorted(p.name for p in out.iterdir())}, indent=2))


if __name__ == "__main__":
    main()
