"""Locally match pilot FIRMS detections to tagged OSM features.

This is proximity evidence for investigation, not causal attribution or labels.
Distances are computed in UTM zone 45N (EPSG:32645); input/output coordinates
remain WGS84. Outputs are written to a fresh run directory to avoid overwrites.
"""
from __future__ import annotations

import argparse
import ast
import json
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

BOUNDS = (85.75, 23.25, 86.75, 24.00)  # west, south, east, north, WGS84
DISTANCE_CRS = "EPSG:32645"  # UTM zone 45N, appropriate for 85.75–86.75 E
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


def fresh_output_dir(parent: Path, requested: str | None) -> Path:
    if requested:
        target = Path(requested)
        if not target.is_absolute():
            target = (Path.cwd() / target).resolve()
    else:
        stamp = datetime.now(timezone.utc).strftime("run_%Y%m%dT%H%M%SZ")
        target = parent / stamp
    target.mkdir(parents=True, exist_ok=False)
    return target


def load_osm(gpkg: Path) -> tuple[gpd.GeoDataFrame, dict[str, int], dict[str, int]]:
    frames = []
    source_counts: dict[str, int] = {}
    geometry_counts: Counter[str] = Counter()
    for layer in gpd.list_layers(gpkg).name:
        frame = gpd.read_file(gpkg, layer=layer, fid_as_index=True)
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
    if not frames or not any(len(f) for f in frames):
        raise ValueError("No usable industrial/power OSM features found")
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
    projected = osm.to_crs(DISTANCE_CRS)
    return projected, source_counts, dict(geometry_counts)


def load_gem(root: Path) -> gpd.GeoDataFrame:
    files = [
        (root / "data/processed/gem/coal_mines_dhanbad_jharia_bbox.json", "GEM coal mine"),
        (root / "data/processed/gem/coal_plants_dhanbad_jharia_bbox.json", "GEM coal plant"),
    ]
    records = []
    for path, source in files:
        if not path.exists():
            continue
        obj = json.loads(path.read_text(encoding="utf-8"))
        for row in obj.get("records", []):
            lat, lon = pd.to_numeric(row.get("latitude"), errors="coerce"), pd.to_numeric(row.get("longitude"), errors="coerce")
            if pd.notna(lat) and pd.notna(lon) and 23.25 <= lat <= 24.0 and 85.75 <= lon <= 86.75:
                records.append({"name": row.get("asset_name"), "asset_type": row.get("asset_type"), "source": source,
                                "latitude": float(lat), "longitude": float(lon), "asset_id": row.get("asset_id")})
    if not records:
        return gpd.GeoDataFrame(columns=["name", "asset_type", "source", "latitude", "longitude", "asset_id", "geometry"], geometry="geometry", crs="EPSG:4326")
    return gpd.GeoDataFrame(records, geometry=gpd.points_from_xy([r["longitude"] for r in records], [r["latitude"] for r in records]), crs="EPSG:4326")


def do_matching(firms: pd.DataFrame, osm: gpd.GeoDataFrame, gem: gpd.GeoDataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    in_bbox = (
        firms.latitude.between(BOUNDS[1], BOUNDS[3], inclusive="both")
        & firms.longitude.between(BOUNDS[0], BOUNDS[2], inclusive="both")
    )
    pilot = firms.loc[in_bbox].copy()
    # row id is the zero-based original CSV data row, preserved through filtering.
    pilot.insert(0, "firms_source_row", np.flatnonzero(in_bbox.to_numpy()))
    points_wgs84 = gpd.GeoDataFrame(pilot, geometry=gpd.points_from_xy(pilot.longitude, pilot.latitude), crs="EPSG:4326")
    points_m = points_wgs84.to_crs(DISTANCE_CRS)

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
    if not (result.latitude.between(BOUNDS[1], BOUNDS[3]).all() and result.longitude.between(BOUNDS[0], BOUNDS[2]).all()):
        raise AssertionError("FIRMS pilot filter retained coordinates outside the bbox")
    if result.osm_nearest_distance_m.isna().any() or not np.isfinite(result.osm_nearest_distance_m).all():
        raise AssertionError("Nearest OSM distances have missing or non-finite values")
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
    required_match_fields = ["osm_nearest_distance_m", "osm_nearest_feature_id", "osm_nearest_osm_element_type", "osm_nearest_feature_label", "osm_nearest_feature_category", "osm_nearest_source_layer", "osm_nearby_feature_count_1km", "match_status"]
    if result[required_match_fields].isna().any().any():
        raise AssertionError("A required OSM match field is missing")
    qc = {"firms_total_rows": int(len(firms)), "firms_pilot_rows": int(len(result)),
          "firms_missing_coordinates_total": int((firms.latitude.isna() | firms.longitude.isna()).sum()),
          "pilot_invalid_projected_coordinates": invalid_coord_count,
          "pilot_points_outside_bbox_after_filter": int((~(result.latitude.between(BOUNDS[1], BOUNDS[3]) & result.longitude.between(BOUNDS[0], BOUNDS[2]))).sum()),
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
    result["hotspot_cell_id"] = [f"utm45n_{x}_{y}" for x, y in zip(cell_x, cell_y)]
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
        axes[0].set_title("Temporal recurrence (fixed 250 m UTM grid cells)"); axes[0].legend(); axes[0].grid(axis="y", alpha=0.2)
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output-dir", help="new output directory; must not already exist")
    args = parser.parse_args()
    root = args.repo.resolve()
    firms_path = root / "data/processed/india_combined.csv"
    osm_path = root / "data/processed/osm/dhanbad_jharia_bokaro_osm.gpkg"
    for path in (firms_path, osm_path):
        if not path.exists(): raise FileNotFoundError(path)
    out_dir = fresh_output_dir(root / "data/processed/spatial_matching", args.output_dir)

    firms = pd.read_csv(firms_path, low_memory=False)
    required = {"latitude", "longitude"}
    if not required.issubset(firms): raise ValueError(f"FIRMS missing required coordinate columns: {required - set(firms)}")
    firms["latitude"] = pd.to_numeric(firms.latitude, errors="coerce")
    firms["longitude"] = pd.to_numeric(firms.longitude, errors="coerce")
    osm_all, osm_layer_counts, osm_geometry_counts = load_osm(osm_path)
    candidate_feature = osm_all.feature_role.map(lambda role_list: any(role in MATCH_ROLES for role in role_list.split(";")))
    osm_context_only_count = int((~candidate_feature).sum())
    osm = osm_all.loc[candidate_feature].copy()
    gem = load_gem(root)
    result, qc = do_matching(firms, osm, gem)
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
    osm_category_counts = dict(Counter(cat for cats in osm_all.match_categories for cat in cats))
    osm_role_counts = dict(Counter(role for values in osm_all.feature_roles for role in values))
    mining_areas = osm_all.loc[osm_all.feature_role.map(lambda values: "mining_extraction_area" in values.split(";"))]
    mining_area_sqkm = mining_areas.geometry.area / 1_000_000.0
    for table_name, table in tables.items():
        table.to_csv(out_dir / f"{table_name}.csv", index=False)
    recurrence_cells.to_csv(out_dir / "firms_spatial_recurrence_cells.csv", index=False)
    qc.update({"osm_layer_feature_counts": osm_layer_counts, "osm_geometry_type_counts": osm_geometry_counts,
               "osm_relevant_category_counts_overlapping": osm_category_counts, "osm_feature_role_counts_overlapping": osm_role_counts,
               "match_status_counts": status_counts,
               "nearest_osm_category_counts": category_counts, "gem_filtered_records": int(len(gem)),
               "osm_features_available_in_relevant_source_gpkg": int(len(osm_all)),
               "osm_context_only_features_not_used_for_industrial_proximity": osm_context_only_count,
               "osm_quarry_area_geometry_count": int(len(mining_areas)),
               "osm_quarry_area_geometry_area_sqkm_median": float(mining_area_sqkm.median()) if len(mining_area_sqkm) else None,
               "osm_quarry_area_geometry_area_sqkm_max": float(mining_area_sqkm.max()) if len(mining_area_sqkm) else None,
               "osm_source_id_missing_after_way_id_fallback": int(osm.osm_source_id.isna().sum()),
               "osm_gpkg_fid_fallback_count": int(osm.osm_feature_id.str.startswith("gpkg:").sum()),
               "distance_crs": DISTANCE_CRS, "osm_proximity_radius_m": OSM_RADIUS_M,
               "ambiguity_tolerance_m": AMBIGUITY_TOLERANCE_M, "gem_supplementary_radius_m": GEM_RADIUS_M,
               "source_files": {"firms": str(firms_path), "osm": str(osm_path)},
               "bbox_wgs84": {"west": BOUNDS[0], "south": BOUNDS[1], "east": BOUNDS[2], "north": BOUNDS[3]},
               "distance_threshold_summary": threshold_summary.to_dict(orient="records"),
               "recurrence_method": {"algorithm": "fixed UTM grid", "cell_size_m": RECURRENCE_CELL_M,
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
    if written.match_status.isna().any() or written.osm_nearest_distance_m.isna().any():
        raise AssertionError("Saved GeoPackage has missing required match fields")
    save_map(out_dir, result, osm_all, gem)
    save_threshold_plot(out_dir, tables)
    save_daily_plot(out_dir, tables["firms_detections_by_acquisition_date"])
    save_recurrence_plots(out_dir, result, recurrence_cells)

    qc["output_files"] = {"csv": csv_path.name, "gpkg": gpkg_path.name, "map": "pilot_spatial_context.png",
                          "distance_plot": "distance_and_feature_role_summary.png", "recurrence_plot": "firms_recurrence_summary.png",
                          "daily_plot": "daily_detection_recurrence.png",
                          "recurrence_cells": "firms_spatial_recurrence_cells.csv",
                          "tables": [f"{name}.csv" for name in tables]}
    required_match_fields = ["osm_nearest_distance_m", "osm_nearest_feature_id", "osm_nearest_osm_element_type", "osm_nearest_feature_label", "osm_nearest_feature_category", "osm_nearest_feature_role", "osm_nearest_tag_signature", "osm_nearest_source_layer", "osm_nearby_feature_count_1km", "match_status"]
    qc["matching_field_null_counts"] = result[required_match_fields].isna().sum().to_dict()
    qc["recurrence_validation"] = {
        "detection_rows_preserved": int(len(result)) == int(qc["firms_pilot_rows"]),
        "cell_ids_assigned_to_all_rows": bool(result.hotspot_cell_id.notna().all()),
        "repeat_status_requires_multiple_dates": bool(result.loc[result.cell_recurrence_status.eq("repeat_observed_across_dates"), "cell_distinct_acquisition_dates"].ge(2).all()),
        "required_matching_fields_have_no_nulls": not bool(result[required_match_fields].isna().any().any()),
        "threshold_counts_monotonic": bool(threshold_summary.detections_with_relevant_feature.is_monotonic_increasing),
    }
    (out_dir / "summary.json").write_text(json.dumps(qc, indent=2, default=str) + "\n", encoding="utf-8")
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
    top_daily = tables["firms_detections_by_acquisition_date"].sort_values("firms_detections", ascending=False).head(10)
    report = f"""# ThermoScope pilot spatial-matching and recurrence review

## Scope and interpretation

FIRMS detections were filtered inclusively to 23.25–24.00°N, 85.75–86.75°E. OSM proximity distances use projected CRS {DISTANCE_CRS} (UTM zone 45N); source and output coordinates remain EPSG:4326. Threshold comparisons are inclusive at {', '.join(str(v) + ' m' for v in DISTANCE_THRESHOLDS_M)}. Ambiguity is flagged when a second distinct mapped feature lies within {AMBIGUITY_TOLERANCE_M:.0f} m of the nearest. GEM mine/plant records are supplementary context. Proximity is evidence for investigation, never verified cause or ground truth.

## Counts and validation

- FIRMS input rows: {qc['firms_total_rows']:,}
- FIRMS rows in pilot: {qc['firms_pilot_rows']:,}
- Missing FIRMS coordinates in source: {qc['firms_missing_coordinates_total']:,}
- OSM proximity features used (industrial, extraction, waste, rail, and power roles): {qc['osm_features_used']:,}
- OSM `landuse=quarry` area geometries: {qc['osm_quarry_area_geometry_count']:,} (median {qc['osm_quarry_area_geometry_area_sqkm_median']:.2f} km²; maximum {qc['osm_quarry_area_geometry_area_sqkm_max']:.2f} km², using retained full geometries)
- OSM rows lacking any node/way/relation ID after the `osm_way_id` fallback: {qc['osm_source_id_missing_after_way_id_fallback']:,}; GeoPackage feature-ID fallback used: {qc['osm_gpkg_fid_fallback_count']:,}
- OSM source layer counts: `{json.dumps(osm_layer_counts)}`
- OSM geometry types: `{json.dumps(osm_geometry_counts)}`
- OSM invalid/empty geometries among selected match features: {qc['osm_invalid_or_empty_filtered']:,}
- Invalid projected FIRMS coordinates: {qc['pilot_invalid_projected_coordinates']:,}
- Pilot points outside bbox after filter: {qc['pilot_points_outside_bbox_after_filter']:,}
- Invalid pilot point geometries: {qc['pilot_geometry_invalid']:,}
- Supplementary GEM sites in bbox: {len(gem):,}
- FIRMS acquisition dates represented: {source_dates}
- Earlier 1 km result: 2,210 proximity candidates plus 660 ambiguous detections using industrial/power roles. This run uses element-aware OSM IDs and additionally includes mining/extraction, industrial rail, and waste facilities as separate roles; current counts are {current_unambiguous:,} proximity candidates and {current_ambiguous:,} ambiguous out of {len(candidate_rows):,} detections within 1 km. The difference reflects corrected feature identity and expanded mapped context.

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
