# ThermoScope free Render demo preparation

This folder prepares a public demonstration deployment. **Nothing has been deployed yet.** The deployment uses a Render free web service and may sleep after inactivity; free services can take about a minute to wake. Free compute has limited memory, so smoke inference may be slow or may exceed available memory.

## Assets prepared for review

The `assets/` folder contains the exact files the Docker image would publish (about 20.2 MB total):

- Prepared Jharkhand FIRMS CSV and feature/recurrence table.
- Jharkhand OSM GeoPackage and its boundary geometry.
- Satellite scene metadata and the associated selected-cell table.
- The trained visible-smoke TinyCNN and segmentation U-Net weights.

The data is a bounded Jharkhand research snapshot, not a live data feed. FIRMS inputs cover 2026-01-20 through 2026-09-06; OSM was processed from the 2026-10-16 Eastern Zone extract. The app will expose the public data and model outputs to anyone with the URL. The demo has no login, and its analysis endpoint accepts uploads up to 25 MiB; anyone with the public URL can use the available CPU. Uploaded images are sent to the hosted service for analysis; the current application handles them in memory and does not save them. Map imagery requests still send tile locations to Esri. Do not upload private or sensitive imagery.

## Attribution and scientific description

- FIRMS thermal observations: NASA Fire Information for Resource Management System (FIRMS).
- OSM facilities and Jharkhand boundary: © OpenStreetMap contributors, ODbL 1.0. The displayed boundary is an administrative relation from the stated extract, not a legal boundary.
- Visible-smoke model: trained on the Industrial Smoke Plumes dataset, Zenodo 4250706, CC BY 4.0. It predicts visible-smoke cues only and was evaluated on held-out 2019 European sites. It is not validated for Jharkhand and is not an industrial-fire classifier.
- Sentinel-2 scene references retain Copernicus attribution in source metadata/documentation.

## Prepared files

- `Dockerfile`: installs the existing geospatial and CPU model requirements, copies the reviewed demo assets, and binds to Render's assigned port.
- `render.yaml`: selects a free Render Docker web service with `/api/health` as its health check.
- `assets/manifest.sha256`: SHA-256 checksums for every included asset.

To launch, the current UI changes and these deployment files/assets must be published to the connected GitHub repository, then a Render Blueprint can be created from that repository. Neither the repository publication nor service creation has been done as part of preparation.
