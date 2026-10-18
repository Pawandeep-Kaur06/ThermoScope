"""Create an auditable label-readiness assessment for the ThermoScope pilot.

This script deliberately does not label FIRMS detections or calculate model
metrics. It records external incident evidence separately and creates a
transparent review-priority ranking using only row-level FIRMS FRP and the
existing strictly-past recurrence features.

Run from the repository root:
    python src/assess_label_evidence.py
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
FEATURE_RUN = ROOT / "data/processed/feature_engineering/run_20261018T203712Z"
FEATURES = FEATURE_RUN / "feature_table.csv.gz"
OUTPUT_PARENT = ROOT / "data/processed/label_evaluation"

# Fixed, documented scales keep this review ordering row-local and independent
# of later observations or full-dataset statistics. These are not model weights.
FRP_SATURATION_MW = 5.0
RECURRENCE_SATURATION_DATES = 3.0
FRP_WEIGHT = 0.55
RECURRENCE_WEIGHT = 0.45
TOP_N = 100


def make_output_dir() -> Path:
    OUTPUT_PARENT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("run_%Y%m%dT%H%M%SZ")
    path = OUTPUT_PARENT / stamp
    path.mkdir(exist_ok=False)
    return path


def incident_register() -> pd.DataFrame:
    """Publicly documented events; none is asserted to match a FIRMS row."""
    rows = [
        {
            "evidence_id": "ndmi_dhanbad_kenduadih_2025_12_03",
            "source_type": "official disaster incident report",
            "event_class_as_reported": "gas leakage attributed to underground mine fire",
            "evidence_tier": "verified_event_only",
            "source_organization": "National Disaster Management Information (MHA); report says information from DC Dhanbad/DDMO",
            "source_url": "https://ndmindia.mha.gov.in/ndmi/viewUploadedDocument?uid=NEW2783",
            "source_published_date": None,
            "event_date_start": "2025-12-03",
            "event_date_end": "2025-12-03",
            "event_time_local": "around 11:00 (as reported)",
            "location_as_reported": "Rajpoot Basti, under Kenduadih police station, Dhanbad, Jharkhand",
            "latitude": None,
            "longitude": None,
            "detection_level_label": "unknown_unlinked",
            "firms_detection_link": "not_linkable_from_record",
            "confidence_rationale": "High confidence that an official report recorded this local incident; no confidence is assigned to any FIRMS-row linkage because the event predates the FIRMS window and is not georeferenced.",
            "limitation": "Official report supports this event at locality/date level, but has no coordinates or satellite-pixel link; event is before the current FIRMS source window (starts 2026-01-20).",
            "permitted_use": "Verified event-level evidence; not a detection-level training/evaluation label.",
        },
        {
            "evidence_id": "hindustan_bhowra_transformer_2026_06_10",
            "source_type": "single local media report",
            "event_class_as_reported": "750 kVA transformer fire; short circuit reported as cause",
            "evidence_tier": "weak_candidate_event",
            "source_organization": "Hindustan (Live Hindustan)",
            "source_url": "https://www.livehindustan.com/jharkhand/dhanbad/story-750-kva-transformer-fire-in-bccl-east-jharia-local-anger-over-power-crisis-201781035792165.html",
            "source_published_date": "2026-06-10",
            "event_date_start": "2026-06-10",
            "event_date_end": "2026-06-10",
            "event_time_local": None,
            "location_as_reported": "Bhowra, BCCL East Jharia area, Dhanbad",
            "latitude": None,
            "longitude": None,
            "detection_level_label": "unknown_unlinked",
            "firms_detection_link": "not_linkable_from_record",
            "confidence_rationale": "Low-to-moderate confidence that a transformer fire was reported; a single secondary source and locality-only location do not establish event geometry, timing, or a FIRMS match.",
            "limitation": "One press report and locality only; no event point/polygon, confirmed ignition time, or pixel-level linkage. A nearby power-infrastructure feature would not prove causation.",
            "permitted_use": "Weak event candidate for manual source research; not an evaluation label.",
        },
        {
            "evidence_id": "nbt_jharia_barari6_2026_09_03",
            "source_type": "single local media report",
            "event_class_as_reported": "flames/smoke associated with settlement subsidence and reported underground fire",
            "evidence_tier": "weak_candidate_event",
            "source_organization": "Navbharat Times",
            "source_url": "https://navbharattimes.indiatimes.com/state/jharkhand/dhanbad/jharia-barari-number-6-settlement-land-subsidence-with-massive-blast-fire-and-toxic-smoke-spew-out/articleshow/133736919.cms",
            "source_published_date": "2026-09-03",
            "event_date_start": "2026-09-03",
            "event_date_end": "2026-09-03",
            "event_time_local": None,
            "location_as_reported": "Barari Number 6 settlement, Jharia, Dhanbad",
            "latitude": None,
            "longitude": None,
            "detection_level_label": "unknown_unlinked",
            "firms_detection_link": "not_linkable_from_record",
            "confidence_rationale": "Low-to-moderate confidence in the reported neighborhood event; single media report, approximate locality and uncertain onset make both persistence and detection linkage unverified.",
            "limitation": "Neighborhood-scale location and report date only; the report does not give an event point or precise onset/overpass time. The condition may be persistent, but this record alone cannot identify individual FIRMS pixels or source causes.",
            "permitted_use": "Weak event candidate for manual source research; not an evaluation label.",
        },
        {
            "evidence_id": "jagran_bokaro_steel_admin_fire_2026_08_23_24",
            "source_type": "single local media report",
            "event_class_as_reported": "fire in Bokaro Steel Plant administrative building; short circuit suspected",
            "evidence_tier": "weak_candidate_event",
            "source_organization": "Dainik Jagran",
            "source_url": "https://www.jagran.com/jharkhand/bokaro-bokaro-steel-plant-admin-building-fire-short-circuit-suspected-40350546.html",
            "source_published_date": "2026-08-24",
            "event_date_start": "2026-08-23",
            "event_date_end": "2026-08-24",
            "event_time_local": "article describes approximately 02:00; date wording is ambiguous",
            "location_as_reported": "Administrative building, Bokaro Steel Plant, Bokaro",
            "latitude": None,
            "longitude": None,
            "detection_level_label": "unknown_unlinked",
            "firms_detection_link": "not_linkable_from_record",
            "confidence_rationale": "Low-to-moderate confidence that a fire occurred in the named plant building based on a single report; no building footprint, unambiguous incident time, independent confirmation, or FIRMS linkage.",
            "limitation": "The article is a single report and does not provide a georeferenced building footprint or an unambiguous event timestamp; an indoor building fire may also be below FIRMS detectability.",
            "permitted_use": "Weak event candidate for manual source research; not an evaluation label.",
        },
    ]
    return pd.DataFrame(rows)


def source_inventory() -> pd.DataFrame:
    """Potential label sources and why they do or do not support row labels."""
    rows = [
        {
            "source": "NASA FIRMS active fire / thermal anomaly products",
            "url": "https://firms.modaps.eosdis.nasa.gov/map/",
            "potential_classes": "Satellite thermal detections (input observations)",
            "evidence_value": "Provides time-stamped detections and sensor attributes; official description says detections can be fire, hot smoke, agriculture, or other sources.",
            "current_status": "Already used as the target observation table, not independent ground truth.",
            "main_limitations": "Approximate sensor pixels (VIIRS about 375 m, MODIS about 1 km); no causal label. Confidence/FRP do not establish source class.",
        },
        {
            "source": "NDMI / Ministry of Home Affairs incident reporting",
            "url": "https://ndmindia.mha.gov.in/ndmi/viewUploadedDocument?uid=NEW2783",
            "potential_classes": "Documented industrial/mine-fire event at event scale",
            "evidence_value": "Official report records a 2025-12-03 gas leak attributed to an underground mine fire at Rajpoot Basti/Kenduadih, Dhanbad.",
            "current_status": "One event-level verified record entered in the evidence register; not linkable to current FIRMS period.",
            "main_limitations": "No coordinates/polygon in the report; date predates FIRMS coverage in the feature table; event record is not a pixel-level label.",
        },
        {
            "source": "BCCL environmental-clearance/compliance reports with NRSC coal-fire mapping",
            "url": "https://www.bcclweb.in/EC%20Compliance%201st%20April%2023%20to%2030th%20Sept%2023/Cluster%20IV%20six%20monthly%20EC%20compliance.pdf",
            "potential_classes": "Persistent coal-mine-fire areas / mine-wise fire status",
            "evidence_value": "BCCL-indexed compliance documents describe an NRSC/Jharia coalfield fire map for 2020 based on Landsat-8 and mine-wise fire-affected area tables.",
            "current_status": "Strongest candidate for future persistent-mine-fire site polygons; not downloaded or spatially linked in this run.",
            "main_limitations": "The indexed map is from 2020 and therefore stale for 2026 detections; map georeferencing, exact observation dates, active/persistent definitions, and current status must be verified. Automated page retrieval returned HTTP 403 during this assessment.",
        },
        {
            "source": "OISD case studies and safety alerts",
            "url": "https://oisd.gov.in/case-studies",
            "potential_classes": "Documented oil, gas, and petroleum industrial fire incidents",
            "evidence_value": "Official Ministry of Petroleum and Natural Gas safety directorate publishes incident-analysis case studies and alerts, including named fires at process units and facilities.",
            "current_status": "Useful source for building an event catalogue; no Dhanbad/Bokaro row-level links identified in current inputs.",
            "main_limitations": "Sector-selective and case-study based; individual documents need extraction of event date, site coordinates/footprint, and incident timing before spatial matching.",
        },
        {
            "source": "Local news incident reports (Hindustan, Navbharat Times, Dainik Jagran)",
            "url": "https://www.livehindustan.com/jharkhand/dhanbad/story-750-kva-transformer-fire-in-bccl-east-jharia-local-anger-over-power-crisis-201781035792165.html",
            "potential_classes": "Candidate local industrial fire / mine-fire events",
            "evidence_value": "Three current-window event leads are recorded separately in label_evidence_register.csv with date/location uncertainty and rationale.",
            "current_status": "Weak candidate events only; no row-level labels.",
            "main_limitations": "Single secondary reports, generally locality not coordinates, uncertain onset/overpass time, possible ambiguity in source attribution.",
        },
        {
            "source": "NASA MODIS MCD64A1 burned-area product",
            "url": "https://modis-land.gsfc.nasa.gov/burn.html",
            "potential_classes": "Broad vegetation/burn-scar context; not industrial source class",
            "evidence_value": "Monthly global 500 m burned-area product can help inspect large burn scars and distinguish some landscape fire context.",
            "current_status": "Not used as labels.",
            "main_limitations": "Algorithm couples MODIS reflectance with active-fire observations; monthly 500 m support and dependence on active-fire inputs prevent treating it as independent industrial-cause truth.",
        },
        {
            "source": "OSM and GEM facility inventories",
            "url": "https://www.openstreetmap.org/",
            "potential_classes": "Industrial site/facility context only",
            "evidence_value": "Provides mapped feature types and supplementary GEM coal-asset records for manual investigation context.",
            "current_status": "Already used as context features; never used as labels.",
            "main_limitations": "Facility presence or proximity does not establish a fire or thermal-source cause; inventories can be incomplete and are not historical incident records.",
        },
    ]
    return pd.DataFrame(rows)


def build_ranking(features: pd.DataFrame) -> pd.DataFrame:
    required = {
        "firms_source_row", "latitude", "longitude", "acq_date", "acq_time",
        "thermal_frp_mw", "confidence", "hotspot_cell_id",
        "cell_prior_distinct_acquisition_dates", "cell_prior_last_acquisition_date",
        "osm_nearest_relevant_distance_m", "osm_nearest_relevant_role",
        "gem_nearest_distance_m", "gem_nearest_name", "s2_spectral_data_status",
    }
    missing = sorted(required - set(features.columns))
    if missing:
        raise ValueError(f"Feature input is missing required fields: {missing}")
    df = features.copy()
    df["acq_date"] = pd.to_datetime(df["acq_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    df["thermal_frp_mw"] = pd.to_numeric(df["thermal_frp_mw"], errors="coerce")
    df["cell_prior_distinct_acquisition_dates"] = pd.to_numeric(
        df["cell_prior_distinct_acquisition_dates"], errors="coerce"
    )
    df["osm_nearest_relevant_distance_m"] = pd.to_numeric(df["osm_nearest_relevant_distance_m"], errors="coerce")
    prior_date = pd.to_datetime(df["cell_prior_last_acquisition_date"], errors="coerce")
    acquisition_date = pd.to_datetime(df["acq_date"], errors="coerce")
    causal_prior = prior_date.isna() | (prior_date < acquisition_date)
    if not causal_prior.all():
        raise ValueError("Past-only recurrence check failed: prior date is not strictly earlier")

    frp = df["thermal_frp_mw"].clip(lower=0)
    prior_dates = df["cell_prior_distinct_acquisition_dates"].clip(lower=0).fillna(0)
    df["review_frp_component"] = frp / (frp + FRP_SATURATION_MW)
    df["review_prior_recurrence_component"] = prior_dates / (prior_dates + RECURRENCE_SATURATION_DATES)
    df["candidate_review_priority_score"] = (
        FRP_WEIGHT * df["review_frp_component"]
        + RECURRENCE_WEIGHT * df["review_prior_recurrence_component"]
    )
    df["review_priority_rank"] = df["candidate_review_priority_score"].rank(method="first", ascending=False).astype("int64")
    df["candidate_review_priority_band"] = np.select(
        [df["review_priority_rank"] <= max(1, int(np.ceil(len(df) * 0.05))),
         df["review_priority_rank"] <= max(1, int(np.ceil(len(df) * 0.25)))],
        ["high_review_priority", "medium_review_priority"],
        default="routine_review_priority",
    )
    df["confidence_high_flag"] = df["confidence"].astype("string").str.lower().eq("h")
    df["near_relevant_osm_250m_context_flag"] = df["osm_nearest_relevant_distance_m"].le(250)
    df["recurrent_prior_3plus_dates_flag"] = prior_dates.ge(3)
    df["firms_detection_label"] = "unknown_unlinked"
    df["ranking_interpretation"] = (
        "Manual review order only; not a probability, source class, cause attribution, or ground-truth label."
    )
    keep = [
        "review_priority_rank", "candidate_review_priority_band", "candidate_review_priority_score",
        "firms_source_row", "latitude", "longitude", "acq_date", "acq_time", "satellite", "instrument",
        "thermal_frp_mw", "thermal_brightness_k", "thermal_brightness_t31_k", "confidence", "daynight",
        "hotspot_cell_id", "cell_prior_detection_count", "cell_prior_distinct_acquisition_dates",
        "cell_prior_last_acquisition_date", "cell_days_since_prior_observation", "cell_prior_recurring_flag",
        "review_frp_component", "review_prior_recurrence_component", "confidence_high_flag",
        "osm_nearest_relevant_distance_m", "osm_nearest_relevant_role", "osm_nearest_relevant_category",
        "osm_evidence_status_250m", "osm_context_is_ground_truth", "gem_nearest_distance_m",
        "gem_nearest_name", "gem_nearest_type", "s2_spectral_data_status", "s2_spectral_predictor_eligible",
        "firms_detection_label", "ranking_interpretation",
    ]
    return df[keep].sort_values("review_priority_rank", kind="stable").reset_index(drop=True)


def write_methodology(path: Path, n_rows: int, unique_cells: int, verified_event_only: int, weak_events: int) -> None:
    content = f"""# ThermoScope label evidence and evaluation readiness

Run: `{path.name}`
Feature source: `data/processed/feature_engineering/run_20261018T203712Z/feature_table.csv.gz`

## Finding

There are **no credible detection-level ground-truth labels** in the current pilot. The feature table has {n_rows:,} FIRMS observations in {unique_cells:,} 250 m grid cells, but none has an independently documented, georeferenced incident linked to the FIRMS pixel footprint and acquisition time. This run therefore has **zero detection-level verified labels, zero detection-level weak labels attached to rows, and {n_rows:,} unknown/unlinked FIRMS rows**. It reports no classification accuracy, precision, recall, or other model metrics. Supervised classification is not justified yet.

The separate incident register contains {verified_event_only} official event-level record outside the FIRMS source window and {weak_events} local-media event candidates. These are useful audit leads; they are not FIRMS training/evaluation rows.

## Labeling framework

| Tier | Meaning | Minimum evidence | Current use |
|---|---|---|---|
| `verified_detection_label` | A particular FIRMS detection is linked to an independently verified event/source class | Primary incident record or regulator/operator investigation; usable event coordinates/footprint and time; temporal overlap with sensor overpass and FIRMS pixel footprint; review of source-class interpretation | None available. Do not assign from OSM/GEM proximity or recurrence. |
| `weak_candidate_event` | An event is reported by a credible secondary source, but event-to-detection linkage or source-class verification is incomplete | Citable report plus explicitly recorded date/location uncertainty | Three event leads in `label_evidence_register.csv`; no FIRMS row labels. |
| `verified_event_only` | Independent official documentation verifies an event at event/locality scale but cannot support a sensor-row label | Official incident report with described event, date and locality | One 2025 Kenduadih mine-fire gas-leak incident; outside the available FIRMS window and lacks coordinates. |
| `unknown_unlinked` | No sufficient independent evidence for a row-level class | Default for every FIRMS record until an auditable link exists | All {n_rows:,} rows. |

The project can eventually study `documented industrial fire event`, `documented persistent mine-fire/venting area`, and `other documented thermal source` only when the relevant evidence meets the detection-linkage standard. `non-fire industrial process heat`, `flare`, `wildland fire`, and especially `negative/no-fire` are **not** currently supported as labels in this pilot. A no-report, no-match, cloudy image, or lack of an OSM/GEM feature is never a negative label.

## Source assessment

* **NASA FIRMS** supplies active-fire/thermal-anomaly detections, not cause labels. FIRMS confidence and FRP describe detection attributes, not whether the source is an industrial fire.
* **Official event records** are the strongest target for labels. The National Disaster Management Information report records a 3 Dec 2025 gas-leak incident attributed to an underground mine fire at Rajpoot Basti/Kenduadih, but it predates the FIRMS file window (2026-01-20 onward) and gives no coordinates suitable for pixel linkage.
* **BCCL/NRSC mine-fire mapping** is the strongest discovered source for persistent mine-fire areas. BCCL-indexed environmental compliance documents refer to a Jharia coalfield fire map for 2020 based on Landsat-8 and mine-wise fire-area tables. This could support historical site context, but it is too old to label 2026 detections without updated polygons and active-status evidence; automated retrieval returned HTTP 403 in this assessment.
* **OISD case studies and safety alerts** are a strong future source for documented oil/gas industrial incidents and investigation narratives. They are not automatically pilot labels: a report needs a date/location that can be linked to satellite overpass and footprint, and coverage is sector-selective.
* **Local incident reporting** yields the Bhowra transformer, Barari 6/Jharia, and Bokaro Steel Plant reports in the evidence register. Their available location/time granularity is insufficient for linking a specific FIRMS row. Treat as weak candidate events only.
* **OSM and GEM** are contextual asset inventories, not incident registries. Current snapshots may post-date a detection; proximity identifies a place to inspect, not the cause of a thermal anomaly. GEM additionally covers coal assets, not all industrial sources.
* **Sentinel-2** has only a few chips in this investigation and almost all relevant values are post-detection or cloud-affected; 2 rows have temporally eligible samples. Optical 10/20 m imagery may offer surface context but cannot certify short-lived fires or absence at FIRMS overpass time. The same evidence limits apply to visual interpretation.
* **Public burned-area/fire products** can help identify broad vegetation-fire context, but they are not an industrial-cause label set. Some products are temporally/coarsely aggregated or derived partly using active-fire observations, so independence and spatial match must be checked before use.

## Review ranking (not classification)

`candidate_review_priority_score` is a transparent ordering for human evidence collection. It uses only the current row's nonnegative FRP and the existing count of **strictly earlier** distinct FIRMS acquisition dates in the 250 m grid cell:

`0.55 * FRP/(FRP + 5 MW) + 0.45 * prior_dates/(prior_dates + 3)`

The constants and weights are fixed heuristics, not fitted parameters. The score is not calibrated, not a posterior probability, and not a class prediction. OSM, GEM, confidence, and Sentinel-2 are displayed as review context but do not increase the score. Repeated detections in one cell are temporally recurring observations, not proven distinct physical sources. The output does not make a train/test split.

## Evaluation plan when labels are collected

1. Preserve source URL/document ID, access date, incident ID, annotator, exact class, event time interval, geospatial footprint/uncertainty, sensor overpass time, evidence excerpt, confidence rationale, and adjudication history.
2. Link a FIRMS row only when the incident footprint and time uncertainty overlap a plausible sensor footprint/overpass. Keep ambiguous links weak or unknown. Have a second reviewer adjudicate positives and all negative candidates.
3. Require observable negatives: a time-matched, sufficiently clear and spatially resolved inspection plus documented source coverage. Missing detections, imagery, reports, or mapped facilities do not establish a negative.
4. Do not randomly split rows. Group all rows from a single incident/site and spatially neighboring cells (initially at least a 1 km site buffer) together, and keep a later temporal block for prospective evaluation. Select thresholds only on training/validation groups. Report metrics only after enough independent, adjudicated events exist; show event-level and row-level counts and uncertainty.

## Artifacts

* `label_evidence_register.csv`: citable external event leads and explicit detection-linkage limitations and confidence rationale.
* `candidate_label_sources.csv`: source inventory with class potential, evidence value, and limitations.
* `candidate_review_priority.csv`: all source rows ordered by the non-model review heuristic.
* `top_100_for_manual_evidence_review.csv`: first 100 ranked observations, still all marked unknown.
* `label_readiness.json`: counts, validation checks, and explicit absence of model metrics.
* `review_priority_overview.png`: score/rank and evidence-context visualization.
* `methodology.md`: this labeling and evaluation protocol.
"""
    (path / "methodology.md").write_text(content, encoding="utf-8")


def main() -> None:
    if not FEATURES.exists():
        raise FileNotFoundError(f"Feature table not found: {FEATURES}")
    features = pd.read_csv(FEATURES, low_memory=False)
    if features["firms_source_row"].duplicated().any():
        raise ValueError("Expected one feature row per unique FIRMS source row")
    ranking = build_ranking(features)
    incidents = incident_register()
    sources = source_inventory()
    output = make_output_dir()

    incidents.to_csv(output / "label_evidence_register.csv", index=False)
    sources.to_csv(output / "candidate_label_sources.csv", index=False)
    ranking.to_csv(output / "candidate_review_priority.csv", index=False)
    ranking.head(TOP_N).to_csv(output / "top_100_for_manual_evidence_review.csv", index=False)

    # Plot two complementary views: the review order and its unscored context.
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.2))
    axes[0].hist(ranking["candidate_review_priority_score"], bins=30, color="#3478a5", edgecolor="white")
    axes[0].set_title("Manual review score distribution")
    axes[0].set_xlabel("Heuristic score (not a probability or label)")
    axes[0].set_ylabel("FIRMS detection rows")
    top = ranking.head(TOP_N)
    role_counts = top["osm_nearest_relevant_role"].fillna("no mapped relevant role").value_counts().head(8).sort_values()
    role_counts.plot.barh(ax=axes[1], color="#d27d2d")
    axes[1].set_title("OSM context among top 100 review rows")
    axes[1].set_xlabel("Rows (context only; not used as class label or score input)")
    axes[1].set_ylabel("Nearest relevant mapped role")
    fig.suptitle("ThermoScope pilot — label evidence is not yet sufficient for supervised evaluation", fontsize=12)
    fig.tight_layout()
    fig.savefig(output / "review_priority_overview.png", dpi=170, bbox_inches="tight")
    plt.close(fig)

    prior = pd.to_datetime(features["cell_prior_last_acquisition_date"], errors="coerce")
    acq = pd.to_datetime(features["acq_date"], errors="coerce")
    missing_coords = features[["latitude", "longitude"]].isna().any(axis=1)
    coords_ok = features.latitude.between(23.25, 24.00) & features.longitude.between(85.75, 86.75)
    checks = {
        "source_feature_rows": int(len(features)),
        "unique_firms_source_rows": int(features.firms_source_row.nunique()),
        "unique_250m_cells": int(features.hotspot_cell_id.nunique()),
        "duplicate_firms_source_row_count": int(features.firms_source_row.duplicated().sum()),
        "missing_coordinate_rows": int(missing_coords.sum()),
        "coordinates_within_pilot_bbox_rows": int(coords_ok.sum()),
        "rows_outside_pilot_bbox": int((~coords_ok).sum()),
        "past_only_recurrence_violations": int((prior.notna() & prior.ge(acq)).sum()),
        "review_score_missing_or_nonfinite": int((~np.isfinite(ranking.candidate_review_priority_score)).sum()),
        "candidate_rank_unique": bool(ranking.review_priority_rank.is_unique),
        "detection_labels_assigned": int(ranking.firms_detection_label.ne("unknown_unlinked").sum()),
        "verified_detection_labels": 0,
        "weak_detection_labels": 0,
        "unknown_unlinked_detection_rows": int(len(ranking)),
        "external_event_records": int(len(incidents)),
        "verified_event_only_records": int(incidents.evidence_tier.eq("verified_event_only").sum()),
        "weak_candidate_event_records": int(incidents.evidence_tier.eq("weak_candidate_event").sum()),
        "linked_event_records": int(incidents.firms_detection_link.ne("not_linkable_from_record").sum()),
        "evaluation_split_created": False,
        "model_metrics_computed": False,
    }
    if checks["duplicate_firms_source_row_count"] or checks["missing_coordinate_rows"] or checks["rows_outside_pilot_bbox"]:
        raise ValueError(f"Input validation failed: {checks}")
    if checks["past_only_recurrence_violations"] or checks["review_score_missing_or_nonfinite"] or not checks["candidate_rank_unique"]:
        raise ValueError(f"Ranking validation failed: {checks}")
    (output / "label_readiness.json").write_text(json.dumps({
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "feature_input": str(FEATURES.relative_to(ROOT)).replace("\\", "/"),
        "run_directory": output.name,
        "checks": checks,
        "decision": "supervised_classification_not_justified",
        "reason": "No independently verified FIRMS detection-level labels or observable negative cases are available.",
        "metrics": None,
        "score_is_probability": False,
    }, indent=2), encoding="utf-8")
    write_methodology(
        output, len(features), features.hotspot_cell_id.nunique(),
        int(incidents.evidence_tier.eq("verified_event_only").sum()),
        int(incidents.evidence_tier.eq("weak_candidate_event").sum()),
    )
    print(f"Output: {output}")
    print(json.dumps(checks, indent=2))


if __name__ == "__main__":
    main()
