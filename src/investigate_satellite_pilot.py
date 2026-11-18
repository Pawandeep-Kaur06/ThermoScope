"""Create a small, reproducible Sentinel-2 context investigation for FIRMS cells.

This is an exploratory context workflow, not fire verification or label creation.
It queries the public Element 84 Earth Search STAC API, then reads only small
windows from public Sentinel-2 COG assets. Run from the repository root:
    python src/investigate_satellite_pilot.py
"""
from __future__ import annotations

import json
import hashlib
import argparse
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
try:
    from src.regions import DEFAULT_REGION_CONFIG, get_region, tile_for_coordinate
except ImportError:  # pragma: no cover
    from regions import DEFAULT_REGION_CONFIG, get_region, tile_for_coordinate

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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


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


def read_osm_nearby(center_x: float, center_y: float, target_crs: str,
                    osm_path: Path = OSM) -> gpd.GeoDataFrame:
    bounds = box(center_x - HALF_SIZE_M, center_y - HALF_SIZE_M,
                 center_x + HALF_SIZE_M, center_y + HALF_SIZE_M)
    # The regional OSM GeoPackage is stored in WGS84; Fiona's bbox is interpreted
    # in the layer CRS, so transform the chip footprint before reading each layer.
    to_geo = Transformer.from_crs(target_crs, "EPSG:4326", always_xy=True)
    west, south = to_geo.transform(center_x - HALF_SIZE_M, center_y - HALF_SIZE_M)
    east, north = to_geo.transform(center_x + HALF_SIZE_M, center_y + HALF_SIZE_M)
    geographic_bbox = (west, south, east, north)
    frames = []
    for layer in gpd.list_layers(osm_path).name:
        frame = gpd.read_file(osm_path, layer=layer, bbox=geographic_bbox).to_crs(target_crs)
        if len(frame):
            frame["_source_layer"] = layer
            frames.append(frame)
    if not frames:
        return gpd.GeoDataFrame(geometry=[], crs=target_crs)
    return gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs=target_crs)


def reproject_scl_asset(href: str, dst_transform, dst_crs: str, dst_size: int) -> np.ndarray:
    """Warp the Sentinel Scene Classification Layer to the spectral chip grid."""
    out = np.zeros((dst_size, dst_size), dtype=np.uint8)
    with rasterio.open(href) as src:
        reproject(source=rasterio.band(src, 1), destination=out,
                  src_transform=src.transform, src_crs=src.crs,
                  dst_transform=dst_transform, dst_crs=dst_crs,
                  resampling=Resampling.nearest, src_nodata=0, dst_nodata=0)
    return out


def select_investigation_cells(recurrence: pd.DataFrame, matches: pd.DataFrame,
                              ranking: pd.DataFrame | None, region: dict,
                              max_cells: int, region_id: str) -> list[str]:
    """Select a small, tile-diverse sample; ranking categories are strata only."""
    cells = recurrence.set_index("hotspot_cell_id")
    if ranking is None:
        preferred = [cell for cell in CHOSEN if region_id == "dhanbad_jharia_bokaro" and cell in cells.index]
        ordered = recurrence.sort_values(["distinct_acquisition_dates", "detection_observations"], ascending=False)
        candidates = preferred + ordered.hotspot_cell_id.astype(str).tolist()
        return list(dict.fromkeys(candidates))[:max_cells]
    required = {"hotspot_cell_id", "candidate_category", "candidate_evidence_score", "firms_source_row"}
    if not required.issubset(ranking.columns):
        raise ValueError(f"Candidate-ranking input is missing fields: {sorted(required - set(ranking.columns))}")
    categories = [
        "persistent_thermal_with_nearby_relevant_industrial_context",
        "persistent_thermal_without_nearby_relevant_osm_context",
        "persistent_thermal_near_general_power_infrastructure_only",
        "elevated_thermal_with_nearby_relevant_industrial_context",
        "elevated_thermal_without_nearby_relevant_osm_context",
        "other_thermal_observation_review",
    ]
    work = ranking.copy()
    work["_score"] = pd.to_numeric(work.candidate_evidence_score, errors="coerce").fillna(0)
    if "cell_prior_distinct_acquisition_dates" in work:
        work["_prior"] = pd.to_numeric(work.cell_prior_distinct_acquisition_dates, errors="coerce").fillna(0)
    else:
        work["_prior"] = 0
    selected: list[str] = []
    used_tiles: set[str] = set()
    for _ in range(2):
        for category in categories:
            group = work.loc[work.candidate_category.eq(category)].sort_values(
                ["_score", "_prior", "firms_source_row"], ascending=[False, False, True]
            )
            options = []
            for cell_id in group.hotspot_cell_id.dropna().astype(str).drop_duplicates():
                if cell_id in selected or cell_id not in cells.index:
                    continue
                row = cells.loc[cell_id]
                tile = tile_for_coordinate(float(row.centroid_longitude), float(row.centroid_latitude), region)
                if tile is not None:
                    options.append((cell_id, str(tile["tile_id"])))
            choice = next((item for item in options if item[1] not in used_tiles), options[0] if options else None)
            if choice is not None and len(selected) < max_cells:
                selected.append(choice[0])
                used_tiles.add(choice[1])
        if len(selected) >= max_cells:
            break
    return selected[:max_cells]


def latest_firms_timestamp_utc(observations: pd.DataFrame) -> pd.Timestamp:
    dates = pd.to_datetime(observations.acq_date, errors="coerce").dt.strftime("%Y-%m-%d")
    times = pd.to_numeric(observations.acq_time, errors="coerce").astype("Int64").astype("string").str.zfill(4).str[-4:]
    timestamps = pd.to_datetime(dates + times, format="%Y-%m-%d%H%M", errors="coerce", utc=True)
    if timestamps.isna().any():
        raise ValueError("FIRMS cell contains an invalid date/time; cannot apply exact Sentinel-2 eligibility")
    return timestamps.max()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", default="dhanbad_jharia_bokaro", help="shared region ID")
    parser.add_argument("--region-config", type=Path, default=DEFAULT_REGION_CONFIG)
    parser.add_argument("--matching-dir", type=Path, default=RUN_SOURCE,
                        help="matching run with recurrence and FIRMS proximity CSVs")
    parser.add_argument("--osm", type=Path, default=OSM, help="OSM GeoPackage used for overlays")
    parser.add_argument("--candidate-ranking", type=Path,
                        help="ranking CSV to stratify image sampling by evidence category")
    parser.add_argument("--max-cells", type=int, default=8,
                        help="maximum recurring cells to inspect; defaults to four known cells plus four additional cells")
    parser.add_argument("--cell-ids", nargs="+", help="explicit hotspot_cell_id values; overrides automatic selection")
    parser.add_argument("--days-before", type=int, default=30,
                        help="maximum lookback from each cell's latest FIRMS date")
    parser.add_argument("--output-dir", type=Path, help="new run directory (must not already exist)")
    args = parser.parse_args(argv)
    run_source = args.matching_dir if args.matching_dir.is_absolute() else ROOT / args.matching_dir
    osm_path = args.osm if args.osm.is_absolute() else ROOT / args.osm
    ranking_path = args.candidate_ranking if args.candidate_ranking and args.candidate_ranking.is_absolute() else (ROOT / args.candidate_ranking if args.candidate_ranking else None)
    recurrence_path, matches_path = run_source / "firms_spatial_recurrence_cells.csv", run_source / "firms_pilot_osm_proximity.csv"
    if args.max_cells < 1 or args.days_before < 1:
        parser.error("--max-cells and --days-before must be positive")
    if not all(p.exists() for p in (recurrence_path, matches_path, osm_path)):
        raise FileNotFoundError("Required run output or OSM GeoPackage is missing")
    region = get_region(args.region, args.region_config)
    if ranking_path is not None and not ranking_path.is_file():
        raise FileNotFoundError(f"Candidate-ranking CSV not found: {ranking_path}")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    outdir = args.output_dir or ROOT / "data/processed/satellite_investigation" / f"run_{stamp}"
    if not outdir.is_absolute():
        outdir = ROOT / outdir
    outdir.mkdir(parents=True, exist_ok=False)

    recurrence = pd.read_csv(recurrence_path)
    matches = pd.read_csv(matches_path, low_memory=False)
    ranking = pd.read_csv(ranking_path, low_memory=False) if ranking_path is not None else None
    cells = recurrence.set_index("hotspot_cell_id")
    if args.cell_ids:
        selected_cell_ids = list(dict.fromkeys(args.cell_ids))
        missing_ids = [cell_id for cell_id in selected_cell_ids if cell_id not in cells.index]
        if missing_ids:
            raise ValueError(f"Requested hotspot_cell_id values missing from recurrence table: {missing_ids}")
    else:
        selected_cell_ids = select_investigation_cells(recurrence, matches, ranking, region, args.max_cells, args.region)
    if not selected_cell_ids:
        raise ValueError("No recurring FIRMS grid cells selected")
    for cell_id in selected_cell_ids:
        if not (matches.hotspot_cell_id == cell_id).any():
            raise ValueError(f"Selected cell has no FIRMS proximity observations: {cell_id}")
    details, all_chips = [], {}
    with rasterio.Env(AWS_NO_SIGN_REQUEST="YES", GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"):
        for cell_id in selected_cell_ids:
            cell = cells.loc[cell_id]
            obs = matches[matches.hotspot_cell_id == cell_id].copy()
            target_date = pd.to_datetime(obs.acq_date).max()
            target_timestamp = latest_firms_timestamp_utc(obs)
            lon, lat = float(cell.centroid_longitude), float(cell.centroid_latitude)
            tile = tile_for_coordinate(lon, lat, region)
            if tile is None:
                raise ValueError(f"Selected hotspot cell lies outside region {args.region}: {cell_id}")
            target_crs = str(tile["projected_crs"])
            to_utm = Transformer.from_crs("EPSG:4326", target_crs, always_xy=True)
            cx, cy = to_utm.transform(lon, lat)
            role_counts = obs.osm_nearest_feature_role.fillna("unknown").value_counts()
            dominant_role = role_counts.index[0] if len(role_counts) else "unknown"
            dominant_label = obs.osm_nearest_feature_label.dropna().mode()
            dominant_label = dominant_label.iloc[0] if len(dominant_label) else ""
            transform = from_origin(cx - HALF_SIZE_M, cy + HALF_SIZE_M, PIXEL_M, PIXEL_M)
            # Restrict catalog search to historical scenes; independently reject
            # any item whose timestamp is after the latest FIRMS observation.
            start = target_date - pd.Timedelta(days=args.days_before)
            body = {"collections": [COLLECTION], "bbox": [lon - 0.003, lat - 0.003, lon + 0.003, lat + 0.003],
                    "datetime": f"{start:%Y-%m-%d}T00:00:00Z/{target_timestamp.isoformat().replace('+00:00', 'Z')}", "limit": 100}
            response = requests.post(STAC, json=body, timeout=60)
            response.raise_for_status()
            items = response.json().get("features", [])
            items = [item for item in items if pd.to_datetime(item["properties"]["datetime"], utc=True) <= target_timestamp]
            items.sort(key=lambda f: (
                abs((pd.to_datetime(f["properties"]["datetime"], utc=True) - target_timestamp).total_seconds()),
                float(f.get("properties", {}).get("eo:cloud_cover", 100)),
            ))
            selected = next((f for f in items if all(k in f.get("assets", {}) for k in ("red", "green", "blue", "swir16", "scl"))), None)
            if not selected:
                details.append({
                    "hotspot_cell_id": cell_id, "status": "no_historical_scene_with_required_assets",
                    "tile_id": tile["tile_id"], "chip_crs": target_crs,
                    "firms_reference_date": str(target_date.date()), "firms_reference_datetime_utc": target_timestamp.isoformat(),
                    "stac_items_in_window": len(items), "selected_stac_item": None,
                    "scene_datetime_utc": None, "scene_minus_firms_reference_days": None,
                    "eo_cloud_cover_percent_scene_level": None, "chip_path": None, "scl_chip_path": None,
                })
                continue
            # RGB at 10 m and B11/SWIR at native 20 m resampled to 10 m for aligned comparison.
            band_arrays = {}
            for key in ("red", "green", "blue", "swir16"):
                band_arrays[key] = reproject_asset(selected["assets"][key]["href"], transform, target_crs, SIZE)
            local_cloud_shadow = local_scl_cloud_fraction(selected["assets"]["scl"]["href"], transform, target_crs, SIZE)
            scl_stack = reproject_scl_asset(selected["assets"]["scl"]["href"], transform, target_crs, SIZE)
            stack = np.stack([band_arrays[k] for k in ("red", "green", "blue", "swir16")])
            chip_path = outdir / f"{cell_id}_{selected['id']}_4band_10m.tif"
            scl_chip_path = outdir / f"{cell_id}_{selected['id']}_scl_10m.tif"
            with rasterio.open(chip_path, "w", driver="GTiff", height=SIZE, width=SIZE,
                               count=4, dtype="uint16", crs=target_crs, transform=transform,
                               compress="deflate", predictor=2, tiled=True) as dst:
                dst.write(stack)
                for i, description in enumerate(("red_B04_10m", "green_B03_10m", "blue_B02_10m", "swir16_B11_20m_resampled_to_10m"), start=1):
                    dst.set_band_description(i, description)
            with rasterio.open(scl_chip_path, "w", driver="GTiff", height=SIZE, width=SIZE,
                               count=1, dtype="uint8", crs=target_crs, transform=transform,
                               compress="deflate", tiled=True, nodata=0) as dst:
                dst.write(scl_stack, 1)
                dst.set_band_description(1, "SCL_20m_nearest_resampled_to_10m_grid")
            all_chips[cell_id] = (stack, transform, cx, cy, obs, target_crs)
            item_date = pd.Timestamp(selected["properties"]["datetime"])
            details.append({
                "hotspot_cell_id": cell_id, "status": "chip_created", "representative_context": cell.get("cell_interpretation", ""),
                "tile_id": tile["tile_id"], "chip_crs": target_crs,
                "detection_observations_in_cell": int(cell.detection_observations),
                "distinct_firms_acquisition_dates": int(cell.distinct_acquisition_dates),
                "dominant_nearest_osm_role_across_observations": dominant_role,
                "modal_nearest_osm_feature_label": dominant_label,
                "median_nearest_osm_distance_m": float(obs.osm_nearest_distance_m.median()),
                "firms_reference_date": str(target_date.date()), "firms_reference_datetime_utc": target_timestamp.isoformat(), "selected_stac_item": selected["id"],
                "scene_datetime_utc": item_date.isoformat(), "scene_minus_firms_reference_days": round((pd.to_datetime(item_date, utc=True)-target_timestamp).total_seconds()/86400, 3),
                "eo_cloud_cover_percent_scene_level": selected["properties"].get("eo:cloud_cover"),
                "local_scl_cloud_shadow_fraction": local_cloud_shadow,
                "local_scl_cloud_shadow_percent": (100 * local_cloud_shadow) if local_cloud_shadow is not None else None,
                "stac_items_in_plus_minus_5_day_window": len(items), "sensor": selected["properties"].get("platform"),
                "resolution_m": "B02/B03/B04 10 m; B11 20 m (resampled to 10 m in chip)",
                "chip_size_pixels": f"{SIZE}x{SIZE}", "chip_extent_m": f"{2*HALF_SIZE_M}x{2*HALF_SIZE_M}",
                "chip_path": str(chip_path.relative_to(ROOT)), "catalog_url": STAC,
                "scl_chip_path": str(scl_chip_path.relative_to(ROOT)),
                "asset_urls": json.dumps({k: selected["assets"][k]["href"] for k in ("red", "green", "blue", "swir16")}),
                "authentication": "none; public Earth Search STAC and public Sentinel COG assets",
                "interpretation_limit": "Optical land-surface context only; spatial and temporal mismatch prevents fire confirmation.",
            })

    pd.DataFrame(details).to_csv(outdir / "scene_metadata.csv", index=False)
    # Catalog-only Sentinel-1 check for the most cloud-obscured quarry example.
    # No radar pixels are requested or downloaded in this stage.
    quarry_id = selected_cell_ids[0]
    quarry = cells.loc[quarry_id]
    qdate = pd.to_datetime(matches.loc[matches.hotspot_cell_id == quarry_id, "acq_date"]).max()
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
    loc = recurrence[recurrence.hotspot_cell_id.isin(selected_cell_ids)].copy()
    if ranking is not None:
        strata = ranking.loc[ranking.hotspot_cell_id.astype(str).isin(selected_cell_ids),
                             ["hotspot_cell_id", "candidate_category"]].drop_duplicates("hotspot_cell_id")
        loc = loc.merge(strata, on="hotspot_cell_id", how="left")
    loc = loc.merge(pd.DataFrame(details)[["hotspot_cell_id", "status", "tile_id", "chip_crs", "firms_reference_date", "firms_reference_datetime_utc", "selected_stac_item", "scene_datetime_utc", "scene_minus_firms_reference_days", "eo_cloud_cover_percent_scene_level", "chip_path", "scl_chip_path"]], on="hotspot_cell_id", how="left")
    loc.to_csv(outdir / "selected_investigation_cells.csv", index=False)

    # One overlay figure: true-color reflectance stretch with FIRMS points, 250 m grid, and mapped OSM geometry.
    if all_chips:
        n = len(all_chips)
        fig, axes = plt.subplots(1, n, figsize=(5*n, 5), squeeze=False)
        for ax, (cell_id, (stack, transform, cx, cy, obs, target_crs)) in zip(axes[0], all_chips.items()):
            rgb = np.moveaxis(stack[:3], 0, -1).astype(float)
            # Robust display stretch; stored pixel values remain unchanged in the GeoTIFF.
            valid = rgb[rgb > 0]
            high = np.percentile(valid, 99) if valid.size else 1
            rgb = np.clip(rgb / max(high, 1), 0, 1) ** 0.75
            ax.imshow(rgb, extent=(cx-HALF_SIZE_M, cx+HALF_SIZE_M, cy-HALF_SIZE_M, cy+HALF_SIZE_M), origin="upper")
            local_osm = read_osm_nearby(cx, cy, target_crs, osm_path)
            if len(local_osm):
                try:
                    local_osm.boundary.plot(ax=ax, color="#00e5ff", linewidth=0.8, alpha=0.9)
                except Exception:
                    pass
            local_transformer = Transformer.from_crs("EPSG:4326", target_crs, always_xy=True)
            grid_x, grid_y = local_transformer.transform(float(cells.loc[cell_id].centroid_longitude), float(cells.loc[cell_id].centroid_latitude))
            gpd.GeoSeries([box(grid_x-125, grid_y-125, grid_x+125, grid_y+125)], crs=target_crs).boundary.plot(ax=ax, color="yellow", linewidth=1.5)
            ref_date = pd.to_datetime(obs.acq_date).max()
            same_day = obs[pd.to_datetime(obs.acq_date) == ref_date]
            xs, ys = local_transformer.transform(same_day.longitude.to_numpy(), same_day.latitude.to_numpy())
            ax.scatter(xs, ys, s=18, facecolors="none", edgecolors="magenta", linewidths=1.0, label="FIRMS points on reference date")
            ax.set_title(cell_id + "\n" + str(pd.to_datetime(obs.acq_date).max().date()))
            ax.set_xlim(cx-HALF_SIZE_M, cx+HALF_SIZE_M); ax.set_ylim(cy-HALF_SIZE_M, cy+HALF_SIZE_M)
            ax.set_aspect("equal"); ax.set_xlabel(f"{target_crs} metres"); ax.set_ylabel(f"{target_crs} metres")
            ax.text(0.02, 0.02, "OSM geometry outlines (cyan); 250 m FIRMS cell (yellow)\nReference-date FIRMS points (magenta); optical context only", transform=ax.transAxes, fontsize=7, color="white", bbox={"facecolor":"black","alpha":0.65,"pad":3})
        fig.suptitle(f"ThermoScope {args.region}: Sentinel-2 scene context with FIRMS and OSM overlays", fontsize=13)
        fig.tight_layout()
        fig.savefig(outdir / "satellite_context_overlays.png", dpi=180, bbox_inches="tight")
        plt.close(fig)

    readme = f"""# Sentinel-2 context sample: {args.region}\n\nThis is an exploratory optical-context sample, not fire verification, ground-truth labeling, or a source-class model.\n\n- FIRMS matching input: `{matches_path.relative_to(ROOT)}`; recurrence input: `{recurrence_path.relative_to(ROOT)}`. OSM context: `{osm_path.relative_to(ROOT)}`.\n- Selected cells: {len(selected_cell_ids)}; chips created: {sum(d.get('status') == 'chip_created' for d in details)}; candidate categories, when supplied, are sampling strata only.\n- Source: Sentinel-2 L2A through Earth Search STAC (`{STAC}`), collection `{COLLECTION}`. No credentials are required for these public COG assets.\n- Each chip is 640 m square at 10 m grid spacing (64x64), with red/green/blue (10 m) and B11 SWIR (native 20 m resampled to 10 m), plus an SCL cloud/shadow mask. Chip CRS is selected locally from the region tile; no single UTM CRS is used statewide.\n- Historical rule: every candidate Sentinel acquisition timestamp must be at or before the latest FIRMS acquisition timestamp in that cell. Per-detection feature eligibility is checked separately; a cell-level image does not prove a fire or its cause.\n- FIRMS and OSM provide context only. Missing or cloudy imagery remains unknown.\n- Reproduce: `python src/investigate_satellite_pilot.py --region {args.region} --matching-dir {run_source.relative_to(ROOT)} --osm {osm_path.relative_to(ROOT)} --candidate-ranking <candidate_ranking.csv> --max-cells {args.max_cells} --output-dir <new-run-directory>`.\n"""
    (outdir / "README.md").write_text(readme, encoding="utf-8")
    chip_rows = [d for d in details if d.get("status") == "chip_created"]
    total_chip_bytes = sum((ROOT / d["chip_path"]).stat().st_size for d in chip_rows)
    source_note = f"""# Satellite imagery source and sample summary\n\nEarth Search STAC (`{STAC}`), collection `{COLLECTION}`, provides Sentinel-2 L2A scene metadata and public COG assets. The sample selected {len(selected_cell_ids)} cells and created {len(chip_rows)} four-band chips plus paired SCL masks ({total_chip_bytes:,} bytes for spectral chips; masks are reported separately in the manifest). Searches and small-window COG reads used no credentials. The workflow requests 64x64 pixels per band and does not download full scenes.\n\nThe four-band chips contain B04 red, B03 green and B02 blue at 10 m, plus B11 SWIR at native 20 m resampled onto a 10 m grid. Sentinel-2 is optical, not thermal; the SCL layer is used to flag cloud/shadow contamination. Item date/time and local quality are recorded per cell. Scene time is constrained to be at or before that cell's latest FIRMS acquisition timestamp; optical context still cannot verify a short-lived fire or establish its cause.\n\nSources: [Earth Search STAC API](https://earth-search.aws.element84.com/v1/api.html), [AWS Open Data Sentinel-2 COG registry](https://registry.opendata.aws/sentinel-2-l2a-cogs/), [Copernicus Sentinel-2 mission](https://documentation.dataspace.copernicus.eu/Data/SentinelMissions/Sentinel2.html).\n"""
    (outdir / "source_assessment.md").write_text(source_note, encoding="utf-8")
    matching_summary = json.loads((run_source / "summary.json").read_text(encoding="utf-8")) if (run_source / "summary.json").is_file() else {}
    input_paths = {"matching_csv": matches_path, "recurrence_csv": recurrence_path, "osm_gpkg": osm_path}
    if ranking_path is not None:
        input_paths["candidate_ranking"] = ranking_path
    firms_source = matching_summary.get("source_files", {}).get("firms")
    if firms_source:
        firms_path = Path(firms_source)
        input_paths["firms_csv"] = firms_path if firms_path.is_absolute() else ROOT / firms_path
    outputs = [p for p in outdir.rglob("*") if p.is_file() and p.name != "run_manifest.json"]
    run_manifest = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "region_id": args.region, "selected_cell_ids": selected_cell_ids,
        "selection": "candidate-ranking categories used only as stratification; no labels inferred",
        "parameters": {"lookback_days": args.days_before, "chip_extent_m": 2 * HALF_SIZE_M,
                       "pixel_size_m": PIXEL_M, "dimensions": [SIZE, SIZE],
                       "historical_cutoff": "Sentinel scene timestamp <= latest FIRMS observation timestamp in selected cell"},
        "inputs": {name: {"path": str(path), "size_bytes": path.stat().st_size, "sha256": sha256_file(path)}
                   for name, path in input_paths.items() if path.is_file()},
        "scenes": [{"cell_id": d.get("hotspot_cell_id"), "status": d.get("status"),
                    "item_id": d.get("selected_stac_item"), "scene_datetime_utc": d.get("scene_datetime_utc"),
                    "chip_path": d.get("chip_path"), "scl_path": d.get("scl_chip_path"),
                    "cloud_shadow_percent": d.get("local_scl_cloud_shadow_percent"), "chip_crs": d.get("chip_crs")}
                   for d in details],
        "outputs": {str(path.relative_to(outdir).as_posix()): {"size_bytes": path.stat().st_size,
                                                               "sha256": sha256_file(path)} for path in outputs},
        "labels_created": 0, "interpretation": "optical surface context only; no fire labels or confirmation",
    }
    (outdir / "run_manifest.json").write_text(json.dumps(run_manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Created {outdir}")
    print(pd.DataFrame(details)[["hotspot_cell_id", "status", "selected_stac_item", "scene_minus_firms_reference_days", "eo_cloud_cover_percent_scene_level"]].to_string(index=False))


if __name__ == "__main__":
    main()
