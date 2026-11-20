FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    MKL_NUM_THREADS=1

WORKDIR /app
COPY requirements-satellite.txt requirements-smoke-model.txt ./
RUN python -m pip install --no-cache-dir \
    --extra-index-url https://download.pytorch.org/whl/cpu \
    -r requirements-smoke-model.txt

COPY . .

# Public deployment sample assets are copied into the paths expected by the app.
COPY deployment/assets/firms_jharkhand_2026.csv data/processed/firms_jharkhand_2026.csv
COPY deployment/assets/jharkhand_261016_osm.gpkg data/processed/osm/jharkhand_261016_osm.gpkg
COPY deployment/assets/feature_table.csv.gz data/processed/jharkhand_analysis/run_001/feature_engineering_with_sentinel2/feature_table.csv.gz
COPY deployment/assets/scene_metadata.csv data/processed/jharkhand_analysis/run_001/satellite_investigation/scene_metadata.csv
COPY deployment/assets/selected_investigation_cells.csv data/processed/jharkhand_analysis/run_001/satellite_investigation/selected_investigation_cells.csv
COPY deployment/assets/jharkhand_osm_admin4.geojson data/processed/boundaries/jharkhand_osm_admin4.geojson
COPY deployment/assets/thermoscope_smoke_tiny_v1.pth models/thermoscope_smoke_tiny_v1.pth
COPY deployment/assets/thermoscope_smoke_unet_v1.pth models/thermoscope_smoke_unet_v1.pth

ENV THERMOSCOPE_ALLOW_PUBLIC_BIND=1
CMD ["sh", "-c", "python -m src.thermoscope_app.server --host 0.0.0.0 --port ${PORT:-10000}"]
