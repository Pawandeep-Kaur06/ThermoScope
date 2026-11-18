# India-wide ThermoScope CV implementation roadmap

**Purpose:** assess how the existing Dhanbad–Jharia–Bokaro pilot could support an India-wide computer-vision (CV) study, and define prerequisites before expanding data acquisition or training.

## Evidence and scope

This roadmap is based on files and data in the complete checkout at `C:\Users\PAWAN\Desktop\CV\ThermoScope`, especially the source tree, `config/`, test suite, local data inventory, completed `run_001`, and existing reports. The current `AGENTS.md`, README and final-pilot configuration describe a pilot candidate-prioritization project. The user's updated intent is India-wide CV; this roadmap records the gap, but does not retroactively change the scope or interpretation of the completed pilot. A later scope/configuration change should be versioned separately.

Labels used below distinguish **Verified in repository** facts from **Recommendation** and **Unknown** items. No model was trained, and no large data were downloaded or experiment rerun for this audit.

## 1. Existing reusable components

| Component | Verified status | Reuse and limitation for India-wide CV |
|---|---|---|
| FIRMS | `src/prepare_firms_pilot.py` streams archive and NRT CSVs in chunks, validates fields/coordinates, applies configured region membership, removes duplicate observation records, retains provenance and stable observation IDs, and writes quality/cache metadata. The region registry includes an India domain. Local raw inputs are `data/raw/archive.csv` (327 MB) and `data/raw/nrt.csv` (609 MB); the pinned experiment records 4,073,699 and 7,247,714 input rows, respectively. | Good starting point for an India polygon-filtered table. These are local source exports, not proof of a complete, current, all-sensor national FIRMS archive. Verify product/sensor/time coverage and retrieval provenance before treating them as the national reference. Prepared data currently contain 9,220 pilot records from 184 dates (2026-01-20–2026-09-05). |
| India boundary / regions | `config/regions.json`, `src/regions.py`, and `src/prepare_country_boundary.py` define India using a Natural Earth 10m India POV polygon plus a rectangular grid envelope. Boundary membership includes polygon-edge points. | Reusable boundary and region registry; Natural Earth is generalized and uses a stated POV for disputed borders. Verify island/coastal membership and exact scope before analysis. |
| Tile framework | India is divided into stable 3° × 3° lat/lon tiles; shared internal edges have one owner. `regions.py` selects a local UTM CRS from each tile center. Matching is tile-aware; recurrence uses a single EPSG:6933 grid across tiles and strictly earlier acquisition dates. | Architecture is relevant for nationwide processing. Tests cover assignment, boundaries, CRS, uniqueness, recurrence across tile boundaries and resume behavior. A controlled trial exists for two adjacent tiles, using pilot observations; it is not national coverage or validation across India's full CRS/geographic range. |
| OSM | `src/fetch_osm_pilot.py` retrieves a pinned Geofabrik Eastern Zone PBF and filters it locally to the pilot. Local pilot GeoPackage: 8,333 features (7,574 points, 225 lines, 534 multipolygons). `src/match_firms_osm_pilot.py` supports tile-window matching, geometry-aware distances, category roles, local CRS, stable IDs and matching checkpoints. | The matcher can be reused with appropriately prepared OSM tile/national inputs. Acquisition is still pilot/eastern-zone specific; the local GeoPackage covers the pilot rather than the India tile envelope. National OSM coverage is absent. OSM remains incomplete, time-varying context, not cause labels. |
| Sentinel-2 | `src/investigate_satellite_pilot.py` queries public STAC metadata and retrieves small COG windows with SCL masks. The saved fixed pilot run references eight 64×64 chips: B04/B03/B02 at 10 m, B11 native 20 m resampled onto a 10 m grid, plus eight SCL rasters. `src/engineer_features.py` enforces per-detection temporal eligibility and cloud/shadow masking. | Reusable targeted retrieval and QA pattern, not a national image dataset. Sentinel-2 is optical context, not thermal confirmation. The present cell selector and output protocol are pilot-focused and do not create a representative labeled dataset. |
| Feature engineering | `src/engineer_features.py` combines FIRMS thermal attributes, past-only cell recurrence, OSM roles/distances, supplementary GEM proximity, and eligible S2 spectral samples. It checks stable IDs, tile assignment/CRS and temporal leakage. | Can feed a future multimodal baseline. Most outputs remain engineered observation/context data, not image training examples. National input discovery, image manifests and scale/performance have not been demonstrated. |
| Ranking and evidence review | `src/rank_firms_candidates.py`, `src/assess_label_evidence.py` and `src/review_evidence.py` create rule-based review priorities, source inventories, event records and an auditable human-review queue. Proximity and recurrence are explicitly not labels. | Good candidate triage and evidence-management components; they are not classifiers. The existing score/category thresholds are hand-set and must not become target labels. |
| Pilot experiment / reporting | `data/processed/final_pilot_experiment/run_001/` contains aligned 9,220-row preparation, match, feature, rank, review and validation stages with manifests. Reports and the 12-case register are under `docs/` and `outputs/final_pilot/`. | Valuable benchmark/regression case for preserving the old pilot workflow. It is not nationwide or an image classification experiment. The completed experiment and its pinned config/output are historical and should remain immutable. |
| Tests / configuration | `config/regions.json`, `config/final_pilot_experiment.json`, `requirements-satellite.txt`, and 13 test modules cover region/tile logic, caching, matching interfaces, satellite eligibility, ranking, evidence review and reporting. Prior worklog records 60 passing `unittest` cases after the final evaluation work. | Extend tests with national-scale data contracts and model-dataset checks. Existing tests are mostly unit/synthetic or pilot-slice; they do not establish all-India data coverage or model validity. No tests were rerun in this roadmap task. |

## 2. Actual imagery and image-label gap

### TIFF inventory (verified)

- The local `data/processed/satellite_investigation/` tree contains **37 TIFF files across seven timestamped runs**, with **22 distinct file-content hashes**; several chip rasters are repeated across runs.
- The fixed Sentinel-2 reference run used by `run_001` contains 16 rasters: eight four-band chips and eight SCL masks. Raster headers show four-band chips are 64×64 `uint16`, EPSG:32645 at 10 m; the fourth band is B11 resampled from its native 20 m grid. SCL masks are 64×64 `uint8` with class masks resampled onto that grid.
- The TIFFs are **investigation chips**, selected from a small number of recurring pilot cells and dates. They do not contain image-level class annotations, instance masks, source-cause labels, train/validation/test assignments or national sampling coverage. Multiple copies across run folders do not increase independent training sample count.
- The current engineered pilot features found 11 detections with a temporally eligible scene but only **two** with usable, clear pre-detection spectral samples among 9,220 FIRMS records. The 12 later case studies have no eligible pre-detection chips. This is inadequate for supervised CV.

### Reference evidence and labels (verified)

The pilot's latest evidence validation records six event reviews and eight source records; five records have date-only overlap with 240 FIRMS rows, but **zero genuinely linkable FIRMS detections**, zero verified detection labels, zero weak detection labels attached to rows and zero negative examples. Existing cases remain pending review. Date coincidence, OSM/GEM facility location, a candidate score, or a cloudy/missing image cannot be promoted to a truth label.

Some independent event leads exist, including an official event-level report that lacks location precision and lies outside the FIRMS window, and secondary-source leads with insufficient location/time precision. These are useful for human evidence review, but do not currently make a training/evaluation set. OSM/GEM are asset/context data, not incident labels. BCCL/NRSC historical mine-fire maps, if later obtainable and date/version appropriate, could provide area context but would not automatically verify individual 2026 detections.

### Satellite sources and task fit

- **Sentinel-2 L2A:** locally available for a handful of pilot cells and realistically useful for surface/land-use context when cloud-free and acquired at a relevant time. Its optical bands do not measure thermal radiance; a scene on a different date cannot establish whether a brief FIRMS event occurred.
- **FIRMS sensor observations (e.g. VIIRS/MODIS products present in source exports):** useful for locating and describing thermal detections. They are already algorithmic detections and do not by themselves provide independent image labels for cause classification. Confirm the local exports' sensor/product mix from data before defining the model input.
- **Other optical, radar or thermal imagery:** potential future evidence streams, but this checkout has no other image corpus. Select by target, pixel size, revisit/time alignment, cloud/fire sensitivity, licensing and obtainable ground truth; estimate storage and retrieval before acquiring.

**Unknown:** usable India-wide coverage, scene volumes, historical revisit/quality by FIRMS observation, and API/storage costs for a selected national chip design. These require a small metadata-only coverage study and representative sample before download.

## 3. Feasible classification targets and model choice

### What the present evidence supports

Current evidence supports **descriptive analysis and human-review prioritization only**. It does not support supervised classification, weak supervision with meaningful evaluation, or a claim of India-wide system performance. There is no labeled image sample or held-out truth set.

### Potential targets after data readiness

1. **Surface/site-context classification** (for example mining/industrial footprint, vegetation/agriculture, built-up, water/other) is a more feasible initial image task than fire-cause classification. It still needs independently curated image/land-cover labels and an evaluation set that is not derived solely from the same OSM layers used as model context.
2. **Documented thermal-event/source category** (e.g. independently documented industrial fire, wildland/biomass fire, persistent mine-fire/combustion source, other documented thermal source, unknown) is closer to the project title. It requires dated, georeferenced, independently verified event evidence overlapping a plausible sensor observation footprint/time. Current counts are zero linked examples.
3. **Candidate priority** can remain an explainable ranking task while labels are collected. It is not a source-class target and its ranking rules cannot serve as validation truth.

### Model-development recommendation

- Do **not** train a supervised or weakly supervised source classifier on the current chips. OSM buffers, GEM assets, recurrence or FIRMS detection itself would create circular or noisy labels for industrial cause.
- If a CV deliverable is needed before incident labels can be obtained, narrow and rename the target to a **visual surface/site-context characterization** problem, using independent context annotations/products and a manually audited test subset. State clearly that it does not classify the FIRMS source or confirm a fire.
- For a future labeled source task, compare a transparent tabular baseline using FIRMS/context features with a modest pretrained remote-sensing image encoder or multimodal image-plus-tabular model. Keep the rule-based candidate ranker as a triage baseline only. Use weak labels only as training hints with explicit noise/coverage modeling and an independently verified test set; otherwise prefer human review or self-supervised representation exploration without semantic performance claims.

## 4. India-wide requirements and processing architecture

### Additional data acquisition

1. **FIRMS:** verify exact source product, sensor mix, coverage dates, retrieval/query bounds and archive/NRT overlap; define a fixed national time window and update cadence. Use the existing chunked preparation and India polygon filter; save immutable raw-source manifests and prepared national output partitions.
2. **OSM:** obtain appropriately licensed national or regional extracts. Start with staged state/region extracts that overlap selected FIRMS tiles; avoid a full-country download until format, feature volume, disk budget and required tag taxonomy are tested. Preserve geometry, OSM IDs, tags, snapshot date and attribution. Pilot GeoPackage cannot stand in for missing tile coverage.
3. **Imagery:** inventory scene metadata first for a stratified, multi-region sample, with acquisition time, sensor, resolution, cloud/shadow, footprint overlap and asset access. Retrieve only chips needed for a reviewed sample; store chip bounds/CRS, band definitions, resampling, QA masks, source scene IDs, time offsets, checksums and license/provenance. Separate optical context from thermal evidence.
4. **Reference evidence:** build a national event/site register from official regulator/operator, disaster-management, mine-fire, fire-service and credible incident records. Store event time/location uncertainty and source quality; use a human two-reviewer process for difficult links. Build potential controls through reviewed evidence and sampling, not absence of reports.

### Proposed architecture

- Keep `dhanbad_jharia_bokaro` as an immutable regression/validation region. Create a separately versioned India-wide experiment config rather than altering `run_001` parameters.
- Treat the country polygon as the processing domain and stable regular tiles as execution partitions. Assign every FIRMS observation to one tile/region; retain global stable IDs. Match each tile to an OSM subset plus distance buffer in its configured local CRS; persist tile checkpoints and input hashes.
- Store national tabular stages partitioned by region/tile and time (for example Parquet if adopted after dependency review), with deduplicated observation identity at combine time. Calculate recurrence with one documented national grid and strictly past-only dates; prevent tile boundaries from changing recurrence IDs.
- Maintain an **image catalog** separate from tabular features. One manifest row per scene/chip includes stable chip ID, source observation/event IDs, platform/product, acquisition timestamp/time offset, bands, CRS/transform, pixel size, cloud QA, data checksum, label tier/reviewer, and spatial/site group for splits. Do not make duplicate TIFF copies to link one chip to many observations.
- Maintain label evidence in separate tables from predictions/features. Preserve verified, weak, rejected and unresolved evidence tiers; unknown is not negative.
- Use resumable stages with content-addressed caches, audit logs and stage-specific manifests. Measure peak storage and run time on representative tiles before national execution. Avoid logging credentials; keep generated rasters and derived labels out of Git.

## 5. Validation and evaluation requirements

### Data and geospatial QA

- Verify raw input checksums, product/sensor/date coverage, invalid/missing values, duplicate policy and country-polygon membership. Reconcile prepared row counts to source partitions.
- Test each boundary and tile edge, unique assignment, per-tile CRS, buffered OSM overlap, duplicate prevention on resume/combine, and recurrence across tile edges. Validate coverage and tag/geometry availability per region, not just total counts.
- Audit image-to-observation spatial intersection and event-to-image time offsets; quantify clear-pixel coverage and missingness by region, season and candidate context. Missing clouds/imagery stay unknown.
- Audit label evidence independently of all model inputs; sample adjudications, measure reviewer agreement, preserve unresolved and weak cases, and check that no OSM-derived weak label is used as an independent test truth.

### Model evaluation, only after labeled data exist

- Freeze target ontology, label inclusion, chip construction and split plan first. Group repeated observations/chips from the same source event and facility/site; add a spatial buffer so neighboring chips cannot leak; hold out later time blocks and preferably entire regions for geographic transfer evaluation.
- Compare simple rules/tabular baselines and image/multimodal models. Report class counts by split, per-class precision/recall/F1, confusion matrix, PR-AUC where appropriate, calibration/uncertainty, confidence intervals and an explicit abstain/unknown rate. Report event-level and observation-level results separately and inspect false positives/negatives with reviewers.
- Do not use random row splits, report accuracy from unlabeled categories, or claim India-wide generalization from a pilot tile. Keep threshold/weight/model selection off the final test groups.

## 6. Prioritized implementation phases

Complexity is relative (M = medium, H = high) and excludes the time needed for external agencies or operators to respond to data requests.

| Phase | Work and gate | Complexity | Dependency / exit criterion |
|---|---|---:|---|
| **P0 — scope and provenance contract** | Version a new India-wide research protocol: define whether first CV target is site context or documented event/source class; reconcile README/task scope in a separate change; freeze period, sensors, spatial support, label tiers and claims. Inventory local FIRMS products and all 37 TIFFs by unique scene/hash. | M | No pipeline expansion until target and coverage are explicit. Keep final pilot config/output immutable. |
| **P1 — national geospatial data foundation** | Audit FIRMS source coverage and prepare a polygon-filtered India table; validate stable IDs and source deduplication. Design tile partitions and manifests. Acquire small OSM extracts for a stratified set of non-adjacent contexts (mining, power, manufacturing, urban/open burning/vegetated controls) and quantify storage/feature coverage. | M–H | Existing region framework; representative extract access and OSM license/provenance. Exit when one reproducible multi-region run resumes and produces unique, validated observations. |
| **P2 — image coverage and dataset registry** | Metadata-only image availability scan over selected events/cells; compare temporal offsets, cloud, resolution and missingness. Decide imagery by target; retrieve a small balanced, case-reviewed sample and versioned chip manifest only after volume approval. | H | Requires target, selected regions and scene metadata. Exit when imagery is genuinely useful for a defined class, not merely available. |
| **P3 — independent labels and benchmark** | Source event records and/or annotators; establish label handbook, time/location linkage, dual review, disagreement and negative/control protocol. Create site/event-separated train/validation/test groups, with regional and temporal holdouts. | H (research-intensive) | Strongest dependency and likely critical path. Exit only with enough independent examples per class and a credible held-out test set; set minimum counts after a pilot label yield study rather than inventing a target number now. |
| **P4 — model baselines and error analysis** | Implement no-model and tabular baselines, then transfer-learning image or multimodal model if data support it. Compare to candidate-ranking triage without treating its labels as truth. Calibrate uncertainty/abstention and conduct expert error review. | M–H | P2/P3 readiness gates. No accuracy claim before locked test evaluation. |
| **P5 — India-wide inference and reporting** | Scale tile execution, OSM context, chips/inference only after resource measurement; publish coverage/uncertainty maps, per-region evaluation, provenance, limitations and storage costs. | H | Passed P1–P4; adequate compute/storage and regional test evidence. Nationwide map is not itself model validation. |

**Recommended first implementation task:** create a read-only **national data readiness inventory** for the existing raw FIRMS exports and satellite chips: verify FIRMS sensor/product/date/geographic coverage and archive/NRT overlap; group the 37 TIFFs by unique content and STAC scene; reconcile those scenes against the eight pinned cells and feature eligibility; report what is missing without downloading or rewriting. In parallel, freeze the first target choice. This determines whether to build a site-context benchmark or invest in difficult event-level source labels.

## 7. Risks, dependencies and unresolved questions

| Risk / unknown | Why it matters | Mitigation / decision needed |
|---|---|---|
| Sparse, purposively selected image sample | Eight pinned chip pairs cannot represent India's regions/seasons/classes and carry no labels. | Coverage survey and stratified sample design before retrieval; account for repeated hashes. |
| No independent row-level truth | Cannot train/validate event-cause classes; rule/OSM proximity would be circular. | Secure precise event records and human adjudication; preserve unknowns and genuine controls. |
| Sensor/date/spatial mismatch | FIRMS active detections and later/coarse optical context describe different measurement supports. | Define time tolerance and pixel footprint per sensor; use matched thermal evidence for event claims and optical scenes for context only. |
| OSM extraction coverage and vintage | Pilot layer cannot support national matching; OSM coverage varies. | Staged regional extracts, tags/geometry QA, snapshots and contextual coverage reporting. |
| Scope documentation still says pilot | README and AGENTS retain the old pilot objective and final protocol is Dhanbad-specific. | Approve and version a new project-level scope/config; retain original pilot documentation as historical record. |
| National storage/runtime unknown | Full-resolution imagery and broad OSM have much larger costs than 64×64 chips. | Metadata-first queries, representative dry run, output-size estimates, checkpoint/cache policy and disk monitoring. No large download in P0/P1. |
| Boundary and CRS approximation | Natural Earth is generalized; tile UTM strategy and global grid need country-wide edge/corner checks. | Preserve polygon version, quantify boundary sensitivity, test representative extreme tiles and antimeridian/UTM-zone edges. |
| Weak/event labels are biased | Official and news records overrepresent reported incidents/sectors and may be coarsely located. | Track source ascertainment, temporal/spatial precision and label confidence; evaluate a clearly defined sampling frame. |
| Repeated observations leak across splits | FIRMS repeatedly observes the same site; random row splits inflate metrics. | Group by event/site and spatial buffer; hold out region and later dates; audit chip duplicates by hashes. |

## Readiness conclusion

The repository contains a useful, tested **India domain/tile foundation** and a complete **Dhanbad pilot analysis**, but not an India-wide CV dataset or trained/validated classifier. The national FIRMS preparation interface is reusable; national OSM coverage and representative, time-appropriate labeled imagery are not present. The existing 37 TIFFs are small investigation products (22 content hashes), not training data. There are zero verified detection-level links and zero negative examples in the audited pilot.

An India-wide *candidate analysis* can be advanced by extending data coverage, but a defensible image classifier requires the P2/P3 gates first. The lowest-risk next action is the read-only national data readiness inventory, followed by a target/label protocol decision—not model training or a national download.
