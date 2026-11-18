"""Build leakage-aware ThermoScope feature tables for a configured region.

The output is an exploratory feature set, not a labeled training set. Recurrence
uses strictly earlier acquisition dates (same-date detections are excluded).
Sentinel-2 values are sampled from the available small chips and retain their
scene timing/cloud quality context.

Run from the repository root after matching:
    python src/engineer_features.py --matching-dir data/processed/spatial_matching/run_x
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
try:
    import rasterio
except ImportError:  # imagery sampling is optional for non-satellite feature runs
    rasterio = None
from pyproj import Transformer
from shapely.geometry import Point
from shapely.strtree import STRtree
try:
    from src.regions import (DEFAULT_REGION_CONFIG, RegionConfigurationError, assign_recurrence_grid,
                             assign_tile_ids, contains_coordinates, get_region, bounds_tuple,
                             select_projected_crs, tile_for_coordinate)
except ImportError:  # pragma: no cover - direct script invocation
    from regions import (DEFAULT_REGION_CONFIG, RegionConfigurationError, assign_recurrence_grid,
                         assign_tile_ids, contains_coordinates, get_region, bounds_tuple,
                         select_projected_crs, tile_for_coordinate)

ROOT = Path(__file__).resolve().parents[1]
GRID_SIZE_M = 250.0
DISTANCE_CRS = "EPSG:32645"
BOUNDS = (85.75, 23.25, 86.75, 24.00)  # default pilot; loaded from shared config in main()
REGION_ID = "dhanbad_jharia_bokaro"
BOUNDS_MAX_INCLUSIVE = True
RELEVANT_ROLES = (
    "industrial_landuse", "industrial_facility", "mining_extraction_area",
    "mine_working_feature", "waste_facility", "industrial_rail",
    "power_generation", "power_site",
)
ROLE_CATEGORY = {
    "industrial_landuse": "industrial_landuse",
    "industrial_facility": "industrial_facility",
    "mining_extraction_area": "mining_extraction",
    "mine_working_feature": "mine_working_feature",
    "waste_facility": "waste_facility",
    "industrial_rail": "industrial_rail",
    "power_generation": "power_generation",
    "power_site": "power_site",
}


def make_output_dir(output_dir: Path | None = None, repo_root: Path = ROOT) -> Path:
    if output_dir is not None:
        output = output_dir if output_dir.is_absolute() else (Path.cwd() / output_dir).resolve()
        output.mkdir(parents=True, exist_ok=False)
        return output
    parent = repo_root / "data/processed/feature_engineering"
    parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("run_%Y%m%dT%H%M%SZ")
    output = parent / stamp
    output.mkdir(exist_ok=False)
    return output


def read_gem_records(gem_dir: Path) -> pd.DataFrame:
    records = []
    for filename, label in (("coal_mines_dhanbad_jharia_bbox.json", "GEM coal mine"),
                            ("coal_plants_dhanbad_jharia_bbox.json", "GEM coal plant")):
        path = gem_dir / filename
        if not path.exists():
            continue
        obj = json.loads(path.read_text(encoding="utf-8"))
        for row in obj.get("records", []):
            lat = pd.to_numeric(row.get("latitude"), errors="coerce")
            lon = pd.to_numeric(row.get("longitude"), errors="coerce")
            lat_ok = BOUNDS[1] <= lat <= BOUNDS[3] if BOUNDS_MAX_INCLUSIVE else BOUNDS[1] <= lat < BOUNDS[3]
            lon_ok = BOUNDS[0] <= lon <= BOUNDS[2] if BOUNDS_MAX_INCLUSIVE else BOUNDS[0] <= lon < BOUNDS[2]
            if pd.notna(lat) and pd.notna(lon) and lat_ok and lon_ok:
                records.append({
                    "asset_id": row.get("asset_id"), "location_id": row.get("location_id"),
                    "name": row.get("asset_name"), "asset_type": row.get("asset_type"),
                    "source": label, "latitude": float(lat), "longitude": float(lon),
                    "operating_status": row.get("operating_status"),
                })
    return pd.DataFrame(records)


def add_gem_traceability(frame: pd.DataFrame, gem: pd.DataFrame) -> pd.DataFrame:
    """Add identifiers for the GEM nearest facility while checking matcher distances."""
    frame = frame.copy()
    new_columns = ["gem_nearest_asset_id", "gem_nearest_location_id", "gem_nearest_source",
                   "gem_nearest_operating_status"]
    for column in new_columns:
        frame[column] = pd.NA
    if gem.empty:
        return frame
    if "distance_crs" in frame:
        groups = frame.groupby("distance_crs", sort=False).groups.items()
    else:
        groups = [(DISTANCE_CRS, frame.index)]
    for crs, indices in groups:
        to_local = Transformer.from_crs("EPSG:4326", str(crs), always_xy=True)
        gx, gy = to_local.transform(gem.longitude.to_numpy(), gem.latitude.to_numpy())
        gem_points = np.asarray([Point(x, y) for x, y in zip(gx, gy)], dtype=object)
        tree = STRtree(gem_points)
        subset = frame.loc[indices]
        px, py = to_local.transform(subset.longitude.to_numpy(), subset.latitude.to_numpy())
        nearest_ix = np.asarray(tree.nearest(np.asarray([Point(x, y) for x, y in zip(px, py)], dtype=object)), dtype=int)
        nearest = gem.iloc[nearest_ix]
        for column, source_column in zip(new_columns, ("asset_id", "location_id", "source", "operating_status")):
            frame.loc[indices, column] = nearest[source_column].to_numpy()
        recomputed = np.hypot(px - gx[nearest_ix], py - gy[nearest_ix])
        observed = pd.to_numeric(subset.gem_nearest_distance_m, errors="coerce").to_numpy()
        comparable = np.isfinite(observed)
        if comparable.any() and not np.allclose(recomputed[comparable], observed[comparable], atol=0.02, rtol=0):
            delta = float(np.max(np.abs(recomputed[comparable] - observed[comparable])))
            raise ValueError(f"Recomputed GEM nearest distance differs from matcher output for {crs} (max {delta:.3f} m)")
    return frame


def add_industrial_context(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    distance_columns = {role: f"nearest_{role}_distance_m" for role in RELEVANT_ROLES}
    absent = [column for column in distance_columns.values() if column not in frame.columns]
    if absent:
        raise ValueError(f"Missing role-specific OSM distance fields: {absent}")
    values = frame[[distance_columns[r] for r in RELEVANT_ROLES]].apply(pd.to_numeric, errors="coerce")
    frame["osm_nearest_relevant_distance_m"] = values.min(axis=1, skipna=True)
    nearest_role = values.fillna(np.inf).idxmin(axis=1).str.replace("nearest_", "", regex=False).str.replace("_distance_m", "", regex=False)
    nearest_role = nearest_role.where(values.notna().any(axis=1), pd.NA)
    frame["osm_nearest_relevant_role"] = nearest_role
    frame["osm_nearest_relevant_category"] = nearest_role.map(ROLE_CATEGORY)
    frame["osm_nearest_relevant_feature_id"] = pd.NA
    # An OSM ID is traceable only when the matcher-selected nearest feature is the
    # same role as this derived nearest-relevant role; otherwise leave it unknown.
    chosen_role = frame.osm_nearest_feature_role.fillna("").str.split(";")
    agrees = [role in roles for role, roles in zip(nearest_role.fillna(""), chosen_role)]
    frame.loc[~np.asarray(agrees), "osm_nearest_relevant_feature_id"] = pd.NA
    frame["osm_evidence_status_250m"] = frame["match_status_250m"].astype("string")
    frame["osm_evidence_status_1000m"] = frame["match_status_1000m"].astype("string")
    frame["osm_context_is_ground_truth"] = False
    return frame


def add_past_only_recurrence(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    frame["_acq_date"] = pd.to_datetime(frame.acq_date, errors="coerce").dt.normalize()
    if frame["_acq_date"].isna().any():
        raise ValueError("FIRMS acquisition dates contain missing/invalid values")
    daily = (frame.groupby(["hotspot_cell_id", "_acq_date"], sort=True, as_index=False)
             .agg(_day_detections=("firms_source_row", "size"),
                  _day_frp_sum=("frp", "sum")))
    daily = daily.sort_values(["hotspot_cell_id", "_acq_date"], kind="stable").reset_index(drop=True)
    groups = daily.groupby("hotspot_cell_id", sort=False)
    daily["cell_prior_detection_count"] = groups["_day_detections"].cumsum() - daily["_day_detections"]
    daily["cell_prior_distinct_acquisition_dates"] = groups.cumcount().astype("int64")
    daily["_prior_frp_sum"] = groups["_day_frp_sum"].cumsum() - daily["_day_frp_sum"]
    daily["cell_prior_mean_frp"] = daily["_prior_frp_sum"].div(daily["cell_prior_detection_count"].replace(0, np.nan))
    daily["cell_prior_last_acquisition_date"] = groups["_acq_date"].shift(1)
    daily["cell_days_since_prior_observation"] = (daily["_acq_date"] - daily["cell_prior_last_acquisition_date"]).dt.days
    daily["cell_prior_recurring_flag"] = (daily["cell_prior_distinct_acquisition_dates"] >= 2)
    daily["cell_first_observed_in_source_window"] = daily["cell_prior_distinct_acquisition_dates"].eq(0)
    keep = ["hotspot_cell_id", "_acq_date", "cell_prior_detection_count",
            "cell_prior_distinct_acquisition_dates", "cell_prior_mean_frp",
            "cell_prior_last_acquisition_date", "cell_days_since_prior_observation",
            "cell_prior_recurring_flag", "cell_first_observed_in_source_window"]
    return frame.merge(daily[keep], on=["hotspot_cell_id", "_acq_date"], how="left", validate="many_to_one")


def add_sentinel_features(
    frame: pd.DataFrame, satellite_dir: Path | None, repo_root: Path = ROOT,
) -> tuple[pd.DataFrame, dict[str, int]]:
    frame = frame.copy()
    metadata_path = satellite_dir / "scene_metadata.csv" if satellite_dir else None
    if metadata_path is not None and not metadata_path.is_file():
        raise FileNotFoundError(f"Sentinel-2 scene metadata missing: {metadata_path}")
    metadata = (pd.read_csv(metadata_path).set_index("hotspot_cell_id", drop=False)
                if metadata_path else pd.DataFrame())
    if metadata_path is not None:
        needed = {"hotspot_cell_id", "status", "chip_path", "scene_datetime_utc"}
        missing = sorted(needed.difference(metadata.columns))
        if missing:
            raise ValueError(f"Satellite scene metadata is missing required columns: {missing}")
        if not metadata.index.is_unique:
            raise ValueError("Satellite scene metadata must contain at most one row per hotspot_cell_id")
    transformer_cache = {}
    fields = ["s2_b04_red_dn", "s2_b03_green_dn", "s2_b02_blue_dn", "s2_b11_swir16_dn"]
    for column in fields:
        frame[column] = np.nan
    no_metadata_status = "not_available_no_scene_metadata" if metadata_path is None else "not_available_no_chip"
    no_metadata_quality = "scene_metadata_not_supplied" if metadata_path is None else "not_available_no_chip"
    for column, default in {
        "s2_chip_available_for_context": False, "s2_temporally_eligible": False,
        "s2_pixel_valid": False, "s2_spectral_predictor_eligible": False,
        "s2_spectral_data_status": no_metadata_status,
        "s2_chip_cloud_quality": no_metadata_quality, "s2_scene_item_id": pd.NA,
        "s2_scene_datetime_utc": pd.NA, "s2_scene_cloud_cover_percent": np.nan,
        "s2_chip_scl_cloud_shadow_percent": np.nan, "s2_scene_offset_hours": np.nan,
        "s2_scene_offset_days": np.nan, "s2_chip_source_path": pd.NA,
    }.items():
        frame[column] = default
    frame["s2_spectral_spatial_resolution_note"] = pd.NA
    frame["s2_scl_class"] = np.nan
    frame["s2_pixel_cloud_screen_status"] = "no_sentinel_metadata"

    for cell_id, indices in frame.groupby("hotspot_cell_id", sort=False).groups.items():
        if cell_id not in metadata.index:
            continue
        meta = metadata.loc[cell_id]
        if str(meta.get("status", "")) != "chip_created" or pd.isna(meta.get("chip_path")):
            continue
        raw_chip_path = Path(str(meta.chip_path).replace("\\", "/"))
        if raw_chip_path.is_absolute():
            chip_path = raw_chip_path
        else:
            candidates = ([satellite_dir / raw_chip_path, satellite_dir / raw_chip_path.name] if satellite_dir is not None else [])
            candidates.append(repo_root / raw_chip_path)
            chip_path = next((candidate for candidate in candidates if candidate.exists()), candidates[0])
        if not chip_path.exists():
            continue
        if rasterio is None:
            raise RuntimeError("rasterio is required to sample an available Sentinel-2 chip; install requirements-satellite.txt")
        scene_time = pd.to_datetime(meta.scene_datetime_utc, utc=True)
        cloud = pd.to_numeric(meta.get("local_scl_cloud_shadow_percent", np.nan), errors="coerce")
        if pd.isna(cloud):
            cloud_quality = "cloud_quality_unavailable"
        elif cloud >= 50:
            cloud_quality = "cloud_shadow_heavy_chip"
        elif cloud >= 20:
            cloud_quality = "cloud_shadow_moderate_chip"
        else:
            cloud_quality = "low_cloud_shadow_flag_chip"
        scl_raw = meta.get("scl_chip_path", pd.NA)
        scl_path = None
        if pd.notna(scl_raw) and str(scl_raw).strip():
            raw_scl_path = Path(str(scl_raw).replace("\\", "/"))
            candidates = [raw_scl_path] if raw_scl_path.is_absolute() else [satellite_dir / raw_scl_path, satellite_dir / raw_scl_path.name, repo_root / raw_scl_path]
            scl_path = next((candidate for candidate in candidates if candidate.is_file()), None)
        # Older chips saved only a chip-wide SCL cloud fraction. Trust a sample
        # from those chips only when no cloud/shadow pixels were present.
        has_pixel_scl = scl_path is not None
        with rasterio.open(chip_path) as ds:
            if ds.crs is None or ds.count != 4:
                raise ValueError(f"Unexpected Sentinel chip schema: {chip_path}")
            to_chip = transformer_cache.setdefault(ds.crs.to_string(),
                Transformer.from_crs("EPSG:4326", ds.crs, always_xy=True))
            lon = frame.loc[indices, "longitude"].to_numpy(dtype=float)
            lat = frame.loc[indices, "latitude"].to_numpy(dtype=float)
            x, y = to_chip.transform(lon, lat)
            rows, cols = rasterio.transform.rowcol(ds.transform, x, y)
            samples = np.full((len(indices), 4), np.nan, dtype=float)
            sampled_scl = np.full(len(indices), np.nan, dtype=float)
            in_bounds = np.asarray([(0 <= r < ds.height and 0 <= c < ds.width) for r, c in zip(rows, cols)])
            scl_ds = rasterio.open(scl_path) if has_pixel_scl else None
            if scl_ds is not None and (scl_ds.count != 1 or scl_ds.crs != ds.crs or
                                       scl_ds.transform != ds.transform or scl_ds.width != ds.width or
                                       scl_ds.height != ds.height):
                scl_ds.close()
                raise ValueError(f"SCL chip grid does not align with spectral chip: {scl_path}")
            for k, (r, c) in enumerate(zip(rows, cols)):
                if in_bounds[k]:
                    values = ds.read(window=((r, r + 1), (c, c + 1)))[:, 0, 0].astype(float)
                    if np.all(values > 0):  # chip nodata is encoded as zero
                        samples[k] = values
                    if scl_ds is not None:
                        sampled_scl[k] = float(scl_ds.read(1, window=((r, r + 1), (c, c + 1)))[0, 0])
            if scl_ds is not None:
                scl_ds.close()
            raw_valid = np.isfinite(samples).all(axis=1)
            offsets = (scene_time - frame.loc[indices, "acquisition_datetime_utc"]).dt.total_seconds().to_numpy() / 3600.0
            temporal_ok = offsets <= 0  # scene acquisition must be at/before the FIRMS detection
            # Only clear land/water classes are eligible. Mask shadow, cloud,
            # cirrus, snow, unclassified, defective and nodata SCL values.
            pixel_clear = np.isin(sampled_scl, [4, 5, 6]) if has_pixel_scl else np.full(len(indices), cloud == 0)
            valid = raw_valid & temporal_ok & pixel_clear
            # A later image remains documented as available context, but its band
            # values are withheld from the row to prevent post-event leakage.
            samples[~valid] = np.nan
            frame.loc[indices, fields] = samples
            frame.loc[indices, "s2_chip_available_for_context"] = True
            frame.loc[indices, "s2_temporally_eligible"] = temporal_ok
            frame.loc[indices, "s2_pixel_valid"] = valid
            frame.loc[indices, "s2_spectral_predictor_eligible"] = valid
            status = np.where(~temporal_ok, "post_detection_imagery_withheld",
                     np.where(valid, "sampled_pre_detection_image",
                     np.where(~pixel_clear, "cloud_shadow_contaminated_or_unverified",
                              "pre_detection_pixel_nodata_or_outside")))
            frame.loc[indices, "s2_spectral_data_status"] = status
            frame.loc[indices, "s2_chip_cloud_quality"] = cloud_quality
            frame.loc[indices, "s2_scene_item_id"] = str(meta.get("selected_stac_item", meta.get("item_id", cell_id)))
            frame.loc[indices, "s2_scene_datetime_utc"] = scene_time.isoformat()
            frame.loc[indices, "s2_scene_cloud_cover_percent"] = pd.to_numeric(
                meta.get("eo_cloud_cover_percent_scene_level", meta.get("eo_cloud_cover", np.nan)), errors="coerce")
            frame.loc[indices, "s2_chip_scl_cloud_shadow_percent"] = cloud
            frame.loc[indices, "s2_scene_offset_hours"] = offsets
            frame.loc[indices, "s2_scene_offset_days"] = frame.loc[indices, "s2_scene_offset_hours"] / 24.0
            try:
                chip_display_path = chip_path.relative_to(repo_root).as_posix()
            except ValueError:
                chip_display_path = str(chip_path)
            frame.loc[indices, "s2_chip_source_path"] = chip_display_path
            frame.loc[indices, "s2_scl_class"] = sampled_scl
            frame.loc[indices, "s2_pixel_cloud_screen_status"] = np.where(
                has_pixel_scl, np.where(pixel_clear, "scl_clear_class", "scl_masked_or_nodata"),
                np.where(cloud == 0, "legacy_chip_zero_cloud_fraction", "legacy_chip_point_quality_unverifiable"))
            frame.loc[indices, "s2_spectral_spatial_resolution_note"] = "B02/B03/B04 10m; B11 native 20m resampled to 10m grid; stored integer reflectance values"
    counts = {
        "metadata_available": int(metadata_path is not None),
        "rows_with_chip_for_context": int(frame.s2_chip_available_for_context.sum()),
        "rows_with_temporally_eligible_scene": int(frame.s2_temporally_eligible.sum()),
        "rows_with_valid_causal_spectral_samples": int(frame.s2_spectral_predictor_eligible.sum()),
        "rows_with_post_detection_imagery_withheld": int(frame.s2_spectral_data_status.eq("post_detection_imagery_withheld").sum()),
        "rows_with_heavy_chip_cloud_shadow": int(frame.s2_chip_cloud_quality.eq("cloud_shadow_heavy_chip").sum()),
        "rows_with_cloud_or_unverifiable_pixel_screen": int(frame.s2_spectral_data_status.eq("cloud_shadow_contaminated_or_unverified").sum()),
        "rows_with_clear_pixel_level_scl": int(frame.s2_pixel_cloud_screen_status.eq("scl_clear_class").sum()),
    }
    return frame, counts


def add_thermal_features(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    for col in ("frp", "brightness", "bright_t31", "scan", "track", "type"):
        if col in frame.columns:
            frame[col] = pd.to_numeric(frame[col], errors="coerce")
    raw_time = pd.to_numeric(frame.acq_time, errors="coerce")
    good = raw_time.notna() & raw_time.between(0, 2359) & (raw_time.mod(100) < 60)
    hhmm = raw_time.fillna(0).astype("int64").map(lambda x: f"{x:04d}")
    timestamp = pd.to_datetime(frame.acq_date.astype(str) + " " + hhmm,
                               format="%Y-%m-%d %H%M", errors="coerce", utc=True)
    timestamp = timestamp.where(good)
    frame["acquisition_datetime_utc"] = timestamp
    frame["thermal_frp_mw"] = frame["frp"]
    frame["thermal_brightness_k"] = frame["brightness"]
    frame["thermal_brightness_t31_k"] = frame["bright_t31"]
    frame["thermal_confidence_raw"] = frame["confidence"].astype("string")
    frame["thermal_daynight"] = frame["daynight"].astype("string").str.upper()
    frame["thermal_acquisition_time_valid"] = good
    return frame


def make_feature_definitions() -> pd.DataFrame:
    defs = [
        ("firms_source_row", "Source traceability", "Zero-based row number in the FIRMS CSV passed to the matching stage; join key used by feature engineering."),
        ("firms_sources/duplicate_record_count", "FIRMS provenance", "Archive/NRT source membership and number of duplicate source rows represented by the canonical observation, when present."),
        ("latitude/longitude", "Source coordinates", "Original FIRMS WGS84 coordinates in decimal degrees."),
        ("frp, brightness, bright_t31, confidence, daynight, acq_date, acq_time", "Thermal source attributes", "Original NASA FIRMS attributes, retained; numeric thermal fields use source units, confidence remains raw categorical code."),
        ("acquisition_datetime_utc", "Thermal timing", "UTC datetime from FIRMS acquisition date and HHMM acquisition time."),
        ("hotspot_cell_id", "Spatial recurrence key", f"Fixed 250 m projected recurrence grid key using {DISTANCE_CRS}; shared across matching tiles and used only as an analysis unit, not a physical-source identifier."),
        ("cell_prior_detection_count", "Past-only recurrence", "Number of FIRMS rows in this cell on strictly earlier acquisition dates within the source history."),
        ("cell_prior_distinct_acquisition_dates", "Past-only recurrence", "Number of distinct earlier acquisition dates in this cell; same-date rows excluded."),
        ("cell_days_since_prior_observation", "Past-only recurrence", "Whole days since the most recent earlier date observed in the cell; missing for first observed date."),
        ("cell_prior_mean_frp", "Past-only recurrence", "Mean FRP of rows from strictly earlier dates in this cell."),
        ("osm_nearest_relevant_distance_m", "OSM mapped context", "Minimum precomputed UTM distance among industrial, mining, waste, industrial rail, generation and power-site roles."),
        ("osm_nearest_relevant_category/role", "OSM mapped context", "Role/category for the minimum relevant OSM role distance; contextual evidence only."),
        ("osm_evidence_status_250m/1000m", "OSM evidence indicator", "Existing matcher proximity status at stated radius; not a target or verified cause."),
        ("gem_nearest_distance_m/name/type/asset_id/location_id", "GEM supplementary context", "Nearest point from filtered GEM coal mine/plant files; repeated locations/assets remain source records and are not ground truth."),
        ("osm_gem_temporal_vintage_status", "Context vintage audit", "OSM/GEM inputs are latest available snapshots and are not historically versioned for each FIRMS date; use with caution in historical prediction."),
        ("s2_b04_red_dn, s2_b03_green_dn, s2_b02_blue_dn", "Sentinel-2 spectrum", "Sampled chip pixel values for native 10 m L2A red, green and blue bands; raw stored integer values."),
        ("s2_b11_swir16_dn", "Sentinel-2 spectrum", "Sampled B11 SWIR value; native 20 m resampled onto the 10 m chip grid in the prior chip stage."),
        ("s2_chip_available_for_context/s2_temporally_eligible", "Sentinel-2 availability", "Chip availability is audit context. Spectral values are exposed only if the image acquisition time is at/before the FIRMS detection time."),
        ("s2_pixel_valid/s2_spectral_predictor_eligible/s2_spectral_data_status", "Sentinel-2 availability", "Only valid pre-detection pixels populate spectral fields; post-detection image values are withheld. Missing values do not indicate absence."),
        ("s2_scene_datetime_utc/s2_scene_offset_hours", "Sentinel-2 timing", "Selected optical acquisition time and signed offset from FIRMS time; metadata fields are audit-only, not model inputs."),
        ("s2_scene_cloud_cover_percent/s2_chip_scl_cloud_shadow_percent/s2_chip_cloud_quality", "Sentinel-2 quality", "Catalog scene-level cloud cover and chip-level SCL cloud/shadow flags; not point-level cloud validation."),
        ("s2_scl_class/s2_pixel_cloud_screen_status", "Sentinel-2 pixel quality", "Aligned point-level SCL class; only classes 4, 5 and 6 are spectrally usable. Cloud, shadow, cirrus, snow, unclassified, defective and nodata pixels are withheld. Legacy chips without an SCL raster are usable only when the recorded chip-wide cloud/shadow fraction is exactly zero."),
        ("label/target", "Supervision", "No ground-truth label or model target is created in this feature run."),
    ]
    return pd.DataFrame(defs, columns=["feature_or_group", "group", "definition_and_limits"])


def save_plots(frame: pd.DataFrame, outdir: Path) -> None:
    plt.figure(figsize=(9, 4.5))
    daily = frame.groupby(pd.to_datetime(frame.acq_date).dt.date).agg(detections=("firms_source_row", "size"), median_frp=("thermal_frp_mw", "median"))
    ax = daily.detections.plot(color="#2369a1", linewidth=1.1, label="FIRMS observations")
    ax.set_ylabel("Observations per acquisition date")
    ax2 = ax.twinx(); daily.median_frp.plot(ax=ax2, color="#d87922", linewidth=1.0, alpha=0.8, label="Median FRP")
    ax2.set_ylabel("Median FRP (source units)")
    ax.set_title("Pilot FIRMS observations and daily median FRP")
    ax.set_xlabel("FIRMS acquisition date")
    ax.grid(alpha=0.2); plt.tight_layout(); plt.savefig(outdir / "firms_daily_thermal_summary.png", dpi=160); plt.close()

    fig, axes = plt.subplots(1, 2, figsize=(10, 4.2))
    axes[0].hist(frame.cell_prior_distinct_acquisition_dates, bins=20, color="#417d5b")
    axes[0].set_title("Earlier distinct dates in the 250 m cell")
    axes[0].set_xlabel("Prior acquisition dates (same date excluded)"); axes[0].set_ylabel("FIRMS rows")
    axes[1].scatter(frame.cell_prior_distinct_acquisition_dates, frame.thermal_frp_mw,
                    s=9, alpha=0.28, c="#704b97")
    axes[1].set_title("FRP by strictly past cell recurrence")
    axes[1].set_xlabel("Prior distinct acquisition dates"); axes[1].set_ylabel("FRP (source units)")
    fig.tight_layout(); fig.savefig(outdir / "past_only_recurrence.png", dpi=160); plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5))
    categories = frame.osm_nearest_relevant_category.fillna("no_relevant_feature")
    categories.value_counts().sort_values().plot.bar(ax=axes[0], color="#567a9f")
    axes[0].set_title("Nearest relevant OSM context")
    axes[0].set_ylabel("FIRMS rows"); axes[0].tick_params(axis="x", rotation=40)
    sampled = frame[frame.s2_pixel_valid]
    if len(sampled):
        scatter = axes[1].scatter(sampled.s2_b04_red_dn, sampled.s2_b11_swir16_dn,
                                  c=sampled.s2_chip_scl_cloud_shadow_percent, cmap="viridis", s=14, alpha=0.65)
        fig.colorbar(scatter, ax=axes[1], label="Chip SCL cloud/shadow (%)")
    axes[1].set_title("Sampled Sentinel-2 chip values (context only)")
    axes[1].set_xlabel("B04 red stored value"); axes[1].set_ylabel("B11 SWIR16 stored value")
    fig.tight_layout(); fig.savefig(outdir / "mapped_context_and_sentinel_features.png", dpi=160); plt.close(fig)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=ROOT, help="repository root for relative input paths")
    parser.add_argument("--region", default="dhanbad_jharia_bokaro", help="shared region ID (default: existing pilot)")
    parser.add_argument("--region-config", type=Path, default=DEFAULT_REGION_CONFIG, help="shared region JSON")
    parser.add_argument("--firms", type=Path, default=Path("data/processed/firms_pilot.csv"),
                        help="same FIRMS CSV supplied to the matching stage")
    parser.add_argument("--osm", type=Path, default=Path("data/processed/osm/dhanbad_jharia_bokaro_osm.gpkg"),
                        help="OSM GeoPackage used by the matching stage")
    parser.add_argument("--matching-dir", type=Path, required=True,
                        help="matching run directory containing firms_pilot_osm_proximity.csv")
    parser.add_argument("--gem-dir", type=Path, default=Path("data/processed/gem"),
                        help="optional directory containing filtered GEM JSON files")
    parser.add_argument("--satellite-dir", type=Path,
                        help="satellite run directory containing scene_metadata.csv and chips; defaults to latest compatible run")
    parser.add_argument("--output-dir", type=Path,
                        help="new feature output directory; defaults to a timestamped directory")
    return parser


def resolve_path(path: Path | None, root: Path) -> Path | None:
    if path is None:
        return None
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def display_path(path: Path | None, root: Path) -> str:
    if path is None:
        return "not supplied"
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def discover_satellite_run(root: Path) -> Path | None:
    """Return the newest run with readable metadata and at least one chip."""
    parent = root / "data/processed/satellite_investigation"
    if not parent.is_dir():
        return None
    for candidate in sorted(parent.glob("run_*"), key=lambda p: p.name, reverse=True):
        metadata = candidate / "scene_metadata.csv"
        if not metadata.is_file():
            continue
        try:
            table = pd.read_csv(metadata)
        except (OSError, pd.errors.ParserError, UnicodeDecodeError):
            continue
        if "chip_path" not in table:
            continue
        for raw in table.chip_path.dropna().astype(str):
            p = Path(raw.replace("\\", "/"))
            options = [p] if p.is_absolute() else [candidate / p, root / p]
            if any(option.is_file() for option in options):
                return candidate
    return None


def validate_source_alignment(source: pd.DataFrame, matched: pd.DataFrame) -> pd.DataFrame:
    """Validate matcher row IDs and preserve every FIRMS source attribute."""
    if "firms_source_row" not in matched or not matched.firms_source_row.is_unique:
        raise ValueError("Matching output must have a unique firms_source_row key")
    matched = matched.copy()
    matched["firms_source_row"] = pd.to_numeric(matched.firms_source_row, errors="raise").astype("int64")
    if (matched.firms_source_row < 0).any() or (matched.firms_source_row >= len(source)).any():
        raise ValueError("Matching output contains FIRMS source row IDs outside the source file")
    # Verify every retained source attribute against its source row before using the
    # matching output as the joined feature base.
    aligned_source = source.iloc[matched.firms_source_row.to_numpy()].reset_index(drop=True)
    for column in source.columns:
        if column not in matched.columns:
            raise ValueError(f"Matcher omitted original FIRMS attribute {column}")
        left, right = matched[column].reset_index(drop=True), aligned_source[column]
        same = left.fillna("__THERMOSCOPE_NA__").astype(str).equals(right.fillna("__THERMOSCOPE_NA__").astype(str))
        if not same:
            raise ValueError(f"FIRMS source attribute mismatch after row join: {column}")
    return matched


def main(argv: list[str] | None = None) -> None:
    global BOUNDS, DISTANCE_CRS, REGION_ID, BOUNDS_MAX_INCLUSIVE
    args = build_parser().parse_args(argv)
    root = args.repo.resolve()
    try:
        region = get_region(args.region, args.region_config)
        BOUNDS = bounds_tuple(region)
        DISTANCE_CRS = str(region.get("recurrence_grid_crs", "EPSG:6933")) if region.get("tiling") else select_projected_crs(region)
        BOUNDS_MAX_INCLUSIVE = bool(region.get("max_inclusive", False))
    except RegionConfigurationError as exc:
        raise ValueError(f"Cannot engineer features for region {args.region!r}: {exc}") from exc
    REGION_ID = args.region
    firms_path = resolve_path(args.firms, root)
    osm_path = resolve_path(args.osm, root)
    matching_dir = resolve_path(args.matching_dir, root)
    gem_dir = resolve_path(args.gem_dir, root)
    satellite_dir = resolve_path(args.satellite_dir, root)
    # The existing local Sentinel-2 runs are Dhanbad purposive chips. Never
    # auto-attach them to a different region simply because their folder is newest.
    if satellite_dir is None and REGION_ID == "dhanbad_jharia_bokaro":
        satellite_dir = discover_satellite_run(root)
    output_dir = resolve_path(args.output_dir, root)
    match_path = matching_dir / "firms_pilot_osm_proximity.csv"
    required = [firms_path, osm_path, match_path]
    missing = [path for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Missing required input file(s): {[str(path) for path in missing]}")
    if satellite_dir is not None and not (satellite_dir / "scene_metadata.csv").is_file():
        raise FileNotFoundError(f"Sentinel-2 scene metadata missing: {satellite_dir / 'scene_metadata.csv'}")

    source = pd.read_csv(firms_path, low_memory=False)
    matched = pd.read_csv(match_path, low_memory=False)
    feature_required = {"latitude", "longitude", "acq_date", "acq_time", "brightness", "bright_t31", "frp", "confidence", "daynight"}
    absent = sorted(feature_required.difference(source.columns))
    if absent:
        raise ValueError(f"FIRMS input is missing feature-engineering columns: {absent}")
    matched = validate_source_alignment(source, matched)
    lon = pd.to_numeric(matched.longitude, errors="coerce")
    lat = pd.to_numeric(matched.latitude, errors="coerce")
    in_region = contains_coordinates(lon, lat, region)
    if not in_region.all():
        raise ValueError(f"Matching rows contain coordinates outside region {REGION_ID!r} bounds")
    expected_ids = assign_recurrence_grid(lon.to_numpy(), lat.to_numpy(), region, GRID_SIZE_M)
    grid_matches = np.asarray(expected_ids) == matched.hotspot_cell_id.astype(str).to_numpy()
    if not grid_matches.all():
        raise ValueError(f"250 m grid ID coordinate check failed for {(~grid_matches).sum()} rows")
    if matched.empty:
        raise ValueError("Matching output contains no pilot FIRMS detections")
    if "firms_observation_id" in matched and matched.firms_observation_id.duplicated().any():
        raise ValueError("Matching output contains duplicate stable FIRMS observation IDs")
    if "region_id" in matched and set(matched.region_id.dropna().astype(str)) - {REGION_ID}:
        raise ValueError("Matching output region_id does not match the requested feature region")
    if region.get("tiling"):
        needed_tile_fields = {"tile_id", "distance_crs", "region_id"}
        if not needed_tile_fields.issubset(matched.columns):
            raise ValueError(f"Tiled matching output is missing fields: {sorted(needed_tile_fields - set(matched.columns))}")
        expected_tiles = assign_tile_ids(lon.to_numpy(), lat.to_numpy(), region)
        if not np.array_equal(np.asarray(expected_tiles), matched.tile_id.astype(str).to_numpy()):
            raise ValueError("Matching tile IDs do not agree with unique shared-region assignment")
        for tile_id, indices in matched.groupby("tile_id", sort=False).groups.items():
            expected_tile = tile_for_coordinate(float(lon.iloc[indices[0]]), float(lat.iloc[indices[0]]), region)
            if expected_tile is None or expected_tile["tile_id"] != tile_id:
                raise ValueError(f"Invalid tile assignment for {tile_id}")
            observed_crs = set(matched.loc[indices, "distance_crs"].astype(str))
            if observed_crs != {expected_tile["projected_crs"]}:
                raise ValueError(f"Tile {tile_id} used inconsistent projected CRS values: {observed_crs}")
    outdir = make_output_dir(output_dir, root)

    result = add_thermal_features(matched)
    if not result.thermal_acquisition_time_valid.all():
        raise ValueError("Invalid FIRMS acquisition HHMM values detected")
    result = add_past_only_recurrence(result)
    result = add_industrial_context(result)
    gem = read_gem_records(gem_dir)
    result = add_gem_traceability(result, gem)
    result["osm_gem_temporal_vintage_status"] = "latest_snapshot_unversioned_for_detection_date"
    result, sat_counts = add_sentinel_features(result, satellite_dir, root)
    result["thermal_confidence_raw"] = result.thermal_confidence_raw.astype("string")
    result["osm_nearest_relevant_category"] = result.osm_nearest_relevant_category.astype("string")
    result["s2_chip_available_for_context"] = result.s2_chip_available_for_context.astype("bool")
    result["s2_temporally_eligible"] = result.s2_temporally_eligible.astype("bool")
    result["s2_pixel_valid"] = result.s2_pixel_valid.astype("bool")
    result["s2_spectral_predictor_eligible"] = result.s2_spectral_predictor_eligible.astype("bool")
    result["s2_spectral_data_status"] = result.s2_spectral_data_status.astype("string")
    result["s2_chip_cloud_quality"] = result.s2_chip_cloud_quality.astype("string")
    result["cell_prior_detection_count"] = result.cell_prior_detection_count.astype("int64")
    result["cell_prior_distinct_acquisition_dates"] = result.cell_prior_distinct_acquisition_dates.astype("int64")
    result["cell_prior_recurring_flag"] = result.cell_prior_recurring_flag.astype("bool")
    result["cell_first_observed_in_source_window"] = result.cell_first_observed_in_source_window.astype("bool")

    # Explicit leakage audit: no prior history row has the same or a later date.
    if not (result.loc[result.cell_prior_last_acquisition_date.notna(), "cell_prior_last_acquisition_date"] <
            result.loc[result.cell_prior_last_acquisition_date.notna(), "_acq_date"]).all():
        raise ValueError("Temporal recurrence includes same-date or future information")
    result.drop(columns=["_acq_date"], inplace=True)  # internal recurrence join key, not a model feature
    if result.firms_source_row.duplicated().any() or len(result) != len(matched):
        raise ValueError("Feature table row cardinality changed unexpectedly")
    if result[["latitude", "longitude"]].isna().any().any():
        raise ValueError("Missing detection coordinates in feature table")
    if result.s2_pixel_valid.ne(result[["s2_b04_red_dn", "s2_b03_green_dn", "s2_b02_blue_dn", "s2_b11_swir16_dn"]].notna().all(axis=1)).any():
        raise ValueError("Sentinel sampled-pixel validity flag disagrees with spectral values")
    if (result.loc[result.s2_scene_offset_hours > 0, ["s2_b04_red_dn", "s2_b03_green_dn", "s2_b02_blue_dn", "s2_b11_swir16_dn"]].notna().any().any()):
        raise ValueError("Post-detection Sentinel-2 spectral values leaked into features")
    if any(c.lower() in {"label", "target", "ground_truth", "ground_truth_label", "model_target"} for c in result.columns):
        raise ValueError("Unexpected label/target column detected")

    result["cell_prior_last_acquisition_date"] = pd.to_datetime(result.cell_prior_last_acquisition_date, errors="coerce").dt.strftime("%Y-%m-%d")
    result.to_csv(outdir / "feature_table.csv.gz", index=False, compression="gzip")
    schema = {
        "format": "CSV gzip; UTF-8; header row",
        "row_grain": f"one row per FIRMS detection in region {REGION_ID}",
        "region_id": REGION_ID,
        "primary_key": "firms_source_row",
        "column_dtypes_before_serialization": {column: str(dtype) for column, dtype in result.dtypes.items()},
        "parse_as_utc_datetime": ["acquisition_datetime_utc", "s2_scene_datetime_utc"],
        "parse_as_iso_date": ["acq_date", "cell_prior_last_acquisition_date"],
        "coordinate_order": "latitude, longitude; WGS84 EPSG:4326",
        "distance_units": "metres; OSM/GEM distances use the row's tile-local distance_crs when tiled; recurrence uses the region's configured grid CRS " + DISTANCE_CRS,
        "missing_sentinel_spectral_value": "empty CSV field / NaN; not evidence of absence",
        "audit_only_columns": ["s2_chip_available_for_context", "s2_scene_item_id", "s2_scene_datetime_utc", "s2_scene_cloud_cover_percent", "s2_chip_scl_cloud_shadow_percent", "s2_scene_offset_hours", "s2_scene_offset_days", "s2_chip_cloud_quality", "s2_scl_class", "s2_pixel_cloud_screen_status", "s2_chip_source_path", "osm_gem_temporal_vintage_status", "gem_nearest_operating_status"],
    }
    (outdir / "feature_schema.json").write_text(json.dumps(schema, indent=2, default=str), encoding="utf-8")
    definitions = make_feature_definitions()
    definitions.to_csv(outdir / "feature_definitions.csv", index=False)

    missing = pd.DataFrame({
        "column": result.columns,
        "dtype_in_memory": [str(result[c].dtype) for c in result.columns],
        "missing_count": [int(result[c].isna().sum()) for c in result.columns],
        "missing_percent": [round(float(result[c].isna().mean() * 100), 4) for c in result.columns],
    })
    missing.to_csv(outdir / "feature_missingness.csv", index=False)
    save_plots(result, outdir)

    checks = {
        "overall_status": "passed",
        "source_rows": int(len(source)), "region_feature_rows": int(len(result)),
        "source_paths": {
            "firms": display_path(firms_path, root), "osm": display_path(osm_path, root),
            "matching_csv": display_path(match_path, root),
            "gem_directory": display_path(gem_dir, root),
            "satellite_directory": display_path(satellite_dir, root),
        },
        "unique_firms_source_rows": int(result.firms_source_row.nunique()),
        "duplicate_source_row_ids": int(result.firms_source_row.duplicated().sum()),
        "source_attribute_alignment": "passed for every original FIRMS column",
        "region_bbox_coordinate_check": "passed", "projected_grid_id_check": "passed",
        "grid_crs": DISTANCE_CRS, "grid_size_m": GRID_SIZE_M,
        "temporal_leakage_check": "passed; all recurrence source dates strictly earlier than detection date; same-date rows excluded",
        "invalid_firms_datetime_count": int((~result.thermal_acquisition_time_valid).sum()),
        "valid_firms_coordinates_count": int(result[["latitude", "longitude"]].notna().all(axis=1).sum()),
        "osm_evidence_status_counts_250m": result.osm_evidence_status_250m.value_counts(dropna=False).to_dict(),
        "gem_records_loaded": int(len(gem)),
        "gem_distance_matcher_consistency": "passed (nearest distance recomputed from filtered GEM files)",
        "sentinel2": sat_counts,
        "sentinel2_missing_pixel_value_count_by_band": {c: int(result[c].isna().sum()) for c in ["s2_b04_red_dn", "s2_b03_green_dn", "s2_b02_blue_dn", "s2_b11_swir16_dn"]},
        "ground_truth_labels_available": False,
        "osm_gem_temporal_vintage": "static snapshots; no historical as-of date available",
        "ground_truth_label_created": False,
        "proximity_status_interpretation": "evidence indicator only, not label",
        "source_dates": {"minimum": str(pd.to_datetime(result.acq_date).min().date()), "maximum": str(pd.to_datetime(result.acq_date).max().date())},
        "missingness_report": "feature_missingness.csv",
        "feature_table_serialization": "gzip CSV; restore output types using feature_schema.json",
    }
    (outdir / "quality_checks.json").write_text(json.dumps(checks, indent=2, default=str), encoding="utf-8")

    conf = result.thermal_confidence_raw.value_counts(dropna=False).to_dict()
    cloud_counts = result.loc[result.s2_chip_available_for_context, "s2_chip_cloud_quality"].value_counts().to_dict()
    summary = f"""# ThermoScope feature engineering: {REGION_ID}\n\n## Run\n\n- Output: `{display_path(outdir, root)}`\n- Inputs: FIRMS `{display_path(firms_path, root)}`; OSM GeoPackage `{display_path(osm_path, root)}` and role-specific distances from matching `{display_path(match_path, root)}`; GEM directory `{display_path(gem_dir, root)}`; Sentinel-2 chips and metadata from `{display_path(satellite_dir, root)}`.\n- FIRMS source provenance fields such as `firms_sources` and `duplicate_record_count` are retained from the input CSV.\n- Rows: {len(result):,}; unique FIRMS source rows: {result.firms_source_row.nunique():,}; acquisition dates: {pd.to_datetime(result.acq_date).nunique():,} ({pd.to_datetime(result.acq_date).min().date()} to {pd.to_datetime(result.acq_date).max().date()}).\n\n## Feature readiness\n\n- **Thermal/time:** FIRMS FRP, brightness, T31, confidence, day/night, acquisition HHMM, platform/sensor metadata, scan/track and original attributes are retained. Confidence is categorical (`{conf}`), not an ordered numeric score. Acquisition datetime is parsed as UTC.\n- **Temporal:** Each row has prior observation count, prior distinct acquisition dates, prior mean FRP, days since the last prior date, and prior recurrence flag within its 250 m {DISTANCE_CRS} recurrence grid cell. Features use only strictly earlier `acq_date` values; same-day observations are excluded. The observed history begins at {pd.to_datetime(result.acq_date).min().date()}, so it is left-truncated to available FIRMS data. Cells are grid units, not physical sources.\n- **OSM:** Role-specific matcher distances are retained, with a derived nearest relevant industrial/mining/waste/industrial-rail/power-generation/site role and category. At 250 m the proximity evidence counts are `{result.osm_evidence_status_250m.value_counts().to_dict()}`; these statuses are evidence indicators, not causes or labels. General transmission lines/towers are retained in the original OSM context fields but excluded from the “nearest relevant industrial context” distance. OSM/GEM are unversioned current snapshots, not verified historical infrastructure states at each FIRMS date; treat their time-varying status as audit-only in strict historical prediction.\n- **GEM:** Nearest GEM name/type/distance are retained; nearest asset/location identifiers and source/status were added from the filtered GEM files. GEM is supplementary and covers coal mine/plant assets, not all industrial facilities.\n- **Sentinel-2:** {sat_counts['rows_with_chip_for_context']:,} rows have a chip for contextual audit. {sat_counts['rows_with_post_detection_imagery_withheld']:,} rows use images acquired after the FIRMS detection and have spectral values withheld to prevent future-image leakage. Only {sat_counts['rows_with_valid_causal_spectral_samples']:,} rows retain temporally eligible, cloud-screened spectral samples ({sat_counts['rows_with_valid_causal_spectral_samples']/len(result)*100:.3f}% of rows). Pixel-level SCL classes 4/5/6 are accepted; cloud/shadow and uncertain pixels are masked. Older chips without an SCL raster are used only when their recorded chip-wide cloud/shadow fraction is exactly zero. Chip-level cloud quality is `{cloud_counts}`. B11 is native 20 m resampled onto a 10 m chip grid. Scene time and signed offset are included as audit-only metadata. Missing imagery or withheld future imagery is not evidence of absence.\n\n## Labels and limits\n\nNo credible ground-truth labels are available in these inputs. This pipeline creates no label or model target. OSM proximity, GEM proximity, recurrence, and spectral values are context features only. The engineered table is ready for exploratory analysis and feature pipeline development; supervised model training is not yet supported until independently reviewed labels with documented evidence and temporal validation are assembled.\n\n## Artifacts\n\n- `feature_table.csv.gz`: one row per FIRMS detection in {REGION_ID}, with original attributes and traceable source IDs.\n- `feature_definitions.csv`: feature meanings and limitations; `feature_schema.json`: dtypes and parse instructions.\n- `feature_missingness.csv`, `quality_checks.json`: type, missingness, coordinate, row, grid, and leakage checks.\n- `firms_daily_thermal_summary.png`, `past_only_recurrence.png`, `mapped_context_and_sentinel_features.png`: exploratory summaries only.\n"""
    (outdir / "summary_report.md").write_text(summary, encoding="utf-8")
    print(f"Feature engineering complete: {outdir}")
    print(json.dumps({"rows": len(result), "columns": len(result.columns), "satellite": sat_counts,
                      "labels_available": False, "quality": checks["overall_status"]}, indent=2))


if __name__ == "__main__":
    main()
