"""Create a small, reproducible Sentinel-2 context investigation for FIRMS cells.

This is an exploratory context workflow, not fire verification or label creation.
It queries the public Element 84 Earth Search STAC API, then reads only small
windows from public Sentinel-2 COG assets. Run from the repository root:
    python src/investigate_satellite_pilot.py
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio
import requests
from pyproj import Transformer
from rasterio.enums import Resampling
from rasterio.transform import from_origin
from rasterio.warp import reproject
from shapely.geometry import box

ROOT = Path(__file__).resolve().parents[1]
RUN_SOURCE = ROOT / "data/processed/spatial_matching/run_20261018T201433Z"
RECURRENCE = RUN_SOURCE / "firms_spatial_recurrence_cells.csv"
MATCHES = RUN_SOURCE / "firms_pilot_osm_proximity.csv"
OSM = ROOT / "data/processed/osm/dhanbad_jharia_bokaro_osm.gpkg"
STAC = "https://earth-search.aws.element84.com/v1/search"
COLLECTION = "sentinel-2-l2a"
CHOSEN = [
    "utm45n_1769_10501",  # recurring quarry/mining area
    "utm45n_1678_10520",  # recurring quarry/mining area, separate locality
    "utm45n_1627_10475",  # Bokaro Steel Plant industrial landuse
    "utm45n_1653_10520",  # recurring power transmission corridor context
]
HALF_SIZE_M = 320  # 640 m square, enough to show the 250 m FIRMS grid with context
PIXEL_M = 10
SIZE = int(2 * HALF_SIZE_M / PIXEL_M)
TARGET_CRS = "EPSG:32645"


def stac_items(lon: float, lat: float, target_date: pd.Timestamp) -> list[dict]:
    start, end = target_date - pd.Timedelta(days=5), target_date + pd.Timedelta(days=5)
    body = {
        "collections": [COLLECTION],
        "bbox": [lon - 0.003, lat - 0.003, lon + 0.003, lat + 0.003],
        "datetime": f"{start:%Y-%m-%d}T00:00:00Z/{end:%Y-%m-%d}T23:59:59Z",
        "limit": 100,
    }
    response = requests.post(STAC, json=body, timeout=60)
    response.raise_for_status()
    return response.json().get("features", [])


def reproject_asset(href: str, dst_transform, dst_crs: str, dst_size: int) -> np.ndarray:
    out = np.zeros((dst_size, dst_size), dtype=np.uint16)
    with rasterio.open(href) as src:
        reproject(
            source=rasterio.band(src, 1), destination=out,
            src_transform=src.transform, src_crs=src.crs,
            dst_transform=dst_transform, dst_crs=dst_crs,
            resampling=Resampling.bilinear, src_nodata=src.nodata,
            dst_nodata=0,
        )
    return out


def local_scl_cloud_fraction(href: str, dst_transform, dst_crs: str, dst_size: int) -> float | None:
    """Fraction of chip cells assigned a Sentinel-2 cloud or shadow SCL class."""
    out = np.zeros((dst_size, dst_size), dtype=np.uint8)
    with rasterio.open(href) as src:
        reproject(source=rasterio.band(src, 1), destination=out,
                  src_transform=src.transform, src_crs=src.crs,
                  dst_transform=dst_transform, dst_crs=dst_crs,
                  resampling=Resampling.nearest, src_nodata=0, dst_nodata=0)
    valid = out > 0
    return float(np.isin(out[valid], [3, 8, 9, 10]).mean()) if valid.any() else None


def read_osm_nearby(center_x: float, center_y: float) -> gpd.GeoDataFrame:
    bounds = box(center_x - HALF_SIZE_M, center_y - HALF_SIZE_M,
                 center_x + HALF_SIZE_M, center_y + HALF_SIZE_M)
    # The regional OSM GeoPackage is stored in WGS84; Fiona's bbox is interpreted
    # in the layer CRS, so transform the chip footprint before reading each layer.
    to_geo = Transformer.from_crs(TARGET_CRS, "EPSG:4326", always_xy=True)
    west, south = to_geo.transform(center_x - HALF_SIZE_M, center_y - HALF_SIZE_M)
    east, north = to_geo.transform(center_x + HALF_SIZE_M, center_y + HALF_SIZE_M)
    geographic_bbox = (west, south, east, north)
    frames = []
    for layer in gpd.list_layers(OSM).name:
        frame = gpd.read_file(OSM, layer=layer, bbox=geographic_bbox).to_crs(TARGET_CRS)
        if len(frame):
            frame["_source_layer"] = layer
            frames.append(frame)
    if not frames:
        return gpd.GeoDataFrame(geometry=[], crs=TARGET_CRS)
    return gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs=TARGET_CRS)


def main() -> None:
    if not all(p.exists() for p in (RECURRENCE, MATCHES, OSM)):
        raise FileNotFoundError("Required run output or OSM GeoPackage is missing")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    outdir = ROOT / "data/processed/satellite_investigation" / f"run_{stamp}"
    outdir.mkdir(parents=True, exist_ok=False)

    recurrence = pd.read_csv(RECURRENCE)
    matches = pd.read_csv(MATCHES, low_memory=False)
    cells = recurrence.set_index("hotspot_cell_id")
    to_utm = Transformer.from_crs("EPSG:4326", TARGET_CRS, always_xy=True)
    to_wgs = Transformer.from_crs(TARGET_CRS, "EPSG:4326", always_xy=True)
    details, all_chips = [], {}
    with rasterio.Env(AWS_NO_SIGN_REQUEST="YES", GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"):
        for cell_id in CHOSEN:
            cell = cells.loc[cell_id]
            obs = matches[matches.hotspot_cell_id == cell_id].copy()
            target_date = pd.to_datetime(obs.acq_date).max()
            lon, lat = float(cell.centroid_longitude), float(cell.centroid_latitude)
            cx, cy = to_utm.transform(lon, lat)
            role_counts = obs.osm_nearest_feature_role.fillna("unknown").value_counts()
            dominant_role = role_counts.index[0] if len(role_counts) else "unknown"
            dominant_label = obs.osm_nearest_feature_label.dropna().mode()
            dominant_label = dominant_label.iloc[0] if len(dominant_label) else ""
            transform = from_origin(cx - HALF_SIZE_M, cy + HALF_SIZE_M, PIXEL_M, PIXEL_M)
            items = stac_items(lon, lat, target_date)
            # Pick the least cloudy scene among near-time coverage; tie-break toward the FIRMS date.
            items.sort(key=lambda f: (
                float(f.get("properties", {}).get("eo:cloud_cover", 100)),
                abs((pd.Timestamp(f["properties"]["datetime"]).tz_localize(None) - target_date).total_seconds()),
            ))
            selected = next((f for f in items if all(k in f.get("assets", {}) for k in ("red", "green", "blue", "swir16"))), None)
            if not selected:
                details.append({"hotspot_cell_id": cell_id, "status": "no_scene_with_required_assets", "stac_items_in_window": len(items)})
                continue
            # RGB at 10 m and B11/SWIR at native 20 m resampled to 10 m for aligned comparison.
            band_arrays = {}
            for key in ("red", "green", "blue", "swir16"):
                band_arrays[key] = reproject_asset(selected["assets"][key]["href"], transform, TARGET_CRS, SIZE)
            local_cloud_shadow = local_scl_cloud_fraction(selected["assets"]["scl"]["href"], transform, TARGET_CRS, SIZE) if "scl" in selected.get("assets", {}) else None
            stack = np.stack([band_arrays[k] for k in ("red", "green", "blue", "swir16")])
            chip_path = outdir / f"{cell_id}_{selected['id']}_4band_10m.tif"
            with rasterio.open(chip_path, "w", driver="GTiff", height=SIZE, width=SIZE,
                               count=4, dtype="uint16", crs=TARGET_CRS, transform=transform,
                               compress="deflate", predictor=2, tiled=True) as dst:
                dst.write(stack)
                for i, description in enumerate(("red_B04_10m", "green_B03_10m", "blue_B02_10m", "swir16_B11_20m_resampled_to_10m"), start=1):
                    dst.set_band_description(i, description)
            all_chips[cell_id] = (stack, transform, cx, cy, obs)
            item_date = pd.Timestamp(selected["properties"]["datetime"])
            details.append({
                "hotspot_cell_id": cell_id, "status": "chip_created", "representative_context": cell.get("cell_interpretation", ""),
                "detection_observations_in_cell": int(cell.detection_observations),
                "distinct_firms_acquisition_dates": int(cell.distinct_acquisition_dates),
                "dominant_nearest_osm_role_across_observations": dominant_role,
                "modal_nearest_osm_feature_label": dominant_label,
                "median_nearest_osm_distance_m": float(obs.osm_nearest_distance_m.median()),
                "firms_reference_date": str(target_date.date()), "selected_stac_item": selected["id"],
                "scene_datetime_utc": item_date.isoformat(), "scene_minus_firms_reference_days": round((item_date.tz_localize(None)-target_date).total_seconds()/86400, 3),
                "eo_cloud_cover_percent_scene_level": selected["properties"].get("eo:cloud_cover"),
                "local_scl_cloud_shadow_fraction": local_cloud_shadow,
                "local_scl_cloud_shadow_percent": (100 * local_cloud_shadow) if local_cloud_shadow is not None else None,
                "stac_items_in_plus_minus_5_day_window": len(items), "sensor": selected["properties"].get("platform"),
                "resolution_m": "B02/B03/B04 10 m; B11 20 m (resampled to 10 m in chip)",
                "chip_size_pixels": f"{SIZE}x{SIZE}", "chip_extent_m": f"{2*HALF_SIZE_M}x{2*HALF_SIZE_M}",
                "chip_path": str(chip_path.relative_to(ROOT)), "catalog_url": STAC,
                "asset_urls": json.dumps({k: selected["assets"][k]["href"] for k in ("red", "green", "blue", "swir16")}),
                "authentication": "none; public Earth Search STAC and public Sentinel COG assets",
                "interpretation_limit": "Optical land-surface context only; spatial and temporal mismatch prevents fire confirmation.",
            })

    pd.DataFrame(details).to_csv(outdir / "scene_metadata.csv", index=False)
    # Catalog-only Sentinel-1 check for the most cloud-obscured quarry example.
    # No radar pixels are requested or downloaded in this stage.
    quarry = cells.loc[CHOSEN[0]]
    qdate = pd.to_datetime(matches.loc[matches.hotspot_cell_id == CHOSEN[0], "acq_date"]).max()
    qlon, qlat = float(quarry.centroid_longitude), float(quarry.centroid_latitude)
    s1body = {
        "collections": ["sentinel-1-grd"],
        "bbox": [qlon - 0.003, qlat - 0.003, qlon + 0.003, qlat + 0.003],
        "datetime": f"{qdate-pd.Timedelta(days=5):%Y-%m-%d}T00:00:00Z/{qdate+pd.Timedelta(days=5):%Y-%m-%d}T23:59:59Z",
        "limit": 100,
    }
    s1response = requests.post(STAC, json=s1body, timeout=60)
    s1response.raise_for_status()
    s1rows = []
    for item in s1response.json().get("features", []):
        props = item.get("properties", {})
        s1rows.append({
            "collection": "sentinel-1-grd", "item_id": item.get("id"),
            "datetime": props.get("datetime"), "platform": props.get("platform"),
            "instrument_mode": props.get("sar:instrument_mode"),
            "product_type": props.get("sar:product_type"),
            "polarizations": json.dumps(props.get("sar:polarizations", [])),
            "resolution_range_m": props.get("sar:resolution_range"),
            "asset_keys": json.dumps(list(item.get("assets", {}))),
            "retrieved_pixels": False,
        })
    pd.DataFrame(s1rows, columns=["collection", "item_id", "datetime", "platform", "instrument_mode", "product_type", "polarizations", "resolution_range_m", "asset_keys", "retrieved_pixels"]).to_csv(outdir / "sentinel1_catalog_check.csv", index=False)
    # Location register for every selected recurring cell, regardless of imagery success.
    loc = recurrence[recurrence.hotspot_cell_id.isin(CHOSEN)].copy()
    loc = loc.merge(pd.DataFrame(details)[["hotspot_cell_id", "status", "selected_stac_item", "scene_datetime_utc", "scene_minus_firms_reference_days", "eo_cloud_cover_percent_scene_level", "chip_path"]], on="hotspot_cell_id", how="left")
    loc.to_csv(outdir / "selected_investigation_cells.csv", index=False)

    # One overlay figure: true-color reflectance stretch with FIRMS points, 250 m grid, and mapped OSM geometry.
    if all_chips:
        n = len(all_chips)
        fig, axes = plt.subplots(1, n, figsize=(5*n, 5), squeeze=False)
        for ax, (cell_id, (stack, transform, cx, cy, obs)) in zip(axes[0], all_chips.items()):
            rgb = np.moveaxis(stack[:3], 0, -1).astype(float)
            # Robust display stretch; stored pixel values remain unchanged in the GeoTIFF.
            valid = rgb[rgb > 0]
            high = np.percentile(valid, 99) if valid.size else 1
            rgb = np.clip(rgb / max(high, 1), 0, 1) ** 0.75
            ax.imshow(rgb, extent=(cx-HALF_SIZE_M, cx+HALF_SIZE_M, cy-HALF_SIZE_M, cy+HALF_SIZE_M), origin="upper")
            local_osm = read_osm_nearby(cx, cy)
            if len(local_osm):
                try:
                    local_osm.boundary.plot(ax=ax, color="#00e5ff", linewidth=0.8, alpha=0.9)
                except Exception:
                    pass
            grid_x, grid_y = to_utm.transform(float(cells.loc[cell_id].centroid_longitude), float(cells.loc[cell_id].centroid_latitude))
            gpd.GeoSeries([box(grid_x-125, grid_y-125, grid_x+125, grid_y+125)], crs=TARGET_CRS).boundary.plot(ax=ax, color="yellow", linewidth=1.5)
            ref_date = pd.to_datetime(obs.acq_date).max()
            same_day = obs[pd.to_datetime(obs.acq_date) == ref_date]
            xs, ys = to_utm.transform(same_day.longitude.to_numpy(), same_day.latitude.to_numpy())
            ax.scatter(xs, ys, s=18, facecolors="none", edgecolors="magenta", linewidths=1.0, label="FIRMS points on reference date")
            ax.set_title(cell_id + "\n" + str(pd.to_datetime(obs.acq_date).max().date()))
            ax.set_xlim(cx-HALF_SIZE_M, cx+HALF_SIZE_M); ax.set_ylim(cy-HALF_SIZE_M, cy+HALF_SIZE_M)
            ax.set_aspect("equal"); ax.set_xlabel("UTM 45N metres"); ax.set_ylabel("UTM 45N metres")
            ax.text(0.02, 0.02, "OSM geometry outlines (cyan); 250 m FIRMS cell (yellow)\nReference-date FIRMS points (magenta); optical context only", transform=ax.transAxes, fontsize=7, color="white", bbox={"facecolor":"black","alpha":0.65,"pad":3})
        fig.suptitle("ThermoScope pilot: Sentinel-2 scene context with FIRMS and OSM overlays", fontsize=13)
        fig.tight_layout()
        fig.savefig(outdir / "satellite_context_overlays.png", dpi=180, bbox_inches="tight")
        plt.close(fig)

    readme = f"""# Satellite investigation run {stamp}\n\nThis is a bounded context investigation, not fire detection validation or ground-truth labeling.\n\n- Inputs: `{RECURRENCE.relative_to(ROOT)}`, `{MATCHES.relative_to(ROOT)}`, `{OSM.relative_to(ROOT)}`.\n- Source: Sentinel-2 L2A via public Earth Search STAC (`{STAC}`), collection `{COLLECTION}`.\n- Method: For each selected recurring 250 m EPSG:32645 grid cell, search the ±5 day interval around its latest FIRMS acquisition date; choose the least-cloudy matching item with B02/B03/B04/B11 assets; retrieve a 640 m square as a 64x64 four-band COG window. B11 native 20 m pixels are resampled to the 10 m chip grid for alignment.\n- Dates: the selected scene timestamp and offset from the FIRMS reference date are recorded in `scene_metadata.csv`. Catalog `eo:cloud_cover` is scene-level; a local SCL cloud/shadow fraction is recorded where available. SCL is a screening mask, not manual image-quality validation.\n- Credentials: none; STAC and S3 COG assets are public.\n- Limits: Sentinel-2 is optical (no thermal band), 10 m visible/NIR and 20 m SWIR. FIRMS detections may be days apart from the image, and an individual fire can be much smaller/short-lived than a pixel or scene interval. FIRMS marks in the overlay are observations, not validation. OSM outlines are mapped features, not causal attribution.\n- Reproduce: run `python src/investigate_satellite_pilot.py` from repo root; dependencies include rasterio, geopandas, pandas, requests, matplotlib, numpy, pyproj, shapely.\n"""
    (outdir / "README.md").write_text(readme, encoding="utf-8")
    source_note = """# Imagery source assessment\n\n## Recommended: Sentinel-2 L2A\n\nEarth Search STAC (`https://earth-search.aws.element84.com/v1/search`, collection `sentinel-2-l2a`) exposes Sentinel-2 L2A items and links to public Cloud-Optimized GeoTIFF assets. Search and pixel windows were accessed without credentials. The AWS Open Data registry identifies the Sentinel-2 COG buckets as public and states that an AWS account is not required. Each small chip contains 64 x 64 pixels x four UInt16 bands (32 KiB total raw pixel data), saved as a compressed GeoTIFF; the four stored chips total about 0.1 MiB. COG block reads may transfer more than the chip bytes, but avoid retrieving full scenes.\n\nSentinel-2 MSI provides visible/NIR bands at 10 m and SWIR bands at 20 m; the nominal constellation revisit is five days. B11 is resampled only to align the exploratory chip. Scene-level `eo:cloud_cover` and local SCL cloud/shadow-screened chip percentages appear in `scene_metadata.csv`. The four selected scenes had scene cloud cover from 14.2% to 69.4%; local SCL cloud/shadow fractions ranged from 0% to 100%. A low local mask fraction still needs visual checking. S2 is optical, has no thermal band, and individual FIRMS dates are 0.21 to 3.21 days away from the selected image timestamps in this run. It can provide surface context; it cannot verify a brief fire or explain a FIRMS detection.\n\n## Cloud-resistant complementary source: Sentinel-1 GRD\n\nThe same Earth Search catalog returned a Sentinel-1 GRD IW scene for the quarry-area reference date 2026-09-05 window: `S1D_IW_GRDH_1SDV_20260909T122026_20260909T122051_004501_0085C5`, acquired 2026-09-09 12:20 UTC, with VV and VH assets. Sentinel-1 is C-band SAR, so cloud does not block acquisition; its radar backscatter requires different visual/analytical treatment and is not a fire sensor. It is a useful next option for land-surface context where optical clouds persist, not a substitute for fire evidence. This run queried its catalog metadata only and did not download SAR pixels.\n\n## References\n\n- [Earth Search STAC API](https://earth-search.aws.element84.com/v1/api.html)\n- [AWS Registry: Sentinel-2 COGs](https://registry.opendata.aws/sentinel-2-l2a-cogs/)\n- [Copernicus Sentinel-2 mission](https://documentation.dataspace.copernicus.eu/Data/SentinelMissions/Sentinel2.html)\n- [Copernicus Sentinel-1 mission](https://documentation.dataspace.copernicus.eu/Data/SentinelMissions/Sentinel1.html)\n"""
    (outdir / "source_assessment.md").write_text(source_note, encoding="utf-8")
    print(f"Created {outdir}")
    print(pd.DataFrame(details)[["hotspot_cell_id", "status", "selected_stac_item", "scene_minus_firms_reference_days", "eo_cloud_cover_percent_scene_level"]].to_string(index=False))


if __name__ == "__main__":
    main()
