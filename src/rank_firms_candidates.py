"""Create an auditable, non-supervised ThermoScope candidate review ranking.

Categories and scores prioritize human investigation only. They are not source
class predictions, calibrated probabilities, verified labels, or model metrics.
No FIRMS row is labeled by proximity, recurrence, or imagery availability.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
FEATURE_PARENT = ROOT / "data/processed/feature_engineering"
LABEL_PARENT = ROOT / "data/processed/label_evaluation"
OUTPUT_PARENT = ROOT / "data/processed/candidate_ranking"
S2_BANDS = ["s2_b04_red_dn", "s2_b03_green_dn", "s2_b02_blue_dn", "s2_b11_swir16_dn"]
INFRASTRUCTURE_DISTANCE_FIELDS = [
    "nearest_power_transmission_tower_distance_m", "nearest_power_transmission_line_distance_m",
    "nearest_power_transmission_other_distance_m", "nearest_power_distribution_distance_m",
    "nearest_power_other_distance_m",
]
RELEVANT_ROLE_WEIGHTS = {
    "mining_extraction_area": 1.0, "mine_working_feature": 1.0,
    "industrial_landuse": 1.0, "industrial_facility": 1.0,
    "power_generation": 0.85, "power_site": 0.8,
    "waste_facility": 0.75, "industrial_rail": 0.7,
}
FRP_REVIEW_THRESHOLD_MW = 5.0
RECURRENCE_REVIEW_THRESHOLD_DATES = 3
INDUSTRIAL_CONTEXT_NEAR_M = 250.0
CONTEXT_DISTANCE_CAP_M = 1000.0
SCORE_WEIGHTS = {"thermal": 0.50, "past_recurrence": 0.30, "mapped_relevant_context": 0.20}


def latest_feature_table(parent: Path = FEATURE_PARENT) -> Path:
    for run in sorted(parent.iterdir(), key=lambda p: p.name, reverse=True) if parent.exists() else []:
        path = run / "feature_table.csv.gz"
        if path.is_file():
            return path
    raise FileNotFoundError(f"No feature_table.csv.gz found below {parent}")


def latest_label_run(parent: Path = LABEL_PARENT) -> Path | None:
    for run in sorted(parent.iterdir(), key=lambda p: p.name, reverse=True) if parent.exists() else []:
        if (run / "label_readiness.json").is_file() and (run / "label_evidence_register.csv").is_file():
            return run
    return None


def make_output_dir(path: Path | None) -> Path:
    if path is not None:
        output = path if path.is_absolute() else (ROOT / path).resolve()
        output.mkdir(parents=True, exist_ok=False)
        return output
    OUTPUT_PARENT.mkdir(parents=True, exist_ok=True)
    output = OUTPUT_PARENT / datetime.now(timezone.utc).strftime("run_%Y%m%dT%H%M%SZ")
    output.mkdir(exist_ok=False)
    return output


def build_candidate_ranking(features: pd.DataFrame) -> pd.DataFrame:
    """Apply fixed review rules after auditing recurrence and imagery timing."""
    required = {
        "firms_source_row", "latitude", "longitude", "acq_date", "acq_time",
        "thermal_frp_mw", "confidence", "daynight", "hotspot_cell_id",
        "cell_prior_distinct_acquisition_dates", "cell_prior_last_acquisition_date",
        "osm_nearest_relevant_distance_m", "osm_nearest_relevant_role",
    }
    missing = sorted(required - set(features.columns))
    if missing:
        raise ValueError(f"Feature input missing ranking fields: {missing}")
    if features.firms_source_row.duplicated().any():
        raise ValueError("Feature input must contain one row per unique firms_source_row")

    df = features.copy()
    acq_date = pd.to_datetime(df.acq_date, errors="coerce").dt.normalize()
    if acq_date.isna().any():
        raise ValueError("FIRMS acquisition dates contain missing or invalid values")
    prior_date = pd.to_datetime(df.cell_prior_last_acquisition_date, errors="coerce").dt.normalize()
    prior_n = pd.to_numeric(df.cell_prior_distinct_acquisition_dates, errors="coerce")
    if prior_n.isna().any() or (prior_n < 0).any():
        raise ValueError("Past-only recurrence counts must be present and nonnegative")
    if (prior_date.notna() & prior_date.ge(acq_date)).any():
        raise ValueError("Temporal leakage: prior recurrence date must be strictly earlier than detection date")
    if ((prior_n == 0) & prior_date.notna()).any() or ((prior_n > 0) & prior_date.isna()).any():
        raise ValueError("Recurrence count and prior-date fields are inconsistent")

    frp = pd.to_numeric(df.thermal_frp_mw, errors="coerce")
    df["candidate_frp_value_mw"] = frp
    df["thermal_frp_review_component"] = (frp.clip(lower=0) / 10.0).clip(upper=1).fillna(0)
    confidence = df.confidence.astype("string").str.strip().str.lower()
    conf_component = confidence.map({"h": 1.0, "n": 0.65, "l": 0.30})
    df["thermal_confidence_review_component"] = conf_component.fillna(0)
    df["thermal_evidence_component"] = (
        0.75 * df.thermal_frp_review_component + 0.25 * df.thermal_confidence_review_component
    )
    df["thermal_high_frp_flag"] = frp.ge(FRP_REVIEW_THRESHOLD_MW).fillna(False)
    df["firms_confidence_band"] = confidence.map({"h": "high", "n": "nominal", "l": "low"}).fillna("unknown")
    # Brightness and day/night are retained as row-level review context. Neither
    # has a validated, sensor-independent source-class threshold in this pilot.

    df["prior_distinct_dates_for_rule"] = prior_n.astype(float)
    df["persistent_thermal_evidence_flag"] = prior_n.ge(RECURRENCE_REVIEW_THRESHOLD_DATES)
    df["past_recurrence_component"] = prior_n / (prior_n + RECURRENCE_REVIEW_THRESHOLD_DATES)
    role = df.osm_nearest_relevant_role.astype("string").str.strip()
    distance = pd.to_numeric(df.osm_nearest_relevant_distance_m, errors="coerce")
    role_weight = role.map(RELEVANT_ROLE_WEIGHTS).fillna(0.0)
    df["osm_relevant_context_available"] = role_weight.gt(0) & distance.notna()
    df["osm_relevant_context_within_250m"] = df.osm_relevant_context_available & distance.le(INDUSTRIAL_CONTEXT_NEAR_M)
    df["osm_relevant_context_within_1km"] = df.osm_relevant_context_available & distance.le(CONTEXT_DISTANCE_CAP_M)
    match_status = df.get("osm_evidence_status_250m", df.get("match_status_250m", pd.Series(pd.NA, index=df.index)))
    match_status = match_status.astype("string").str.lower()
    ambiguous = match_status.str.contains("ambiguous", na=False)
    df["osm_match_ambiguous_flag"] = ambiguous
    df["osm_context_evidence_quality"] = np.select(
        [ambiguous, df.osm_relevant_context_within_250m, df.osm_relevant_context_within_1km],
        ["ambiguous_mapped_context", "relevant_mapped_context_within_250m", "relevant_mapped_context_within_1km"],
        default="no_relevant_context_recorded_within_1km",
    )
    df["mapped_relevant_context_component"] = (
        role_weight * (1.0 - distance.clip(lower=0, upper=CONTEXT_DISTANCE_CAP_M) / CONTEXT_DISTANCE_CAP_M)
    ).fillna(0)
    # A matcher ambiguity reduces context weight; it never creates a cause label.
    df.loc[ambiguous, "mapped_relevant_context_component"] *= 0.5

    infra_fields = [c for c in INFRASTRUCTURE_DISTANCE_FIELDS if c in df.columns]
    if infra_fields:
        infra_distance = df[infra_fields].apply(pd.to_numeric, errors="coerce").min(axis=1, skipna=True)
    else:
        infra_distance = pd.Series(np.nan, index=df.index)
    df["nearest_general_power_infrastructure_distance_m"] = infra_distance
    df["general_power_infrastructure_within_250m_flag"] = infra_distance.le(250).fillna(False)
    df["power_infrastructure_only_context_flag"] = (
        df.general_power_infrastructure_within_250m_flag & ~df.osm_relevant_context_within_250m
    )

    # GEM coverage is supplementary coal-asset context. It does not increase
    # candidate scores because facility proximity cannot identify cause.
    gem_distance = pd.to_numeric(df.get("gem_nearest_distance_m", pd.Series(np.nan, index=df.index)), errors="coerce")
    df["gem_context_within_1km_flag"] = gem_distance.le(1000).fillna(False)

    df["candidate_evidence_score"] = (
        SCORE_WEIGHTS["thermal"] * df.thermal_evidence_component
        + SCORE_WEIGHTS["past_recurrence"] * df.past_recurrence_component
        + SCORE_WEIGHTS["mapped_relevant_context"] * df.mapped_relevant_context_component
    )
    df["candidate_evidence_score"] = df.candidate_evidence_score.clip(0, 1)

    # Sentinel spectra are audit context only in this pilot. They are surfaced
    # as reviewability evidence, not scored: two samples cannot justify a
    # spectral rule, and DN values have no verified class-specific threshold.
    s2_columns_exist = all(c in df.columns for c in S2_BANDS)
    s2_flag = df.get("s2_spectral_predictor_eligible", pd.Series(False, index=df.index)).fillna(False).astype(bool)
    s2_pixel = df.get("s2_pixel_valid", pd.Series(False, index=df.index)).fillna(False).astype(bool)
    spectral_finite = df[S2_BANDS].apply(pd.to_numeric, errors="coerce").notna().all(axis=1) if s2_columns_exist else pd.Series(False, index=df.index)
    if (s2_flag & ~s2_pixel).any() or (s2_flag & ~spectral_finite).any():
        raise ValueError("Sentinel eligibility flags disagree with pixel validity or spectral values")
    s2_eligible = s2_flag & s2_pixel & spectral_finite
    if s2_eligible.any():
        scene_time = pd.to_datetime(df.get("s2_scene_datetime_utc", pd.Series(pd.NaT, index=df.index)), errors="coerce", utc=True)
        detection_time = pd.to_datetime(df.get("acquisition_datetime_utc", pd.Series(pd.NaT, index=df.index)), errors="coerce", utc=True)
        if (scene_time[s2_eligible].isna() | detection_time[s2_eligible].isna()).any():
            raise ValueError("Eligible Sentinel samples require scene and FIRMS acquisition timestamps")
        if (scene_time[s2_eligible] > detection_time[s2_eligible]).any():
            raise ValueError("Temporal leakage: eligible Sentinel scene occurs after FIRMS acquisition")
    df["sentinel2_clear_pre_detection_spectrum_available"] = s2_eligible
    df["sentinel2_review_context"] = np.where(s2_eligible, "valid_pre_detection_clear_pixel_spectrum",
                                               df.get("s2_spectral_data_status", pd.Series("not_available", index=df.index)).fillna("not_available").astype(str))

    # Exclusive descriptive buckets, ordered from strongest review evidence to
    # routine. These names describe evidence combinations, not source classes.
    df["candidate_category"] = np.select(
        [df.persistent_thermal_evidence_flag & df.osm_relevant_context_within_250m,
         df.persistent_thermal_evidence_flag & df.power_infrastructure_only_context_flag,
         df.persistent_thermal_evidence_flag,
         df.thermal_high_frp_flag & df.osm_relevant_context_within_250m,
         df.thermal_high_frp_flag],
        ["persistent_thermal_with_nearby_relevant_industrial_context",
         "persistent_thermal_near_general_power_infrastructure_only",
         "persistent_thermal_without_nearby_relevant_osm_context",
         "elevated_thermal_with_nearby_relevant_industrial_context",
         "elevated_thermal_without_nearby_relevant_osm_context"],
        default="other_thermal_observation_review",
    )
    df["evidence_rationale"] = [
        "; ".join(reason for condition, reason in [
            (bool(high_frp), "FRP at or above 5 MW"),
            (bool(recurrent), "at least 3 strictly prior distinct detection dates in the 250 m cell"),
            (bool(near_osm), f"nearest relevant mapped OSM role={r} at {d:.1f} m" if pd.notna(d) else "relevant OSM context within 250 m"),
            (bool(amb), "250 m OSM matcher status is ambiguous; context contribution downweighted"),
            (bool(infra_only), "general power infrastructure within 250 m without relevant industrial-role match"),
            (bool(s2), "valid pre-detection clear-pixel Sentinel-2 spectrum available for manual review only"),
        ] if condition) or "No high-priority rule met; retain for exploratory review"
        for high_frp, recurrent, near_osm, r, d, amb, infra_only, s2 in zip(
            df.thermal_high_frp_flag, df.persistent_thermal_evidence_flag,
            df.osm_relevant_context_within_250m, role, distance, ambiguous,
            df.power_infrastructure_only_context_flag, s2_eligible)
    ]
    df["review_priority_rank"] = df.candidate_evidence_score.rank(method="first", ascending=False).astype("int64")
    df["candidate_review_priority_band"] = np.select(
        [df.review_priority_rank.le(max(1, int(np.ceil(len(df) * 0.05)))),
         df.review_priority_rank.le(max(1, int(np.ceil(len(df) * 0.25))))],
        ["high_review_priority", "medium_review_priority"], default="routine_review_priority",
    )
    df["firms_detection_label"] = "unknown_unlinked"
    df["candidate_interpretation"] = (
        "Rule-based manual investigation priority only; not a fire classification, cause, probability, or ground-truth label."
    )
    keep = [
        "review_priority_rank", "candidate_review_priority_band", "candidate_evidence_score", "candidate_category",
        "evidence_rationale", "firms_source_row", "latitude", "longitude", "acq_date", "acq_time",
        "satellite", "instrument", "firms_sources", "thermal_frp_mw", "thermal_brightness_k",
        "thermal_brightness_t31_k", "confidence", "firms_confidence_band", "daynight",
        "thermal_frp_review_component", "thermal_confidence_review_component", "thermal_evidence_component",
        "cell_prior_detection_count", "cell_prior_distinct_acquisition_dates", "cell_prior_last_acquisition_date",
        "cell_days_since_prior_observation", "persistent_thermal_evidence_flag", "past_recurrence_component",
        "hotspot_cell_id", "osm_nearest_relevant_distance_m", "osm_nearest_relevant_role",
        "osm_nearest_relevant_category", "osm_relevant_context_within_250m", "osm_relevant_context_within_1km",
        "osm_context_evidence_quality", "osm_match_ambiguous_flag", "mapped_relevant_context_component",
        "nearest_general_power_infrastructure_distance_m", "general_power_infrastructure_within_250m_flag",
        "power_infrastructure_only_context_flag", "gem_nearest_distance_m", "gem_nearest_name",
        "gem_nearest_type", "gem_context_within_1km_flag", "s2_spectral_data_status",
        "s2_scene_datetime_utc", "s2_scene_offset_hours", "s2_scene_cloud_cover_percent",
        "s2_chip_scl_cloud_shadow_percent", "s2_pixel_cloud_screen_status",
        "sentinel2_clear_pre_detection_spectrum_available", *S2_BANDS,
        "sentinel2_review_context", "firms_detection_label", "candidate_interpretation",
    ]
    for column in keep:
        if column not in df:
            df[column] = pd.NA
    return df[keep].sort_values("review_priority_rank", kind="stable").reset_index(drop=True)


def build_summary_tables(ranking: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    categories = (ranking.groupby("candidate_category", dropna=False)
                  .agg(detections=("firms_source_row", "size"),
                       unique_cells=("hotspot_cell_id", "nunique"),
                       median_frp_mw=("thermal_frp_mw", "median"),
                       median_prior_dates=("cell_prior_distinct_acquisition_dates", "median"),
                       within_250m_osm_context=("osm_relevant_context_within_250m", "sum"),
                       valid_sentinel_spectra=("sentinel2_clear_pre_detection_spectrum_available", "sum"))
                  .reset_index().sort_values("detections", ascending=False))
    evidence_rows = []
    for label, mask in [
        ("FRP >= 5 MW", pd.to_numeric(ranking.thermal_frp_mw, errors="coerce").ge(FRP_REVIEW_THRESHOLD_MW)),
        ("High FIRMS confidence", ranking.firms_confidence_band.eq("high")),
        ("At least 3 strictly prior distinct dates", ranking.persistent_thermal_evidence_flag),
        ("Relevant OSM context <= 250 m", ranking.osm_relevant_context_within_250m),
        ("Ambiguous OSM 250 m status", ranking.osm_match_ambiguous_flag),
        ("General power infrastructure <= 250 m", ranking.general_power_infrastructure_within_250m_flag),
        ("Power infrastructure only <= 250 m", ranking.power_infrastructure_only_context_flag),
        ("GEM supplementary facility <= 1 km", ranking.gem_context_within_1km_flag),
        ("Usable pre-detection S2 spectrum", ranking.sentinel2_clear_pre_detection_spectrum_available),
    ]:
        evidence_rows.append({"evidence_indicator": label, "detections": int(mask.sum()),
                              "percent_of_detections": round(float(mask.mean() * 100), 3)})
    return categories, pd.DataFrame(evidence_rows)


def save_visualizations(ranking: pd.DataFrame, categories: pd.DataFrame, evidence: pd.DataFrame, outdir: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    shown = categories.sort_values("detections")
    axes[0].barh(shown.candidate_category.str.replace("_", " "), shown.detections, color="#3b7598")
    axes[0].set_title("Rule-based candidate evidence categories")
    axes[0].set_xlabel("FIRMS detections (all remain unknown/unlinked)")
    scatter = axes[1].scatter(
        ranking.cell_prior_distinct_acquisition_dates,
        pd.to_numeric(ranking.thermal_frp_mw, errors="coerce"),
        c=ranking.candidate_evidence_score, cmap="viridis", s=10, alpha=0.5,
    )
    axes[1].axhline(FRP_REVIEW_THRESHOLD_MW, linestyle="--", color="#aa5544", linewidth=1, label="FRP review threshold")
    axes[1].axvline(RECURRENCE_REVIEW_THRESHOLD_DATES, linestyle=":", color="#333333", linewidth=1, label="prior-date rule")
    axes[1].set_title("Thermal strength vs. strictly past recurrence")
    axes[1].set_xlabel("Earlier distinct FIRMS dates in 250 m cell")
    axes[1].set_ylabel("FRP (MW)")
    axes[1].legend(fontsize=8)
    fig.colorbar(scatter, ax=axes[1], label="Review score (not probability)")
    fig.suptitle("ThermoScope candidate review baseline — evidence combinations, not classifications")
    fig.tight_layout()
    fig.savefig(outdir / "candidate_categories_and_evidence.png", dpi=170, bbox_inches="tight")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(10, 5.5))
    ev = evidence.sort_values("detections")
    ax.barh(ev.evidence_indicator, ev.detections, color="#cb8b45")
    ax.set_xlabel("FIRMS detections")
    ax.set_title("Available evidence coverage (signals may overlap)")
    ax.grid(axis="x", alpha=0.2)
    fig.tight_layout()
    fig.savefig(outdir / "evidence_coverage.png", dpi=170, bbox_inches="tight")
    plt.close(fig)


def markdown_table(frame: pd.DataFrame) -> str:
    headers = [str(column) for column in frame.columns]
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for row in frame.itertuples(index=False, name=None):
        values = [str(value) for value in row]
        lines.append("| " + " | ".join(value.replace("|", "\\|") for value in values) + " |")
    return "\n".join(lines)


def write_report(outdir: Path, feature_path: Path, label_dir: Path | None, region_id: str,
                 ranking: pd.DataFrame, categories: pd.DataFrame, evidence: pd.DataFrame,
                 source_metadata: dict) -> None:
    cat_table = markdown_table(categories[["candidate_category", "detections", "unique_cells", "within_250m_osm_context", "valid_sentinel_spectra"]])
    ev_table = markdown_table(evidence)
    prep_summary = source_metadata.get("firms_preparation", {})
    osm_summary = source_metadata.get("osm_matching", {})
    s2_summary = source_metadata.get("sentinel2_integration", {}).get("counts", {})
    def count_text(value: object, fallback: str = "unknown") -> str:
        return f"{value:,}" if isinstance(value, (int, np.integer)) else fallback
    firms_line = (
        f"{count_text(prep_summary.get('output_rows'), f'{len(ranking):,}')} prepared {region_id} rows from "
        f"{count_text(prep_summary.get('archive_input_rows'))} archive and "
        f"{count_text(prep_summary.get('nrt_input_rows'))} NRT input records; "
        f"{prep_summary.get('duplicate_input_rows_removed', 'unknown')} duplicate rows removed; "
        f"date coverage {prep_summary.get('date_coverage', {}).get('minimum', 'unknown')} to "
        f"{prep_summary.get('date_coverage', {}).get('maximum', 'unknown')} across "
        f"{prep_summary.get('date_coverage', {}).get('distinct_acquisition_dates', 'unknown')} dates."
    )
    osm_line = (
        f"{osm_summary.get('osm_features_used', 'unknown')} OSM features used and "
        f"{osm_summary.get('gem_facility_records', 'unknown')} supplementary GEM records; "
        f"matching status counts `{json.dumps(osm_summary.get('match_status_counts', {}), sort_keys=True)}`."
    )
    s2_line = (
        f"{s2_summary.get('rows_with_chip_for_context', 0)} detections have chip context, "
        f"{s2_summary.get('rows_with_temporally_eligible_scene', 0)} a temporally eligible scene, "
        f"{s2_summary.get('rows_with_post_detection_imagery_withheld', 0)} are withheld as future imagery, and "
        f"{s2_summary.get('rows_with_valid_causal_spectral_samples', 0)} have valid causal clear-pixel samples."
    )
    label_summary = "No label-evidence run was found."
    if label_dir:
        readyp = label_dir / "label_readiness.json"
        if readyp.exists():
            checks = json.loads(readyp.read_text(encoding="utf-8")).get("checks", {})
            label_summary = (
                f"Latest label-evidence directory: `{label_dir.name}`. It records "
                f"{checks.get('verified_event_only_records', 'unknown')} official event-only record(s), "
                f"{checks.get('weak_candidate_event_records', 'unknown')} weak event lead(s), "
                f"{checks.get('verified_detection_labels', 'unknown')} verified detection labels, "
                f"{checks.get('weak_detection_labels', 'unknown')} weak detection labels, and "
                f"{checks.get('unknown_unlinked_detection_rows', 'unknown')} unknown/unlinked rows."
            )
    if region_id == "dhanbad_jharia_bokaro":
        label_readiness_text = (
            "The pilot event-evidence review is event-level only; none of its records is linked to a FIRMS detection."
            if label_dir else "No label-evidence run was supplied."
        )
    else:
        label_readiness_text = (
            "No Jharkhand-wide detection-level label evidence was supplied. Dhanbad pilot event leads are not transferred to other state observations."
            if label_dir is None else "Supplied evidence is reported as provenance only and does not automatically label detections."
        )
    clear_spectra = int(ranking.sentinel2_clear_pre_detection_spectrum_available.sum())
    report = f"""# ThermoScope rule-based candidate ranking: {region_id}

Run: `{outdir.name}`
Feature table: `{feature_path}`
Label evidence reviewed: `{label_dir if label_dir else 'none supplied for this region'}`

## Purpose and objective fit

The project objective—investigating potential industrial fires and persistent thermal sources using NASA FIRMS, OSM, and satellite data—is partly supported as an **evidence-integration and manual-review prioritization** task. FIRMS supplies time-stamped thermal detections and attributes; OSM supplies incomplete, current mapped facility/infrastructure context; GEM supplements coal-asset context; Sentinel-2 supplies optical surface context for a very small number of clear, pre-detection pixels.

The current inputs do not support a verified classification of industrial fire, mine fire, process heat, flare, vegetation fire, or negative/no-fire. The ranking therefore emits candidate evidence categories and keeps every detection `unknown_unlinked`. Proximity, recurrence, FRP, confidence, and imagery availability are not ground-truth labels.

**Supported now:** describe FIRMS thermal detections; identify repeated activity in fixed 250 m analysis cells using only earlier dates; summarize nearby mapped industrial/mining and general power-infrastructure context; flag the handful of detections with valid historical clear-pixel Sentinel-2 context; and order rows for human investigation.

**Not supported now:** infer that an OSM/GEM facility caused a detection; distinguish industrial fire from process heat, mine-fire venting, biomass fire, or other hot source; call an unlinked row a negative; confirm a short-lived fire from the sparse optical chips; or estimate classification accuracy. The current satellite and incident evidence are far too sparse for those conclusions.

## Label readiness

{label_summary}

{label_readiness_text} All ranking labels remain `unknown_unlinked`; the evidence categories are not source classes.

## Upstream data review

- **FIRMS preparation:** {firms_line}
- **OSM matching and GEM:** {osm_line} These are mapped-context references, not labels.
- **Sentinel-2 integration:** {s2_line} Only valid, pre-detection, clear-pixel samples are marked image-review-ready.

## Candidate categories

{cat_table}

The category names describe combinations for human investigation, not the underlying source class. General transmission towers, lines, and distribution infrastructure are recorded separately; they do not count as relevant industrial-role matches. Ambiguous 250 m OSM context is retained but its context score is halved and visibly flagged.

## Transparent scoring and rules

- **Thermal component:** `0.75 * min(max(FRP, 0) / 10 MW, 1) + 0.25 * confidence_component`, where FIRMS confidence H/N/L maps to 1.00/0.65/0.30. FRP >= 5 MW is a review flag, not a fire threshold. Brightness, T31, day/night and sensor attributes are preserved for reviewer context; no unsupported class-specific cutoffs are imposed.
- **Past recurrence component:** `prior distinct acquisition dates / (prior distinct acquisition dates + 3)`. “Persistent” review evidence requires at least three distinct dates strictly earlier than the row date in the existing 250 m grid cell. This is repeated cell activity, not a proven physical source.
- **Mapped context component:** nearest relevant OSM role weight times `max(0, 1 - distance/1000 m)`, with role weights documented in `src/rank_firms_candidates.py`. Ambiguous 250 m match status halves this component. General transmission infrastructure is not assigned industrial context.
- **Review score:** 0.50 thermal + 0.30 past recurrence + 0.20 mapped relevant context. It is an arbitrary, bounded review ordering, not calibrated probability, prediction, or class label. Missing mapped context is not evidence that no facility exists.
- **Sentinel-2:** a row is marked image-review-ready only when all four bands have finite values, the feature pipeline marks its pixel valid, and the Sentinel acquisition timestamp is not after the FIRMS timestamp. In this region, {clear_spectra} rows meet that condition. Spectral values do not change the score; this run has no region-matched spectral evidence adequate to define or validate source classes.
- **GEM:** distance within 1 km is displayed as supplementary coal-facility context and does not change the score or category.

## Evidence coverage

{ev_table}

## Validation and limitations

- Input rows: {len(ranking):,}; unique FIRMS source rows: {ranking.firms_source_row.nunique():,}; duplicate source row IDs: {int(ranking.firms_source_row.duplicated().sum())}.
- Detection labels assigned: 0; all rows remain `unknown_unlinked`. No negatives, train/test split, or performance metrics were created.
- Recurrence is strictly past-only; the script aborts if a prior date equals or exceeds the detection date.
- Sentinel features are required to have valid clear pixels and a nonfuture acquisition timestamp; the script aborts if an eligible row violates those conditions.
- OSM/GEM are static, incomplete snapshots. A mapped feature is context only; absent or ambiguous context does not establish a source or a negative.
- Sentinel-2 is optical at 10/20 m and the available usable samples are sparse. It cannot verify short-lived fire, radiance at FIRMS overpass, or absence.
- FIRMS confidence and FRP measure sensor-observation properties, not industrial cause. High FRP or high confidence cannot independently establish an industrial fire.

## Additional labeled data needed for supervised learning

1. Independently verified event/source records with stable incident IDs, source class, primary report, adjudication, event start/end uncertainty, georeferenced footprint or coordinate uncertainty, and evidence provenance.
2. Independent, time-matched evidence for persistent mine-fire/venting polygons and for other industrial process sources; current OSM/GEM facility presence is insufficient.
3. Auditable observable negatives: adequate clear imagery or authoritative inspection for the same time/footprint, with source coverage documented. Unreported or unmatched FIRMS rows must not be treated as negative.
4. Enough independent sites/incidents in each class for two-reviewer labels, spatially grouped holdouts and a later temporal test period. Keep every incident/site and neighboring grid cells within one split; report metrics only after adjudication and adequate independent test events.

## Artifacts

- `candidate_ranking.csv`: all FIRMS rows, evidence components, flags, rationale and explicit unknown label.
- `top_100_for_manual_review.csv`, `category_counts.csv`, `evidence_coverage.csv`.
- `rule_definitions.json`, `validation.json`, `report.md`.
- `input_lineage.json`: references to FIRMS preparation, OSM/GEM matching, Sentinel-2 feature quality, and label-evidence inputs.
- `candidate_categories_and_evidence.png`, `evidence_coverage.png`.
"""
    (outdir / "report.md").write_text(report, encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--features", type=Path, help="feature_table.csv.gz; defaults to newest local feature run")
    parser.add_argument("--labels-dir", type=Path, help="label-evidence run for readiness summary; defaults to newest local run")
    parser.add_argument("--no-label-evidence", action="store_true", help="do not attach label-evidence run discovery to a non-pilot region")
    parser.add_argument("--output-dir", type=Path, help="new result directory; must not exist")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    root = args.repo.resolve()
    feature_path = args.features if args.features and args.features.is_absolute() else (root / args.features if args.features else latest_feature_table(root / "data/processed/feature_engineering"))
    if not feature_path.is_file():
        raise FileNotFoundError(f"Feature table not found: {feature_path}")
    features = pd.read_csv(feature_path, low_memory=False)
    region_values = sorted(set(features.region_id.dropna().astype(str))) if "region_id" in features else []
    if len(region_values) > 1:
        raise ValueError(f"Feature table contains multiple region IDs: {region_values}")
    region_id = region_values[0] if region_values else "unknown_region"
    if args.labels_dir:
        label_dir = args.labels_dir if args.labels_dir.is_absolute() else root / args.labels_dir
    elif args.no_label_evidence or region_id != "dhanbad_jharia_bokaro":
        label_dir = None
    else:
        label_dir = latest_label_run(root / "data/processed/label_evaluation")
    if label_dir is not None and not label_dir.is_dir():
        raise FileNotFoundError(f"Label-evidence directory not found: {label_dir}")
    ranking = build_candidate_ranking(features)
    if not ranking.firms_detection_label.eq("unknown_unlinked").all():
        raise AssertionError("Candidate ranking must not assign detection labels")
    categories, evidence = build_summary_tables(ranking)
    outdir = make_output_dir(args.output_dir)
    ranking.to_csv(outdir / "candidate_ranking.csv", index=False)
    ranking.head(100).to_csv(outdir / "top_100_for_manual_review.csv", index=False)
    categories.to_csv(outdir / "category_counts.csv", index=False)
    evidence.to_csv(outdir / "evidence_coverage.csv", index=False)
    definitions = {
        "interpretation": "Manual-review priority only; not a probability, classification, cause attribution, or ground-truth label.",
        "candidate_categories": {
            "persistent_thermal_with_nearby_relevant_industrial_context": "At least 3 prior distinct FIRMS dates and a relevant mapped OSM role within 250 m.",
            "persistent_thermal_near_general_power_infrastructure_only": "At least 3 prior distinct dates and general transmission/distribution infrastructure within 250 m, with no relevant industrial role within 250 m.",
            "persistent_thermal_without_nearby_relevant_osm_context": "At least 3 prior distinct dates, without relevant OSM context within 250 m.",
            "elevated_thermal_with_nearby_relevant_industrial_context": "FRP >= 5 MW and relevant OSM context within 250 m, without the persistent rule above.",
            "elevated_thermal_without_nearby_relevant_osm_context": "FRP >= 5 MW without the higher-priority rules above.",
            "other_thermal_observation_review": "Retained detection not meeting the review rules above.",
        },
        "thresholds": {"FRP_review_flag_mw": FRP_REVIEW_THRESHOLD_MW,
                       "strictly_prior_dates_for_persistent_flag": RECURRENCE_REVIEW_THRESHOLD_DATES,
                       "near_relevant_osm_m": INDUSTRIAL_CONTEXT_NEAR_M,
                       "context_distance_cap_m": CONTEXT_DISTANCE_CAP_M},
        "score_weights": SCORE_WEIGHTS,
        "confidence_components": {"H": 1.0, "N": 0.65, "L": 0.30, "unknown": 0.0},
        "osm_role_weights": RELEVANT_ROLE_WEIGHTS,
        "ambiguous_osm_context_multiplier": 0.5,
        "satellite_policy": "Only valid, clear, temporally causal bands are surfaced. They do not affect score or category because only two samples and no validated class signature are available.",
        "labels": "All rows remain unknown_unlinked. No labels or negatives are inferred.",
    }
    (outdir / "rule_definitions.json").write_text(json.dumps(definitions, indent=2), encoding="utf-8")
    save_visualizations(ranking, categories, evidence, outdir)

    label_readiness_path = label_dir / "label_readiness.json" if label_dir else None
    label_readiness = json.loads(label_readiness_path.read_text(encoding="utf-8")) if label_readiness_path and label_readiness_path.exists() else {}
    label_checks = label_readiness.get("checks", {})
    source_metadata = {
        "region_id": region_id,
        "feature_table": str(feature_path), "feature_rows": int(len(features)),
        "latest_label_evidence_run": str(label_dir) if label_dir else None,
        "label_detection_rows_unknown": label_checks.get("unknown_unlinked_detection_rows"),
        "verified_detection_labels": label_checks.get("verified_detection_labels"),
        "weak_detection_labels": label_checks.get("weak_detection_labels"),
        "firms_preparation": {}, "osm_matching": {}, "sentinel2_integration": {},
    }
    feature_quality = feature_path.parent / "quality_checks.json"
    quality = json.loads(feature_quality.read_text(encoding="utf-8")) if feature_quality.is_file() else {}
    input_paths = quality.get("source_paths", {})
    prep_source = input_paths.get("firms")
    prep_report = Path(str(prep_source) + ".quality.json") if prep_source else None
    if prep_report is not None and not prep_report.is_absolute():
        prep_report = root / prep_report
    match_source = input_paths.get("matching_csv")
    match_report = Path(match_source).parent / "summary.json" if match_source else None
    if match_report is not None and not match_report.is_absolute():
        match_report = root / match_report
    if prep_report is not None and prep_report.is_file():
        prep = json.loads(prep_report.read_text(encoding="utf-8"))
        source_metadata["firms_preparation"] = {
            "report": str(prep_report), "output_rows": prep.get("output", {}).get("row_count"),
            "date_coverage": prep.get("output", {}).get("date_coverage"),
            "duplicate_input_rows_removed": prep.get("deduplication", {}).get("duplicate_input_rows_removed"),
            "archive_input_rows": prep.get("sources", {}).get("archive", {}).get("input_rows"),
            "nrt_input_rows": prep.get("sources", {}).get("nrt", {}).get("input_rows"),
        }
    if match_report is not None and match_report.is_file():
        match = json.loads(match_report.read_text(encoding="utf-8"))
        source_metadata["osm_matching"] = {
            "report": str(match_report), "osm_features_used": match.get("osm_features_used"),
            "gem_facility_records": match.get("gem_filtered_records"),
            "match_status_counts": match.get("match_status_counts"),
            "osm_relevant_category_counts": match.get("osm_relevant_category_counts_overlapping"),
            "distance_threshold_summary": match.get("distance_threshold_summary"),
        }
    if feature_quality.is_file():
        q = json.loads(feature_quality.read_text(encoding="utf-8"))
        source_metadata["sentinel2_integration"] = {
            "quality_report": str(feature_quality), "counts": q.get("sentinel2"),
            "ground_truth_labels_available": q.get("ground_truth_labels_available"),
        }
    (outdir / "input_lineage.json").write_text(json.dumps(source_metadata, indent=2), encoding="utf-8")
    checks = {
        "rows": int(len(ranking)), "unique_firms_source_rows": int(ranking.firms_source_row.nunique()),
        "duplicate_source_rows": int(ranking.firms_source_row.duplicated().sum()),
        "all_labels_unknown_unlinked": bool(ranking.firms_detection_label.eq("unknown_unlinked").all()),
        "unique_priority_ranks": bool(ranking.review_priority_rank.is_unique),
        "score_finite_and_bounded_0_1": bool(np.isfinite(ranking.candidate_evidence_score).all() and ranking.candidate_evidence_score.between(0, 1).all()),
        "strict_prior_date_rule_passed": True,
        "eligible_sentinel_spectra_nonfuture_and_complete": True,
        "supervised_model_trained": False, "metrics_computed": False,
    }
    (outdir / "validation.json").write_text(json.dumps(checks, indent=2), encoding="utf-8")
    write_report(outdir, feature_path, label_dir, region_id, ranking, categories, evidence, source_metadata)
    print(json.dumps({"output": str(outdir), "rows": len(ranking),
                      "category_counts": dict(zip(categories.candidate_category, categories.detections)),
                      "all_unknown": checks["all_labels_unknown_unlinked"], "validation": checks}, indent=2))


if __name__ == "__main__":
    main()
