# Representative case studies — ThermoScope final pilot

## Purpose and safeguards

These purposively selected examples illustrate different evidence combinations in the Dhanbad–Jharia–Bokaro pilot. They are not a validation set and do not establish industrial fires, causal sources, or classifier performance. No new incident records, labels, or satellite imagery were added. The reviewer field remains pending for every case.

## Selection

Twelve observations were selected: two from each of the six rule-based candidate-ranking categories. The base selections are at the within-category 25th and 75th percentiles of review rank, rather than only the highest-ranked cases. Where a category has existing chip coverage and the 25th-percentile selection has no chip, the second selection is the chip-available observation nearest the 75th-percentile rank. This deterministic, category-balanced selection is not a probability sample; the register records the exact stratum position for each observation.

| Ranking category | Selected observations |
|---|---:|
| `elevated_thermal_with_nearby_relevant_industrial_context` | 2 |
| `elevated_thermal_without_nearby_relevant_osm_context` | 2 |
| `other_thermal_observation_review` | 2 |
| `persistent_thermal_near_general_power_infrastructure_only` | 2 |
| `persistent_thermal_with_nearby_relevant_industrial_context` | 2 |
| `persistent_thermal_without_nearby_relevant_osm_context` | 2 |

## Comparative findings

The case set contains 12 observations. FRP ranges from 0.88 to 9.00 MW; confidence values are n=12. Strictly prior recurrence in selected 250 m cells ranges from 0 to 29 distinct earlier acquisition dates. These differences reflect the constructed selection strata and should not be interpreted as category prevalence.

11 of the selected rows have at least one mapped industrial or power feature within 1 km. 0 selected observations have usable pre-detection Sentinel-2 spectra. Existing chip source: `data\processed\satellite_investigation\run_20261018T212303Z`.


Four selected observations have existing local Sentinel-2 chips; all four scenes post-date their FIRMS observations and therefore none is eligible as historical evidence. Scene cloud estimates range from 14.2% to 87.1%; 2 chips have a clear pixel-level SCL flag, but their later acquisition dates still exclude them, while 2 have at least 50% cloud/shadow within the chip. No new imagery was retrieved.

## Case register and maps

The [case-study register](../outputs/final_pilot/case_studies/run_20261116T_case_review_final/case_study_register.csv) records stable IDs, FIRMS attributes, nearest OSM role/distance, supplementary GEM context, strictly prior recurrence, scene/cloud metadata, investigation rationale, uncertainties, and pending reviewer assessment. The [comparative table](../outputs/final_pilot/case_studies/run_20261116T_case_review_final/comparative_case_study_table.csv) provides a compact comparison; [nearby OSM features](../outputs/final_pilot/case_studies/run_20261116T_case_review_final/case_osm_nearby_features.csv) contains recomputed geometry-to-point distances for mapped industrial/power features within 1 km. The [location overview](../outputs/final_pilot/case_studies/run_20261116T_case_review_final/case_locations_overview.png) and per-case panels are generated from the existing OSM snapshot, FIRMS rows, and only local Sentinel-2 chips already referenced by the run.

- [case_01_elevated_thermal_with_nearby_relevant_industrial_context_25thpct](../outputs/final_pilot/case_studies/run_20261116T_case_review_final/individual/case_01_elevated_thermal_with_nearby_relevant_industrial_context_25thpct.md) — `elevated_thermal_with_nearby_relevant_industrial_context`; FIRMS 2026-01-27; FRP 6.06 MW; 2 prior dates.
- [case_02_elevated_thermal_with_nearby_relevant_industrial_context_75thpct](../outputs/final_pilot/case_studies/run_20261116T_case_review_final/individual/case_02_elevated_thermal_with_nearby_relevant_industrial_context_75thpct.md) — `elevated_thermal_with_nearby_relevant_industrial_context`; FIRMS 2026-01-20; FRP 6.70 MW; 0 prior dates.
- [case_03_elevated_thermal_without_nearby_relevant_osm_context_25thpct](../outputs/final_pilot/case_studies/run_20261116T_case_review_final/individual/case_03_elevated_thermal_without_nearby_relevant_osm_context_25thpct.md) — `elevated_thermal_without_nearby_relevant_osm_context`; FIRMS 2026-03-14; FRP 9.00 MW; 0 prior dates.
- [case_04_elevated_thermal_without_nearby_relevant_osm_context_75thpct](../outputs/final_pilot/case_studies/run_20261116T_case_review_final/individual/case_04_elevated_thermal_without_nearby_relevant_osm_context_75thpct.md) — `elevated_thermal_without_nearby_relevant_osm_context`; FIRMS 2026-03-04; FRP 5.72 MW; 0 prior dates.
- [case_05_other_thermal_observation_review_25thpct](../outputs/final_pilot/case_studies/run_20261116T_case_review_final/individual/case_05_other_thermal_observation_review_25thpct.md) — `other_thermal_observation_review`; FIRMS 2026-01-22; FRP 1.89 MW; 1 prior dates.
- [case_06_other_thermal_observation_review_75thpct](../outputs/final_pilot/case_studies/run_20261116T_case_review_final/individual/case_06_other_thermal_observation_review_75thpct.md) — `other_thermal_observation_review`; FIRMS 2026-02-25; FRP 0.88 MW; 2 prior dates.
- [case_07_persistent_thermal_near_general_power_infrastructure_only_25thpct](../outputs/final_pilot/case_studies/run_20261116T_case_review_final/individual/case_07_persistent_thermal_near_general_power_infrastructure_only_25thpct.md) — `persistent_thermal_near_general_power_infrastructure_only`; FIRMS 2026-03-05; FRP 1.04 MW; 9 prior dates.
- [case_08_persistent_thermal_near_general_power_infrastructure_only_75thpct](../outputs/final_pilot/case_studies/run_20261116T_case_review_final/individual/case_08_persistent_thermal_near_general_power_infrastructure_only_75thpct.md) — `persistent_thermal_near_general_power_infrastructure_only`; FIRMS 2026-03-19; FRP 1.08 MW; 4 prior dates.
- [case_09_persistent_thermal_with_nearby_relevant_industrial_context_25thpct](../outputs/final_pilot/case_studies/run_20261116T_case_review_final/individual/case_09_persistent_thermal_with_nearby_relevant_industrial_context_25thpct.md) — `persistent_thermal_with_nearby_relevant_industrial_context`; FIRMS 2026-05-24; FRP 3.00 MW; 27 prior dates.
- [case_10_persistent_thermal_with_nearby_relevant_industrial_context_75thpct](../outputs/final_pilot/case_studies/run_20261116T_case_review_final/individual/case_10_persistent_thermal_with_nearby_relevant_industrial_context_75thpct.md) — `persistent_thermal_with_nearby_relevant_industrial_context`; FIRMS 2026-02-06; FRP 1.73 MW; 9 prior dates.
- [case_11_persistent_thermal_without_nearby_relevant_osm_context_25thpct](../outputs/final_pilot/case_studies/run_20261116T_case_review_final/individual/case_11_persistent_thermal_without_nearby_relevant_osm_context_25thpct.md) — `persistent_thermal_without_nearby_relevant_osm_context`; FIRMS 2026-08-23; FRP 1.37 MW; 29 prior dates.
- [case_12_persistent_thermal_without_nearby_relevant_osm_context_75thpct](../outputs/final_pilot/case_studies/run_20261116T_case_review_final/individual/case_12_persistent_thermal_without_nearby_relevant_osm_context_75thpct.md) — `persistent_thermal_without_nearby_relevant_osm_context`; FIRMS 2026-05-08; FRP 0.95 MW; 15 prior dates.

## Evidence limits

- FIRMS coordinates are thermal-anomaly detections; confidence and FRP are sensor attributes, not industrial-cause verification.
- OSM is a static snapshot; its completeness, feature vintage, and the real-world source footprint may differ. Distances were recomputed from feature geometries in EPSG:32645; no proximity is a causal link.
- Recurrence counts strictly earlier acquisition dates within a fixed 250 m grid cell. The cell can contain multiple physical sources; repeated sensor observations are not a source identity.
- GEM assets are supplementary, static facility references and may be temporally mismatched.
- Sentinel-2 is optical context. A post-event image is not eligible historical evidence; cloudy/shadowed, missing, or temporally unsuitable imagery is not evidence of no fire. Chips are small and cannot independently confirm a thermal event.
- No verified detection-level labels exist in this pilot. Human reviewer decisions have not been collected in this case-study register. No labels or model metrics are asserted.

## Reproducibility

Selection settings, input filenames/checksums, software versions, selected IDs, output inventory, and quality checks are recorded in [case_study_manifest.json](../outputs/final_pilot/case_studies/run_20261116T_case_review_final/case_study_manifest.json). The source experiment and historical case-study runs were left unchanged.
