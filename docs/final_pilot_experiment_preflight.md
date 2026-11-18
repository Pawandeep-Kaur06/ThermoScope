# ThermoScope final pilot experiment: preflight reproducibility report

**Status:** configured and preflighted; the final experiment has **not** been run. The full workflow is intentionally waiting for review of the experiment plan.

- Preflight report generated: `2026-11-16T07:01:14+00:00`
- Experiment processing date: **not run / pending plan review**
- Fixed configuration: [`config/final_pilot_experiment.json`](../config/final_pilot_experiment.json)
- Configuration SHA-256: `e4983c4777fb69815953c81a9015a9cd5ce34f78d4f1c6767ba8ac51f885b4b8`
- Research claim: explainable candidate prioritization only; no validated supervised classifier.

## Inputs and checksums

SHA-256 values were calculated from the local files in this checkout. For large FIRMS inputs, the checksum read was streamed; no data was downloaded or rewritten.

| Input | Bytes | SHA-256 | Status |
|---|---:|---|---|
| `data/raw/archive.csv` | 327,304,467 | `bec91015e4deccd388af92558368bee673235376adc6493dc9ee53f6920ca043` | present |
| `data/raw/nrt.csv` | 608,946,569 | `b2d06fe4fadd2a0d2e2d620a67750c3e84cc5e5b1b09e2eb1059ca4aef4be4fa` | present |
| `data/processed/firms_pilot.csv` | 841,401 | `c4588f65185e459cfeeb1066e4d1d8d0247654a4702aa12f8471f03e763b03f9` | present |
| `data/processed/osm/dhanbad_jharia_bokaro_osm.gpkg` | 2,191,360 | `97b5a1906bacd0a9964529c1cbf385ebb573b05ab34412dfdb2811e453cecbe9` | present |
| `data/raw/osm/geofabrik_eastern-zone_261016.osm.pbf` | 247,316,001 | `6e187ecfc152ba8803badf48bbdbf427cbcb231eb3aa5fff20a851e478017602` | present |
| `data/processed/osm/manifest.json` | 2,511 | `44c1e418af26e9aeb9032e9059a5e8cbd1c9d9bf14abfc07aa6e62214e5e5c80` | present |
| `data/processed/gem/coal_mines_dhanbad_jharia_bbox.json` | 58,892 | `7d952d701419ff770fe03ebff67dc77ee711f1e68c2e1c02ccd60376179ed07b` | present |
| `data/processed/gem/coal_plants_dhanbad_jharia_bbox.json` | 24,227 | `9dbe2c088108baff8d8e7bcfb2c3197a054944745bd419421b906e84763e6fa2` | present |
| `data/raw/gem/manifest.json` | 3,533 | `c6a66c9ba6a28643b8156112166cdfde4f9def342c0512e1f0a0a3320857b900` | present |
| `data/raw/gem/coal_mines_jharkhand.json` | 133,521 | `ab1cc83f911739e77e7c05ec4bb1dc324ba59eb8a9a121123fcd43830e628e1e` | present |
| `data/raw/gem/coal_plants_jharkhand.json` | 118,006 | `0f8c7a2a8eeb9d5dad7c352205fad06f666983cb9f18e7443bdb4453b826202c` | present |
| `data/processed/satellite_investigation/run_20261018T212303Z/scene_metadata.csv` | 11,241 | `f2235cf0980785352bc15019d322edb6be8e499e41dd591d1a4dc9182b885097` | present |
| `config/regions.json` | 2,217 | `cc08e86c1fff27e81ef02d5e22acb6de9b9ab53f875881d9e43be85c21797f52` | present |
| `config/final_pilot_experiment.json` | 10,329 | `e4983c4777fb69815953c81a9015a9cd5ce34f78d4f1c6767ba8ac51f885b4b8` | present |
| `requirements-satellite.txt` | 141 | `cc7b988cb9a64c813a3a18883cf0b1af0b40202cf489b91827dae7fc4e762701` | present |


Additional provenance in the configuration records raw GEM snapshot checksums, the pinned Geofabrik OSM PBF checksum and metadata, plus SHA-256 checksums for the existing Sentinel-2 metadata and all 16 chip/SCL rasters (eight pairs). The existing OSM source is the Geofabrik Eastern Zone snapshot through 2026-10-16 (ODbL 1.0). The GEM files are supplementary coal facility references only. The configured experiment reuses those pinned local satellite chips and makes no STAC request.

## Software environment

- Python: `3.12.4`
- Requirements file: `requirements-satellite.txt` (SHA-256 `cc7b988cb9a64c813a3a18883cf0b1af0b40202cf489b91827dae7fc4e762701`)
- Installed versions: pandas 3.0.6; GeoPandas 1.1.4; Shapely 2.1.2; pyproj 3.8.0; Pyogrio 0.13.0; GDAL runtime 3.12.4; Rasterio 1.5.2; NumPy 2.5.3; Matplotlib 3.11.2; requests 2.34.2.
- Pyogrio/GDAL exposes the read-only `OSM` driver in this environment.

Core pipeline script checksums (SHA-256):

| Script | SHA-256 |
|---|---|
| `src/prepare_firms_pilot.py` | `524559940cd6012c75d45abb4dbb26c94d1447d6b2ae63da0a45f26a2b2e03c0` |
| `src/match_firms_osm_pilot.py` | `f30fdbe4e3f0e5326cdd87c377078351fc984c0c0983616aaaac5c1086a62fe5` |
| `src/engineer_features.py` | `40eb6bae6daa285255b92dc870f6d7a504fd1f2af92ed88a707d225dd1ce8ade` |
| `src/investigate_satellite_pilot.py` | `8b37ebf3b79c669ebe4167a858808c2b203e18425191f8e91173a611eef5a91a` |
| `src/rank_firms_candidates.py` | `934c63f15afa06a6091f4ad54c537b86eee74b09aab3cb40eb7811e230453e12` |
| `src/review_evidence.py` | `3080f99a81f1e312d8a385accfbb51d9a541b4defe3c4ea9adb6bf5795a0f414` |
- Current unit test command `venv\Scripts\python.exe -m unittest discover -s tests`: **51 passed**.

## Validation evidence

| Check | Result | Evidence and scope |
|---|---|---|
| Experiment config parses as JSON and pins the pilot bounds/CRS | PASS | Lightweight local preflight; configuration bounds are 85.75–86.75°E, 23.25–24.00°N, inclusive; distance and recurrence CRS are EPSG:32645. |
| All declared FIRMS, OSM, GEM and configuration files exist and match their recorded SHA-256 values | PASS | Local file existence and SHA-256 verified before writing this report. |
| Prepared FIRMS has 9,220 rows, 184 dates, 0 invalid coordinates, 0 cross-source overlaps, and 0 duplicate removals | PASS | Existing `firms_pilot.csv.quality.json`; prepared period 2026-01-20 to 2026-09-05. |
| Existing pilot spatial-matching summary covers 9,220 pilot observations and reports monotonic 100/250/500/1,000 m threshold counts | PASS | Historical `spatial_matching/firms_pilot_run_001/summary.json`; not a fresh run under the final experiment configuration. |
| Existing feature quality report passes source alignment and past-only recurrence checks | PASS | Historical `feature_engineering/sentinel2_pilot_validation_002/quality_checks.json`; 9,220 rows. |
| Existing Sentinel-2 audit records 8 chips, 11 temporally eligible detections, and 2 usable clear pre-detection samples | PASS | Historical satellite/feature outputs; chip sampling is very sparse and cannot validate fire cause. |
| Existing candidate ranking keeps every detection unknown_unlinked and reports no model metrics | PASS | Historical `candidate_ranking/run_20261018T213107Z/validation.json`. |
| Existing evidence review reports 0 genuinely linkable FIRMS records and 0 labels | PASS | Historical `label_evidence_review/run_20261019T050100Z/validation.json`. |
| Current Python unit tests: 51 passed | PASS | Executed during this preflight on 2026-11-16. |
| Final experiment processing run completed | NOT RUN | Not executed, as requested pending review. |


A separate saved two-tile software validation (2026-10-30) tested tile assignment, boundary membership, uniqueness, CRS, cross-tile recurrence, and completed-run cache reuse. It is **not** a final pilot experiment result and does not establish nationwide readiness.

## Reproduction and known safeguards

The exact PowerShell commands are in the “Frozen final pilot experiment” README section. The run uses existing FIRMS archive/NRT CSVs, the pilot OSM GeoPackage, filtered GEM files, and eight small pre-downloaded Sentinel-2 chip pairs. No network request is needed for the configured experiment.

Checksum-aware output reuse exists for FIRMS preparation and valid GEM snapshots. OSM PBF download validates source size/MD5/SHA, but PBF-to-GeoPackage conversion does not reuse an existing output. Tile checkpoints/resume apply only to tiled matching; the final Dhanbad pilot matcher has no tile cache. Satellite retrieval, feature engineering, candidate ranking, and evidence review create fresh outputs and do not resume/cache completed outputs. Use new run directories and preserve old runs.

The FIRMS quality sidecar and several older run summaries contain machine-specific absolute paths. The new experiment config uses repository-relative paths and fixed hashes; final output manifests should retain relative paths. The experiment JSON is a frozen protocol/manifest, not yet a runtime object consumed by every stage: region bounds/CRS are loaded through `regions.json`, while distance thresholds, grid size, and ranking weights remain script constants. They currently agree with the protocol; the recorded script checksums and tests pin that implementation. Any parameter change must be reflected in a new experiment config version. The satellite selector can pin cells but not STAC item IDs as a CLI option. The final experiment therefore reuses the existing chip run by checksum rather than querying the mutable catalog again. Refreshing imagery would be a separate, reviewed experiment version.

## Output status

The final output tree is proposed under `data/processed/final_pilot_experiment/run_001/` and is not yet created. Its fixed structure is defined in the experiment configuration. Existing datasets, notebooks, historical outputs, and caches were left untouched by this preflight.
