# ThermoScope task tracker

## Current intended project objective
Jharkhand-wide analysis of potential industrial fires and persistent thermal sources using FIRMS, satellite imagery, and OSM context. The Dhanbad–Jharia–Bokaro work remains the developed pilot and case study. Build a genuine image-based CV model only if independently verifiable labels support a defensible target and evaluation.

## Existing completed pilot (historical scope)
- Study area: Dhanbad–Jharia–Bokaro, Jharkhand, India.
- Completed contribution: explainable candidate prioritization and evidence review, not a validated supervised industrial-fire classifier.
- GEM coal-mine and plant records are supplementary context only.
- Proximity, recurrence, and optical imagery are evidence indicators; they do not establish causal source or verified fire labels.
- Preserve the pilot configuration and outputs as a historical benchmark; any India-wide scope/configuration must be versioned separately.

## Current phase
Jharkhand data integration and CV dataset/label feasibility. A first statewide evidence pipeline has run; supervised model development remains blocked by the lack of independent labels and adequate temporally eligible imagery.

## Current state
- The final pilot run exists at `data/processed/final_pilot_experiment/run_001/`.
- Its reproducibility manifest reports `run_status: completed`, 9,220 pilot observations, and about 232 seconds elapsed.
- The run manifest records 51 unit tests and 35 validation checks passed during execution; they have not yet been rerun in the current session.
- No credible verified labels are available; no supervised classifier or performance metrics are claimed.
- The historical lifecycle wording in `config/final_pilot_experiment.json` still says preflight-only. The later completed run and chronology are documented in `docs/final_pilot_experiment_execution_addendum.md`; the pinned config remains unchanged to preserve its recorded checksum.
- Eight evidence-only case studies and a metadata-only Sentinel-2 availability assessment now exist under `data/processed/final_pilot_experiment/`; no imagery was newly downloaded.
- The current India-wide repository audit found 37 local TIFF files across seven Sentinel-2 investigation runs (22 unique content hashes); these are unlabeled small chips/masks, not a training set.
- No verified FIRMS detection-level labels or defensible negatives are available in the pilot evidence review.
- The completed local inventory records eight FIRMS source/derived files and all 37 TIFFs. Raw files report SNPP/SNPP (VIIRS-family inferred, exact collection unverified); raw NRT has four repeated identities; the broad legacy combined table has 288,194 records outside the configured India polygon.
- Six distinct Sentinel-2 item IDs have four-band TIFFs. In run_001, 11/9,220 observations have temporally eligible scenes, two have clear usable spectra, and none is image-labeled.

## Most recent completed tasks
- **Jharkhand statewide feasibility run.** Derived a valid state polygon from the existing OSM PBF; prepared 21,450 archive/NRT FIRMS records; locally filtered 37,046 OSM features; ran tile-specific matching, past-only recurrence, six-cell Sentinel-2 inspection, feature engineering, evidence-only candidate ranking, and a validated visualization package. Results are in `data/processed/jharkhand_analysis/run_001/`, `outputs/jharkhand/run_002/`, and `docs/jharkhand_results.md`. No labels or model were created.
- **CV dataset readiness audit.** Inventoried local Sentinel-2 chips, deduplicated image content by SHA-256 into `data/processed/cv_dataset/manifest.csv`, paired available SCL masks, and recorded all samples as unlabeled. Report: `docs/cv_dataset_report.md`. No model or train/test split was created because credible labels are absent.
- **WorldCover land-cover dataset feasibility plan.** Evaluated label semantics, 2021-to-2026 temporal drift, categorical image alignment, spatial/scene grouping, and storage. Report: `docs/landcover_dataset_plan.md`. Checked full-object size headers for six relevant COGs; downloaded no raster payloads.

## Prior current task (before image-application implementation)
**Blocked — labeled land-cover dataset/model development.** The local dataset contains 20 unique four-band chips, but WorldCover 2021 is temporally mismatched to the 2026 imagery and there are no independent contemporary labels. Next dependencies: a byte-counted COG-window pilot and human-adjudicated, date-appropriate test references; see `docs/landcover_dataset_plan.md`. No model or split has been created.

**Reference-data review workflow completed.** Identified NRSC/ISRO Bhuvan Panchayat SISDP Phase II (1:10,000; mapped 2018–2023) as a candidate independent broad land-cover reference. Exact project access, Jharkhand Phase II export coverage, licence, per-area dates and download size remain to be confirmed. Created a six-location unlabelled review queue and validation script; no reference payloads or labels were created. See `docs/reference_data_strategy.md`.

**Bhuvan access verification completed; acquisition blocked pending written permission and metadata.** Confirmed SSO/Get Data request workflow and Shapefile delivery in the portal manual. Exact Phase II Jharkhand coverage, per-area mapping years and file size remain unverified; general Bhuvan terms restrict copying/derivatives absent prior written authorization. Prepared a request draft; it was not submitted. See `docs/bhuvan_reference_data_access.md` and `data/processed/cv_dataset/reference_source_inventory.csv`.

**Openly licensed CV reference sample acquired.** Selected ESA WorldCover 2021 v200 as a CC BY 4.0 weak reference for broad land-cover classes only. Retrieved six chip-footprint COG windows (3 source tiles) using 1,017,485 bytes of HTTP range responses; saved six source-grid crops totaling 11,766 bytes. CRS, 10 m nominal grid, code domain, WGS84 overlap, checksums and provenance validated. These are not labels for 2026 chips or independent test truth; no model was trained. See `docs/cv_reference_dataset_decision.md`.

**Six-chip segmentation prototype blocked at data-readiness gate.** Nearest-neighbor alignment and SCL masking produced 4,038 weak-label pixels, but 4,036 are in one leakage group and only two in a second; the other groups have none. Built-up/bare support is 49/16 pixels and water is absent. A meaningful geographic validation split cannot be made, so no model or performance metrics were produced. See `docs/cv_prototype_results.md`.

## Upcoming tasks
1. Recover authoritative FIRMS product/query provenance and confirm archive/NRT completeness for Jharkhand; local CSVs do not fully establish product resolution or retrieval coverage.
2. Run a small, byte-counted WorldCover COG-window pilot on selected existing chip locations and assess temporal alignment before creating weak masks.
3. Obtain contemporary independent reference material and human-audit a geographically held-out evaluation subset; record uncertain pixels as ignore/unknown.
4. Expand Sentinel-2 sampling only after target labels and geographic split feasibility are confirmed.
5. If independent labels remain insufficient, complete the project as explainable evidence-based geospatial prioritization rather than unsupported fire classification.

## Status convention
- **Pending** — not started.
- **In Progress** — currently being worked on.
- **Completed** — finished and checked.
- **Blocked** — cannot proceed until a stated dependency is resolved.

## Current task: image upload evidence application — completed
- Added a local-only browser application for GeoTIFF/PNG/JPEG upload, preview, safe file checks, CRS/affine/EXIF metadata extraction, and user-entered coordinates/dates.
- Connected uploads to the existing Jharkhand FIRMS/feature/recurrence outputs, local OSM GeoPackage, and temporally eligible chips from the existing six-chip Sentinel-2 run.
- Kept CV inference explicitly unavailable because credible labels and an independently evaluated model do not exist. Evidence aggregation is separate and cannot issue an industrial-fire/source class prediction.
- Added `docs/image_upload_prediction_design.md`, nine application tests, and README run instructions. Existing datasets, notebooks and historical outputs were preserved; nothing was staged, committed or pushed.

## Current task: industrial-fire CV model — blocked at label/target gate
- Audited all local CV imagery, WorldCover masks, model files, app inference seam, and dependencies. No image-level fire labels, verified controls, model weights, or ML runtime are available locally.
- Discovered a public 21,350-image Sentinel-2 industrial-smoke dataset (CC BY 4.0; 6.36 GB archive) that may support a separate visible-smoke cue, but smoke is not fire and cannot be substituted for the requested classes. No archive or weights were downloaded.
- Added the per-file inventory at `docs/cv_model_dataset_inventory.csv` and the actionable blocker report at `docs/cv_model_development.md`. Existing inference remains explicitly unavailable; tests now verify missing data/model yields unknown rather than a class.
- Next decision needed for a future task: whether to add a separately named smoke-plume evidence model and authorize retrieval of the 6.36 GB archive. A fire classifier still requires independent dated incident-to-image labels and held-out test examples.


## Current task: Industrial smoke dataset assessment — completed
- Verified the Zenodo record, small dataset README, 2020 paper, and associated repository without retrieving the 6.36 GB image archive. Confirmed Sentinel-2 multispectral GeoTIFFs, manual smoke/no-visible-smoke labels, segmentation subset, CC BY 4.0 data licence, and location-grouped split; temporal independence is not established.
- Recommendation: conditional go for a separate visible smoke-plume cue with strict 12-channel Sentinel-2 input validation; no-go as a fire or persistent-thermal-source classifier. No download, training or app behavior change.
- Assessment: `docs/industrial_smoke_dataset_assessment.md`.

## Current task: Industrial smoke model — completed as an experimental smoke-only CV component
- Acquired and checksum-verified the CC BY 4.0 Zenodo archive; extracted 21,350 Sentinel-2 images and 1,437 mask JSONs without overwriting previous data. Verified dimensions/bands/CRS, labels, mask pairing, dates, site groups and absent original split assignment files.
- Created a reproducible site-held-out split, trained a compact 12-band smoke CNN and U-Net, evaluated on held-out European sites, saved model weights/config and provenance-linked evaluation artifacts, and integrated separate smoke inference/overlay into the upload app. The fire classifier remains unavailable; scores are uncalibrated and no Jharkhand generalisation is claimed.
- Report: `docs/smoke_model_training_report.md`. Local source data, extracted images, run outputs and `.pth` weights are Git-ignored. No existing notebooks or historical pilot outputs were changed.

- Final smoke-model validation rerun (2026-11-17): 107 tests passed; model/app syntax and real held-out GeoTIFF inference checks passed; large local data/model artifacts remain ignored.

- **Final academic demonstration review — completed 2026-11-17.** README/UI consistency fixes made; 107 tests passed; app launch and health verified on port 8766. Details: WORKLOG.md.

- **UI reference adaptation — completed 2026-11-17.** Applied the dashboard layout to the live upload/evidence app without copying mock data or unsupported fire verdicts; see WORKLOG.md.

- **Interactive Jharkhand map selection — completed 2026-11-17.** Added local-boundary hover/click/rectangle selection and map-only FIRMS/OSM evidence search. Rectangle results use a clearly disclosed covering radius. See WORKLOG.md.

- Final validation for interactive map: **109 tests passed**; local boundary/evidence routes and sample area search verified; no persistent server or external map service used.
