# ThermoScope land-cover CV prototype: feasibility result

## Decision

**The six-chip sample is insufficient for a leakage-safe segmentation prototype. No model was trained, no weights/configuration were created, and no loss, IoU, Dice or confusion matrix is reported.** The available clear weak-reference pixels are concentrated in one geographic/scene group; the only second group contributes two pixels. A test split built from those two pixels would not be meaningful, and pixel-random splitting would leak spatially adjacent information.

This assessment concerns broad land-cover segmentation against **ESA WorldCover 2021 weak reference masks** only. It does not assess fire, industrial-site or mine classification and does not establish 2026 land-cover truth.

## Inputs and preparation

Inputs were the six existing Jharkhand Sentinel-2 64×64 four-band chips and their SCL rasters, the six native-grid WorldCover 2021 v200 windows, and the existing geographic/scene leakage groups. The categorical WorldCover windows were reprojected with nearest-neighbor resampling to each chip's exact CRS, affine transform and 64×64 grid. WorldCover codes were grouped into vegetation (10/20/30), cropland (40), built-up (50), bare/sparse (60), and water (80). Other codes and no-data became ignore value 255.

Only pixels with valid four-band image data and SCL clear classes 4, 5 or 6 were retained. Clouds, shadows, invalid pixels, WorldCover no-data and unsupported classes were ignored. This is a **weak-mask preparation output**; the six review-register records remain unlabelled and pending human review.

Reproduce the preparation into a new, non-existing output directory (the script refuses overwrite):

```powershell
venv\Scripts\python.exe src\prepare_weak_labeled_chips.py `
  --register data\processed\cv_dataset\reference_review_register.csv `
  --sample-manifest data\raw\cv_reference\worldcover_2021_sample_validated\sample_manifest.csv `
  --output-dir data\processed\cv_dataset\worldcover_weak_alignment_v002
```

The actual feasibility masks and counts from this run are under `data/processed/cv_dataset/worldcover_weak_alignment_v001/`: `masks/`, `weak_sample_manifest.csv`, and `readiness.json`. Each mask is 64×64 in the associated Sentinel chip's grid and records the weak reference origin and date gap in its metadata/manifest.

## Observed sample support

All six chips have 4,096 valid image pixels. After SCL screening, the per-chip counts were:

| Sample | Tile | Scene/leakage group | SCL-clear pixels | Usable weak-label pixels |
|---|---|---|---:|---:|
| `s2_264a66bdf7310db9` | `jharkhand_r03_c04` | `geo_scene_2b0ee1a7698dbceb` | 0 | 0 |
| `s2_3f3175261af193fc` | `jharkhand_r01_c03` | `geo_scene_89a1e1cf79e4adee` | 0 | 0 |
| `s2_6354de74e49607b0` | `jharkhand_r02_c00` | `geo_scene_c17f511edb7b54d8` | 4,036 | 4,036 |
| `s2_b4bee1599e877df9` | `jharkhand_r00_c02` | `geo_scene_ddd2de5fa975b8e4` | 0 | 0 |
| `s2_c99217257d8e20e5` | `jharkhand_r01_c02` | `geo_scene_89a1e1cf79e4adee` | 0 | 0 |
| `s2_e8545fc37bd10b5c` | `jharkhand_r01_c01` | `geo_scene_1ca59a90cd11689b` | 2 | 2 |
| **Total** | **6 tiles** | **5 connected groups** | **4,038** | **4,038** |

Usable weak-label class counts across these pixels were:

| Target class | Pixels | Interpretation |
|---|---:|---|
| Vegetation | 3,160 | WorldCover codes 10/20/30 grouped |
| Cropland | 813 | WorldCover code 40 |
| Built-up | 49 | WorldCover code 50; residential and industrial are mixed |
| Bare/sparse | 16 | WorldCover code 60; not a mine label |
| Water | 0 | No SCL-clear WorldCover water pixels in this sample |

Only **two of five** leakage groups have any retained pixels. One group contributes 4,036 pixels; the other contributes two. Only one group reaches the prototype's simple 256-pixel nontrivial-group screen. That screen is a feasibility check, not a statistical sufficiency threshold. Class support for built-up and bare/sparse is only 49 and 16 pixels respectively, all in the large group. There is no independent group on which to evaluate any class, and no meaningful train/validation/test split can be made.

## Evaluation status

| Requested result | Status |
|---|---|
| Training and validation loss | Not run: no eligible leakage-safe split |
| Per-class IoU / Dice | Not calculated |
| Confusion matrix | Not calculated |
| Baseline comparison | Not run |
| Model weights / training history | Not created |
| Independent test labels | None available |

These are intentionally marked **not run**, not zero. A future model trained to WorldCover masks can report agreement with those weak labels, but must not present it as independent ground-truth accuracy. WorldCover represents 2021 while these Sentinel chips were acquired in 2026; surfaces may have changed, and the map itself uses Sentinel-1/2 inputs.

## Validation and tests

`src/prepare_weak_labeled_chips.py` validates inputs, reprojects categorical pixels by nearest neighbor, applies SCL and image-valid masks, records source provenance and hashes, and keeps splits unassigned. It rejects mismatched array grids and refuses to overwrite an output directory. Synthetic tests cover exact-grid alignment, cloud/shadow/invalid-pixel masking, shape checks and leakage-group separation, including the case where two pixels in a second group do not make a meaningful holdout.

The test suite passed after implementation; see `WORKLOG.md` for exact command and total. Existing pilot outputs, notebooks and source imagery were preserved. No large data were downloaded.

## Next step

Do not train on this six-chip set. First expand clear Sentinel sampling across independent geographic/scene groups, selected independently of FIRMS candidate ranking, with WorldCover retained only as weak training/reference data. Establish a geographically held-out, human-reviewed contemporary test subset before model development. If that cannot be assembled, keep the project as geospatial evidence prioritization and describe this land-cover run as a failed CV feasibility gate.
