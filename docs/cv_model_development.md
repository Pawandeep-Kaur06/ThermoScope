# ThermoScope CV model development: evidence gate

**Decision: no industrial-fire or persistent-thermal-source image classifier can be trained or evaluated defensibly from the current Jharkhand data.** The application should keep its model state as unavailable and return `insufficient_evidence_to_classify`. This is a data/target blocker, not a lack of a sufficiently large neural network.

The closest credible public dataset found is for **visible industrial smoke-plume presence**, which is a different image target from an industrial fire or thermal source. It is potentially useful only if the project explicitly adds a separate smoke-evidence output. It must not be relabelled as fire.

## Local inventory and provenance

The reproducible per-file raster inventory is [cv_model_dataset_inventory.csv](cv_model_dataset_inventory.csv). Rebuild it without changing source rasters with:

```powershell
venv\Scripts\python.exe src\inventory_cv_model_data.py `
  --output docs\cv_model_dataset_inventory_rebuilt.csv
```

The inventory script refuses to overwrite an existing file and records relative path, byte size, SHA-256, dimensions, bands, data types, CRS, grid bounds, scene/date metadata where available, and the distinction between imagery, SCL quality masks, and weak WorldCover masks.

| Local resource | Verified contents | Label/evaluation value for fire model |
|---|---|---|
| Processed Sentinel TIFFs | 35 four-band file copies, **20 unique chip contents**, 64×64 `uint16`, B04/B03/B02/B11, 10 m grid; 11 unique scene IDs, 14 centers, 6 Jharkhand tiles; 2026-04-24 through 2026-09-08 | All 20 chips are explicitly unlabelled. None has an independently verified fire/source label. |
| Paired Sentinel SCL | 14 files; only 8 have any clear pixels, 3 are at least 50% clear, 2 at least 95% clear | Cloud/shadow/land-screening metadata, not a fire target. |
| ESA WorldCover source windows | 7 local TIFF files including one previously retained duplicate; 6 are listed in the validated sample manifest. Reference year 2021, 10 m nominal source grid, CC BY 4.0. | Weak broad land-cover only. It does not label fire, thermal activity, industrial emissions, or mines. |
| Aligned WorldCover masks | 6 masks and 4,038 SCL-clear usable weak pixels: vegetation 3,160; cropland 813; built-up 49; bare/sparse 16; water 0 | 4,036 usable pixels are in one leakage group and 2 in a second; one group reaches the 256-pixel feasibility screen. No useful independent split. |
| Model weights | `models/` contains only `.gitkeep`. No checkpoint or exported model is present. | Nothing to load for CV inference. |
| ML runtime | Current environment has no PyTorch, torchvision, timm, Transformers, or segmentation-model library installed. | These are not installed while the dataset/target is unresolved. |

The local image inventory is purposive and FIRMS-selected, not a representative random sample. Available FIRMS points are sensor detections, not confirmation of fire. The feature/ranking categories, OSM/GEM proximity, and recurrence cannot be used as image labels. The current app's inference adapter returns `unavailable` and its evidence aggregator keeps that separate from the map context.

## Public dataset and model review

### Closest task-matched resource: industrial smoke, not industrial fire

The [Industrial Smoke Plumes from Remote Sensing dataset](https://zenodo.org/records/4250706) (Mommert et al., [paper](https://arxiv.org/abs/2011.11344), code at [HSG-AIML/IndustrialSmokePlumeDetection](https://github.com/HSG-AIML/IndustrialSmokePlumeDetection)) contains 21,350 georeferenced Sentinel-2 patches from 2019 and 624 locations selected using the European Pollutant Release and Transfer Register. Its manually reviewed scene labels are 3,750 “smoke plume present” and 17,600 “no visible smoke plume”; 1,437 positive patches have manual plume segmentation polygons. Images are 120×120 with 13 bands (the published model uses 12 channels; band 10 is not used). The Zenodo record metadata declares **CC BY 4.0** for the data. The associated code is GPL-3.0; that code licence is separate from the imagery licence.

The image archive is **6,359,411,128 bytes (6.36 GB decimal; about 5.92 GiB)**, plus a 340,588-byte segmentation-label archive and README. It has not been downloaded. The raw array volume after extraction is not stated by the record; from the listed sample count/shape/bands it would be roughly 8.0 GB if stored as 16-bit samples or 16.0 GB if stored as 32-bit samples, before filesystem/processing overhead. Actual dtype and extracted size need verification from a small authorized sample. Do not allocate based on the compressed archive size alone.

The authors' repository supplies a modified ResNet-50 smoke classifier and a U-Net segmentation workflow, and states that all observations from one location were kept in one train/validation/test partition. It is a useful reproducibility reference for a *smoke plume* task, not an existing pretrained checkpoint: no weights are in this checkout, and the current environment has no PyTorch stack. The available 2019 imagery also does not provide a later-year temporal test for the 2026 Jharkhand application. A model trained on the European sites would need a separate local domain-validation set before deployment.

**Why this does not unblock the requested model:** the positive class is visible smoke, not fire; the negative class means no visible plume in that image, not no industrial activity or no fire. Smoke from routine combustion/process emissions may not be a fire, while an industrial fire may have no visible plume in the overpass image. Thus those labels cannot support the application's industrial-fire or persistent-thermal-source categories. They may support a separately named “visible smoke plume” visual cue if the project scope is explicitly expanded and the 6.36 GB archive is approved for retrieval.

### Other model/data options

- FIRMS MODIS/VIIRS records are thermal-anomaly/active-fire algorithm outputs whose locations represent coarse sensor footprints. They are useful for evidence matching, but using them as target image labels would be circular and would transfer pixel-centre labels to 10 m imagery without incident verification. See the [NASA FIRMS overview](https://firms.modaps.eosdis.nasa.gov/) and the [FIRMS data description](https://developers.google.com/earth-engine/datasets/catalog/FIRMS).
- Wildfire image datasets such as FLAME are primarily UAV/aerial-camera imagery and focus on vegetation fires. They do not provide Sentinel-2 industrial-facility examples or persistent industrial-source labels, so they do not fill this gap.
- Existing weak WorldCover classes cannot become industrial/fire labels. The app's small Sentinel chips are 4-band optical context, not thermal imagery. Sentinel-2 has no thermal band; its optical pixels may show smoke or post-event surface change but do not measure source temperature.
- No suitable fire/thermal-source pretrained model or weights were found in the local `models/` folder. The HSG repository is training/evaluation code for the adjacent smoke-plume task, not a downloadable pretrained fire classifier.

## Exact blocker and minimum training data

There are **zero** credible image-labelled industrial-fire examples, **zero** credible no-fire/control examples, and **zero** independently labelled Jharkhand test images. No confusion matrix, precision, recall, F1, calibration, or fire-class probability can therefore be calculated. Even if an off-the-shelf smoke/wildfire model were available, it would not distinguish industrial fire from routine industrial smoke, hot process infrastructure, vegetation fires, or other thermal anomalies in Jharkhand.

The smallest defensible dataset for the requested *visible industrial fire evidence* task must include:

1. A documented target definition separating visible flame/fire evidence from smoke, burn scars, routine stack emissions, thermal anomaly, and unknown.
2. Image-time incident records from authoritative or independently verifiable sources with event date/time, coordinates and spatial uncertainty. Facilities alone, FIRMS points, OSM/GEM, headlines without precise incident location, and candidate ranking are not positive labels.
3. Matching imagery that actually covers each event at an appropriate time. Each label must cite the event evidence and image/scene ID. For thermal-source classification, include an appropriate thermal sensor; the current Sentinel-2 chips are optical.
4. Verified controls and unresolved/ambiguous examples, reviewed with the same protocol. Lack of a FIRMS detection or incident report is not automatically a negative.
5. Enough independent sites/events to reserve geographically separate test locations and a later-time test period. Keep scenes from the same facility, event, spatial footprint and overlapping dates within one split. Freeze the test set before model choice.
6. A label register with source URL/citation, publication/event time, coordinates/precision, reviewer and rationale, plus checksummed imagery metadata and class definitions.

Until those items exist, the minimum actionable path is to retain the current app behavior and collect an auditable event-to-image reference set for the pilot. A separate smoke-plume model is feasible from the public dataset only after explicit confirmation that the task may include **smoke evidence rather than fire classification**, approval to download the 6.36 GB archive, and a local geographic evaluation sample is assembled.

## Recommended model strategy once the blocker is resolved

- For an approved smoke-cue subtask, first reproduce the published 12-channel ResNet-50 binary classifier; optionally reproduce U-Net only for the 1,437 polygon-annotated patches. Split all image dates/sites from a facility into one spatial group and report a distinct held-out Jharkhand review set as out-of-domain performance, not training-domain accuracy.
- For verified fire imagery, start with a pretrained remote-sensing encoder only after labels and input-band compatibility are defined. Fine-tune a compact image classifier (or segmentation network only when pixel masks exist), compare with a non-neural baseline, calibrate on validation data, and test once on held-out sites and later dates.
- The app should emit an image-model output such as “visible plume cue” or “fire-evidence model unavailable,” never a confirmed fire. FIRMS/OSM/recurrence remain a separate evidence panel; combined assessment must preserve uncertainty and the source of each statement.

No dataset archive, model weights, or framework packages were downloaded. No model was trained, and no historical output or notebook was modified.
