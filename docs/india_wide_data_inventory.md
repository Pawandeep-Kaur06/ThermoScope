# India-wide FIRMS and satellite data inventory

## Scope and methods

Read-only local inventory on 2026-11-16. No network/API requests, downloads, pipeline reruns, or training occurred. FIRMS CSVs were streamed in 150,000-row chunks. Observation identity follows the preparation script's normalized coordinates/date/time/platform/instrument/scan/track identity; two independent 64-bit pandas fingerprints were used as compact comparison keys, so a hash collision is theoretically possible. India counts use the configured Natural Earth India POV polygon within its grid envelope. TIFF metadata were read with Rasterio and each TIFF was SHA256-hashed. The detailed per-file records are in the two requested CSVs.

CSV metadata do not include a complete FIRMS product/query manifest. Explicit row fields are separated from product-family inference below.

## FIRMS inventory

| File | Role/source | Rows | Date range (distinct dates) | Coordinate extent | India bbox rows | India polygon rows | Unique identities | Duplicate identity rows |
|---|---|---:|---|---|---:|---:|---:|---:|
| data/raw/archive.csv | archive | 4,073,699 | 2026-01-20 to 2026-04-27 (95) | -79.2572..82.8202 N/S; -176.1341..179.8234 E/W | 594,409 | 374,683 | 4,073,699 | 0 |
| data/raw/nrt.csv | NRT | 7,247,714 | 2026-04-28 to 2026-09-07 (127) | -87.7964..73.5368 N/S; -179.9810..179.8358 E/W | 127,382 | 103,701 | 7,247,710 | 4 |
| data/processed/india_archive.csv | archive (legacy rectangular subset) | 638,069 | 2026-01-20 to 2026-04-27 (95) | 6.0278..37.9999 N/S; 68.0000..98.0000 E/W | 594,409 | 374,683 | 638,069 | 0 |
| data/processed/india_nrt.csv | NRT | 128,509 | 2026-04-30 to 2026-09-07 (124) | 6.1124..37.9846 N/S; 68.0008..97.9990 E/W | 127,382 | 103,701 | 128,509 | 0 |
| data/processed/india_combined.csv | archive + NRT concatenation; row-level provenance absent | 766,578 | 2026-01-20 to 2026-09-07 (219) | 6.0278..37.9999 N/S; 68.0000..98.0000 E/W | 721,791 | 478,384 | 766,578 | 0 |
| data/processed/firms_pilot.csv | prepared archive/NRT union | 9,220 | 2026-01-20 to 2026-09-05 (184) | 23.2529..23.9935 N/S; 85.7508..86.7499 E/W | 9,220 | 9,220 | 9,220 | 0 |
| data/processed/sample_1000.csv | unknown sample source | 1,000 | 2026-01-20 to 2026-09-06 (160) | 6.1457..37.3140 N/S; 68.2475..97.9965 E/W | 942 | 605 | 1,000 | 0 |
| data/processed/final_pilot_experiment/run_001/input/firms_pilot.csv | prepared archive/NRT union | 9,220 | 2026-01-20 to 2026-09-05 (184) | 23.2529..23.9935 N/S; 85.7508..86.7499 E/W | 9,220 | 9,220 | 9,220 | 0 |

### Product, schema and geographic coverage

- Raw archive platform/instrument/version counts: {"SNPP|SNPP|2": 4073699}. Raw NRT: {"SNPP|SNPP|2.0NRT": 7247714}.
- Both raw files report satellite/platform SNPP and instrument SNPP. Archive version is reported as 2; NRT version as 2.0NRT. This is consistent with a Suomi-NPP VIIRS-family FIRMS export, but the CSVs do not identify the exact product collection, nominal resolution, query endpoint or retrieval time. Product-family attribution is therefore qualified; no MODIS/other platform was observed in these local rows.
- In the raw archive, all 4,073,699 rows have values in the columns present. In raw NRT, all columns present are non-missing, but the type column is absent from the schema. The prepared pilot and run input therefore have 2,722 blank type entries; the old combined file instead uses -1 for NRT type.
- Raw archive extent: {"west": -176.13405, "south": -79.25716, "east": 179.82336, "north": 82.8202}; raw NRT extent: {"west": -179.98096, "south": -87.7964, "east": 179.83582, "north": 73.53683}. Both have coordinates outside India; raw row counts are not India counts.
- Of raw rows, 374,683 archive and 103,701 NRT coordinates fall inside the configured India polygon (478,384 combined identities, with no archive/NRT identity overlap). The legacy rectangular outputs have 766,578 rows, of which only 478,384 fall inside that polygon; 288,194 rows lie outside it. The legacy notebook rectangle 6–38°N, 68–98°E is broader than the country's configured domain.
- The prepared firms_pilot.csv and run_001/input/firms_pilot.csv are Dhanbad-region outputs. sample_1000.csv lacks recorded sampling provenance. NRT files omit type; the legacy combined file fills NRT type with -1, a missing-field sentinel.

### Dates, missingness and duplicates

- India-polygon date range in legacy archive subset: 2026-01-20–2026-04-27 (95 dates). Legacy NRT subset: 2026-04-30–2026-09-06 (123 dates). Distinct-date overlap: 0; calendar days between last archive and first NRT date: 2. A row-date gap does not prove a missing source file or continuous daily collection.
- Identity overlaps: raw archive vs raw NRT 0; india_archive vs raw archive 638,069; india_nrt vs raw NRT 128,509; legacy combined vs archive subset 638,069, vs NRT subset 128,509. The raw archive has zero repeated identities; raw NRT contains four repeated identities globally, all outside the prepared India-rectangle subset. The archive and NRT date ranges are adjacent globally (archive ends Apr 27; NRT starts Apr 28); the India-polygon detection rows begin NRT on Apr 30, leaving no Indian rows dated Apr 28–29.
- Pilot prepared IDs overlapping legacy combined 9,220; overlapping raw archive 6,498; overlapping raw NRT 2,722; run_001 input vs prepared pilot 9,220. All within-file duplicate counts and missing values are recorded per file in firms_inventory.csv.
- Raw row counts scanned: archive 4,073,699, NRT 7,247,714. Pinned config/quality manifests record 4,073,699 and 7,247,714 rows. The scan must agree before downstream reuse; if these differ, treat the source inventory as changed and revalidate.

### FIRMS consistency assessment

These exports can support a detection-level national table only after their source period, product identity and coverage are documented and schemas harmonized. The archive/NRT version and schema difference is visible, and the legacy combined table lacks explicit row provenance. Geographic extents show the raw inputs are broader than India; the legacy subsets use a rectangle. The local files alone do not establish completeness of national collection over time, so they do not yet support a defensible claim of consistent India-wide coverage. Reuse the region-aware preparation script only after confirming raw files match the checksummed inputs and writing a national query/product manifest.

## Satellite TIFF inventory


- Found 37 TIFFs across 7 satellite-investigation runs, with 22 distinct SHA256 file contents. The inventory has an absolute_path for every file. Repeated copies are not additional images; five files do not have a matching row in their run's scene_metadata.csv (their STAC ID/date can still be parsed from filenames).
- Unique STAC scene identifiers with four-band imagery: 6; distinct four-band raster contents: 14; distinct SCL raster contents: 8. Each TIFF path, size, SHA256, dimensions, band count/type, CRS, native and geographic bounds, resolution, NoData, band descriptions, scene/date, duplicates and run_001 linkage is in satellite_inventory.csv.
- Four-band chips are Sentinel-2 L2A red/green/blue (B04/B03/B02) at 10 m and B11 SWIR (native 20 m resampled onto 10 m grid); paired single-band rasters are SCL scene-classification masks. The chips are 64×64 pixels in EPSG:32645. Sentinel-2 is optical context and has no thermal band.
- The eight pinned chip/mask pairs use four distinct STAC scene IDs and are marked by pinned_run_source=true in the inventory; their item IDs, dates, cloud and SCL fields reconcile to run_20261018T212303Z/scene_metadata.csv and config/final_pilot_experiment.json. Files are exploratory windows around selected pilot grid cells, not an unbiased image sample.
- In run_001, 530 FIRMS rows have chip/scene metadata: 11 meet the per-observation scene-time ≤ acquisition-time rule, including 9 whose pixel sample is cloud/shadow contaminated or unverifiable and 2 with a clear valid sampled spectrum; 519 post-detection scenes are withheld. The two usable samples represent 2 cell-scene pairs and 2 distinct scene IDs. The other 8,690 detections have no chip metadata. This agrees with the 9,220-row feature table; file presence alone does not imply an eligible pixel.

## CV readiness

- There are 6 distinct item IDs with four-band TIFFs and 14 unique spectral-raster file contents. The pinned final feature run uses four of those scene IDs. Of the four, all have at least one temporally eligible observation, but only two have any clear valid sampled pre-detection pixel. None has an image-level class label or site/event train/test assignment; no negative examples were created.
- Feature-table eligibility: 11 of 9,220 detections have temporally eligible scenes, but only 2 have usable clear pre-detection spectra (from 2 distinct scene IDs); 9 are obscured/unverifiable and 519 scene-linked rows are future imagery. The counts follow the exact per-observation temporal and pixel/cloud-screen flags.
- The ranking table labels are {"unknown_unlinked": 9220}; evidence validation reports 0 genuinely linkable FIRMS rows. No image is paired to a reliable class label.
- Supported now: visual inspection and descriptive optical context for a few pilot cells, plus tabular candidate prioritization. No supervised or weakly supervised event/source classification, CV training example set, or India-wide model evaluation is supportable.

## Recommendation for next dataset-development phase

First recover FIRMS product/query provenance, verify the raw exports against the pinned checksums and source coverage, and create a versioned national table after explicit archive/NRT harmonization and country-polygon filtering. Then decide whether the first CV target is (a) independently labeled visual site/land-cover context or (b) documented thermal-event/source class. Run a metadata-only, stratified imagery coverage survey across multiple Indian contexts, review time offsets/cloud/storage, and retrieve a small balanced sample only after those checks. Build independent human-reviewed labels and site/event/region-separated holdouts before training.

## Deliverables and constraints

- firms_inventory.csv: one record per local raw/prepared/sample FIRMS CSV, including source role, observed platform/instrument/version, row/schema/missingness, date/geographic coverage and duplicate comparisons.
- satellite_inventory.csv: one record per local TIFF with hash, dimensions/bands, CRS/bounds, scene/date, duplicate grouping, feature linkage and temporal/QA evidence.
- No dataset was changed; no model training, experiment rerun, download or API request occurred.
