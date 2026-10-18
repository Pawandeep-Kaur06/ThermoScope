# ThermoScope

**AI-Based Detection and Classification of Industrial Fires and Persistent Thermal Sources using NASA FIRMS, OSM & Satellite Data**

ThermoScope is an exploratory computer-vision and geospatial project for investigating satellite-detected thermal anomalies in the Dhanbad–Jharia–Bokaro region of Jharkhand, India. The project brings together NASA FIRMS observations, OpenStreetMap context, satellite imagery, and supplementary Global Energy Monitor (GEM) facility data. The intended goal is to distinguish industrial fires and persistent thermal sources from other thermal anomalies using evidence that can be independently checked.

## Current status

The pilot has reproducible local acquisition/matching/feature scripts and exploratory outputs. **It does not yet have verified detection-level ground-truth labels, and no supervised model has been trained.** OSM/GEM proximity, FIRMS recurrence, and image context are investigation evidence, not cause labels.

Current local inputs and outputs are intentionally excluded from Git. A fresh checkout needs the inputs listed below before the corresponding pipeline commands will run.

## Data sources

| Source | Role in ThermoScope | Access and limits |
| --- | --- | --- |
| [NASA FIRMS](https://firms.modaps.eosdis.nasa.gov/) | Active-fire and thermal-anomaly observations with acquisition time, coordinates, FRP, brightness, confidence, and sensor attributes. | The existing project input is a prepared local CSV at `data/processed/india_combined.csv`; this repository does not currently automate FIRMS download/merge. FIRMS detections are sensor observations, not source-cause labels. VIIRS and MODIS footprint scale, cloud/smoke obstruction, and confidence must be considered. |
| [OpenStreetMap](https://www.openstreetmap.org/) / [Geofabrik](https://download.geofabrik.de/) | Mapped industrial/mining land use, facilities, extraction areas, power generation, transmission, and other infrastructure. | `fetch_osm_pilot.py` uses a pinned Eastern Zone PBF and filters it locally to the pilot. It does not use Overpass. The source extract is about 235.8 MiB when downloaded. OSM is an incomplete, time-varying snapshot; attribution and ODbL terms apply. Proximity does not prove causality. |
| [GEM Global Coal Mine Tracker](https://globalenergymonitor.org/projects/global-coal-mine-tracker/) and [Global Coal Plant Tracker](https://globalenergymonitor.org/projects/global-coal-plant-tracker/) | Supplementary coal-mine and coal-plant facility references. | Retrieved from the GEM Assets API for Jharkhand, then filtered to the pilot. GEM is coal-sector coverage only and does not represent all industrial assets or incident history. It is not a label source. |
| [Sentinel-2 L2A via Earth Search STAC](https://earth-search.aws.element84.com/v1/api.html) | Optical land-surface context around selected recurring FIRMS grid cells. | The script searches public STAC metadata and reads small public COG image windows; no credentials are required for the current path. Visible bands are 10 m and SWIR is 20 m. Sentinel-2 has no thermal band; date, cloud, and spatial mismatch means an image cannot verify a brief FIRMS fire. |

The FIRMS pilot bounding box is 23.25–24.00°N, 85.75–86.75°E. The OSM local extract is saved at `data/raw/osm/geofabrik_eastern-zone_261016.osm.pbf`; its provenance, size, and filtering details are in `data/raw/osm/README.md`.

## Pipeline stages

1. **Prepare FIRMS input.** Provide a combined FIRMS CSV at `data/processed/india_combined.csv`. The current `src/filter_data.py` is empty, so raw archive/NRT download and merging are not yet a reproducible script stage in this repository.
2. **Fetch GEM references** (`src/fetch_gem_references.py`) for Jharkhand and create pilot-bounds subsets. GEM is optional supplementary context.
3. **Acquire/filter OSM** (`src/fetch_osm_pilot.py`) from the regional Geofabrik PBF locally. The script preserves OSM tags and geometries in a GeoPackage. It does not query Overpass.
4. **Match FIRMS to OSM** (`src/match_firms_osm_pilot.py`) with distances calculated in UTM zone 45N (EPSG:32645). Point, line, and area features are handled spatially; statuses indicate mapped context only.
5. **Inspect satellite context** (`src/investigate_satellite_pilot.py`) by selecting representative recurring cells and retrieving small Sentinel-2 windows with scene/cloud metadata.
6. **Engineer features** (`src/engineer_features.py`) including thermal, past-only recurrence, OSM/GEM context, and temporally eligible Sentinel-2 values.
7. **Assess label readiness** (`src/assess_label_evidence.py`) by keeping external event evidence separate from unlinked FIRMS rows and producing a manual review ranking. The ranking is not a classifier or probability.

## Repository layout

```text
src/                         Acquisition, spatial matching, feature, and evidence scripts
data/raw/                    Local source downloads (ignored by Git)
data/processed/              Local prepared data and timestamped runs (ignored by Git)
notebooks/                   Exploratory notebooks; local cache is ignored
models/                      Reserved for future models; no trained model yet
outputs/                     Local generated figures and reports (ignored by Git)
requirements-satellite.txt   Pinned Python dependencies for the current scripts
```

## Setup

Python 3.12 is the version used by the current project environment. From the repository root in PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements-satellite.txt
```

`pyogrio` is listed directly because the OSM conversion script imports it and requires its GDAL OSM read driver. The current environment was checked with pyogrio 0.13.0 and GDAL runtime 3.12.4. The scripts use Python's standard library for HTTP downloads except the Sentinel-2 workflow, which uses `requests`. The installed Pyogrio/GDAL build must expose the `OSM` read driver. No separate `ogr2ogr` command or OSMnx dependency is used by the regional OSM pipeline. OSMnx appears only in exploratory notebook experiments.

The six pipeline scripts do not require Jupyter or OSMnx. The exploratory notebooks use OSMnx, so install it separately only if you intend to run those notebook experiments; notebook cache files are local and ignored.

## Running the scripts

Run commands from the repository root. The scripts do not need notebook execution.

```powershell
# Fetch state-filtered GEM records and pilot subsets (network required).
.\.venv\Scripts\python.exe src/fetch_gem_references.py

# Download the pinned ~235.8 MiB OSM PBF and filter it locally.
# If the PBF is already present and only the GeoPackage is missing, use --process-only.
.\.venv\Scripts\python.exe src/fetch_osm_pilot.py --download

# Create a new timestamped FIRMS–OSM spatial-matching run.
.\.venv\Scripts\python.exe src/match_firms_osm_pilot.py

# Search Earth Search STAC and retrieve small Sentinel-2 context chips.
.\.venv\Scripts\python.exe src/investigate_satellite_pilot.py

# Build the timestamped feature-engineering output.
.\.venv\Scripts\python.exe src/engineer_features.py

# Build label-readiness evidence and review-priority outputs.
.\.venv\Scripts\python.exe src/assess_label_evidence.py
```

The data-acquisition commands require network access. Sentinel-2 STAC/COG access and GEM's current API path use no credentials. OSM acquisition downloads the full pinned regional extract, not just the pilot area; local filtering reduces the processed study-area data. Do not pass `--overwrite` to the GEM or OSM scripts unless replacing their generated targets is intentional. The OSM script refuses existing targets without that explicit option.

**Run-version note:** the current satellite, feature-engineering, and label-evidence scripts refer to specific timestamped upstream run directories (the matching run `run_20261018T201433Z`, satellite run `run_20261018T202541Z`, and feature run `run_20261018T203712Z`). These ignored run folders are present only in the working data environment, not in a clean clone. After regenerating a stage, update the downstream input path constants to its new run ID before continuing. Output directories are timestamped and are created without replacing prior runs.

## Current pilot results

These figures summarize existing local run outputs; they are exploratory and are not model performance metrics.

| Measure | Current result |
| --- | --- |
| FIRMS detections in pilot | 9,220 across 184 acquisition dates, 2026-01-20 to 2026-09-05 |
| FIRMS 250 m analysis cells | 1,063; grid cells are not verified physical sources |
| Selected OSM features | 8,333 in the filtered GeoPackage; 8,206 features used in the matching run's relevant context roles |
| FIRMS with relevant OSM feature within 250 m | 8,013 detections; statuses: 7,679 proximity candidates, 334 ambiguous, 1,207 with no relevant OSM feature within 250 m |
| GEM supplementary pilot records | 96 mine/plant records from the filtered references |
| Sentinel-2 | Four small chips selected; 217 detections have a chip available for context, but only 2 retain temporally eligible spectral samples in the current feature table. Missing, post-detection, or cloudy imagery is not evidence of absence. |
| Detection-level labels | 0 verified and 0 weak labels attached to FIRMS rows; all 9,220 rows remain unknown/unlinked |
| External event evidence | One official event-level record outside the FIRMS time window and three weak local-media event candidates; none is linked to a FIRMS row |

At a 1 km threshold the spatial-matching report lists 8,926 detections with a relevant mapped feature (8,276 proximity candidates and 650 ambiguous); this broad context is dominated by mining/extraction and infrastructure. Those counts describe proximity only. No classifier has been trained and no accuracy, precision, recall, or other model metric is reported.

## Limitations and next data needs

- **Ground truth:** No verified FIRMS-row labels or observable negative cases are currently available. Event reports can be event-level evidence, but they need precise time and georeferenced footprint linkage before use as detection labels. OSM/GEM matches cannot substitute for that evidence.
- **Persistent coal-fire context:** BCCL/NRSC fire mapping is a promising future reference source, but the discovered Jharia map is from 2020 and is not current enough to label 2026 detections without updated, time-specific mapping.
- **FIRMS preparation:** A reproducible download/merge script is still needed. The current processed CSV is a local input and is not committed.
- **Run paths:** Some downstream scripts have fixed run-directory constants; make those configurable before automating fresh end-to-end runs.
- **Satellite evidence:** Sentinel-2 is optical context rather than a fire sensor. Acquisition date, cloud/shadow, 10/20 m resolution, and pixel footprint limit conclusions about brief fires. FIRMS detections and mapped OSM features in overlays are not validation labels.
- **OSM/GEM vintages:** Current snapshots may not represent historical facilities at each FIRMS date. GEM covers coal assets only; OSM tagging and coverage are incomplete.

The next modeling step should wait for independently reviewed labels with auditable sources, timing and location uncertainty, plus a spatially grouped and temporally held-out evaluation design. Do not split repeated detections randomly across train and test.
