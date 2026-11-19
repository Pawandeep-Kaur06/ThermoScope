# ThermoScope: system and data summary

**Purpose.** ThermoScope investigates satellite thermal observations near mapped industrial contexts in Jharkhand. Its results support human review; the project does not currently provide a validated industrial-fire classifier.

## What the application does

1. A user uploads a GeoTIFF, PNG, or JPEG (up to 25 MiB). It previews the image and reads geospatial/date metadata when available; users can enter missing coordinates or date. A map lets users choose a Jharkhand search location.
2. If the upload meets the smoke model input contract, a separate image model estimates whether visible-smoke cues are present and may show an experimental smoke segmentation overlay.
3. With a location in Jharkhand, the app searches local FIRMS thermal observations and local OSM features, and may show an eligible stored Sentinel-2 context chip. These evidence sources are displayed separately.
4. The overall assessment is for investigation. A nearby thermal detection or industrial feature does not establish a fire, cause, or source.

## Inputs and specifications

| Component | Data/model used | What it extracts or provides |
|---|---|---|
| NASA FIRMS | Local archive/NRT CSV exports, prepared and deduplicated with source provenance. Active Jharkhand run: 21,450 detections dated 2026-01-20 to 2026-09-06. | Thermal observation coordinates/date, sensor and satellite, confidence, day/night, brightness and fire radiative power (FRP), where supplied. These are satellite detections, not incident labels. |
| OpenStreetMap | Local Geofabrik Eastern Zone PBF snapshot processed 2026-10-16; 37,046 tagged features in the Jharkhand run. | Mapped industrial/mining land use, facilities, power generation and general power infrastructure. The matcher computes nearby distances and categories; mapped proximity is context, not causation. |
| Sentinel-2 | Six small sampled optical chips with scene-classification (SCL) masks in the state run; 10 m and 20 m source bands may be resampled for analysis. | Surface/spectral context and cloud/shadow screening. Sentinel-2 is optical and has no thermal band. In the state feature integration, only one FIRMS row had a valid, clear, temporally eligible spectral sample. |
| Visible-smoke CV dataset | Industrial Smoke Plumes dataset, Zenodo 4250706 (CC BY 4.0): 21,350 13-band `uint16` Sentinel-2 chips, 120×120 pixels for nearly all samples, from 624 European sites in 2019. It has 3,750 manually marked visible-smoke positives and 17,600 negatives; 1,427 usable polygon annotations. | Training/evaluation targets are visible smoke in imagery, not industrial fire or thermal-source identity. The project’s split is grouped by site, with 436 train, 94 validation and 94 held-out test sites. |

## Model used

- **Image classifier:** a compact, locally trained 12-channel TinyCNN. It uses the source dataset’s Sentinel-2 channel selection and normalization. Training used a seeded, class-balanced sample of 4,000 images for three CPU epochs. The validation-selected threshold is 0.48; displayed scores are uncalibrated.
- **Segmentation:** a compact U-Net trained on the dataset’s 1,427 polygon-annotated smoke scenes. Its overlay is an experimental visible-smoke mask, not a fire boundary.
- The published paper’s modified ResNet-50 was not reproduced. The model was evaluated on held-out **2019 European sites**, not Jharkhand. Its performance does not establish local reliability.
- Upload inference expects a 13-band `uint16` Sentinel-2 GeoTIFF, 90–120 pixels per side, with the documented band order. The source dataset’s 13-band stack combines 12 L2A bands with B10 from its matching L1C source; preprocessing omits B10 and feeds 12 channels to the model. Four-band context chips can be viewed as imagery but cannot run this model.

## Current analysis coverage and limits

The completed Jharkhand run prepared 21,450 FIRMS detections and matched them against 37,046 tagged OSM features across 14 processing tiles. Six small Sentinel-2 samples were investigated. Those samples are sparse context, not a representative training dataset. No verified detection-level fire/source labels are available, and no supervised industrial-fire model or Jharkhand-validated smoke model exists. Missing FIRMS, OSM or imagery evidence means “not found in the available search,” not “absent.”

For full methods and caveats, see [Jharkhand results](jharkhand_results.md), [smoke model training and evaluation](smoke_model_training_report.md), and [image-upload application design](image_upload_prediction_design.md).
