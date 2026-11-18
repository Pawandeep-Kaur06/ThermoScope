"""Validate and package the completed local Jharkhand pilot workflow outputs."""
from __future__ import annotations

import argparse
import ast
import hashlib
import html
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DEFAULT_RUN = ROOT / "data/processed/jharkhand_analysis/run_001"
CATEGORY_COLORS = {
    "persistent_thermal_with_nearby_relevant_industrial_context": "#d73027",
    "persistent_thermal_without_nearby_relevant_osm_context": "#7b3294",
    "persistent_thermal_near_general_power_infrastructure_only": "#008837",
    "elevated_thermal_with_nearby_relevant_industrial_context": "#fc8d59",
    "elevated_thermal_without_nearby_relevant_osm_context": "#4575b4",
    "other_thermal_observation_review": "#999999",
}
GROUP_COLOR = {
    "industrial_landuse": "#e7298a", "industrial_facility": "#d95f02",
    "mining_extraction": "#8c510a", "industrial_structure": "#a6761d",
    "power_infrastructure": "#1b9e77", "waste_facility": "#7570b3",
    "industrial_rail": "#e6ab02",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_groups(value) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    try:
        parsed = json.loads(str(value))
    except (json.JSONDecodeError, TypeError):
        try:
            parsed = ast.literal_eval(str(value))
        except (ValueError, SyntaxError):
            parsed = []
    return [str(item) for item in parsed] if isinstance(parsed, (list, tuple)) else []


def load_inputs(run_dir: Path) -> dict:
    firms_path = ROOT / "data/processed/firms_jharkhand_2026.csv"
    osm_path = ROOT / "data/processed/osm/jharkhand_261016_osm.gpkg"
    boundary_path = ROOT / "data/processed/boundaries/jharkhand_osm_admin4.geojson"
    matching_dir = run_dir / "spatial_matching"
    feature_dir = run_dir / "feature_engineering_with_sentinel2"
    ranking_dir = run_dir / "candidate_ranking_with_sentinel2"
    satellite_dir = run_dir / "satellite_investigation"
    paths = {
        "firms": firms_path, "firms_quality": Path(str(firms_path) + ".quality.json"),
        "osm": osm_path, "osm_manifest": osm_path.with_suffix(".manifest.json"),
        "boundary": boundary_path, "matching_csv": matching_dir / "firms_pilot_osm_proximity.csv",
        "matching_gpkg": matching_dir / "firms_pilot_osm_proximity.gpkg",
        "matching_summary": matching_dir / "summary.json",
        "recurrence_cells": matching_dir / "firms_spatial_recurrence_cells.csv",
        "features": feature_dir / "feature_table.csv.gz",
        "feature_quality": feature_dir / "quality_checks.json",
        "ranking": ranking_dir / "candidate_ranking.csv",
        "ranking_categories": ranking_dir / "category_counts.csv",
        "ranking_validation": ranking_dir / "validation.json",
        "satellite_metadata": satellite_dir / "scene_metadata.csv",
        "satellite_manifest": satellite_dir / "run_manifest.json",
    }
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Jharkhand analysis inputs are missing: {missing}")
    return paths


def validate(paths: dict, firms: pd.DataFrame, matches: pd.DataFrame,
             features: pd.DataFrame, ranking: pd.DataFrame) -> dict:
    checks = {}
    checks["prepared_firms_rows"] = len(firms) == 21_450
    checks["matching_rows_equal_prepared_firms"] = len(matches) == len(firms)
    checks["features_rows_equal_prepared_firms"] = len(features) == len(firms)
    checks["ranking_rows_equal_prepared_firms"] = len(ranking) == len(firms)
    checks["unique_observation_ids"] = (firms.firms_observation_id.is_unique
                                        and matches.firms_observation_id.is_unique
                                        and features.firms_observation_id.is_unique)
    checks["unique_source_rows"] = (matches.firms_source_row.is_unique
                                    and features.firms_source_row.is_unique
                                    and ranking.firms_source_row.is_unique)
    ids = set(firms.firms_observation_id.astype(str))
    checks["observation_id_sets_match"] = all(
        set(frame.firms_observation_id.astype(str)) == ids for frame in (matches, features)
    )
    checks["ranking_source_rows_match"] = set(ranking.firms_source_row.astype(int)) == set(matches.firms_source_row.astype(int))
    checks["all_candidate_labels_unknown"] = bool(ranking.firms_detection_label.eq("unknown_unlinked").all())
    checks["no_ground_truth_columns"] = not any(
        col.lower() in {"ground_truth", "ground_truth_label", "verified_label", "target"}
        for frame in (firms, matches, features, ranking) for col in frame.columns
    )
    date = pd.to_datetime(matches.acq_date, errors="coerce")
    prior = pd.to_datetime(features.cell_prior_last_acquisition_date, errors="coerce")
    checks["recurrence_is_past_only"] = bool((prior.isna() | prior.lt(pd.to_datetime(features.acq_date))).all())
    checks["coordinates_present"] = not matches[["latitude", "longitude"]].isna().any().any()
    checks["valid_wgs84_coordinate_ranges"] = bool(matches.longitude.between(-180, 180).all() and matches.latitude.between(-90, 90).all())
    checks["state_boundary_membership"] = True
    from src.regions import assign_tile_ids, contains_coordinates, get_region, tile_for_coordinate
    region = get_region("jharkhand")
    membership = contains_coordinates(matches.longitude, matches.latitude, region)
    checks["state_boundary_membership"] = bool(membership.all())
    expected_tiles = assign_tile_ids(matches.longitude.to_numpy(), matches.latitude.to_numpy(), region)
    checks["tile_assignments_consistent"] = expected_tiles == matches.tile_id.astype(str).tolist()
    crs_ok = True
    for tile_id, rows in matches.groupby("tile_id", sort=False):
        first = rows.iloc[0]
        tile = tile_for_coordinate(float(first.longitude), float(first.latitude), region)
        crs_ok &= tile is not None and tile["tile_id"] == tile_id
        crs_ok &= set(rows.distance_crs.astype(str)) == {tile["projected_crs"]}
    checks["tile_local_crs_consistent"] = bool(crs_ok)
    spectral = ["s2_b04_red_dn", "s2_b03_green_dn", "s2_b02_blue_dn", "s2_b11_swir16_dn"]
    future = pd.to_numeric(features.s2_scene_offset_hours, errors="coerce").gt(0)
    checks["no_future_spectral_values"] = not bool(features.loc[future, spectral].notna().any().any())
    checks["valid_spectra_require_clear_eligible_pixels"] = bool(
        features.loc[features.s2_spectral_predictor_eligible, spectral].notna().all(axis=1).all()
        and not features.loc[features.s2_spectral_predictor_eligible, "s2_scene_offset_hours"].gt(0).any()
    )
    checks["checks_passed"] = all(value for value in checks.values() if isinstance(value, bool))
    if not checks["checks_passed"]:
        failed = [key for key, value in checks.items() if isinstance(value, bool) and not value]
        raise ValueError(f"Jharkhand output validation failed: {failed}")
    return checks


def create_tables(paths: dict, firms: pd.DataFrame, matches: pd.DataFrame,
                  features: pd.DataFrame, ranking: pd.DataFrame, out: Path) -> dict[str, pd.DataFrame]:
    date = pd.to_datetime(firms.acq_date, errors="coerce")
    frp = pd.to_numeric(firms.frp, errors="coerce")
    firms_summary = pd.DataFrame([
        {"metric": "observations", "value": len(firms), "definition": "prepared, in-boundary FIRMS rows"},
        {"metric": "unique_observation_ids", "value": firms.firms_observation_id.nunique(), "definition": "stable SHA-256 observation identities"},
        {"metric": "minimum_acquisition_date", "value": str(date.min().date()), "definition": "earliest available source date"},
        {"metric": "maximum_acquisition_date", "value": str(date.max().date()), "definition": "latest available source date"},
        {"metric": "distinct_acquisition_dates", "value": date.nunique(), "definition": "dates with at least one observation"},
        {"metric": "median_frp_mw", "value": float(frp.median()), "definition": "FIRMS FRP median; not source class"},
        {"metric": "frp_95th_percentile_mw", "value": float(frp.quantile(.95)), "definition": "FIRMS FRP 95th percentile"},
    ])
    confidence = firms.confidence.fillna("missing").astype(str).value_counts().rename_axis("confidence").reset_index(name="observations")
    confidence.insert(0, "summary_type", "confidence_count")
    confidence = confidence.rename(columns={"confidence": "metric", "observations": "value"})
    firms_summary = pd.concat([firms_summary, confidence.assign(definition="FIRMS source confidence attribute")], ignore_index=True)

    group_counts: dict[str, int] = {}
    # Read each geometry layer and count overlapping tags by source layer.
    for layer in gpd.list_layers(paths["osm"]).name:
        frame = gpd.read_file(paths["osm"], layer=layer)
        for value in frame.feature_groups.fillna("[]"):
            for group in set(parse_groups(value)):
                group_counts[group] = group_counts.get(group, 0) + 1
    osm_summary = pd.DataFrame([{"feature_group": key, "feature_records": value,
                                 "interpretation": "OSM snapshot feature count; groups overlap and do not label FIRMS"}
                                for key, value in sorted(group_counts.items())])
    threshold_path = paths["matching_csv"].parent / "distance_threshold_summary.csv"
    threshold = pd.read_csv(threshold_path)
    recurrence = pd.read_csv(paths["recurrence_cells"])
    recurrence_summary = pd.DataFrame([
        {"metric": "250m_grid_cells", "value": recurrence.hotspot_cell_id.nunique()},
        {"metric": "cells_with_repeated_acquisition_dates", "value": int((recurrence.distinct_acquisition_dates >= 2).sum())},
        {"metric": "cells_with_at_least_3_acquisition_dates", "value": int((recurrence.distinct_acquisition_dates >= 3).sum())},
        {"metric": "maximum_distinct_dates_in_a_cell", "value": int(recurrence.distinct_acquisition_dates.max())},
        {"metric": "median_distinct_dates_per_cell", "value": float(recurrence.distinct_acquisition_dates.median())},
    ])
    ranking_summary = pd.read_csv(paths["ranking_categories"])
    quality = json.loads(paths["feature_quality"].read_text(encoding="utf-8"))
    s2 = quality["sentinel2"]
    satellite_summary = pd.DataFrame([
        {"metric": key, "value": value, "interpretation": key.replace("_", " ")}
        for key, value in s2.items()
    ])
    prep = json.loads(paths["firms_quality"].read_text(encoding="utf-8"))
    match_summary = json.loads(paths["matching_summary"].read_text(encoding="utf-8"))
    validation = json.loads(paths["ranking_validation"].read_text(encoding="utf-8"))
    quality_rows = [
        {"check": "FIRMS prepared count", "value": prep["output"]["row_count"], "status": "passed"},
        {"check": "OSM retained features", "value": json.loads(paths["osm_manifest"].read_text(encoding="utf-8"))["feature_count"], "status": "passed"},
        {"check": "FIRMS matching rows", "value": match_summary["firms_pilot_rows"], "status": "passed"},
        {"check": "Active OSM matching tiles", "value": match_summary["tile_processing"]["tile_count_used"], "status": "passed"},
        {"check": "Feature row count", "value": quality["region_feature_rows"], "status": quality["overall_status"]},
        {"check": "Unlinked labels remain unknown", "value": validation["all_labels_unknown_unlinked"], "status": "passed"},
        {"check": "Supervised model trained", "value": validation["supervised_model_trained"], "status": "not_run_no_verified_labels"},
        {"check": "Independent metrics", "value": validation["metrics_computed"], "status": "not_run_no_verified_labels"},
    ]
    tables = {
        "firms_summary": firms_summary,
        "osm_feature_groups": osm_summary,
        "industrial_proximity_thresholds": threshold,
        "recurrence_summary": recurrence_summary,
        "candidate_ranking_summary": ranking_summary,
        "satellite_coverage": satellite_summary,
        "data_quality_validation": pd.DataFrame(quality_rows),
    }
    for name, table in tables.items():
        table.to_csv(out / "tables" / f"{name}.csv", index=False)
    return tables


def plot_figures(paths: dict, firms: pd.DataFrame, matches: pd.DataFrame,
                 features: pd.DataFrame, ranking: pd.DataFrame, out: Path) -> None:
    figures = out / "figures"
    boundary = gpd.read_file(paths["boundary"])
    recurrence = pd.read_csv(paths["recurrence_cells"])
    # Study-area thermal map.
    fig, ax = plt.subplots(figsize=(8, 8))
    boundary.boundary.plot(ax=ax, color="#333333", linewidth=1.2)
    ax.scatter(firms.longitude, firms.latitude, c="#d73027", s=1.2, alpha=.35, rasterized=True)
    ax.set(title="Jharkhand FIRMS observations (2026-01-20 to 2026-09-06)", xlabel="Longitude", ylabel="Latitude")
    ax.set_aspect("equal"); ax.grid(alpha=.2)
    fig.tight_layout(); fig.savefig(figures / "01_jharkhand_firms_map.png", dpi=180); plt.close(fig)
    # Time series.
    daily = firms.assign(date=pd.to_datetime(firms.acq_date)).groupby("date").size()
    fig, ax = plt.subplots(figsize=(10, 4))
    daily.plot(ax=ax, color="#2c7fb8", linewidth=.8)
    ax.set(title="FIRMS observation volume by acquisition date", xlabel="Date", ylabel="Detections")
    ax.grid(alpha=.2); fig.tight_layout(); fig.savefig(figures / "02_firms_over_time.png", dpi=180); plt.close(fig)
    # FRP and confidence.
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    frp = pd.to_numeric(firms.frp, errors="coerce").dropna()
    axes[0].hist(frp.clip(upper=frp.quantile(.99)), bins=35, color="#fdae61", edgecolor="white")
    axes[0].set(title="FRP distribution (clipped at 99th percentile)", xlabel="FRP (MW)", ylabel="Observations")
    firms.confidence.fillna("missing").astype(str).value_counts().plot.bar(ax=axes[1], color="#74add1")
    axes[1].set(title="FIRMS confidence field", xlabel="Confidence", ylabel="Observations")
    fig.tight_layout(); fig.savefig(figures / "03_frp_confidence.png", dpi=180); plt.close(fig)
    # Proximity thresholds.
    threshold = pd.read_csv(paths["matching_csv"].parent / "distance_threshold_summary.csv")
    fig, ax = plt.subplots(figsize=(7, 4))
    xcol = "threshold_m" if "threshold_m" in threshold else threshold.columns[0]
    ycol = next((c for c in threshold.columns if "detections_with_relevant_feature" in c), threshold.columns[-1])
    ax.bar(threshold[xcol].astype(str), threshold[ycol], color="#1b9e77")
    ax.set(title="Relevant OSM proximity evidence by threshold", xlabel="Distance threshold (m)", ylabel="FIRMS observations")
    fig.tight_layout(); fig.savefig(figures / "04_osm_proximity_thresholds.png", dpi=180); plt.close(fig)
    # Recurrence distribution.
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.hist(recurrence.distinct_acquisition_dates, bins=30, color="#8c6bb1")
    ax.set(title="Past-window recurrence across 250 m grid cells", xlabel="Distinct observed dates per cell", ylabel="Cells")
    fig.tight_layout(); fig.savefig(figures / "05_recurrence_distribution.png", dpi=180); plt.close(fig)
    # Candidate categories.
    counts = pd.read_csv(paths["ranking_categories"])
    fig, ax = plt.subplots(figsize=(10, 5))
    counts.sort_values("detections").plot.barh(x="candidate_category", y="detections", ax=ax, color="#756bb1", legend=False)
    ax.set(title="Rule-based review categories (evidence indicators only)", xlabel="FIRMS observations", ylabel="")
    fig.tight_layout(); fig.savefig(figures / "06_candidate_categories.png", dpi=180); plt.close(fig)
    # Imagery coverage.
    q = json.loads(paths["feature_quality"].read_text(encoding="utf-8"))["sentinel2"]
    labels = ["cell chip context", "temporally eligible", "clear valid spectrum", "future withheld", "cloud/shadow"]
    vals = [q["rows_with_chip_for_context"], q["rows_with_temporally_eligible_scene"],
            q["rows_with_valid_causal_spectral_samples"], q["rows_with_post_detection_imagery_withheld"],
            q["rows_with_heavy_chip_cloud_shadow"]]
    fig, ax = plt.subplots(figsize=(9, 4))
    ax.bar(labels, vals, color=["#3182bd", "#31a354", "#006d2c", "#de2d26", "#fd8d3c"])
    ax.set(title="Satellite evidence availability (feature rows)", ylabel="Observations")
    ax.tick_params(axis="x", rotation=20); fig.tight_layout(); fig.savefig(figures / "07_satellite_coverage.png", dpi=180); plt.close(fig)


def create_dashboard(paths: dict, matches: pd.DataFrame, features: pd.DataFrame,
                     ranking: pd.DataFrame, output_path: Path, max_osm: int) -> dict:
    boundary_frame = gpd.read_file(paths["boundary"])
    boundary_geojson = json.loads(boundary_frame.to_json(drop_id=True))
    joined = ranking.copy()
    if "s2_spectral_data_status" not in joined:
        joined = joined.merge(
            features[["firms_source_row", "s2_spectral_data_status", "s2_scene_datetime_utc"]],
            on="firms_source_row", how="left", validate="one_to_one",
        )
    features_geo = []
    for row in joined.itertuples(index=False):
        popup = "<br>".join([
            f"<b>{html.escape(str(row.candidate_category))}</b>",
            f"Date: {html.escape(str(row.acq_date))} {html.escape(str(row.acq_time))} UTC",
            f"FRP: {html.escape(str(row.thermal_frp_mw))} MW; confidence: {html.escape(str(row.confidence))}",
            f"Prior cell dates: {html.escape(str(row.cell_prior_distinct_acquisition_dates))}",
            f"Nearest relevant OSM role: {html.escape(str(row.osm_nearest_relevant_role))}",
            f"Nearest relevant OSM distance: {html.escape(str(row.osm_nearest_relevant_distance_m))} m",
            f"Satellite status: {html.escape(str(row.s2_spectral_data_status))}",
            "Detection label: unknown; proximity and recurrence are not ground truth",
        ])
        features_geo.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [float(row.longitude), float(row.latitude)]},
                             "properties": {"category": str(row.candidate_category), "popup": popup}})
    # Keep a bounded, deterministic OSM overlay; all mapped feature totals remain in the summary tables.
    relevant_groups = set(GROUP_COLOR)
    osm_rows = []
    for layer in gpd.list_layers(paths["osm"]).name:
        frame = gpd.read_file(paths["osm"], layer=layer)
        for row in frame.itertuples(index=False):
            groups = parse_groups(getattr(row, "feature_groups"))
            group = next((g for g in groups if g in relevant_groups), None)
            geom = getattr(row, "geometry")
            if group and geom is not None and not geom.is_empty:
                osm_rows.append((str(getattr(row, "osm_id", "")), group, geom))
    osm_rows.sort(key=lambda item: item[0])
    # Prefer contextual polygons/mining/industrial and sample the large mapped-power point layer.
    if len(osm_rows) > max_osm:
        priorities = {"mining_extraction": 0, "industrial_landuse": 1, "industrial_facility": 2,
                      "waste_facility": 3, "industrial_structure": 4, "industrial_rail": 5,
                      "power_infrastructure": 6}
        osm_rows.sort(key=lambda item: (priorities.get(item[1], 9), item[0]))
        osm_rows = osm_rows[:max_osm]
    osm_geo = []
    for osm_id, group, geom in osm_rows:
        if geom.geom_type not in {"Point", "MultiPoint"}:
            geom = geom.simplify(0.00008, preserve_topology=True)
        if geom.is_empty:
            continue
        from shapely.geometry import mapping
        osm_geo.append({"type": "Feature", "geometry": mapping(geom),
                        "properties": {"group": group, "osm_id": osm_id,
                                       "popup": f"<b>{html.escape(group.replace('_', ' '))}</b><br>OSM {html.escape(osm_id)}"}})
    boundary_json = json.dumps(boundary_geojson, separators=(",", ":")).replace("</", "<\\/")
    firms_json = json.dumps({"type": "FeatureCollection", "features": features_geo}, separators=(",", ":")).replace("</", "<\\/")
    osm_json = json.dumps({"type": "FeatureCollection", "features": osm_geo}, separators=(",", ":")).replace("</", "<\\/")
    colors_json = json.dumps(CATEGORY_COLORS)
    group_colors_json = json.dumps(GROUP_COLOR)
    html_doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>ThermoScope Jharkhand evidence map</title><link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"><style>html,body,#map{{height:100%;margin:0}}.legend{{background:white;padding:10px;line-height:1.45;font:12px sans-serif;box-shadow:0 1px 5px #666}}.dot{{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px}}</style></head><body><div id="map"></div><script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script><script>
const boundary={boundary_json};const firms={firms_json};const osm={osm_json};const colors={colors_json};const groupColors={group_colors_json};
const map=L.map('map',{{preferCanvas:true}});L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',{{maxZoom:18,attribution:'&copy; OpenStreetMap contributors'}}).addTo(map);
const bounds=L.geoJSON(boundary,{{style:{{color:'#222',weight:2,fillOpacity:0.02}}}}).addTo(map);map.fitBounds(bounds.getBounds());
const osmLayer=L.geoJSON(osm,{{style:f=>({{color:groupColors[f.properties.group]||'#555',weight:1,fillOpacity:.22}}),pointToLayer:(f,ll)=>L.circleMarker(ll,{{radius:3,color:groupColors[f.properties.group]||'#555',fillOpacity:.65,weight:1}}),onEachFeature:(f,l)=>l.bindPopup(f.properties.popup)}});
const firmLayer=L.geoJSON(firms,{{pointToLayer:(f,ll)=>L.circleMarker(ll,{{renderer:L.canvas(),radius:3,color:colors[f.properties.category]||'#777',fillColor:colors[f.properties.category]||'#777',fillOpacity:.72,weight:.4}}),onEachFeature:(f,l)=>l.bindPopup(f.properties.popup)}}).addTo(map);
L.control.layers(null,{{'FIRMS observations (evidence categories)':firmLayer,'Mapped OSM industrial/power context (bounded overview)':osmLayer,'Jharkhand boundary':bounds}},{{collapsed:false}}).addTo(map);
const legend=L.control({{position:'bottomright'}});legend.onAdd=()=>{{const d=L.DomUtil.create('div','legend');d.innerHTML='<b>Review categories</b><br>'+Object.entries(colors).map(([k,v])=>'<span class="dot" style="background:'+v+'"></span>'+k.replaceAll('_',' ')+'<br>').join('')+'<hr>Categories prioritize review; they are not source classes or confirmed fires.';return d}};legend.addTo(map);
</script></body></html>"""
    output_path.write_text(html_doc, encoding="utf-8")
    return {"html_bytes": output_path.stat().st_size, "osm_features_embedded": len(osm_geo),
            "firms_observations_embedded": len(features_geo), "map_requires_internet_for_basemap_and_leaflet": True}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs/jharkhand/run_001")
    parser.add_argument("--max-osm-features", type=int, default=5000)
    args = parser.parse_args(argv)
    run_dir = args.run_dir if args.run_dir.is_absolute() else ROOT / args.run_dir
    output = args.output_dir if args.output_dir.is_absolute() else ROOT / args.output_dir
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite existing Jharkhand output package: {output}")
    paths = load_inputs(run_dir)
    firms = pd.read_csv(paths["firms"], low_memory=False)
    matches = pd.read_csv(paths["matching_csv"], low_memory=False)
    features = pd.read_csv(paths["features"], low_memory=False)
    ranking = pd.read_csv(paths["ranking"], low_memory=False)
    checks = validate(paths, firms, matches, features, ranking)
    output.mkdir(parents=True)
    (output / "figures").mkdir()
    (output / "tables").mkdir()
    tables = create_tables(paths, firms, matches, features, ranking, output)
    plot_figures(paths, firms, matches, features, ranking, output)
    dashboard = create_dashboard(paths, matches, features, ranking, output / "jharkhand_evidence_map.html", args.max_osm_features)
    inputs = {name: {"path": path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else path.name,
                     "size_bytes": path.stat().st_size, "sha256": sha256(path)} for name, path in paths.items()}
    outputs = [p for p in output.rglob("*") if p.is_file()]
    manifest = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "region_id": "jharkhand", "region_boundary_sha256": sha256(paths["boundary"]),
        "run_dir": run_dir.relative_to(ROOT).as_posix() if run_dir.is_relative_to(ROOT) else run_dir.name,
        "inputs": inputs, "validation": checks,
        "software": {"python": sys.version, "platform": platform.platform(), "pandas": pd.__version__,
                     "geopandas": gpd.__version__, "numpy": np.__version__},
        "dashboard": dashboard,
        "output_files": {p.relative_to(output).as_posix(): {"size_bytes": p.stat().st_size, "sha256": sha256(p)} for p in outputs},
        "labels": {"verified_detection_labels": 0, "negative_examples": 0,
                   "all_candidate_labels_unknown": bool(ranking.firms_detection_label.eq("unknown_unlinked").all())},
        "model": {"trained": False, "evaluation_metrics": None,
                  "reason": "No independently verified image/event labels; supervised fire-source classification is unsupported."},
    }
    (output / "results_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "checks": checks, "dashboard": dashboard,
                      "tables": list(tables), "manifest": str(output / 'results_manifest.json')}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
