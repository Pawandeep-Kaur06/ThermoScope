# Industrial Smoke Plume Detection dataset: ThermoScope assessment

**Assessment date:** 2026-11-16  
**Decision:** **Conditional go** for a separately named Sentinel-2 *visible smoke-plume* classifier; **no-go** as an industrial-fire or persistent-thermal-source classifier. The dataset contains actual georeferenced Sentinel-2 multispectral scenes and manually assigned smoke-presence labels, so it is materially suitable for the adjacent smoke task. It does not establish that a plume is caused by a fire, and its labels cannot be renamed as fire or thermal-source labels.

## Dataset characteristics

The Zenodo record describes 21,350 GeoTIFF scenes with 13 bands and georeferencing, each 120 × 120 pixels covering 1.2 km square. They are Sentinel-2 imagery, not aircraft, drone, or ground photographs. The spectral bands are from Sentinel-2 Level-2A except band 10, which is taken from Level-1C; the paper says the published model uses the 12 Level-2A channels, not band 10. The chips were collected during 2019 for 624 European industrial locations selected from E-PRTR reporting sites. The scenes show mainly industrial sites, with repeated observations at sites across the year.

The source reports 3,750 positive images containing a visible smoke plume and 17,600 negatives with no visible plume. Thus the positive share is about 17.6%. There are manually drawn segmentation annotations for 1,437 images. This supports image-level binary classification and, for the annotated subset, a smoke-pixel segmentation experiment. It does not supply a fire-event class, source-cause class, or persistent-thermal-source class.

## Label quality and interpretation

The paper defines a smoke plume visually as an opaque or semi-transparent cloud originating at the surface, without establishing its chemical composition or production process; the authors consider it likely anthropogenic. Sites were selected from an industrial emissions register, but **industrial location does not make each visible plume a verified industrial-fire event**. The negative means “no smoke plume visible in this image,” not “the facility did not emit,” “no fire occurred,” or “no thermal source exists.”

Annotations were made manually from RGB views. The authors explicitly describe the process as subjective and note confusion from surface features, weather and illumination, partial cloud cover, semi-transparent smoke, and human annotation error. Segmentation edges also need conversion: the dataset README says polygon coordinates must be scaled by 1.2 to fit the rasters. For a ThermoScope reproduction, labels/masks and scene identifiers should be checked against the actual GeoTIFFs on a small sample before using them; the 1,437 masks are not a clean independent reference standard.

## Licence and use

The Zenodo record metadata identifies the **dataset as CC BY 4.0**. The record requests citation of the associated 2020 workshop paper. The separate GitHub training-code repository is **GPL-3.0**; that code licence does not replace or change the dataset licence. The imagery is modified Copernicus Sentinel data acquired in 2019 and processed by ESA. Preserve the dataset citation, CC BY attribution, and Copernicus acknowledgement in any derived manifests or redistributed outputs. This assessment reads only public metadata, paper, and small README; it does not download the image archive.

Sources: [Zenodo dataset record and README](https://zenodo.org/records/4250706), [dataset metadata API (licence and exact file sizes)](https://zenodo.org/api/records/4250706), [Mommert et al. paper](https://arxiv.org/abs/2011.11344), and [associated code repository](https://github.com/HSG-AIML/IndustrialSmokePlumeDetection).

## Split integrity and leakage

The paper reports 624 locations and says all image observations belonging to a location were assigned to one train/validation/test subset. That is an appropriate geographic grouping rule and reduces leakage from repeated scenes of the same site across those subsets. The code repository likewise expects separate train, validation and evaluation data and says the published version groups all observations from one location together.

The evidence inspected does **not** establish a temporally independent test: observations are from 2019, with locations represented by multiple dates, and the split is described by location rather than by year. Scene dates can therefore occur in each geographic partition. This supports a location-held-out test of transfer within that 2019 collection, not prospective performance in Jharkhand or in later years. Before training, inspect the archive's actual filenames/manifests and reproduce the published location assignments; keep any Jharkhand review data entirely outside training and model selection.

## Compatibility with ThermoScope

The dataset's georeferenced 13-band Sentinel-2 GeoTIFFs are compatible in *data type and sensor family* with the application's GeoTIFF upload path. They are not compatible with the app's current four-band Jharkhand chips or with arbitrary PNG/JPEG uploads as-is. ThermoScope's local chips contain four bands (B04/B03/B02/B11); the published smoke model uses 12 channels. A model adapter would need to validate Sentinel-2 band identities/order, scaling, resampling, nodata and shape, and reject inputs that do not meet its training contract. RGB photographs and three-band images must not receive this model's output.

If integrated, the output should be named **“visible smoke-plume evidence”** and shown separately from FIRMS/OSM/recurrence context. A positive result would mean visual similarity to a smoke plume in a satellite image, not “industrial fire,” “confirmed emission,” or thermal anomaly. The image may still contain a plume from a non-fire process. It cannot answer whether a heat source is persistent.

## Model approach and resource estimate

For this dataset's task, the most defensible quick baseline is the authors' modified 12-channel ResNet-50 image classifier, compared with a simple spectral-feature or logistic/gradient-boosting baseline. Use the provided location-grouped split, class-aware metrics, calibration on validation only, and report the held-out result as performance on European sites from the 2019 sample. The U-Net is a later, separate experiment for the 1,437 manually polygon-labelled images; convert and visually spot-check polygon masks first. Do not assume the paper's reported metrics transfer to ThermoScope or reproduce them without running the exact split and protocol.

The image archive is exactly **6,359,411,128 bytes (6.36 GB decimal, about 5.92 GiB)**; annotations add 340,588 bytes and the README 2,807 bytes. Keeping the compressed archive plus extracted rasters requires more than 6.36 GB. Based on 21,350 × 120 × 120 × 12 used bands, raw arrays alone would be about 7.99 GB at 16-bit or 15.97 GB at 32-bit, before GeoTIFF metadata, temporary files, checkpoints and caches. These are storage estimates, not measured extracted sizes; actual compression and dtype must be checked after a small authorized sample. Budget at least roughly 15–25 GB free for a controlled extraction/training trial, with more headroom for retained archive and training artifacts.

The paper trains ResNet-50 from scratch, so no pretrained weights are required for a faithful reproduction. A modern pretrained Sentinel-2 encoder could reduce training needs, but it would add a separate weight download and preprocessing compatibility check; it is not needed to establish this dataset's basic feasibility. CPU/GPU duration cannot be credibly estimated without the target machine, framework version and a pilot benchmark. Training on 10-band/12-band inputs will need more memory than ordinary RGB; use a small-batch GPU pilot, or expect slower CPU training.

## Risks and limitations

- Task mismatch: visible smoke presence is adjacent to, but not a proxy label for, fire or thermal-source classification.
- Domain shift: all 624 sites are European E-PRTR locations, while ThermoScope is intended for Jharkhand. Buildings, fuels, weather, seasonal haze, industrial processes and acquisition conditions can differ.
- Temporal limitation: the dataset imagery is from 2019 and does not establish performance on 2026 scenes or later operational imagery.
- Annotation subjectivity and false labels: RGB-based human review can confuse smoke with clouds/surface features and miss transparent plumes.
- Negative-class semantics: absence of visible smoke in one overpass is not an absence-of-emission or no-fire ground truth.
- Band-contract mismatch: model input must use the expected 12 Sentinel-2 channels; the local four-band chips and ordinary RGB uploads are insufficient.
- Segmentation mask conversion: polygon scale factor and raster alignment must be validated.
- Storage and compute: dataset extraction and repeated preprocessing require substantially more disk than the compressed archive.

## Recommendation

**Go** only if ThermoScope explicitly treats this as a separate, experimental **Sentinel-2 visible smoke-plume cue**, keeps it distinct from fire and thermal-source assessment, and accepts the 6.36 GB archive/storage cost. The imagery, labels and original location-grouped evaluation make it a genuine satellite CV dataset for that narrow target.

**No-go** for presenting it as an industrial-fire or persistent-thermal-source model. For fire-related use, an output can at most be one visual cue among other evidence, and the current app must preserve “fire classifier unavailable.” If the smoke cue is accepted later, the next step is a small archive sample to verify the actual band order, dates, metadata, location/split identifiers and segmentation geometry; then reproduce a baseline on the published grouped split before integrating it. This task did not download imagery, train a model, or modify application behavior.
