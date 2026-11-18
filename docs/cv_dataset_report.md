# ThermoScope CV dataset readiness: Jharkhand

## Decision

**No supervised ThermoScope image-classification task is currently trainable from the local data.** I recommend one future image task, once references are assembled: **broad surface-context classification** (built-up, bare/sparse vegetation, vegetation, water, and other available land-cover classes), explicitly as contextual evidence for the thermal-observation workflow. This task is more tractable than industrial-fire attribution, but it is not the same as classifying industrial facilities, mines, or fires. The current local images have no credible image labels, so this report creates an unlabelled image manifest only; it does not create training examples or splits.

An external reference candidate is ESA WorldCover 2021, which has 10 m land-cover classes including “built-up” and “bare/sparse vegetation.” Those broad classes do not distinguish industrial from residential built-up areas, nor coal mines from other bare surfaces. WorldCover is a satellite-derived 2021 product, so using it to label 2026 chips creates a temporal mismatch and a non-independent reference if evaluated against imagery from the same sensor family. It is suitable only as a weak pre-labeling layer after local acquisition and manual review against an independent, finer-resolution reference. [ESA WorldCover Product User Manual](https://worldcover2021.esa.int/data/docs/WorldCover_PUM_V2.0.pdf).

The Ministry of Coal describes coalfield, lease, and block boundary layers in its Coal Map/CSMSM interface. Those polygons could support a separate “inside mapped lease area” context target after access, export format, date vintage, and coverage are verified. A lease boundary is not an image-level label of visible mine surface or active operation. [Ministry of Coal Coal Map information](https://coal.gov.in/sites/default/files/2024-08/08-08-2024b-wn.pdf). The Jharkhand government’s GIS portals are additional possible sources, but no locally downloaded, validated industrial/land-use reference layer was found in this audit. [Jharkhand State GIS](https://gis.jharkhand.gov.in/).

## Inventory method and output

`src/prepare_cv_dataset.py` scans local `data/processed/` for existing Sentinel-2 four-band chip rasters, hashes file contents, collapses duplicate copies, pairs available SCL masks, reads raster dimensions/bands/types/CRS/date/scene metadata, locates chip centers against the configured Jharkhand region tiles, and writes an auditable CSV. It does not copy or alter imagery, call a network service, infer labels, or overwrite an existing manifest.

```powershell
venv\Scripts\python.exe src\prepare_cv_dataset.py `
  --region jharkhand `
  --output data/processed/cv_dataset/manifest.csv
```

The default input is `data/processed/`; `--input-root` may be repeated to scan other local imagery folders. To regenerate after the manifest already exists, provide a new output path; the script refuses to overwrite it.

### Verified local inventory

| Measure | Observed |
| --- | ---: |
| TIFF files across processed satellite runs | 49 |
| Four-band chip files before content deduplication | 35 |
| Unique four-band chip contents in manifest | 20 |
| Distinct Sentinel-2 scene item IDs | 11 |
| Distinct chip-center locations | 14 |
| Configured Jharkhand tile IDs represented | 6 |
| Chips with valid four-band raster pixels | 20 / 20 |
| SCL masks paired to unique chip content | 14 / 20 |
| Paired chips with any clear SCL pixel (classes 4, 5 or 6) | 8 / 14 |
| Paired chips with at least 50% clear valid SCL pixels | 3 / 14 |
| Paired chips with at least 95% clear valid SCL pixels | 2 / 14 |
| Credibly labelled image chips | 0 |

All 20 unique chips are 64×64 `uint16`, four-band GeoTIFFs with B04 red, B03 green, B02 blue at 10 m and B11 SWIR native 20 m resampled onto the 10 m chip grid. The chips span 2026-04-24 through 2026-09-08. The 14-mask count includes files paired to unique chip content; duplicate copies across repeated runs are retained in `duplicate_chip_paths_json` but not counted as independent data. Clear-pixel summaries are descriptive; no quality cutoff was used to label or remove samples. Scene cloud cover is not a substitute for chip-level SCL.

This dataset is geographically sparse and concentrated: six 1° region tiles, with nine of the 20 content-unique chips in `jharkhand_r01_c02` and seven in `jharkhand_r01_c03`. These chips were targeted investigations of FIRMS-selected cells, not a probability sample of Jharkhand land cover. The Dhanbad pilot chips and later state samples share locations/scenes; their copies are deduplicated by SHA-256.

## Assessment of possible CV targets

| Proposed target | Local evidence | Decision |
| --- | --- | --- |
| Industrial/mining land-cover classification | The OSM/GEM data describe mapped facilities/assets, not image labels. No independent site-boundary or land-cover label layer is present locally. WorldCover has only broad land-cover classes and is five years older than the chips. | Not currently trainable as an industrial/mining image classifier. Broad surface-context classification is the most feasible future image task, subject to reference acquisition and manual validation. |
| Industrial-site versus non-industrial context | No independently surveyed positive/negative site footprints or adjudicated chip labels. OSM tags may be incomplete, and using them as both matching context and truth would be circular. Lease polygons, if acquired, represent legal/administrative area rather than visible operating surfaces. | Unsupported with current data. Do not use OSM/GEM proximity or candidate-ranking categories as labels. |
| Thermal-event-associated image classification | Sentinel-2 is optical, not thermal; brief FIRMS detections are not confirmed events. State features contain 178 rows with some chip available for context, 8 rows with a temporally eligible scene, and 1 row with usable clear causal spectral values. The Dhanbad pilot feature run had 530 rows with chip context, 11 temporally eligible scenes, and 2 clear usable spectra. Existing event review yielded zero genuinely linkable detection labels. | Unsupported. No verified positives, defensible negatives, or adequate matched image coverage exist. FIRMS detections remain observations, not event labels. |

### Label counts and evaluation feasibility

Every manifest row has `label_status=unlabelled`, blank `label_class` and `label_source`, `independent_label_verified=false`, and `is_training_sample=false`. Credible labels per candidate class are therefore **zero**; class imbalance is undefined. No training, validation, or test assignment is made. A geographic split is not meaningful without labeled examples and would invite false confidence from the small, selected sample.

The manifest records both `spatial_group_id` (configured tile) and `scene_item_id`. `geo_scene_leakage_group` joins chips that share either a tile or a scene, so future splitting can keep connected geographic/scene groups together. If the dataset grows, define holdouts by non-adjacent geographic groups and later acquisition periods, with the final test labels independently adjudicated. Exact copies are removed before any split.

## Dataset and label requirements before training

For the recommended broad surface-context task, next obtain a small Jharkhand crop of a documented land-cover reference layer, preserve its licence/version/checksum, and independently review uncertain pixels/chips. ESA WorldCover can provide broad provisional classes but cannot establish industrial or mining identity. A future industrial/mining task needs independently mapped facility footprints or authoritative mine lease/surface maps with a date vintage, plus manual image-level review; a fire-source task additionally needs detection-level incident labels with precise date/location and negative sampling protocol.

Expand Sentinel-2 sampling only after proving label availability and chip yield. Select balanced samples across state tiles and reference classes rather than FIRMS ranking categories; avoid relying on post-detection scenes for event claims. Record scene time, cloud/SCL coverage, all band resolutions, reprojection/resampling, label-source time and uncertainty. Keep ambiguous labels unknown. For evaluation, freeze a geographically separated test region and later-time holdout before model selection; ensure no shared scene or spatial group crosses splits. If these label conditions are not met, finish ThermoScope as evidence-based geospatial prioritization and do not report supervised CV metrics.

## Existing label/reference limitations

- No image-level labels, pixel masks for industrial surfaces, or verified detection-to-event links are present locally.
- Existing SCL masks label cloud/shadow/land/water classes for atmospheric screening, not industrial activity or thermal source. They are not target labels for this project.
- OSM is useful spatial context but is neither complete nor independently verified for the image task. OSM proximity cannot be used as a class label.
- GEM files are Dhanbad pilot facility references; they do not cover all industrial classes across Jharkhand and do not describe event history.
- FIRMS points/ranking rules are selection or thermal-observation evidence, never ground truth.
- Existing six state chips were selected from candidate cells; they cannot estimate statewide class prevalence or model performance.

## Reproducibility and validation

The generated manifest is `data/processed/cv_dataset/manifest.csv`. It includes chip and SCL checksums, image dimensions and data types, CRS, band order/resolution, scene identifiers and dates, WGS84 chip-center coordinates, configured tile, cloud/SCL clear-pixel fractions, duplicate paths, geographic/scene leakage group, and explicitly unlabelled status. Generated processed data remain ignored by Git.

Tests in `tests/test_prepare_cv_dataset.py` cover file-content deduplication, SCL pairing and clear-pixel calculation, unknown-label preservation, connected geographic/scene leakage groups, and refusal to overwrite a manifest. No imagery was downloaded, no notebook or historical result was changed, and no model was trained.
