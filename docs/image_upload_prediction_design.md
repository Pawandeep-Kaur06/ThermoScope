# ThermoScope image upload and evidence application

## What the application does

ThermoScope now has a local browser interface for uploading GeoTIFF, PNG, or JPEG satellite imagery. It previews the image, checks dimensions and file size, reads GeoTIFF CRS/affine bounds and acquisition-date tags where available, and reads JPEG EXIF GPS/date when present. The user can enter WGS84 longitude/latitude and acquisition date when metadata is absent.

The interface also renders the configured Jharkhand boundary from local GeoJSON. Hovering shows map coordinates; clicking chooses a search center, and dragging selects a rectangle. Because the evidence engine searches by distance from a point, a rectangle is evaluated using the covering circle around its center, with the resulting radius shown in the UI. This is an approximate area search, not a polygon overlay/intersection query. FIRMS and OSM markers on the map are actual returned local records. The side panel also loads Esri World Imagery map tiles centered on the selected coordinates. The mosaic can combine sources with different acquisition dates and spatial resolutions; it is visual context only and cannot establish an active fire. Attribution is shown on the map as “Source: Esri, Vantor, Earthstar Geographics, and the GIS User Community.” The browser requests tile URLs from Esri, which reveals tile locations to the provider; uploaded image bytes remain local.

For a location inside the configured Jharkhand boundary, the app searches the existing local Jharkhand FIRMS feature table, the local OSM GeoPackage, the state pilot recurrence features, and the six-chip Sentinel-2 investigation output. The Sentinel-2 sample is shown only when the uploaded date is present, the scene was acquired on or before that date, and the chip is within 10 km. This is a small contextual archive, not general satellite retrieval.

The application has **no trained image-based fire/source classifier**. The fire-model interface returns `unavailable`; the final geographic assessment remains `insufficient_evidence_to_classify`. A separate experimental visible-smoke model is now available for compatible 13-band Sentinel-2 GeoTIFF chips. Its smoke cue and optional polygon-mask overlay are displayed separately from FIRMS observations, recurrence and OSM; they do not establish fire, source cause or thermal activity. See [the smoke-model development report](smoke_model_training_report.md).

## Run locally

From the repository root, with the existing satellite/geospatial dependencies installed:

```powershell
venv\Scripts\python.exe -m src.thermoscope_app.server
```

Open `http://127.0.0.1:8765`. Stop the server with Ctrl+C. The server only binds to loopback and refuses a non-local bind address. Existing datasets are read-only inputs. Uploaded image bytes remain in memory for the request and are not saved. The satellite preview makes direct HTTPS image-tile requests to Esri's World Imagery service; other evidence searches use local project data and do not call an external evidence API.

The default inputs are the local Jharkhand prepared FIRMS, OSM, feature/recurrence, and satellite metadata outputs. To point at an alternate compatible local run:

```powershell
venv\Scripts\python.exe -m src.thermoscope_app.server `
  --firms data\processed\firms_jharkhand_2026.csv `
  --osm data\processed\osm\jharkhand_261016_osm.gpkg `
  --features data\processed\jharkhand_analysis\run_001\feature_engineering_with_sentinel2\feature_table.csv.gz `
  --satellite-metadata data\processed\jharkhand_analysis\run_001\satellite_investigation\scene_metadata.csv
```

The CSV feature table must retain `latitude`, `longitude`, `acq_date`, and FIRMS thermal attributes; for recurrence-cell context it should also contain `hotspot_cell_id`, `cell_prior_detection_count`, `cell_prior_distinct_acquisition_dates`, and `cell_prior_last_acquisition_date`. Satellite metadata must have a matching `selected_investigation_cells.csv` beside it.

## Evidence rules

- FIRMS points are filtered by projected distance and, when the uploaded date is supplied, shown from the configured lookback period through that date. Same-day order remains unknown because FIRMS records and image metadata may have different acquisition times.
- The nearby-observation recurrence summary counts only detections strictly before the image date. The precomputed grid-cell recurrence fields are shown from the nearest matched detection and retain the feature pipeline's strictly-past-date rule. A grid cell is not assumed to be one physical source.
- OSM point, line, and polygon geometries are measured in the local UTM CRS selected for the upload coordinate. Industrial/mining/generation features and general power infrastructure are separate context groups. OSM is the 2026-10-16 snapshot, not a historically versioned record.
- Local Sentinel-2 context is optical and cloud metadata is reported. The image cannot confirm an active fire or its cause. If upload date is unknown, Sentinel context is withheld; with date-only metadata, only scenes from an earlier calendar day are eligible because intraday ordering cannot be established.
- Coordinates outside the configured Jharkhand polygon receive no state evidence lookup. The boundary itself is an OSM administrative relation and has documented limits.
- Missing data is reported as unavailable/unknown, never as evidence that a thermal event or facility is absent.

## Application architecture

- `core.inspect_upload`: validation, metadata extraction and image preview, in memory.
- `core.cv_inference`: fire/source inference seam; it reports unavailable and makes no fire/source prediction.
- `smoke_model.predict_smoke_upload`: optional 12-channel visible-smoke classifier and segmentation adapter. It requires a 13-band uint16 Sentinel-2 GeoTIFF chip, named band metadata or explicit band-order confirmation, and local model weights; RGB/four-band inputs are refused.
- `EvidenceRepository`: FIRMS proximity and temporal filtering, existing recurrence fields, OSM matching, and optional nearby stored Sentinel context.
- `server`: loopback-only HTTP/multipart interface with bounded uploads and no request-body logging.
- `app/index.html` and `app/map.js`: dark dashboard interface with an interactive local boundary/evidence map, hover/click/rectangle selection, upload/settings panel, image preview, and separate evidence results. The boundary is local configuration data and detections/facilities are drawn only from returned FIRMS/OSM records.

## Current limitations

1. There is no image-based fire model, suitable label set, or independent evaluation in the repository. The app cannot emit the four requested source classes as predictions.
2. The image upload accepts common image rasters, but only GeoTIFF CRS/affine metadata and JPEG EXIF GPS are interpreted. Other sidecars/world files are not read.
3. The app uses the local 2026 Jharkhand FIRMS/OSM snapshot. It does not fetch fresh FIRMS, OSM or satellite data and has no statewide live evidence service.
4. Only the existing six Sentinel-2 investigation chips are available; lack of a nearby chip means unavailable context, not no satellite coverage.
5. FIRMS same-day event ordering cannot be resolved from a date-only upload. The user must provide precise time and a time-aware workflow would be needed for sub-day eligibility.
6. The smoke models were trained/evaluated on 2019 European sites. Their local held-out split is site-grouped but not a later-time or Jharkhand evaluation. The visible-smoke score is uncalibrated and must not be called a fire probability.

The smoke cue is only a feasibility model for visible plumes. A credible, independently reviewed, geographically held-out Jharkhand validation set is still needed before local use can be assessed. A fire/source classifier remains unavailable until a separate image dataset with time- and location-specific verified fire/source labels and controls exists.
