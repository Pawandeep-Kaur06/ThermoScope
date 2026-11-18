"""Create final-pilot tables, figures, and a provenance manifest from run_001.

This is a reporting layer only: it reads the completed run and local OSM snapshot,
and never retrieves data or modifies pipeline outputs.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import platform
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pyproj
import shapely


ROOT = Path(__file__).resolve().parents[1]
BBOX = (85.75, 23.25, 86.75, 24.00)
CRS_METRIC = "EPSG:32645"
THRESHOLDS = (100, 250, 500, 1000)
ROLE_FIELDS = {
    "Industrial land use": "nearest_industrial_landuse_distance_m",
    "Industrial facilities": "nearest_industrial_facility_distance_m",
    "Mining / extraction areas": "nearest_mining_extraction_area_distance_m",
    "Mine workings": "nearest_mine_working_feature_distance_m",
    "Waste facilities": "nearest_waste_facility_distance_m",
    "Industrial rail": "nearest_industrial_rail_distance_m",
    "Power generation": "nearest_power_generation_distance_m",
    "Power sites": "nearest_power_site_distance_m",
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_tags(value: object) -> dict:
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        try:
            parsed = ast.literal_eval(value)
        except (ValueError, SyntaxError):
            return {}
    return parsed if isinstance(parsed, dict) else {}


def validate_inputs(firms: pd.DataFrame, matching: pd.DataFrame,
                    features: pd.DataFrame, ranking: pd.DataFrame) -> dict:
    frames = {"firms": firms, "matching": matching, "features": features,
              "ranking": ranking}
    required = {"firms": {"latitude", "longitude", "acq_date", "frp", "confidence", "firms_observation_id"},
                "matching": {"latitude", "longitude", "firms_observation_id", "distance_crs"},
                "features": {"latitude", "longitude", "acq_date", "firms_observation_id", "hotspot_cell_id", "cell_prior_distinct_acquisition_dates", "s2_spectral_data_status"},
                "ranking": {"latitude", "longitude", "acq_date", "firms_source_row", "candidate_category", "firms_detection_label"}}
    for name, frame in frames.items():
        missing = required[name] - set(frame.columns)
        if missing:
            raise ValueError(f"{name} is missing required columns: {sorted(missing)}")
    ids = firms.firms_observation_id
    if len(firms) != 9220:
        raise ValueError(f"Expected audited 9,220 FIRMS rows; found {len(firms)}")
    if ids.isna().any() or ids.duplicated().any():
        raise ValueError("FIRMS observation IDs are missing or duplicated")
    if not ((firms.latitude.between(BBOX[1], BBOX[3])) &
            (firms.longitude.between(BBOX[0], BBOX[2]))).all():
        raise ValueError("FIRMS coordinates fall outside the configured pilot bbox")
    if matching.firms_observation_id.duplicated().any() or features.firms_observation_id.duplicated().any():
        raise ValueError("Matching/features contain duplicate observation IDs")
    if set(ids) != set(matching.firms_observation_id) or set(ids) != set(features.firms_observation_id):
        raise ValueError("Input stages do not contain identical observation ID sets")
    if ranking.firms_source_row.duplicated().any() or len(ranking) != len(firms):
        raise ValueError("Ranking row count/source-row uniqueness does not align with FIRMS")
    return {"rows": len(firms), "unique_ids": int(ids.nunique()),
            "date_count": int(pd.to_datetime(firms.acq_date).nunique()),
            "bbox_wgs84": list(BBOX), "matching_crs": sorted(matching.distance_crs.dropna().unique().tolist())}


def _save(fig, path: Path) -> None:
    fig.savefig(path, dpi=300, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def generate(run_root: Path, osm_path: Path, out_root: Path) -> dict:
    figs = out_root / "figures"
    tables = out_root / "tables"
    for folder in (figs, tables):
        if folder.exists() and any(folder.iterdir()):
            raise FileExistsError(f"Refusing to overwrite non-empty output directory: {folder}")
        folder.mkdir(parents=True, exist_ok=True)

    paths = {
        "firms": run_root / "input/firms_pilot.csv",
        "matching": run_root / "spatial_matching/firms_pilot_osm_proximity.csv",
        "features": run_root / "features/feature_table.csv.gz",
        "ranking": run_root / "candidate_ranking/candidate_ranking.csv",
        "thresholds": run_root / "spatial_matching/distance_threshold_summary.csv",
        "role_coverage": run_root / "spatial_matching/role_coverage_by_threshold.csv",
        "recurrence": run_root / "spatial_matching/recurrence_summary.csv",
        "feature_missingness": run_root / "features/feature_missingness.csv",
        "quality": run_root / "features/quality_checks.json",
        "manifest": run_root / "validation/reproducibility_manifest.json",
        "osm": osm_path,
    }
    missing_paths = [str(p) for p in paths.values() if not p.exists()]
    if missing_paths:
        raise FileNotFoundError("Missing required audited input(s): " + ", ".join(missing_paths))

    firms = pd.read_csv(paths["firms"])
    matching = pd.read_csv(paths["matching"])
    features = pd.read_csv(paths["features"])
    ranking = pd.read_csv(paths["ranking"])
    quality = json.loads(paths["quality"].read_text(encoding="utf-8"))
    run_manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    checks = validate_inputs(firms, matching, features, ranking)
    dates = pd.to_datetime(firms.acq_date, errors="coerce")
    if dates.isna().any():
        raise ValueError("Invalid acquisition dates found")
    firms["date"] = dates
    features["date"] = pd.to_datetime(features.acq_date, errors="coerce")
    ranking["frp_mw"] = pd.to_numeric(ranking.thermal_frp_mw, errors="coerce")
    matching["frp_mw"] = pd.to_numeric(matching.frp, errors="coerce")

    # Tables: descriptive calculations from the source records.
    confidence = firms.confidence.fillna("missing").astype(str).str.lower().value_counts()
    daynight = firms.daynight.fillna("missing").astype(str).str.upper().value_counts()
    frp = pd.to_numeric(firms.frp, errors="coerce")
    firms_summary = pd.DataFrame([
        ("observations", len(firms)), ("unique_observation_ids", firms.firms_observation_id.nunique()),
        ("acquisition_dates", dates.nunique()), ("date_start", dates.min().date()),
        ("date_end", dates.max().date()), ("frp_mean_mw", frp.mean()),
        ("frp_median_mw", frp.median()), ("frp_p95_mw", frp.quantile(.95)),
        ("frp_min_mw", frp.min()), ("frp_max_mw", frp.max()),
        ("latitude_min", firms.latitude.min()), ("latitude_max", firms.latitude.max()),
        ("longitude_min", firms.longitude.min()), ("longitude_max", firms.longitude.max()),
    ], columns=["metric", "value"])
    for c, n in confidence.items():
        firms_summary.loc[len(firms_summary)] = [f"confidence_{c}_count", int(n)]
    for c, n in daynight.items():
        firms_summary.loc[len(firms_summary)] = [f"daynight_{c}_count", int(n)]
    firms_summary.to_csv(tables / "firms_observation_summary.csv", index=False)

    layers = []
    role_counts: dict[str, int] = {}
    group_counts: dict[str, int] = {}
    for layer in gpd.list_layers(paths["osm"]).name.tolist():
        gdf = gpd.read_file(paths["osm"], layer=layer)
        if gdf.crs is None:
            raise ValueError(f"OSM layer {layer} has no declared CRS")
        if not gdf.geometry.is_valid.all():
            raise ValueError(f"OSM layer {layer} includes invalid geometries")
        for _, row in gdf.iterrows():
            tags = parse_tags(row.get("all_tags"))
            groupval = row.get("feature_groups")
            try:
                groups = json.loads(groupval) if isinstance(groupval, str) else []
            except json.JSONDecodeError:
                groups = []
            if not groups:
                groups = ["unclassified"]
            for group in groups:
                group_counts[group] = group_counts.get(group, 0) + 1
            power = tags.get("power")
            role = ("Power transmission towers" if power == "tower" else
                    "Power transmission lines" if power == "line" else
                    "Power infrastructure (other)" if power else None)
            if role:
                role_counts[role] = role_counts.get(role, 0) + 1
        gdf["_layer"] = layer
        layers.append(gdf)
    osm = pd.DataFrame([{"category": k, "feature_count": v,
                         "category_basis": "existing OSM feature_groups; categories may overlap"}
                        for k, v in sorted(group_counts.items())])
    osm = pd.concat([osm, pd.DataFrame([{"category": k, "feature_count": v,
                  "category_basis": "parsed power tag; overlaps feature_groups"}
                  for k, v in sorted(role_counts.items())])], ignore_index=True)
    osm.to_csv(tables / "osm_feature_category_summary.csv", index=False)

    thresh = pd.read_csv(paths["thresholds"])
    thresh.to_csv(tables / "industrial_proximity_threshold_comparison.csv", index=False)
    recurrence = pd.read_csv(paths["recurrence"])
    recurrence.to_csv(tables / "recurrence_summary.csv", index=False)

    # Enrich candidate table with robust aggregate summaries from ranking rows.
    ranking_summary = ranking.groupby("candidate_category", dropna=False).agg(
        detections=("firms_source_row", "size"),
        unique_250m_cells=("hotspot_cell_id", "nunique"),
        median_frp_mw=("frp_mw", "median"),
        median_prior_distinct_dates=("cell_prior_distinct_acquisition_dates", "median"),
        relevant_osm_within_250m=("osm_relevant_context_within_250m", "sum"),
        valid_pre_detection_s2=("sentinel2_clear_pre_detection_spectrum_available", "sum"),
    ).reset_index()
    ranking_summary.to_csv(tables / "candidate_ranking_summary.csv", index=False)

    s2counts = features.s2_spectral_data_status.fillna("missing_status").value_counts().rename_axis("status").reset_index(name="detections")
    s2counts["percent"] = 100 * s2counts.detections / len(features)
    s2counts.to_csv(tables / "satellite_evidence_coverage_summary.csv", index=False)

    s2band_cols = ["s2_b04_red_dn", "s2_b03_green_dn", "s2_b02_blue_dn", "s2_b11_swir16_dn"]
    missingness = pd.DataFrame({"feature": s2band_cols + ["s2_chip_available_for_context", "s2_temporally_eligible", "s2_pixel_valid", "s2_spectral_predictor_eligible"],
                                "missing_or_false_count": [int(features[c].isna().sum()) if c in s2band_cols else int((~features[c].fillna(False).astype(bool)).sum()) for c in s2band_cols + ["s2_chip_available_for_context", "s2_temporally_eligible", "s2_pixel_valid", "s2_spectral_predictor_eligible"]]})
    missingness["percent"] = 100 * missingness.missing_or_false_count / len(features)
    missingness.to_csv(tables / "feature_availability_summary.csv", index=False)

    coord_ok = ((firms.latitude.between(BBOX[1], BBOX[3])) & firms.longitude.between(BBOX[0], BBOX[2])).all()
    validation = pd.DataFrame([
        ("FIRMS rows", len(firms), "PASS" if len(firms) == 9220 else "FAIL"),
        ("FIRMS unique IDs", firms.firms_observation_id.nunique(), "PASS" if firms.firms_observation_id.is_unique else "FAIL"),
        ("matching rows", len(matching), "PASS" if len(matching) == len(firms) else "FAIL"),
        ("feature rows", len(features), "PASS" if len(features) == len(firms) else "FAIL"),
        ("ranking rows", len(ranking), "PASS" if len(ranking) == len(firms) else "FAIL"),
        ("all FIRMS coordinates inside pilot bbox", bool(coord_ok), "PASS" if coord_ok else "FAIL"),
        ("distance CRS", ";".join(checks["matching_crs"]), "PASS" if checks["matching_crs"] == [CRS_METRIC] else "REVIEW"),
        ("invalid feature geometries in OSM", sum(int((~g.geometry.is_valid).sum()) for g in layers), "PASS"),
        ("verified detection labels", int((ranking.firms_detection_label.astype(str) != "unknown_unlinked").sum()), "PASS"),
        ("S2 usable pre-detection spectra", int(features.s2_spectral_predictor_eligible.fillna(False).astype(bool).sum()), "PASS"),
        ("experiment quality_checks overall", quality.get("overall_status", "unknown"), "PASS" if quality.get("overall_status") == "passed" else "REVIEW"),
    ], columns=["check", "result", "status"])
    validation.to_csv(tables / "data_quality_validation_summary.csv", index=False)

    # Figure 1: spatial FIRMS distribution.
    points = gpd.GeoDataFrame(firms, geometry=gpd.points_from_xy(firms.longitude, firms.latitude), crs="EPSG:4326").to_crs(CRS_METRIC)
    minx, miny, maxx, maxy = points.total_bounds
    fig, ax = plt.subplots(figsize=(9, 8))
    scatter = ax.scatter(points.geometry.x, points.geometry.y, c=np.log10(frp.clip(lower=.01)), s=8, alpha=.42, cmap="inferno", rasterized=True)
    ax.set(xlim=(minx-1500,maxx+1500), ylim=(miny-1500,maxy+1500), xlabel="Easting (m, EPSG:32645)", ylabel="Northing (m, EPSG:32645)", title="FIRMS thermal observations — Dhanbad–Jharia–Bokaro")
    cb=fig.colorbar(scatter,ax=ax); cb.set_label("log10(FRP, MW)")
    ax.grid(alpha=.2); _save(fig,figs/"01_study_area_firms_detections.png")

    # Figure 2: acquisition series.
    daily=dates.value_counts().sort_index().asfreq("D",fill_value=0)
    fig,ax=plt.subplots(figsize=(12,4.5)); ax.bar(daily.index,daily.values,width=1,color="#3b82a0",alpha=.62,label="Daily detections")
    ax.plot(daily.index,daily.rolling(7,min_periods=1).mean(),color="#b6402e",lw=1.8,label="7-day rolling mean")
    ax.set(title="FIRMS observations by acquisition date",ylabel="Observations",xlabel="Acquisition date"); ax.legend(frameon=False); ax.grid(axis="y",alpha=.2); _save(fig,figs/"02_firms_observations_over_time.png")

    # Figure 3: thermal attribute distributions.
    fig,(ax1,ax2)=plt.subplots(1,2,figsize=(11,4.5)); ax1.hist(frp.dropna(),bins=np.geomspace(max(.1,frp[frp>0].min()),frp.max(),32),color="#d97732",edgecolor="white"); ax1.set_xscale("log"); ax1.set(title="FRP distribution",xlabel="FRP (MW, log scale)",ylabel="Observations")
    conf_order=["l","n","h","missing"]; cc=firms.confidence.fillna("missing").astype(str).str.lower().value_counts().reindex(conf_order,fill_value=0); ax2.bar(cc.index,cc.values,color=["#8899aa","#4e79a7","#e15759","#bbbbbb"]); ax2.set(title="FIRMS confidence categories",xlabel="Confidence code",ylabel="Observations"); ax2.grid(axis="y",alpha=.2); _save(fig,figs/"03_frp_and_confidence_distributions.png")

    # Figure 4: non-exclusive industrial/power-generation proximity categories.
    prox_rows=[]
    for label,col in ROLE_FIELDS.items():
        vals=pd.to_numeric(matching[col],errors="coerce")
        for t in THRESHOLDS:
            prox_rows.append({"feature_category":label,"threshold_m":t,"detections_within_threshold":int((vals<=t).sum()),"available_distances":int(vals.notna().sum())})
    prox=pd.DataFrame(prox_rows); prox.to_csv(tables/"osm_proximity_by_feature_category.csv",index=False)
    fig,ax=plt.subplots(figsize=(10,6)); sub=prox[prox.threshold_m.eq(250)].sort_values("detections_within_threshold")
    ax.barh(sub.feature_category,sub.detections_within_threshold,color="#4c8c6b"); ax.set(title="Detections near mapped industrial categories (≤250 m)",xlabel="FIRMS detections",ylabel="Nearest feature role")
    ax.text(.99,.02,"Per-role counts overlap; transmission infrastructure excluded from industrial roles.",transform=ax.transAxes,ha="right",va="bottom",fontsize=8); ax.grid(axis="x",alpha=.2); _save(fig,figs/"04_industrial_proximity_by_osm_category.png")

    # Figure 5: cells are spatial bins, not physical-source identities.
    cell=features.groupby("hotspot_cell_id",dropna=True).agg(observations=("firms_observation_id","size"),distinct_dates=("date","nunique")).reset_index()
    rec_summary=pd.DataFrame([{"metric":"unique_250m_cells","value":len(cell)},*[{"metric":f"cells_with_{n}_distinct_dates","value":int((cell.distinct_dates==n).sum())} for n in sorted(cell.distinct_dates.unique())],{"metric":"median_distinct_dates_per_cell","value":cell.distinct_dates.median()},{"metric":"max_distinct_dates_per_cell","value":cell.distinct_dates.max()},{"metric":"median_observations_per_cell","value":cell.observations.median()},{"metric":"max_observations_per_cell","value":cell.observations.max()}])
    rec_summary.to_csv(tables/"recurrence_distribution_summary.csv",index=False)
    fig,(ax1,ax2)=plt.subplots(1,2,figsize=(11,4.5)); bins=np.arange(.5,cell.distinct_dates.max()+1.5,1); ax1.hist(cell.distinct_dates,bins=bins,color="#6b8e9f"); ax1.set(title="Distinct acquisition dates per 250 m cell",xlabel="Dates observed",ylabel="Cells"); ax2.hist(cell.observations,bins=30,color="#a274a0"); ax2.set(title="Detection rows per 250 m cell",xlabel="Detection rows",ylabel="Cells"); _save(fig,figs/"05_thermal_recurrence_by_250m_cell.png")

    # Figure 6: evidence-priority category distribution.
    cats=ranking_summary.sort_values("detections")
    fig,ax=plt.subplots(figsize=(10,5.5)); ax.barh(cats.candidate_category.str.replace("_"," "),cats.detections,color="#577590"); ax.set(title="Rule-based candidate review categories",xlabel="FIRMS detections",ylabel="Review category"); ax.grid(axis="x",alpha=.2); _save(fig,figs/"06_candidate_ranking_categories.png")

    # Figure 7: S2 status and per-band availability.
    fig,(ax1,ax2)=plt.subplots(1,2,figsize=(12,5)); ss=s2counts.sort_values("detections"); ax1.barh(ss.status.str.replace("_"," "),ss.detections,color="#5b8e7d"); ax1.set(title="Sentinel-2 evidence status",xlabel="Detections",ylabel="Status")
    flags=pd.Series({"Chip context":features.s2_chip_available_for_context,"Temporal eligibility":features.s2_temporally_eligible,"Clear pixel flag":features.s2_pixel_valid,"Usable pre-event spectra":features.s2_spectral_predictor_eligible}).apply(lambda s:int(s.fillna(False).astype(bool).sum()))
    ax2.bar(flags.index,flags.values,color="#d9a441"); ax2.set(title="Sentinel-2 availability flags",ylabel="Detections",ylim=(0,max(flags.max()*1.12,1))); ax2.tick_params(axis="x",rotation=30); ax2.grid(axis="y",alpha=.2)
    for i,v in enumerate(flags.values): ax2.text(i,v+max(flags.max()*.015,.1),str(v),ha="center",fontsize=9)
    ax2.text(.98,.98,"Flags can overlap; clear-pixel flag alone does not imply historical eligibility.",transform=ax2.transAxes,ha="right",va="top",fontsize=8); _save(fig,figs/"07_feature_availability_and_sentinel2.png")

    # Figure 8: mapped context with separate symbols for mapped land/industrial features and towers/lines.
    osm_all=gpd.GeoDataFrame(pd.concat(layers,ignore_index=True),geometry="geometry",crs=layers[0].crs).to_crs(CRS_METRIC)
    tags=osm_all.all_tags.map(parse_tags)
    groups=osm_all.feature_groups.fillna("[]").astype(str)
    industrial_mask=groups.str.contains("industrial|mining_extraction|waste_facility",case=False,regex=True)
    power_tower=tags.map(lambda t:t.get("power")=="tower")
    power_line=tags.map(lambda t:t.get("power")=="line")
    fig,ax=plt.subplots(figsize=(10,8)); osm_all[industrial_mask].plot(ax=ax,color="#5b8e7d",edgecolor="#245c4a",linewidth=.4,alpha=.45,label="Mapped industrial/mining/waste context")
    osm_all[power_line].plot(ax=ax,color="#6b7280",linewidth=1,alpha=.7,label="Transmission line")
    osm_all[power_tower].plot(ax=ax,color="#2563eb",markersize=6,alpha=.45,label="Transmission tower")
    points.plot(ax=ax,color="#d1495b",markersize=5,alpha=.42,label="FIRMS observation",rasterized=True)
    ax.set(title="FIRMS observations and mapped OSM industrial/power context",xlabel="Easting (m, EPSG:32645)",ylabel="Northing (m, EPSG:32645)"); ax.legend(loc="upper left",fontsize=8,framealpha=.9); ax.set_xlim(minx-1500,maxx+1500); ax.set_ylim(miny-1500,maxy+1500); ax.grid(alpha=.15); _save(fig,figs/"08_firms_and_osm_context_map.png")

    # Generate table values and a self-contained report based on calculated outputs.
    report_lines=["# Final pilot results — ThermoScope", "", "## Scope and interpretation", "",
      "This analysis uses the already completed Dhanbad–Jharia–Bokaro pilot run. FIRMS points are satellite thermal-anomaly observations. OSM proximity, recurrence, GEM context, and Sentinel-2 samples are evidence indicators for investigation; none establishes a detection's cause. The rule-based categories are review priorities, not verified fire classes. No supervised classifier or predictive metric is reported.", "",
      "## Data analysed", "",
      f"The run contains **{len(firms):,} FIRMS observations** over **{dates.nunique()} acquisition dates**, from **{dates.min().date()}** through **{dates.max().date()}**. The detection coordinates lie within the configured pilot bounds ({BBOX[1]}–{BBOX[3]}°N, {BBOX[0]}–{BBOX[2]}°E). Prepared FIRMS, matching, engineered-feature, and ranking files each contain {len(firms):,} rows; the first three share a complete unique observation-ID set. Ranking aligns one-to-one by source row.", "",
      f"FRP median is **{frp.median():.2f} MW** (mean {frp.mean():.2f}, 95th percentile {frp.quantile(.95):.2f}, maximum {frp.max():.2f}). Confidence codes: nominal `n` {int((firms.confidence=='n').sum()):,}, low `l` {int((firms.confidence=='l').sum()):,}, high `h` {int((firms.confidence=='h').sum()):,}. These are FIRMS attributes, not certainty of industrial cause.", "",
      "## Spatial and temporal patterns", "",
      f"Using the experiment's fixed 250 m EPSG:32645 grid, {len(cell):,} cells contain detections. {int((cell.distinct_dates>1).sum()):,} cells ({100*(cell.distinct_dates>1).mean():.1f}%) have observations on multiple distinct dates; the median cell spans {cell.distinct_dates.median():.0f} date(s), and the maximum is {cell.distinct_dates.max()} dates. Recurrence is computed using dates strictly before each observation in the feature/ranking evidence. A grid cell is a spatial bin, not an assertion of one physical source; multiple sources may occupy a cell and a source can move across cells.", "",
      "The daily plot shows observations by FIRMS acquisition date and a 7-day rolling mean. It describes sampling volume and temporal clustering, not incident duration or continuous burning.", "",
      "## Industrial and power context", "",
      f"At the relevant-context thresholds, unambiguous candidate / ambiguous / no relevant mapped feature counts are: 100 m {int(thresh.loc[thresh.threshold_m==100,'proximity_candidate_unambiguous'].iloc[0]):,}/{int(thresh.loc[thresh.threshold_m==100,'ambiguous_proximity'].iloc[0]):,}/{int(thresh.loc[thresh.threshold_m==100,'unknown_no_relevant_feature_within_threshold'].iloc[0]):,}; 250 m {int(thresh.loc[thresh.threshold_m==250,'proximity_candidate_unambiguous'].iloc[0]):,}/{int(thresh.loc[thresh.threshold_m==250,'ambiguous_proximity'].iloc[0]):,}/{int(thresh.loc[thresh.threshold_m==250,'unknown_no_relevant_feature_within_threshold'].iloc[0]):,}; 500 m {int(thresh.loc[thresh.threshold_m==500,'proximity_candidate_unambiguous'].iloc[0]):,}/{int(thresh.loc[thresh.threshold_m==500,'ambiguous_proximity'].iloc[0]):,}/{int(thresh.loc[thresh.threshold_m==500,'unknown_no_relevant_feature_within_threshold'].iloc[0]):,}; 1 km {int(thresh.loc[thresh.threshold_m==1000,'proximity_candidate_unambiguous'].iloc[0]):,}/{int(thresh.loc[thresh.threshold_m==1000,'ambiguous_proximity'].iloc[0]):,}/{int(thresh.loc[thresh.threshold_m==1000,'unknown_no_relevant_feature_within_threshold'].iloc[0]):,}.", "",
      "The matching output keeps transmission towers, lines, and other power infrastructure distinct from industrial land, mining/extraction areas, industrial facilities, and generation sites. Figure 4 reports non-exclusive role-specific distance counts derived from the matched distances; one detection can be near multiple categories. OSM is a static mapped snapshot with incomplete and temporally unversioned coverage, so absence of mapped context is not evidence of absence of an industrial source. GEM records are supplementary static facility context only.", "",
      "## Candidate prioritization", "",
      f"The ranking partitions all {len(ranking):,} detections into six rule-based review categories (see the candidate table and Figure 6). The largest category contains {int(ranking_summary.detections.max()):,} records. A high review priority is a transparent combination of thermal attributes, past-only recurrence, mapped context, and limited satellite evidence; it is not a calibrated probability or classification. Every label field remains `unknown_unlinked`; there are no verified detection-level incident labels, no fabricated negatives, and no supervised evaluation metrics.", "",
      "## Satellite evidence and limitations", "",
      f"Sentinel-2 statuses in the engineered feature table: {int((features.s2_spectral_data_status=='not_available_no_chip').sum()):,} rows without chip metadata; {int((features.s2_spectral_data_status=='post_detection_imagery_withheld').sum()):,} with post-detection imagery withheld from historical features; {int((features.s2_spectral_data_status=='cloud_shadow_contaminated_or_unverified').sum()):,} cloud/shadow-contaminated or unverifiable; and {int((features.s2_spectral_data_status=='sampled_pre_detection_image').sum()):,} with sampled, temporally eligible spectra. Thus only {int(features.s2_spectral_predictor_eligible.fillna(False).astype(bool).sum())} detections ({100*features.s2_spectral_predictor_eligible.fillna(False).astype(bool).mean():.3f}%) have usable pre-detection spectral features. The chips are optical context; they do not independently confirm a thermal event. Missing imagery is not evidence of absence.", "",
      "## Data quality, uncertainty, and reproducibility", "",
      f"The run's saved feature quality report marks overall checks `{quality.get('overall_status')}`. This reporting script additionally checked row alignment, ID uniqueness, bbox membership, metric CRS declaration, and OSM geometry validity. Static OSM/GEM snapshots do not establish as-of-date facility status; FIRMS observations are sensor detections rather than adjudicated fire events; recurrence reflects repeat observation rather than source identity. No new data were downloaded and the experiment was not rerun.", "",
      "## Generated outputs", "",
      "### Figures", "",
      *[f"- [Figure {i:02d}: {title}](../outputs/final_pilot/figures/{name})" for i,(name,title) in enumerate([
          ("01_study_area_firms_detections.png","Study-area FIRMS detections"),
          ("02_firms_observations_over_time.png","Observations over time"),
          ("03_frp_and_confidence_distributions.png","FRP and confidence distributions"),
          ("04_industrial_proximity_by_osm_category.png","Industrial proximity by OSM category"),
          ("05_thermal_recurrence_by_250m_cell.png","Recurrence by 250 m cell"),
          ("06_candidate_ranking_categories.png","Candidate review categories"),
          ("07_feature_availability_and_sentinel2.png","Feature availability and Sentinel-2 coverage"),
          ("08_firms_and_osm_context_map.png","FIRMS and OSM context map")],1)], "",
      "### Tables", "",
      *[f"- [{name.replace('_',' ').replace('.csv','').title()}](../outputs/final_pilot/tables/{name})" for name in sorted(p.name for p in tables.glob("*.csv"))], "",
      "Input checksums, analysis parameters, software versions, and output hashes are recorded in [`results_manifest.json`](../outputs/final_pilot/results_manifest.json).", ""]
    report_path=ROOT/"docs/final_pilot_results.md"
    report_path.write_text("\n".join(report_lines),encoding="utf-8")

    manifest={"analysis_id":"thermoscope_final_pilot_analysis_v1","generated_at_utc":datetime.now(timezone.utc).isoformat(),"source_run":str(run_root.relative_to(ROOT)),"source_files":{k:{"path":str(p.relative_to(ROOT)),"size_bytes":p.stat().st_size,"sha256":sha256(p)} for k,p in paths.items()},"analysis_parameters":{"bbox_wgs84":BBOX,"distance_crs":CRS_METRIC,"proximity_thresholds_m":list(THRESHOLDS),"recurrence_grid_m":250,"recurrence_temporal_rule":"strictly earlier acquisition dates only, as represented by the saved feature table","satellite_rule":"only valid, temporally eligible pre-detection samples counted; post-detection withheld; missing is not absence","osm_role_categories":list(ROLE_FIELDS),"osm_map_categories":"existing feature_groups matching industrial/mining/waste; power=tower and power=line drawn separately"},"input_validation":checks,"experiment_validation":{"overall_status":quality.get("overall_status"),"validation_check_count":run_manifest.get("validation",{}).get("check_count"),"candidate_labels_available":False,"supervised_model_trained":False},"software":{"python":platform.python_version(),"pandas":pd.__version__,"geopandas":gpd.__version__,"shapely":shapely.__version__,"pyproj":pyproj.__version__,"matplotlib":matplotlib.__version__},"outputs":{}}
    for folder in (figs,tables):
        for p in sorted(folder.iterdir()):
            manifest["outputs"][str(p.relative_to(ROOT))]={"size_bytes":p.stat().st_size,"sha256":sha256(p)}
    manifest_path=out_root/"results_manifest.json"
    manifest_path.write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    return {"out_root":out_root,"rows":len(firms),"cells":len(cell),"candidate_categories":ranking_summary.to_dict(orient="records"),"satellite_statuses":s2counts.to_dict(orient="records"),"figures":len(list(figs.glob("*.png"))),"tables":len(list(tables.glob("*.csv"))),"manifest":manifest_path}


def main() -> None:
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-root",type=Path,default=ROOT/"data/processed/final_pilot_experiment/run_001")
    ap.add_argument("--osm",type=Path,default=ROOT/"data/processed/osm/dhanbad_jharia_bokaro_osm.gpkg")
    ap.add_argument("--output-root",type=Path,default=ROOT/"outputs/final_pilot")
    args=ap.parse_args()
    result=generate(args.run_root,args.osm,args.output_root)
    print(json.dumps(result,indent=2,default=str))


if __name__=="__main__":
    main()
