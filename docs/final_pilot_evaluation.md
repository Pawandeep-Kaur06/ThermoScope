# Final pilot evaluation and scientific limitations

## Scope and evaluation method

This evaluation uses only the completed `run_001` experiment, the existing `outputs/final_pilot` analysis tables, and its 12 representative case studies. No experiment stage was rerun, no data were retrieved, and no labels or classifier were created. The evaluation is descriptive: stage alignment, data-quality checks, evidence coverage, rule-based candidate summaries, threshold sensitivity, and review-case comparison.

The saved ranking uses FRP ≥5 MW, at least three strictly earlier distinct FIRMS acquisition dates in a 250 m cell, and relevant mapped OSM context within 250 m. General power infrastructure is separated from relevant industrial context. The evidence score weights thermal evidence 0.5, past recurrence 0.3, and mapped context 0.2; it is a manual-review score, not a probability. Satellite spectra are surfaced for review but do not change score or category.

## Data quality and evidence coverage

The prepared input contains **9,220 detections** from **184 dates** (2026-01-20 to 2026-09-05). The source quality report attributes 6,498 rows to the FIRMS archive and 2,722 to NRT; it recorded zero within-region duplicates and zero archive/NRT overlap. Confidence attributes are `n` 8,471, `l` 743, and `h` 6. The archive/NRT source schemas differ: the prepared `type` attribute is absent for 2,722 rows, matching the NRT source column omission. This establishes data lineage and row-level completeness for the chosen inputs, not complete observation of all real-world fires or thermal sources.

FIRMS, matching, feature, and ranking files each have 9,220 rows. Stable FIRMS IDs are unique and align among source, match, and feature tables; all coordinates passed the pilot bbox checks, and saved processing validation passed. Matching used EPSG:32645. The OSM snapshot supplied 8,333 features; 8,206 entered industrial proximity matching, with 127 vegetation/context features retained as context rather than assigned industrial roles. No invalid/empty used geometry was recorded.

Matching is complete as a table join, but useful mapped industrial evidence is not universal. At 250 m, **7,679** rows are unambiguous proximity candidates, **334** are ambiguous, and **1,207** have no relevant mapped feature within the threshold. At 1 km the counts are **8,276**, **650**, and **294**, respectively. Feature-role coverage overlaps: at 250 m, mining/extraction areas occur near 7,049 detections, industrial land use near 944, facilities near 567, transmission lines near 152, and towers near 140. These are proximity indicators to the mapped snapshot, not source matches. The 615 rows without a saved nearest relevant role and the fully missing `osm_nearest_relevant_feature_id` field limit traceability; overall nearest OSM IDs remain present separately.

OSM completeness and vintage are not independently known. Features may be missing, generalized, mistagged, or changed between the map snapshot and FIRMS dates. Lines, points, and polygon distances are measured to their mapped geometries, whose positional accuracy is not quantified here. In particular, transmission infrastructure is not treated as industrial attribution. GEM contributes 96 supplementary coal-asset records, not broad industrial coverage, and its snapshots have no historical as-of dates.

Past-only recurrence features have no missing values for prior distinct-date counts; 1,092 rows have no prior last-date/mean value because they have no earlier observation in their cell/source window. The fixed 250 m projected grid contains 1,063 occupied cells, of which 522 recur on multiple dates; 7,136 detections meet the ≥3-prior-date ranking rule. The feature-quality check confirmed dates used were strictly earlier and same-date rows were excluded. However, the observation history starts on 2026-01-20, so recurrence is left-truncated; grid cells are spatial bins and may mix physical sources or split one changing source across cells.

Sentinel-2 is the limiting evidence stream: 530 records have chip context, 11 have a temporally eligible scene, and only **2 (0.022%)** have usable pre-detection spectra. 519 post-detection scenes are withheld; 440 chips have heavy cloud/shadow and 9 have cloud or unverifiable pixel screens. The four spectral bands are missing for 9,218 rows each. Missingness and withheld imagery cannot be interpreted as absence of fire or industrial activity.

Other missingness: FIRMS `type` is absent in NRT rows by source schema; `cell_prior_last_acquisition_date`/prior-mean missingness is expected where no prior recurrence exists; nearest OSM role-specific distances are null when no matching feature of that role was available in the matcher; `s2_scene_item_id` and related scene metadata are unavailable for rows without chip metadata. These are different causes of missingness and should not be collapsed into one meaning.

## Candidate-ranking categories and evidence characteristics

Categories below are mutually exclusive rule buckets for review. They are not source classes, incident labels, or probabilities. The recurrence values are medians of strictly prior distinct dates; OSM/power counts overlap only as evidence fields within categories.

| Rule-based review category | Detections | 250 m cells | Median FRP (MW) | Median prior distinct dates | Relevant OSM ≤250 m | Power-only ≤250 m |
|---|---:|---:|---:|---:|---:|---:|
| `persistent_thermal_with_nearby_relevant_industrial_context` | 6,550 | 329 | 2.34 | 16.5 | 6,550 | 0 |
| `persistent_thermal_near_general_power_infrastructure_only` | 30 | 7 | 0.96 | 6.5 | 0 | 30 |
| `persistent_thermal_without_nearby_relevant_osm_context` | 556 | 78 | 1.46 | 8.0 | 0 | 0 |
| `elevated_thermal_with_nearby_relevant_industrial_context` | 57 | 49 | 6.13 | 1.0 | 57 | 0 |
| `elevated_thermal_without_nearby_relevant_osm_context` | 106 | 105 | 7.08 | 0.0 | 0 | 14 |
| `other_thermal_observation_review` | 1,921 | 955 | 1.69 | 0.0 | 1,298 | 64 |

The largest bucket, persistent thermal with relevant industrial context, has 6,550 rows in 329 cells, median FRP 2.34 MW, and median 16.5 prior dates. The two elevated buckets contain 57 and 106 rows, with median FRP 6.13 and 7.08 MW and median prior-date counts 1 and 0, respectively. The power-only persistent bucket has 30 rows in 7 cells, median FRP 0.96 MW, and median 6.5 prior dates. The ‘other’ bucket is intentionally broad. Differences are induced partly by the category rules themselves; they do not show validated separation among physical sources.

### Distance-threshold sensitivity

The observed matcher statuses become more inclusive as distance increases: candidates 6,963 → 7,679 → 8,031 → 8,276 from 100 m through 1 km; ambiguity 249 → 334 → 472 → 650; no relevant feature 2,008 → 1,207 → 717 → 294. In a counterfactual re-binning, FRP ≥5 MW and ≥3 prior dates were held fixed while the relevant-context and power-only radius changed together; evidence scores were held fixed. The 250 m row reproduces the saved categories exactly.

| Threshold | Rows reclassified vs 250 m | Category counts at that threshold |
|---:|---:|---|
| 100 m | 604 (6.6%) | elevated thermal with nearby relevant industrial context 50; elevated thermal without nearby relevant osm context 113; other thermal observation review 1,921; persistent thermal near general power infrastructure only 10; persistent thermal with nearby relevant industrial context 5,973; persistent thermal without nearby relevant osm context 1,153 |
| 250 m | 0 (0.0%) | elevated thermal with nearby relevant industrial context 57; elevated thermal without nearby relevant osm context 106; other thermal observation review 1,921; persistent thermal near general power infrastructure only 30; persistent thermal with nearby relevant industrial context 6,550; persistent thermal without nearby relevant osm context 556 |
| 500 m | 316 (3.4%) | elevated thermal with nearby relevant industrial context 60; elevated thermal without nearby relevant osm context 103; other thermal observation review 1,921; persistent thermal near general power infrastructure only 84; persistent thermal with nearby relevant industrial context 6,809; persistent thermal without nearby relevant osm context 243 |
| 1000 m | 541 (5.9%) | elevated thermal with nearby relevant industrial context 65; elevated thermal without nearby relevant osm context 98; other thermal observation review 1,921; persistent thermal near general power infrastructure only 117; persistent thermal with nearby relevant industrial context 6,991; persistent thermal without nearby relevant osm context 28 |

This is rule sensitivity, not classification error. A larger radius moves detections into mapped-context categories by definition and can inflate apparent association; it does not establish a causal industrial source. The candidate score itself uses continuous distance with a 1 km cap, while category membership uses a hard 250 m cut-off; rows near the cut-off can therefore change category abruptly even though their score changes smoothly or not at all in this counterfactual.

![OSM threshold and category sensitivity](../outputs/final_pilot/figures/09_evaluation_threshold_sensitivity.png)

![Category evidence comparison](../outputs/final_pilot/figures/10_candidate_category_evidence_comparison.png)

## Representative-case evaluation

The 12 cases are purposively balanced at two per ranking category, with within-category rank positions chosen around the 25th/75th percentiles and chip availability considered. They are not a random sample and cannot estimate population behavior. All 12 have nominal FIRMS confidence `n`; FRP ranges from 0.88 to 9.00 MW; prior-date recurrence ranges from 0 to 29. Eleven cases have at least one mapped industrial or power feature within 1 km, but nearby lines/towers or mining polygons still do not establish source identity or cause.

| Selected review-group | Cases | Median FRP (MW) | Median prior distinct dates |
|---|---:|---:|---:|
| elevated review categories | 4 | 6.38 | 0.0 |
| other review category | 2 | 1.39 | 1.5 |
| persistent review categories | 6 | 1.23 | 12.0 |

The elevated examples have higher FRP by construction, while persistent examples show earlier repeat observations by construction. These case differences therefore illustrate the rules and their evidence, not an independent class comparison. The persistent-without-relevant-context examples include one case with a nearby mapped mine beyond 250 m and another near general transmission infrastructure; mapped-context categories include observations at/near mapped extraction areas. Both patterns demonstrate that a 250 m threshold can omit nearby mapped assets and that zero-distance polygon overlap does not confirm the thermal source is inside/caused by that industrial site.

Four selected observations have existing Sentinel-2 chips, all acquired after their FIRMS dates. Scene cloud estimates range from 14.2% to 87.1%; two have clear pixel-level SCL flags but are still future imagery for the corresponding detection, while two have at least 50% chip cloud/shadow. None of the selected cases has eligible pre-detection spectra. A later image describes later surface conditions and cannot establish what existed at the FIRMS acquisition time. The per-case summaries distinguish scene date, cloud screen, and eligibility.

![Selected case evidence scatter](../outputs/final_pilot/figures/11_case_study_evidence_scatter.png)

## Scientific validity and limitations

### No verified detection-level labels

There are zero verified FIRMS-to-incident links, zero adjudicated positive detections, and no defensible negative examples. The human review fields in this case register are pending, not completed judgments. Accuracy, precision, recall, F-score, ROC/AUC, calibration, and other supervised metrics cannot be calculated because no truth labels or evaluation outcomes exist. Treating the rule categories, OSM/GEM proximity, or recurrence as labels would be circular and invalid. No supervised classifier is justified by the current data.

### Causality, source identity, and temporal evidence

- **Proximity is association only:** FIRMS geolocation uncertainty, source geometry/extent, mixed land use, and OSM positional/tagging completeness prevent causal attribution from distance alone.
- **Recurrence is not identity:** repeat dates within a 250 m cell can arise from multiple sources, shifting plumes or footprints, repeated overpasses, or geolocation scatter. Recurrence only counts observations in the available window and is not continuous-duration proof.
- **Post-detection optical imagery is not pre-event evidence:** later Sentinel-2 scenes cannot establish pre-detection surface conditions. Even clear optical imagery is not thermal confirmation and may miss short-lived events between revisit dates.
- **Ranking is a heuristic:** thresholds and weights are hand-set, not learned or calibrated against outcomes. The high nominal-confidence prevalence, low high-confidence count, cloud/sensor effects, class imbalance, OSM vintage, missing imagery, and threshold discontinuities affect ordering. Different plausible thresholds or weights can reorder candidates.
- **Study scope is narrow:** results describe one pilot rectangle and the 2026 FIRMS input period. They do not establish transfer to other regions, industries, sensors, seasons, or historical periods.

## Recommendations

1. Keep outputs named candidate-review priorities and unknowns; do not call them fire classifications.
2. Human-review a small, stratified set with dated, georeferenced, independent incident sources. Record source URLs, time/location precision, decision, reviewer, rationale, and uncertainty; keep unresolved cases unknown.
3. Define defensible negative/control evidence separately, and evaluate with site/event-grouped and temporally held-out splits to prevent spatial and temporal leakage.
4. Improve OSM feature traceability by retaining stable IDs for role-specific nearest features and preserving source snapshot dates; quantify positional uncertainty before interpreting short distances.
5. For satellite evidence, obtain only case-targeted scenes that predate detections, preserve scene IDs and SCL/cloud metadata, and keep post-event images as contextual follow-up only. Do not scale imagery retrieval until coverage is demonstrated.
6. Report sensitivity across thresholds and alternative plausible weights as robustness analysis, not model validation.

## Reproducibility and outputs

No new data were downloaded, the pilot was not rerun, and the analysis used only the audited experiment and saved case-study register. Summary calculations are in [evaluation_summary.csv](../outputs/final_pilot/tables/evaluation_summary.csv) and the threshold re-binning details are in [candidate_category_threshold_sensitivity.csv](../outputs/final_pilot/tables/candidate_category_threshold_sensitivity.csv). Source tables and rule definitions are recorded in `run_001`; the figures are under `outputs/final_pilot/figures/`.
