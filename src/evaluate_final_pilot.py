"""Evaluate saved ThermoScope final-pilot evidence without rerunning processing."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/"data/processed/final_pilot_experiment/run_001"
CASE=ROOT/"outputs/final_pilot/case_studies/run_20261116T_case_review_final"
OUT=ROOT/"outputs/final_pilot"
THRESHOLDS=(100,250,500,1000)
CATEGORIES=(
    "persistent_thermal_with_nearby_relevant_industrial_context",
    "persistent_thermal_near_general_power_infrastructure_only",
    "persistent_thermal_without_nearby_relevant_osm_context",
    "elevated_thermal_with_nearby_relevant_industrial_context",
    "elevated_thermal_without_nearby_relevant_osm_context",
    "other_thermal_observation_review",
)


def classify_at_thresholds(ranking: pd.DataFrame, thresholds=THRESHOLDS) -> pd.DataFrame:
    """Reapply fixed FRP/recurrence rules while varying industrial/power radii."""
    needed={"candidate_category","thermal_frp_mw","cell_prior_distinct_acquisition_dates",
            "osm_nearest_relevant_distance_m","nearest_general_power_infrastructure_distance_m"}
    if not needed.issubset(ranking.columns):
        raise ValueError(f"Ranking input missing: {sorted(needed-set(ranking.columns))}")
    frp=pd.to_numeric(ranking.thermal_frp_mw,errors="coerce")
    prior=pd.to_numeric(ranking.cell_prior_distinct_acquisition_dates,errors="coerce").fillna(0)
    relevant=pd.to_numeric(ranking.osm_nearest_relevant_distance_m,errors="coerce")
    power=pd.to_numeric(ranking.nearest_general_power_infrastructure_distance_m,errors="coerce")
    persistence=prior.ge(3)
    high=frp.ge(5)
    outputs=[]
    for threshold in thresholds:
        near_rel=relevant.le(threshold).fillna(False)
        near_power=power.le(threshold).fillna(False)
        category=np.select(
            [persistence&near_rel,persistence&near_power&~near_rel,persistence,high&near_rel,high],
            [CATEGORIES[0],CATEGORIES[1],CATEGORIES[2],CATEGORIES[3],CATEGORIES[4]],
            default=CATEGORIES[5],
        )
        outputs.append(pd.DataFrame({"threshold_m":threshold,"candidate_category":category,
                                     "baseline_category":ranking.candidate_category.astype(str)}))
    result=pd.concat(outputs,ignore_index=True)
    if len(result)!=len(ranking)*len(thresholds):
        raise AssertionError("Threshold evaluation changed the number of detection-threshold rows")
    return result


def build_tables(run:Path,case_dir:Path,output:Path,write_files:bool=True) -> dict:
    p={
        "firms":run/"input/firms_pilot.csv",
        "firms_quality":run/"input/firms_pilot.csv.quality.json",
        "matching":run/"spatial_matching/firms_pilot_osm_proximity.csv",
        "threshold_summary":run/"spatial_matching/distance_threshold_summary.csv",
        "role_coverage":run/"spatial_matching/role_coverage_by_threshold.csv",
        "features":run/"features/feature_table.csv.gz",
        "feature_missingness":run/"features/feature_missingness.csv",
        "feature_quality":run/"features/quality_checks.json",
        "ranking":run/"candidate_ranking/candidate_ranking.csv",
        "category_counts":run/"candidate_ranking/category_counts.csv",
        "ranking_rules":run/"candidate_ranking/rule_definitions.json",
        "case_register":case_dir/"case_study_register.csv",
        "case_manifest":case_dir/"case_study_manifest.json",
        "analysis_manifest":OUT/"results_manifest.json",
    }
    missing=[str(x) for x in p.values() if not x.is_file()]
    if missing: raise FileNotFoundError("Required verified evaluation input missing: "+", ".join(missing))
    firms=pd.read_csv(p["firms"])
    matching=pd.read_csv(p["matching"])
    features=pd.read_csv(p["features"])
    ranking=pd.read_csv(p["ranking"])
    cases=pd.read_csv(p["case_register"])
    thresholds=pd.read_csv(p["threshold_summary"])
    role_coverage=pd.read_csv(p["role_coverage"])
    missingness=pd.read_csv(p["feature_missingness"])
    firms_q=json.loads(p["firms_quality"].read_text(encoding="utf-8"))
    feature_q=json.loads(p["feature_quality"].read_text(encoding="utf-8"))
    rules=json.loads(p["ranking_rules"].read_text(encoding="utf-8"))
    case_manifest=json.loads(p["case_manifest"].read_text(encoding="utf-8"))
    run_manifest=json.loads((run/"validation/reproducibility_manifest.json").read_text(encoding="utf-8"))
    n=len(firms)
    if n!=9220 or any(len(x)!=n for x in [matching,features,ranking]):
        raise ValueError("Source stage counts do not match the audited 9,220-row pilot")
    if not firms.firms_observation_id.is_unique or not matching.firms_observation_id.is_unique or not features.firms_observation_id.is_unique:
        raise ValueError("Duplicate stable FIRMS observation IDs found")
    if set(firms.firms_observation_id)!=set(matching.firms_observation_id) or set(firms.firms_observation_id)!=set(features.firms_observation_id):
        raise ValueError("Observation ID sets do not align across FIRMS, matching, and features")
    if set(ranking.candidate_category.dropna().unique())!=set(CATEGORIES):
        raise ValueError("Ranking categories differ from the documented six-category rule set")
    if not ranking.firms_detection_label.astype(str).eq("unknown_unlinked").all():
        raise ValueError("Unexpected non-unknown label in evidence-only ranking input")
    if not (features.distance_crs.astype(str).eq("EPSG:32645").all()):
        raise ValueError("Feature table contains unexpected distance CRS")
    if not feature_q.get("temporal_leakage_check","").startswith("passed"):
        raise ValueError("Saved recurrence leakage check is not passed")
    if len(cases)!=12 or not cases.firms_observation_id.is_unique:
        raise ValueError("Case-study register is not the expected 12 unique records")

    sensitivity=classify_at_thresholds(ranking)
    by_threshold=(sensitivity.groupby(["threshold_m","candidate_category"],dropna=False)
                  .size().rename("detections").reset_index())
    baseline=sensitivity[sensitivity.threshold_m.eq(250)].set_index(sensitivity[sensitivity.threshold_m.eq(250)].index)["candidate_category"]
    source_baseline=ranking.candidate_category.astype(str).reset_index(drop=True)
    if not baseline.reset_index(drop=True).equals(source_baseline):
        raise AssertionError("Reconstructed 250 m category counts do not reproduce saved ranking categories")
    baseline_by_source=ranking.candidate_category.astype(str).to_numpy()
    change_rows=[]
    for t,part in sensitivity.groupby("threshold_m",sort=True):
        changed=part.candidate_category.to_numpy()!=baseline_by_source
        change_rows.append({"threshold_m":int(t),
                            "detections_reclassified_vs_250m":int(changed.sum()),
                            "percent_reclassified_vs_250m":100*changed.mean(),
                            "ranking_rule_note":"FRP>=5 MW and >=3 strictly prior dates held fixed; relevant-context and power-only radius changed together; ranking scores held fixed"})
    sensitivity_table=by_threshold.merge(pd.DataFrame(change_rows),on="threshold_m",how="left")
    if write_files:
        sensitivity_table.to_csv(output/"candidate_category_threshold_sensitivity.csv",index=False)

    rows=[]
    def add(domain,metric,value,unit="count",denominator="",interpretation="",source=""):
        rows.append({"domain":domain,"metric":metric,"value":value,"unit":unit,
                     "denominator":denominator,"interpretation":interpretation,"source":source})
    qsrc=firms_q["sources"]
    add("FIRMS","observations",n,source="input/firms_pilot.csv")
    add("FIRMS","acquisition_dates",int(pd.to_datetime(firms.acq_date).nunique()),"dates",n,"Distinct dates with at least one retained observation","input/firms_pilot.csv")
    add("FIRMS","period_start",str(firms.acq_date.min()),"date",interpretation="Beginning of observed source window; not proof of complete historical coverage",source="input/firms_pilot.csv")
    add("FIRMS","period_end",str(firms.acq_date.max()),"date",interpretation="End of observed source window",source="input/firms_pilot.csv")
    add("FIRMS","archive_region_rows",int(qsrc["archive"]["region_rows_before_deduplication"]),"rows",n,"Archive contribution to the prepared dataset",source="input/firms_pilot.csv.quality.json")
    add("FIRMS","NRT_region_rows",int(qsrc["nrt"]["region_rows_before_deduplication"]),"rows",n,"NRT contribution to the prepared dataset",source="input/firms_pilot.csv.quality.json")
    add("FIRMS","archive_NRT_overlap_rows",int(firms_q["deduplication"]["cross_source_overlap_rows"]),"rows",n,"No overlap was recorded in the available source exports",source="input/firms_pilot.csv.quality.json")
    add("FIRMS","duplicate_input_rows_removed",int(firms_q["deduplication"]["duplicate_input_rows_removed"]),"rows",n,"No within-source duplicates removed in pilot bounds",source="input/firms_pilot.csv.quality.json")
    add("FIRMS","invalid_or_missing_coordinates",int(firms_q["coordinate_validation"]["invalid_or_missing_coordinate_rows_excluded"]),"rows",n,"All retained records passed coordinate validation",source="input/firms_pilot.csv.quality.json")
    add("FIRMS","missing_type_attribute",int(firms.type.isna().sum()),"rows",n,"NRT export schema did not provide FIRMS type; field is blank for those records",source="input/firms_pilot.csv")
    for conf,count in firms.confidence.fillna("missing").astype(str).str.lower().value_counts().sort_index().items():
        add("FIRMS",f"confidence_{conf}_count",int(count),"rows",n,"FIRMS sensor confidence attribute; not a cause label",source="input/firms_pilot.csv")

    add("Spatial matching","matched_observation_rows",len(matching),"rows",n,"One output row per FIRMS observation",source="spatial_matching/firms_pilot_osm_proximity.csv")
    add("Spatial matching","unique_observation_ids",int(matching.firms_observation_id.nunique()),"IDs",n,"No duplicate IDs in matching output",source="spatial_matching/firms_pilot_osm_proximity.csv")
    add("Spatial matching","distance_crs",str(matching.distance_crs.dropna().unique().tolist()),"CRS",interpretation="Local pilot UTM zone used for metre-based distance calculations",source="spatial_matching/firms_pilot_osm_proximity.csv")
    osm_summary=json.loads((run/"spatial_matching/summary.json").read_text(encoding="utf-8"))
    add("OSM","source_features_available",int(osm_summary["osm_features_available_in_relevant_source_gpkg_or_tile_reads"]),"features",interpretation="Source snapshot feature count",source="spatial_matching/summary.json")
    add("OSM","features_used_for_matching",int(osm_summary["osm_features_used"]),"features",interpretation="127 context features were not used as industrial-proximity features",source="spatial_matching/summary.json")
    add("OSM","context_only_features_excluded_from_industrial_match",int(osm_summary["osm_context_only_features_not_used_for_industrial_proximity"]),"features",interpretation="Vegetation/context features were retained as context, not treated as industrial facilities",source="spatial_matching/summary.json")
    add("OSM","invalid_or_empty_features_filtered",int(osm_summary["osm_invalid_or_empty_filtered"]),"features",interpretation="No invalid/empty filtered features in the recorded run",source="spatial_matching/summary.json")
    add("OSM","missing_nearest_relevant_role",int(features.osm_nearest_relevant_role.isna().sum()),"detections",n,"No relevant role recorded; this is not evidence that no facility exists",source="features/feature_table.csv.gz")
    add("OSM","missing_nearest_relevant_feature_id",int(features.osm_nearest_relevant_feature_id.isna().sum()),"detections",n,"Relevant-role distances are not fully traceable to a stable feature ID in this output field",source="features/feature_table.csv.gz")
    for _,r in thresholds.iterrows():
        for metric in ["proximity_candidate_unambiguous","ambiguous_proximity","unknown_no_relevant_feature_within_threshold"]:
            add("OSM distance sensitivity",f"{int(r.threshold_m)}m_{metric}",int(r[metric]),"detections",n,"Threshold changes evidence coverage; it does not verify source attribution",source="spatial_matching/distance_threshold_summary.csv")
    role250=role_coverage[role_coverage.threshold_m.eq(250)]
    for role in ["mining_extraction_area","industrial_landuse","industrial_facility","power_transmission_line","power_transmission_tower"]:
        value=role250.loc[role250.feature_role.eq(role),"detections_with_any_feature_in_role"]
        add("OSM role availability",f"detections_with_{role}_within_250m",int(value.iloc[0]) if len(value) else 0,"detections",n,"Role counts overlap; transmission roles remain general infrastructure",source="spatial_matching/role_coverage_by_threshold.csv")

    cell=features.groupby("hotspot_cell_id",dropna=False).agg(n_rows=("firms_observation_id","size"),dates=("acq_date","nunique"))
    add("Recurrence","250m_cells",int(len(cell)),"cells",interpretation="Cells are projected grid bins, not source identities",source="features/feature_table.csv.gz")
    add("Recurrence","cells_seen_on_multiple_dates",int(cell.dates.gt(1).sum()),"cells",int(len(cell)),"May contain multiple physical sources",source="features/feature_table.csv.gz")
    add("Recurrence","detections_with_at_least_3_strictly_prior_dates",int(pd.to_numeric(ranking.cell_prior_distinct_acquisition_dates).ge(3).sum()),"detections",n,"Past-only recurrence flag threshold used by ranking",source="candidate_ranking/candidate_ranking.csv")
    add("Recurrence","missing_prior_distinct_date_feature",int(features.cell_prior_distinct_acquisition_dates.isna().sum()),"rows",n,"Feature is explicit zero when no earlier dates exist",source="features/feature_table.csv.gz")
    add("Recurrence","missing_prior_last_date",int(features.cell_prior_last_acquisition_date.isna().sum()),"rows",n,"Expected when no earlier date exists",source="features/feature_table.csv.gz")
    add("Recurrence","maximum_prior_distinct_dates",int(pd.to_numeric(features.cell_prior_distinct_acquisition_dates).max()),"dates",interpretation="Within available 2026 observation window only",source="features/feature_table.csv.gz")

    sat=feature_q["sentinel2"]
    for key,label in [("rows_with_chip_for_context","chip_context"),("rows_with_temporally_eligible_scene","temporally_eligible_scene"),("rows_with_valid_causal_spectral_samples","usable_pre_detection_spectra"),("rows_with_post_detection_imagery_withheld","post_detection_scene_withheld"),("rows_with_heavy_chip_cloud_shadow","heavy_cloud_shadow_chip"),("rows_with_cloud_or_unverifiable_pixel_screen","cloud_or_unverified_pixel_screen"),("rows_with_clear_pixel_level_scl","clear_pixel_level_scl_flag")]:
        count=int(sat[key]); add("Sentinel-2",label,count,"detections",n,f"{100*count/n:.3f}% of pilot rows; imagery remains optical context",source="features/quality_checks.json")
    add("Sentinel-2","band_value_missing_rows",int(features.s2_b04_red_dn.isna().sum()),"rows",n,"Same missing count for B03/B02/B11; absent values are not evidence of no thermal activity",source="features/feature_table.csv.gz")

    cat_summary=ranking.groupby("candidate_category").agg(
        detections=("firms_source_row","size"),unique_cells=("hotspot_cell_id","nunique"),
        median_frp_mw=("thermal_frp_mw","median"),median_prior_dates=("cell_prior_distinct_acquisition_dates","median"),
        relevant_within_250m=("osm_relevant_context_within_250m","sum"),
        power_only_within_250m=("power_infrastructure_only_context_flag","sum"),
        ambiguous_250m=("osm_match_ambiguous_flag","sum"),
        valid_s2=("sentinel2_clear_pre_detection_spectrum_available","sum"),
    ).reindex(CATEGORIES)
    for category,r in cat_summary.iterrows():
        for metric in cat_summary.columns:
            add("Candidate category",f"{category}__{metric}",r[metric],"count" if metric in ["detections","unique_cells","relevant_within_250m","power_only_within_250m","ambiguous_250m","valid_s2"] else "MW" if metric=="median_frp_mw" else "dates",int(r.detections),"Evidence-combination bucket, not verified source class",source="candidate_ranking/candidate_ranking.csv")
    sensitivity_summary=sensitivity_table.groupby("threshold_m").first()
    for threshold,r in sensitivity_summary.iterrows():
        add("Candidate ranking sensitivity",f"threshold_{int(threshold)}m_reclassified_from_250m",int(r.detections_reclassified_vs_250m),"detections",n,"Counterfactual category re-binning; score and non-spatial rules held fixed",source="candidate_category_threshold_sensitivity.csv")
        add("Candidate ranking sensitivity",f"threshold_{int(threshold)}m_percent_reclassified_from_250m",float(r.percent_reclassified_vs_250m),"percent",n,"Not model error; sensitivity to the chosen spatial rule threshold",source="candidate_category_threshold_sensitivity.csv")

    add("Representative cases","selected_observations",len(cases),"cases",interpretation="Purposive category-balanced illustration, not a random or representative population sample",source="case_studies/case_study_register.csv")
    add("Representative cases","cases_with_relevant_or_power_osm_feature_within_1km",int(cases.osm_nearby_feature_count.gt(0).sum()),"cases",len(cases),"OSM context is evidence only",source="case_studies/case_study_register.csv")
    add("Representative cases","cases_with_existing_s2_chip",int(cases.s2_chip_path.notna().sum()),"cases",len(cases),"Some chip files are shared across selected observations",source="case_studies/case_study_register.csv")
    add("Representative cases","cases_with_valid_pre_detection_s2_spectra",int(cases.s2_spectrum_eligible.sum()),"cases",len(cases),"No selected case has temporally eligible spectra",source="case_studies/case_study_register.csv")
    add("Representative cases","cases_with_pending_reviewer_assessment",int(cases.reviewer_assessment.str.startswith("Pending").sum()),"cases",len(cases),"No human assessment or labels were created",source="case_studies/case_study_register.csv")
    case_group=cases.assign(case_group=np.select([cases.candidate_ranking_category.str.startswith("persistent"),cases.candidate_ranking_category.str.startswith("elevated")], ["persistent review categories","elevated review categories"], default="other review category"))
    for group,g in case_group.groupby("case_group"):
        add("Representative case comparison",f"{group}__median_frp_mw",float(g.frp_mw.median()),"MW",len(g),"Descriptive selected-case statistic only",source="case_studies/case_study_register.csv")
        add("Representative case comparison",f"{group}__median_prior_dates",float(g.prior_cell_distinct_acquisition_dates.median()),"dates",len(g),"Strictly prior dates within selected cells",source="case_studies/case_study_register.csv")
    add("Labels and evaluation","verified_detection_labels",0,"labels",n,"No ground-truth labels; classification accuracy cannot be estimated",source="features/quality_checks.json and case_study_register.csv")
    add("Labels and evaluation","supervised_metrics_reported",0,"metrics",interpretation="No labels and no classifier; do not interpret this as zero model performance",source="candidate_ranking/validation.json")

    summary=pd.DataFrame(rows)
    if write_files:
        summary.to_csv(output/"evaluation_summary.csv",index=False)
    return {"paths":p,"firms":firms,"matching":matching,"features":features,"ranking":ranking,"cases":cases,
            "thresholds":thresholds,"role_coverage":role_coverage,"missingness":missingness,"quality":feature_q,
            "rules":rules,"summary":summary,"sensitivity":sensitivity_table,"cat_summary":cat_summary,
            "case_group":case_group,"case_manifest":case_manifest,"run_manifest":run_manifest}


def create_figures(data:dict,figdir:Path)->None:
    if not figdir.exists(): figdir.mkdir(parents=True)
    targets=[figdir/"09_evaluation_threshold_sensitivity.png",figdir/"10_candidate_category_evidence_comparison.png",figdir/"11_case_study_evidence_scatter.png"]
    exists=[str(p) for p in targets if p.exists()]
    if exists: raise FileExistsError("Refusing to overwrite evaluation figure(s): "+", ".join(exists))
    t=data["thresholds"].sort_values("threshold_m")
    sens=data["sensitivity"]
    fig,(ax1,ax2)=plt.subplots(1,2,figsize=(14,6))
    x=np.arange(len(t)); bottom=np.zeros(len(t))
    for col,label,color in [("proximity_candidate_unambiguous","Unambiguous proximity candidate","#388c6d"),("ambiguous_proximity","Ambiguous proximity","#e0a23b"),("unknown_no_relevant_feature_within_threshold","No relevant feature within threshold","#8994a3")]:
        ax1.bar(x,t[col],bottom=bottom,label=label,color=color); bottom+=t[col].to_numpy()
    ax1.set_xticks(x,[f"{int(v)} m" if v<1000 else "1 km" for v in t.threshold_m]); ax1.set(title="Observed OSM evidence status by distance",ylabel="FIRMS observations",xlabel="Threshold"); ax1.legend(fontsize=8,frameon=False); ax1.grid(axis="y",alpha=.2)
    pivot=sens.pivot(index="candidate_category",columns="threshold_m",values="detections").reindex(CATEGORIES)
    im=ax2.imshow(pivot.to_numpy(),aspect="auto",cmap="Blues")
    ax2.set_yticks(range(len(pivot)),[c.replace("_"," ") for c in pivot.index],fontsize=7); ax2.set_xticks(range(len(pivot.columns)),[f"{int(v)} m" if v<1000 else "1 km" for v in pivot.columns]); ax2.set(title="Counterfactual candidate-category counts",xlabel="Spatial rule threshold")
    for i in range(pivot.shape[0]):
        for j in range(pivot.shape[1]): ax2.text(j,i,f"{int(pivot.iloc[i,j]):,}",ha="center",va="center",fontsize=7,color="black")
    fig.colorbar(im,ax=ax2,label="Detections"); fig.suptitle("Distance sensitivity changes evidence buckets, not validated classes",fontsize=12); fig.tight_layout(); fig.savefig(targets[0],dpi=250,bbox_inches="tight",facecolor="white"); plt.close(fig)

    cat=data["cat_summary"].reset_index()
    labels=[v.replace("_"," ") for v in cat.candidate_category]
    fig,(a1,a2,a3)=plt.subplots(1,3,figsize=(16,6))
    colors=["#537b9b" if c.startswith("persistent") else "#d88939" if c.startswith("elevated") else "#87939d" for c in cat.candidate_category]
    order=np.arange(len(cat))
    a1.barh(order,cat.detections,color=colors); a1.set_yticks(order,labels,fontsize=7); a1.invert_yaxis(); a1.set(title="Category population",xlabel="FIRMS observations")
    a2.barh(order,cat.median_frp_mw,color=colors); a2.set_yticks(order,labels,fontsize=7); a2.invert_yaxis(); a2.set(title="Median FRP",xlabel="MW")
    a3.barh(order,cat.median_prior_dates,color=colors); a3.set_yticks(order,labels,fontsize=7); a3.invert_yaxis(); a3.set(title="Median strictly prior dates",xlabel="Dates")
    for ax in [a1,a2,a3]: ax.grid(axis="x",alpha=.2)
    fig.suptitle("Observed evidence characteristics by rule-based review category",fontsize=12); fig.tight_layout(); fig.savefig(targets[1],dpi=250,bbox_inches="tight",facecolor="white"); plt.close(fig)

    cases=data["cases"]
    color_map={cat:plt.cm.tab10(i%10) for i,cat in enumerate(CATEGORIES)}
    fig,ax=plt.subplots(figsize=(9,6))
    for cat,group in cases.groupby("candidate_ranking_category"):
        ax.scatter(group.prior_cell_distinct_acquisition_dates,group.frp_mw,s=75,c=[color_map[cat]],edgecolors="black",linewidths=.4,label=cat.replace("_"," "))
        for _,row in group.iterrows():
            ident=str(row.case_id).split("_")[1]
            ax.annotate(ident,(row.prior_cell_distinct_acquisition_dates,row.frp_mw),xytext=(4,3),textcoords="offset points",fontsize=8)
    ax.set(title="Evidence attributes in the 12 purposively selected case studies",xlabel="Strictly prior distinct dates in 250 m cell",ylabel="FIRMS FRP (MW)"); ax.legend(fontsize=7,frameon=False,loc="best"); ax.grid(alpha=.2)
    ax.text(.99,.02,"Category-balanced illustration; not a population sample or validated labels.",transform=ax.transAxes,ha="right",va="bottom",fontsize=8)
    fig.tight_layout(); fig.savefig(targets[2],dpi=250,bbox_inches="tight",facecolor="white"); plt.close(fig)


def write_report(data:dict,run:Path,case_dir:Path)->None:
    summary=data["summary"]
    def get(metric): return summary.loc[summary.metric.eq(metric),"value"].iloc[0]
    sens=data["sensitivity"]
    threshold_lines=[]
    for t,g in sens.groupby("threshold_m"):
        threshold_lines.append(f"| {int(t)} m | {int(g.detections_reclassified_vs_250m.iloc[0]):,} ({g.percent_reclassified_vs_250m.iloc[0]:.1f}%) | "+"; ".join(f"{r.candidate_category.replace('_',' ')} {int(r.detections):,}" for r in g.sort_values("candidate_category").itertuples())+" |")
    category_lines=[]
    for cat,r in data["cat_summary"].iterrows():
        category_lines.append(f"| `{cat}` | {int(r.detections):,} | {int(r.unique_cells):,} | {r.median_frp_mw:.2f} | {r.median_prior_dates:.1f} | {int(r.relevant_within_250m):,} | {int(r.power_only_within_250m):,} |")
    cg=data["case_group"].groupby("case_group").agg(n=("case_id","size"),frp=("frp_mw","median"),prior=("prior_cell_distinct_acquisition_dates","median"))
    case_lines=[f"| {name} | {int(r.n)} | {r.frp:.2f} | {r.prior:.1f} |" for name,r in cg.iterrows()]
    report=[
        "# Final pilot evaluation and scientific limitations",
        "",
        "## Scope and evaluation method",
        "",
        "This evaluation uses only the completed `run_001` experiment, the existing `outputs/final_pilot` analysis tables, and its 12 representative case studies. No experiment stage was rerun, no data were retrieved, and no labels or classifier were created. The evaluation is descriptive: stage alignment, data-quality checks, evidence coverage, rule-based candidate summaries, threshold sensitivity, and review-case comparison.",
        "",
        "The saved ranking uses FRP ≥5 MW, at least three strictly earlier distinct FIRMS acquisition dates in a 250 m cell, and relevant mapped OSM context within 250 m. General power infrastructure is separated from relevant industrial context. The evidence score weights thermal evidence 0.5, past recurrence 0.3, and mapped context 0.2; it is a manual-review score, not a probability. Satellite spectra are surfaced for review but do not change score or category.",
        "",
        "## Data quality and evidence coverage",
        "",
        f"The prepared input contains **{len(data['firms']):,} detections** from **{pd.to_datetime(data['firms'].acq_date).nunique()} dates** ({data['firms'].acq_date.min()} to {data['firms'].acq_date.max()}). The source quality report attributes {int(get('archive_region_rows')):,} rows to the FIRMS archive and {int(get('NRT_region_rows')):,} to NRT; it recorded zero within-region duplicates and zero archive/NRT overlap. Confidence attributes are `n` {int((data['firms'].confidence=='n').sum()):,}, `l` {int((data['firms'].confidence=='l').sum()):,}, and `h` {int((data['firms'].confidence=='h').sum()):,}. The archive/NRT source schemas differ: the prepared `type` attribute is absent for {int(get('missing_type_attribute')):,} rows, matching the NRT source column omission. This establishes data lineage and row-level completeness for the chosen inputs, not complete observation of all real-world fires or thermal sources.",
        "",
        f"FIRMS, matching, feature, and ranking files each have {len(data['firms']):,} rows. Stable FIRMS IDs are unique and align among source, match, and feature tables; all coordinates passed the pilot bbox checks, and saved processing validation passed. Matching used EPSG:32645. The OSM snapshot supplied {int(get('source_features_available')):,} features; {int(get('features_used_for_matching')):,} entered industrial proximity matching, with {int(get('context_only_features_excluded_from_industrial_match')):,} vegetation/context features retained as context rather than assigned industrial roles. No invalid/empty used geometry was recorded.",
        "",
        "Matching is complete as a table join, but useful mapped industrial evidence is not universal. At 250 m, **7,679** rows are unambiguous proximity candidates, **334** are ambiguous, and **1,207** have no relevant mapped feature within the threshold. At 1 km the counts are **8,276**, **650**, and **294**, respectively. Feature-role coverage overlaps: at 250 m, mining/extraction areas occur near 7,049 detections, industrial land use near 944, facilities near 567, transmission lines near 152, and towers near 140. These are proximity indicators to the mapped snapshot, not source matches. The 615 rows without a saved nearest relevant role and the fully missing `osm_nearest_relevant_feature_id` field limit traceability; overall nearest OSM IDs remain present separately.",
        "",
        "OSM completeness and vintage are not independently known. Features may be missing, generalized, mistagged, or changed between the map snapshot and FIRMS dates. Lines, points, and polygon distances are measured to their mapped geometries, whose positional accuracy is not quantified here. In particular, transmission infrastructure is not treated as industrial attribution. GEM contributes 96 supplementary coal-asset records, not broad industrial coverage, and its snapshots have no historical as-of dates.",
        "",
        f"Past-only recurrence features have no missing values for prior distinct-date counts; {int(get('missing_prior_last_date')):,} rows have no prior last-date/mean value because they have no earlier observation in their cell/source window. The fixed 250 m projected grid contains {int(get('250m_cells')):,} occupied cells, of which {int(get('cells_seen_on_multiple_dates')):,} recur on multiple dates; {int(get('detections_with_at_least_3_strictly_prior_dates')):,} detections meet the ≥3-prior-date ranking rule. The feature-quality check confirmed dates used were strictly earlier and same-date rows were excluded. However, the observation history starts on 2026-01-20, so recurrence is left-truncated; grid cells are spatial bins and may mix physical sources or split one changing source across cells.",
        "",
        f"Sentinel-2 is the limiting evidence stream: {int(get('chip_context')):,} records have chip context, {int(get('temporally_eligible_scene')):,} have a temporally eligible scene, and only **{int(get('usable_pre_detection_spectra'))} ({100*int(get('usable_pre_detection_spectra'))/len(data['firms']):.3f}%)** have usable pre-detection spectra. {int(get('post_detection_scene_withheld')):,} post-detection scenes are withheld; {int(get('heavy_cloud_shadow_chip')):,} chips have heavy cloud/shadow and {int(get('cloud_or_unverified_pixel_screen')):,} have cloud or unverifiable pixel screens. The four spectral bands are missing for 9,218 rows each. Missingness and withheld imagery cannot be interpreted as absence of fire or industrial activity.",
        "",
        "Other missingness: FIRMS `type` is absent in NRT rows by source schema; `cell_prior_last_acquisition_date`/prior-mean missingness is expected where no prior recurrence exists; nearest OSM role-specific distances are null when no matching feature of that role was available in the matcher; `s2_scene_item_id` and related scene metadata are unavailable for rows without chip metadata. These are different causes of missingness and should not be collapsed into one meaning.",
        "",
        "## Candidate-ranking categories and evidence characteristics",
        "",
        "Categories below are mutually exclusive rule buckets for review. They are not source classes, incident labels, or probabilities. The recurrence values are medians of strictly prior distinct dates; OSM/power counts overlap only as evidence fields within categories.",
        "",
        "| Rule-based review category | Detections | 250 m cells | Median FRP (MW) | Median prior distinct dates | Relevant OSM ≤250 m | Power-only ≤250 m |",
        "|---|---:|---:|---:|---:|---:|---:|",
        *category_lines,
        "",
        "The largest bucket, persistent thermal with relevant industrial context, has 6,550 rows in 329 cells, median FRP 2.34 MW, and median 16.5 prior dates. The two elevated buckets contain 57 and 106 rows, with median FRP 6.13 and 7.08 MW and median prior-date counts 1 and 0, respectively. The power-only persistent bucket has 30 rows in 7 cells, median FRP 0.96 MW, and median 6.5 prior dates. The ‘other’ bucket is intentionally broad. Differences are induced partly by the category rules themselves; they do not show validated separation among physical sources.",
        "",
        "### Distance-threshold sensitivity",
        "",
        "The observed matcher statuses become more inclusive as distance increases: candidates 6,963 → 7,679 → 8,031 → 8,276 from 100 m through 1 km; ambiguity 249 → 334 → 472 → 650; no relevant feature 2,008 → 1,207 → 717 → 294. In a counterfactual re-binning, FRP ≥5 MW and ≥3 prior dates were held fixed while the relevant-context and power-only radius changed together; evidence scores were held fixed. The 250 m row reproduces the saved categories exactly.",
        "",
        "| Threshold | Rows reclassified vs 250 m | Category counts at that threshold |",
        "|---:|---:|---|",
        *threshold_lines,
        "",
        "This is rule sensitivity, not classification error. A larger radius moves detections into mapped-context categories by definition and can inflate apparent association; it does not establish a causal industrial source. The candidate score itself uses continuous distance with a 1 km cap, while category membership uses a hard 250 m cut-off; rows near the cut-off can therefore change category abruptly even though their score changes smoothly or not at all in this counterfactual.",
        "",
        "![OSM threshold and category sensitivity](../outputs/final_pilot/figures/09_evaluation_threshold_sensitivity.png)",
        "",
        "![Category evidence comparison](../outputs/final_pilot/figures/10_candidate_category_evidence_comparison.png)",
        "",
        "## Representative-case evaluation",
        "",
        "The 12 cases are purposively balanced at two per ranking category, with within-category rank positions chosen around the 25th/75th percentiles and chip availability considered. They are not a random sample and cannot estimate population behavior. All 12 have nominal FIRMS confidence `n`; FRP ranges from 0.88 to 9.00 MW; prior-date recurrence ranges from 0 to 29. Eleven cases have at least one mapped industrial or power feature within 1 km, but nearby lines/towers or mining polygons still do not establish source identity or cause.",
        "",
        "| Selected review-group | Cases | Median FRP (MW) | Median prior distinct dates |",
        "|---|---:|---:|---:|",
        *case_lines,
        "",
        "The elevated examples have higher FRP by construction, while persistent examples show earlier repeat observations by construction. These case differences therefore illustrate the rules and their evidence, not an independent class comparison. The persistent-without-relevant-context examples include one case with a nearby mapped mine beyond 250 m and another near general transmission infrastructure; mapped-context categories include observations at/near mapped extraction areas. Both patterns demonstrate that a 250 m threshold can omit nearby mapped assets and that zero-distance polygon overlap does not confirm the thermal source is inside/caused by that industrial site.",
        "",
        "Four selected observations have existing Sentinel-2 chips, all acquired after their FIRMS dates. Scene cloud estimates range from 14.2% to 87.1%; two have clear pixel-level SCL flags but are still future imagery for the corresponding detection, while two have at least 50% chip cloud/shadow. None of the selected cases has eligible pre-detection spectra. A later image describes later surface conditions and cannot establish what existed at the FIRMS acquisition time. The per-case summaries distinguish scene date, cloud screen, and eligibility.",
        "",
        "![Selected case evidence scatter](../outputs/final_pilot/figures/11_case_study_evidence_scatter.png)",
        "",
        "## Scientific validity and limitations",
        "",
        "### No verified detection-level labels",
        "",
        "There are zero verified FIRMS-to-incident links, zero adjudicated positive detections, and no defensible negative examples. The human review fields in this case register are pending, not completed judgments. Accuracy, precision, recall, F-score, ROC/AUC, calibration, and other supervised metrics cannot be calculated because no truth labels or evaluation outcomes exist. Treating the rule categories, OSM/GEM proximity, or recurrence as labels would be circular and invalid. No supervised classifier is justified by the current data.",
        "",
        "### Causality, source identity, and temporal evidence",
        "",
        "- **Proximity is association only:** FIRMS geolocation uncertainty, source geometry/extent, mixed land use, and OSM positional/tagging completeness prevent causal attribution from distance alone.",
        "- **Recurrence is not identity:** repeat dates within a 250 m cell can arise from multiple sources, shifting plumes or footprints, repeated overpasses, or geolocation scatter. Recurrence only counts observations in the available window and is not continuous-duration proof.",
        "- **Post-detection optical imagery is not pre-event evidence:** later Sentinel-2 scenes cannot establish pre-detection surface conditions. Even clear optical imagery is not thermal confirmation and may miss short-lived events between revisit dates.",
        "- **Ranking is a heuristic:** thresholds and weights are hand-set, not learned or calibrated against outcomes. The high nominal-confidence prevalence, low high-confidence count, cloud/sensor effects, class imbalance, OSM vintage, missing imagery, and threshold discontinuities affect ordering. Different plausible thresholds or weights can reorder candidates.",
        "- **Study scope is narrow:** results describe one pilot rectangle and the 2026 FIRMS input period. They do not establish transfer to other regions, industries, sensors, seasons, or historical periods.",
        "",
        "## Recommendations",
        "",
        "1. Keep outputs named candidate-review priorities and unknowns; do not call them fire classifications.",
        "2. Human-review a small, stratified set with dated, georeferenced, independent incident sources. Record source URLs, time/location precision, decision, reviewer, rationale, and uncertainty; keep unresolved cases unknown.",
        "3. Define defensible negative/control evidence separately, and evaluate with site/event-grouped and temporally held-out splits to prevent spatial and temporal leakage.",
        "4. Improve OSM feature traceability by retaining stable IDs for role-specific nearest features and preserving source snapshot dates; quantify positional uncertainty before interpreting short distances.",
        "5. For satellite evidence, obtain only case-targeted scenes that predate detections, preserve scene IDs and SCL/cloud metadata, and keep post-event images as contextual follow-up only. Do not scale imagery retrieval until coverage is demonstrated.",
        "6. Report sensitivity across thresholds and alternative plausible weights as robustness analysis, not model validation.",
        "",
        "## Reproducibility and outputs",
        "",
        "No new data were downloaded, the pilot was not rerun, and the analysis used only the audited experiment and saved case-study register. Summary calculations are in [evaluation_summary.csv](../outputs/final_pilot/tables/evaluation_summary.csv) and the threshold re-binning details are in [candidate_category_threshold_sensitivity.csv](../outputs/final_pilot/tables/candidate_category_threshold_sensitivity.csv). Source tables and rule definitions are recorded in `run_001`; the figures are under `outputs/final_pilot/figures/`.",
        "",
    ]
    (ROOT/"docs/final_pilot_evaluation.md").write_text("\n".join(report),encoding="utf-8")


def main()->None:
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-root",type=Path,default=RUN)
    ap.add_argument("--case-dir",type=Path,default=CASE)
    ap.add_argument("--output-root",type=Path,default=OUT)
    ap.add_argument("--resume-incomplete",action="store_true",help="Complete a partial evaluation run created by this script when tables exist but report/figures do not")
    args=ap.parse_args()
    tables=args.output_root/"tables"; figures=args.output_root/"figures"
    if not tables.exists() or not figures.exists(): raise FileNotFoundError("Expected final-pilot tables/figures directory missing")
    summary_path=tables/"evaluation_summary.csv"
    sensitivity_path=tables/"candidate_category_threshold_sensitivity.csv"
    partial=summary_path.exists() and sensitivity_path.exists()
    if partial and not args.resume_incomplete: raise FileExistsError("Evaluation tables already exist; use --resume-incomplete only for a partial run created by this script")
    if args.resume_incomplete:
        if not partial or (args.output_root/"figures/09_evaluation_threshold_sensitivity.png").exists() or (ROOT/"docs/final_pilot_evaluation.md").exists():
            raise FileExistsError("--resume-incomplete requires the partial evaluation state: both tables present, figures/report absent")
    data=build_tables(args.run_root,args.case_dir,tables,write_files=True)
    create_figures(data,figures)
    write_report(data,args.run_root,args.case_dir)
    print(json.dumps({"rows_in_evaluation_summary":len(data["summary"]),"threshold_sensitivity_rows":len(data["sensitivity"]),"cases":len(data["cases"]),"report":"docs/final_pilot_evaluation.md","figures":["09_evaluation_threshold_sensitivity.png","10_candidate_category_evidence_comparison.png","11_case_study_evidence_scatter.png"]},indent=2))


if __name__=="__main__": main()
