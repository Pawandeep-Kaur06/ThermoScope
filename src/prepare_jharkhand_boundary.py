"""Prepare the Jharkhand admin-1 boundary from the pinned local OSM extract.

This reads existing local data only. It never downloads a boundary or modifies
the source PBF. The output is derived from the OSM administrative relation and
is suitable as a reproducible project-domain mask, not as a legal boundary.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PBF = ROOT / "data/raw/osm/geofabrik_eastern-zone_261016.osm.pbf"
DEFAULT_OUTPUT = ROOT / "data/processed/boundaries/jharkhand_osm_admin4.geojson"
EXPECTED_NAME = "Jharkhand"
EXPECTED_ADMIN_LEVEL = "4"
SEARCH_BOUNDS = (82.5, 20.5, 89.0, 26.5)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def select_boundary(frame: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Select and validate exactly the named administrative level-4 feature."""
    if frame.empty:
        raise ValueError("The local OSM extract contains no Jharkhand admin-level-4 feature")
    for required in ("name", "admin_level", "boundary", "geometry"):
        if required not in frame.columns:
            raise ValueError(f"OSM boundary layer is missing required field {required!r}")
    selected = frame.loc[
        frame["name"].astype(str).str.casefold().eq(EXPECTED_NAME.casefold())
        & frame["admin_level"].astype(str).eq(EXPECTED_ADMIN_LEVEL)
        & frame["boundary"].astype(str).eq("administrative")
    ].copy()
    selected = selected.loc[selected.geometry.notna()]
    if len(selected) != 1:
        raise ValueError(f"Expected one Jharkhand administrative relation; found {len(selected)}")
    geometry = selected.geometry.iloc[0]
    if geometry.is_empty or geometry.geom_type not in {"Polygon", "MultiPolygon"}:
        raise ValueError(f"Jharkhand OSM boundary is not polygonal: {geometry.geom_type}")
    if not geometry.is_valid:
        raise ValueError("Jharkhand OSM boundary geometry is invalid; refusing silent repair")
    if selected.crs is None:
        raise ValueError("Jharkhand OSM boundary has no CRS metadata")
    selected = selected.to_crs("EPSG:4326")
    selected = selected[["osm_id", "name", "boundary", "admin_level", "geometry"]]
    return selected


def prepare(pbf_path: Path, output_path: Path) -> dict:
    pbf_path, output_path = pbf_path.resolve(), output_path.resolve()
    if not pbf_path.is_file():
        raise FileNotFoundError(f"Local OSM PBF does not exist: {pbf_path}")
    manifest_path = output_path.with_suffix(".manifest.json")
    if output_path.exists() or manifest_path.exists():
        raise FileExistsError(f"Boundary output already exists; choose a new path: {output_path}")
    try:
        import pyogrio
    except ImportError as exc:
        raise RuntimeError("Boundary preparation requires the project's pyogrio/GDAL OSM driver") from exc
    if pyogrio.list_drivers(read=True).get("OSM") != "r":
        raise RuntimeError("Installed GDAL/Pyogrio has no readable OSM driver")
    frame = pyogrio.read_dataframe(
        pbf_path,
        layer="multipolygons",
        bbox=SEARCH_BOUNDS,
        where="name = 'Jharkhand' AND admin_level = '4' AND boundary = 'administrative'",
        use_arrow=False,
    )
    selected = select_boundary(frame)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    selected.to_file(output_path, driver="GeoJSON", index=False)
    manifest = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "OpenStreetMap contributors via Geofabrik Eastern Zone extract",
        "source_extract": "eastern-zone-261016; OSM data through 2026-10-16",
        "source_path": pbf_path.as_posix(),
        "source_size_bytes": pbf_path.stat().st_size,
        "source_sha256": sha256_file(pbf_path),
        "source_license": "Open Database License (ODbL) 1.0; attribute OpenStreetMap contributors",
        "osm_relation_id": str(selected.iloc[0].get("osm_id", "")),
        "name": EXPECTED_NAME,
        "boundary": "administrative",
        "admin_level": EXPECTED_ADMIN_LEVEL,
        "search_bounds_wgs84": list(SEARCH_BOUNDS),
        "geometry_crs": "EPSG:4326",
        "geometry_type": selected.geometry.iloc[0].geom_type,
        "geometry_valid": bool(selected.geometry.iloc[0].is_valid),
        "geometry_bounds_wgs84": list(selected.total_bounds),
        "output": output_path.as_posix(),
        "output_sha256": sha256_file(output_path),
        "limitations": [
            "This is the administrative boundary encoded in the pinned OSM snapshot, not a legal survey boundary.",
            "OSM boundary representation may differ from authoritative government demarcations.",
            "Preserve OSM attribution and ODbL terms for derived spatial outputs.",
        ],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pbf", type=Path, default=DEFAULT_PBF)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    manifest = prepare(args.pbf, args.output)
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
