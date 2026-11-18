"""Locally match regional FIRMS detections to tagged OSM features.

This is proximity evidence for investigation, not causal attribution or labels.
Distances use the shared region configuration's local projected CRS; input/output
coordinates remain WGS84. Outputs are written to a fresh run directory.
"""
from __future__ import annotations

import argparse
import ast
import json
import math
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from pyproj import CRS
from shapely.geometry import Point, box
from shapely.strtree import STRtree
try:
    from src.regions import (DEFAULT_REGION_CONFIG, RegionConfigurationError, assign_recurrence_grid,
                             assign_tile_ids, bounds_tuple, contains_coordinates, get_region, grid_crs_prefix,
                             select_projected_crs, stable_observation_id, tile_for_coordinate)
except ImportError:  # pragma: no cover - direct script invocation
    from regions import (DEFAULT_REGION_CONFIG, RegionConfigurationError, assign_recurrence_grid,
                         assign_tile_ids, bounds_tuple, contains_coordinates, get_region, grid_crs_prefix,
                         select_projected_crs, stable_observation_id, tile_for_coordinate)
try:
    from src.pipeline_cache import atomic_json, cache_hit, cache_key, file_fingerprint, write_manifest
except ImportError:  # pragma: no cover
    from pipeline_cache import atomic_json, cache_hit, cache_key, file_fingerprint, write_manifest

BOUNDS = (85.75, 23.25, 86.75, 24.00)  # default pilot; set from shared config in main()
DISTANCE_CRS = "EPSG:32645"
REGION_ID = "dhanbad_jharia_bokaro"
BOUNDS_MAX_INCLUSIVE = True
BOUNDS_EAST_INCLUSIVE = True
BOUNDS_NORTH_INCLUSIVE = True
TILED_MODE = False
OSM_RADIUS_M = 1_000.0
AMBIGUITY_TOLERANCE_M = 100.0
GEM_RADIUS_M = 5_000.0
DISTANCE_THRESHOLDS_M = (100, 250, 500, 1_000)
RECURRENCE_CELL_M = 250.0
INDUSTRIAL_BUILDINGS = {"industrial", "factory", "works", "boiler_house"}
INDUSTRIAL_STRUCTURES = {"works", "chimney", "storage_tank", "gasometer", "kiln", "cooling_tower"}
POWER_VALUES = {
    "plant", "generator", "substation", "line", "minor_line", "cable", "minor_cable",
    "tower", "pole", "transformer", "converter", "switch", "switchgear", "terminal",
    "portal", "insulator", "catenary_mast", "busbar", "bay", "compensator",
}
MATCH_ROLES = (
    "industrial_landuse", "industrial_facility", "mining_extraction_area", "mine_working_feature", "waste_facility", "industrial_rail",
    "power_generation", "power_site",
    "power_transmission_line", "power_transmission_tower", "power_transmission_other",
    "power_distribution", "power_other",
)


def json_safe(value):
    """Normalize pandas/numpy scalars and nullable category keys for JSON output."""
    if isinstance(value, dict):
        normalized = {}
        for key, item in value.items():
            if key is pd.NA:
                safe_key = "unknown"
            elif isinstance(key, np.generic):
                key = key.item()
                safe_key = ("unknown" if isinstance(key, float) and math.isnan(key)
                            else key if isinstance(key, (str, int, float, bool)) else str(key))
            elif isinstance(key, (str, int, float, bool)) or key is None:
                safe_key = "unknown" if isinstance(key, float) and math.isnan(key) else key
            else:
                safe_key = str(key)
            normalized[safe_key] = json_safe(item)
        return normalized
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    if value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def parse_tags(value: object) -> dict[str, object]:
    """Parse JSON and Python-literal dict strings seen in GDAL's all_tags field."""
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return {}
    for parser in (json.loads, ast.literal_eval):
        try:
            result = parser(value)
            if isinstance(result, dict):
                return result
        except (ValueError, SyntaxError, json.JSONDecodeError):
            pass
    return {}


def tag_categories(tags: dict[str, object]) -> list[str]:
    categories = []
    if tags.get("landuse") == "industrial":
        categories.append("industrial_landuse")
    if (
        (tags.get("industrial") is not None and str(tags.get("industrial")).lower() not in {"no", "false", "0"})
        or tags.get("building") in INDUSTRIAL_BUILDINGS
        or tags.get("man_made") in INDUSTRIAL_STRUCTURES
    ):
        categories.append("industrial_facility")
    if tags.get("power") in POWER_VALUES or tags.get("plant") is not None or tags.get("generator:source") is not None:
        categories.append("power_infrastructure")
    if tags.get("landuse") == "quarry" or tags.get("man_made") in {"mine", "mineshaft", "adit"} or tags.get("industrial") == "mine":
        categories.append("mining_extraction")
    if tags.get("landuse") == "landfill" or tags.get("amenity") in {"waste_disposal", "waste_transfer_station", "recycling"}:
        categories.append("waste_facility")
    if tags.get("railway") in {"industrial", "yard", "spur", "siding"}:
        categories.append("industrial_rail")
    if (
        tags.get("landuse") in {"forest", "farmland", "grass", "meadow", "orchard", "vineyard", "plant_nursery"}
        or tags.get("natural") in {"wood", "scrub", "heath", "grassland", "wetland", "shrubbery"}
        or tags.get("landcover") in {"trees", "grass", "scrub", "wetland", "cropland"}
    ):
        categories.append("vegetation_context")
    return categories


def feature_roles(tags: dict[str, object], categories: list[str]) -> list[str]:
    """Separate industrial-site context from generation, grid, and distribution assets."""
    roles = [name for name in ("industrial_landuse", "industrial_facility") if name in categories]
    if "mining_extraction" in categories:
        if tags.get("landuse") == "quarry":
            roles.append("mining_extraction_area")
        if tags.get("man_made") in {"mine", "mineshaft", "adit"} or tags.get("industrial") == "mine":
            roles.append("mine_working_feature")
    roles.extend(name for name in ("waste_facility", "industrial_rail", "vegetation_context") if name in categories)
    power = str(tags.get("power", ""))
    if power in {"plant", "generator"} or tags.get("plant") is not None or tags.get("generator:source") is not None:
        roles.append("power_generation")
    elif power in {"substation", "converter", "switch", "switchgear", "terminal", "busbar", "bay", "compensator"}:
        roles.append("power_site")
    elif power in {"line", "minor_line", "cable", "minor_cable"}:
        roles.append("power_transmission_line")
    elif power == "tower":
        roles.append("power_transmission_tower")
    elif power == "portal":
        roles.append("power_transmission_other")
    elif power in {"pole", "transformer", "insulator", "catenary_mast"}:
        roles.append("power_distribution")
    elif power:
        roles.append("power_other")
    return roles


def tag_signature(tags: dict[str, object]) -> str:
    keys = ("industrial", "landuse", "building", "man_made", "power", "plant", "generator:source", "voltage", "operator")
    return ";".join(f"{key}={tags[key]}" for key in keys if tags.get(key) is not None)


def feature_label(tags: dict[str, object], categories: list[str]) -> str:
    for key in ("name", "operator", "ref"):
        value = tags.get(key)
        if value:
            return str(value)
    return " | ".join(categories) or "OSM feature"


def fresh_output_dir(parent: Path, requested: str | Path | None, resume: bool = False) -> Path:
    if requested:
        target = Path(requested)
        if not target.is_absolute():
            target = (Path.cwd() / target).resolve()
    else:
        stamp = datetime.now(timezone.utc).strftime("run_%Y%m%dT%H%M%SZ")
        target = parent / stamp
    if resume:
        target.mkdir(parents=True, exist_ok=True)
    else:
        target.mkdir(parents=True, exist_ok=False)
    return target


def _in_current_bounds(longitude: pd.Series, latitude: pd.Series) -> pd.Series:
    west, south, east, north = BOUNDS
    lon_inside = longitude.ge(west) & (longitude.le(east) if BOUNDS_EAST_INCLUSIVE else longitude.lt(east))
    lat_inside = latitude.ge(south) & (latitude.le(north) if BOUNDS_NORTH_INCLUSIVE else latitude.lt(north))
    return lon_inside & lat_inside


def _expanded_tile_bbox(tile: dict[str, object], radius_m: float = OSM_RADIUS_M) -> tuple[float, float, float, float]:
    """WGS84 query envelope for a local tile plus its matching search radius."""
    west, south, east, north = bounds_tuple(tile)
    mid_lat = (south + north) / 2
    delta_lat = radius_m / 110_574.0
    delta_lon = radius_m / max(1.0, 111_320.0 * abs(np.cos(np.deg2rad(mid_lat))))
    return west - delta_lon, south - delta_lat, east + delta_lon, north + delta_lat


def combine_tile_results(tile_results: list[pd.DataFrame]) -> pd.DataFrame:
    """Combine tile matches and reject duplicate source observations/row IDs."""
    if not tile_results:
        return pd.DataFrame()
    combined = pd.concat(tile_results, ignore_index=True).sort_values("firms_source_row", kind="stable").reset_index(drop=True)
    if combined.firms_source_row.duplicated().any():
        raise ValueError("Tile match outputs duplicate firms_source_row; tile boundary assignment is not unique")
    if "firms_observation_id" in combined and combined.firms_observation_id.duplicated().any():
        raise ValueError("Tile match outputs duplicate firms_observation_id; refusing duplicated FIRMS detections")
    return combined


def load_osm(gpkg: Path, target_crs: str | None = None,
             bbox: tuple[float, float, float, float] | None = None) -> tuple[gpd.GeoDataFrame, dict[str, int], dict[str, int]]:
    frames = []
    source_counts: dict[str, int] = {}
    geometry_counts: Counter[str] = Counter()
    for layer in gpd.list_layers(gpkg).name:
        frame = gpd.read_file(gpkg, layer=layer, fid_as_index=True, bbox=bbox)
        frame["gpkg_fid"] = frame.index.astype("int64")
        source_counts[layer] = len(frame)
        if frame.crs is None:
            raise ValueError(f"OSM layer {layer} has no CRS")
        if CRS.from_user_input(frame.crs) != CRS.from_epsg(4326):
            raise ValueError(f"OSM layer {layer} expected EPSG:4326, found {frame.crs}")
        geometry_counts.update(frame.geom_type.fillna("missing").value_counts().to_dict())
        valid = frame.geometry.notna() & ~frame.geometry.is_empty & frame.geometry.is_valid
        frame = frame.loc[valid].copy()
        frame["tags_parsed"] = frame["all_tags"].map(parse_tags)
        frame["match_categories"] = frame["tags_parsed"].map(tag_categories)
        frame["feature_roles"] = [feature_roles(tags, cats) for tags, cats in zip(frame.tags_parsed, frame.match_categories)]
        frame = frame.loc[frame.match_categories.map(bool)].copy()
        frames.append(frame)
    if not frames:
        raise ValueError("The OSM GeoPackage contains no readable vector layers")
    osm = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), geometry="geometry", crs="EPSG:4326")
    osm["feature_label"] = [feature_label(t, c) for t, c in zip(osm.tags_parsed, osm.match_categories)]
    osm["feature_category"] = osm.match_categories.map(lambda c: ";".join(c))
    osm["feature_role"] = osm.feature_roles.map(lambda roles: ";".join(roles))
    osm["tag_signature"] = osm.tags_parsed.map(tag_signature)
    osm["osm_element_type"] = "unknown"
    osm["osm_source_id"] = osm["osm_id"]
    if "osm_way_id" in osm.columns:
        way_ids = osm.osm_way_id.notna()
        osm.loc[way_ids, "osm_source_id"] = osm.loc[way_ids, "osm_way_id"]
    osm.loc[osm.source_layer.eq("points"), "osm_element_type"] = "node"
    osm.loc[osm.source_layer.eq("points"), "osm_source_id"] = osm.loc[osm.source_layer.eq("points"), "osm_id"]
    osm.loc[osm.source_layer.eq("lines"), "osm_element_type"] = "way"
    osm.loc[osm.source_layer.eq("lines"), "osm_source_id"] = osm.loc[osm.source_layer.eq("lines"), "osm_id"]
    is_multi = osm.source_layer.eq("multipolygons")
    osm.loc[is_multi & osm.osm_way_id.notna(), "osm_element_type"] = "way"
    osm.loc[is_multi & osm.osm_way_id.isna(), "osm_element_type"] = "relation"
    osm["osm_feature_id"] = [
        f"{element[0]}{source_id}" if pd.notna(source_id) and element != "unknown" else f"gpkg:{layer}:{fid}"
        for element, source_id, layer, fid in zip(osm.osm_element_type, osm.osm_source_id, osm.source_layer, osm.gpkg_fid)
    ]
    projected = osm.to_crs(target_crs or DISTANCE_CRS)
    return projected, source_counts, dict(geometry_counts)


def load_gem(root: Path, gem_dir: Path | None = None) -> gpd.GeoDataFrame:
    gem_root = gem_dir if gem_dir is not None else root / "data/processed/gem"
    files = [
        (gem_root / "coal_mines_dhanbad_jharia_bbox.json", "GEM coal mine"),
        (gem_root / "coal_plants_dhanbad_jharia_bbox.json", "GEM coal plant"),
    ]
    records = []
    for path, source in files:
        if not path.exists():
            continue
        obj = json.loads(path.read_text(encoding="utf-8"))
        for row in obj.get("records", []):
            lat, lon = pd.to_numeric(row.get("latitude"), errors="coerce"), pd.to_numeric(row.get("longitude"), errors="coerce")
            lat_ok = BOUNDS[1] <= lat and (lat <= BOUNDS[3] if BOUNDS_NORTH_INCLUSIVE else lat < BOUNDS[3])
            lon_ok = BOUNDS[0] <= lon and (lon <= BOUNDS[2] if BOUNDS_EAST_INCLUSIVE else lon < BOUNDS[2])
            if pd.notna(lat) and pd.notna(lon) and lat_ok and lon_ok:
                records.append({"name": row.get("asset_name"), "asset_type": row.get("asset_type"), "source": source,
                                "latitude": float(lat), "longitude": float(lon), "asset_id": row.get("asset_id")})
    if not records:
        return gpd.GeoDataFrame(columns=["name", "asset_type", "source", "latitude", "longitude", "asset_id", "geometry"], geometry="geometry", crs="EPSG:4326")
    return gpd.GeoDataFrame(records, geometry=gpd.points_from_xy([r["longitude"] for r in records], [r["latitude"] for r in records]), crs="EPSG:4326")


def do_matching(firms: pd.DataFrame, osm: gpd.GeoDataFrame, gem: gpd.GeoDataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    in_bbox = _in_current_bounds(firms.longitude, firms.latitude)
    pilot = firms.loc[in_bbox].copy()
    # Row ID is zero-based in the input FIRMS CSV, preserving its original row through filtering.
    source_rows = pilot.pop("_firms_source_row") if "_firms_source_row" in pilot else np.flatnonzero(in_bbox.to_numpy())
    pilot.insert(0, "firms_source_row", np.asarray(source_rows, dtype=np.int64))
    points_wgs84 = gpd.GeoDataFrame(pilot, geometry=gpd.points_from_xy(pilot.longitude, pilot.latitude), crs="EPSG:4326")
    points_m = points_wgs84.to_crs(DISTANCE_CRS)

    if osm.empty:
        result = pilot.reset_index(drop=True)
        result["osm_nearest_distance_m"] = np.nan
        for column in ("osm_nearest_osm_id", "osm_nearest_feature_id", "osm_nearest_osm_element_type",
                       "osm_nearest_feature_label", "osm_nearest_feature_category", "osm_nearest_feature_role",
                       "osm_nearest_tag_signature", "osm_nearest_source_layer"):
            result[column] = pd.NA
        result["osm_nearby_feature_count_1km"] = 0
        for threshold in DISTANCE_THRESHOLDS_M:
            result[f"osm_nearby_feature_count_{threshold}m"] = 0
            result[f"match_status_{threshold}m"] = f"unknown_no_relevant_osm_within_{threshold}m"
        for role in MATCH_ROLES:
            result[f"nearest_{role}_distance_m"] = np.nan
        result["gem_nearest_distance_m"] = np.nan
        result["gem_nearest_name"] = pd.NA
        result["gem_nearest_type"] = pd.NA
        result["gem_nearest_within_5km"] = pd.NA
        if len(gem):
            gem_m = gem.to_crs(DISTANCE_CRS)
            gem_tree = STRtree(gem_m.geometry.array)
            gem_geom = gem_m.geometry.array
            distance_values, names, types, within_values = [], [], [], []
            for point in points_m.geometry:
                gi = int(gem_tree.nearest(point))
                distance = float(point.distance(gem_geom[gi]))
                distance_values.append(distance)
                names.append(gem_m.iloc[gi]["name"])
                types.append(gem_m.iloc[gi]["asset_type"])
                within_values.append(distance <= GEM_RADIUS_M)
            result["gem_nearest_distance_m"] = distance_values
            result["gem_nearest_name"] = names
            result["gem_nearest_type"] = types
            result["gem_nearest_within_5km"] = within_values
        result["match_interpretation"] = "proximity only; not verified cause or ground truth"
        result["match_status"] = result["match_status_1000m"]
        qc = {"firms_total_rows": int(len(firms)), "firms_pilot_rows": int(len(result)),
              "firms_missing_coordinates_total": int((firms.latitude.isna() | firms.longitude.isna()).sum()),
              "pilot_invalid_projected_coordinates": 0, "pilot_points_outside_bbox_after_filter": 0,
              "pilot_geometry_invalid": 0, "osm_features_used": 0, "osm_invalid_or_empty_filtered": 0}
        return result, qc

    tree = STRtree(osm.geometry.array)
    geometries = osm.geometry.array
    ids = osm.osm_feature_id.astype("string").to_numpy()
    source_ids = osm.osm_source_id.astype("string").fillna("").to_numpy()
    element_types = osm.osm_element_type.astype("string").to_numpy()
    labels = osm.feature_label.to_numpy()
    categories = osm.feature_category.to_numpy()
    roles = osm.feature_role.to_numpy()
    signatures = osm.tag_signature.to_numpy()
    layers = osm.source_layer.to_numpy()
    out = {
        "osm_nearest_distance_m": [], "osm_nearest_osm_id": [], "osm_nearest_feature_id": [], "osm_nearest_osm_element_type": [], "osm_nearest_feature_label": [],
        "osm_nearest_feature_category": [], "osm_nearest_feature_role": [], "osm_nearest_tag_signature": [],
        "osm_nearest_source_layer": [], "osm_nearby_feature_count_1km": [],
        "gem_nearest_distance_m": [], "gem_nearest_name": [], "gem_nearest_type": [],
        "gem_nearest_within_5km": [],
    }
    for threshold in DISTANCE_THRESHOLDS_M:
        out[f"osm_nearby_feature_count_{threshold}m"] = []
        out[f"match_status_{threshold}m"] = []
    for role in MATCH_ROLES:
        out[f"nearest_{role}_distance_m"] = []
    gem_m = gem.to_crs(DISTANCE_CRS) if len(gem) else gem
    gem_tree = STRtree(gem_m.geometry.array) if len(gem_m) else None
    gem_geom = gem_m.geometry.array if len(gem_m) else []
    invalid_coord_count = int((~np.isfinite(points_m.geometry.x) | ~np.isfinite(points_m.geometry.y)).sum())

    for point in points_m.geometry:
        if point is None or point.is_empty or not np.isfinite(point.x) or not np.isfinite(point.y):
            for col in out:
                if col.startswith("match_status"):
                    out[col].append("unknown_missing_coordinates")
                elif col.startswith("osm_nearby_feature_count"):
                    out[col].append(0)
                else:
                    out[col].append(np.nan)
            continue
        nearby = np.asarray(tree.query(point, predicate="dwithin", distance=OSM_RADIUS_M), dtype=int)
        if len(nearby):
            distances = np.asarray([point.distance(geometries[i]) for i in nearby], dtype=float)
            order = np.lexsort((np.asarray(ids)[nearby], distances))
            nearby, distances = nearby[order], distances[order]
            best = int(nearby[0]); best_dist = float(distances[0])
            vals = [best_dist, source_ids[best], ids[best], element_types[best], labels[best], categories[best], roles[best], signatures[best], layers[best], int(len(nearby))]
        elif TILED_MODE:
            vals = [np.nan, pd.NA, pd.NA, pd.NA, pd.NA, pd.NA, pd.NA, pd.NA, pd.NA, 0]
            distances = np.array([], dtype=float)
        else:
            nearest = int(tree.nearest(point))
            dist = float(point.distance(geometries[nearest]))
            vals = [dist, source_ids[nearest], ids[nearest], element_types[nearest], labels[nearest], categories[nearest], roles[nearest], signatures[nearest], layers[nearest], 0]
            distances = np.array([], dtype=float)
        for col, val in zip(["osm_nearest_distance_m", "osm_nearest_osm_id", "osm_nearest_feature_id", "osm_nearest_osm_element_type", "osm_nearest_feature_label", "osm_nearest_feature_category", "osm_nearest_feature_role", "osm_nearest_tag_signature", "osm_nearest_source_layer", "osm_nearby_feature_count_1km"], vals):
            out[col].append(val)
        for threshold in DISTANCE_THRESHOLDS_M:
            within = np.flatnonzero(distances <= threshold) if len(nearby) else np.array([], dtype=int)
            count = int(len(within))
            if count:
                first = int(within[0])
                tied = any(
                    distances[j] <= distances[first] + AMBIGUITY_TOLERANCE_M
                    and (ids[int(nearby[j])] != ids[int(nearby[first])] or layers[int(nearby[j])] != layers[int(nearby[first])])
                    for j in within[1:]
                )
                status = "ambiguous_proximity" if tied else "proximity_candidate"
            else:
                status = f"unknown_no_relevant_osm_within_{threshold}m"
            out[f"osm_nearby_feature_count_{threshold}m"].append(count)
            out[f"match_status_{threshold}m"].append(status)
        role_distances = {role: np.nan for role in MATCH_ROLES}
        for index, distance in zip(nearby, distances):
            if distance <= OSM_RADIUS_M:
                for role in str(roles[int(index)]).split(";"):
                    if role in role_distances and (np.isnan(role_distances[role]) or distance < role_distances[role]):
                        role_distances[role] = float(distance)
        for role in MATCH_ROLES:
            out[f"nearest_{role}_distance_m"].append(role_distances[role])

        if gem_tree is not None:
            gi = int(gem_tree.nearest(point)); gd = float(point.distance(gem_geom[gi]))
            if gd <= GEM_RADIUS_M:
                out["gem_nearest_distance_m"].append(gd)
                out["gem_nearest_name"].append(gem_m.iloc[gi]["name"])
                out["gem_nearest_type"].append(gem_m.iloc[gi].asset_type)
                out["gem_nearest_within_5km"].append(True)
            else:
                out["gem_nearest_distance_m"].append(gd)
                out["gem_nearest_name"].append(gem_m.iloc[gi]["name"])
                out["gem_nearest_type"].append(gem_m.iloc[gi].asset_type)
                out["gem_nearest_within_5km"].append(False)
        else:
            out["gem_nearest_distance_m"].append(np.nan); out["gem_nearest_name"].append(pd.NA); out["gem_nearest_type"].append(pd.NA)
            out["gem_nearest_within_5km"].append(pd.NA)
    result = pilot.reset_index(drop=True)
    for col, vals in out.items():
        result[col] = vals
    result["match_interpretation"] = "proximity only; not verified cause or ground truth"
    result["match_status"] = result["match_status_1000m"]
    # Sanity checks for coordinate filtering, source-row traceability, and distance fields.
    if not result.firms_source_row.is_unique:
        raise AssertionError("FIRMS source row IDs are not unique")
    if not _in_current_bounds(result.longitude, result.latitude).all():
        raise AssertionError("FIRMS pilot filter retained coordinates outside the bbox")
    if result.loc[result.match_status.isin(["proximity_candidate", "ambiguous_proximity"]), "osm_nearest_distance_m"].isna().any():
        raise AssertionError("Candidate statuses must have a finite nearest OSM distance")
    if (result.osm_nearest_distance_m < 0).any():
        raise AssertionError("Negative OSM distance found")
    candidate = result.match_status.ne("unknown_no_relevant_osm_within_1000m")
    if (result.loc[candidate, "osm_nearest_distance_m"] > OSM_RADIUS_M).any() or (result.loc[~candidate, "osm_nearest_distance_m"] <= OSM_RADIUS_M).any():
        raise AssertionError("OSM status does not agree with the screening distance")
    roundtrip = gpd.GeoSeries(gpd.points_from_xy(result.longitude, result.latitude), crs="EPSG:4326").to_crs(DISTANCE_CRS).to_crs("EPSG:4326")
    if not np.allclose(roundtrip.x, result.longitude, atol=1e-6) or not np.allclose(roundtrip.y, result.latitude, atol=1e-6):
        raise AssertionError("Projected coordinate round-trip failed")
    if not roundtrip.is_valid.all():
        raise AssertionError("Invalid FIRMS point geometry generated")
    required_match_fields = ["osm_nearby_feature_count_1km", "match_status"]
    if result[required_match_fields].isna().any().any():
        raise AssertionError("A required OSM match field is missing")
    in_bounds = _in_current_bounds(result.longitude, result.latitude)
    qc = {"firms_total_rows": int(len(firms)), "firms_pilot_rows": int(len(result)),
          "firms_missing_coordinates_total": int((firms.latitude.isna() | firms.longitude.isna()).sum()),
          "pilot_invalid_projected_coordinates": invalid_coord_count,
          "pilot_points_outside_bbox_after_filter": int((~in_bounds).sum()),
          "pilot_geometry_invalid": int((~points_wgs84.geometry.is_valid).sum()),
          "osm_features_used": int(len(osm)), "osm_invalid_or_empty_filtered": int(sum(geometry_counts_invalid(osm)))}
    return result, qc


def geometry_counts_invalid(osm: gpd.GeoDataFrame) -> tuple[int]:
    return (int((osm.geometry.isna() | osm.geometry.is_empty | ~osm.geometry.is_valid).sum()),)


def analyze_recurrence(result: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Summarize observations in fixed projected grid cells; cells are not source IDs."""
    projected = gpd.GeoSeries(gpd.points_from_xy(result.longitude, result.latitude), crs="EPSG:4326").to_crs(DISTANCE_CRS)
    coords = np.column_stack([projected.x.to_numpy(), projected.y.to_numpy()])
    cell_x = np.floor(coords[:, 0] / RECURRENCE_CELL_M).astype(np.int64)
    cell_y = np.floor(coords[:, 1] / RECURRENCE_CELL_M).astype(np.int64)
    result["hotspot_cell_id"] = [f"{grid_crs_prefix(DISTANCE_CRS)}_{x}_{y}" for x, y in zip(cell_x, cell_y)]
    result["recurrence_cell_size_m"] = RECURRENCE_CELL_M
    result["cell_recurrence_status"] = "single_date_cell"
    result["cell_detection_count"] = 1
    result["cell_distinct_acquisition_dates"] = 1
    result["cell_unique_coordinates_5dp"] = 1
    result["cell_repeated_coordinate_across_dates"] = False
    cell_rows = []
    dates = pd.to_datetime(result.acq_date, errors="coerce").dt.date
    coords5 = pd.DataFrame({"lat5": result.latitude.round(5), "lon5": result.longitude.round(5)})
    for raw_label, group in result.groupby("hotspot_cell_id", sort=True):
        idx = group.index
        n_dates = int(dates.loc[idx].nunique())
        coord_date = pd.DataFrame({"lat5": coords5.loc[idx, "lat5"], "lon5": coords5.loc[idx, "lon5"], "date": dates.loc[idx]}).dropna(subset=["date"])
        date_counts_by_coord = coord_date.groupby(["lat5", "lon5"], dropna=False).date.nunique()
        repeated_coord = bool((date_counts_by_coord >= 2).any())
        recurrence_status = "repeat_observed_across_dates" if n_dates >= 2 else "single_date_cell"
        result.loc[idx, "cell_recurrence_status"] = recurrence_status
        result.loc[idx, "cell_detection_count"] = int(len(group))
        result.loc[idx, "cell_distinct_acquisition_dates"] = n_dates
        result.loc[idx, "cell_unique_coordinates_5dp"] = int(coords5.loc[idx].drop_duplicates().shape[0])
        result.loc[idx, "cell_repeated_coordinate_across_dates"] = repeated_coord
        xy = coords[idx]
        centroid = xy.mean(axis=0)
        radius = np.sqrt(((xy - centroid) ** 2).sum(axis=1)).max()
        cell_rows.append({
            "hotspot_cell_id": raw_label,
            "detection_observations": int(len(group)),
            "distinct_acquisition_dates": n_dates,
            "first_acquisition_date": str(min(d for d in dates.loc[idx] if pd.notna(d))),
            "last_acquisition_date": str(max(d for d in dates.loc[idx] if pd.notna(d))),
            "unique_coordinates_5dp": int(coords5.loc[idx].drop_duplicates().shape[0]),
            "repeated_same_rounded_coordinate_across_dates": repeated_coord,
            "centroid_latitude": float(group.latitude.mean()),
            "centroid_longitude": float(group.longitude.mean()),
            "max_distance_from_cell_mean_m": float(radius),
            "recurrence_status": recurrence_status,
            "cell_interpretation": "fixed 250 m grid cell of FIRMS observations, not a verified physical source",
        })
    cell_summary = pd.DataFrame(cell_rows)
    return result, cell_summary


def match_firms_by_tiles(firms: pd.DataFrame, osm_path: Path, root: Path, gem_dir: Path,
                         region: dict[str, object], region_id: str,
                         checkpoint_dir: Path | None = None,
                         selected_tile_ids: list[str] | None = None) -> tuple[pd.DataFrame, dict[str, object]]:
    """Read only the OSM bbox needed per active tile and match in its local CRS."""
    global BOUNDS, DISTANCE_CRS, REGION_ID, BOUNDS_MAX_INCLUSIVE, BOUNDS_EAST_INCLUSIVE, BOUNDS_NORTH_INCLUSIVE
    longitudes = pd.to_numeric(firms.longitude, errors="coerce")
    latitudes = pd.to_numeric(firms.latitude, errors="coerce")
    west, south, east, north = bounds_tuple(region)
    max_inclusive = bool(region.get("max_inclusive", False))
    in_region = contains_coordinates(longitudes, latitudes, region)
    regional = firms.loc[in_region].copy()
    regional["_firms_source_row"] = np.flatnonzero(in_region.to_numpy())
    if "firms_observation_id" not in regional:
        regional["firms_observation_id"] = regional.apply(stable_observation_id, axis=1)
    else:
        missing_ids = regional.firms_observation_id.isna() | regional.firms_observation_id.astype(str).str.strip().eq("")
        regional.loc[missing_ids, "firms_observation_id"] = regional.loc[missing_ids].apply(stable_observation_id, axis=1)
    regional["region_id"] = region_id
    regional["tile_id"] = assign_tile_ids(longitudes.loc[in_region], latitudes.loc[in_region], region)
    if regional.tile_id.isna().any():
        raise AssertionError("A regional FIRMS observation was not assigned to exactly one tile")
    if selected_tile_ids is not None:
        if len(selected_tile_ids) != len(set(selected_tile_ids)):
            raise ValueError("--tile-ids must not contain duplicates")
        absent = sorted(set(selected_tile_ids) - set(regional.tile_id.astype(str)))
        if absent:
            raise ValueError(f"Requested tile(s) have no in-region FIRMS detections: {absent}")
        regional = regional.loc[regional.tile_id.isin(selected_tile_ids)].copy()
    if regional.empty:
        raise ValueError(f"No FIRMS detections fall inside configured region {region_id!r}")

    # GEM is optional supplementary context. The current local GEM inventory is
    # small; each tile's do_matching call reprojects these points into its CRS.
    BOUNDS = (west, south, east, north)
    BOUNDS_EAST_INCLUSIVE = max_inclusive
    BOUNDS_NORTH_INCLUSIVE = max_inclusive
    BOUNDS_MAX_INCLUSIVE = max_inclusive
    gem_wgs84 = load_gem(root, gem_dir)
    osm_fingerprint = file_fingerprint(osm_path)
    gem_inputs = {str(p.name): file_fingerprint(p) for p in sorted(gem_dir.glob("*.json"))} if gem_dir.is_dir() else {}
    tile_results: list[pd.DataFrame] = []
    tile_summaries: list[dict[str, object]] = []
    tile_cache_hits = 0
    osm_layer_appearances: Counter[str] = Counter()
    osm_geometry_appearances: Counter[str] = Counter()
    osm_category_appearances: Counter[str] = Counter()
    osm_role_appearances: Counter[str] = Counter()
    osm_total_feature_appearances = 0
    quarry_area_appearances = 0
    for tile_id, tile_firms in regional.groupby("tile_id", sort=True):
        tile = tile_for_coordinate(float(tile_firms.longitude.iloc[0]), float(tile_firms.latitude.iloc[0]), region)
        if tile is None or tile["tile_id"] != tile_id:
            raise AssertionError(f"Tile assignment changed for {tile_id}")
        BOUNDS = bounds_tuple(tile)
        BOUNDS_EAST_INCLUSIVE = bool(tile["east_inclusive"])
        BOUNDS_NORTH_INCLUSIVE = bool(tile["north_inclusive"])
        BOUNDS_MAX_INCLUSIVE = BOUNDS_EAST_INCLUSIVE and BOUNDS_NORTH_INCLUSIVE
        DISTANCE_CRS = str(tile["projected_crs"])
        tile_checkpoint = checkpoint_dir / f"{tile_id}.pkl" if checkpoint_dir else None
        tile_configuration = {"region_id": region_id, "tile": tile, "osm_radius_m": OSM_RADIUS_M,
                              "ambiguity_tolerance_m": AMBIGUITY_TOLERANCE_M,
                              "distance_thresholds_m": DISTANCE_THRESHOLDS_M}
        tile_rows_hash = __import__("hashlib").sha256(
            pd.util.hash_pandas_object(tile_firms, index=True).values.tobytes()).hexdigest()
        tile_key = cache_key(stage="osm_tile_match", inputs={"firms_tile_hash": tile_rows_hash,
                             "osm": osm_fingerprint, "gem": gem_inputs}, configuration=tile_configuration,
                             code_path=Path(__file__))
        if tile_checkpoint and cache_hit(tile_checkpoint, tile_key):
            matched = pd.read_pickle(tile_checkpoint)
            if (len(matched) != len(tile_firms) or matched.firms_observation_id.duplicated().any()
                    or set(matched.firms_observation_id) != set(tile_firms.firms_observation_id)):
                # A valid checksum can still describe a logically inconsistent artifact.
                raise ValueError(f"Cached tile {tile_id} failed row/identity validation: {tile_checkpoint}")
            cached_meta = json.loads(Path(str(tile_checkpoint) + ".cache.json").read_text(encoding="utf-8"))
            tile_summaries.append(cached_meta["metadata"]["tile_summary"])
            osm_layer_appearances.update(cached_meta["metadata"].get("layer_counts", {}))
            osm_geometry_appearances.update(cached_meta["metadata"].get("geometry_counts", {}))
            osm_category_appearances.update(cached_meta["metadata"].get("category_counts", {}))
            osm_role_appearances.update(cached_meta["metadata"].get("role_counts", {}))
            osm_total_feature_appearances += int(cached_meta["metadata"].get("total_features", 0))
            quarry_area_appearances += int(cached_meta["metadata"].get("quarry_areas", 0))
            tile_results.append(matched)
            tile_cache_hits += 1
            continue
        osm_all_tile, layer_counts, geometry_counts = load_osm(
            osm_path, target_crs=DISTANCE_CRS, bbox=_expanded_tile_bbox(tile)
        )
        candidate_feature = osm_all_tile.feature_role.map(
            lambda role_list: any(role in MATCH_ROLES for role in role_list.split(";"))
        )
        osm_tile = osm_all_tile.loc[candidate_feature].copy()
        osm_layer_appearances.update(Counter(layer_counts))
        for name, count in geometry_counts.items():
            osm_geometry_appearances[name] += count
        osm_category_appearances.update(Counter(cat for cats in osm_all_tile.match_categories for cat in cats))
        osm_role_appearances.update(Counter(role for roles in osm_all_tile.feature_roles for role in roles))
        osm_total_feature_appearances += len(osm_all_tile)
        quarry_area_appearances += int(osm_all_tile.feature_roles.map(lambda roles: "mining_extraction_area" in roles).sum())
        matched, _ = do_matching(tile_firms, osm_tile, gem_wgs84)
        matched["tile_id"] = tile_id
        matched["region_id"] = region_id
        matched["distance_crs"] = DISTANCE_CRS
        tile_results.append(matched)
        tile_summary = {
            "tile_id": tile_id, "bbox_wgs84": tile["bbox_wgs84"],
            "distance_crs": DISTANCE_CRS, "firms_rows": int(len(matched)),
            "osm_features_read_by_layer": layer_counts,
            "osm_features_used_for_matching": int(len(osm_tile)),
        }
        tile_summaries.append(tile_summary)
        if tile_checkpoint:
            tile_checkpoint.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(prefix=tile_checkpoint.name + ".", suffix=".partial",
                                             dir=tile_checkpoint.parent, delete=False) as temporary:
                temp_checkpoint = Path(temporary.name)
                matched.to_pickle(temporary)
                temporary.flush()
            temp_checkpoint.replace(tile_checkpoint)
            write_manifest(tile_checkpoint, key=tile_key, source="local OSM/GEM inputs and FIRMS tile",
                           metadata={"tile_summary": tile_summary, "layer_counts": layer_counts,
                                     "geometry_counts": geometry_counts,
                                     "category_counts": dict(Counter(cat for cats in osm_all_tile.match_categories for cat in cats)),
                                     "role_counts": dict(Counter(role for roles in osm_all_tile.feature_roles for role in roles)),
                                     "total_features": int(len(osm_all_tile)),
                                     "quarry_areas": int(osm_all_tile.feature_roles.map(lambda roles: "mining_extraction_area" in roles).sum())})
    combined = combine_tile_results(tile_results)
    if len(combined) != len(regional) or set(combined.firms_observation_id) != set(regional.firms_observation_id):
        raise AssertionError("Tiled matching did not preserve every regional FIRMS observation exactly once")
    return combined, {
        "tile_count_used": len(tile_summaries), "tiles": tile_summaries,
        "selected_tile_ids": selected_tile_ids,
        "completed_tile_cache_hits": tile_cache_hits,
        "osm_layer_feature_appearances": dict(osm_layer_appearances),
        "osm_geometry_appearances": dict(osm_geometry_appearances),
        "osm_category_appearances": dict(osm_category_appearances),
        "osm_role_appearances": dict(osm_role_appearances),
        "osm_total_feature_appearances": osm_total_feature_appearances,
        "osm_quarry_area_appearances": quarry_area_appearances,
        "osm_feature_rows_are_per_tile_reads_and_may_overlap_in_buffer_zones": True,
        "gem_records_loaded": int(len(gem_wgs84)),
        "assigned_firms_rows": int(len(combined)),
        "unique_observation_ids": int(combined.firms_observation_id.nunique()),
    }


def build_summary_tables(result: pd.DataFrame) -> dict[str, pd.DataFrame]:
    threshold_rows = []
    nearest_role_rows = []
    role_coverage_rows = []
    recurrence_role_rows = []
    for threshold in DISTANCE_THRESHOLDS_M:
        status = result[f"match_status_{threshold}m"]
        counts = status.value_counts()
        threshold_rows.append({
            "threshold_m": threshold,
            "detections_with_relevant_feature": int(status.isin(["proximity_candidate", "ambiguous_proximity"]).sum()),
            "proximity_candidate_unambiguous": int(counts.get("proximity_candidate", 0)),
            "ambiguous_proximity": int(counts.get("ambiguous_proximity", 0)),
            "unknown_no_relevant_feature_within_threshold": int(status.str.startswith("unknown_").sum()),
        })
        selected = result.loc[status.isin(["proximity_candidate", "ambiguous_proximity"])]
        role_status_counts = selected.groupby(["osm_nearest_feature_role", f"match_status_{threshold}m"]).size()
        for (role, status_name), n in role_status_counts.items():
            nearest_role_rows.append({"threshold_m": threshold, "nearest_feature_role": role, "match_status": status_name, "detections": int(n)})
        for role in MATCH_ROLES:
            distances = pd.to_numeric(result[f"nearest_{role}_distance_m"], errors="coerce")
            role_coverage_rows.append({
                "threshold_m": threshold,
                "feature_role": role,
                "detections_with_any_feature_in_role": int((distances <= threshold).sum()),
                "detections_with_role_as_overall_nearest": int((selected.osm_nearest_feature_role.str.split(";").map(lambda values: role in values)).sum()),
            })
        if not selected.empty:
            grouped = selected.groupby(["cell_recurrence_status", "osm_nearest_feature_role"], dropna=False)
            for (recurrence_status, role), group in grouped:
                recurrence_role_rows.append({
                    "threshold_m": threshold,
                    "cell_recurrence_status": recurrence_status,
                    "nearest_feature_role": role,
                    "detections": int(len(group)),
                    "distinct_acquisition_dates": int(group.acq_date.nunique()),
                    "spatial_cells": int(group.hotspot_cell_id.nunique()),
                })
    candidate = result.loc[result.match_status.isin(["proximity_candidate", "ambiguous_proximity"])].copy()
    tag_rows = []
    for _, row in candidate.iterrows():
        signature = str(row.get("osm_nearest_tag_signature", ""))
        if signature:
            for pair in signature.split(";"):
                key, _, value = pair.partition("=")
                tag_rows.append((key, value, row.osm_nearest_feature_role, row.match_status))
    tag_df = pd.DataFrame(tag_rows, columns=["tag_key", "tag_value", "nearest_feature_role", "match_status"])
    if not tag_df.empty:
        tag_table = tag_df.groupby(["match_status", "tag_key", "tag_value", "nearest_feature_role"], dropna=False).size().rename("candidate_detections").reset_index().sort_values("candidate_detections", ascending=False)
    else:
        tag_table = pd.DataFrame(columns=["match_status", "tag_key", "tag_value", "nearest_feature_role", "candidate_detections"])
    recurrence = result.groupby("cell_recurrence_status", dropna=False).agg(
        detections=("firms_source_row", "size"),
        spatial_cells=("hotspot_cell_id", "nunique"),
        distinct_dates=("acq_date", "nunique"),
        repeated_coordinate_detections=("cell_repeated_coordinate_across_dates", "sum"),
    ).reset_index()
    repeated_cell_counts = result.drop_duplicates(["cell_recurrence_status", "hotspot_cell_id"]).groupby("cell_recurrence_status").cell_repeated_coordinate_across_dates.sum().to_dict()
    recurrence["cells_with_repeated_rounded_coordinate"] = recurrence.cell_recurrence_status.map(repeated_cell_counts).fillna(0).astype(int)
    if len(result):
        overall = pd.DataFrame([{
            "cell_recurrence_status": "ALL_PILOT_DETECTIONS",
            "detections": int(len(result)),
            "spatial_cells": int(result.hotspot_cell_id.nunique()),
            "distinct_dates": int(result.acq_date.nunique()),
            "repeated_coordinate_detections": int(result.cell_repeated_coordinate_across_dates.sum()),
            "cells_with_repeated_rounded_coordinate": int(result.drop_duplicates("hotspot_cell_id").cell_repeated_coordinate_across_dates.sum()),
        }])
        recurrence = pd.concat([recurrence, overall], ignore_index=True)
    coordinate_keys = result[["latitude", "longitude"]].round(5)
    daily = result.assign(_date=pd.to_datetime(result.acq_date, errors="coerce").dt.date).groupby("_date", dropna=False).agg(
        firms_detections=("firms_source_row", "size"),
        unique_rounded_coordinates=("firms_source_row", lambda idx: int(coordinate_keys.loc[idx.index].drop_duplicates().shape[0])),
        proximity_candidates_1km=("match_status", lambda s: int(s.eq("proximity_candidate").sum())),
        ambiguous_proximity_1km=("match_status", lambda s: int(s.eq("ambiguous_proximity").sum())),
        observations_in_recurrent_cells=("cell_recurrence_status", lambda s: int(s.eq("repeat_observed_across_dates").sum())),
    ).reset_index().rename(columns={"_date": "acquisition_date"})
    daily["acquisition_date"] = daily.acquisition_date.astype(str)
    return {
        "distance_threshold_summary": pd.DataFrame(threshold_rows),
        "nearest_feature_role_by_threshold": pd.DataFrame(nearest_role_rows),
        "role_coverage_by_threshold": pd.DataFrame(role_coverage_rows),
        "candidate_counts_by_recurrence_role": pd.DataFrame(recurrence_role_rows),
        "candidate_nearest_tag_breakdown": tag_table,
        "recurrence_summary": recurrence,
        "firms_detections_by_acquisition_date": daily,
    }


def save_tiled_detection_map(out_dir: Path, results: pd.DataFrame, tiles: list[dict[str, object]]) -> None:
    """Lightweight WGS84 overview for tiled runs; matching uses each tile's CRS."""
    fig, ax = plt.subplots(figsize=(10, 8), constrained_layout=True)
    for tile in tiles:
        west, south, east, north = bounds_tuple({"bbox_wgs84": tile["bbox_wgs84"]})
        ax.plot([west, east, east, west, west], [south, south, north, north, south],
                color="#888888", linewidth=0.35, alpha=0.7)
    ax.scatter(results.longitude, results.latitude, s=2, c="#377eb8", alpha=0.4, label="FIRMS detections")
    ax.set_xlabel("Longitude (degrees)"); ax.set_ylabel("Latitude (degrees)")
    ax.set_title("ThermoScope tiled FIRMS overview\nOSM distances use tile-local projected CRSs")
    ax.grid(alpha=0.2); ax.legend(loc="best")
    fig.savefig(out_dir / "tiled_firms_overview.png", dpi=160); plt.close(fig)


def save_map(out_dir: Path, results: pd.DataFrame, osm: gpd.GeoDataFrame, gem: gpd.GeoDataFrame) -> None:
    fig, ax = plt.subplots(figsize=(11, 9), constrained_layout=True)
    bbox_gdf = gpd.GeoDataFrame(geometry=[box(*BOUNDS)], crs="EPSG:4326").to_crs(DISTANCE_CRS)
    bbox_gdf.boundary.plot(ax=ax, color="#333333", linewidth=1.2, label="Pilot boundary")
    # Map full candidate families, but style transmission towers separately from industrial sites.
    map_osm = gpd.clip(osm, bbox_gdf)
    role_styles = [
        ("industrial_landuse", "#d95f02", "polygon"), ("industrial_facility", "#e7298a", "square"),
        ("mining_extraction", "#a6761d", "polygon"), ("waste_facility", "#7570b3", "polygon"),
        ("industrial_rail", "#e6ab02", "line"), ("vegetation_context", "#a1d99b", "polygon"),
        ("power_generation", "#984ea3", "star"), ("power_site", "#4daf4a", "triangle"),
        ("power_transmission_line", "#1b9e77", "line"), ("power_transmission_tower", "#006d2c", "tiny"),
        ("power_transmission_other", "#66a61e", "tiny"), ("power_distribution", "#a6d854", "tiny"),
    ]
    for role, color, style in role_styles:
        subset = map_osm.loc[map_osm.feature_roles.map(lambda values: role in values)]
        if subset.empty: continue
        if style == "polygon":
            subset.plot(ax=ax, facecolor=color, edgecolor=color, alpha=0.24, linewidth=0.6, label=role.replace("_", " "))
        elif style == "line":
            subset.plot(ax=ax, color=color, linewidth=1, alpha=0.65, label=role.replace("_", " "))
        elif style == "tiny":
            subset = subset.loc[subset.geom_type.eq("Point")]
            if not subset.empty: subset.plot(ax=ax, color=color, markersize=3, alpha=0.28, label=role.replace("_", " "))
        else:
            marker = {"square": "s", "star": "*", "triangle": "^"}[style]
            subset.plot(ax=ax, color=color, markersize=15, marker=marker, label=role.replace("_", " "))
    firms_gdf = gpd.GeoDataFrame(results, geometry=gpd.points_from_xy(results.longitude, results.latitude), crs="EPSG:4326").to_crs(DISTANCE_CRS)
    firms_gdf.plot(ax=ax, color="#377eb8", markersize=4, alpha=0.35, label="FIRMS detections")
    if len(gem):
        gem.to_crs(DISTANCE_CRS).plot(ax=ax, color="#4d4d4d", marker="*", markersize=55, edgecolor="white", linewidth=0.4, label="GEM supplementary sites")
    ax.set_title("ThermoScope Dhanbad–Jharia–Bokaro pilot\nFIRMS detections and mapped industrial/power context")
    ax.set_xlabel("Easting (m), UTM zone 45N"); ax.set_ylabel("Northing (m), UTM zone 45N")
    minx, miny, maxx, maxy = bbox_gdf.total_bounds
    ax.set_xlim(minx - 500, maxx + 500); ax.set_ylim(miny - 500, maxy + 500)
    ax.legend(loc="best", fontsize=8); ax.set_aspect("equal", adjustable="box"); ax.grid(alpha=0.2)
    fig.savefig(out_dir / "pilot_spatial_context.png", dpi=180); plt.close(fig)


def save_threshold_plot(out_dir: Path, tables: dict[str, pd.DataFrame]) -> None:
    summary = tables["distance_threshold_summary"]
    role = tables["role_coverage_by_threshold"]
    fig, axes = plt.subplots(1, 2, figsize=(15, 6), constrained_layout=True)
    x = np.arange(len(summary)); labels = [f"{v} m" for v in summary.threshold_m]
    axes[0].bar(x, summary.proximity_candidate_unambiguous, label="Proximity candidate", color="#377eb8")
    axes[0].bar(x, summary.ambiguous_proximity, bottom=summary.proximity_candidate_unambiguous, label="Ambiguous proximity", color="#ff9f1c")
    axes[0].set_xticks(x, labels); axes[0].set_ylabel("FIRMS detections"); axes[0].set_title("Detections within each distance threshold")
    axes[0].legend(); axes[0].grid(axis="y", alpha=0.2)
    for role_name, group in role.groupby("feature_role"):
        axes[1].plot(group.threshold_m, group.detections_with_any_feature_in_role, marker="o", linewidth=1.6, label=role_name.replace("_", " "))
    axes[1].set_xticks(DISTANCE_THRESHOLDS_M, labels); axes[1].set_xlabel("Distance threshold"); axes[1].set_ylabel("Detections with any feature in role")
    axes[1].set_title("Role coverage (categories overlap)"); axes[1].grid(alpha=0.2); axes[1].legend(fontsize=7, loc="best")
    fig.suptitle("Proximity evidence by distance and mapped feature role")
    fig.savefig(out_dir / "distance_and_feature_role_summary.png", dpi=180); plt.close(fig)


def save_daily_plot(out_dir: Path, daily: pd.DataFrame) -> None:
    dates = pd.to_datetime(daily.acquisition_date, errors="coerce")
    fig, ax = plt.subplots(figsize=(13, 5), constrained_layout=True)
    ax.plot(dates, daily.firms_detections, color="#4d4d4d", linewidth=1.2, label="All FIRMS detections")
    ax.plot(dates, daily.proximity_candidates_1km, color="#377eb8", linewidth=1.0, label="Unambiguous proximity candidates, 1 km")
    ax.plot(dates, daily.ambiguous_proximity_1km, color="#ff9f1c", linewidth=1.0, label="Ambiguous proximity, 1 km")
    ax.plot(dates, daily.observations_in_recurrent_cells, color="#d95f02", linewidth=1.0, alpha=0.8, label="Observations in recurrent 250 m cells")
    ax.set_title("FIRMS observations by acquisition date")
    ax.set_xlabel("Acquisition date"); ax.set_ylabel("Detection observations")
    ax.grid(alpha=0.2); ax.legend(fontsize=8)
    fig.savefig(out_dir / "daily_detection_recurrence.png", dpi=180); plt.close(fig)


def save_recurrence_plots(out_dir: Path, result: pd.DataFrame, clusters: pd.DataFrame) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(15, 6), constrained_layout=True)
    if len(clusters):
        repeated = clusters.loc[clusters.recurrence_status.eq("repeat_observed_across_dates")]
        single = clusters.loc[clusters.recurrence_status.eq("single_date_cell")]
        bins = np.arange(0.5, max(2.5, float(clusters.distinct_acquisition_dates.max()) + 1.5), 1)
        axes[0].hist(single.distinct_acquisition_dates, bins=bins, alpha=0.75, label="Single-date clusters", color="#999999")
        axes[0].hist(repeated.distinct_acquisition_dates, bins=bins, alpha=0.75, label="Observed on multiple dates", color="#d95f02")
        axes[0].set_xlabel("Distinct acquisition dates per grid cell"); axes[0].set_ylabel("Grid cells")
        axes[0].set_title(f"Temporal recurrence (fixed 250 m {DISTANCE_CRS} grid cells)"); axes[0].legend(); axes[0].grid(axis="y", alpha=0.2)
    else:
        axes[0].text(0.5, 0.5, "No multi-observation spatial cells", ha="center", va="center", transform=axes[0].transAxes)
    points = gpd.GeoDataFrame(result, geometry=gpd.points_from_xy(result.longitude, result.latitude), crs="EPSG:4326").to_crs(DISTANCE_CRS)
    once = points.loc[points.cell_recurrence_status.eq("single_date_cell")]
    recurring = points.loc[points.cell_recurrence_status.eq("repeat_observed_across_dates")]
    once.plot(ax=axes[1], color="#377eb8", markersize=3, alpha=0.35, label="Cell observed on one date")
    recurring.plot(ax=axes[1], color="#d95f02", markersize=5, alpha=0.55, label="Cell observed on multiple dates")
    if len(clusters):
        centroids = gpd.GeoDataFrame(clusters, geometry=gpd.points_from_xy(clusters.centroid_longitude, clusters.centroid_latitude), crs="EPSG:4326").to_crs(DISTANCE_CRS)
        repeated_centroids = centroids.loc[centroids.recurrence_status.eq("repeat_observed_across_dates")]
        if len(repeated_centroids):
            repeated_centroids.plot(ax=axes[1], column="distinct_acquisition_dates", cmap="magma", markersize=np.clip(repeated_centroids.detection_observations * 2, 18, 150), edgecolor="black", linewidth=0.4, legend=True, legend_kwds={"label": "Distinct dates at cell centroid", "shrink": 0.65}, label="Repeated cell centroid")
    if TILED_MODE and len(points):
        minx, miny, maxx, maxy = points.total_bounds
        padx, pady = max(5_000, (maxx-minx)*0.03), max(5_000, (maxy-miny)*0.03)
        axes[1].set_xlim(minx-padx, maxx+padx); axes[1].set_ylim(miny-pady, maxy+pady)
        axes[1].set_xlabel(f"Easting (m), {DISTANCE_CRS}"); axes[1].set_ylabel(f"Northing (m), {DISTANCE_CRS}")
    else:
        axes[1].set_xlim(372_000, 475_000); axes[1].set_ylim(2_570_000, 2_656_000)
        axes[1].set_xlabel("Easting (m), UTM zone 45N"); axes[1].set_ylabel("Northing (m), UTM zone 45N")
    axes[1].set_title("Observed detection cells; cells are not physical-source IDs")
    axes[1].legend(fontsize=7, loc="best"); axes[1].grid(alpha=0.2); axes[1].set_aspect("equal", adjustable="box")
    fig.suptitle("FIRMS recurrence across dates and coordinates")
    fig.savefig(out_dir / "firms_recurrence_summary.png", dpi=180); plt.close(fig)


def markdown_table(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "_(no rows)_"
    columns = [str(c) for c in frame.columns]
    rows = [[str(value) for value in row] for row in frame.fillna("").itertuples(index=False, name=None)]
    lines = ["| " + " | ".join(columns) + " |", "| " + " | ".join(["---"] * len(columns)) + " |"]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--region", default="dhanbad_jharia_bokaro", help="shared region ID")
    parser.add_argument("--region-config", type=Path, default=DEFAULT_REGION_CONFIG, help="shared region JSON")
    parser.add_argument("--firms", type=Path, help="FIRMS CSV to match (defaults to data/processed/firms_pilot.csv)")
    parser.add_argument("--osm", type=Path, help="OSM GeoPackage (defaults to the pilot GeoPackage)")
    parser.add_argument("--gem-dir", type=Path, help="optional directory containing filtered GEM JSON files")
    parser.add_argument("--output-dir", type=Path, help="new output directory; must not already exist")
    parser.add_argument("--resume", action="store_true", help="resume valid completed tile checkpoints in --output-dir")
    parser.add_argument("--tile-ids", nargs="+", help="process only these assigned tile IDs (tiled regions only)")
    return parser


def _from_root(path: Path | None, root: Path, default_relative: str) -> Path:
    selected = path if path is not None else root / default_relative
    return selected if selected.is_absolute() else (root / selected).resolve()


def main(argv: list[str] | None = None) -> int:
    global BOUNDS, DISTANCE_CRS, REGION_ID, BOUNDS_MAX_INCLUSIVE, BOUNDS_EAST_INCLUSIVE, BOUNDS_NORTH_INCLUSIVE, TILED_MODE
    args = build_parser().parse_args(argv)
    if args.resume and args.output_dir is None:
        raise ValueError("--resume requires the same explicit --output-dir used by the interrupted run")
    root = args.repo.resolve()
    try:
        region = get_region(args.region, args.region_config)
        BOUNDS = bounds_tuple(region)
        TILED_MODE = bool(region.get("tiling"))
        DISTANCE_CRS = str(region.get("recurrence_grid_crs", "EPSG:6933")) if TILED_MODE else select_projected_crs(region)
        BOUNDS_MAX_INCLUSIVE = bool(region.get("max_inclusive", False))
        BOUNDS_EAST_INCLUSIVE = BOUNDS_MAX_INCLUSIVE
        BOUNDS_NORTH_INCLUSIVE = BOUNDS_MAX_INCLUSIVE
    except RegionConfigurationError as exc:
        raise ValueError(f"Cannot run matching for region {args.region!r}: {exc}") from exc
    if args.tile_ids and not TILED_MODE:
        raise ValueError("--tile-ids is only valid for a tiled region")
    REGION_ID = args.region
    firms_path = _from_root(args.firms, root, "data/processed/firms_pilot.csv")
    osm_path = _from_root(args.osm, root, "data/processed/osm/dhanbad_jharia_bokaro_osm.gpkg")
    gem_dir = _from_root(args.gem_dir, root, "data/processed/gem")
    for path in (firms_path, osm_path):
        if not path.is_file():
            raise FileNotFoundError(f"Required input file not found: {path}")

    firms = pd.read_csv(firms_path, low_memory=False)
    required = {"latitude", "longitude"}
    if not required.issubset(firms): raise ValueError(f"FIRMS missing required coordinate columns: {required - set(firms)}")
    firms["latitude"] = pd.to_numeric(firms.latitude, errors="coerce")
    firms["longitude"] = pd.to_numeric(firms.longitude, errors="coerce")
    if "firms_source_row" in firms.columns:
        raise ValueError("FIRMS input already contains reserved column 'firms_source_row'")
    if "firms_observation_id" not in firms.columns:
        firms["firms_observation_id"] = firms.apply(stable_observation_id, axis=1)
    output_dir = _from_root(args.output_dir, root, "") if args.output_dir is not None else None
    if args.resume and (output_dir is None or not output_dir.is_dir()):
        raise ValueError(f"--resume requires an existing interrupted run directory: {output_dir}")
    out_dir = fresh_output_dir(root / "data/processed/spatial_matching", output_dir, resume=args.resume)
    run_marker = out_dir / ".thermoscope_matching_run.json"
    if args.resume:
        if not run_marker.is_file():
            raise ValueError(f"Cannot resume an unowned/unmarked directory safely: {out_dir}")
        previous_run = json.loads(run_marker.read_text(encoding="utf-8"))
        if (previous_run.get("stage") != "spatial_matching" or previous_run.get("region_id") != REGION_ID
                or previous_run.get("tile_ids") != args.tile_ids):
            raise ValueError(f"Resume directory belongs to a different stage or region: {out_dir}")
    else:
        atomic_json(run_marker, {"stage": "spatial_matching", "region_id": REGION_ID,
                                 "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                 "firms_path": str(firms_path), "osm_path": str(osm_path),
                                 "gem_dir": str(gem_dir), "tile_ids": args.tile_ids})
    tile_metadata: dict[str, object] | None = None
    if TILED_MODE:
        checkpoint_dir = out_dir / ".intermediate" / "tiles"
        result, tile_metadata = match_firms_by_tiles(firms, osm_path, root, gem_dir, region, REGION_ID,
                                                     checkpoint_dir, args.tile_ids)
        osm_layer_counts = tile_metadata["osm_layer_feature_appearances"]
        osm_geometry_counts = tile_metadata["osm_geometry_appearances"]
        osm_category_counts = tile_metadata["osm_category_appearances"]
        osm_role_counts = tile_metadata["osm_role_appearances"]
        osm_context_only_count = 0
        osm = gpd.GeoDataFrame(columns=["osm_feature_id", "osm_source_id", "feature_role", "feature_roles", "match_categories", "geometry"], geometry="geometry", crs="EPSG:4326")
        osm_all = osm.copy()
        BOUNDS = bounds_tuple(region)
        BOUNDS_EAST_INCLUSIVE = BOUNDS_NORTH_INCLUSIVE = BOUNDS_MAX_INCLUSIVE
        DISTANCE_CRS = str(region.get("recurrence_grid_crs", "EPSG:6933"))
        gem = load_gem(root, gem_dir)
        qc = {"firms_total_rows": int(len(firms)), "firms_pilot_rows": int(len(result)),
              "firms_missing_coordinates_total": int((firms.latitude.isna() | firms.longitude.isna()).sum()),
              "pilot_invalid_projected_coordinates": 0, "pilot_points_outside_bbox_after_filter": 0,
              "pilot_geometry_invalid": 0, "osm_features_used": int(sum(t["osm_features_used_for_matching"] for t in tile_metadata["tiles"])),
              "osm_invalid_or_empty_filtered": 0, "tile_processing": tile_metadata,
              "recurrence_grid_crs": DISTANCE_CRS}
    else:
        osm_all, osm_layer_counts, osm_geometry_counts = load_osm(osm_path)
        candidate_feature = osm_all.feature_role.map(lambda role_list: any(role in MATCH_ROLES for role in role_list.split(";")))
        osm_context_only_count = int((~candidate_feature).sum())
        osm = osm_all.loc[candidate_feature].copy()
        gem = load_gem(root, gem_dir)
        result, qc = do_matching(firms, osm, gem)
        result["region_id"] = REGION_ID
        result["distance_crs"] = DISTANCE_CRS
        osm_category_counts = dict(Counter(cat for cats in osm_all.match_categories for cat in cats))
        osm_role_counts = dict(Counter(role for values in osm_all.feature_roles for role in values))
    result, recurrence_cells = analyze_recurrence(result)
    tables = build_summary_tables(result)
    threshold_summary = tables["distance_threshold_summary"]
    if not threshold_summary.detections_with_relevant_feature.is_monotonic_increasing:
        raise AssertionError("Candidate counts must not decrease as distance thresholds increase")
    for table in tables.values():
        if table.isna().all(axis=None) and not table.empty:
            raise AssertionError("A generated analysis summary table is entirely empty")
    status_counts = result.match_status.value_counts(dropna=False).to_dict()
    category_counts = result.osm_nearest_feature_category.value_counts(dropna=False).head(25).to_dict()
    mining_areas = osm_all.loc[osm_all.feature_role.map(lambda values: "mining_extraction_area" in values.split(";"))] if len(osm_all) else osm_all
    mining_area_sqkm = mining_areas.to_crs("EPSG:6933").geometry.area / 1_000_000.0 if len(mining_areas) else pd.Series(dtype=float)
    for table_name, table in tables.items():
        table.to_csv(out_dir / f"{table_name}.csv", index=False)
    recurrence_cells.to_csv(out_dir / "firms_spatial_recurrence_cells.csv", index=False)
    osm_available_count = int(tile_metadata["osm_total_feature_appearances"]) if TILED_MODE else int(len(osm_all))
    quarry_count = int(tile_metadata["osm_quarry_area_appearances"]) if TILED_MODE else int(len(mining_areas))
    qc.update({"osm_layer_feature_counts": osm_layer_counts, "osm_geometry_type_counts": osm_geometry_counts,
               "osm_relevant_category_counts_overlapping": osm_category_counts, "osm_feature_role_counts_overlapping": osm_role_counts,
               "match_status_counts": status_counts,
               "nearest_osm_category_counts": category_counts, "gem_filtered_records": int(len(gem)),
               "osm_features_available_in_relevant_source_gpkg_or_tile_reads": osm_available_count,
               "osm_context_only_features_not_used_for_industrial_proximity": osm_context_only_count,
               "osm_quarry_area_geometry_count": quarry_count,
               "osm_quarry_area_geometry_area_sqkm_median": float(mining_area_sqkm.median()) if len(mining_area_sqkm) else None,
               "osm_quarry_area_geometry_area_sqkm_max": float(mining_area_sqkm.max()) if len(mining_area_sqkm) else None,
               "osm_source_id_missing_after_way_id_fallback": int(osm.osm_source_id.isna().sum()),
               "osm_gpkg_fid_fallback_count": int(osm.osm_feature_id.str.startswith("gpkg:").sum()),
               "distance_crs": "tile-specific (see tile_processing.tiles)" if TILED_MODE else DISTANCE_CRS,
               "recurrence_grid_crs": str(region.get("recurrence_grid_crs", DISTANCE_CRS)),
               "osm_proximity_radius_m": OSM_RADIUS_M,
               "ambiguity_tolerance_m": AMBIGUITY_TOLERANCE_M, "gem_supplementary_radius_m": GEM_RADIUS_M,
               "source_files": {"firms": str(firms_path), "osm": str(osm_path)},
               "region_id": REGION_ID, "region_config_path": str(args.region_config.resolve()),
               "country_boundary": ({"source": region["country_boundary"].get("source"),
                                     "source_version": region["country_boundary"].get("source_version"),
                                     "prepared_sha256": region["country_boundary"].get("prepared_sha256"),
                                     "membership_rule": "boundary-inclusive point coverage"}
                                    if region.get("country_boundary") else None),
               "region_max_bounds_inclusive": BOUNDS_MAX_INCLUSIVE,
               "bbox_wgs84": {"west": BOUNDS[0], "south": BOUNDS[1], "east": BOUNDS[2], "north": BOUNDS[3]},
               "distance_threshold_summary": threshold_summary.to_dict(orient="records"),
               "recurrence_method": {"algorithm": "fixed region grid" if not TILED_MODE else "one global equal-area grid computed after tile combination",
                                     "grid_crs": str(region.get("recurrence_grid_crs", DISTANCE_CRS)), "cell_size_m": RECURRENCE_CELL_M,
                                     "repeated_across_dates": "at least two distinct acq_date values within a grid cell",
                                     "interpretation": "grid cells are analysis units, not verified physical sources; cell boundaries can split a site"},
               "recurrence_summary": tables["recurrence_summary"].to_dict(orient="records"),
               "interpretation": "Proximity evidence only. OSM/GEM proximity does not establish cause, verified source, or ground truth."})

    csv_path = out_dir / "firms_pilot_osm_proximity.csv"
    result.to_csv(csv_path, index=False)
    spatial_result = gpd.GeoDataFrame(result, geometry=gpd.points_from_xy(result.longitude, result.latitude), crs="EPSG:4326")
    gpkg_path = out_dir / "firms_pilot_osm_proximity.gpkg"
    spatial_result.to_file(gpkg_path, layer="firms_pilot_matches", driver="GPKG", index=False)
    written = gpd.read_file(gpkg_path, layer="firms_pilot_matches")
    if len(written) != len(result) or str(written.crs).upper() != "EPSG:4326" or written.geometry.isna().any() or (~written.geometry.is_valid).any():
        raise AssertionError("Saved GeoPackage failed row count, CRS, missing geometry, or validity checks")
    valid_status = written.match_status.isin(["proximity_candidate", "ambiguous_proximity"])
    if written.match_status.isna().any() or written.loc[valid_status, "osm_nearest_distance_m"].isna().any():
        raise AssertionError("Saved GeoPackage has missing status or candidate distance fields")
    if TILED_MODE:
        save_tiled_detection_map(out_dir, result, tile_metadata["tiles"])
    else:
        save_map(out_dir, result, osm_all, gem)
    save_threshold_plot(out_dir, tables)
    save_daily_plot(out_dir, tables["firms_detections_by_acquisition_date"])
    save_recurrence_plots(out_dir, result, recurrence_cells)

    qc["output_files"] = {"csv": csv_path.name, "gpkg": gpkg_path.name,
                          "map": "tiled_firms_overview.png" if TILED_MODE else "pilot_spatial_context.png",
                          "distance_plot": "distance_and_feature_role_summary.png", "recurrence_plot": "firms_recurrence_summary.png",
                          "daily_plot": "daily_detection_recurrence.png",
                          "recurrence_cells": "firms_spatial_recurrence_cells.csv",
                          "tables": [f"{name}.csv" for name in tables]}
    required_match_fields = ["osm_nearby_feature_count_1km", "match_status"]
    if not TILED_MODE:
        required_match_fields += ["osm_nearest_distance_m", "osm_nearest_feature_id", "osm_nearest_osm_element_type", "osm_nearest_feature_label", "osm_nearest_feature_category", "osm_nearest_feature_role", "osm_nearest_tag_signature", "osm_nearest_source_layer"]
    qc["matching_field_null_counts"] = result[required_match_fields].isna().sum().to_dict()
    qc["recurrence_validation"] = {
        "detection_rows_preserved": int(len(result)) == int(qc["firms_pilot_rows"]),
        "cell_ids_assigned_to_all_rows": bool(result.hotspot_cell_id.notna().all()),
        "repeat_status_requires_multiple_dates": bool(result.loc[result.cell_recurrence_status.eq("repeat_observed_across_dates"), "cell_distinct_acquisition_dates"].ge(2).all()),
        "required_matching_fields_have_no_nulls": not bool(result[required_match_fields].isna().any().any()),
        "tile_assignment_unique": bool(result.firms_source_row.is_unique and result.firms_observation_id.is_unique) if TILED_MODE else True,
        "threshold_counts_monotonic": bool(threshold_summary.detections_with_relevant_feature.is_monotonic_increasing),
    }
    (out_dir / "summary.json").write_text(json.dumps(json_safe(qc), indent=2, default=str) + "\n", encoding="utf-8")
    status_lines = "\n".join(f"- `{key}`: {value:,}" for key, value in status_counts.items())
    cat_lines = "\n".join(f"- `{key}`: {value:,}" for key, value in osm_category_counts.items())
    candidate_rows = result.loc[result.match_status.isin(["proximity_candidate", "ambiguous_proximity"])]
    current_unambiguous = int(result.match_status.eq("proximity_candidate").sum())
    current_ambiguous = int(result.match_status.eq("ambiguous_proximity").sum())
    top_tags = tables["candidate_nearest_tag_breakdown"].loc[tables["candidate_nearest_tag_breakdown"].match_status.eq("proximity_candidate")].head(15)
    ambiguous_tags = tables["candidate_nearest_tag_breakdown"].loc[tables["candidate_nearest_tag_breakdown"].match_status.eq("ambiguous_proximity")].head(10)
    role_1km = tables["role_coverage_by_threshold"].loc[tables["role_coverage_by_threshold"].threshold_m.eq(1_000), ["feature_role", "detections_with_any_feature_in_role", "detections_with_role_as_overall_nearest"]]
    nearest_role_1km = tables["nearest_feature_role_by_threshold"].loc[tables["nearest_feature_role_by_threshold"].threshold_m.eq(1_000)]
    recurrence_role_1km = tables["candidate_counts_by_recurrence_role"].loc[tables["candidate_counts_by_recurrence_role"].threshold_m.eq(1_000)]
    repeated_cells = int(recurrence_cells.recurrence_status.eq("repeat_observed_across_dates").sum()) if len(recurrence_cells) else 0
    repeat_observations = int(recurrence_cells.loc[recurrence_cells.recurrence_status.eq("repeat_observed_across_dates"), "detection_observations"].sum()) if len(recurrence_cells) else 0
    source_dates = int(pd.to_datetime(result.acq_date, errors="coerce").dt.date.nunique())
    quarry_area_summary = (
        f"median {qc['osm_quarry_area_geometry_area_sqkm_median']:.2f} km²; maximum {qc['osm_quarry_area_geometry_area_sqkm_max']:.2f} km²"
        if qc["osm_quarry_area_geometry_area_sqkm_median"] is not None
        else "per-tile area summary not aggregated"
    )
    top_daily = tables["firms_detections_by_acquisition_date"].sort_values("firms_detections", ascending=False).head(10)
    report = f"""# ThermoScope spatial-matching and recurrence review: {REGION_ID}

## Scope and interpretation

FIRMS coordinates use the configured region {REGION_ID}; source/output coordinates remain EPSG:4326. {"Each active tile uses its own local projected CRS for distances; recurrence is computed after all tiles are combined in " + str(region.get("recurrence_grid_crs", "EPSG:6933")) + "." if TILED_MODE else "Distances use configured local projected CRS " + DISTANCE_CRS + "."} Threshold comparisons are inclusive at {', '.join(str(v) + ' m' for v in DISTANCE_THRESHOLDS_M)}. Ambiguity is flagged when a second distinct mapped feature lies within {AMBIGUITY_TOLERANCE_M:.0f} m of the nearest. GEM mine/plant records are supplementary context. Proximity is evidence for investigation, never verified cause or ground truth.

## Counts and validation

- FIRMS input rows: {qc['firms_total_rows']:,}
- FIRMS rows in region: {qc['firms_pilot_rows']:,}
- Missing FIRMS coordinates in source: {qc['firms_missing_coordinates_total']:,}
- OSM proximity features used (industrial, extraction, waste, rail, and power roles): {qc['osm_features_used']:,}
- OSM `landuse=quarry` area geometries/appearances: {qc['osm_quarry_area_geometry_count']:,} ({quarry_area_summary})
- OSM rows lacking any node/way/relation ID after the `osm_way_id` fallback: {qc['osm_source_id_missing_after_way_id_fallback']:,}; GeoPackage feature-ID fallback used: {qc['osm_gpkg_fid_fallback_count']:,}
- OSM source layer counts: `{json.dumps(osm_layer_counts)}`
- OSM geometry types: `{json.dumps(osm_geometry_counts)}`
- OSM invalid/empty geometries among selected match features: {qc['osm_invalid_or_empty_filtered']:,}
- Invalid projected FIRMS coordinates: {qc['pilot_invalid_projected_coordinates']:,}
- Region points outside bbox after filter: {qc['pilot_points_outside_bbox_after_filter']:,}
- Invalid FIRMS point geometries: {qc['pilot_geometry_invalid']:,}
- Supplementary GEM sites in bbox: {len(gem):,}
- FIRMS acquisition dates represented: {source_dates}
    - Current 1 km evidence: {current_unambiguous:,} proximity candidates and {current_ambiguous:,} ambiguous out of {len(candidate_rows):,} detections with a relevant mapped feature in range.

### Overlapping OSM categories

{cat_lines}

### FIRMS match status

{status_lines}

### Counts by threshold

{markdown_table(threshold_summary)}

### Role coverage at 1 km

Counts overlap when a feature has multiple roles or when multiple roles are near one detection. `detections_with_role_as_overall_nearest` counts records whose overall nearest mapped feature includes the role.

{markdown_table(role_1km)}

Transmission tower proximity here means a tower point occurs within 1 km of a detection; it is general grid context. It does not identify the source of a thermal observation. The nearest-role split is:

{markdown_table(nearest_role_1km)}

### Candidate counts by recurrence and nearest feature role at 1 km

These categories can overlap in nearby-feature coverage; the table counts each detection once under its deterministically selected nearest role.

{markdown_table(recurrence_role_1km)}

### Nearest-feature tags among detections within 1 km

Tag counts below use the deterministically selected nearest feature per detection for the {current_unambiguous:,} unambiguous `proximity_candidate` rows; they do not count every nearby feature. The second table shows top tags among the separately flagged {current_ambiguous:,} ambiguous rows. The full role coverage table is in `role_coverage_by_threshold.csv`.

{markdown_table(top_tags)}

#### Top tags among ambiguous detections

{markdown_table(ambiguous_tags)}

### Recurrence across dates and coordinates

Observations are grouped into fixed {RECURRENCE_CELL_M:.0f} m square cells on the UTM grid; a cell is marked recurrent only when its observations span at least two distinct `acq_date` values. Fixed cells avoid DBSCAN's long chaining clusters, but cell boundaries can split observations from one real site into adjacent cells. These are spatial analysis units, not physical-source IDs or labels. {repeated_cells:,} grid cells recur across dates and contain {repeat_observations:,} FIRMS observation rows. Coordinates are also rounded to five decimal places to measure whether the identical rounded coordinate was observed on multiple dates.

{markdown_table(tables['recurrence_summary'])}

Top 10 dates by number of FIRMS detection rows:

{markdown_table(top_daily)}

The complete daily time series is `firms_detections_by_acquisition_date.csv`. Cell-level detail is in `firms_spatial_recurrence_cells.csv`; row-level cell/date assignments remain in the matched CSV. The three cells with repeated identical five-decimal coordinates span {int(recurrence_cells.repeated_same_rounded_coordinate_across_dates.sum())} grid cells; repeated coordinates still do not identify causal sources.

## Match fields

The CSV preserves all original FIRMS attributes and adds original source-row index, nearest OSM distance, element-aware feature ID and element type, OSM ID, label/category/role/layer/tag signature, threshold counts/statuses, separate nearest GEM site fields, and a non-causality interpretation field. `unknown_no_relevant_osm_within_1000m` means the nearest relevant mapped feature is outside the screening radius. `ambiguous_proximity` denotes near-tied distinct OSM features. Other detections are `proximity_candidate`, which still means only spatial proximity.

## Coverage and limitations

The OSM source is a single current snapshot and may be incomplete or inconsistently tagged. Matching roles separate industrial landuse/facilities, broad quarry-area polygons, mine working features, waste facilities, industrial rail, generation sites, substations/power sites, transmission lines, transmission towers, distribution infrastructure, and other power features. `landuse=quarry` polygons describe mapped extraction areas rather than point locations of individual active workings; because their geometries can be broad, they dominate the expanded proximity counts and must be interpreted as area context, not point-source evidence. Transmission towers remain in the analysis; they are general grid infrastructure and are not automatically treated as industrial facilities. Vegetation is retained as separate map context and excluded from industrial proximity statuses. Role coverage counts can overlap. FIRMS observation coordinates and acquisition timing, OSM geometries, and GEM site coordinate precision differ; this workflow does not fuse satellite imagery or infer event cause. GEM records represent coal mines/plants only and do not cover all industrial sources.

The OSM `all_tags` field was parsed from the actual GDAL output in either JSON or Python-dict literal form, and matching uses both geometry and those tags. All retained candidate distances are computed against points, lines, and polygons in the projected CRS, so polygon interior matches have zero distance and line distance is point-to-line distance.
"""
    (out_dir / "summary_report.md").write_text(report, encoding="utf-8")
    print(f"Output directory: {out_dir}")
    print(json.dumps({"pilot_detections": len(result), "osm_features_used": len(osm), "gem_sites": len(gem),
                      "match_status_counts": status_counts, "validation": {k: qc[k] for k in ["pilot_invalid_projected_coordinates", "pilot_points_outside_bbox_after_filter", "pilot_geometry_invalid", "osm_invalid_or_empty_filtered"]}}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
