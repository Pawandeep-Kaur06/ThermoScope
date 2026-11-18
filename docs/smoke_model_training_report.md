# ThermoScope visible-smoke model: training and evaluation

**Run date:** 2026-11-17  
**Model status:** Experimental visible-smoke image classifier and segmentation overlay are integrated. They do not classify fires or thermal sources.

## Summary

ThermoScope now trains and runs a local, 12-channel Sentinel-2 visible-smoke model using the public Industrial Smoke Plumes dataset. The application presents this output separately from FIRMS, OSM, recurrence, and the still-unavailable fire classifier. The classifier returns a **validation-thresholded, uncalibrated smoke score**; the score is not a calibrated probability.

The trained models were evaluated on a location-held-out split created for this project. They were **not** evaluated on Jharkhand data. Results below measure agreement with the dataset's manually assigned smoke labels and masks, not fire-detection performance, independent ground truth, industrial cause, or generalisation to India.

## Dataset acquisition and validation

Source: [Zenodo record 4250706](https://zenodo.org/records/4250706), DOI [10.5281/zenodo.4250706](https://doi.org/10.5281/zenodo.4250706); paper: [Mommert et al. (2020)](https://arxiv.org/abs/2011.11344); reference implementation: [HSG-AIML repository](https://github.com/HSG-AIML/IndustrialSmokePlumeDetection). The dataset licence was rechecked from the Zenodo record API as **CC BY 4.0**. The separate code repository is GPL-3.0. Copernicus Sentinel data attribution is retained in the downloaded README and project documentation.

The image archive downloaded to `data/raw/industrial_smoke_zenodo_v1/images.tar.gz` was **6,359,411,128 bytes** and matched the Zenodo-published MD5 `d87992cf622920dc0135e16bac9e2cfd`. Its computed SHA-256 is `808e839b98e247fdd613b29d63796bde1af08eed7b6a630d8dc39a21fd5ba71c`. The annotation archive also passed its published size and MD5 check; the retrieval manifest records SHA-256 for each file. All downloaded files and extracted data are Git-ignored.

The verified archive was extracted to `data/processed/smoke_model_dataset_v002/`: 22,787 files totaling **8,017,134,543 bytes** (21,350 images and 1,437 annotation JSONs). The image characteristics found locally are:

- All 21,350 TIFFs have 13 `uint16` bands and a georeferenced CRS. There are nine UTM CRSs (EPSG:32628–32636); image centers span approximately 15.44°W–33.29°E and 27.81°N–66.50°N.
- 21,326 images are 120×120 pixels; 24 are 119×120. The source preprocessing edge-pads undersized chips to 120×120, which this workflow reproduces.
- 3,750 images are manually marked positive for visible smoke; 17,600 are marked negative for visible smoke. The 2019 dates span 2019-01-01 through 2019-12-31 across 624 European E-PRTR-selected sites.
- All 1,437 mask JSONs link to an image. Ten JSONs have no usable polygon and were excluded from segmentation; 1,427 contain at least one smoke polygon. Polygons are rasterized at the README's 1.2 coordinate scale.
- The TIFFs have no band descriptions. The released code selects bands 1–10 and 12–13, omitting raster band 11 (Sentinel-2 cirrus B10), to create its 12-channel input. The upload path therefore requires recognizable band descriptions or an explicit user confirmation of that published order.

The archives contain `positive/` and `negative/` folders but **do not contain the authors' exact train/validation/test assignment files**. The reported paper split keeps each location in only one partition, but its site IDs per partition could not be recovered from the release. ThermoScope therefore created a deterministic, seeded `GroupShuffleSplit` by site, approximately 70/15/15 by image count. This is a new site-held-out split, not a reproduction of the authors' exact partition. Split manifest: `data/processed/smoke_model_manifest_v001/manifest.csv`; quality summary: `dataset_quality.json`.

| Split | Sites | No visible smoke | Visible smoke | Total images |
| --- | ---: | ---: | ---: | ---: |
| Train | 436 | 12,382 | 2,621 | 15,003 |
| Validation | 94 | 2,675 | 582 | 3,257 |
| Test | 94 | 2,543 | 547 | 3,090 |

No site ID occurs in more than one split. All images are from 2019, so this does not provide a later-year temporal test. The location IDs and acquisition dates are parsed from filenames and checked against raster metadata.

## Model and training protocol

The paper's classifier is a modified ResNet-50 using 12 Sentinel-2 channels, ImageNet initialization, source-specific per-channel normalization, random 90×90 crops, and flips/rotations. The released training code expects class folders and a grouped split, but the dataset archive does not carry the paper's original split assignments. This checkout has no GPU and, during this run, only around 0.2–0.8 GiB of free RAM while a large desktop application was resident. The full ResNet-50 reproduction was therefore not run. No ImageNet weights were downloaded.

Instead, ThermoScope trained a compact 12-band CNN from scratch as a CPU-feasible baseline. It uses the source band selection and published per-band normalization values, random 90×90 crop/flip/rotation augmentation, and a balanced, seeded subset of 4,000 images from the training sites (2,000 per class). The model was trained for three epochs with AdamW; the best validation-loss checkpoint was epoch 2. The final threshold was selected on validation data to maximize positive-class F1. Scores remain explicitly uncalibrated.

| Setting | Value |
| --- | --- |
| Architecture | ThermoScope TinyCNN, 12 input channels |
| Training subset | 4,000 images from 436 training sites, class-balanced |
| Epochs / batch | 3 / 2 |
| Epoch losses (train / validation) | 0.632 / 0.638; 0.560 / 0.546; 0.531 / 0.684 |
| Selected checkpoint | Epoch 2, minimum validation loss |
| Decision threshold | 0.48, selected on validation positive-class F1 |
| Training runtime | 818 seconds, CPU |

This is a small ThermoScope model trained on a subset, not the published ResNet-50 and not a reproduction of the paper's reported 94.3% accuracy.

## Image-level test results

The following results are for the 3,090 images from 94 **held-out European sites**. They compare with subjective manual visible-smoke/no-visible-smoke labels. The simple majority-class baseline predicts no visible smoke for every test scene.

| Metric | Majority baseline | TinyCNN |
| --- | ---: | ---: |
| Accuracy | 0.823 | 0.823 |
| Positive-class precision | 0.000 | 0.500 |
| Positive-class recall | 0.000 | 0.422 |
| Positive-class F1 | 0.000 | 0.458 |
| Macro F1 | 0.451 | 0.676 |
| ROC AUC | 0.500 | 0.771 |
| Average precision | 0.177 | 0.441 |

TinyCNN confusion matrix (rows: manual label 0/1; columns: predicted 0/1): `[[2312, 231], [316, 231]]`. Its accuracy equals the majority baseline at the selected threshold, while it retrieves some positive scenes. It still misses 316 of the 547 manually positive test scenes and makes 231 positive predictions on manually negative scenes. This is a feasibility result, not a deployment-ready model.

## Segmentation experiment

The compact U-Net was trained on 512 examples from the training sites (256 polygon-labelled positives and 256 negatives), for two epochs. Validation used all 301 polygon-labelled positive images plus 301 sampled negatives. The held-out test used 115 polygon-labelled positives plus 115 sampled negatives from test sites. The threshold was selected on validation data to maximize mask IoU.

| Pixel metric | Held-out test |
| --- | ---: |
| Precision | 0.528 |
| Recall | 0.444 |
| IoU | 0.318 |
| Dice | 0.482 |

These metrics compare against human-drawn smoke polygons after the documented 1.2 scale conversion. Mask boundaries and omitted smoke are annotation limitations; polygon labels are not independent pixel truth. The test confusion matrix over 1,863,000 crop pixels is `[[1,808,319, 15,557], [21,752, 17,372]]` (true background/smoke by predicted background/smoke).

## Error review and interpretation

The error-review figure is a visual aid, not an extra source of labels. Several of the highest-scoring false positives appear visually diffuse and cloud-like or atmospherically bright, which is consistent with the paper's noted cloud confusion risk; this quick visual inspection does not independently establish that they are clouds. Some false negatives repeat at one held-out site across different dates, showing that a site-held-out split tests generalisation to unseen locations, while repeated observations within that held-out site remain correlated. They are not multiple independent failures at unrelated sites.

Figures and tables are under `outputs/smoke_model/run_001/`, `outputs/smoke_model/analysis_v001/`, and `outputs/smoke_model/segmentation_run_001/`. The provenance-enriched test table links every prediction to stable sample ID, site, date, coordinates, and source image path; false positives and false negatives are kept as review cases, not relabelled data.

## ThermoScope application integration

`src/thermoscope_app/smoke_model.py` performs the 12-band selection, source normalization, small-chip padding/cropping, classification, and optional smoke-mask inference. The local application loads `models/thermoscope_smoke_tiny_v1.pth` and `models/thermoscope_smoke_unet_v1.pth`; both weight files are Git-ignored. Uploads must be GeoTIFFs with exactly 13 Sentinel-2 bands, `uint16` training-scale reflectance, and a 90–120 pixel chip. Described band order is checked automatically; otherwise an explicit confirmation is required. Ordinary RGB/PNG/JPEG and ThermoScope's existing four-band B04/B03/B02/B11 chips are refused for smoke inference. The application displays the smoke cue, uncalibrated score, threshold and segmentation overlay separately from its FIRMS/OSM panels. Fire-class inference remains unavailable.

If weights are absent on another checkout, the UI reports smoke inference unavailable; this checkout's local weights are ignored by Git and must be transferred separately or regenerated from the dataset.

## Reproduction commands

Run from the repository root in PowerShell. The acquisition command is needed only when the checksum-verified raw archive is absent; it refuses to overwrite a destination.

```powershell
venv\Scripts\python.exe -m pip install --extra-index-url https://download.pytorch.org/whl/cpu -r requirements-smoke-model.txt
venv\Scripts\python.exe src\acquire_industrial_smoke_dataset.py --output-dir data\raw\industrial_smoke_zenodo_v1
venv\Scripts\python.exe src\extract_industrial_smoke_dataset.py --raw-dir data\raw\industrial_smoke_zenodo_v1 --output-dir data\processed\smoke_model_dataset_v003
venv\Scripts\python.exe src\prepare_smoke_dataset.py --dataset-dir data\processed\smoke_model_dataset_v003 --output-dir data\processed\smoke_model_manifest_v002
venv\Scripts\python.exe -m src.train_smoke_model --manifest data\processed\smoke_model_manifest_v002\manifest.csv --dataset-dir data\processed\smoke_model_dataset_v003 --output-dir outputs\smoke_model\run_002 --model-path models\thermoscope_smoke_tiny_v2.pth --epochs 3 --batch-size 2 --max-train-images 4000
venv\Scripts\python.exe -m src.train_smoke_segmentation --manifest data\processed\smoke_model_manifest_v002\manifest.csv --dataset-dir data\processed\smoke_model_dataset_v003 --output-dir outputs\smoke_model\segmentation_run_002 --model-path models\thermoscope_smoke_unet_v2.pth --epochs 2 --batch-size 2 --max-positive 256
venv\Scripts\python.exe -m src.summarize_smoke_model_run --manifest data\processed\smoke_model_manifest_v002\manifest.csv --dataset-dir data\processed\smoke_model_dataset_v003 --train-run-dir outputs\smoke_model\run_002 --output-dir outputs\smoke_model\analysis_v002
venv\Scripts\python.exe -m src.thermoscope_app.server
```

For this checkout, reuse the existing verified archive, extraction, manifest, model checkpoints and outputs rather than repeating acquisition/training. Launch with `venv\Scripts\python.exe -m src.thermoscope_app.server`; the app remains local-only.

## Limitations and next validation

- The model detects the dataset's visual smoke concept, not industrial-fire events, combustion cause, thermal sources, or temperature. A smoke-positive result is not a fire alert.
- All training/evaluation imagery is from 2019 European industrial sites. There is no Jharkhand smoke-labelled evaluation set; no Jharkhand/India generalisation claim is justified.
- The custom split is site-separated but not temporally separated; all data are from 2019. It does not evaluate later-year operation.
- Human annotations are subjective, based on image appearance; negative means no smoke visible in that scene only. They are not independently verified incident labels.
- Training is a short 4,000-image subset/three-epoch CNN feasibility run and a 512-image/two-epoch segmentation run. No hyperparameter search or calibration was conducted. The CNN score is not a calibrated probability.
- The official ResNet-50 baseline was not reproduced. The current weights are local and Git-ignored, so the application needs weight transfer or retraining on another clone.
- Sentinel-2 optical imagery cannot establish active fire or persistent thermal activity. FIRMS and OSM remain supporting evidence and are not merged into the model target.

The next useful research step is a properly resourced ResNet-50 comparison and, before any Jharkhand use, a geographically independent, human-reviewed local visible-smoke evaluation sample. A separate, independently labelled fire-event image dataset is still required for fire classification.
