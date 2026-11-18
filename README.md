# ThermoScope

**AI-Based Detection and Classification of Industrial Fires and Persistent Thermal Sources using NASA FIRMS, OSM & Satellite Data**

ThermoScope is an exploratory computer-vision and geospatial project for investigating satellite-detected thermal anomalies across Jharkhand, India. It brings together NASA FIRMS observations, OpenStreetMap context, satellite imagery, and supplementary Global Energy Monitor (GEM) facility data. Dhanbad–Jharia–Bokaro is the developed pilot. The project combines explainable evidence-based prioritization with an experimental visible-smoke image model; it is not a validated industrial-fire classifier.

## Current status

The project has local FIRMS preparation, OSM matching, feature, satellite-context, evidence-review, candidate-ranking, and image-upload workflows. **There are no verified detection-level fire/source labels and no trained fire/source classifier.** A separate experimental visible-smoke CNN and segmentation model was trained on 2019 European Sentinel-2 scenes; it has not been validated for Jharkhand. OSM/GEM proximity, FIRMS recurrence, and image context are evidence for review, not cause labels.

### Active project scope: Jharkhand

The current scope decision supersedes the India-wide expansion plans documented below: the active study area is the whole state of Jharkhand, with Dhanbad–Jharia–Bokaro retained as the developed pilot. A first state-level run has been completed using existing local FIRMS exports and the existing Geofabrik Eastern Zone OSM PBF. It contains 21,450 prepared FIRMS detections (2026-01-20–2026-09-06), 37,046 tagged OSM features, 14 active processing tiles, and six small Sentinel-2 image/SCL samples. All 19 final package checks passed. Only one FIRMS row has a usable, clear, temporally eligible Sentinel-2 spectral sample; no detection-level labels or Jharkhand-validated fire/smoke model are available. These are exploratory evidence results, not confirmed industrial-fire classifications or model performance. Details are in [the Jharkhand results report](docs/jharkhand_results.md); files and checksums are listed in `outputs/jharkhand/run_002/results_manifest.json`.

The Jharkhand boundary is derived from OSM relation 1960191 in the local 2026-10-16 extract, and is not a legal boundary. The statewide GEM reference files are not available locally; the existing GEM subset is pilot-only and is intentionally not used as state-wide evidence. The small Sentinel sample requires no credentials through the public Earth Search STAC/COG workflow, but retrieval accesses the network. Do not treat its six cells as a training dataset.

To reproduce the analytical stages from the already prepared state FIRMS/OSM inputs, use fresh output directories (the completed run is preserved):

```powershell
$run = "data/processed/jharkhand_analysis/run_002"

python src/match_firms_osm_pilot.py `
  --region jharkhand `
  --firms data/processed/firms_jharkhand_2026.csv `
  --osm data/processed/osm/jharkhand_261016_osm.gpkg `
  --output-dir "$run/spatial_matching"

python src/investigate_satellite_pilot.py `
  --region jharkhand `
  --matching-dir "$run/spatial_matching" `
  --osm data/processed/osm/jharkhand_261016_osm.gpkg `
  --candidate-ranking data/processed/jharkhand_analysis/run_001/candidate_ranking_with_sentinel2/candidate_ranking.csv `
  --max-cells 6 `
  --days-before 30 `
  --output-dir "$run/satellite_investigation"

python src/engineer_features.py `
  --region jharkhand `
  --firms data/processed/firms_jharkhand_2026.csv `
  --osm data/processed/osm/jharkhand_261016_osm.gpkg `
  --matching-dir "$run/spatial_matching" `
  --satellite-dir "$run/satellite_investigation" `
  --output-dir "$run/feature_engineering_with_sentinel2"

python src/rank_firms_candidates.py `
  --features "$run/feature_engineering_with_sentinel2/feature_table.csv.gz" `
  --no-label-evidence `
  --output-dir "$run/candidate_ranking_with_sentinel2"

python src/create_jharkhand_outputs.py `
  --run-dir "$run" `
  --output-dir outputs/jharkhand/run_003
```

These commands do not download FIRMS or OSM data, but the satellite stage makes small public STAC/COG requests. Use a new, unused `$run` and report output directory for every rerun. To regenerate the state FIRMS table from the local archive/NRT files, pass `--region jharkhand` and a new `--output` path to `src/prepare_firms_pilot.py`. To rebuild the filtered state OSM GeoPackage without a download or Overpass query, pass `--process-only --region jharkhand`, the existing PBF via `--pbf`, and new `--output`/`--manifest` paths to `src/fetch_osm_pilot.py`. Matching can resume valid tile checkpoints with the same `--output-dir` and `--resume`; other stages must use fresh output paths.

Current local inputs and outputs are intentionally excluded from Git. A fresh checkout needs the inputs listed below before the corresponding pipeline commands will run.

## Data sources

| Source | Role in ThermoScope | Access and limits |
| --- | --- | --- |
| [NASA FIRMS](https://firms.modaps.eosdis.nasa.gov/) | Active-fire and thermal-anomaly observations with acquisition time, coordinates, FRP, brightness, confidence, and sensor attributes. | `src/prepare_firms_pilot.py` validates local archive and NRT CSV exports, filters to the pilot, and records archive/NRT provenance while deduplicating overlaps. It does not download FIRMS data. FIRMS detections are sensor observations, not source-cause labels. VIIRS and MODIS footprint scale, cloud/smoke obstruction, and confidence must be considered. |
| [OpenStreetMap](https://www.openstreetmap.org/) / [Geofabrik](https://download.geofabrik.de/) | Mapped industrial/mining land use, facilities, extraction areas, power generation, transmission, and other infrastructure. | `fetch_osm_pilot.py` uses a pinned Eastern Zone PBF and filters it locally to the pilot. It does not use Overpass. The source extract is about 235.8 MiB when downloaded. OSM is an incomplete, time-varying snapshot; attribution and ODbL terms apply. Proximity does not prove causality. |
| [GEM Global Coal Mine Tracker](https://globalenergymonitor.org/projects/global-coal-mine-tracker/) and [Global Coal Plant Tracker](https://globalenergymonitor.org/projects/global-coal-plant-tracker/) | Supplementary coal-mine and coal-plant facility references. | Retrieved from the GEM Assets API for Jharkhand, then filtered to the pilot. GEM is coal-sector coverage only and does not represent all industrial assets or incident history. It is not a label source. |
| [Sentinel-2 L2A via Earth Search STAC](https://earth-search.aws.element84.com/v1/api.html) | Optical land-surface context around selected recurring FIRMS grid cells. | The script searches public STAC metadata and reads small public COG image windows; no credentials are required for the current path. Visible bands are 10 m and SWIR is 20 m. Sentinel-2 has no thermal band; date, cloud, and spatial mismatch means an image cannot verify a brief FIRMS fire. |

The FIRMS pilot bounding box is 23.25–24.00°N, 85.75–86.75°E. The OSM local extract is saved at `data/raw/osm/geofabrik_eastern-zone_261016.osm.pbf`; its provenance, size, and filtering details are in `data/raw/osm/README.md`.

## Shared region configuration

`config/regions.json` is the central region registry. The Dhanbad–Jharia–Bokaro pilot retains its historical inclusive bounding box and EPSG:32645. India uses a two-part domain: the existing rectangle remains as the stable regular tile-grid envelope, while FIRMS membership must also fall inside the configured Natural Earth India polygon. The rectangle is not treated as the country boundary. India declares `utm_per_tile`, because nationwide distances and 250 m grids must be computed in local projected tiles.

### India boundary source and preparation

The India polygon is from [Natural Earth Admin-0 Countries, India point-of-view theme](https://www.naturalearthdata.com/downloads/10m-cultural-vectors/10m-admin-0-countries/), version 5.1.1 at 1:10m scale. Natural Earth documents the alternate India POV and its disputed-boundary policy; its map data is [public domain](https://www.naturalearthdata.com/about/terms-of-use/). The pinned source is the 4.9 MB `ne_10m_admin_0_countries_ind.zip` from NACIS CDN. Its SHA-256 is `36a54ee97a509325e98eb44fd91bc7e53b0c5139cf10039918042bbd64102192`; the processed boundary checksum and retrieval metadata are in `data/processed/boundaries/manifest.json` (generated data remains ignored by Git).

Prepare it once with `python src/prepare_country_boundary.py --download`. This checks the pinned archive size and checksum, selects `ADMIN == India`, converts to WGS84 GeoJSON, checks polygon validity, and writes a provenance manifest. To rebuild from the local archive without network access, use `python src/prepare_country_boundary.py --process-only`. Existing output files are treated as a cache only when their checksums agree; otherwise the script stops and asks for a new output path. The archive is only a small administrative boundary source; this command does not access FIRMS or OSM datasets.

Boundary membership uses a polygon `covers`/point-intersection test, so points exactly on the mapped country outline are retained. The Natural Earth polygon is a generalized cartographic boundary, not a legal cadastral definition; it follows Natural Earth's India POV for contested borders and has scale-related positional limits, especially near small islands and complex borders. Keep boundary-near detections traceable and interpret their inclusion with that uncertainty in mind.

When regional outputs from adjoining tiles are combined, use the stable `firms_observation_id` field to deduplicate detections on shared edges. Region definitions should use inclusive minima and exclusive maxima for adjacent tiles, except the outermost edge; the existing pilot preserves inclusive maxima for compatibility. The same observation ID is stable across regions because it derives from the normalized FIRMS observation identity.

The India entry uses a fixed `regular_latlon` grid anchored at its southwest bound, with 3° longitude × 3° latitude tiles and IDs such as `india_r04_c03`. Tile row and column indices are stable as long as the configured extent, origin, and tile dimensions remain unchanged. West/south edges are inclusive; east/north edges are exclusive, except at the outer region edge. A point on an internal tile edge is assigned to the tile to its east or north, so it has one owner. Each tile selects UTM from its center. OSM reads are windowed to that tile plus the 1 km match buffer, then projected into the same tile CRS. Result rows retain `region_id`, `tile_id`, `distance_crs`, and `firms_observation_id`.

Tile-specific distances are stored in metres and are comparable across rows as distances, while the CRS identifier identifies each row's projection. The 250 m recurrence key uses one configured region grid (`EPSG:6933` for India) and is calculated after all tile matches are combined. It is independent of tile ID/CRS, so observations in the same recurrence cell across an internal tile edge share history. Recurrence is calculated by acquisition date, using only strictly earlier dates; same-day observations do not contribute. OSM buffer reads can repeat the same mapped feature across tile windows, but they do not duplicate FIRMS observations; tile-level OSM read counts are therefore reported as appearances and may overlap.

Tiled matching validates that every in-region row received one tile, tile CRS matches the configured tile, output row IDs and stable observation IDs are unique, and the combined row count equals assigned detections. The run's `summary.json` records tile bounds, CRS, row counts, and OSM read counts. Feature engineering independently validates tile assignment, per-tile CRS, global recurrence grid IDs, FIRMS source alignment, and strictly earlier recurrence dates.

The India tile envelope intentionally includes some non-India area to retain stable tile IDs; the country polygon excludes those observations before processing. The current pilot OSM GeoPackage covers only Dhanbad–Jharia–Bokaro; India-tiled matching must be pointed at a prepared nationwide OSM GeoPackage. No national FIRMS or OSM input is bundled or fetched by this workflow.

### Controlled multi-tile validation trial

The current local data supports a real, bounded trial on adjacent tiles `india_r05_c05` and `india_r05_c06` (shared edge 86.1°E). Selection favors existing prepared FIRMS observations and local OSM coverage, and the adjacent pair exercises cross-tile matching/recurrence. In the current workspace, `firms_pilot.csv` has 9,220 observations inside the India polygon: 1,335 in `india_r05_c05` and 7,885 in `india_r05_c06`, across 184 acquisition dates. 126 observations lie within roughly 500 m of the shared tile edge; 2 recurrence grid cells contain observations from both tiles (11 observations total). These are local pilot-data counts, not nationwide statistics.

The trial uses `data/processed/firms_pilot.csv`, `data/processed/osm/dhanbad_jharia_bokaro_osm.gpkg`, the local Natural Earth boundary, and optional filtered GEM/Sentinel-2 references already on disk. The GeoPackage contains 7,574 point, 225 line, and 534 multipolygon features, but its mapped extent is the pilot area, not the two full India tiles. This is enough to validate matching for the pilot detections in these tiles, but OSM context can be incomplete near the pilot bbox edges and elsewhere in the tile envelopes. The existing eastern-zone PBF is not automatically converted for this trial. Do not interpret this as validation of India-wide OSM coverage.

Run the prepared-data trial; it creates a dedicated timestamped run directory under ignored `data/processed/multi_tile_validation/`, runs only the selected tiles, then engineers features and writes `trial_validation.json` with elapsed time, sampled peak run-directory usage, final file sizes, observation counts, tile status, cache hits, and validation results:

```powershell
venv\Scripts\python.exe src/run_multitile_trial.py `
  --tiles india_r05_c05 india_r05_c06
```

For an interrupted run, pass the same directory printed on the first invocation and add `--resume`:

```powershell
venv\Scripts\python.exe src/run_multitile_trial.py `
  --run-dir data/processed/multi_tile_validation/run_YYYYMMDDTHHMMSSZ `
  --tiles india_r05_c05 india_r05_c06 --resume
```

The trial checks India polygon membership, deterministic tile IDs, that only requested tiles are present, unique observation IDs, each tile's configured projected CRS, recurrence recomputed from the combined selected-tile observations, and whether recurrence cells cross the tile edge. A repeat completed run can reuse checksum-valid tile checkpoints and feature artifacts when inputs and feature code are unchanged. Peak disk usage is sampled every 100 ms, so a shorter transient spike may be missed. Interrupted feature engineering is preserved and requires a new run directory because that stage does not yet checkpoint its work.

These checks validate the local pilot slice plus synthetic boundary/resumption cases. They do not establish national coverage or nationwide readiness. If the pilot FIRMS/OSM files are absent on another checkout, the smallest next step is to supply the prepared FIRMS pilot CSV and pilot GeoPackage locally; the trial intentionally does not fetch them.

### Local image upload application

ThermoScope includes a local browser application with an interactive Jharkhand boundary map, image upload/preview, metadata extraction, and local FIRMS, OSM, recurrence, and stored Sentinel-2 context. Hover the map for coordinates, click to choose a search center, or drag a rectangle; evidence search uses the circle that covers a rectangle, not an exact polygon query. FIRMS/OSM map markers are drawn from the local records returned for that search. A separate satellite-view panel loads Esri World Imagery tiles centered on the selected Jharkhand coordinates; imagery date and resolution vary by location, and it is contextual imagery rather than fire evidence. The map boundary and FIRMS/OSM evidence remain local. A separate experimental model provides **visible-smoke image cues** on compatible Sentinel-2 multispectral chips. Optional segmentation shows a predicted smoke mask. Neither output classifies industrial fires or persistent thermal sources. FIRMS thermal-anomaly evidence, OSM industrial-context evidence, and the overall human-review assessment are presented separately from the image-model output.

Launch from the repository root:

```powershell
venv\Scripts\python.exe -m src.thermoscope_app.server
```

Then open `http://127.0.0.1:8765`. The server binds to the local machine only. GeoTIFF, PNG, and JPEG uploads up to 25 MiB are previewed; GeoTIFF transform/CRS and JPEG EXIF GPS are read when present. Enter coordinates and date manually when metadata is missing. Uploads are held in memory and are not saved. FIRMS, OSM, and reference evidence comes from the existing local Jharkhand run. The optional Esri World Imagery preview loads map tiles from Esri and sends tile locations to that provider; no FIRMS/OSM datasets or uploaded images are sent. Smoke inference accepts only compatible 13-band `uint16` Sentinel-2 GeoTIFF chips between 90 and 120 pixels per side. Named band descriptions are checked; otherwise the user must confirm the published Sentinel-2 band order. RGB, JPEG/PNG and existing four-band ThermoScope chips are not passed to the model. Full design, evidence timing rules, and limitations are documented in [the image upload application design](docs/image_upload_prediction_design.md) and [the smoke-model training report](docs/smoke_model_training_report.md).

If port 8765 is already occupied, pass `--port` with an available local port, for example `venv\Scripts\python.exe -m src.thermoscope_app.server --port 8767`, then open `http://127.0.0.1:8767`.

The local smoke model weights are Git-ignored. This checkout has `models/thermoscope_smoke_tiny_v1.pth` and `models/thermoscope_smoke_unet_v1.pth`; if weights are absent, the app reports smoke inference unavailable. The model score is uncalibrated and its labels describe visible smoke in 2019 European scenes, not fires or Jharkhand performance.

### Industrial smoke model data and training

The Zenodo dataset is licensed CC BY 4.0 and includes 21,350 Sentinel-2 scenes (3,750 visible-smoke positive and 17,600 no-visible-smoke labels) plus 1,437 manual smoke-mask annotations. The downloaded archive is 6.36 GB; extracted files occupy about 8.02 GB. No original split-ID manifest is included, so ThermoScope uses a deterministic, site-held-out split and does not claim to reproduce the paper's exact ResNet-50. The current local model is a small CPU-trained 12-band CNN plus a compact smoke-mask U-Net. Evaluation is against the dataset's manually assigned smoke labels only. See [training report](docs/smoke_model_training_report.md).

To repeat training from verified local data, first ensure the ignored dataset archive has been acquired and extracted, then run from the repository root:

```powershell
venv\Scripts\python.exe -m pip install --extra-index-url https://download.pytorch.org/whl/cpu -r requirements-smoke-model.txt
venv\Scripts\python.exe src\extract_industrial_smoke_dataset.py --raw-dir data\raw\industrial_smoke_zenodo_v1 --output-dir data\processed\smoke_model_dataset_v003
venv\Scripts\python.exe src\prepare_smoke_dataset.py --dataset-dir data\processed\smoke_model_dataset_v003 --output-dir data\processed\smoke_model_manifest_v002
venv\Scripts\python.exe -m src.train_smoke_model --manifest data\processed\smoke_model_manifest_v002\manifest.csv --dataset-dir data\processed\smoke_model_dataset_v003 --output-dir outputs\smoke_model\run_002 --model-path models\thermoscope_smoke_tiny_v2.pth --epochs 3 --batch-size 2 --max-train-images 4000
venv\Scripts\python.exe -m src.train_smoke_segmentation --manifest data\processed\smoke_model_manifest_v002\manifest.csv --dataset-dir data\processed\smoke_model_dataset_v003 --output-dir outputs\smoke_model\segmentation_run_002 --model-path models\thermoscope_smoke_unet_v2.pth --epochs 2 --batch-size 2 --max-positive 256
```

To select another compatible local state run, pass `--firms`, `--osm`, `--features`, and `--satellite-metadata` paths to the server command. Date-only metadata requires Sentinel-2 scenes to be from a strictly earlier calendar day; same-day intraday order is not assumed.

## Pipeline stages

1. **Prepare FIRMS input.** `src/prepare_firms_pilot.py` streams local archive and NRT CSV exports, validates coordinates and core fields, filters detections to the pilot bounds, removes duplicate observation records, and writes a quality report. It does not download the exports.
2. **Fetch GEM references** (`src/fetch_gem_references.py`) for Jharkhand and create pilot-bounds subsets. GEM is optional supplementary context.
3. **Acquire/filter OSM** (`src/fetch_osm_pilot.py`) from the regional Geofabrik PBF locally. The script preserves OSM tags and geometries in a GeoPackage. It does not query Overpass.
4. **Match FIRMS to OSM** (`src/match_firms_osm_pilot.py`) from the prepared CSV. The Dhanbad pilot uses UTM zone 45N (EPSG:32645); India mode assigns observations to stable tiles, reads the relevant OSM window, and uses a local UTM CRS per tile. FIRMS provenance is retained; statuses indicate mapped context only.
5. **Inspect satellite context** (`src/investigate_satellite_pilot.py`) by selecting up to eight representative recurring cells (the four prior examples plus additional high-recurrence cells) and retrieving small Sentinel-2 windows with aligned SCL masks. Catalog searches and item checks exclude scenes later than each cell's latest FIRMS date.
6. **Engineer features** (`src/engineer_features.py`) from an explicitly selected matching run and satellite run, including thermal, past-only recurrence, OSM/GEM context, and only pre-detection, SCL-clear Sentinel-2 samples. If `--satellite-dir` is omitted, the latest compatible local satellite run is discovered; pass it explicitly for reproducibility.
7. **Assess label readiness** (`src/assess_label_evidence.py`) by keeping external event evidence separate from unlinked FIRMS rows and producing a manual review ranking. The ranking is not a classifier or probability.
8. **Rank candidates for manual review** (`src/rank_firms_candidates.py`) with explicit thermal, strictly past recurrence, mapped OSM-context, and available Sentinel evidence. Every detection remains `unknown_unlinked`; the score is not a probability or model output.
9. **Review external evidence** (`src/review_evidence.py`) to create a timestamped source inventory, event register, date-only overlap audit, and unresolved human review queue. Event acceptance and detection-link review are separate; neither silently assigns a FIRMS label.

## Repository layout

```text
src/                         Acquisition, spatial matching, feature, and evidence scripts
data/raw/                    Local source downloads (ignored by Git)
data/processed/              Local prepared data and timestamped runs (ignored by Git)
notebooks/                   Exploratory notebooks; local cache is ignored
models/                      Smoke-model configs tracked; local weight files ignored by Git
outputs/                     Local generated figures and reports (ignored by Git)
requirements-satellite.txt   Pinned Python dependencies for the current scripts
```

## Setup

Python 3.12 is the version used by the current project environment. From the repository root in PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements-satellite.txt
.\.venv\Scripts\python.exe -m pip install --extra-index-url https://download.pytorch.org/whl/cpu -r requirements-smoke-model.txt
```

The current checkout's existing environment is named `venv`; its launch command is `venv\Scripts\python.exe -m src.thermoscope_app.server`. The setup commands above create a fresh `.venv` for another checkout; use `\.venv\Scripts\python.exe -m src.thermoscope_app.server` there.

`pyogrio` is listed directly because the OSM conversion script imports it and requires its GDAL OSM read driver. The current environment was checked with pyogrio 0.13.0 and GDAL runtime 3.12.4. The scripts use Python's standard library for HTTP downloads except the Sentinel-2 workflow, which uses `requests`. The installed Pyogrio/GDAL build must expose the `OSM` read driver. No separate `ogr2ogr` command or OSMnx dependency is used by the regional OSM pipeline. OSMnx appears only in exploratory notebook experiments.

The pipeline scripts do not require Jupyter or OSMnx. The exploratory notebooks use OSMnx, so install it separately only if you intend to run those notebook experiments; notebook cache files are local and ignored.

## Running the scripts

Run commands from the repository root. The scripts do not need notebook execution.

```powershell
# Prepare a pilot-only FIRMS table from downloaded NASA archive/NRT CSVs.
# Required input columns: latitude, longitude, acq_date, acq_time, satellite, instrument.
# scan and track are used as additional deduplication keys when present.
.\.venv\Scripts\python.exe src/prepare_firms_pilot.py `
  --archive data/raw/archive.csv `
  --nrt data/raw/nrt.csv `
  --output data/processed/firms_pilot.csv

# The pilot remains the default. The same script can prepare a bounded India
# extent without overwriting any existing file (not run here):
.\.venv\Scripts\python.exe src/prepare_firms_pilot.py `
  --region india `
  --archive data/raw/archive.csv `
  --nrt data/raw/nrt.csv `
  --output data/processed/firms_india.csv

# Matching and feature-engineering accept the same --region / --region-config
# options. The India matcher requires a prepared nationwide OSM GeoPackage;
# no national source is downloaded by these commands.

# Optional: fetch state-filtered GEM records and pilot subsets (network required).
.\.venv\Scripts\python.exe src/fetch_gem_references.py

# Download the pinned ~235.8 MiB OSM PBF and filter it locally.
# If the PBF is already present and only the GeoPackage is missing, use --process-only.
.\.venv\Scripts\python.exe src/fetch_osm_pilot.py --download

# Match the prepared pilot CSV. Choose a new output path for each run.
.\.venv\Scripts\python.exe src/match_firms_osm_pilot.py `
  --region dhanbad_jharia_bokaro `
  --firms data/processed/firms_pilot.csv `
  --osm data/processed/osm/dhanbad_jharia_bokaro_osm.gpkg `
  --gem-dir data/processed/gem `
  --output-dir data/processed/spatial_matching/firms_pilot_run_001

# India tile command template; requires a pre-existing India-wide FIRMS file
# and an OSM GeoPackage for India. This command was not run during framework work.
.\.venv\Scripts\python.exe src/match_firms_osm_pilot.py `
  --region india `
  --firms data/processed/firms_india.csv `
  --osm data/processed/osm/india_osm.gpkg `
  --output-dir data/processed/spatial_matching/india_tiled_run_001

# Feature-engineer the combined tile match output, verifying tile IDs, CRS values,
# stable observation IDs, and one global past-only recurrence grid.
.\.venv\Scripts\python.exe src/engineer_features.py `
  --region india `
  --firms data/processed/firms_india.csv `
  --osm data/processed/osm/india_osm.gpkg `
  --matching-dir data/processed/spatial_matching/india_tiled_run_001 `
  --output-dir data/processed/feature_engineering/india_tiled_run_001

# Retrieve/update imagery for four known cells plus four more recurring cells.
# Scene lookup is bounded to small chips and up to 30 days before each cell's
# latest FIRMS acquisition; an aligned SCL mask is saved for pixel cloud checks.
.\.venv\Scripts\python.exe src/investigate_satellite_pilot.py `
  --matching-dir data/processed/spatial_matching/firms_pilot_run_001 `
  --max-cells 8 --days-before 30 `
  --output-dir data/processed/satellite_investigation/sentinel2_pilot_run_001

# Engineer features from that exact matching run and satellite run.
.\.venv\Scripts\python.exe src/engineer_features.py `
  --region dhanbad_jharia_bokaro `
  --firms data/processed/firms_pilot.csv `
  --osm data/processed/osm/dhanbad_jharia_bokaro_osm.gpkg `
  --gem-dir data/processed/gem `
  --matching-dir data/processed/spatial_matching/firms_pilot_run_001 `
  --satellite-dir data/processed/satellite_investigation/sentinel2_pilot_run_001 `
  --output-dir data/processed/feature_engineering/firms_pilot_run_001

# Create a transparent evidence-priority baseline, not a supervised classifier.
# Defaults to the latest feature table and label-evidence assessment if omitted.
.\.venv\Scripts\python.exe src/rank_firms_candidates.py `
  --features data/processed/feature_engineering/firms_pilot_run_001/feature_table.csv.gz

# Build a dated evidence inventory and human-review queue from the latest pilot features.
# This reads existing local data only; it does not download sources or create labels.
.\.venv\Scripts\python.exe src/review_evidence.py --repo .

# Append a human decision to that run's audit log. Event review does not accept a detection link.
.\.venv\Scripts\python.exe src/review_evidence.py `
  --review-run data/processed/label_evidence_review/run_20261018T214049Z `
  --evidence-id akashvani_dhanbad_warehouse_2026_01_22 `
  --scope event --decision unresolved --reviewer "Your name" `
  --reason "Need a precise site location before considering any FIRMS link." `
  --source-reference https://newsonair.gov.in/jharkhand-massive-fire-engulfs-electricity-department-warehouse-in-dhanbad/
```

The default FIRMS preparation output is `data/processed/firms_pilot.csv`; its adjacent
`firms_pilot.csv.quality.json` report records source row counts, pilot retention,
coordinate validation, missing values, date coverage, and duplicate/overlap
counts. Pass `--region <id>` to select another entry from `config/regions.json`;
the default remains `dhanbad_jharia_bokaro`, and the default output is named
`firms_<region-id>.csv` for non-pilot regions. The quality report records region
metadata and inclusive/exclusive bounds. Outputs are created only at new paths; select another `--output` path
if either file already exists. The input CSVs should be standard FIRMS archive
and NRT exports with a header row, WGS84 decimal-degree `latitude` and
`longitude`, acquisition date/time, satellite, and instrument columns. Optional
FIRMS attributes are preserved, and fields absent from one source remain blank.
For duplicate identity, the script uses coordinates, acquisition date/time,
satellite, instrument, and scan/track when available. Archive rows are canonical
for overlaps; `firms_sources` and `duplicate_record_count` retain provenance.
This creates a new pilot-only table; it does not replace `india_combined.csv` or
rewrite earlier matching/feature runs. Matching assigns `firms_source_row` by
row position in the `--firms` input, and feature engineering must receive that
same CSV again to verify source attributes and archive/NRT provenance. The
matching and feature output directories must be new paths.

Unlike `india_combined.csv`, which contains the earlier India-filtered concat
and has no archive/NRT provenance column, `firms_pilot.csv` is already limited
to the pilot, removes duplicate observations, and includes `firms_sources` and
`duplicate_record_count`. The old notebook marked every NRT `type` as `-1`;
this preparation keeps a missing NRT-only `type` blank and identifies its source
with `firms_sources` instead. The matching stage adds row IDs relative to this
prepared file, so do not pair a match run with a different FIRMS CSV.

The data-acquisition commands require network access. Sentinel-2 STAC/COG access and GEM's current API path use no credentials. OSM acquisition downloads the full pinned regional extract, not just the pilot area; local filtering reduces the processed study-area data. Do not pass `--overwrite` to the GEM or OSM scripts unless replacing their generated targets is intentional. The OSM script refuses existing targets without that explicit option.

**Run-path note:** the connected FIRMS → matching → satellite-investigation → feature commands above pass run directories explicitly and do not depend on historical run IDs. The satellite script accepts `--matching-dir`, `--max-cells`, `--days-before`, and explicit `--cell-ids`; feature engineering accepts a satellite run through `--satellite-dir` or discovers the latest compatible local run when omitted. The separate label-evidence script retains historical input assumptions.

## Frozen final pilot experiment

The research scope is fixed to Dhanbad–Jharia–Bokaro. The machine-readable protocol is [config/final_pilot_experiment.json](config/final_pilot_experiment.json), and its pre-execution input checksums, software versions, and known limitations are recorded in the historical [preflight report](docs/final_pilot_experiment_preflight.md); completed-run checks and hashes are in `data/processed/final_pilot_experiment/run_001/validation/reproducibility_manifest.json`. No national processing is part of this experiment. This JSON is a frozen protocol/manifest; region bounds and CRS are consumed from `regions.json`, while the current matching thresholds, recurrence grid size, and ranking weights remain code constants. Their agreement is checked and the scripts are SHA-256 pinned in the preflight report; parameter changes require a versioned config update.

The configured run root is `data/processed/final_pilot_experiment/run_001/`. All output folders must be new. Do not rerun a stage into an existing folder; choose a new run root and update the manifest instead. These commands reproduce the completed `run_001` workflow. That run used existing local FIRMS, OSM, GEM, and Sentinel-2 inputs and did not download data. Do not rerun into `run_001`; use a new run ID to preserve it. The eight existing 640 m Sentinel-2 chips are reused from a checksum-pinned run, without a STAC request.

```powershell
# 1. Prepare the local archive/NRT inputs. The output uses a fresh final-run path.
.\.venv\Scripts\python.exe src/prepare_firms_pilot.py `
  --archive data/raw/archive.csv `
  --nrt data/raw/nrt.csv `
  --region dhanbad_jharia_bokaro `
  --output data/processed/final_pilot_experiment/run_001/input/firms_pilot.csv

# 2. Match FIRMS to the existing local OSM/GEM references.
.\.venv\Scripts\python.exe src/match_firms_osm_pilot.py `
  --region dhanbad_jharia_bokaro `
  --firms data/processed/final_pilot_experiment/run_001/input/firms_pilot.csv `
  --osm data/processed/osm/dhanbad_jharia_bokaro_osm.gpkg `
  --gem-dir data/processed/gem `
  --output-dir data/processed/final_pilot_experiment/run_001/spatial_matching

# 3. Build features using the existing checksum-pinned Sentinel-2 chips.
# The imagery run is referenced in place and is not re-downloaded or overwritten.
.\.venv\Scripts\python.exe src/engineer_features.py `
  --region dhanbad_jharia_bokaro `
  --firms data/processed/final_pilot_experiment/run_001/input/firms_pilot.csv `
  --osm data/processed/osm/dhanbad_jharia_bokaro_osm.gpkg `
  --gem-dir data/processed/gem `
  --matching-dir data/processed/final_pilot_experiment/run_001/spatial_matching `
  --satellite-dir data/processed/satellite_investigation/run_20261018T212303Z `
  --output-dir data/processed/final_pilot_experiment/run_001/features

# 4. Build a fresh evidence inventory/review queue and candidate-priority table.
.\.venv\Scripts\python.exe src/review_evidence.py `
  --features data/processed/final_pilot_experiment/run_001/features/feature_table.csv.gz `
  --output-dir data/processed/final_pilot_experiment/run_001/evidence_review

.\.venv\Scripts\python.exe src/rank_firms_candidates.py `
  --features data/processed/final_pilot_experiment/run_001/features/feature_table.csv.gz `
  --labels-dir data/processed/label_evaluation/run_20261018T205757Z `
  --output-dir data/processed/final_pilot_experiment/run_001/candidate_ranking

# 5. Validate the completed run, run tests/syntax checks, and write provenance.
.\.venv\Scripts\python.exe src/finalize_pilot_experiment.py `
  --run-root data/processed/final_pilot_experiment/run_001
```

The explicitly named label-readiness directory is a historical zero-label assessment (9,220 source rows); it is supplied only as a transparent status reference because the ranking CLI reads `label_readiness.json`, not the newer evidence-review schema. The new evidence review remains a separate, current run. Do not interpret the historical reference as newly adjudicated labels.

The run should preserve the preparation quality/cache sidecars, matching summary/CSV/GeoPackage/tables/figures, feature schema/definitions/missingness/quality report/plots, ranking evidence/category tables/validation/plots, evidence inventory/review queue, and an input/software/validation manifest under `run_001/validation/`. That manifest must reference the existing satellite run and its pinned checksums; satellite files are intentionally not duplicated. The post-run manifest is `data/processed/final_pilot_experiment/run_001/validation/reproducibility_manifest.json`; it records inputs, output hashes, software versions, runtime, disk use, and validation results. The adjacent satellite reference manifest identifies the reused imagery files by checksum.

For thresholds use 100, 250, 500 and 1,000 m; report general transmission infrastructure separately from the candidate-ranking industrial-context role set. Recurrence is a 250 m EPSG:32645 grid using strictly earlier acquisition dates only; same-day rows do not contribute. Sentinel-2 features require an acquisition at or before the exact FIRMS timestamp and a valid SCL class (4, 5 or 6); unavailable/cloudy/future pixels remain missing. Candidate ranking uses the transparent fixed rule definition in the configuration; all observations remain `unknown_unlinked` absent separately verified event linkage.

### Cache and reproducibility limits for this run

FIRMS preparation and valid GEM snapshots can reuse checksum-verified local outputs. The pilot (non-tiled) OSM matcher has no checkpoint cache; its `--resume` option is for tiled runs. This experiment reuses the pinned satellite chips; a fresh satellite retrieval has no cache. Feature engineering, evidence review, and ranking write new outputs and must be rerun into new directories. OSM itself is reused from the local GeoPackage; its PBF-to-GeoPackage conversion is not an output cache. Use the exact input files/configuration hashes in the preflight and post-run manifests. Do not rely on implicit “latest run” discovery.

## Current pilot results

These figures summarize existing local run outputs; they are exploratory and are not model performance metrics.

| Measure | Current result |
| --- | --- |
| FIRMS detections in pilot | 9,220 across 184 acquisition dates, 2026-01-20 to 2026-09-05 |
| FIRMS 250 m analysis cells | 1,063; grid cells are not verified physical sources |
| Selected OSM features | 8,333 in the filtered GeoPackage; 8,206 features used in the matching run's relevant context roles |
| FIRMS with relevant OSM feature within 250 m | 8,013 detections; statuses: 7,679 proximity candidates, 334 ambiguous, 1,207 with no relevant OSM feature within 250 m |
| GEM supplementary pilot records | 96 mine/plant records from the filtered references |
| Sentinel-2 | Eight small chips retrieved for representative cells in validation; 530 detections have a chip available for context, 11 have a temporally eligible scene, and 2 have usable pre-detection SCL-screened samples. Missing, post-detection, cloudy, and uncertain pixels are not evidence of absence. |
| Detection-level labels | 0 verified and 0 weak labels attached to FIRMS rows; all 9,220 rows remain unknown/unlinked |
| External event evidence | The latest review run inventories 8 source records and 6 event records. Five event records overlap FIRMS acquisition dates (240 date-compatible rows total), but 0 are genuinely linkable to a FIRMS row because the current event evidence lacks suitable spatial/time precision. |

The final configured pilot run is saved under `data/processed/final_pilot_experiment/run_001/`. It processed 9,220 rows through matching, feature engineering, evidence review, and ranking; all 9,220 remain unknown/unlinked. The final manifest records 35 successful checks, 51 passing tests, about 232 seconds elapsed from output-root creation to last stage artifact, and about 27.3 MB of generated run files. Peak disk use was not sampled.

At a 1 km threshold the spatial-matching report lists 8,926 detections with a relevant mapped feature (8,276 proximity candidates and 650 ambiguous); this broad context is dominated by mining/extraction and infrastructure. Those counts describe proximity only. No classifier has been trained and no accuracy, precision, recall, or other model metric is reported.

## Limitations and next data needs

- **Ground truth:** No verified FIRMS-row labels or observable negative cases are currently available. Event reports can be event-level evidence, but they need precise time and georeferenced footprint linkage before use as detection labels. OSM/GEM matches cannot substitute for that evidence.
- **Persistent coal-fire context:** BCCL/NRSC fire mapping is a promising future reference source, but the discovered Jharia map is from 2020 and is not current enough to label 2026 detections without updated, time-specific mapping.
- **FIRMS preparation:** Archive/NRT retrieval is still a manual step. The new local preparation script does not download data; processed files remain local and are not committed.
- **Run paths:** The connected FIRMS, matching, and feature-engineering stages accept explicit inputs and outputs. The separate satellite-investigation and label-evidence scripts still use historical run paths.
- **Satellite evidence:** Sentinel-2 is optical context rather than a fire sensor. Acquisition date, cloud/shadow, 10/20 m resolution, and pixel footprint limit conclusions about brief fires. FIRMS detections and mapped OSM features in overlays are not validation labels.
- **OSM/GEM vintages:** Current snapshots may not represent historical facilities at each FIRMS date. GEM covers coal assets only; OSM tagging and coverage are incomplete.

The next modeling step should wait for independently reviewed labels with auditable sources, timing and location uncertainty, plus a spatially grouped and temporally held-out evaluation design. Do not split repeated detections randomly across train and test.

## Safe caching and resumption

`src/pipeline_cache.py` provides checksum-backed cache primitives. The FIRMS preparation step records SHA-256, byte size, source paths, UTC generation time, region, and chunk configuration in a `.cache.json` sidecar. An unchanged valid output is reused; a changed input/configuration or a checksum failure invalidates it. If an output previously created by the script is invalidated, its old CSV/report/manifest are preserved with a `.stale_<UTC timestamp>` suffix before regeneration. A pre-existing output without a ThermoScope cache manifest is never replaced.

The tiled OSM matcher checkpoints each completed tile under `<run>/.intermediate/tiles/`. Each checkpoint is a local pickle plus a checksum manifest keyed by the FIRMS tile content, OSM and GEM input checksums, tile/CRS/distance settings, and matcher code version. On interruption, rerun with the same output directory and `--resume`; matching recomputes only missing, changed, or checksum-invalid tiles. The final combined table validates both row IDs and stable observation IDs to prevent duplicates. Keep checkpoint directories with the run until it is complete; they are not final deliverables.

```powershell
python src/match_firms_osm_pilot.py --region dhanbad_jharia_bokaro --output-dir data/processed/spatial_matching/resumable_pilot
# After interruption, use exactly the same arguments and add:
python src/match_firms_osm_pilot.py --region dhanbad_jharia_bokaro --output-dir data/processed/spatial_matching/resumable_pilot --resume
```

The pinned OSM downloader already checks for a local PBF and validates its published MD5 and expected size before reusing it; interrupted transfers retain a resumable `.part` file. It also records the extract SHA-256, size, source URL, and retrieval time in the processing manifest. GEM acquisition validates its local raw and filtered JSON snapshots/checksum sidecars before making an API request, so the current valid snapshot is reused. The pinned OSM downloader validates existing PBF size and publisher MD5, while PBF-to-GeoPackage conversion requires a new output path or explicit `--overwrite`. Sentinel-2 scene/chip retrieval is repeated into a new run directory. Tile checkpoints/resume apply to tiled matching; the final Dhanbad pilot matcher does not checkpoint. Ranking, evidence review, and feature engineering produce fresh run outputs. No nationwide cache or data was created.

Cache checksums require reading the full input/artifact bytes and can add I/O time for large files. Tile checkpoints duplicate matched rows and consume additional storage until removed manually after retaining the final outputs. Cache manifests detect accidental truncation or content changes, but a local pickle should only be loaded from a trusted project directory. Preserve stale files and prior run directories; they are intentionally not auto-deleted.
