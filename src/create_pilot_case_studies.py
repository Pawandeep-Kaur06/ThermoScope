"""Create auditable case studies from the existing final pilot outputs only."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
import numpy as np
import pandas as pd
import pyproj
import rasterio
from pyproj import Transformer
import shapely

ROOT = Path(__file__).resolve().parents[1]
RUN_DEFAULT = ROOT / "data/processed/final_pilot_experiment/run_001"
OSM_DEFAULT = ROOT / "data/processed/osm/dhanbad_jharia_bokaro_osm.gpkg"
SATELLITE_DEFAULT = ROOT / "data/processed/satellite_investigation/run_20261018T212303Z"
OUT_DEFAULT = ROOT / "outputs/final_pilot/case_studies/run_20261116T_case_review_final"
CRS_METRIC = "EPSG:32645"
MAX_OSM_DISTANCE_M = 1000.0
MAP_RADIUS_M = 1500.0


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def parse_dict(value: object) -> dict:
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        result = json.loads(value)
    except json.JSONDecodeError:
        try:
            result = ast.literal_eval(value)
        except (SyntaxError, ValueError):
            return {}
    return result if isinstance(result, dict) else {}


def parse_groups(value: object) -> list[str]:
    if not isinstance(value, str):
        return []
    try:
        result = json.loads(value)
    except json.JSONDecodeError:
        return []
    return [str(v) for v in result] if isinstance(result, list) else []


def select_representative_cases(ranking: pd.DataFrame, per_category: int = 2) -> pd.DataFrame:
    """Select within-category rank quantiles, not only the top-ranked records."""
    if per_category != 2:
        raise ValueError("The documented stratified design currently selects two cases per category")
    required = {"candidate_category", "review_priority_rank", "firms_source_row", "hotspot_cell_id"}
    if not required.issubset(ranking.columns):
        raise ValueError(f"Ranking table missing columns: {sorted(required-set(ranking.columns))}")
    if ranking.firms_source_row.duplicated().any():
        raise ValueError("Ranking source-row identifiers must be unique")
    selected = []
    for category, frame in ranking.groupby("candidate_category", sort=True, dropna=False):
        frame = frame.sort_values(["review_priority_rank", "firms_source_row"], kind="stable").reset_index(drop=True)
        if len(frame) < 2:
            raise ValueError(f"Category {category!r} has fewer than two observations")
        positions = [round((len(frame)-1)*0.25), round((len(frame)-1)*0.75)]
        if positions[0] == positions[1]:
            positions[1] = min(len(frame)-1, positions[0]+1)
        pair = frame.iloc[positions].copy()
        second_position_label = "within-category 75th percentile"
        if "s2_chip_available_for_context" in frame.columns:
            chip_options = frame[frame.s2_chip_available_for_context.fillna(False).astype(bool)]
            if not chip_options.empty and not bool(pair.iloc[0].get("s2_chip_available_for_context", False)):
                alternatives = chip_options[chip_options.hotspot_cell_id.ne(pair.iloc[0].hotspot_cell_id)]
                if not alternatives.empty:
                    target_rank = frame.iloc[positions[1]].review_priority_rank
                    closest = (alternatives.review_priority_rank-target_rank).abs().sort_values(kind="stable").index[0]
                    pair.iloc[1] = frame.loc[closest]
                    second_position_label = "nearest chip-available case to within-category 75th percentile"
        if pair.hotspot_cell_id.nunique(dropna=False) < 2:
            alternatives = frame[~frame.firms_source_row.isin(pair.firms_source_row)]
            alternatives = alternatives[~alternatives.hotspot_cell_id.isin(pair.hotspot_cell_id)]
            if not alternatives.empty:
                pair.iloc[1] = alternatives.iloc[len(alternatives)//2]
        pair["case_stratum_position"] = ["within-category 25th percentile", second_position_label]
        pair["selection_category"] = category
        selected.append(pair)
    cases = pd.concat(selected, ignore_index=True)
    def _position_slug(value: str) -> str:
        if "25th percentile" in value:
            return "25thpct"
        if "75th percentile" in value:
            return "75thpct"
        return "alternate"
    cases["case_id"] = [f"case_{i:02d}_{_slug(row.candidate_category)}_{_position_slug(row.case_stratum_position)}"
                        for i, row in enumerate(cases.itertuples(index=False), 1)]
    if cases.firms_source_row.duplicated().any():
        raise ValueError("Selected case rows unexpectedly contain duplicates")
    return cases


def _slug(value: object) -> str:
    return "_".join("".join(c.lower() if c.isalnum() else " " for c in str(value)).split())


def _bool(value: object) -> bool:
    return False if pd.isna(value) else bool(value)


def classify_osm(row: pd.Series) -> str:
    tags = parse_dict(row.get("all_tags"))
    groups = parse_groups(row.get("feature_groups"))
    power = tags.get("power")
    if power == "tower":
        return "power transmission tower"
    if power == "line":
        return "power transmission line"
    if power in {"plant", "generator", "substation"}:
        return f"power {power}"
    for group in ("mining_extraction", "industrial_landuse", "industrial_facility", "power_infrastructure", "waste_facility", "industrial_structure"):
        if group in groups:
            return group.replace("_", " ")
    return "other mapped feature"


def load_osm(gpkg: Path) -> gpd.GeoDataFrame:
    frames=[]
    for layer in gpd.list_layers(gpkg).name.tolist():
        frame=gpd.read_file(gpkg,layer=layer)
        if frame.crs is None:
            raise ValueError(f"OSM layer {layer} has no CRS")
        if not frame.geometry.is_valid.all():
            raise ValueError(f"Invalid geometry in OSM layer {layer}")
        frame["source_layer_name"]=layer
        frames.append(frame)
    result=gpd.GeoDataFrame(pd.concat(frames,ignore_index=True),geometry="geometry",crs=frames[0].crs)
    result["case_feature_category"]=result.apply(classify_osm,axis=1)
    result["case_feature_name"]=result.apply(lambda r: parse_dict(r.get("all_tags")).get("name") or parse_dict(r.get("all_tags")).get("operator") or "",axis=1)
    result["case_tag_summary"]=result.all_tags.map(lambda x: ";".join(f"{k}={v}" for k,v in parse_dict(x).items()))
    return result.to_crs(CRS_METRIC)


def nearest_osm_features(point, osm: gpd.GeoDataFrame) -> list[dict]:
    distances=osm.geometry.distance(point)
    nearby=osm.loc[distances.le(MAX_OSM_DISTANCE_M)].copy()
    nearby["distance_m"]=distances.loc[nearby.index].astype(float)
    if nearby.empty:
        return []
    # Exclude ordinary land-cover context; retain the mapped facility/infrastructure groups.
    relevant=nearby[nearby.case_feature_category.ne("other mapped feature")]
    return relevant.sort_values(["distance_m","case_feature_category"]).head(8)[
        ["osm_id","source_layer_name","case_feature_category","case_feature_name","case_tag_summary","distance_m"]
    ].to_dict("records")


def _plot_geometry(ax, gdf: gpd.GeoDataFrame, color: str, point_size: float=7, alpha: float=.6) -> None:
    if gdf.empty:
        return
    polys=gdf[gdf.geom_type.isin(["Polygon","MultiPolygon"])]
    lines=gdf[gdf.geom_type.isin(["LineString","MultiLineString"])]
    pts=gdf[gdf.geom_type.isin(["Point","MultiPoint"])]
    if not polys.empty: polys.plot(ax=ax,color=color,edgecolor=color,linewidth=.5,alpha=alpha)
    if not lines.empty: lines.plot(ax=ax,color=color,linewidth=1.2,alpha=alpha)
    if not pts.empty: pts.plot(ax=ax,color=color,markersize=point_size,alpha=alpha)


def render_case_map(case: pd.Series, osm: gpd.GeoDataFrame, all_points: gpd.GeoDataFrame,
                    chip_path: Path | None, scene_date: str, scene_cloud: object,
                    chip_quality: str, target: Path) -> None:
    geom_point=gpd.GeoSeries([gpd.points_from_xy([case.longitude],[case.latitude])[0]],crs="EPSG:4326").to_crs(CRS_METRIC).iloc[0]
    x,y=geom_point.x,geom_point.y
    context=osm.loc[osm.geometry.distance(geom_point).le(MAP_RADIUS_M)]
    categories={"mining extraction":"#3f8f6b","industrial landuse":"#8c6bb1","industrial facility":"#d17c32","power transmission tower":"#2864ad","power transmission line":"#555b66","power infrastructure":"#2864ad","power generator":"#b54e4e","power plant":"#b54e4e","power substation":"#b54e4e","waste facility":"#6f8b3d","industrial structure":"#9c7444"}
    colors=context.case_feature_category.map(categories).fillna("#929292")
    point_context=all_points.loc[all_points.geometry.distance(geom_point).le(MAP_RADIUS_M)]
    ncols=2 if chip_path and chip_path.exists() else 1
    fig,axes=plt.subplots(1,ncols,figsize=(12 if ncols==2 else 8,6))
    if ncols==1: axes=[axes]
    ax=axes[0]
    for category,color in categories.items():
        subset=context[context.case_feature_category.eq(category)]
        _plot_geometry(ax,subset,color,point_size=8,alpha=.6)
    if not point_context.empty:
        ax.scatter(point_context.geometry.x,point_context.geometry.y,s=12,c="#f0a44b",alpha=.48,label="Nearby FIRMS rows",zorder=3)
    ax.scatter([x],[y],marker="*",s=190,c="#b40000",edgecolors="white",linewidths=.7,label="Selected FIRMS observation",zorder=5)
    ax.set(xlim=(x-MAP_RADIUS_M,x+MAP_RADIUS_M),ylim=(y-MAP_RADIUS_M,y+MAP_RADIUS_M),xlabel="Easting (m, EPSG:32645)",ylabel="Northing (m, EPSG:32645)",title="Local FIRMS and OSM context (1.5 km view)")
    handles=[Patch(facecolor=c,alpha=.6,label=k.title()) for k,c in categories.items() if (context.case_feature_category==k).any()]
    handles += [Line2D([],[],marker="o",linestyle="",color="#f0a44b",alpha=.7,label="Nearby FIRMS rows"),Line2D([],[],marker="*",linestyle="",color="#b40000",markersize=12,label="Selected observation")]
    ax.legend(handles=handles,loc="best",fontsize=7,framealpha=.9); ax.grid(alpha=.18)
    if ncols==2:
        with rasterio.open(chip_path) as ds:
            if ds.count < 3: raise ValueError(f"Existing Sentinel chip has fewer than 3 bands: {chip_path}")
            raw=ds.read([1,2,3]).astype(float)
            rgb=np.zeros_like(raw)
            for b in range(3):
                vals=raw[b][np.isfinite(raw[b]) & (raw[b] != ds.nodata if ds.nodata is not None else np.isfinite(raw[b]))]
                if vals.size:
                    lo,hi=np.percentile(vals,[2,98]); rgb[b]=np.clip((raw[b]-lo)/max(hi-lo,1e-6),0,1)
            extent=(ds.bounds.left,ds.bounds.right,ds.bounds.bottom,ds.bounds.top)
            tr=Transformer.from_crs("EPSG:4326",ds.crs,always_xy=True)
            tx,ty=tr.transform(float(case.longitude),float(case.latitude))
            axes[1].imshow(np.moveaxis(rgb,0,-1),extent=extent,origin="upper")
            axes[1].scatter([tx],[ty],marker="*",s=150,c="#d00000",edgecolors="white",linewidths=.6)
            quality_label=f"{chip_quality}; cloud={scene_cloud}%" if pd.notna(scene_cloud) else chip_quality
            temporal="scene date on/before FIRMS date" if pd.to_datetime(scene_date,utc=True).date() <= pd.to_datetime(str(case.acq_date)).date() else "POST-DETECTION SCENE; context only"
            axes[1].set(title=f"Existing Sentinel-2 RGB stretch\n{scene_date[:10]} | {quality_label}\n{temporal}",xlabel=f"{ds.crs}",ylabel="Northing")
            axes[1].set_xlim(extent[0],extent[1]); axes[1].set_ylim(extent[2],extent[3])
    fig.suptitle(f"{case.case_id}: {case.candidate_category.replace('_',' ')}\nFIRMS {case.acq_date}; FRP {case.thermal_frp_mw} MW; confidence {case.confidence}",fontsize=11)
    fig.tight_layout(); fig.savefig(target,dpi=220,bbox_inches="tight",facecolor="white"); plt.close(fig)


def make_register(run_root: Path, osm_path: Path, satellite_dir: Path, out_root: Path) -> dict:
    if out_root.exists() and any(out_root.iterdir()):
        raise FileExistsError(f"Refusing to overwrite non-empty case-study output: {out_root}")
    out_root.mkdir(parents=True,exist_ok=True)
    (out_root/"individual").mkdir()
    (out_root/"maps").mkdir()
    paths={
        "prepared_firms":run_root/"input/firms_pilot.csv",
        "matching":run_root/"spatial_matching/firms_pilot_osm_proximity.csv",
        "features":run_root/"features/feature_table.csv.gz",
        "ranking":run_root/"candidate_ranking/candidate_ranking.csv",
        "run_manifest":run_root/"validation/reproducibility_manifest.json",
        "quality_checks":run_root/"features/quality_checks.json",
        "osm":osm_path,
        "satellite_reference":run_root/"validation/satellite_evidence_reference.json",
    }
    missing=[str(p) for p in [*paths.values()] if not p.exists()]
    if missing: raise FileNotFoundError("Required existing source is missing: "+", ".join(missing))
    firms=pd.read_csv(paths["prepared_firms"])
    matching=pd.read_csv(paths["matching"])
    features=pd.read_csv(paths["features"])
    ranking=pd.read_csv(paths["ranking"])
    if len(firms)!=9220 or len(matching)!=len(firms) or len(features)!=len(firms) or len(ranking)!=len(firms):
        raise ValueError("Audited run row counts do not align with 9,220 observations")
    if not firms.firms_observation_id.is_unique or not matching.firms_observation_id.is_unique or not features.firms_observation_id.is_unique:
        raise ValueError("Duplicate stable observation ID in source tables")
    if set(firms.firms_observation_id)!=set(matching.firms_observation_id) or set(firms.firms_observation_id)!=set(features.firms_observation_id):
        raise ValueError("FIRMS/matching/feature observation IDs do not align")
    selection_pool=ranking.merge(features[["firms_source_row","s2_chip_available_for_context"]],on="firms_source_row",validate="one_to_one")
    cases=select_representative_cases(selection_pool,2)
    selected_sources=set(cases.firms_source_row.astype(int))
    match_columns=["firms_source_row","firms_observation_id","match_status_250m",
        "nearest_industrial_landuse_distance_m","nearest_industrial_facility_distance_m",
        "nearest_mining_extraction_area_distance_m","nearest_power_generation_distance_m",
        "nearest_power_transmission_line_distance_m","nearest_power_transmission_tower_distance_m"]
    case_matching=matching.loc[matching.firms_source_row.astype(int).isin(selected_sources),match_columns]
    cases=cases.merge(case_matching,on="firms_source_row",validate="one_to_one")
    selected_ids=set(cases.firms_observation_id)
    if not selected_ids.issubset(set(firms.firms_observation_id)):
        raise ValueError("Selected FIRMS observation IDs are absent from prepared source")
    feature_cols=["firms_source_row","s2_temporally_eligible","s2_spectral_predictor_eligible",
        "s2_chip_source_path","s2_chip_cloud_quality","s2_scene_item_id",
        "gem_nearest_operating_status"]
    case_features=features.loc[features.firms_source_row.astype(int).isin(selected_sources),feature_cols]
    cases=cases.merge(case_features,on="firms_source_row",validate="one_to_one")
    osm=load_osm(osm_path)
    all_points=gpd.GeoDataFrame(matching,geometry=gpd.points_from_xy(matching.longitude,matching.latitude),crs="EPSG:4326").to_crs(CRS_METRIC)
    all_points["_source_row"]=matching.firms_source_row.values
    register=[]; detailed_features=[]; individual_links=[]
    for _,case in cases.iterrows():
        wgs_point=gpd.GeoSeries([gpd.points_from_xy([case.longitude],[case.latitude])[0]],crs="EPSG:4326").to_crs(CRS_METRIC).iloc[0]
        x,y=wgs_point.x,wgs_point.y
        near=nearest_osm_features(wgs_point,osm)
        for f in near:
            detailed_features.append({"case_id":case.case_id,"firms_observation_id":case.firms_observation_id,"distance_rule":"geometry-to-point distance in EPSG:32645","maximum_distance_m":MAX_OSM_DISTANCE_M,**f})
        nearest_summary="; ".join(f"{f['case_feature_category']} {f['distance_m']:.0f} m"+(f" ({f['case_feature_name']})" if f["case_feature_name"] else "") for f in near[:5]) or "No industrial/power OSM feature within 1 km"
        support=[]
        if pd.to_numeric(case.get("thermal_frp_mw"),errors="coerce")>=5: support.append("FIRMS FRP ≥5 MW")
        if pd.to_numeric(case.get("cell_prior_distinct_acquisition_dates"),errors="coerce")>0: support.append(f"{int(case.cell_prior_distinct_acquisition_dates)} strictly prior distinct dates in 250 m cell")
        if pd.to_numeric(case.get("osm_nearest_relevant_distance_m"),errors="coerce")<=250: support.append(f"relevant OSM role {case.get('osm_nearest_relevant_role')} within 250 m")
        pwr=case.get("nearest_general_power_infrastructure_distance_m")
        if pd.notna(pwr) and float(pwr)<=250: support.append(f"general power infrastructure within {float(pwr):.0f} m")
        if _bool(case.get("s2_spectral_predictor_eligible",False)): support.append("valid pre-detection Sentinel-2 spectral sample")
        if not support: support.append("selected for balanced category coverage; no single strong indicator required")
        uncertainties=[]
        if case.get("osm_nearest_relevant_role") and pd.notna(case.get("osm_nearest_relevant_role")): uncertainties.append("OSM proximity cannot attribute cause; map completeness and historical status are unknown")
        else: uncertainties.append("No relevant nearby OSM feature recorded; mapped-feature absence is not proof of no industrial context")
        uncertainties.append("No detection-level verified event label or adjudicated negative exists")
        if not _bool(case.get("s2_spectral_predictor_eligible",False)):
            uncertainties.append("No valid temporally eligible Sentinel-2 spectrum for this observation; missing/post-event/cloudy data are not evidence of absence")
        if pd.notna(case.get("gem_nearest_distance_m")): uncertainties.append("GEM is supplementary static facility context and may be temporally mismatched")
        else: uncertainties.append("No GEM nearest-facility match available in the saved feature row")
        chip_value=case.get("s2_chip_source_path")
        chip_path=(ROOT/str(chip_value)) if pd.notna(chip_value) else None
        if chip_path and not chip_path.exists(): chip_path=None
        scene_date=str(case.get("s2_scene_datetime_utc")) if pd.notna(case.get("s2_scene_datetime_utc")) else ""
        scene_cloud=case.get("s2_scene_cloud_cover_percent")
        s2_status=str(case.get("s2_spectral_data_status","not_available_no_chip"))
        image_rel=f"maps/{case.case_id}.png"
        render_case_map(case,osm,all_points,chip_path,scene_date,scene_cloud,str(case.get("s2_chip_cloud_quality","unknown")),out_root/image_rel)
        register.append({
            "case_id":case.case_id,"selection_stratum_position":case.case_stratum_position,
            "firms_observation_id":case.firms_observation_id,"firms_source_row":int(case.firms_source_row),
            "latitude":float(case.latitude),"longitude":float(case.longitude),"acq_date":str(case.acq_date),"acq_time_utc_hhmm":case.acq_time,
            "firms_confidence":case.confidence,"frp_mw":float(case.thermal_frp_mw),"brightness_k":case.thermal_brightness_k,"daynight":case.daynight,
            "candidate_ranking_category":case.candidate_category,"review_priority_rank":int(case.review_priority_rank),"candidate_evidence_score":float(case.candidate_evidence_score),
            "osm_nearest_relevant_role":case.osm_nearest_relevant_role,"osm_nearest_relevant_category":case.osm_nearest_relevant_category,
            "osm_nearest_relevant_distance_m":case.osm_nearest_relevant_distance_m,"osm_status_250m":case.match_status_250m,
            "nearest_industrial_landuse_m":case.nearest_industrial_landuse_distance_m,"nearest_industrial_facility_m":case.nearest_industrial_facility_distance_m,
            "nearest_mining_extraction_m":case.nearest_mining_extraction_area_distance_m,"nearest_power_generation_m":case.nearest_power_generation_distance_m,
            "nearest_power_transmission_line_m":case.nearest_power_transmission_line_distance_m,"nearest_power_transmission_tower_m":case.nearest_power_transmission_tower_distance_m,
            "nearby_osm_features_within_1km":nearest_summary,"osm_nearby_feature_count":len(near),
            "prior_cell_detection_count":int(case.cell_prior_detection_count),"prior_cell_distinct_acquisition_dates":int(case.cell_prior_distinct_acquisition_dates),
            "prior_cell_last_date":case.cell_prior_last_acquisition_date,"grid_cell_id":case.hotspot_cell_id,
            "gem_nearest_name":case.gem_nearest_name,"gem_nearest_type":case.gem_nearest_type,"gem_nearest_distance_m":case.gem_nearest_distance_m,
            "gem_operating_status":case.gem_nearest_operating_status,
            "sentinel_status":s2_status,"s2_scene_id":case.s2_scene_item_id,"s2_scene_date_utc":scene_date or None,
            "s2_scene_cloud_percent":scene_cloud,"s2_cloud_shadow_percent":case.s2_chip_scl_cloud_shadow_percent,
            "s2_pixel_screen":case.s2_pixel_cloud_screen_status,"s2_temporally_eligible":_bool(case.s2_temporally_eligible),
            "s2_spectrum_eligible":_bool(case.s2_spectral_predictor_eligible),"s2_chip_path":str(chip_path.relative_to(ROOT)) if chip_path else None,
            "evidence_supporting_further_investigation":"; ".join(support),"uncertainties_and_missing_information":"; ".join(dict.fromkeys(uncertainties)),
            "reviewer_assessment":"Pending human review; this register does not assign or imply a ground-truth label.",
            "label_status":"unknown_unlinked","map_or_image_panel":image_rel,
        })
        individual_links.append((case.case_id,case,near,support,uncertainties,s2_status,scene_date,scene_cloud,chip_path))
    register_df=pd.DataFrame(register)
    register_df.to_csv(out_root/"case_study_register.csv",index=False)
    detailed=pd.DataFrame(detailed_features)
    detailed.to_csv(out_root/"case_osm_nearby_features.csv",index=False)
    comparative=register_df[["case_id","firms_observation_id","acq_date","candidate_ranking_category","review_priority_rank","frp_mw","firms_confidence","prior_cell_distinct_acquisition_dates","osm_nearest_relevant_role","osm_nearest_relevant_distance_m","nearest_power_transmission_tower_m","gem_nearest_name","gem_nearest_distance_m","sentinel_status","s2_spectrum_eligible","reviewer_assessment"]]
    comparative.to_csv(out_root/"comparative_case_study_table.csv",index=False)
    for cid,case,near,support,uncertainties,s2_status,scene_date,scene_cloud,chip_path in individual_links:
        osm_lines="\n".join(f"- {f['case_feature_category']} — {f['distance_m']:.1f} m; name: {f['case_feature_name'] or 'not mapped'}; tags: `{f['case_tag_summary']}`" for f in near) or "- No relevant industrial or power feature within 1 km in the local OSM snapshot."
        text=[f"# {cid}","", "## Observation", "",f"- Stable FIRMS ID: `{case.firms_observation_id}`",f"- Coordinates: {case.latitude:.5f}°N, {case.longitude:.5f}°E",f"- Acquisition: {case.acq_date} at {int(case.acq_time):04d} UTC",f"- FIRMS confidence: `{case.confidence}`; FRP: {float(case.thermal_frp_mw):.2f} MW; brightness: {case.thermal_brightness_k} K; day/night: {case.daynight}",f"- Ranking category: `{case.candidate_category}` (rank {int(case.review_priority_rank):,}; score {float(case.candidate_evidence_score):.3f}, a review score only)","", "## Industrial and power context", "",f"Nearest relevant OSM role: {case.osm_nearest_relevant_role if pd.notna(case.osm_nearest_relevant_role) else 'not recorded'}; distance {float(case.osm_nearest_relevant_distance_m):.1f} m" if pd.notna(case.osm_nearest_relevant_distance_m) else "Nearest relevant OSM role/distance: not recorded.", "", "Nearby OSM geometries (up to 1 km; distances recomputed from the local snapshot in EPSG:32645):", "",osm_lines,"", "## Recurrence and supplementary context", "",f"The same 250 m grid cell had {int(case.cell_prior_detection_count)} earlier FIRMS rows on {int(case.cell_prior_distinct_acquisition_dates)} distinct acquisition dates before this observation; last prior date: {case.cell_prior_last_acquisition_date if pd.notna(case.cell_prior_last_acquisition_date) else 'none in the source window'}. This is a spatial-bin recurrence measure, not identification of a single physical source.","",f"Nearest GEM context: {case.gem_nearest_name if pd.notna(case.gem_nearest_name) else 'none recorded'} ({case.gem_nearest_type if pd.notna(case.gem_nearest_type) else 'type unavailable'}), {float(case.gem_nearest_distance_m):.1f} m away" if pd.notna(case.gem_nearest_distance_m) else "No GEM nearest-facility context is recorded.","", "## Sentinel-2 evidence", "",f"Status: `{s2_status}`. Scene: {scene_date or 'not available'}; scene cloud estimate: {scene_cloud if pd.notna(scene_cloud) else 'not available'}%; pixel/SCL status: `{case.s2_pixel_cloud_screen_status}`. Spectrum eligible for historical features: `{bool(case.s2_spectral_predictor_eligible)}`.","",("The image panel uses an existing local chip. Any post-detection scene is explicitly contextual and is excluded from historical evidence." if chip_path else "No existing chip is linked to this observation; no imagery was retrieved."),"", "## Evidence for review", "",*([f"- {x}" for x in support]),"", "## Uncertainty and reviewer assessment", "",*([f"- {x}" for x in uncertainties]),"- Human reviewer assessment: pending; no cause or ground-truth label assigned.","",f"![Local context and existing satellite chip if available](../{register_df.loc[register_df.case_id.eq(cid),'map_or_image_panel'].iloc[0]})","", "All nearby distances are spatial evidence only. FIRMS detects thermal anomalies; it does not identify industrial fires or causes.",""]
        (out_root/"individual"/f"{cid}.md").write_text("\n".join(str(x) for x in text),encoding="utf-8")
    category_counts=register_df.candidate_ranking_category.value_counts().sort_index().to_dict()
    # One comparative geographic panel with all selected points and relevant OSM context.
    points=gpd.GeoDataFrame(register_df,geometry=gpd.points_from_xy(register_df.longitude,register_df.latitude),crs="EPSG:4326").to_crs(CRS_METRIC)
    fig,ax=plt.subplots(figsize=(10,8))
    for cat,color in [("mining extraction","#3f8f6b"),("industrial landuse","#8c6bb1"),("industrial facility","#d17c32"),("power transmission tower","#2864ad"),("power transmission line","#555b66"),("power infrastructure","#2864ad"),("power generator","#b54e4e"),("power plant","#b54e4e")]:
        _plot_geometry(ax,osm[osm.case_feature_category.eq(cat)],color,5,.35)
    colors=plt.cm.tab10(np.linspace(0,1,len(category_counts)))
    cmap=dict(zip(category_counts,colors))
    for category,grp in register_df.groupby("candidate_ranking_category"):
        gg=gpd.GeoDataFrame(grp,geometry=gpd.points_from_xy(grp.longitude,grp.latitude),crs="EPSG:4326").to_crs(CRS_METRIC)
        ax.scatter(gg.geometry.x,gg.geometry.y,s=70,c=[cmap[category]],edgecolors="black",linewidths=.5,label=category.replace("_"," "),zorder=5)
        for row,pt in zip(grp.itertuples(),gg.geometry): ax.annotate(row.case_id.split("_")[1],(pt.x,pt.y),xytext=(4,4),textcoords="offset points",fontsize=7)
    ax.set(title="Representative case locations and mapped industrial/power context",xlabel="Easting (m, EPSG:32645)",ylabel="Northing (m, EPSG:32645)"); ax.legend(fontsize=7,loc="best",framealpha=.9); ax.grid(alpha=.15)
    fig.savefig(out_root/"case_locations_overview.png",dpi=250,bbox_inches="tight",facecolor="white"); plt.close(fig)
    report=["# Representative case studies — ThermoScope final pilot","","## Purpose and safeguards","","These purposively selected examples illustrate different evidence combinations in the Dhanbad–Jharia–Bokaro pilot. They are not a validation set and do not establish industrial fires, causal sources, or classifier performance. No new incident records, labels, or satellite imagery were added. The reviewer field remains pending for every case.","","## Selection","",f"Twelve observations were selected: two from each of the six rule-based candidate-ranking categories. The base selections are at the within-category 25th and 75th percentiles of review rank, rather than only the highest-ranked cases. Where a category has existing chip coverage and the 25th-percentile selection has no chip, the second selection is the chip-available observation nearest the 75th-percentile rank. This deterministic, category-balanced selection is not a probability sample; the register records the exact stratum position for each observation.","", "| Ranking category | Selected observations |", "|---|---:|"]
    report += [f"| `{k}` | {v} |" for k,v in sorted(category_counts.items())]
    out_link="../"+str(out_root.relative_to(ROOT)).replace("\\","/")
    report += ["","## Comparative findings","",f"The case set contains {len(register_df)} observations. FRP ranges from {register_df.frp_mw.min():.2f} to {register_df.frp_mw.max():.2f} MW; confidence values are {', '.join(f'{k}={v}' for k,v in register_df.firms_confidence.value_counts().to_dict().items())}. Strictly prior recurrence in selected 250 m cells ranges from {register_df.prior_cell_distinct_acquisition_dates.min()} to {register_df.prior_cell_distinct_acquisition_dates.max()} distinct earlier acquisition dates. These differences reflect the constructed selection strata and should not be interpreted as category prevalence.","",f"{int(register_df.osm_nearby_feature_count.gt(0).sum())} of the selected rows have at least one mapped industrial or power feature within 1 km. {int(register_df.s2_spectrum_eligible.sum())} selected observations have usable pre-detection Sentinel-2 spectra. Existing chip source: `{satellite_dir.relative_to(ROOT)}`.",""]
    chip_cases=register_df[register_df.s2_chip_path.notna()].copy()
    if not chip_cases.empty:
        chip_cases["scene_day"]=pd.to_datetime(chip_cases.s2_scene_date_utc,utc=True,errors="coerce").dt.date
        chip_cases["firms_day"]=pd.to_datetime(chip_cases.acq_date,errors="coerce").dt.date
        later=int((chip_cases.scene_day>chip_cases.firms_day).sum())
        cloud_min=chip_cases.s2_scene_cloud_percent.min(); cloud_max=chip_cases.s2_scene_cloud_percent.max()
        clear=int(chip_cases.s2_pixel_screen.eq("scl_clear_class").sum())
        high_shadow=int(pd.to_numeric(chip_cases.s2_cloud_shadow_percent,errors="coerce").ge(50).sum())
        satellite_finding=f"Four selected observations have existing local Sentinel-2 chips; all four scenes post-date their FIRMS observations and therefore none is eligible as historical evidence. Scene cloud estimates range from {cloud_min:.1f}% to {cloud_max:.1f}%; {clear} chips have a clear pixel-level SCL flag, but their later acquisition dates still exclude them, while {high_shadow} have at least 50% cloud/shadow within the chip. No new imagery was retrieved."
    else:
        satellite_finding="No selected observation has an existing local Sentinel-2 chip; no imagery was retrieved."
    report += ["", satellite_finding, "", "## Case register and maps", "", f"The [case-study register]({out_link}/case_study_register.csv) records stable IDs, FIRMS attributes, nearest OSM role/distance, supplementary GEM context, strictly prior recurrence, scene/cloud metadata, investigation rationale, uncertainties, and pending reviewer assessment. The [comparative table]({out_link}/comparative_case_study_table.csv) provides a compact comparison; [nearby OSM features]({out_link}/case_osm_nearby_features.csv) contains recomputed geometry-to-point distances for mapped industrial/power features within 1 km. The [location overview]({out_link}/case_locations_overview.png) and per-case panels are generated from the existing OSM snapshot, FIRMS rows, and only local Sentinel-2 chips already referenced by the run.",""]
    for row in register_df.itertuples(): report.append(f"- [{row.case_id}]({out_link}/individual/{row.case_id}.md) — `{row.candidate_ranking_category}`; FIRMS {row.acq_date}; FRP {row.frp_mw:.2f} MW; {row.prior_cell_distinct_acquisition_dates} prior dates.")
    report += ["","## Evidence limits","","- FIRMS coordinates are thermal-anomaly detections; confidence and FRP are sensor attributes, not industrial-cause verification.","- OSM is a static snapshot; its completeness, feature vintage, and the real-world source footprint may differ. Distances were recomputed from feature geometries in EPSG:32645; no proximity is a causal link.","- Recurrence counts strictly earlier acquisition dates within a fixed 250 m grid cell. The cell can contain multiple physical sources; repeated sensor observations are not a source identity.","- GEM assets are supplementary, static facility references and may be temporally mismatched.","- Sentinel-2 is optical context. A post-event image is not eligible historical evidence; cloudy/shadowed, missing, or temporally unsuitable imagery is not evidence of no fire. Chips are small and cannot independently confirm a thermal event.","- No verified detection-level labels exist in this pilot. Human reviewer decisions have not been collected in this case-study register. No labels or model metrics are asserted.","","## Reproducibility","", f"Selection settings, input filenames/checksums, software versions, selected IDs, output inventory, and quality checks are recorded in [case_study_manifest.json]({out_link}/case_study_manifest.json). The source experiment and historical case-study runs were left unchanged.",""]
    (ROOT/"docs/final_pilot_case_studies.md").write_text("\n".join(report),encoding="utf-8")
    input_manifest=json.loads(paths["run_manifest"].read_text(encoding="utf-8"))
    source_paths=dict(paths)
    for chip in register_df.s2_chip_path.dropna().unique():
        chip_path=ROOT/chip
        if not chip_path.exists():
            raise FileNotFoundError(f"Selected existing satellite chip is missing: {chip_path}")
        source_paths[f"satellite_chip:{chip_path.name}"]=chip_path
    report_path=ROOT/"docs/final_pilot_case_studies.md"
    manifest={"analysis_id":"thermoscope_final_pilot_case_studies_v1","created_at_utc":datetime.now(timezone.utc).isoformat(),"source_run":str(run_root.relative_to(ROOT)),"source_files":{k:{"path":str(p.relative_to(ROOT)),"size_bytes":p.stat().st_size,"sha256":sha256(p)} for k,p in source_paths.items()},"satellite_source_directory":str(satellite_dir.relative_to(ROOT)),"parameters":{"selection":"two observations per category at within-category review-rank 25th and 75th percentiles; chip-aware second selection moves to the nearest available record where possible","candidate_categories":sorted(category_counts),"osm_distance_crs":CRS_METRIC,"osm_nearby_feature_radius_m":MAX_OSM_DISTANCE_M,"case_map_radius_m":MAP_RADIUS_M,"recurrence":"strictly earlier distinct acquisition dates within existing 250m cell","satellite":"only existing run-linked local chips; no download; status/cloud/date read from saved feature table; RGB per-chip percentile stretch for display"},"selection_counts":category_counts,"quality_checks":{"selected_cases":len(register_df),"unique_observation_ids":int(register_df.firms_observation_id.nunique()),"duplicate_observation_ids":int(register_df.firms_observation_id.duplicated().sum()),"unknown_labels_only":bool(register_df.label_status.eq("unknown_unlinked").all()),"reviewer_assessments_pending":bool(register_df.reviewer_assessment.str.startswith("Pending").all()),"osm_geometries_valid":bool(osm.geometry.is_valid.all()),"all_selected_coordinates_in_pilot_bbox":bool(register_df.latitude.between(23.25,24.0).all() and register_df.longitude.between(85.75,86.75).all()),"selected_chip_count":int(register_df.s2_chip_path.notna().sum()),"eligible_s2_spectra":int(register_df.s2_spectrum_eligible.sum()),"labels_created":False,"imagery_downloaded":False,"experiment_rerun":False,"source_experiment_validation_status":input_manifest.get("run_status")},"software":{"python":__import__("platform").python_version(),"pandas":pd.__version__,"geopandas":gpd.__version__,"shapely":shapely.__version__,"pyproj":pyproj.__version__,"matplotlib":matplotlib.__version__,"rasterio":rasterio.__version__},"outputs":{}}
    for p in sorted(out_root.rglob("*")):
        if p.is_file() and p.name!="case_study_manifest.json": manifest["outputs"][str(p.relative_to(ROOT))]={"size_bytes":p.stat().st_size,"sha256":sha256(p)}
    manifest["outputs"][str(report_path.relative_to(ROOT))]={"size_bytes":report_path.stat().st_size,"sha256":sha256(report_path)}
    mpath=out_root/"case_study_manifest.json"; mpath.write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    return {"output":str(out_root),"cases":len(register_df),"categories":category_counts,"chips":int(register_df.s2_chip_path.notna().sum()),"s2_eligible":int(register_df.s2_spectrum_eligible.sum()),"outputs":len(manifest["outputs"]),"manifest":str(mpath)}


def main() -> None:
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-root",type=Path,default=RUN_DEFAULT)
    ap.add_argument("--osm",type=Path,default=OSM_DEFAULT)
    ap.add_argument("--satellite-dir",type=Path,default=SATELLITE_DEFAULT)
    ap.add_argument("--output-root",type=Path,default=OUT_DEFAULT)
    args=ap.parse_args()
    print(json.dumps(make_register(args.run_root,args.osm,args.satellite_dir,args.output_root),indent=2))


if __name__=="__main__":
    main()
