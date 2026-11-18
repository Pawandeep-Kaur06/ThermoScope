# CV reference dataset decision for Jharkhand Sentinel-2 chips

**Decision date:** 2026-11-16  
**Task considered:** broad land-cover semantic segmentation/context, not industrial-site, mine, fire, or thermal-source classification.

## Recommendation

Use **ESA WorldCover 10 m 2021 v200** as a legally reusable **weak reference/training target only**, with class codes and provenance kept separate from any independently verified labels. Its 10 m categorical COG grid is suitable for spatial alignment to the project's 10 m Sentinel-2 chips using nearest-neighbor categorical sampling. Its license is Creative Commons Attribution 4.0 (CC BY 4.0); ESA's manual says it is free of charge and without restriction of use, while requiring acknowledgment/citation. [ESA data access and license](https://esa-worldcover.org/en/data-access), [WorldCover 2021 product manual](https://worldcover2021.esa.int/data/docs/WorldCover_PUM_V2.0.pdf), [CC BY 4.0 legal text](https://creativecommons.org/licenses/by/4.0/).

This is **not independent ground truth for the 2026 chips**. WorldCover v200 is a 2021 annual product made from Sentinel-1 and Sentinel-2 observations; the project imagery is Sentinel-2 from 2026. It is independent as a separately generated map, but shares Sentinel-2 as an input data family and has a roughly five-calendar-year temporal gap. Product-wide accuracy is not Jharkhand accuracy. Do not use WorldCover labels as the independent test set or describe model agreement with it as 2026 land-cover accuracy.

The license permits use and adaptation with attribution. Required map attribution is: **“© ESA WorldCover project 2021 / Contains modified Copernicus Sentinel data (2021) processed by ESA WorldCover consortium”**; cite Zanaga et al. (2022), *ESA WorldCover 10 m 2021 v200*, DOI `10.5281/zenodo.7254221`. Preserve this attribution in output metadata and reports.

## Other open sources considered

| Dataset | Useful classes | Spatial/time fit | Licence/access | Decision |
|---|---|---|---|---|
| ESA WorldCover 2021 v200 | Tree cover (10), shrubland (20), grassland (30), cropland (40), built-up (50), bare/sparse vegetation (60), permanent water (80), plus other global classes | Global; 10 m nominal; full-year 2021. Same broad pixel grid scale as Sentinel-2 B02/B03/B04; exact chip reprojection is required. | CC BY 4.0; public AWS COG tiles, no credentials. | **Recommended weak reference**; used for the small six-window sample below. Not final independent truth for 2026 imagery. |
| Global Human Settlement Layer (GHSL) GHS-BUILT-S E2018 / R2023A | Built-up surface fraction only; includes a non-residential component in some products | Global 2018 product at 10 m; EPSG:54009 World Mollweide. E2018 and related characterization products use Sentinel-2 composites, so they share the target sensor family and are temporally older. | European Commission JRC says CC BY 4.0 with attribution. | Good supplementary built-up fraction reference, but not a multi-class independent test source and not an industrial label. No download made. |
| JRC Global Surface Water (latest 1984–2024 family) | Water occurrence, seasonality, persistence/change | Global; 30 m Landsat-derived; 1984–2024 in the current data access page. Coarser than 10 m Sentinel-2. | Copernicus data, free without restriction of use; cite JRC source/paper. | Useful supplementary water/persistence layer if the task is modeled/assessed at 30 m or aggregated. Do not upsample to 10 m and call it pixel truth. No download made. |
| Bhuvan/NRSC SISDP Phase II 1:10K | Detailed mapped land-use/cover classes | Metadata 2018–2023, 2.5 m source imagery; exact Jharkhand AOI coverage/access/dates unresolved. | Bhuvan terms require prior written authorization for copying/derivatives; project permission not obtained. | Not immediately usable; see [Bhuvan access assessment](bhuvan_reference_data_access.md). |
| Dynamic World | Nine broad land-cover probabilities | 10 m and temporally dense, but predictions derive from Sentinel-2; not independent reference for Sentinel-2 classification. | Google Earth Engine access/terms. | Potential weak/pseudo-label comparator only; not independent evaluation truth. Not downloaded. |

WorldCover's 11 classes include the four requested surface types (built-up, vegetation subclasses, water, bare/sparse). Class definitions are coarse land-cover semantics: “built-up” includes residential **and** industrial buildings, roads and other structures; “bare/sparse” includes extraction sites and waste deposits but also natural exposed surfaces. Neither class means industrial or mine. No WorldCover class represents fire or thermal source. [Class legend and definitions](https://worldcover2021.esa.int/data/docs/WorldCover_PUM_V2.0.pdf).

WorldCover's own validation reports 76.7% overall accuracy globally and 82.1% for Asia, based on independent validation sampling; these are product-level aggregate estimates, not local Jharkhand performance. Several classes are materially weaker globally (e.g. shrubland and wetlands). [WorldCover validation report](https://worldcover2021.esa.int/data/docs/WorldCover_PVR_V2.0.pdf). Local, geographically held-out validation still needs independent references or human adjudication.

## Small sample acquired and validated

After confirming the CC BY 4.0 terms and checking full-object sizes, I retrieved only windows that intersect the six existing Jharkhand chip footprints. The WorldCover source objects are 3°×3° COGs with 10 m nominal categorical data in EPSG:4326. Three distinct source tiles covered the six chips; their whole-object sizes sum to **372,175,158 bytes (~355 MiB)**. These sizes were checked using HTTP `HEAD`; the files themselves were not downloaded in full. The full six-tile Jharkhand planning set previously measured 701,510,870 bytes (~669 MiB).

The cropped request used 13 HTTP `206 Partial Content` byte ranges totaling **1,017,485 response bytes (~0.97 MiB)**, including COG metadata/index and raster blocks. Six compressed source-grid sample GeoTIFFs total **11,766 bytes (~11.5 KiB)**. All artifacts and provenance are under `data/raw/cv_reference/worldcover_2021_sample_validated/`. The sample windows are not resampled to Sentinel-2 pixels and are not assigned to the image chips as labels.

Validation performed on the acquired sample:

- Six distinct source-grid windows correspond to the six existing chip extents; they cover three WorldCover tiles and six Jharkhand processing tiles.
- Each source crop is one-band `uint8`, EPSG:4326, on the source 1/12,000-degree grid (0.0000833333°); crop bounds contain the transformed Sentinel chip footprint, so each spatial overlap is complete at the chip-bounds level.
- All pixel codes are among WorldCover's defined map codes/no-data values. Observed codes in these six samples were 10, 20, 30, 40, 50, 60 and 80. The small frame did not sample every class and says nothing about class balance across Jharkhand.
- Across the 32,874 cropped map pixels, raw code counts were: 10 tree cover 6,525; 20 shrubland 67; 30 grassland 6,027; 40 cropland 7,032; 50 built-up 7,183; 60 bare/sparse vegetation 4,986; and 80 permanent water 1,054. These are descriptive weak-map pixels in a FIRMS-selected frame, not validated chip-label counts or statewide prevalence.
- Per-file SHA-256, source URL/tile, COG ETag, `Last-Modified`, source object size, CRS/resolution, class counts, crop size and Sentinel chip/date linkage are recorded in the sample manifest and `provenance.json`.
- No rasterization/resampling to chip grid, target label assignment, independent label validation or model training was performed. Date metadata validates only the mismatch: 2021 reference map versus 2026 chips. The approximate five-year gap is unsuitable for assuming unchanged surfaces at mines, construction areas, settlements, crops or vegetation.

Reproduce the small sample (the script refuses to overwrite an existing directory):

```powershell
venv\Scripts\python.exe src\download_worldcover_reference_sample.py `
  --register data\processed\cv_dataset\reference_review_register.csv `
  --output-dir data\raw\cv_reference\worldcover_2021_sample_validated
```

The source COGs support byte-range access from public AWS; the script reads only chip-intersecting windows. Do not replace this with whole-tile downloads without a new size check. `data/raw/` remains excluded from Git.

## Alignment and label-origin rules

For future weak masks, use the chip's exact CRS, affine transform and dimensions, reproject the categorical source by nearest neighbor, preserve WorldCover's original integer codes, and save a separate weak-label mask/provenance table. Apply a separate target taxonomy only as a versioned mapping. Keep class 0/no data, ambiguous mixed boundaries, source gaps and suspected post-2021 change as ignore/unknown. SCL cloud/shadow masks identify invalid imagery, not land-cover truth. Keep `reference_origin=worldcover_2021_weak` distinct from `independently_verified` in every manifest. Never infer mine/industry from codes 50 or 60; never infer fire from FIRMS or OSM.

## Geographic validation and minimum dataset size

The six existing chips are targeted FIRMS-context samples, not a representative state sample. The local manifest has only 20 content-unique chips, 14 locations, 11 scenes, six state tiles and five connected geography/scene leakage groups. The new sample includes no independent labels and cannot form train/validation/test partitions. The historical CV report says only 8/14 available paired SCL chips have any clear pixels, 3/14 have at least 50% clear and 2/14 at least 95%; the state run's own investigation indicates only one usable temporally eligible clear spectral observation. Cloud screening further reduces useful training imagery.

For an exploratory weakly supervised land-cover segmentation baseline, retain the prior project floor of **1,250 usable chips** (roughly 250 chip appearances per each of five broad classes), sampled across districts and spatial blocks, with group-based 60/20/20 partitions. This is a planning minimum rather than a guarantee of power. Require at least 50 independent spatial test blocks per reported class across at least three held-out districts; keep every connected scene/geography group entirely in one split. These weak labels can evaluate reproduction of WorldCover only, not true 2026 land cover.

An independent evaluation is defensible only after a separate test set is human-adjudicated against contemporary independent imagery/survey data or an independently sourced, date-appropriate reference. Use two reviewers for the held-out test subset, freeze districts/blocks before model tuning, and leave disagreements unknown. No such sample exists today. Do not use WorldCover's own map as the final test truth when it is also the training target.

## Decision on model training

**Not yet.** WorldCover is immediately usable by licence and technically aligns at 10 m for a broad land-cover task, and the six-window sample has validated source CRS, class encoding, geographic overlap and byte-range access. However, the local image sample is tiny/biased, heavily cloudy, five-way geography/scene grouping is inadequate for a leakage-safe three-way split, and WorldCover is five years older and Sentinel-derived. Training now would overfit a small sample and measure agreement with a weak 2021 map. Build a broader class-stratified, cloud-screened sample first; keep WorldCover weak labels; create a separate human-verified geographic holdout. Fire/industrial classification remains unsupported by these data.

## Local inventory artifacts

- `data/processed/cv_dataset/reference_source_inventory.csv` — source, rights, coverage, temporal and acquisition status.
- `data/raw/cv_reference/worldcover_2021_sample_validated/sample_manifest.csv` — six crop rows and checksums.
- `data/raw/cv_reference/worldcover_2021_sample_validated/provenance.json` — sources, object metadata, byte-range sample method and attribution.
- `data/raw/cv_reference/worldcover_2021_sample_validated/*.tif` — tiny native-grid categorical crops; weak references, not image labels.
