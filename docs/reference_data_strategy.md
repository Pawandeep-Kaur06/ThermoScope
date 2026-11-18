# Jharkhand reference-data and labelled-sample strategy

## Decision

There is a promising independent reference source for a **broad land-cover segmentation** task, but a labelled dataset is not ready today. The preferred first source to request is NRSC/ISRO Bhuvan Panchayat's **LULC 1:10,000 SISDP Phase II** layer. Its published metadata describes polygon data mapped during 2018–2023 from fused Cartosat-1 and LISS-4 imagery, at 2.5 m source resolution, with four classification levels (7, 27, 41 and 89 classes). The reference sensor and source workflow are independent of this project's 2026 Sentinel-2 chips, but this remains a remotely sensed map rather than field-verified truth. Mapping year varies within the product, and a 3–8 year gap to the existing chips may make change-prone mine surfaces, vegetation, water and settlement edges stale.

The Bhuvan update says Phase II data for 14 states can be requested for research/academic use through **Get Data**; it does not name those states in that notice. A 2025 Department of Space answer confirms Jharkhand institutions accessed Bhuvan 1:10,000 LULC, but does not identify the Phase II version or exact coverage. The manual documents a Bhuvan login, state/district AOI request, request ID and email delivery; it says the Phase II data are delivered as Shapefiles. Bhuvan's general terms restrict copying and derivative works without prior written authorization. Therefore the project must obtain written permission specifically covering local mask derivation/publication before using a delivered dataset. No request has been submitted. See [`docs/bhuvan_reference_data_access.md`](bhuvan_reference_data_access.md) for the access decision and prepared request text.

## Reference sources and intended use

| Source | Status and independence | Potential use | Limitations / decision |
|---|---|---|---|
| Bhuvan Panchayat / NRSC LULC 10K SISDP Phase II | Authoritative NRSC/ISRO product, 2018–2023 mapping; based on fused Cartosat-1 + LISS-4, not the project's Sentinel-2 chips | Candidate per-pixel broad land-cover reference after source-date and class-schema review | Preferred request. Specific Jharkhand Phase II availability, delivery format, licence/terms, date per polygon and file size remain to be confirmed. Not field truth; not industrial-fire labels. |
| JSAC Jharkhand GIS layers | Official state catalog lists mining/industrial wasteland and other GIS layers; current dates, downloadable attributes, accuracy and terms not verified | Possible supplementary dated local reference, if metadata and geometry cover selected chips | Contact JSAC for authoritative layer inventory and metadata. Mining/industrial layer presence alone does not label visible land cover. |
| Bhuvan 1:250,000 LULC 2022–23 / 2023–24 | Official broad-scale land-cover service | Regional context or broad sampling stratification | Too coarse for 10 m Sentinel pixel masks. Do not rasterize it into fine per-pixel truth. |
| Bhuvan 1:50,000 LULC 2015–16 | Official older layer | Historical context only | Too old and coarse for current chip labels. |
| ESA WorldCover 2021 | Open, satellite-derived 10 m map; independent product but derived from Sentinel-1/2 imagery | **Weak/provisional labels only**, e.g. broad bare/built/vegetation context, with source codes retained | Not independent 2026 ground truth; five-year gap; built-up does not mean industrial and bare ground does not mean mine. Do not use as the final independent test truth. |
| OSM, GEM, FIRMS, candidate rankings | Existing project context and observations | Linkage, sampling context, or separate explanatory features | Explicitly prohibited as image labels. None proves visible land cover or causal source. |

Official source links: [Bhuvan announcement of 10K Phase II](https://bhuvan.nrsc.gov.in/updates/bhuvan_nov2023.html), [Bhuvan Panchayat portal and SISDP metadata/service](https://bhuvanpanchayat.nrsc.gov.in/), [Bhuvan Panchayat user manual, including Phase II metadata and Get Data workflow](https://bhuvanpanchayat.nrsc.gov.in/SISDP/BP-usermanual.pdf), [Department of Space / Rajya Sabha answer (7 Aug 2025)](https://sansad.in/getFile/annex/268/AU2207_XpCcS7.pdf?source=pqars), [Jharkhand State GIS](https://gis.jharkhand.gov.in/), and [JSAC layer catalogue](https://jsac.jharkhand.gov.in/pdf/GIS_LAYERS.pdf). The 2025 answer verifies Jharkhand institutions accessed the Bhuvan 1:10,000 layer; it does not prove this project's entitlement to obtain or redistribute data.

## Seed locations and current image chips

The initial review frame is the **six existing `jharkhand_analysis/run_001` four-band chips**, one from each represented state tile (`jharkhand_r00_c02`, `r01_c01`, `r01_c02`, `r01_c03`, `r02_c00`, `r03_c04`). Their chip centers span approximately 83.91–87.39°E and 22.80–25.04°N. This is a manageable geographically distributed seed frame, not a representative probability sample of Jharkhand. These are existing 64×64 chips (about 640 m square each at 10 m; approximately 2.46 km² total footprint). Their 2026 acquisition dates range from 2026-04-24 to 2026-09-03. Five connected scene/geography leakage groups are represented. Most are cloud-affected by their paired SCL summary; only one of the six has a high clear fraction, and a clear optical chip is still not a land-cover label.

The generated `data/processed/cv_dataset/reference_review_register.csv` is an **unlabelled human-review queue**, not a label dataset. Every row is `pending_source_review`; class, reference, confidence and reviewer fields are empty; all split assignments remain `unassigned_unlabelled`. No automatic label approval or label inference occurs. The CSV retains chip hash, scene/date, WGS84 center, tile, SCL context and leakage group for traceability.

Rebuild the register without overwriting an existing file:

```powershell
venv\Scripts\python.exe src\prepare_reference_review_register.py `
  --manifest data\processed\cv_dataset\manifest.csv `
  --chip-root data/processed/jharkhand_analysis/run_001/satellite_investigation/ `
  --output data\processed\cv_dataset\reference_review_register.csv
```

## Per-pixel review workflow

1. Obtain the smallest reference export intersecting the six footprints. Record provider, product/version, URL or request ID, licence/terms, exact mapping/acquisition date per feature, coordinate system, class codebook, download time, byte size and SHA-256. Do not proceed if the source cannot be legally used or its date/legend cannot be resolved.
2. For each image chip, intersect the dated reference polygons with the chip's exact georeferenced pixel grid. Preserve source class codes and source polygons. Rasterize categorical labels at the image grid using an explicit pixel-center or area-coverage rule; do not dominant-class-fill an entire chip.
3. Retain a target label only when the source class is unambiguous at the pixel scale and temporally credible. Pixels crossing class boundaries, source gaps, no-data, mixed polygons or likely change are `ignore/unknown`. Never interpret cloudy SCL pixels as land-cover labels; mark them invalid for image input.
4. Record each reviewed sample/pixel or polygon with source name/URL or stable ID, source acquisition/mapping date and precision, class code/name, confidence rationale, reviewer ID/date, review status, geometry/pixel rule, notes and evidence. Require a human reviewer; use a second reviewer and adjudication for the final test subset. Unresolved disagreements stay unknown.
5. Keep the reference-derived training candidates separate from independently reviewed test truth. WorldCover can only be marked `weak_reference`, never `independent_verified`. Neither OSM/GEM proximity nor FIRMS/ranking can affect the class.
6. Split only after enough reviewed samples exist. Assign connected `geo_scene_leakage_group` groups wholly to one split; also prevent a tile, Sentinel scene, overlapping chip or nearby spatial block from crossing splits. Prefer held-out districts or spatial blocks (with a buffer) for test and a later acquisition window where feasible. Do not assign splits to pending/unlabelled samples.

Proposed initial taxonomy, subject to Bhuvan schema review: **built-up**, **bare/sparse surface**, **vegetated surface**, **cropland**, **water**, and **ignore/uncertain**. These are broad surface classes only. “Built-up” is not “industrial”; “bare” is not “mine”; none is a fire/thermal-source class. Keep Bhuvan's finer codes in source metadata before any grouping. If the map cannot distinguish a class reliably at 10 m or the date gap signals change, leave it unknown.

## Acquisition size and expected value

No data payload was downloaded. The six chips cover about 2.46 km² in total, but Bhuvan's documented request workflow selects state/district units rather than promising an AOI clip. Neither the portal notice nor the manual states the delivered vector archive size. Thus the actual required bytes are **unknown before request**; do not extrapolate a small chip area into a small download. The request should first ask whether an AOI-clipped export is possible and obtain the exact compressed/uncompressed sizes before accepting/downloading. If only district exports are offered, request sizes for the smallest districts covering the six chip windows and download only after checking expected disk use. The expected value is high enough to justify a metadata/access inquiry: a finer independent map could support broad land-cover reference review, but it cannot support industrial/fire classification and its 2018–2023 dates remain a temporal limitation.

WorldCover's existing plan estimated six complete intersecting 3×3° COGs at 701,510,870 bytes (~669 MiB) from response headers (no payload). That is a known alternative source size, but its 2021 map is only weak-label material for 2026 imagery, so it is not the preferred final reference or test truth. No extra imagery is needed to create the current review register.

## Feasibility and minimum defensible alternative

A genuinely independent **broad land-cover** reference dataset is *conditionally achievable* if NRSC/JSAC provide the local SISDP Phase II polygons with per-area mapping dates, class metadata, permitted research use and tractable export size. That does not make it current 2026 ground truth. Before model development, assemble a small set of temporally aligned or manually adjudicated pixels, establish two-reviewer agreement on a geographically held-out subset, and verify adequate samples across independent groups. Current status: six geographically spread image chips, zero credible labels, zero eligible train/validation/test samples; a supervised model and evaluation are not currently justified.

If the reference request is unavailable or dates cannot be aligned, the smallest defensible alternative is a **human-reviewed land-cover reference-agreement / visual interpretation study** on these six chips and a small, documented set of contemporaneous high-resolution reference views, with ambiguous pixels excluded. It may report inter-reviewer agreement and source discrepancies, but should not claim a trained CV classifier. Continue the project's evidence-based thermal candidate prioritization separately; it is not image classification.

## Follow-up update (2026-11-16)

ESA WorldCover 2021 v200 is now available locally as six tiny source-grid reference crops fetched by public COG range requests under CC BY 4.0. They remain weak reference only; no labels were assigned. See `docs/cv_reference_dataset_decision.md` and `data/processed/cv_dataset/reference_source_inventory.csv` for the acquisition amount, observed class codes, checksums and updated model-feasibility decision.
