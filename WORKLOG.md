# ThermoScope work log

## 2026-11-16 — WorldCover reference-label feasibility plan

### Task performed
- Read `docs/cv_dataset_report.md`, `docs/india_wide_cv_implementation_roadmap.md`, `TASKS.md`, `WORKLOG.md`, the local CV manifest, Jharkhand/pilot satellite metadata and feature outputs, and existing image/SCL files.
- Reviewed the ESA WorldCover 2021 product manual and Ministry of Coal public Coal Map documentation for class semantics, temporal provenance, raster tiling/access, licensing, and potential independent mining-context references.
- Issued HTTP HEAD requests only for the six WorldCover COG tiles intersecting the configured Jharkhand boundary. No imagery/reference raster payloads were downloaded.
- Added `docs/landcover_dataset_plan.md` describing class mapping, alignment, pixel-mask rules, sampling, geographic/temporal splitting, storage, and prerequisites. Updated `TASKS.md`.

### Findings and decision
- The existing manifest contains 20 unique four-band 64×64 chips across 11 scene IDs, 14 locations, and six Jharkhand tiles. Fourteen chips have SCL; eight contain any clear valid SCL pixels, three are at least 50% clear, and two are at least 95% clear. The chips date 2026-04-24–2026-09-08 and are targeted, nonrepresentative FIRMS-context samples.
- WorldCover v200 is technically alignable to the chip grids with nearest-neighbor categorical reprojection. It represents 2021 and was generated using Sentinel-1/2, so 2021-to-2026 class changes and source dependence prevent it from serving as independent contemporary ground truth. It maps extraction sites to bare/sparse and mixes residential/industrial in built-up; it does not label industrial facilities or mines.
- Six full 3×3° WorldCover COGs returned HTTP 200 HEAD responses; their lengths sum to 701,510,870 bytes (about 669 MiB). The global Map layer is documented at about 117 GB. Public AWS S3 tile access requires no credentials; the Terrascope download path requires registration. No raster files were downloaded.
- Recommended target is broad land-cover semantic segmentation only, with pixel-level masks and unknown/ignore pixels retained. The smallest proposed benchmark is 1,250 geographically grouped chips over five broad classes, with an independent contemporary test subset; this is a target, not a claim that current data are sufficient.
- Current labels per class: zero. No training or dataset split is justified until contemporary independent review labels and spatially independent test groups exist.

### Validation and preservation
- Verified WorldCover tile-grid footprints against the configured Jharkhand polygon; all six relevant tiles intersect it.
- Recomputed chip sizes and class-mask/SCL counts from `manifest.csv`; calculations are documented in the plan. All existing data, notebooks, and outputs were preserved. No model was trained, no files were staged/committed, and no WorldCover imagery was downloaded.


## 2026-11-16 — Workspace inspection and workflow setup

### Task performed
- Inspected the ThermoScope repository state before setting up the handoff workflow.
- Added permanent project safeguards in `AGENTS.md`.
- Inspected the existing final pilot run manifest and recorded the discrepancy between the experiment configuration status and the completed run manifest.

### Files changed
- `AGENTS.md` — created with project-scope, preservation, Git-safety, data-safety, scientific-integrity, and communication rules.
- `TASKS.md` — created with the frozen scope, verified current state, and ordered remaining work.
- `WORKLOG.md` — created to record this setup and future task results.

### Tests executed and results
- No tests were run during this workflow-setup turn; the changes are documentation only.
- `docs/final_pilot_experiment_preflight.md` reports 51 tests passed on 2026-11-16. They were not rerun here.

### Outputs generated
- No pipeline outputs were generated during this turn.
- Existing `data/processed/final_pilot_experiment/run_001/` was inspected read-only. Its manifest reports `run_status: completed`, 9,220 observations, and 232.297 seconds elapsed.

### Problems or warnings
- The repository already contains extensive uncommitted and untracked work, including modified notebooks and scripts. Those files were left untouched.
- Raw data, processed data, and notebook cache files are locally present and ignored by Git.
- `config/final_pilot_experiment.json` still says `configured_preflight_only_full_run_waits_for_plan_review`, while the `run_001` reproducibility manifest says `completed`. This metadata inconsistency is not resolved in this documentation-only step.
- No `.github/workflows` CI configuration was found.

### Next recommended task
Audit the completed `run_001` artifacts and reconcile the configuration/preflight status without rerunning expensive processing or overwriting historical outputs.

## 2026-11-16 — Read-only audit of final pilot run

### Task performed
- Audited `data/processed/final_pilot_experiment/run_001/` without rerunning processing or changing the run artifacts.

### Files changed
- `TASKS.md` — advanced the current task to documenting the completed run without changing the pinned input configuration.
- `WORKLOG.md` — added these audit findings.
- No experiment configuration, preflight report, pipeline source, notebook, dataset, or run output was modified.

### Tests executed and results
- No tests were rerun for this read-only audit.
- The run manifest reports 35/35 validation checks passed, including 51 unit tests and compileall at execution time.

### Verified facts
- The manifest reports `run_status: completed`, 9,220 rows at the preparation, spatial matching, feature, and ranking stages, and runtime 232.297 seconds.
- The manifest configuration SHA-256 matches the current `config/final_pilot_experiment.json`; all seven recorded source-input size/hash checks match.
- All 47 files in the manifest output inventory exist and match their recorded SHA-256 checksums. The seven code hashes in the manifest also match the current scripts.
- Prepared FIRMS, matching, and feature outputs each contain 9,220 rows with no duplicate IDs. Their `firms_observation_id` sets and `firms_source_row` to observation-ID mappings agree. Candidate ranking contains 9,220 unique source-row keys, all 9,220 labels are `unknown_unlinked`, and no direct causal or ground-truth labels are present.
- The spatial-matching GeoPackage opens with 9,220 point geometries in EPSG:4326; no geometries are invalid or empty, and all retained coordinates lie inside the pilot bounding box.
- Sentinel-2 coverage is sparse: 11 detections have a temporally eligible scene, and 2 have usable clear pre-detection spectral samples. No satellite imagery was downloaded during this audit.
- The manifest records 27,234,146 bytes across 47 generated files before writing the manifest. Peak disk use was not measured.

### Status discrepancy explained
- The preflight report was generated at 2026-11-16 07:01:14 UTC and explicitly says the experiment had not yet been run and the run directory did not exist.
- The run manifest was created later at 2026-11-16 08:27:47 UTC. This timeline explains the apparent contradiction: the preflight and configuration lifecycle status were not revised after the later run. The config hash still matches, so the pinned parameter file used by the run is identifiable; keep that file unchanged to preserve the manifest checksum.
- The 232.297-second runtime is recorded in the manifest. Its start/end wall-clock fields have only second precision and no independent process timer log was found, so the fractional runtime is not independently reproducible from timestamps alone.

### Problems or warnings
- The execution is supported by a checksummed manifest and output inventory, but the manifest is not a cryptographic signature. The audit verifies consistency, not who authored the manifest.
- Peak disk usage was not sampled. The final artifact size is recorded.
- No independently linkable incident records or verified labels exist; supervised evaluation remains unsupported.

### Next recommended task
Add a concise execution addendum that records the later run and links it to the unchanged preflight and pinned configuration, without rewriting the historical preflight or changing the configuration checksum.

## 2026-11-16 — Final pilot execution addendum

### Task performed
- Added a concise execution addendum explaining the chronological difference between the historical preflight report and the later completed `run_001`.
- Recorded audited stage counts, candidate-ranking evidence categories, sparse Sentinel-2 coverage, label availability, integrity checks, and known reproducibility limits.
- Preserved the pinned experiment configuration and its checksum, the preflight report, and all historical run artifacts.

### Files changed
- `docs/final_pilot_experiment_execution_addendum.md` — created as a supplement; it does not replace the preflight report or run manifest.
- `TASKS.md` — marked the addendum task complete and advanced the next task to representative candidate case studies.
- `WORKLOG.md` — recorded this documentation update.

### Tests executed and results
- No pipeline or data tests were run; this change only documents already audited results. The manifest's recorded 51 passing unit tests and 35/35 validation checks are identified as run-time results, not as tests rerun for this edit.
- Attempted `python -m pytest -q` and `venv\Scripts\python.exe -m pytest -q`; both stopped because `pytest` is not installed in the available interpreters. No packages were installed.

### Outputs and preservation
- No data processing, downloads, or pipeline execution occurred.
- No source datasets, notebooks, preflight/configuration files, or historical outputs were modified.

### Problems or warnings
- The experiment configuration retains its historical preflight lifecycle status to preserve the exact configuration hash recorded by the completed run. The new addendum clarifies the chronology without changing that pinned file.
- No verified labels are available; supervised evaluation remains unsupported.

### Next recommended task
Select representative candidate case studies across OSM context categories and recurrence levels, using evidence review only and retaining unknown status unless independently verified evidence supports a label.

## 2026-11-16 — India-wide CV implementation roadmap

### Audit and task performed
- Verified the source-of-truth checkout is `C:\Users\PAWAN\Desktop\CV\ThermoScope`, remote `https://github.com/Pawandeep-Kaur06/ThermoScope.git`, branch `main`, HEAD `ef2f5981e4aed2f611da6bf642bb55d5103a58e7`.
- Read `AGENTS.md`, `TASKS.md`, `WORKLOG.md`, README, pilot reports/configuration, and inspected FIRMS preparation, country boundary/regions, tiled matching, OSM acquisition, satellite retrieval, features, ranking, evidence review, final experiment, case-study/evaluation code and tests.
- Inspected all local Sentinel-2 investigation TIFF headers and content hashes read-only: 37 files across seven runs, 22 distinct hashes. The fixed run used by the final pilot contains eight 64×64 four-band chips and eight SCL masks; none is image-labeled training data.
- Verified pilot evidence has zero detection-level verified or weak FIRMS labels and zero negative examples. Six event reviews/eight source records and date-only overlaps do not establish row-level links.
- Created `docs/india_wide_cv_implementation_roadmap.md` with verified facts vs recommendations/unknowns, target feasibility, national data architecture, evaluation requirements, phases, complexity and risks.
- Updated `TASKS.md` to record the intended India-wide direction while preserving the Dhanbad pilot as a historical benchmark and recording the first readiness task.

### Findings
- The repository has reusable country boundary, configurable region/tile assignment, per-tile CRS, cross-tile past-only recurrence, tiled OSM matching/resumption, FIRMS preparation, Sentinel-2 retrieval/QA, feature engineering, candidate ranking and human evidence review.
- A controlled two-tile run and broad synthetic tests exist, but no nationwide processing has been run. National OSM coverage is absent; local OSM is a pilot GeoPackage and an Eastern Zone source extract.
- Local raw FIRMS source exports exist, but product/sensor mix and national completeness must be verified before calling them an India-wide dataset. The prepared final pilot has 9,220 observations across 184 dates.
- Existing Sentinel-2 chips are a small purposive investigation sample, with duplicate content across runs; only two of 9,220 detections have usable pre-detection spectra in the saved feature results.
- Supervised or weakly supervised industrial-source classification is not justified with current evidence. A site-context task could be considered only with independent annotations; cause/source classes require precise independent incident labels and a grouped held-out test set.

### Validation and preservation
- `git diff --check` passed after the documentation edits.
- No experiment, model, or tests were run. No datasets were downloaded, scripts/configs/notebooks edited, or historical outputs changed.
- Existing uncommitted changes were preserved. Nothing was staged, committed, pushed, stashed, reset, or cleaned.

### Recommended next task
Perform the read-only FIRMS product/coverage and archive/NRT audit, deduplicate the local TIFF inventory by scene and checksum, and reconcile scenes with the existing pilot cells and temporal eligibility before choosing the first CV target or retrieving more data.

## 2026-11-16 — Reproducible candidate case-study selection

### Task performed
- Added `src/select_case_studies.py`, a command-line selector that deterministically chooses eight records from the saved ranking table using explicit evidence strata and a stable source-row tie breaker.
- Selection covers high and low past-only recurrence near mapped mining context, mining context beyond 250 m, a first observation near mapped mining, industrial landuse, general power infrastructure only, and cases with no nearby relevant OSM role.
- Wrote the final reproducible selection output under `data/processed/final_pilot_experiment/case_studies/run_20261116T094126Z/`; the earlier exploratory output at `run_20261116T094048Z/` was preserved and not overwritten.
- Updated `TASKS.md` to make the Sentinel-2 coverage assessment the next task.

### Validation
- `venv\Scripts\python.exe -m py_compile src\select_case_studies.py` passed.
- The selector completed against the 9,220-row candidate ranking and emitted eight cases from eight distinct 250 m cells.
- A separate output check confirmed unique FIRMS source-row IDs and cells, all coordinates inside the pilot bounding box, and all eight labels remain `unknown_unlinked`.
- The generated report records the input checksum and exact reproduction command.
- Attempted `python -m pytest -q` and `venv\Scripts\python.exe -m pytest -q`; pytest is unavailable in both interpreters. No dependencies were installed.

### Interpretation and limitations
- The sample is purposive, not a probability sample or evaluation set. Cell recurrence is an aggregation of detections, not proof of one persistent source.
- OSM proximity and ranking categories remain contextual evidence only. The sample contains no verified labels.
- Sentinel-2 evidence remains sparse; six selected cases lack a usable chip, one is cloud/shadow contaminated or unverifiable, and one has a sampled pre-detection image. The latter's spectra remain contextual evidence rather than thermal confirmation.
- No downloads, full pipeline runs, or nationwide processing occurred. Notebooks, original datasets, historical outputs, configuration, and preflight were preserved.

### Next recommended task
Assess imagery timing and cloud quality for the selected case set; only consider a narrowly scoped public STAC retrieval after checking existing chips and documenting the additional data volume.

## 2026-11-16 — Sentinel-2 coverage assessment for selected cases

### Task performed
- Added `src/assess_case_study_satellite.py` to check existing local chip footprints and point-level SCL values against exact FIRMS coordinates and UTC acquisition timestamps, and optionally query public STAC metadata without fetching raster assets.
- Queried the Element 84 Earth Search public STAC endpoint (`https://earth-search.aws.element84.com/v1/search`, `sentinel-2-l2a`) for eight selected case locations and a 30-day pre-observation window; no imagery assets were requested or downloaded.
- Saved the result in `data/processed/final_pilot_experiment/satellite_assessment/run_20261116T094840Z/`.

### Findings
- All eight catalog queries succeeded. The metadata responses totaled 1,442,161 bytes. All reported nearest scenes are on or before the corresponding FIRMS observation timestamp.
- Existing local chips from the historical imagery run totaled 231,750 bytes for 16 TIFFs (eight 4-band chips and eight SCL chips). Only two selected case points are covered by a temporally eligible local chip footprint: the recurring mining case is cloud contaminated (point SCL class 8; chip cloud/shadow fraction about 85%), while the general-power-infrastructure case has the usable sampled pre-detection optical context (point SCL class 5).
- Four additional cases have a catalog scene with scene-level cloud cover at or below 20% within 30 days before FIRMS. These are retrieval candidates only; scene-level cloud is not a substitute for chip-level SCL screening. Three cases had no such low-cloud scene in the 30-day window.
- A local 4-band chip plus SCL pair has a median compressed size of 29,273 bytes. Four additional low-cloud candidate chip pairs would be about 117,092 bytes on disk based on that median; remote COG range-read traffic may be larger and was not measured. Six cases have no temporally eligible local chip footprint, for which one chip pair each would be about 175,638 bytes.
- Sentinel-2 is optical context, with 10 m visible bands and 20 m SWIR resampled in the existing workflow; date offsets, cloud, and spatial support prevent it from confirming a FIRMS thermal source.

### Validation
- `venv\Scripts\python.exe -m py_compile src\assess_case_study_satellite.py` passed.
- Output checks confirmed eight case rows, eight successful STAC metadata queries, no scene timestamp after its FIRMS observation, and `assets_downloaded: false` in the manifest.
- Output paths in the assessment are repository-relative; output is Git-ignored.
- The STAC collection and public catalog approach are documented by [Element 84 Earth Search](https://github.com/Element84/earth-search/blob/main/README.md), which describes Earth Search as a free-to-use STAC catalog for public AWS-hosted geospatial datasets.

### Tests and limitations
- `pytest` remains unavailable in the active interpreters, so the repository test suite could not be run; no dependency was installed.
- Low scene-level cloud candidates require chip retrieval and pixel-level quality assessment before their spectra could be used. No retrieval has been authorized or performed in this task.
- No labels or classification claims were added.

### Next recommended task
Prepare final report figures and tables from the completed pilot, selected cases, and evidence limitations; keep the candidate-ranking outputs separate from verified labels and do not report supervised performance.

## 2026-11-16 — Final pilot results report

### Task performed
- Added `docs/final_pilot_results.md` with the completed pilot's input period, stage checks, candidate-category and distance-threshold tables, Sentinel-2 coverage, evaluation boundary, label availability, and limitations.
- Included exact rerun command templates for the case selector and metadata-only Sentinel-2 assessment, with new output directories required to prevent overwriting.
- Linked the report to existing figures, the reproducibility manifest, the execution addendum, the eight selected case studies, and the satellite metadata assessment.
- Kept the result framed as a prioritization/evidence-review study; no classifier or performance metrics are claimed.
- Updated `TASKS.md` to move the project from evidence/table preparation to final documentation and presentation.

### Validation
- Cross-checked report counts against `run_001` category, distance-threshold, evidence-coverage, feature, ranking, and reproducibility artifacts.
- Confirmed referenced figures exist locally and the report's relative links point to the saved run assets.
- Confirmed generated reports/figures remain ignored by Git. `git diff --check` passed; no files were staged or committed.

### Limitations
- The report refers to generated figures under ignored local data paths; a fresh checkout must reproduce the run before those embeds resolve.
- The repository test suite remains unavailable in the active interpreters because `pytest` is not installed. The manifest's 51-test pass is historical run evidence, not a rerun during this report preparation.

## 2026-11-16 — Final pilot presentation

### Task performed
- Created a 10-slide live presentation summarizing the pilot scope, inputs, OSM distance sensitivity, evidence-only ranking, past-only recurrence, Sentinel-2 coverage, representative case studies, and evaluation limits.
- Used editable charts and tables and added source references in slide speaker notes.
- Visually inspected all 10 slides at full slide resolution and repaired the case-study table widths/formatting.
- Updated `TASKS.md` to record that no task is currently queued; future retrieval, incident-label collection, or model development requires a separately scoped task.

### Validation and interpretation
- Artifact inspection confirmed 10 slides, 3 editable charts, 2 native tables, and 10 speaker-note blocks.
- All slides state or preserve that the project is candidate prioritization, not verified classification. No model metrics or labels were added.
- The live presentation is available in the Artifact Session viewer (artifact reference `artifact_F_v0dlk6kjfRXZrSkMNIEKCkQiXTUuwj`); it is not a local PPTX file.
- No imagery was downloaded. The pilot config, historical outputs, notebooks, and source datasets remain unchanged.

## 2026-11-16 — Final pilot analysis and visualization package

### Task performed
- Added `src/generate_final_pilot_analysis.py`, a reporting-only script that reads the audited `run_001` FIRMS, matching, feature, ranking, validation, and local OSM outputs. It refuses to overwrite non-empty output folders.
- Created eight publication-resolution PNG figures and ten analytical CSV tables under `outputs/final_pilot/`, plus a provenance manifest with source checksums, parameters, software versions, and output hashes.
- Updated `docs/final_pilot_results.md` with calculated numerical findings, uncertainty and label caveats, and figure/table locations.
- Added four focused standard-library `unittest` checks for OSM tag parsing and input alignment/bounds/ID validation; updated this task tracker.

### Validation
- Confirmed 9,220 aligned FIRMS, spatial matching, feature, and candidate-ranking records; 9,220 unique FIRMS IDs; all points fall in the configured pilot bounding box; distance CRS is EPSG:32645.
- Confirmed all local OSM geometries in the three source layers are valid before mapping; no new retrieval or experiment processing occurred.
- `venv\\Scripts\\python.exe -m unittest tests.test_final_pilot_analysis -v`: 4 tests passed.
- `venv\\Scripts\\python.exe -m py_compile src\\generate_final_pilot_analysis.py tests\\test_final_pilot_analysis.py` and `git diff --check` passed.
- Generated outputs remain excluded by `.gitignore`; existing notebooks, historical run outputs, and source datasets were preserved.

### Findings and limitations
- The experiment contains 1,063 occupied 250 m grid cells; 522 contain detections on multiple acquisition dates. Repeated observations do not establish a single physical source.
- At 250 m, saved matching counts are 7,679 unambiguous relevant-context candidates, 334 ambiguous, and 1,207 with no relevant mapped feature within threshold.
- Only two detections (0.022%) have usable, temporally eligible pre-detection Sentinel-2 spectra; 519 later scenes are withheld from historical features.
- All 9,220 detection labels remain `unknown_unlinked`; no supervised model or performance metrics are asserted.
- The full repository pytest suite was not run because pytest is unavailable; the four focused tests ran via the standard library.

## 2026-11-16 — Representative final-pilot case studies

### Task performed
- Added `src/create_pilot_case_studies.py` to create a category-balanced sample from the completed `run_001` tables. It selects 12 observations, two per candidate-ranking category, near within-category 25th/75th review-rank positions; where possible, a second selection uses an existing chip nearest the 75th-percentile position.
- Generated a case register, comparative table, detailed nearby-OSM feature-distance table, 12 individual case summaries, a location overview, and 12 case-specific map/image panels under `outputs/final_pilot/case_studies/run_20261116T_case_review_final/`.
- Four panels use Sentinel-2 chips already referenced by the pilot feature table. Their scene dates post-date the corresponding FIRMS observations, so all are explicitly marked context-only and none contributes historical spectral evidence.
- Added input/chip/output checksums, software versions, selection parameters, and validation results to `case_study_manifest.json`; wrote `docs/final_pilot_case_studies.md` and added selection/category tests.

### Findings and limits
- The 12 cases cover all six ranking categories (two each), with FRP from 0.88 to 9.00 MW and 0–29 strictly prior distinct dates in the corresponding 250 m cells. This is a category-balanced illustration, not a probability sample.
- 11 of 12 have at least one mapped industrial or power feature within 1 km in the local OSM snapshot. OSM proximity, power infrastructure, and recurrence remain context only.
- Four selected cases link to existing Sentinel-2 chips; cloud estimates range from 14.2% to 87.1%. Two chips have a clear pixel-level SCL flag but were acquired after their FIRMS observation; two have at least 50% chip cloud/shadow. Zero selected cases have eligible pre-detection spectra.
- The reviewer assessment remains pending for all 12. No incident information, labels, or negative examples were fabricated; no imagery was downloaded and the experiment was not rerun.

### Validation
- `venv\\Scripts\\python.exe -m unittest discover -s tests -v`: 58 tests passed.
- Python compilation and `git diff --check` passed. The case-study manifest's source and output hashes, 12 unique IDs, bbox membership, valid OSM geometries, unknown-only labels, and pending-review status were checked.
- Prior case-study output folders and historical experiment runs were preserved; generated outputs remain Git-ignored.

## 2026-11-16 — Final pilot evaluation and scientific limitations

### Task performed
- Added `src/evaluate_final_pilot.py` to evaluate saved `run_001` outputs and the existing 12-case register without rerunning processing or fetching data.
- Generated `docs/final_pilot_evaluation.md`, `outputs/final_pilot/tables/evaluation_summary.csv`, and `candidate_category_threshold_sensitivity.csv`.
- Generated three evaluation figures: OSM threshold/category sensitivity, evidence characteristics by candidate category, and the representative-case evidence scatter.
- The report quantifies FIRMS, OSM, recurrence, and Sentinel-2 coverage; compares all six evidence-only review categories; re-bins categories at 100, 250, 500, and 1,000 m; and discusses the 12 purposively selected cases and scientific limitations.
- Updated `TASKS.md`. No labels, negatives, supervised metrics, or classifier were added; no download or experiment rerun occurred.

### Findings and limitations
- 9,220 observations cover 184 dates; 8,206 of 8,333 OSM features contributed to proximity matching. At 250 m, matching statuses are 7,679 unambiguous, 334 ambiguous, and 1,207 without relevant mapped context.
- 522 of 1,063 occupied 250 m cells recur across multiple dates; 7,136 detections meet the three-prior-date ranking rule. Recurrence remains a grid-cell observation pattern, not confirmed source identity.
- Only 2 detections (0.022%) have usable temporally eligible Sentinel-2 spectra. All four case-study chips postdate their corresponding detections; none is historical evidence for those cases.
- The category assignments move with spatial threshold by construction: compared with 250 m, 604 observations change categories at 100 m, 316 at 500 m, and 541 at 1 km. These are sensitivity counts, not errors or validation metrics.
- No verified FIRMS-to-incident links or defensible negative examples exist; supervised evaluation is not currently justified.

### Validation
- `venv\\Scripts\\python.exe -m py_compile src\\evaluate_final_pilot.py tests\\test_final_pilot_evaluation.py` passed.
- `venv\\Scripts\\python.exe -m unittest discover -s tests -v`: 60 tests passed, including two evaluation tests for threshold re-binning and unknown distances.
- `git diff --check` and generated-output schema/count/file checks passed. The first reporting attempt exposed a synthetic test fixture whose 250 m labels conflicted with its own distances; the fixture was corrected, and the complete suite then passed.
- Existing datasets, experiment outputs, notebooks, and prior figures/tables were preserved. New output files remain Git-ignored; nothing was staged or committed.

## 2026-11-16 — FIRMS and satellite inventory for India-wide CV readiness

### Task performed
- Read `AGENTS.md`, `TASKS.md`, `WORKLOG.md` and `docs/india_wide_cv_implementation_roadmap.md` before the inventory. Confirmed the Desktop ThermoScope checkout and preserved its existing modified/untracked work.
- Stream-scanned the eight local raw/derived FIRMS CSVs, including raw archive/NRT, legacy India-rectangle derivatives, pilot-prepared data, sample_1000, and the run_001 input copy. Computed row/schema/missingness/date/coordinate coverage, India polygon membership, within-file normalized observation identities and requested pairwise overlaps.
- Inspected all 37 local satellite-investigation TIFFs with Rasterio; recorded absolute path, size, SHA256, dimensions, band count/types, CRS, native/WGS84 bounds, resolution, nodata, metadata/scene/date, content duplicates and linkage to run_001 features.
- Created `docs/india_wide_data_inventory.md`, `outputs/india_wide_inventory/firms_inventory.csv`, and `outputs/india_wide_inventory/satellite_inventory.csv`.
- Updated `TASKS.md` with this completion and the next provenance/target-definition steps.

### Findings
- Raw archive and NRT contain 4,073,699 and 7,247,714 rows. Both report SNPP platform/instrument and likely belong to the Suomi-NPP VIIRS family; exact collection/resolution and retrieval coverage are not stated in the CSV metadata. No MODIS platform was observed.
- The raw exports' India-polygon counts are 374,683 archive and 103,701 NRT. Archive/NRT observation identity overlap is zero; four repeated identities occur within raw NRT globally, outside the legacy India rectangle subset. Raw NRT lacks a `type` column.
- Legacy `india_combined.csv` contains 766,578 records from a broad 6–38°N, 68–98°E rectangle; 288,194 are outside the configured Natural Earth India polygon. It is a concatenation, not an exact country-filtered national table. The prepared pilot and run input each contain 9,220 rows and match one another.
- The 37 TIFFs contain 22 distinct file hashes, 29 four-band file copies, 14 unique four-band raster contents and six STAC scene IDs. The pinned final run has eight chip/mask pairs across four scene IDs. Run_001 links 530 detections to scene metadata; 11 are temporally eligible, nine of those are cloud/shadow contaminated or unverifiable, two have usable clear pre-detection spectra, and 519 later scenes are withheld.
- No image-level labels exist; all 9,220 ranked FIRMS observations remain unknown/unlinked. No negative examples were created. The available chips support only limited visual inspection/context, not CV training or validated source classification.

### Validation and preservation
- Verified the FIRMS inventory has eight rows and the satellite inventory has 37 rows. All 37 TIFF paths exist; sizes, SHA256 values and Rasterio dimensions/band counts match the inventory. A repository-wide search excluding `.git` and Python environments found no TIFF files outside these 37.
- Reconciled raw input counts with the pinned config, archive/NRT overlaps, 9,220 pilot source mappings, 530/11/519/9/2 satellite feature counts, and unknown-only candidate labels.
- `git diff --check` passed (only existing notebook/script line-ending warnings were printed). No model/pipeline tests were run because this task added inventory artifacts and documentation only.
- No API/network requests, downloads, pipeline reruns, training, source-data changes, notebook edits or historical-output changes occurred. No files were staged, committed or pushed.

### Recommended next task
Recover authoritative FIRMS product/query and retrieval-coverage provenance, then version a national FIRMS table with explicit archive/NRT schema and coverage rules. Freeze the first CV target and label standard before any imagery retrieval or model development.
## 2026-11-16 — Jharkhand-wide pilot extension

### Scope and implementation
- Updated the active project scope from India-wide planning to Jharkhand, retaining the Dhanbad–Jharia–Bokaro pilot and preserving the historical experiment outputs.
- Prepared the Jharkhand administrative polygon from OSM relation 1960191 in the already-local Geofabrik Eastern Zone extract (no PBF download, Overpass query, nationwide processing, or model training).
- Filtered local FIRMS archive/NRT exports to Jharkhand, retaining source provenance and deduplicating. Output: 21,450 unique rows from 2026-01-20 through 2026-09-06.
- Locally converted the existing OSM PBF into a tagged state GeoPackage (37,046 features); ran matching over 14 active tiles with per-tile UTM, 250 m equal-area recurrence grid, and past-only recurrence.
- Retrieved six small, representative Sentinel-2/SCL chips via the public Earth Search STAC workflow; integrated only temporally eligible, clear samples. No model was trained.
- Produced rule-based review categories and a state visualization/summary package. The complete report and reproducibility manifest are `docs/jharkhand_results.md` and `outputs/jharkhand/run_002/results_manifest.json`.

### Findings and limitations
- OSM feature groups overlap: 31,231 power-infrastructure records dominate; there are also 1,334 mining/extraction, 1,223 industrial-facility, 861 industrial-structure, 750 industrial-landuse, 13 waste, and 2,178 vegetation-context features.
- At 250 m, 12,535 detections have a relevant mapped feature (11,302 unambiguous proximity candidates and 1,233 ambiguous); 8,915 lack relevant mapped context within that distance. Distance sensitivity is reported at 100/250/500/1,000 m.
- The state run has 8,466 occupied 250 m recurrence cells; 1,061 recur across multiple dates, and the maximum is 72 distinct dates. Grid recurrence does not establish a unique physical source.
- Only one detection has usable clear pre-detection Sentinel-2 spectral values. No independently verified detection labels or negative examples are available; supervised classification and performance claims remain unsupported.
- The OSM administrative polygon is not a legal boundary and the extract scan logged malformed rings elsewhere in the source PBF, although the extracted state geometry passed validity checks. GEM coverage remains Dhanbad-specific. One failed partial run with a misspelled `jharkland` directory is preserved; it is not used in final results.

### Validation
- The state result manifest records 19/19 checks passed: input/output row alignment, unique stable observation IDs, state polygon membership, tile assignment/CRS, past-only recurrence, and no future imagery used as spectral evidence.
- The existing output package reports six ranking categories; all candidate labels remain unknown. The map includes 21,450 FIRMS observations and up to 5,000 selected OSM features.
- `venv\\Scripts\\python.exe -m unittest discover -s tests -v`: all 68 tests passed.
- `py_compile` passed for all eight scripts used in the Jharkhand workflow. `git diff --check` passed; Git printed only pre-existing line-ending conversion warnings for modified notebooks and the matcher.
- Generated output validation confirmed 19/19 manifest checks, six summary tables plus the quality table, seven PNG figures, and the 13.39 MB HTML map. The dashboard references online Leaflet and basemap assets.

## 2026-11-16 — CV dataset readiness and manifest

### Task performed
- Read the Jharkhand results report, India-wide CV roadmap, task/work logs, state satellite run metadata, state and pilot feature outputs, and inventoried all local processed TIFF imagery.
- Added `src/prepare_cv_dataset.py`, a local-only manifest builder that hashes and deduplicates four-band Sentinel-2 chip files, pairs SCL masks, records dimensions/bands/resolution/CRS/scene/date/center coordinates/tile/SCL clear fraction, and creates geographic/scene leakage groups. It refuses to overwrite an existing manifest.
- Generated `data/processed/cv_dataset/manifest.csv` and `docs/cv_dataset_report.md`. All samples are explicitly unlabelled and unassigned to training/validation/test.
- Added `tests/test_prepare_cv_dataset.py` for deduplication, SCL handling, unknown labels, leakage grouping, and overwrite safety. No imagery was downloaded or copied; no model was trained.

### Findings and decisions
- Across local processed imagery there are 49 TIFF files, including 35 four-band chip files and 14 SCL masks. Content deduplication yields 20 distinct four-band chips from 11 Sentinel-2 scene IDs and 14 locations spanning six Jharkhand tiles.
- All 20 unique chips are 64×64 four-band uint16 (B04/B03/B02 at 10 m; B11 native 20 m resampled to 10 m). Fourteen have paired SCL. Eight have any clear valid SCL pixels, three have at least 50% clear pixels, and two have at least 95% clear pixels.
- The state feature table has only one usable pre-detection clear spectral sample (8 rows with temporally eligible scenes). The existing pilot feature table has two usable samples. Neither is an image-label dataset.
- Credible image labels per class: zero; class imbalance undefined; independent evaluation impossible. FIRMS/ranking/OSM/GEM are not converted to labels.
- Recommended future CV task: broad surface-context classification using independently reviewed reference labels. ESA WorldCover is a possible weak broad land-cover layer, but its classes do not isolate industrial/mining surfaces and its 2021 date is mismatched to the 2026 chips. Official coal lease boundaries are not visible-surface labels. No local reference layer was acquired or treated as truth.

### Validation
- `venv\\Scripts\\python.exe src\\prepare_cv_dataset.py --output data/processed/cv_dataset/manifest.csv` completed and wrote 20 unique unlabelled samples across 11 scenes.
- `venv\\Scripts\\python.exe -m unittest tests.test_prepare_cv_dataset -v`: passed (3 tests).
- `venv\\Scripts\\python.exe -m unittest discover -s tests -v`: all 71 tests passed.
- `venv\\Scripts\\python.exe -m py_compile src\\prepare_cv_dataset.py tests\\test_prepare_cv_dataset.py` and `git diff --check` passed.

## 2026-11-16 — Reference-data strategy and review register

### Work performed
- Re-read the CV dataset readiness report, Jharkhand land-cover plan and results, task/work logs, and existing 20-chip manifest. Confirmed six existing `jharkhand_analysis/run_001` chips span six state tiles; these form a small review queue, not a representative state sample.
- Reviewed official NRSC/Bhuvan Phase II metadata and access workflow, the 2025 Department of Space statement confirming Jharkhand institutions used Bhuvan 1:10,000 LULC, and the Jharkhand GIS/JSAC layer catalogue.
- Added `docs/reference_data_strategy.md` describing source independence, dates, access and size unknowns, per-pixel review rules, uncertain-pixel handling and geographic/scene split safeguards.
- Added `src/prepare_reference_review_register.py` and generated `data/processed/cv_dataset/reference_review_register.csv` from existing chips. All six are pending source review, with no label or split.
- Added tests validating pending rows have no labels, human-accepted labels require auditable evidence, and geographic/scene leakage groups cannot cross splits.

### Findings and limitations
- Bhuvan Panchayat LULC 1:10K SISDP Phase II is a promising independent broad land-cover reference: published metadata reports fused Cartosat-1/LISS-4 input and 2018–2023 mapping. It is not field truth and may be temporally stale relative to 2026 chips.
- A Government of India 2025 response confirms Jharkhand public institutions accessed Bhuvan 1:10,000 LULC, but project access to the specific Phase II export, its licence/redistribution terms, per-area mapping dates and exact coverage are not established. Portal workflow is request-based; archive size is unpublished. No data payload was downloaded.
- The six-chip queue spans approximately 83.91–87.39°E and 22.80–25.04°N, about 2.46 km² total chip footprint. Existing SCL summaries show substantial cloud contamination. Credible labels remain zero, so supervised training/evaluation is still unjustified.
- WorldCover 2021 remains weak reference only; OSM, GEM, FIRMS and candidate rankings are not image labels.

### Validation and preservation
- `venv\\Scripts\\python.exe -m unittest tests.test_reference_review_register -v` passed (4 tests).
- `venv\\Scripts\\python.exe -m unittest discover -s tests -v` passed (75 tests total).
- `venv\\Scripts\\python.exe src\\prepare_reference_review_register.py --manifest data\\processed\\cv_dataset\\manifest.csv --chip-root data/processed/jharkhand_analysis/run_001/satellite_investigation/ --output data\\processed\\cv_dataset\\reference_review_register.csv` generated six rows; all remain unlabelled, pending, and unsplit.
- No reference download, model training, notebook edit, historical-output change, staging, commit or push occurred.

## 2026-11-16 — Bhuvan SISDP Phase II access verification

### Work performed
- Read the reference strategy and all six rows in the existing reference-review register; preserved all records.
- Reviewed the official Bhuvan Panchayat manual, Phase II announcement, Bhuvan terms, Bhuvan SISDP page and the Department of Space's 2025 Rajya Sabha response. Attempted only a lightweight official WMS GetCapabilities metadata call; it timed out and no map data was requested.
- Added `docs/bhuvan_reference_data_access.md` with portal steps, source and licence analysis, precise unresolved coverage/date/size questions, storage considerations, and a request draft that has not been submitted.
- Added `data/processed/cv_dataset/reference_source_inventory.csv` covering Bhuvan Phase II, historical Bhuvan 50K, WorldCover weak reference and JSAC catalogue candidate.
- Updated `docs/reference_data_strategy.md`, `TASKS.md` and this work log to reflect the access findings.

### Findings and decision
- The SISDP manual requires Bhuvan SSO for Phase II downloads, documents a Get Data request by state/district and says delivered format is Shapefile. It lists research studies as a request purpose. Exact Phase II Jharkhand districts/polygons and per-area dates were not identified in the public materials inspected. The 2025 Government answer confirms Jharkhand institutions accessed Bhuvan 1:10K LULC but does not specify Phase II.
- Product metadata describes fused Cartosat-1 + LISS-4 mapping, 2018–2023, 2.5m source resolution and WGS84 geographic coordinates; a sample layer identifier in the manual uses a different 2016–2019 range, so per-AOI mapping years need clarification.
- General Bhuvan terms require prior written authorization for copying/derivative works and restrict redistribution; academic request purpose is not by itself permission to rasterize masks or publish derived data. No licence was inferred. Acquisition and labeling are paused until written terms/permission, AOI coverage/date, format/schema and file-size estimate are provided.
- No data downloaded, portal account used, request submitted, chip labeled or model trained. No notebook or historical output changed; no staging, commit or push.

## 2026-11-16 — Open land-cover reference decision and sample

### Work performed
- Compared ESA WorldCover 2021, GHSL built-up products, JRC Global Surface Water and Dynamic World against broad Jharkhand Sentinel-2 land-cover labels, date alignment, resolution, source dependence and use terms.
- Verified WorldCover 2021 v200 is public on AWS, nominal 10 m in 3° COGs, EPSG:4326, and CC BY 4.0 with required attribution. Full-object HEAD sizes for the three tiles intersecting the six existing chip footprints totaled 372,175,158 bytes; the six-tile full-region estimate remains 701,510,870 bytes.
- Added `src/download_worldcover_reference_sample.py` with source-window extraction and no-overwrite behavior; added synthetic tile-selection tests.
- Retrieved only six source-grid WorldCover windows corresponding to existing chip footprints. GDAL logs show 13 HTTP 206 byte-range responses totaling 1,017,485 bytes. Six compressed crop GeoTIFFs total 11,766 bytes. The windows were not resampled or converted into labels.
- Added `docs/cv_reference_dataset_decision.md` and updated the reference source inventory. Preserved license attribution, tile ETags, source dates/URL, checksums, CRS/resolution and sample class counts in `data/raw/cv_reference/worldcover_2021_sample_validated/`.

### Findings and limitations
- WorldCover supports broad built-up (50), vegetation (10/20/30), cropland (40), bare/sparse (60), and water (80) concepts at a useful nominal 10 m grid. It does not label mines, industrial facilities or fires. “Built-up” combines residential and industrial; “bare” includes extraction but also natural bare land.
- WorldCover's 2021 map is generated using Sentinel-1 and Sentinel-2, while the local input chips are 2026 Sentinel-2. It can supply weak/reference-derived training targets only; temporal change and shared sensor family prevent claims of independent 2026 ground truth.
- GHSL is open CC BY 4.0 but the relevant 10 m built-up epochs (2018/2022) provide only built-up context and include Sentinel-2-derived products. JRC surface water is openly reusable and Landsat-derived but 30 m, better for coarse water context than 10 m pixel truth. Neither replaces a contemporary local independent test set.
- The local 20-chip inventory, six-chip geographically spread sample and five connected leakage groups are insufficient for a defensible independent three-way model evaluation. No labels were assigned and no model was trained.

### Validation and preservation
- `venv\\Scripts\\python.exe -m unittest tests.test_download_worldcover_reference_sample -v` passed (3 tests).
- `venv\\Scripts\\python.exe -m unittest discover -s tests -v` passed (78 tests total).
- `py_compile` passed for the acquisition script/tests. Six sample rasters validated as one-band uint8 EPSG:4326; each source window contains its transformed Sentinel chip bounds and only valid WorldCover class/no-data codes. SHA-256 checksums and file-size totals match the sample manifest.
- No notebook, historical output or source chip was changed. The separate Bhuvan access request remains unsubmitted; nothing was staged, committed or pushed.
- A first validation attempt created one extra source crop before a QA method error; its SHA-256 matches the corresponding crop in the validated directory. The duplicate was retained rather than removed after the desktop safety review rejected the cleanup command; it is not referenced by the validated inventory or manifest.

## 2026-11-16 — Six-chip segmentation feasibility gate

### Work performed
- Re-read the CV reference decision, CV readiness report, land-cover plan, task/work logs, and inspected all six WorldCover crops with their corresponding Sentinel-2/SCL chips.
- Implemented `src/prepare_weak_labeled_chips.py`: nearest-neighbor categorical reprojection onto each exact Sentinel grid, SCL clear-class and image-valid masking, five broad weak classes, explicit ignore pixels, source provenance/checksums, and leakage-group feasibility checks. It refuses to overwrite an existing output directory and does not train.
- Generated the six 64×64 weak masks and sample/readiness manifests in `data/processed/cv_dataset/worldcover_weak_alignment_v001/`.
- Added `tests/test_prepare_weak_labeled_chips.py` for alignment, cloud/shadow/invalid masking, shape validation, group leakage and the two-pixel pseudo-holdout case.
- Added `docs/cv_prototype_results.md` reporting the data gate and unrun metrics.

### Findings and decision
- SCL-clear usable pixels by chip: 0, 0, 4,036, 0, 0, and 2. The 4,036-pixel chip is one geography/scene group; the 2-pixel chip is a different group. Only one leakage group has at least 256 weak-label pixels.
- Aggregate weak-mask counts: vegetation 3,160; cropland 813; built-up 49; bare/sparse 16; water 0. Built-up/bare occur only in the single large group; no held-out group supports them.
- Although two groups have nonzero labels, the second has only two pixels, so no meaningful train/test or three-way split exists. No model, baseline, weights or loss/IoU/Dice/confusion metrics were produced. These would otherwise be agreement with 2021 weak labels, not independent 2026 ground truth.

### Validation and preservation
- `venv\\Scripts\\python.exe -m unittest tests.test_prepare_weak_labeled_chips -v`: passed (6 tests).
- `venv\\Scripts\\python.exe src\\prepare_weak_labeled_chips.py --register data\\processed\\cv_dataset\\reference_review_register.csv --sample-manifest data\\raw\\cv_reference\\worldcover_2021_sample_validated\\sample_manifest.csv --output-dir data\\processed\\cv_dataset\\worldcover_weak_alignment_v001`: completed for six chips; 4,038 usable weak pixels; grouped split readiness blocked.
- `py_compile` passed for the new script/tests. No model training, extra downloads, notebook or historical-output changes, staging, commit or push occurred.

## 2026-11-16 — Local image upload and evidence application

### Work performed
- Added `src/thermoscope_app/core.py` for bounded in-memory GeoTIFF/PNG/JPEG validation, preview generation, GeoTIFF affine/CRS/date metadata extraction, JPEG EXIF GPS/date extraction, FIRMS time/radius filtering, exact precomputed recurrence-cell context, geometry-aware OSM distance matching, and date-eligible lookup of existing Sentinel-2 chips.
- Added `src/thermoscope_app/server.py`, a local-only standard-library HTTP server and multipart API. It refuses non-loopback binds, restricts uploads to 25 MiB, supports configurable local evidence paths, and does not retain uploads or log request filenames/paths.
- Added `app/index.html` with the upload/preview workflow, manual location/date fields, evidence settings, CV-unavailable state, and evidence results. Added `docs/image_upload_prediction_design.md`, README instructions, and an explicit Pillow dependency.
- Added `tests/test_thermoscope_app.py` for image format/size validation, metadata extraction, unavailable model output, Sentinel date eligibility, past-only FIRMS recurrence, and OSM feature-category distance handling.

### Findings and safeguards
- Confirmed the local completed Jharkhand run has prepared FIRMS features, OSM GeoPackage, past-only recurrence features, and only six small Sentinel-2 chips. The app uses only those local files; it performs no API queries or downloads.
- The app does not have a trained image classifier and does not emit the requested fire/source classes. The result remains `insufficient_evidence_to_classify`; FIRMS, OSM and optical imagery remain separate evidence indicators.
- FIRMS same-day observations are shown with ordering explicitly unknown; recurrence counts use strictly earlier dates. Sentinel chips are withheld unless the uploaded date exists and the scene date is not later than the upload date. OSM distances are computed in a local UTM CRS and geometry-aware for points, lines and polygons.
- Upload content is never written to disk. The app binds to `127.0.0.1` by default and refuses remote bind addresses.

### Validation
- `venv\Scripts\python.exe -m unittest tests.test_thermoscope_app -v`: 9 tests passed.
- Live local HTTP smoke test on port 8766: the page, `/api/health`, and multipart upload returned HTTP 200 with all local evidence inputs available. A generated in-memory PNG upload produced a 36×24 preview, matched 81 local FIRMS rows and 2 OSM features in the chosen test radius, returned the existing 250 m cell history (67 earlier detections over 56 dates at the nearest matched observation), and reported CV unavailable / insufficient evidence to classify. No temporally eligible Sentinel chip was within 10 km, so none was shown.
- `venv\Scripts\python.exe -m py_compile src\thermoscope_app\core.py src\thermoscope_app\server.py tests\test_thermoscope_app.py` passed. No existing outputs/notebooks/data were modified and no files were staged or committed.
## 2026-11-16 — Industrial-fire model data and feasibility gate

### Work performed
- Re-read repository instructions, app modules/UI, the CV dataset and prototype reports, Jharkhand results, local manifests, requirements, tests, and `models/`.
- Audited 62 local raster files across processed imagery and WorldCover reference storage. This comprises 35 four-band Sentinel chip copies (20 unique contents), 14 SCL layers, six aligned WorldCover weak masks, and seven raw WorldCover windows (including a retained duplicate). Added `src/inventory_cv_model_data.py` and generated `docs/cv_model_dataset_inventory.csv` with per-file SHA-256, size, raster schema, CRS/grid, source and explicit label role.
- Checked the public Zenodo record and its small README/metadata (not the image archive). Confirmed the Industrial Smoke Plumes dataset: 21,350 13-band Sentinel-2 chips from 2019 and 624 European E-PRTR-selected locations; 3,750 manually annotated visible-smoke positives, 17,600 no-visible-smoke negatives, and segmentation polygons for 1,437 images. Zenodo metadata declares CC BY 4.0; the related training code is GPL-3.0. The image archive is 6,359,411,128 bytes; no imagery/model weights were downloaded.
- Added `docs/cv_model_development.md` with the local and public data inventory, model/task assessment, archive-size estimate, precise blocker, and minimum reference data required for a fire-class model.
- Added tests for the inventory schema and for preserving unknown/unavailable prediction output when model/evidence inputs are missing.

### Decision and limitations
- No suitable local or public labelled satellite dataset was identified for *industrial-fire* or *persistent thermal-source classification* in Jharkhand. The best public match is visible industrial smoke, not fire; it cannot be relabelled as fire because routine industrial emissions may produce smoke and fires may have no visible plume in an optical overpass.
- Local labels: zero credible fire positives, zero verified negative controls, and zero independent test images. Existing WorldCover masks are weak broad-land-cover references and are too group-concentrated for meaningful land-cover validation; they are not fire labels. No local pretrained model exists and the environment does not include PyTorch/torchvision.
- The 6.36 GB smoke archive is a potentially useful separate task only after a user-approved scope extension. No large data or model weights were downloaded; no model was trained. The app integration remains explicitly unavailable and evidence panels remain separate.
- No notebook, source imagery, or historical output was modified. No staging or commit occurred.

### Validation
- `venv\Scripts\python.exe src\inventory_cv_model_data.py --output docs\cv_model_dataset_inventory.csv`: inventoried 62 files, 966,136 bytes total. Output creation used a new path and refused overwrite if it already existed.
- `venv\Scripts\python.exe -m unittest tests.test_inventory_cv_model_data tests.test_thermoscope_app -v`: passed (11 tests).
- Full test suite and syntax checks recorded at task completion below.

### Final validation (2026-11-16)
- `venv\Scripts\python.exe -m unittest discover -s tests -q`: **95 tests passed**.
- `venv\Scripts\python.exe -m py_compile src\inventory_cv_model_data.py src\thermoscope_app\core.py tests\test_inventory_cv_model_data.py tests\test_thermoscope_app.py`: passed.
- `git diff --check`: passed; Git emitted only existing LF-to-CRLF working-copy notices for modified notebooks/requirements/matching script.
- No data archives or model weights were downloaded; no model was trained; no files were staged or committed.

## 2026-11-16 — Industrial smoke dataset suitability assessment

### Work performed
- Inspected the existing smoke/fire model feasibility report and ThermoScope upload/inference contract. Verified that the application accepts GeoTIFF but currently has no model; local Sentinel chips are four-band, unlike the smoke model's 12-band Sentinel-2 input.
- Reviewed the Zenodo record, its small README, the associated paper and code repository. Confirmed 21,350 georeferenced 120×120, 13-band Sentinel-2 GeoTIFFs covering 624 E-PRTR industrial sites in Europe during 2019; manual smoke/no-visible-smoke labels for all images and 1,437 polygon-annotated smoke masks. Record API metadata lists CC BY 4.0 for the dataset; associated code is separately GPL-3.0. The published split groups all observations at a site into one partition, but it is not temporally independent.
- Recorded the compressed archive size (6,359,411,128 bytes), label/README sizes, estimated extracted array storage, band-contract requirements, annotation limitations and model options in `docs/industrial_smoke_dataset_assessment.md`.

### Decision and safeguards
- Conditional go for a separately named **visible smoke-plume evidence** model using compatible 12-channel Sentinel-2 imagery. No-go for industrial-fire or persistent-thermal-source classification: the labels identify visible smoke, not its cause or temperature.
- No image archive or weights downloaded; no model trained; no application behavior or historical output changed.

### Validation
- Confirmed the metadata API response only (licence, title and file sizes); accessed public record/paper/repository pages and the small README. No archive payload requested.
- `git diff --check` passed. No files staged, committed or pushed.

## 2026-11-17 — Industrial smoke dataset acquisition, models, and app integration

### Data and provenance
- Rechecked Zenodo record 4250706 and the associated paper/code. Confirmed dataset CC BY 4.0 and exact archive sizes. Checked available C: storage (about 287 GB before retrieval) and `.gitignore` rules, then downloaded only to the new ignored `data/raw/industrial_smoke_zenodo_v1/` directory. Published size/MD5 checks passed; SHA-256 values are in `acquisition_manifest.json`.
- Safely extracted into `data/processed/smoke_model_dataset_v002/` (21,350 images + 1,437 JSON masks; 8,017,134,543 extracted bytes). Windows-invalid timestamp colons were mapped to underscores in local filenames; the extraction manifest preserves original archive paths. Initial schema inspection found 24 images at 119×120 and the rest at 120×120, all 13-band uint16; preprocessing reproduces source edge padding.
- Created `data/processed/smoke_model_manifest_v001/manifest.csv` with class/site/date/coordinates/raster provenance and deterministic site-grouped train/validation/test split. Original author split IDs were not in the release; this split is not an exact reproduction. 10 mask JSONs were empty and excluded from segmentation.

### Models and application
- Installed CPU-only PyTorch 2.15.0 and torchvision 0.29.2 in the existing venv; no GPU is available. Trained a compact 12-band CNN on a balanced 4,000-image subset for three epochs, retaining the best validation-loss epoch, and trained a small U-Net on 512 mask/negative samples for two epochs. Checkpoints/configs are local; `.pth` weights are Git-ignored.
- Evaluation outputs: `outputs/smoke_model/run_001/`, `outputs/smoke_model/analysis_v001/`, and `outputs/smoke_model/segmentation_run_001/`. The classifier test set has 3,090 scenes from 94 held-out sites; TinyCNN positive F1 0.458, macro F1 0.676, ROC AUC 0.771, average precision 0.441. Majority accuracy was 0.823 and positive F1 was 0. The U-Net test IoU is 0.318 and Dice 0.482 against manual masks. No paper ResNet-50 reproduction or Jharkhand evaluation is claimed.
- Integrated smoke classification and optional segmentation overlay into `src/thermoscope_app/`; inference requires 13-band uint16 Sentinel-2 GeoTIFF chips with verifiable or explicitly confirmed band order. RGB/four-band inputs are refused. Fire inference and evidence aggregation semantics remain unchanged.
- Added `docs/smoke_model_training_report.md`, CPU model requirements, data acquisition/extraction/preparation/training/evaluation scripts, and model input/split tests. Updated README and image-application design documentation.

### Scientific limitations
- Outputs represent visible-smoke evidence only, not industrial fire, cause, emission verification or thermal-source classification. Scores are uncalibrated.
- Training/evaluation is based on subjective 2019 European labels and masks. The new split is site-held-out but not temporally independent. No Jharkhand smoke test data exists; no regional generalisation claim is made.
- This compact CNN/U-Net feasibility run is not the paper's ResNet-50 reproduction; no ImageNet weights were acquired. Performance is preliminary and short-training/subsampled.

### Validation
- Dataset download MD5/size verification and extraction member/path checks passed. (The first extraction attempt encountered Windows timestamp colons and wrote no image payload; the safe extractor maps these and the complete second extraction succeeded.)
- Smoke-model input tests, app tests, full-suite results, syntax checks, and `git diff --check` will be recorded at final validation below.
- No notebooks, historical pilot outputs, or source project datasets were modified. No files were staged, committed, or pushed.

### Final validation update (2026-11-17)
- Re-ran the complete suite after all smoke model/application edits: `venv\Scripts\python.exe -m unittest discover -s tests -q` — **107 tests passed**.
- Compiled the acquisition, extraction, manifest preparation, training, evaluation, smoke inference and app server modules with `py_compile` — passed.
- Loaded a real held-out 13-band Sentinel-2 TIFF through the trained app inference path with both checkpoints — visible-smoke inference and segmentation overlay returned successfully after explicit band-order confirmation.
- `git diff --check` passed. `git check-ignore -v` confirmed the downloaded archive, extracted imagery, model outputs, and `.pth` weights are ignored by Git.
- No files were staged, committed or pushed. Existing notebook modifications remain present and untouched in this task.

## Final academic demonstration review — completed 2026-11-17
- Reconciled README scope/status with the actual Jharkhand workflow and separate 2019 European visible-smoke model; clarified no verified fire/source labels or Jharkhand model validation.
- Clarified the UI's overall evidence assessment and added the smoke model's European held-out evaluation/domain-shift caveat. Added an extraction step to the reproducibility commands and documented the temporary alternate port.
- Full suite: 107 tests passed. The final local server check on port 8766 returned HTTP 200; health reported fire classifier unavailable, smoke classifier/segmentation available, and no missing evidence inputs. Existing port 8765 process was left untouched.
- Dependency check, local Markdown-link check, Git-ignore checks for dataset/weights, and `git diff --check` passed. No files were staged or committed.

## UI reference adaptation — completed 2026-11-17
- Reworked `app/index.html` to follow the supplied dark geospatial-dashboard visual direction: compact navigation rail, status chips, central scene canvas, metadata overlay and right-side upload/evidence panels.
- Kept the live image upload and API-backed evidence flow. The canvas shows only the uploaded preview; no synthetic map, sample detections, facilities, or combined fire verdict were copied from the mockup.
- Retained explicit separation of visible-smoke classification/segmentation, FIRMS thermal anomalies, OSM context, and the overall evidence-based review. Added input requirements and the European 2019/Jharkhand validation caveat in the dashboard.
- Updated the app design document. Validation: HTML parse passed; app smoke-check available for a browser run; full suite result recorded after completion.
- Final UI validation: `venv\Scripts\python.exe -m unittest discover -s tests -q` — 107 tests passed. Local app on port 8766 returned HTTP 200; health reported smoke model/segmentation available, fire classifier unavailable, and no missing evidence inputs. Dashboard section/input caveat text checks passed; JavaScript syntax and HTML parsing passed. Existing server on port 8765 was not stopped.

## Interactive Jharkhand map selection — completed 2026-11-17
- Added a local SVG map from the configured OSM Jharkhand boundary, with hover coordinates, click-to-center, and drag-to-select rectangles. A drag selection is intentionally queried as a center/radius circle covering the rectangle; the UI discloses that approximation and enforces the existing 10 km search cap.
- Added map-boundary and map-evidence endpoints. Map-only searches are available without uploading an image; FIRMS and OSM result markers use returned local records. OSM representative-point coordinates are included for map rendering.
- Preserved image upload, smoke inference/segmentation, and separate evidence panels. No external map tiles, mock markers, or fire verdicts are used.
- Added boundary, OSM coordinate, and area-search endpoint tests. Python compilation and JavaScript syntax passed; full test result recorded after the final run.
- Final validation: `venv\Scripts\python.exe -m unittest discover -s tests -q` — **109 tests passed**. `py_compile` and Node syntax checks passed; `git diff --check` passed with only pre-existing line-ending notices. In an ephemeral local HTTP server, `/api/map-boundary`, `/map.js`, `/api/health`, and `/api/area-evidence` returned successfully; a sample Jharkhand search found 6 FIRMS records and 14 OSM context features. No persistent server was launched by that endpoint check.
