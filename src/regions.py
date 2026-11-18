"""Shared region configuration and coordinate/CRS helpers for ThermoScope."""
from __future__ import annotations

import json
import math
import hashlib
from functools import lru_cache
from pathlib import Path
from typing import Any

DEFAULT_REGION_CONFIG = Path(__file__).resolve().parents[1] / "config" / "regions.json"


class RegionConfigurationError(ValueError):
    """Raised for missing or invalid region definitions."""


def load_regions(path: Path | str = DEFAULT_REGION_CONFIG) -> dict[str, Any]:
    config_path = Path(path)
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RegionConfigurationError(f"Could not read region configuration {config_path}: {exc}") from exc
    if config.get("schema_version") != 1 or not isinstance(config.get("regions"), dict):
        raise RegionConfigurationError(f"Unsupported or invalid region configuration: {config_path}")
    return config


def get_region(region_id: str, config_path: Path | str = DEFAULT_REGION_CONFIG) -> dict[str, Any]:
    regions = load_regions(config_path)["regions"]
    if region_id not in regions:
        raise RegionConfigurationError(
            f"Unknown region ID {region_id!r}; configured regions: {', '.join(sorted(regions))}"
        )
    region = regions[region_id]
    bbox = region.get("bbox_wgs84", {})
    required = {"west", "south", "east", "north"}
    if region.get("boundary_type") not in {"bbox", "bbox_with_country_polygon"} or not required.issubset(bbox):
        raise RegionConfigurationError(f"Region {region_id!r} needs a bbox_wgs84 with west/south/east/north")
    west, south, east, north = (float(bbox[k]) for k in ("west", "south", "east", "north"))
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise RegionConfigurationError(f"Region {region_id!r} has invalid WGS84 bounds: {bbox}")
    if region.get("boundary_type") == "bbox_with_country_polygon":
        boundary = region.get("country_boundary")
        if not isinstance(boundary, dict) or not boundary.get("geometry_path") or not boundary.get("prepared_sha256"):
            raise RegionConfigurationError(f"Region {region_id!r} requires country_boundary geometry_path and prepared_sha256")
        region["_config_root"] = config_path.resolve().parent.parent
    return region


def bounds_tuple(region: dict[str, Any]) -> tuple[float, float, float, float]:
    """Return (west, south, east, north) in WGS84."""
    b = region["bbox_wgs84"]
    return float(b["west"]), float(b["south"]), float(b["east"]), float(b["north"])


def contains_coordinates(longitude: Any, latitude: Any, region: dict[str, Any]):
    """Test bbox/tile-grid extent and, when configured, country-polygon membership.

    Shapely ``intersects_xy`` semantics include points on the country polygon's
    boundary so valid coast/border observations are retained.
    """
    west, south, east, north = bounds_tuple(region)
    max_inclusive = bool(region.get("max_inclusive", False))
    if max_inclusive:
        mask = longitude.ge(west) & longitude.le(east) & latitude.ge(south) & latitude.le(north)
    else:
        mask = longitude.ge(west) & longitude.lt(east) & latitude.ge(south) & latitude.lt(north)
    if region.get("boundary_type") == "bbox_with_country_polygon":
        import numpy as np
        from shapely import intersects_xy
        lon_values = np.asarray(longitude, dtype=float)
        lat_values = np.asarray(latitude, dtype=float)
        polygon_membership = intersects_xy(load_country_boundary(region), lon_values, lat_values)
        if hasattr(mask, "index"):
            import pandas as pd
            polygon_membership = pd.Series(polygon_membership, index=mask.index)
        mask = mask & polygon_membership
    return mask


def coordinate_in_region(longitude: float, latitude: float, region: dict[str, Any]) -> bool:
    west, south, east, north = bounds_tuple(region)
    if bool(region.get("max_inclusive", False)):
        inside_bbox = west <= float(longitude) <= east and south <= float(latitude) <= north
    else:
        inside_bbox = west <= float(longitude) < east and south <= float(latitude) < north
    if not inside_bbox:
        return False
    if region.get("boundary_type") == "bbox_with_country_polygon":
        from shapely.geometry import Point
        return bool(load_country_boundary(region).covers(Point(float(longitude), float(latitude))))
    return True


@lru_cache(maxsize=16)
def _read_country_boundary(path_text: str, expected_sha256: str, mtime_ns: int):
    """Load and strictly validate a cached WGS84 country polygon."""
    from shapely.geometry import shape
    path = Path(path_text)
    if not path.is_file():
        raise RegionConfigurationError(
            f"Country boundary file is missing: {path}. Prepare it with `python src/prepare_country_boundary.py --download`."
        )
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != expected_sha256:
        raise RegionConfigurationError(f"Country boundary checksum mismatch for {path}: expected {expected_sha256}, found {digest}")
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        crs_name = obj.get("crs", {}).get("properties", {}).get("name", "")
        if crs_name not in {"OGC:CRS84", "urn:ogc:def:crs:OGC:1.3:CRS84", "EPSG:4326"}:
            raise RegionConfigurationError(f"Country boundary must be WGS84 (CRS84/EPSG:4326), found {crs_name!r}")
        features = obj.get("features", [])
        if len(features) != 1:
            raise RegionConfigurationError(f"Expected one dissolved country polygon in {path}; found {len(features)} features")
        geometry = shape(features[0]["geometry"])
    except RegionConfigurationError:
        raise
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise RegionConfigurationError(f"Could not read country boundary {path}: {exc}") from exc
    if geometry.is_empty or geometry.geom_type not in {"Polygon", "MultiPolygon"} or not geometry.is_valid:
        raise RegionConfigurationError(f"Country boundary is empty, non-polygonal, or invalid: {path}")
    return geometry


def load_country_boundary(region: dict[str, Any]):
    """Return configured country polygon; invalid geometry is a hard error."""
    boundary = region.get("country_boundary")
    if not boundary:
        raise RegionConfigurationError(f"Region {region.get('name')} has no country polygon")
    config_root = Path(region.get("_config_root", DEFAULT_REGION_CONFIG.resolve().parent.parent))
    path = Path(boundary["geometry_path"])
    if not path.is_absolute():
        path = config_root / path
    if not path.is_file():
        # Keep the helpful missing-file message from the cached reader.
        _read_country_boundary(str(path.resolve()), str(boundary["prepared_sha256"]), -1)
    return _read_country_boundary(str(path.resolve()), str(boundary["prepared_sha256"]), path.stat().st_mtime_ns)


def select_projected_crs(region: dict[str, Any], longitude: float | None = None,
                         latitude: float | None = None) -> str:
    """Choose a local metric CRS; nationwide mode requires callers to partition by tile."""
    if region.get("projected_crs"):
        return str(region["projected_crs"])
    strategy = region.get("projected_crs_strategy", "utm_from_region_center")
    if strategy == "utm_per_tile":
        if longitude is None or latitude is None:
            raise RegionConfigurationError(
                "This region spans multiple UTM zones; choose a local CRS per processing tile. "
                "Single-CRS nationwide matching is intentionally unsupported."
            )
        lon, lat = float(longitude), float(latitude)
    elif strategy == "utm_from_region_center":
        west, south, east, north = bounds_tuple(region)
        if east - west > 6:
            raise RegionConfigurationError("Region is too wide for one local UTM CRS; split it into tiles.")
        lon, lat = (west + east) / 2, (south + north) / 2
    else:
        raise RegionConfigurationError(f"Unknown projected CRS strategy: {strategy!r}")
    if not (-80 <= lat <= 84):
        raise RegionConfigurationError(f"UTM is not defined at latitude {lat}; configure a local CRS explicitly.")
    zone = max(1, min(60, int((lon + 180) // 6) + 1))
    return f"EPSG:{32600 + zone if lat >= 0 else 32700 + zone}"


def grid_crs_prefix(crs: str) -> str:
    """Stable readable prefix for UTM grid keys (e.g. EPSG:32645 -> utm45n)."""
    code = int(str(crs).split(":")[-1])
    if 32601 <= code <= 32660:
        return f"utm{code - 32600}n"
    if 32701 <= code <= 32760:
        return f"utm{code - 32700}s"
    if code == 6933:
        return "epsg6933"
    return "grid"


def get_tile_config(region: dict[str, Any]) -> dict[str, Any]:
    tiling = region.get("tiling")
    if not isinstance(tiling, dict) or tiling.get("scheme") != "regular_latlon":
        raise RegionConfigurationError(f"Region {region.get('name', '<unknown>')} has no supported regular_latlon tiling")
    width = float(tiling.get("tile_width_degrees", 0))
    height = float(tiling.get("tile_height_degrees", 0))
    if width <= 0 or height <= 0:
        raise RegionConfigurationError("Tile width and height must be positive")
    return tiling


def tile_counts(region: dict[str, Any]) -> tuple[int, int]:
    tiling = get_tile_config(region)
    west, south, east, north = bounds_tuple(region)
    return math.ceil((east - west) / float(tiling["tile_width_degrees"])), math.ceil((north - south) / float(tiling["tile_height_degrees"]))


def tile_for_coordinate(longitude: float, latitude: float, region: dict[str, Any]) -> dict[str, Any] | None:
    """Return one stable tile for a WGS84 point; shared edges belong east/north tiles."""
    if not coordinate_in_region(longitude, latitude, region):
        return None
    tiling = get_tile_config(region)
    west, south, east, north = bounds_tuple(region)
    width, height = float(tiling["tile_width_degrees"]), float(tiling["tile_height_degrees"])
    ncols, nrows = tile_counts(region)
    col = min(ncols - 1, int(math.floor((float(longitude) - west) / width)))
    row = min(nrows - 1, int(math.floor((float(latitude) - south) / height)))
    tile_west, tile_south = west + col * width, south + row * height
    tile_east, tile_north = min(east, tile_west + width), min(north, tile_south + height)
    tile_id = str(tiling.get("id_template", "tile_r{row:02d}_c{column:02d}")).format(row=row, column=col)
    tile = {
        "tile_id": tile_id,
        "row": row,
        "column": col,
        "bbox_wgs84": {"west": tile_west, "south": tile_south, "east": tile_east, "north": tile_north},
        "max_inclusive": col == ncols - 1 and row == nrows - 1 and bool(region.get("max_inclusive", False)),
    }
    # A tile also includes the top outer edge for the last row and the right outer
    # edge for the last column; intersection elsewhere is deliberately half-open.
    tile["east_inclusive"] = col == ncols - 1 and bool(region.get("max_inclusive", False))
    tile["north_inclusive"] = row == nrows - 1 and bool(region.get("max_inclusive", False))
    tile["projected_crs"] = select_projected_crs(
        {"bbox_wgs84": tile["bbox_wgs84"], "projected_crs_strategy": "utm_from_region_center"}
    )
    return tile


def assign_tile_ids(longitudes: Any, latitudes: Any, region: dict[str, Any]) -> list[str | None]:
    """Assign a tile ID (or None outside the region) to each paired coordinate."""
    if len(longitudes) != len(latitudes):
        raise ValueError("Longitude and latitude arrays must have equal length")
    result = []
    for lon, lat in zip(longitudes, latitudes):
        try:
            result.append(tile_for_coordinate(float(lon), float(lat), region)["tile_id"])
        except (TypeError, ValueError):
            result.append(None)
    return result


def assign_recurrence_grid(longitudes: Any, latitudes: Any, region: dict[str, Any], cell_size_m: float = 250.0) -> list[str]:
    """Compute tile-independent recurrence keys in the configured equal-area grid CRS."""
    from pyproj import Transformer

    if cell_size_m <= 0:
        raise ValueError("Recurrence cell size must be positive")
    crs = str(region.get("recurrence_grid_crs") or region.get("projected_crs") or "EPSG:6933")
    transformer = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    x, y = transformer.transform(longitudes, latitudes)
    prefix = grid_crs_prefix(crs)
    return [f"{prefix}_{math.floor(float(xx) / cell_size_m)}_{math.floor(float(yy) / cell_size_m)}" for xx, yy in zip(x, y)]


def stable_observation_id(row: Any) -> str:
    """Stable source-independent FIRMS observation key, compatible with preparation."""
    lat = f"{float(row['latitude']):.8f}"
    lon = f"{float(row['longitude']):.8f}"
    date = str(row.get("acq_date", "")).strip()
    time = str(row.get("acq_time", "")).strip()
    if date:
        try:
            from datetime import date as date_type
            date = date_type.fromisoformat(date[:10]).isoformat()
        except ValueError:
            pass
    if time.isdigit():
        time = time.zfill(4)[-4:]
    values = [lat, lon, date, time, str(row.get("satellite", "")).strip().upper(),
              str(row.get("instrument", "")).strip().upper()]
    for column in ("scan", "track"):
        value = row.get(column, "")
        text = "" if value is None else str(value).strip()
        values.append("" if text.lower() in {"", "nan", "na", "n/a", "null", "none", "<na>"} else text)
    return hashlib.sha256("\x1f".join(values).encode("utf-8")).hexdigest()
