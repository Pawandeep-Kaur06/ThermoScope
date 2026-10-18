# ThermoScope OSM pilot data provenance

The pilot uses the pinned Geofabrik Eastern Zone extract `eastern-zone-261016.osm.pbf`, containing OSM data through 2026-10-16. Geofabrik listed it at 247,316,001 bytes (about 235.8 MiB). It is broader than the Dhanbad–Jharia–Bokaro study area, so the acquisition script filters it locally to the pilot bbox (23.25–24.00 N, 85.75–86.75 E). No Overpass query is used.

The extract and publisher MD5 sidecar are stored in `data/raw/osm/`; the locally filtered GeoPackage and retrieval manifest are in `data/processed/osm/`. The manifest records the retrieval timestamp, source URLs, MD5/SHA-256 checksums, bbox, geometry/tag handling, feature counts, and limitations. The current GeoPackage contains 8,333 selected OSM features.

To rebuild the processed data from the saved PBF:

```powershell
.\venv\Scripts\python.exe .\src\fetch_osm_pilot.py --process-only --overwrite
```

To reacquire the pinned extract and rebuild the GeoPackage:

```powershell
.\venv\Scripts\python.exe .\src\fetch_osm_pilot.py --download --overwrite
```

The script verifies the publisher's MD5 checksum, uses the installed GDAL OSM driver, and writes tagged geometries to a multi-layer GeoPackage. It preserves all source tags in a JSON `all_tags` field, OSM IDs, source geometry layers, and original full geometries for features intersecting the pilot bbox. The local feature selection covers industrial landuse/facilities, power infrastructure, mining/extraction, industrial structures and rail, waste facilities, and vegetation context.

OSM data is licensed under ODbL 1.0. Attribute it to OpenStreetMap contributors and retain the license notice when redistributing OSM-derived data. The extract is a current snapshot, not historical OSM for each FIRMS acquisition date. OSM coverage and tagging are incomplete; spatial matches do not establish why a FIRMS hotspot occurred. GDAL emitted warnings for some malformed source polygon rings during this conversion; no custom geometry repair was applied.
