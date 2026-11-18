"""Prepare a cached India country polygon from the Natural Earth 10m India POV.

The source archive is only about 4.9 MB. This is a boundary-only input; this
script does not access FIRMS or OSM data.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
from shapely.geometry import GeometryCollection, mapping
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[1]
SOURCE_URL = "https://naciscdn.org/naturalearth/10m/cultural/ne_10m_admin_0_countries_ind.zip"
SOURCE_PAGE = "https://www.naturalearthdata.com/downloads/10m-cultural-vectors/10m-admin-0-countries/"
TERMS_URL = "https://www.naturalearthdata.com/about/terms-of-use/"
EXPECTED_SHA256 = "36a54ee97a509325e98eb44fd91bc7e53b0c5139cf10039918042bbd64102192"
EXPECTED_SIZE = 4_922_443
RAW = ROOT / "data/raw/boundaries/ne_10m_admin_0_countries_ind_v5.1.1.zip"
OUT = ROOT / "data/processed/boundaries/india_naturalearth_10m_india_pov.geojson"
MANIFEST = ROOT / "data/processed/boundaries/manifest.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="\n", prefix=path.name + ".",
                                     suffix=".partial", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(value)
        stream.flush()
    temporary.replace(path)


def validate_polygon(geometry):
    """Return a non-empty valid polygonal geometry; reject silent repair here."""
    if geometry is None or geometry.is_empty:
        raise ValueError("Country boundary geometry is empty")
    if geometry.geom_type not in {"Polygon", "MultiPolygon"}:
        raise ValueError(f"Expected Polygon/MultiPolygon country boundary, received {geometry.geom_type}")
    if not geometry.is_valid:
        raise ValueError("Country boundary geometry is invalid; rerun the boundary preparation script")
    return geometry


def _polygon_parts(geometry):
    if geometry.geom_type == "Polygon":
        return [geometry]
    if geometry.geom_type == "MultiPolygon":
        return list(geometry.geoms)
    if isinstance(geometry, GeometryCollection):
        return [part for child in geometry.geoms for part in _polygon_parts(child)
                if child.geom_type in {"Polygon", "MultiPolygon", "GeometryCollection"}]
    return []


def extract_india(archive: Path):
    if archive.stat().st_size != EXPECTED_SIZE or sha256(archive) != EXPECTED_SHA256:
        raise ValueError(f"Natural Earth archive size/checksum mismatch: {archive}")
    with tempfile.TemporaryDirectory(prefix="thermoscope-boundary-") as temporary:
        with zipfile.ZipFile(archive) as bundle:
            shp = next((name for name in bundle.namelist() if name.endswith(".shp")), None)
            version_file = next((name for name in bundle.namelist() if name.endswith(".VERSION.txt")), None)
            if not shp or not version_file:
                raise ValueError("Natural Earth archive is missing the shapefile or version marker")
            version = bundle.read(version_file).decode("ascii").strip()
            if version != "5.1.1":
                raise ValueError(f"Expected Natural Earth v5.1.1, found {version!r}")
            bundle.extractall(temporary)
        frame = gpd.read_file(Path(temporary) / shp)
    if frame.crs is None:
        raise ValueError("Natural Earth source has no CRS")
    if frame.crs.to_epsg() != 4326:
        frame = frame.to_crs("EPSG:4326")
    selected = frame.loc[frame["ADMIN"].eq("India")]
    if len(selected) != 1:
        raise ValueError(f"Expected exactly one India feature in Natural Earth archive, found {len(selected)}")
    geometry = selected.geometry.iloc[0]
    repaired = False
    if not geometry.is_valid:
        try:
            from shapely import make_valid
            geometry = make_valid(geometry)
        except ImportError:
            geometry = geometry.buffer(0)
        parts = _polygon_parts(geometry)
        if not parts:
            raise ValueError("Geometry repair did not produce polygonal boundary components")
        geometry = unary_union(parts)
        repaired = True
    geometry = validate_polygon(geometry)
    return geometry, version, repaired


def prepare(archive: Path = RAW, output: Path = OUT, manifest_path: Path = MANIFEST) -> dict:
    archive, output, manifest_path = archive.resolve(), output.resolve(), manifest_path.resolve()
    geometry, version, repaired = extract_india(archive)
    # Existing correct output is a cache hit; invalid or unowned files are kept
    # untouched and require a new output path, avoiding accidental replacement.
    if output.exists() or manifest_path.exists():
        if output.is_file() and manifest_path.is_file():
            saved = json.loads(manifest_path.read_text(encoding="utf-8"))
            if saved.get("source_sha256") == sha256(archive) and saved.get("output_sha256") == sha256(output):
                validate_polygon(gpd.read_file(output).geometry.iloc[0])
                return saved
        raise FileExistsError(f"Boundary outputs already exist and are not a valid cache: {output}; choose a new path")
    output.parent.mkdir(parents=True, exist_ok=True)
    feature = {"type": "Feature", "properties": {"country": "India", "source": "Natural Earth Admin-0 Countries India POV", "version": version},
               "geometry": mapping(geometry)}
    atomic_text(output, json.dumps({"type": "FeatureCollection", "name": "india_boundary", "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}}, "features": [feature]}, separators=(",", ":")))
    retrieved_at = datetime.fromtimestamp(archive.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")
    metadata = {
        "source": "Natural Earth Admin-0 Countries, India point-of-view variant",
        "source_page": SOURCE_PAGE, "source_url": SOURCE_URL,
        "license": "Public domain", "license_url": TERMS_URL,
        "version": version, "scale": "1:10m",
        "retrieved_at_utc": retrieved_at,
        "source_archive": str(archive), "source_size_bytes": archive.stat().st_size,
        "source_sha256": sha256(archive), "output_file": str(output),
        "output_size_bytes": output.stat().st_size, "output_sha256": sha256(output),
        "source_crs": "EPSG:4326", "output_crs": "OGC:CRS84 (longitude, latitude; equivalent axis order for stored GeoJSON)",
        "geometry_type": geometry.geom_type, "component_count": len(geometry.geoms) if geometry.geom_type == "MultiPolygon" else 1,
        "geometry_valid_after_preparation": bool(geometry.is_valid), "geometry_repaired": repaired,
        "selection": "ADMIN == India from the India POV Admin-0 country theme",
        "limitations": ["Generalized 1:10m cartographic boundary, not a legal cadastral border.",
                        "Natural Earth's POV policy represents its India viewpoint for disputed boundaries; boundary-sensitive detections should retain uncertainty.",
                        "Small coastal/island details and positional accuracy are limited by source scale."],
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_text(manifest_path, json.dumps(metadata, indent=2) + "\n")
    return metadata


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true", help="download the 4.9 MB Natural Earth archive if missing")
    parser.add_argument("--process-only", action="store_true", help="prepare the boundary from the existing local ZIP")
    parser.add_argument("--source-zip", type=Path, default=RAW)
    parser.add_argument("--output", type=Path, default=OUT)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    args = parser.parse_args()
    if args.download == args.process_only:
        parser.error("select exactly one of --download or --process-only")
    archive = args.source_zip if args.source_zip.is_absolute() else ROOT / args.source_zip
    if args.download and not archive.exists():
        archive.parent.mkdir(parents=True, exist_ok=True)
        from urllib.request import urlretrieve
        urlretrieve(SOURCE_URL, archive)
    elif not archive.is_file():
        raise FileNotFoundError(f"Boundary archive missing: {archive}. Run with --download first.")
    result = prepare(archive, args.output if args.output.is_absolute() else ROOT / args.output,
                     args.manifest if args.manifest.is_absolute() else ROOT / args.manifest)
    print(json.dumps({"boundary": result["output_file"], "version": result["version"],
                      "sha256": result["output_sha256"], "valid": result["geometry_valid_after_preparation"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
