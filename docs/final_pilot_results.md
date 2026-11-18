# Final pilot results — ThermoScope

## Scope and interpretation

This analysis uses the already completed Dhanbad–Jharia–Bokaro pilot run. FIRMS points are satellite thermal-anomaly observations. OSM proximity, recurrence, GEM context, and Sentinel-2 samples are evidence indicators for investigation; none establishes a detection's cause. The rule-based categories are review priorities, not verified fire classes. No supervised classifier or predictive metric is reported.

## Data analysed

The run contains **9,220 FIRMS observations** over **184 acquisition dates**, from **2026-01-20** through **2026-09-05**. The detection coordinates lie within the configured pilot bounds (23.25–24.0°N, 85.75–86.75°E). Prepared FIRMS, matching, engineered-feature, and ranking files each contain 9,220 rows; the first three share a complete unique observation-ID set. Ranking aligns one-to-one by source row.

FRP median is **2.15 MW** (mean 2.73, 95th percentile 6.80, maximum 19.15). Confidence codes: nominal `n` 8,471, low `l` 743, high `h` 6. These are FIRMS attributes, not certainty of industrial cause.

## Spatial and temporal patterns

Using the experiment's fixed 250 m EPSG:32645 grid, 1,063 cells contain detections. 522 cells (49.1%) have observations on multiple distinct dates; the median cell spans 1 date(s), and the maximum is 70 dates. Recurrence is computed using dates strictly before each observation in the feature/ranking evidence. A grid cell is a spatial bin, not an assertion of one physical source; multiple sources may occupy a cell and a source can move across cells.

The daily plot shows observations by FIRMS acquisition date and a 7-day rolling mean. It describes sampling volume and temporal clustering, not incident duration or continuous burning.

## Industrial and power context

At the relevant-context thresholds, unambiguous candidate / ambiguous / no relevant mapped feature counts are: 100 m 6,963/249/2,008; 250 m 7,679/334/1,207; 500 m 8,031/472/717; 1 km 8,276/650/294.

The matching output keeps transmission towers, lines, and other power infrastructure distinct from industrial land, mining/extraction areas, industrial facilities, and generation sites. Figure 4 reports non-exclusive role-specific distance counts derived from the matched distances; one detection can be near multiple categories. OSM is a static mapped snapshot with incomplete and temporally unversioned coverage, so absence of mapped context is not evidence of absence of an industrial source. GEM records are supplementary static facility context only.

## Candidate prioritization

The ranking partitions all 9,220 detections into six rule-based review categories (see the candidate table and Figure 6). The largest category contains 6,550 records. A high review priority is a transparent combination of thermal attributes, past-only recurrence, mapped context, and limited satellite evidence; it is not a calibrated probability or classification. Every label field remains `unknown_unlinked`; there are no verified detection-level incident labels, no fabricated negatives, and no supervised evaluation metrics.

## Satellite evidence and limitations

Sentinel-2 statuses in the engineered feature table: 8,690 rows without chip metadata; 519 with post-detection imagery withheld from historical features; 9 cloud/shadow-contaminated or unverifiable; and 2 with sampled, temporally eligible spectra. Thus only 2 detections (0.022%) have usable pre-detection spectral features. The chips are optical context; they do not independently confirm a thermal event. Missing imagery is not evidence of absence.

## Data quality, uncertainty, and reproducibility

The run's saved feature quality report marks overall checks `passed`. This reporting script additionally checked row alignment, ID uniqueness, bbox membership, metric CRS declaration, and OSM geometry validity. Static OSM/GEM snapshots do not establish as-of-date facility status; FIRMS observations are sensor detections rather than adjudicated fire events; recurrence reflects repeat observation rather than source identity. No new data were downloaded and the experiment was not rerun.

## Generated outputs

### Figures

- [Figure 1: Study-area FIRMS detections](../outputs/final_pilot/figures/01_study_area_firms_detections.png)
- [Figure 2: Observations over time](../outputs/final_pilot/figures/02_firms_observations_over_time.png)
- [Figure 3: FRP and confidence distributions](../outputs/final_pilot/figures/03_frp_and_confidence_distributions.png)
- [Figure 4: Industrial proximity by OSM category](../outputs/final_pilot/figures/04_industrial_proximity_by_osm_category.png)
- [Figure 5: Recurrence by 250 m cell](../outputs/final_pilot/figures/05_thermal_recurrence_by_250m_cell.png)
- [Figure 6: Candidate review categories](../outputs/final_pilot/figures/06_candidate_ranking_categories.png)
- [Figure 7: Feature availability and Sentinel-2 coverage](../outputs/final_pilot/figures/07_feature_availability_and_sentinel2.png)
- [Figure 8: FIRMS and OSM context map](../outputs/final_pilot/figures/08_firms_and_osm_context_map.png)

### Tables

- [Candidate ranking summary](../outputs/final_pilot/tables/candidate_ranking_summary.csv)
- [Data quality and validation summary](../outputs/final_pilot/tables/data_quality_validation_summary.csv)
- [Feature availability summary](../outputs/final_pilot/tables/feature_availability_summary.csv)
- [FIRMS observation summary](../outputs/final_pilot/tables/firms_observation_summary.csv)
- [Industrial proximity threshold comparison](../outputs/final_pilot/tables/industrial_proximity_threshold_comparison.csv)
- [OSM feature category summary](../outputs/final_pilot/tables/osm_feature_category_summary.csv)
- [OSM proximity by feature category](../outputs/final_pilot/tables/osm_proximity_by_feature_category.csv)
- [Recurrence distribution summary](../outputs/final_pilot/tables/recurrence_distribution_summary.csv)
- [Recurrence status summary](../outputs/final_pilot/tables/recurrence_summary.csv)
- [Satellite evidence coverage summary](../outputs/final_pilot/tables/satellite_evidence_coverage_summary.csv)

Input checksums, analysis parameters, software versions, and output hashes are recorded in the [results manifest](../outputs/final_pilot/results_manifest.json).
