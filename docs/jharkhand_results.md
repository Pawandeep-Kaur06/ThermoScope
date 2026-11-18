# Jharkhand pilot-to-state workflow: current results

## Scope and interpretation

This report records a bounded, reproducible Jharkhand-wide run using the local FIRMS archive/NRT exports and the Geofabrik Eastern Zone OSM snapshot dated 2026-10-16. The developed Dhanbad–Jharia–Bokaro pilot remains the validation case study. The state run provides statewide thermal-observation context and mapped infrastructure evidence; it is not a validated fire classifier. FIRMS detections are sensor observations. OSM proximity and recurrence are evidence indicators, and Sentinel-2 provides optical surface context only.

The region boundary was derived locally from OSM administrative relation 1960191 (Jharkhand, admin_level 4) in the existing Geofabrik extract. This is reproducible but not an authoritative legal boundary. The source PBF has ODbL terms and requires OpenStreetMap attribution. GDAL logged malformed/unclosed rings elsewhere in the PBF while scanning it; the extracted Jharkhand geometry was valid. The boundary preparation and OSM filter did not download a new extract or issue Overpass queries.

## Inputs and processing

- FIRMS archive and NRT CSVs were locally validated, clipped to the Jharkhand polygon, deduplicated, and retained with source provenance.
- OSM features were locally filtered from `data/raw/osm/geofabrik_eastern-zone_261016.osm.pbf`; relevant industrial, mining, waste, vegetation, and power feature groups were kept. Groups overlap and describe map features, not FIRMS causes.
- Matching used 14 state tiles and a local UTM projection per tile. Recurrence used a tile-independent 250 m EPSG:6933 grid and strictly earlier acquisition dates.
- Six small Sentinel-2 L2A COG chips with SCL masks were sampled from public Earth Search STAC. Cell/category selection was for coverage only; no category was interpreted as a label. Per-detection spectral values were accepted only when scene time preceded or equaled FIRMS acquisition time and the sampled SCL pixel was clear.
- Candidate ranking uses the existing transparent evidence rules. Every detection remains unlabeled/unknown.

## Quantitative findings

| Measure | Observed result |
| --- | ---: |
| Prepared FIRMS detections | 21,450 |
| FIRMS date range | 2026-01-20 through 2026-09-06 |
| Distinct acquisition dates | 198 |
| State tiles with observations | 14 |
| Duplicate source rows / repeated observation IDs | 0 / 0 |
| Invalid coordinates / outside-state retained rows | 0 / 0 |
| Invalid OSM geometries used for matching | 0 |
| OSM feature appearances across tile windows | 36,037 (features can appear in more than one buffered tile window) |
| Distinct 250 m recurrence cells | 8,466 |
| Cells with detections on multiple dates | 1,061 |
| Cells with detections on at least 3 dates | 836 |
| Maximum distinct dates in a cell | 72 |
| Median distinct dates per cell | 1 |
| Valid pre-detection, clear Sentinel-2 spectral samples | 1 detection |
| Independently verified FIRMS labels / negative examples | 0 / 0 |

### OSM feature groups

The 37,046 state OSM source features are categorized into overlapping groups: power infrastructure 31,231; vegetation context 2,178; mining/extraction 1,334; industrial facilities 1,223; industrial structures 861; industrial land use 750; and waste facilities 13. The large power count includes general network infrastructure and should not be read as industrial source confirmation.

### Distance sensitivity

| Distance threshold | Detections with relevant mapped feature | Unambiguous proximity candidates | Ambiguous proximity | No relevant feature within threshold |
| ---: | ---: | ---: | ---: | ---: |
| 100 m | 11,080 | 10,171 | 909 | 10,370 |
| 250 m | 12,535 | 11,302 | 1,233 | 8,915 |
| 500 m | 13,397 | 11,815 | 1,582 | 8,053 |
| 1,000 m | 14,326 | 12,288 | 2,038 | 7,124 |

Counts change with threshold and map-feature density. “Candidate” and “ambiguous” are proximity statuses, not source classes or labels.

### Candidate-ranking categories

| Evidence-review category | Detections | Distinct cells |
| --- | ---: | ---: |
| Persistent thermal with nearby relevant industrial context | 9,664 | 599 |
| Other thermal observation review | 8,536 | 6,603 |
| Elevated thermal without nearby relevant OSM context | 1,932 | 1,898 |
| Persistent thermal without nearby relevant OSM context | 1,185 | 164 |
| Elevated thermal with nearby relevant industrial context | 101 | 84 |
| Persistent thermal near general power infrastructure only | 32 | 8 |

These are rule-based review buckets. Recurrence means repeated observations in the same grid cell, not necessarily a single persistent physical source. OSM/GEM proximity does not establish the cause of a thermal observation.

### Satellite evidence

The selected six-cell retrieval found six pre-detection scenes by the cell-level search rule, but only 8 of 21,450 row-level detections had any eligible scene in the available feature integration. One row had a valid clear SCL-screened causal spectral sample. 170 rows had only post-detection imagery withheld; 177 encountered heavy chip cloud/shadow, and seven had cloud or pixel-screen uncertainty. The sample is deliberately small and not representative of all state dates/locations. Sentinel-2 has no thermal band and cannot confirm short-lived fire events.

## Reproducibility and validation

The immutable input checksums, software versions, output hashes, region boundary checksum, and validation results are in `outputs/jharkhand/run_002/results_manifest.json`. It records all 19 checks passing, including row/ID alignment between preparation, matching, features, and ranking; unique observation IDs; state membership; tile and CRS assignment; past-only recurrence; and exclusion of future spectra. The interactive map embeds all 21,450 FIRMS points and up to 5,000 OSM context features; Leaflet and its basemap require internet access to render. Static figures and CSV tables are alongside it in the same output directory.

The processing outputs live under `data/processed/jharkhand_analysis/run_001/`. The preparation, boundary, matching, feature, satellite, ranking, and final visualization scripts write generated local files, which are excluded from Git. Reruns must use new run/output directories; do not overwrite `run_001` or `outputs/jharkhand/run_002`.

## Scientific conclusion and next work

The data supports statewide exploratory analysis of where and when FIRMS thermal detections recur and how they relate spatially to mapped OSM contexts. It does not support detection-level industrial-fire labels, supervised model training, or accuracy claims. The immediate scientific blocker is credible independent reference data with event dates, geolocation/uncertainty, and auditable linkage to imagery/observations. The six retrieved chips and single valid spectrum are not a CV dataset. Next, define the image task and labeling protocol, then pilot a larger but still sampled imagery/label feasibility study using independently documented events and a spatially/temporally held-out review design. If suitable labels cannot be assembled, retain this work as an explainable geospatial evidence-prioritization project rather than inventing a CV result.

## Known warnings and limitations

- The Jharkhand polygon comes from an OSM admin relation, not a survey/legal boundary.
- OSM is incomplete, time-varying, and based on a 2026-10-16 extract. Buffered tile counts include repeated OSM feature appearances.
- GEM reference files available locally are Dhanbad-specific and were not applied to statewide matching.
- FIRMS archive/NRT coverage is limited to the available local exports and dates above; this is not a complete historical or future state record.
- Satellite sampling is very small, cloudy, and weakly matched to individual acquisition times.
- One initial processing attempt was retained in an incorrectly named partial directory (`data/processed/jharkland_analysis/run_001/`). It is not a source of final results; the verified complete run is the manifest-linked `jharkhand_analysis/run_001/`. No historical/user files were removed.
- There are no verified labels, negative samples, trained model weights, or model performance metrics.
