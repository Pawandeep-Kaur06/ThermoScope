# Jharkhand Sentinel-2 land-cover dataset plan

## Feasibility decision

**WorldCover can provide a technically usable, broad pixel-level reference layer, but it cannot by itself produce a temporally sound, independently evaluated 2026 training/test dataset. Do not label the current chips or train yet.** The recommended CV task is semantic segmentation of broad land-cover context (not industrial sites, mines, or fires), using WorldCover 2021 only as a provisional/weak training reference and an independent, contemporary human-reviewed test set.

The existing local inventory (`data/processed/cv_dataset/manifest.csv`) has 20 content-unique 64×64 Sentinel-2 chips from 11 scenes and 14 chip locations, across six Jharkhand tiles. It contains no labels. Only 14 chips have paired SCL masks; eight have any clear SCL pixels, three are at least 50% clear, and two are at least 95% clear. These targeted FIRMS-context samples are not a representative land-cover sample. There are only five connected spatial/scene leakage groups, insufficient for geographic train/validation/test partitions.

The date mismatch is substantial: the existing chips are dated 2026-04-24 through 2026-09-08, while WorldCover v200 represents 2021. Its documentation says the product was created from Sentinel-1 and Sentinel-2 observations for the reference year. Over five years, mine faces, spoil piles, urban growth, cropland, vegetation, water, and reclamation may change. Temporal agreement cannot be presumed from spatial alignment. WorldCover also has known class confusion/artefacts and global/continental validation results do not imply Jharkhand accuracy. Its reported 82.1±1.0% Asia overall accuracy is regional aggregate validation, not local class accuracy. [ESA WorldCover 2021 Product User Manual](https://worldcover2021.esa.int/data/docs/WorldCover_PUM_V2.0.pdf).

## What WorldCover can and cannot label

WorldCover v200 provides 11 categorical classes at 10 m nominal resolution. Its map is EPSG:4326 with grid spacing 1/12,000 degree, internally compressed COGs, and 3×3° tiles. Relevant original code meanings include:

| Proposed target class | WorldCover code(s) | Use and caveat |
| --- | --- | --- |
| Built-up | 50 | Buildings, roads, rail, and other man-made structures; explicitly mixes residential and industrial built-up. Cannot label industrial sites. |
| Bare/sparse | 60 | Exposed soil/sand/rock with low vegetation. WorldCover explicitly assigns extraction sites and waste dumps to this class, but natural exposed ground is also included; it is not a mining label. |
| Vegetation | 10, 20, 30 | Tree cover, shrubland, and grassland grouped for a broad context target. Preserve original codes in the raster/metadata so subclasses remain recoverable. |
| Cropland | 40 | Keep separate from natural vegetation where sample support allows; this class is seasonally variable. |
| Permanent water | 80 | Water present most of the year; seasonal water and wetlands are not equivalent. |

Codes 0/no-data, 70/snow and ice, 90/wetland, 95/mangrove, and 100/moss/lichen should remain `ignore/other` for this small Jharkhand taxonomy unless a separate class definition and adequate reference samples are justified. Do not remap all unselected values to a negative class. In particular, no WorldCover class means “industrial”, “mine”, “fire”, or “thermal source”.

## Alignment and label validity

Alignment is technically straightforward but does not cure the five-year date gap. Each chip is a four-band 64×64 `uint16` raster: B04/B03/B02 at 10 m and B11 at native 20 m resampled onto the 10 m grid. WorldCover is categorical. The reproducible alignment operation should:

1. Use the exact chip CRS, affine transform, dimensions, and pixel grid as the destination.
2. Read only the WorldCover source window intersecting the chip, then reproject categorical codes with **nearest-neighbor** (never bilinear/cubic interpolation).
3. Write a per-pixel label mask at the chip grid. Preserve original WorldCover codes and a separately versioned target-class mapping. Set no-data/unmapped values, excluded classes, and any human-identified changed/uncertain pixels to an explicit ignore code.
4. Keep the mask separate from SCL. The 2026 SCL mask controls cloud/shadow/invalid input pixels; it does not label land cover.
5. Record reference year/version, input/output hashes, transformation parameters, valid-pixel fraction, class proportions, and image-to-reference time difference for every chip.
6. Do not assign the dominant map class to every pixel in a mixed chip. Preserve the full per-pixel mask. Exclude temporally uncertain areas from supervised loss or keep them in an explicitly weak-label subset; do not silently convert them into hard truth.

The 2021 labels are especially risky for mine and urban-change contexts. For a valid evaluation, independently review contemporary high-resolution imagery or official, date-stamped land-use reference at the chip date. WorldCover must not be used as both training target and supposedly independent test truth. If current independent verification cannot be obtained, results must be described as agreement with a 2021 reference map, not accuracy against 2026 land cover.

## Reproducible sampling and labeling procedure

### Sampling frame

- Freeze the Jharkhand boundary/configuration, imagery period, target classes, chip size (retain 640 m / 64×64 for initial compatibility), cloud criteria, label version, and split plan in a versioned JSON before retrieval.
- Build the frame from the state polygon and reference-map class pixels, stratified by the five target classes and distributed across districts/5 km spatial blocks. Sample from the reference frame rather than FIRMS candidate ranking or OSM proximity. FIRMS may be retained as a separate analysis linkage field only; it must not determine the image label.
- Select scenes with low scene and local SCL cloud/shadow and valid coverage; set a documented screening rule such as at least 80% valid, clear input pixels. Store excluded chips and exclusion reason in a selection log, not as negatives.
- Keep whole 64×64 WorldCover masks, class proportions, no-data, and uncertainty. Never label an entire image as one class solely because that class is the largest fraction.
- For an image-level classifier rather than segmentation, use a predeclared purity threshold and label only the *chip-level target* when it is met; retain all pixel masks and proportions, and place mixed chips into an unlabeled/ambiguous pool. Do not propagate one chip label to every pixel.

### Human review and independent test truth

- Review a stratified subset, with priority to change-prone bare/extraction and built-up areas, against contemporaneous high-resolution reference imagery or government survey/vector data. Record reviewer, source, source date, spatial resolution, polygon/pixel interpretation, confidence, disagreement, and final adjudication.
- Use two independent reviewers for the test subset; resolve disagreements by a third review or mark pixels unknown. Do not use OSM tags, GEM facility points, FIRMS, or ranking categories as the image class.
- The Ministry of Coal states that its Coal Map/CSMSM contains coalfield, lease, and block boundaries and also satellite imagery/complaint layers. Access/export format and date vintage still require verification, and lease boundaries describe administrative extents rather than visible land cover. They can guide independent review, not directly label all pixels. [Ministry of Coal Coal Map information](https://coal.gov.in/sites/default/files/2024-08/08-08-2024b-wn.pdf).

### Geographic and temporal split

Split spatial/scene groups before any augmentation or model fitting. Use whole district groups where class coverage permits; otherwise use nonadjacent ≥5 km spatial blocks with a ≥1 km exclusion buffer around held-out blocks. Keep all chips from one Sentinel scene and all overlapping/nearby chips within one split. Do not allow same-scene or near-duplicate chips to cross partitions. Target 60% training, 20% validation, and 20% test by group, with the test set in at least three districts absent from train/validation and later acquisition dates where available. Preserve natural class prevalence in the test set; use class weights or balanced sampling only in training. If these group/class constraints cannot be satisfied, report that independent evaluation is unavailable rather than falling back to random chip splits.

## Minimum sample and storage estimate

### Recommended smallest defensible benchmark

For a modest transfer-learning semantic-segmentation baseline, target **at least 1,250 retained chips** (approximately 250 chip appearances per target class across five classes), with geographically grouped 60/20/20 partitions. This gives a nominal 150/50/50 train/validation/test appearances per class if the strata and geographic groups permit. Require at least 50 distinct spatial test blocks per class spanning three or more held-out districts; otherwise lower-confidence classes remain exploratory. Class appearances may overlap because masks are pixel-level; report valid labeled pixels and independent spatial groups per class, not only chip counts. This is a minimum feasibility target, not a guarantee of adequate statistical power. A stronger study would need more independent regions and external test labels.

The current 20 chips do not count toward those targets as verified labels; they can be retained as unlabeled context or weak-label candidates after individual temporal review. Approximately 1,230 additional chips would be needed to reach the 1,250-chip target, and substantially more may be needed for rare permanent-water or class-balanced spatial test groups.

| Data item | Approximate size |
| --- | ---: |
| Existing 20 unique compressed chips | 533,307 bytes (~0.51 MiB) |
| 1,250 four-band chips uncompressed (`64×64×4×uint16`) | 40,960,000 bytes (~39.1 MiB) |
| 1,250 one-byte pixel label masks uncompressed | 5,120,000 bytes (~4.9 MiB) |
| 1,250 one-byte SCL masks uncompressed | 5,120,000 bytes (~4.9 MiB) |
| Six complete WorldCover Map COGs intersecting the state polygon | **701,510,870 bytes (~669 MiB)** by HTTP `Content-Length` HEAD requests on 2026-11-16; no raster payload downloaded |
| Global WorldCover 2021 Map dataset | ~117 GB per ESA manual |

The six relevant tile objects are `N21E081`, `N21E084`, `N21E087`, `N24E081`, `N24E084`, and `N24E087`; all intersect the configured Jharkhand polygon. Their observed full-object lengths were 124,090,449; 127,991,194; 81,771,213; 126,723,055; 123,474,050; and 117,460,909 bytes, respectively. The objects are public on ESA's AWS S3 bucket. The manual also offers authenticated Terrascope downloads; no credential is needed for the public S3 objects. WorldCover is licensed CC BY 4.0 and requires attribution. [ESA data access, license, and tile format](https://worldcover2021.esa.int/data/docs/WorldCover_PUM_V2.0.pdf).

The lowest-storage approach is remote COG window reads for selected chips, caching only cropped label masks and input checksums. COGs are 3×3° tiles with internal 1024-pixel blocks; a 64×64 label window can trigger a full compressed block range read. Therefore, a 20-chip pilot should first measure actual bytes transferred and cache size; a naive raw-block upper estimate is about 1 MiB per intersected source block, and windows may cross block boundaries. For the statewide 1,250-chip sample, range requests may or may not beat downloading the six ~669 MiB tiles, depending on spatial spread and cache overlap. Do not start retrieval until the exact sample frame and measured pilot transfer are reviewed. The chip/mask outputs themselves should remain tens of MiB at the current chip size; retain the original source uint16 imagery and generate normalization on the fly rather than storing duplicate float rasters.

## Reproducible implementation sequence

1. Freeze a versioned sampling config and choose final target taxonomy; confirm districts/blocks and image dates.
2. Inspect public COG metadata and issue a small byte-counted range-read pilot for the existing chip windows. Save source URLs, tile IDs, retrieval timestamp, ETag/Last-Modified, byte count, SHA-256 of cropped masks, and software versions. Do not download whole tiles automatically.
3. Build label masks by exact-grid nearest-neighbor reprojection; run alignment checks (CRS, transform, dimensions, class codes, nodata, SCL mask, per-chip class proportions) and temporal review flags.
4. Expand image collection only around selected, reference-stratified spatial blocks; log missing/cloudy/unavailable samples explicitly.
5. Independently adjudicate a geographically separated contemporary test subset; retain unresolved masks as ignore/unknown.
6. Generate a new, timestamped dataset manifest and grouped split table without overwriting `data/processed/cv_dataset/manifest.csv`. Validate hash uniqueness, no scene/spatial overlap across splits, class counts, temporal gaps, and per-chip label quality before any model training.

No WorldCover data were downloaded for this plan. The six-tile estimate is based on public-object response headers only. The next practical step is a small, user-approved COG-window pilot plus a dated independent-label review—not model training.

## Follow-up update (2026-11-16)

A later, licensed WorldCover 2021 v200 pilot retrieved six chip-footprint source-grid windows by HTTP range requests; it did not download any complete COG tiles or create Sentinel-2 label masks. See `docs/cv_reference_dataset_decision.md` for the actual byte count, checksum/provenance paths and updated training decision. The original statement above records the state of this plan when it was written.
