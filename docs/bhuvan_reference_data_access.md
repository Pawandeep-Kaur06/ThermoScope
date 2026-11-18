# Bhuvan SISDP Phase II reference-data access assessment

**Assessment date:** 2026-11-16  
**Project area:** Jharkhand; six existing Sentinel-2 chip footprints listed in the local reference-review register.  
**Decision:** Do not download or derive labels yet. A request-based route exists, but the exact Jharkhand Phase II coverage/dates, project-specific authorization for copying/derivative masks, and file size are not established.

## Findings

### Official request and access route

The current documented SISDP portal flow is:

1. Open the Bhuvan Panchayat Data Download portal and sign in with Bhuvan SSO credentials. The manual says users can create an account if they do not already have one.
2. Select **Land Use and Land Cover (10K): SISDP Phase II**, choose the stated purpose (the form includes “Research studies”), enter a utilization overview of at least 50 characters, and choose an administrative AOI by state/district.
3. Submit a request, retain its request ID, and check status. The manual says an email is sent when the data is ready; the documented output format is **Shapefile**.

The manual's screenshot shows a state/district AOI selector; it does not document an AOI polygon upload for this Phase II request. The 2026 Bhuvan announcement of AOI upload applies to the **1:50,000** product, not evidence that Phase II 1:10,000 supports AOI clipping. Do not assume the six small chip footprints can be requested as a six-chip clip. The SISDP request may require state/district data.

No project credentials were used, no portal request was submitted, and no files or map tiles were downloaded. The public Phase II WMS is documented for visualization and QGIS use, but this does not grant permission to extract it as an offline reference raster. An attempted lightweight WMS `GetCapabilities` metadata request from this environment did not complete (timed out); this is an environment/service reachability result, not proof that the service is unavailable.

### Coverage and dates

The official Bhuvan update says Phase II 10K data for **14 states** (mapping window 2018–2023) can be requested, but does not list the states. A Department of Space response to a Rajya Sabha question, dated 2025-08-07, confirms that Jharkhand Space Applications Centre, Jharkhand Water Resources and Irrigation departments, and Central University of Jharkhand accessed Bhuvan-hosted LULC at 1:10,000. The answer does **not** identify the SISDP Phase II version, districts, geometry coverage, or whether the data used was Phase I or II. Therefore it supports the existence/use of a Jharkhand 1:10K Bhuvan layer but does not confirm exact Jharkhand coverage of the requested Phase II export.

The Phase II metadata panel in the official manual gives fused NCC (Cartosat-1 + LISS-4), satellite data year and mapping year **2018–2023**, 2.5 m source resolution, GCS/WGS84, scale 1:10,000, polygon geometry, four classification levels (7/27/41/89 classes). The QGIS screenshot also shows an example internal layer identifier containing `2016_2019`; this does not resolve the official metadata range. No per-district or per-polygon mapping date was available in the public metadata reviewed. Ask for exact years by AOI and a versioned legend/codebook before any pixel labeling.

The six chip centers in `data/processed/cv_dataset/reference_review_register.csv` range from 83.90947–87.38909°E and 22.79740–25.03545°N and span six configured Jharkhand tiles. This is the project's sample extent, **not verified Bhuvan layer coverage**. The inventory also shows their chip dates span 2026-04-24–2026-09-03. The Phase II product is independent of the project's Sentinel-2 chip observations as described: its stated source is fused Cartosat-1 + LISS-4, not Sentinel-2. It remains a remotely sensed thematic interpretation, not field survey truth; temporal gaps to 2026 can be several years.

### Format, CRS, licensing and use

- **Format:** The SISDP manual states Phase II thematic download in Shapefile format. This is a usable vector input for a per-pixel mask after permitted local processing. It does not document GeoTIFF/classified-raster delivery for Phase II. The WMS/WMTS endpoint is documented for viewing/rendering; rendered image tiles do not preserve a reliable categorical class codebook for training masks.
- **CRS:** published metadata says geographic coordinate system, WGS84. A delivered archive still needs its `.prj`/metadata checked; no files are available to validate actual CRS, geometry validity, schema, class codes or overlap.
- **Terms:** The general [Bhuvan Terms of Service](https://bhuvan.nrsc.gov.in/bhuvan/bhuvan_terms/) grant a non-exclusive, non-transferable right to access the portal/service/content, but state that, without **prior written authorization**, users must not copy/modify/create derivatives, redistribute or publish content; the page says map/image data are provided for viewing. The research-purpose choice in the Get Data form is a purpose for requesting delivery, **not an explicit licence** permitting conversion into training masks or publication of derived sample data. The source-specific download approval/terms, permission to make cropped/rasterized masks, attribution requirements, academic publication rights, retention and redistribution limits must be obtained in writing from NRSC/ISRO or the applicable content owner. No licence has been established for this project; no derived masks should be created until it is.
- **Independence:** The named Cartosat-1 + LISS-4 reference imagery differs from the Sentinel-2 B04/B03/B02/B11 chips. This gives sensor/source independence from the current model inputs, but not independent field verification. Confirm product provenance for the actual delivered AOI.

## Size and processing estimate

No size is published for the Phase II download. The manual's documented request interface selects State/District, and the current manual does not promise a chip-level clip. The six existing chips cover only about 2.46 km² combined (each 64×64 at 10 m), but a district/state Shapefile package could be far larger. Consequently an honest download estimate in bytes is **unavailable before the data custodian responds**. Request the compressed archive and extracted size (and whether clipping is possible) before approval/download. If no AOI clip is offered, do not accept a statewide package without a size/storage review.

If a permitted vector sample is supplied for the six chip extents, expected local work is modest: validate ZIP contents and checksums; read/repair geometry only under documented rules; confirm WGS84 CRS and class fields; clip to the six chip footprints; transform/rasterize to each chip's exact grid using nearest categorical assignment or a predeclared pixel-center/coverage rule; keep mixed and uncertain pixels as ignore. Exact processing time/storage depends on returned file size and feature density. The reference masks would add roughly 24 KiB for six 64×64 one-byte masks before metadata/compression, but the source package—not the masks—is the unknown storage cost.

## Request draft — do not submit without user authorization

**Product requested:** Land Use and Land Cover (10K), SISDP Phase II, vector/Shapefile delivery.  
**Purpose:** Research studies.  
**AOI:** Jharkhand, restricted to the smallest administrative units covering the six locations in `data/processed/cv_dataset/reference_review_register.csv`; please confirm the district list and provide coverage for those AOIs. If possible, provide an AOI-clipped sample only for those six 64×64 Sentinel-2 chip footprints. Do not send statewide data without prior file-size estimate and approval.

**Utilization overview (portal minimum 50 characters):**  
“Academic research on broad land-cover segmentation using existing Sentinel-2 chips in Jharkhand. The data will be independently quality-checked and any uncertain pixels left unlabelled.”

**Questions to include with request / send to the SISDP technical team before accepting delivery:**

1. Does Phase II 1:10K LULC cover Jharkhand, and which districts/polygons are available for the six AOIs (coordinates in the attached register)? Please confirm coverage in writing.
2. What is the exact mapping year/date and source-imagery acquisition period for each requested district or feature? Please explain the example layer identifier containing `2016_2019` versus the metadata's 2018–2023 range.
3. Can NRSC provide a clipped Shapefile sample for the six chip footprints? What are the compressed archive size, extracted size, feature count and expected delivery format? If not, quote those values for each smallest available district package.
4. Please provide the full class code/name hierarchy, data dictionary, geometry and positional accuracy/scale information, CRS definition, no-data/gap semantics, quality/validation report and version identifier.
5. Please identify the dataset-specific licence/terms. Does the approval expressly permit academic local download, copying, clipping, reprojection, categorical rasterization into per-pixel reference masks, and use in model development/evaluation?
6. May derived masks, class counts, figures and evaluation results be included in a thesis/paper/public presentation? What attribution is required? May any derived sample files be shared with examiners or deposited with the project? If not, state restrictions and retention/deletion requirements.
7. Is separate written authorization required under the Bhuvan terms for creating derivative masks or publishing derived figures? Please provide that authorization before delivery/use.

**Suggested official contact:** SISDP Technical Team, RRSC-NRSC, `sisdpadmin@nrsc.gov.in` (the manual displays this address obfuscated as `sisdpadmin[at]nrsc[dot]gov[dot]in`; verify it on the portal before sending). The manual also lists telephone 040-23884356. This report only prepares the request content; it has not been sent.

## Updated feasibility decision

**No download is authorized or justified yet.** The official portal offers a request workflow and identifies an academic/research purpose, and the manual says delivered data are Shapefiles. But exact Jharkhand Phase II geometry and dates are unverified, package size is unknown, and the general terms require prior written authorization for copying and derivative work. Because mask generation is a derivative use, proceed only after written permission specifically covers the proposed academic workflow and any intended publication. Do not label current chips or train a model until the actual data package passes CRS/schema/date/geometry/overlap validation and temporal suitability review.

## Sources reviewed

- [Bhuvan Panchayat user manual, June 2024 (download workflow, Phase II Shapefile format, WMS, metadata)](https://bhuvanpanchayat.nrsc.gov.in/SISDP/BP-usermanual.pdf).
- [Bhuvan 3 Nov 2023 update (14 states, research/academic Get Data route)](https://bhuvan.nrsc.gov.in/updates/bhuvan_nov2023.html).
- [Bhuvan Terms of Service](https://bhuvan.nrsc.gov.in/bhuvan/bhuvan_terms/).
- [Department of Space answer, Rajya Sabha question 2207, 7 Aug 2025](https://sansad.in/getFile/annex/268/AU2207_XpCcS7.pdf?source=pqars).
- [Bhuvan SISDP Phase II WMS page](https://bhuvanpanchayat.nrsc.gov.in/).
- [Bhuvan 2026 LULC 50K AOI announcement](https://bhuvan.nrsc.gov.in/updates/bhuvan_apr2026.html) (used only to distinguish that AOI workflow from Phase II 10K).
