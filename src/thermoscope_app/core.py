"""Image validation and evidence lookup for the local ThermoScope application.

The CV interface is deliberately model-agnostic. No fire classifier is shipped;
geographic evidence is returned separately and never converted to a fire label.
"""
from __future__ import annotations

import base64
import io
import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from PIL import ExifTags, Image
from pyproj import Transformer
from rasterio.io import MemoryFile
from rasterio.warp import transform_bounds
from shapely.geometry import Point, shape, mapping
from shapely.strtree import STRtree

from src.match_firms_osm_pilot import feature_label, feature_roles, parse_tags, tag_categories
from src.regions import coordinate_in_region, get_region, select_projected_crs

ROOT = Path(__file__).resolve().parents[2]
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_IMAGE_DIMENSION = 10_000
MAX_IMAGE_PIXELS = 50_000_000
ALLOWED_SUFFIXES = {".tif", ".tiff", ".png", ".jpg", ".jpeg"}
REGION = get_region("jharkhand")


def load_jharkhand_map_data() -> dict[str, Any]:
    """Return a simplified local Jharkhand boundary for the interactive map."""
    config_path = ROOT / "config" / "regions.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    state = config["regions"]["jharkhand"]
    relative = state["country_boundary"]["geometry_path"]
    boundary_path = ROOT / relative
    if not boundary_path.is_file():
        raise FileNotFoundError(f"Configured Jharkhand boundary is missing: {relative}")
    collection = json.loads(boundary_path.read_text(encoding="utf-8"))
    geometries = [shape(feature["geometry"]) for feature in collection.get("features", [])
                  if feature.get("geometry")]
    if not geometries:
        raise ValueError("Configured Jharkhand boundary contains no polygon geometry.")
    from shapely.ops import unary_union
    boundary = unary_union(geometries)
    if boundary.is_empty or not boundary.is_valid:
        raise ValueError("Configured Jharkhand boundary is empty or invalid.")
    simplified = boundary.simplify(0.002, preserve_topology=True)
    return {"geometry": mapping(simplified), "bbox_wgs84": state["bbox_wgs84"],
            "name": state["name"], "source": state["country_boundary"]["source"],
            "source_version": state["country_boundary"]["source_version"],
            "source_license": state["country_boundary"]["source_license"]}


class UploadError(ValueError):
    """Raised when an uploaded image cannot be safely interpreted."""


def _scale_band(values: np.ndarray, valid: np.ndarray) -> np.ndarray:
    vals = np.asarray(values, dtype=np.float32)
    finite = np.isfinite(vals) & valid
    if not finite.any():
        return np.zeros(vals.shape, dtype=np.uint8)
    low, high = np.percentile(vals[finite], [2, 98])
    if high <= low:
        high = low + 1
    return np.clip((vals - low) * (255.0 / (high - low)), 0, 255).astype(np.uint8)


def _raster_preview(dataset: rasterio.io.DatasetReader) -> Image.Image:
    if dataset.width * dataset.height > MAX_IMAGE_PIXELS:
        raise UploadError(f"Image is too large to preview safely ({dataset.width:,} × {dataset.height:,}).")
    if dataset.width > MAX_IMAGE_DIMENSION or dataset.height > MAX_IMAGE_DIMENSION:
        raise UploadError(f"Maximum supported image dimension is {MAX_IMAGE_DIMENSION:,} pixels.")
    count = dataset.count
    if count < 1 or count > 16:
        raise UploadError("GeoTIFF must contain between 1 and 16 raster bands.")
    scale = min(1.0, 1400 / max(dataset.width, dataset.height))
    out_w, out_h = max(1, int(dataset.width * scale)), max(1, int(dataset.height * scale))
    indexes: list[int]
    descriptions = [str(d or "").lower() for d in dataset.descriptions]
    if count >= 3:
        indexes = []
        for needles in (("red", "b04"), ("green", "b03"), ("blue", "b02")):
            found = next((i + 1 for i, desc in enumerate(descriptions) if any(n in desc for n in needles)), None)
            indexes.append(found or len(indexes) + 1)
    else:
        indexes = [1]
    valid_masks = dataset.read_masks(indexes, out_shape=(len(indexes), out_h, out_w), resampling=rasterio.enums.Resampling.nearest) > 0
    arrays = dataset.read(indexes, out_shape=(len(indexes), out_h, out_w), resampling=rasterio.enums.Resampling.bilinear)
    valid = np.all(valid_masks, axis=0)
    bands = [_scale_band(arrays[i], valid) for i in range(len(indexes))]
    if len(bands) == 1:
        rgb = np.repeat(bands[0][:, :, None], 3, axis=2)
    else:
        rgb = np.stack(bands[:3], axis=2)
    return Image.fromarray(rgb, mode="RGB")


def _image_date_from_tags(tags: dict[str, Any], filename: str) -> str | None:
    for key, value in tags.items():
        if any(term in key.lower() for term in ("date", "datetime", "sensing_time", "acquisition")):
            match = re.search(r"20\d{2}[-:]?\d{2}[-:]?\d{2}", str(value))
            if match:
                raw = match.group(0).replace(":", "-")
                if len(raw) == 8:
                    return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
                try:
                    return date.fromisoformat(raw).isoformat()
                except ValueError:
                    pass
    match = re.search(r"20\d{6}", filename)
    if match:
        raw = match.group(0)
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
    return None


def _exif_gps_and_date(image: Image.Image) -> tuple[float | None, float | None, str | None]:
    try:
        exif = image.getexif()
        named = {ExifTags.TAGS.get(k, str(k)): v for k, v in exif.items()}
        dt = str(named.get("DateTimeOriginal") or named.get("DateTime") or "")
        parsed_date = None
        m = re.search(r"(20\d{2}):(\d{2}):(\d{2})", dt)
        if m:
            parsed_date = "-".join(m.groups())
        gps_raw = exif.get_ifd(ExifTags.IFD.GPSInfo) if hasattr(exif, "get_ifd") else {}
        gps = {ExifTags.GPSTAGS.get(k, str(k)): v for k, v in gps_raw.items()}
        def decimal(parts):
            return float(parts[0]) + float(parts[1]) / 60 + float(parts[2]) / 3600
        lat, lon = gps.get("GPSLatitude"), gps.get("GPSLongitude")
        if lat and lon:
            latitude, longitude = decimal(lat), decimal(lon)
            if gps.get("GPSLatitudeRef") == "S": latitude *= -1
            if gps.get("GPSLongitudeRef") == "W": longitude *= -1
            return latitude, longitude, parsed_date
        return None, None, parsed_date
    except Exception:
        return None, None, None


def inspect_upload(filename: str, content: bytes) -> dict[str, Any]:
    """Validate and preview an in-memory upload; never writes the upload to disk."""
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise UploadError("Supported formats are GeoTIFF (.tif/.tiff), PNG and JPEG.")
    if not content:
        raise UploadError("The uploaded file is empty.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise UploadError(f"Upload exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MiB limit.")

    output: dict[str, Any] = {
        "filename": Path(filename).name, "size_bytes": len(content), "width": None,
        "height": None, "bands": None, "crs": None, "bounds_wgs84": None,
        "longitude": None, "latitude": None, "acquisition_date": None,
        "metadata_source": "none", "warnings": [],
    }
    preview: Image.Image
    if suffix in {".tif", ".tiff"}:
        try:
            with MemoryFile(content) as mem, mem.open() as ds:
                output.update(width=ds.width, height=ds.height, bands=ds.count,
                              crs=ds.crs.to_string() if ds.crs else None)
                if ds.width > MAX_IMAGE_DIMENSION or ds.height > MAX_IMAGE_DIMENSION or ds.width * ds.height > MAX_IMAGE_PIXELS:
                    raise UploadError("GeoTIFF dimensions exceed the safe processing limit (10,000 per side; 50 million pixels total).")
                tags = dict(ds.tags())
                tags.update(ds.tags(ns="IMAGE_STRUCTURE"))
                output["acquisition_date"] = _image_date_from_tags(tags, filename)
                if ds.crs and ds.transform and ds.width and ds.height:
                    bounds = transform_bounds(ds.crs, "EPSG:4326", *ds.bounds, densify_pts=21)
                    west, south, east, north = map(float, bounds)
                    if all(np.isfinite([west, south, east, north])):
                        output["bounds_wgs84"] = [west, south, east, north]
                        output["longitude"], output["latitude"] = (west + east) / 2, (south + north) / 2
                        output["metadata_source"] = "GeoTIFF CRS and affine transform"
                else:
                    output["warnings"].append("GeoTIFF has no usable CRS/geotransform; enter location manually for geographic evidence.")
                preview = _raster_preview(ds)
        except UploadError:
            raise
        except Exception as exc:
            raise UploadError(f"Could not read GeoTIFF: {exc}") from exc
    else:
        try:
            with Image.open(io.BytesIO(content)) as im:
                im.verify()
            with Image.open(io.BytesIO(content)) as im:
                if im.width > MAX_IMAGE_DIMENSION or im.height > MAX_IMAGE_DIMENSION or im.width * im.height > MAX_IMAGE_PIXELS:
                    raise UploadError("Image dimensions exceed the safe processing limit.")
                output.update(width=im.width, height=im.height, bands=len(im.getbands()))
                lat, lon, exif_date = _exif_gps_and_date(im)
                output["latitude"], output["longitude"] = lat, lon
                output["acquisition_date"] = exif_date or _image_date_from_tags({}, filename)
                if lat is not None:
                    output["metadata_source"] = "JPEG EXIF GPS"
                else:
                    output["warnings"].append("No geospatial metadata found; enter coordinates and date if known.")
                preview = im.convert("RGB")
                preview.thumbnail((1400, 1400))
        except UploadError:
            raise
        except Exception as exc:
            raise UploadError(f"Could not decode image: {exc}") from exc
    buf = io.BytesIO()
    preview.save(buf, format="PNG", optimize=True)
    output["preview_data_url"] = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
    if output["acquisition_date"] is None:
        output["warnings"].append("Acquisition date is unavailable; historical evidence cannot be time-filtered.")
    return output


def cv_inference(_preview_data_url: str) -> dict[str, Any]:
    """Stable model interface; intentionally unavailable until a model is defensible."""
    return {
        "status": "unavailable",
        "model": None,
        "prediction": None,
        "message": "No scientifically supported industrial-fire CV model is available in this repository. Image-based classification is not run.",
    }


@dataclass
class EvidenceRepository:
    firms_path: Path
    osm_path: Path
    features_path: Path
    satellite_metadata_path: Path

    @classmethod
    def local_default(cls) -> "EvidenceRepository":
        return cls(
            ROOT / "data/processed/firms_jharkhand_2026.csv",
            ROOT / "data/processed/osm/jharkhand_261016_osm.gpkg",
            ROOT / "data/processed/jharkhand_analysis/run_001/feature_engineering_with_sentinel2/feature_table.csv.gz",
            ROOT / "data/processed/jharkhand_analysis/run_001/satellite_investigation/scene_metadata.csv",
        )

    def check_inputs(self) -> list[str]:
        names = ("FIRMS detections", "Jharkhand OSM GeoPackage", "feature/recurrence table", "Sentinel-2 metadata")
        paths = (self.firms_path, self.osm_path, self.features_path, self.satellite_metadata_path)
        return [f"{name} unavailable" for name, path in zip(names, paths) if not path.is_file()]

    def analyze(self, longitude: float, latitude: float, acquisition_date: str | None,
                radius_m: float = 1_000, lookback_days: int = 30) -> dict[str, Any]:
        if not (-180 <= longitude <= 180 and -90 <= latitude <= 90):
            raise ValueError("Coordinates must be valid longitude/latitude in EPSG:4326.")
        within = coordinate_in_region(longitude, latitude, REGION)
        result: dict[str, Any] = {
            "within_study_area": within, "study_area": "Jharkhand, India",
            "location": {"longitude": longitude, "latitude": latitude},
            "uploaded_acquisition_date": acquisition_date,
            "cv": cv_inference(""),
            "firms": {"status": "not_run", "records": [], "prior_count_within_250m": None,
                      "prior_distinct_dates_within_250m": None},
            "osm": {"status": "not_run", "features": []},
            "sentinel2_context": {"status": "not_run", "record": None},
            "assessment": "insufficient_evidence_to_classify",
            "assessment_text": "A validated fire/source classifier is unavailable. The visible-smoke model output is separate; this application reports supporting evidence for human review.",
            "limitations": [
                "FIRMS thermal observations are not confirmed fires or source labels.",
                "OSM/GEM proximity describes mapped context and does not establish causality.",
                "Sentinel-2 is optical and cannot confirm an active thermal event.",
            ],
        }
        missing = self.check_inputs()
        if missing:
            result["data_warnings"] = ["Local evidence input unavailable: " + item for item in missing]
            return result
        if not within:
            result["data_warnings"] = ["Location falls outside the configured Jharkhand boundary; local evidence search was skipped."]
            return result
        result["firms"] = self._firms_evidence(longitude, latitude, acquisition_date, radius_m, lookback_days)
        result["osm"] = self._osm_evidence(longitude, latitude, radius_m)
        result["sentinel2_context"] = self._sentinel_context(longitude, latitude, acquisition_date)
        result["assessment_text"] = (
            "This is an evidence-based human-review summary, not a fire/source classification. The visible-smoke model output is reported separately."
            if result["firms"]["records"] or result["osm"]["features"]
            else "No local evidence was found in the configured search window; absence of a mapped record is not evidence of absence."
        )
        return result

    def _firms_evidence(self, lon: float, lat: float, acq_date: str | None,
                        radius_m: float, lookback_days: int) -> dict[str, Any]:
        base = pd.read_csv(self.firms_path, low_memory=False, usecols=lambda c: c in {
            "firms_observation_id", "latitude", "longitude", "acq_date", "acq_time",
            "satellite", "instrument", "confidence", "frp", "brightness", "bright_t31",
            "daynight", "firms_sources", "duplicate_record_count", "region_id", "version", "type",
        })
        enriched = pd.read_csv(self.features_path, compression="gzip", low_memory=False,
                               usecols=lambda c: c in {
                                   "firms_observation_id", "thermal_frp_mw", "thermal_brightness_k",
                                   "osm_nearest_relevant_role", "osm_nearest_relevant_category",
                                   "osm_nearest_relevant_distance_m", "cell_prior_detection_count",
                                   "cell_prior_distinct_acquisition_dates", "cell_prior_last_acquisition_date",
                                   "hotspot_cell_id", "cell_distinct_acquisition_dates",
                               })
        if "firms_observation_id" not in base or "firms_observation_id" not in enriched:
            raise ValueError("FIRMS and feature inputs must contain stable firms_observation_id values.")
        if base.firms_observation_id.duplicated().any() or enriched.firms_observation_id.duplicated().any():
            raise ValueError("FIRMS and feature inputs must have unique stable observation IDs.")
        feature_extras = [c for c in enriched.columns if c != "firms_observation_id" and c not in base.columns]
        frame = base.merge(enriched[["firms_observation_id", *feature_extras]], on="firms_observation_id",
                           how="left", validate="one_to_one")
        frame["latitude"] = pd.to_numeric(frame.latitude, errors="coerce")
        frame["longitude"] = pd.to_numeric(frame.longitude, errors="coerce")
        frame["_date"] = pd.to_datetime(frame.acq_date, errors="coerce").dt.date
        crs = select_projected_crs(REGION, lon, lat)
        trans = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
        x0, y0 = trans.transform(lon, lat)
        xs, ys = trans.transform(frame.longitude.to_numpy(), frame.latitude.to_numpy())
        frame["distance_m"] = np.hypot(xs - x0, ys - y0)
        frame = frame[frame.distance_m <= radius_m].copy()
        if acq_date:
            cutoff = date.fromisoformat(acq_date)
            start = pd.Timestamp(cutoff) - pd.Timedelta(days=lookback_days)
            frame = frame[frame["_date"].notna() & (frame["_date"] <= cutoff) & (frame["_date"] >= start.date())].copy()
            temporal_status = f"Date-filtered from {start.date()} through {cutoff}; same-date ordering is unknown because FIRMS and image times may differ."
        else:
            temporal_status = "No upload date supplied; dates are shown without temporal eligibility filtering."
        frame.sort_values(["distance_m", "_date"], ascending=[True, False], inplace=True)
        records = []
        for row in frame.head(30).to_dict("records"):
            records.append({k: _json_value(v) for k, v in row.items() if not k.startswith("_")})
        recurrence = frame[frame.distance_m <= min(250, radius_m)]
        if acq_date:
            recurrence = recurrence[recurrence["_date"] < date.fromisoformat(acq_date)]
            distinct_dates = int(recurrence["_date"].dropna().nunique())
            count = int(len(recurrence))
        else:
            distinct_dates, count = None, None
        nearest = records[0] if records else {}
        precomputed_cell_history = None
        if nearest:
            precomputed_cell_history = {
                "hotspot_cell_id": nearest.get("hotspot_cell_id"),
                "past_detection_count_at_detection_date": nearest.get("cell_prior_detection_count"),
                "past_distinct_dates_at_detection_date": nearest.get("cell_prior_distinct_acquisition_dates"),
                "last_prior_detection_date": nearest.get("cell_prior_last_acquisition_date"),
                "definition": "Existing feature pipeline's strictly earlier-date 250 m grid-cell history for the nearest FIRMS observation.",
            }
        return {"status": "available", "count_in_search_radius": int(len(frame)),
                "search_radius_m": radius_m, "lookback_days": lookback_days if acq_date else None,
                "temporal_rule": temporal_status, "records": records,
                "prior_count_within_250m": count,
                "prior_distinct_dates_within_250m": distinct_dates,
                "nearest_detection_grid_history": precomputed_cell_history,
                "recurrence_interpretation": "Repeated sensor observations in a radius, not proof of one physical source."}

    def _osm_evidence(self, lon: float, lat: float, radius_m: float) -> dict[str, Any]:
        crs = select_projected_crs(REGION, lon, lat)
        trans = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
        x0, y0 = trans.transform(lon, lat)
        # A conservative geographic query box around up to 5 km; exact distances are projected.
        pad = max(radius_m, 5_000) / 80_000
        bbox = (lon - pad, lat - pad, lon + pad, lat + pad)
        records: list[dict[str, Any]] = []
        to_wgs84 = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
        for layer in gpd.list_layers(self.osm_path).name:
            try:
                source = gpd.read_file(self.osm_path, layer=layer, bbox=bbox)
            except Exception:
                continue
            if source.empty or source.crs is None:
                continue
            source = source.to_crs(crs)
            for _, row in source.iterrows():
                geom = row.geometry
                if geom is None or geom.is_empty or not geom.is_valid:
                    continue
                tags = parse_tags(row.get("all_tags"))
                categories = tag_categories(tags)
                roles = feature_roles(tags, categories)
                # Show industrial/mine facilities separately from general power grid assets.
                meaningful = [r for r in roles if r != "vegetation_context"]
                if not meaningful:
                    continue
                distance = float(geom.distance(Point(x0, y0)))
                if distance > radius_m:
                    continue
                representative = geom.representative_point()
                feature_lon, feature_lat = to_wgs84.transform(representative.x, representative.y)
                classes = ("industrial_landuse", "industrial_facility", "mining_extraction_area", "mine_working_feature", "waste_facility", "industrial_rail", "power_generation", "power_site")
                group = "industrial_or_generation_context" if any(r in classes for r in meaningful) else "general_power_infrastructure"
                records.append({"distance_m": distance, "label": feature_label(tags, categories),
                                "categories": categories, "roles": meaningful, "context_group": group,
                                "osm_id": str(row.get("osm_id", "")),
                                "geometry_type": geom.geom_type,
                                "longitude": float(feature_lon), "latitude": float(feature_lat),
                                "selected_tags": {k: tags[k] for k in ("name", "landuse", "industrial", "power", "plant", "building", "man_made", "railway") if k in tags}})
        records.sort(key=lambda r: (r["distance_m"], r["label"]))
        industrial_count = sum(r["context_group"] == "industrial_or_generation_context" for r in records)
        general_power_count = sum(r["context_group"] == "general_power_infrastructure" for r in records)
        return {"status": "available", "search_radius_m": radius_m,
                "feature_count": len(records),
                "industrial_feature_count": industrial_count,
                "general_power_feature_count": general_power_count,
                "features": records[:30],
                "source_vintage": "Local Geofabrik Eastern Zone OSM extract processed 2026-10-16; current mapped context, not date-versioned."}

    def _sentinel_context(self, lon: float, lat: float, acq_date: str | None) -> dict[str, Any]:
        if not acq_date:
            return {"status": "date_required_for_temporal_eligibility", "record": None,
                    "message": "Enter the uploaded image acquisition date before showing stored Sentinel scenes; future scenes cannot be ruled out otherwise."}
        table = pd.read_csv(self.satellite_metadata_path)
        selected = pd.read_csv(self.satellite_metadata_path.parent / "selected_investigation_cells.csv")
        if not {"hotspot_cell_id", "scene_datetime_utc", "chip_path", "status"}.issubset(table.columns):
            return {"status": "unavailable", "record": None, "message": "Local Sentinel metadata has an unexpected schema."}
        coords = selected[["hotspot_cell_id", "centroid_longitude", "centroid_latitude"]].dropna()
        table = table.merge(coords, on="hotspot_cell_id", how="left")
        table = table[(table.status == "chip_created") & table.centroid_longitude.notna()]
        if acq_date:
            # Date-only upload metadata cannot establish intraday ordering, so only
            # earlier calendar dates qualify as historical optical context.
            table = table[pd.to_datetime(table.scene_datetime_utc, utc=True).dt.date < date.fromisoformat(acq_date)]
        if table.empty:
            return {"status": "no_temporally_eligible_local_chip", "record": None,
                    "message": "No locally stored chip is both spatially represented and acquired on/before the uploaded image date."}
        crs = select_projected_crs(REGION, lon, lat)
        trans = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
        x0, y0 = trans.transform(lon, lat)
        xs, ys = trans.transform(table.centroid_longitude.to_numpy(), table.centroid_latitude.to_numpy())
        table = table.copy()
        table["distance_m"] = np.hypot(xs - x0, ys - y0)
        table = table.sort_values("distance_m")
        row = table.iloc[0]
        if float(row.distance_m) > 10_000:
            return {"status": "no_local_chip_within_10km", "record": None,
                    "message": "The existing Sentinel sample has no chip within 10 km of this upload."}
        raw = Path(str(row.chip_path).replace("\\", "/"))
        chip_path = raw if raw.is_absolute() else ROOT / raw
        if not chip_path.is_file():
            return {"status": "metadata_only_chip_missing", "record": None}
        with rasterio.open(chip_path) as ds:
            preview = _raster_preview(ds)
        buf = io.BytesIO(); preview.save(buf, format="PNG", optimize=True)
        return {"status": "context_only", "record": {
            "distance_m": float(row.distance_m), "scene_item_id": row.get("selected_stac_item"),
            "acquisition_datetime_utc": row.scene_datetime_utc,
            "scene_cloud_percent": _json_value(row.get("eo_cloud_cover_percent_scene_level")),
            "chip_cloud_shadow_percent": _json_value(row.get("local_scl_cloud_shadow_percent")),
            "preview_data_url": "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii"),
            "warning": "Existing optical context chip only. It is not thermal, causal proof, or an independent label."}}


def _json_value(value: Any) -> Any:
    if value is None or value is pd.NA or pd.isna(value):
        return None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (pd.Timestamp, date)):
        return value.isoformat()
    return value.item() if isinstance(value, np.generic) else value
