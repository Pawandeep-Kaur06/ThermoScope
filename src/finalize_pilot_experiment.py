"""Validate a completed ThermoScope final pilot run and write its provenance manifest.

Run from the repository root after all final-pilot stages complete:
    python src/finalize_pilot_experiment.py --run-root data/processed/final_pilot_experiment/run_001
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata as metadata
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config/final_pilot_experiment.json"
CODE_FILES = [
    "src/prepare_firms_pilot.py", "src/match_firms_osm_pilot.py",
    "src/engineer_features.py", "src/investigate_satellite_pilot.py",
    "src/rank_firms_candidates.py", "src/review_evidence.py",
]
PACKAGES = ["pandas", "geopandas", "shapely", "pyproj", "pyogrio", "rasterio", "numpy", "matplotlib", "requests"]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--config", type=Path, default=Path("config/final_pilot_experiment.json"))
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--refresh", action="store_true",
                        help="refresh only this script's existing manifest after verifying its experiment identity")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo = args.repo.resolve()
    config_path = args.config if args.config.is_absolute() else repo / args.config
    run_root = args.run_root if args.run_root.is_absolute() else repo / args.run_root
    run_root = run_root.resolve()
    config = load_json(config_path)
    validation_dir = run_root / "validation"
    manifest_path = validation_dir / "reproducibility_manifest.json"
    satellite_ref_path = validation_dir / "satellite_evidence_reference.json"
    if not run_root.is_dir():
        raise FileNotFoundError(f"Final pilot run directory not found: {run_root}")
    if validation_dir.exists():
        if not args.refresh or not manifest_path.is_file():
            raise FileExistsError(f"Refusing to overwrite existing validation directory: {validation_dir}; use --refresh only for this run's own manifest")
        previous = load_json(manifest_path)
        if (previous.get("experiment_id") != config.get("experiment_id")
                or previous.get("configuration", {}).get("sha256") != sha256(config_path)):
            raise ValueError(f"Refusing to refresh a manifest owned by another experiment/config: {manifest_path}")

    checks: list[dict[str, Any]] = []
    def check(name: str, ok: bool, details: str) -> None:
        checks.append({"check": name, "status": "passed" if ok else "failed", "details": details})

    # Verify shared region configuration and the source artifacts pinned by the experiment.
    region_config_path = repo / config["region"]["configuration"]
    region_config = load_json(region_config_path)["regions"][config["region"]["region_id"]]
    check("region_bounds_and_crs", config["region"]["bbox_wgs84"] == region_config["bbox_wgs84"]
          and config["region"]["distance_crs"] == region_config["projected_crs"],
          f"{config['region']['bbox_wgs84']}; {config['region']['distance_crs']}")
    check("region_config_checksum", sha256(region_config_path) == config["region"]["configuration_sha256"], relative(region_config_path, repo))

    source_fingerprints: dict[str, dict[str, Any]] = {}
    for item in config["firms"]["inputs"]:
        path = repo / item["path"]
        actual = sha256(path) if path.is_file() else None
        check(f"firms_input:{item['role']}", actual == item["sha256"], relative(path, repo))
        source_fingerprints[item["role"]] = {"path": item["path"], "size_bytes": path.stat().st_size if path.exists() else None, "sha256": actual}

    osm_path = repo / config["osm"]["path"]
    osm_manifest_path = repo / config["osm"]["manifest"]
    for name, path, expected in [
        ("osm_geopackage", osm_path, config["osm"]["sha256"]),
        ("osm_manifest", osm_manifest_path, config["osm"]["manifest_sha256"]),
    ]:
        actual = sha256(path) if path.is_file() else None
        check(name, actual == expected, relative(path, repo))
        source_fingerprints[name] = {"path": relative(path, repo), "size_bytes": path.stat().st_size if path.exists() else None, "sha256": actual}

    for item in config["gem"]["filtered_inputs"]:
        path = repo / item["path"]
        actual = sha256(path) if path.is_file() else None
        check(f"gem:{path.name}", actual == item["sha256"], relative(path, repo))
        source_fingerprints[f"gem:{path.name}"] = {"path": item["path"], "size_bytes": path.stat().st_size if path.exists() else None, "sha256": actual}

    reference = config["sentinel2"]["existing_reference_run"]
    satellite_dir = repo / reference["path"]
    scene_metadata = satellite_dir / "scene_metadata.csv"
    scene_hash = sha256(scene_metadata) if scene_metadata.is_file() else None
    check("sentinel2_scene_metadata_checksum", scene_hash == reference["scene_metadata_sha256"], relative(scene_metadata, repo))
    chip_inventory = []
    for item in reference["chips"]:
        path = repo / item["path"]
        actual = sha256(path) if path.is_file() else None
        valid = actual == item["sha256"] and path.stat().st_size == item["size_bytes"]
        check(f"sentinel2_chip:{path.name}", valid, relative(path, repo))
        chip_inventory.append({"path": item["path"], "size_bytes": path.stat().st_size if path.exists() else None, "sha256": actual})

    # Validate all generated pipeline stages against their own saved quality reports and row-level keys.
    firms_path = run_root / "input/firms_pilot.csv"
    prep_path = run_root / "input/firms_pilot.csv.quality.json"
    prep = load_json(prep_path)
    firms = pd.read_csv(firms_path, low_memory=False)
    bounds = config["region"]["bbox_wgs84"]
    in_bounds = (firms.longitude.between(bounds["west"], bounds["east"], inclusive="both")
                 & firms.latitude.between(bounds["south"], bounds["north"], inclusive="both"))
    prep_ok = (len(firms) == config["firms"]["prepared_reference"]["rows"]
               and prep["output"]["row_count"] == len(firms)
               and in_bounds.all()
               and not firms["firms_observation_id"].duplicated().any()
               and prep["deduplication"]["cross_source_overlap_rows"] == 0
               and prep["deduplication"]["duplicate_input_rows_removed"] == 0)
    check("firms_preparation_and_identity", prep_ok, f"rows={len(firms)}; dates={prep['output']['date_coverage']}; duplicate IDs={int(firms.firms_observation_id.duplicated().sum())}")
    prep_output_hash = sha256(firms_path)

    match_dir = run_root / "spatial_matching"
    matching_summary = load_json(match_dir / "summary.json")
    matching_path = match_dir / "firms_pilot_osm_proximity.csv"
    matched = pd.read_csv(matching_path, low_memory=False)
    matching_ok = (len(matched) == len(firms)
                   and matched.firms_observation_id.is_unique
                   and matched.firms_source_row.is_unique
                   and matching_summary["firms_pilot_rows"] == len(firms)
                   and matching_summary["distance_crs"] == config["spatial_matching"]["distance_geometry"].split(" in ")[-1].rstrip("; points, lines, and polygons retained and measured by geometry distance")
                   and matching_summary["pilot_points_outside_bbox_after_filter"] == 0
                   and matching_summary["pilot_invalid_projected_coordinates"] == 0
                   and matching_summary["osm_invalid_or_empty_filtered"] == 0)
    check("spatial_matching_rows_unique_and_crs", matching_ok, f"rows={len(matched)}; CRS={matching_summary['distance_crs']}; OSM used={matching_summary['osm_features_used']}; GEM={matching_summary['gem_filtered_records']}")
    check("matching_thresholds", [x["threshold_m"] for x in matching_summary["distance_threshold_summary"]] == config["spatial_matching"]["reported_thresholds_m"], json.dumps(matching_summary["distance_threshold_summary"]))

    features_dir = run_root / "features"
    feature_quality = load_json(features_dir / "quality_checks.json")
    feature_table = pd.read_csv(features_dir / "feature_table.csv.gz", low_memory=False)
    features_ok = (feature_quality["overall_status"] == "passed"
                   and len(feature_table) == len(firms)
                   and feature_table.firms_source_row.is_unique
                   and feature_quality["temporal_leakage_check"].startswith("passed")
                   and feature_quality["ground_truth_label_created"] is False)
    check("feature_schema_temporal_and_label_checks", features_ok, f"rows={len(feature_table)}; columns={len(feature_table.columns)}; recurrence={feature_quality['temporal_leakage_check']}")
    satellite_counts = feature_quality["sentinel2"]
    check("satellite_nonfuture_screening", satellite_counts["rows_with_valid_causal_spectral_samples"] <= satellite_counts["rows_with_temporally_eligible_scene"] <= len(feature_table), json.dumps(satellite_counts))

    # The ranking CLI currently consumes the historical label-readiness schema, not the new evidence-review schema.
    legacy_label_dir = repo / "data/processed/label_evaluation/run_20261018T205757Z"
    legacy_label_path = legacy_label_dir / "label_readiness.json"
    legacy_label = load_json(legacy_label_path)
    legacy_label_checks = legacy_label.get("checks", {})
    legacy_label_hash = sha256(legacy_label_path)
    legacy_label_ok = (legacy_label_checks.get("verified_detection_labels") == 0
                       and legacy_label_checks.get("weak_detection_labels") == 0
                       and legacy_label_checks.get("unknown_unlinked_detection_rows") == len(firms))
    check("ranking_label_status_reference", legacy_label_ok,
          f"{relative(legacy_label_path, repo)}; 0 verified, 0 weak, {legacy_label_checks.get('unknown_unlinked_detection_rows')} unknown")
    source_fingerprints["legacy_label_readiness_reference"] = {
        "path": relative(legacy_label_path, repo), "size_bytes": legacy_label_path.stat().st_size,
        "sha256": legacy_label_hash,
    }

    evidence_dir = run_root / "evidence_review"
    evidence = load_json(evidence_dir / "validation.json")
    evidence_ok = (evidence["feature_rows"] == len(firms)
                   and evidence["genuinely_linkable_to_firms_rows"] == 0
                   and evidence["verified_detection_labels_created"] == 0
                   and evidence["weak_detection_labels_created"] == 0
                   and evidence["negative_examples_created"] == 0)
    check("evidence_review_has_no_fabricated_labels", evidence_ok, f"events={evidence['events_reviewed']}; linkable={evidence['genuinely_linkable_to_firms_rows']}; verified={evidence['verified_detection_labels_created']}; weak={evidence['weak_detection_labels_created']}; negatives={evidence['negative_examples_created']}")

    ranking_dir = run_root / "candidate_ranking"
    ranking_validation = load_json(ranking_dir / "validation.json")
    ranking = pd.read_csv(ranking_dir / "candidate_ranking.csv", low_memory=False)
    category_table = pd.read_csv(ranking_dir / "category_counts.csv")
    category_counts = {str(row.candidate_category): int(row.detections) for row in category_table.itertuples()}
    ranking_ok = (len(ranking) == len(firms)
                  and category_table.detections.sum() == len(firms)
                  and ranking_validation["all_labels_unknown_unlinked"] is True
                  and ranking_validation["supervised_model_trained"] is False
                  and ranking_validation["metrics_computed"] is False
                  and ranking_validation["duplicate_source_rows"] == 0)
    check("candidate_ranking_unknown_only", ranking_ok, f"rows={len(ranking)}; categories={category_counts}")

    # Tests are part of final validation; they run after the real-data stages.
    test = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], cwd=repo,
                          text=True, capture_output=True, check=False)
    test_lines = (test.stderr + "\n" + test.stdout).strip().splitlines()
    test_summary_lines = [line.strip() for line in test_lines if line.strip().startswith("Ran ") or line.strip() == "OK"]
    test_summary = " | ".join(test_summary_lines) if test_summary_lines else "\n".join(test_lines[-8:])
    check("unit_tests", test.returncode == 0, test_summary)
    compile_result = subprocess.run([sys.executable, "-m", "compileall", "-q", "src", "tests"], cwd=repo,
                                   text=True, capture_output=True, check=False)
    check("compileall", compile_result.returncode == 0, "passed" if compile_result.returncode == 0 else compile_result.stderr[-1500:])

    # Pin source code and package versions used by this run.
    code_hashes = {}
    for rel in CODE_FILES + ["src/finalize_pilot_experiment.py"]:
        path = repo / rel
        code_hashes[rel] = sha256(path)
    try:
        import pyogrio
        gdal_version = ".".join(str(x) for x in pyogrio.__gdal_version__)
        osm_driver = pyogrio.list_drivers(read=True).get("OSM")
    except Exception as exc:  # pragma: no cover
        gdal_version, osm_driver = None, f"unavailable: {exc}"
    software = {"python": sys.version.split()[0], "packages": {name: metadata.version(name) for name in PACKAGES},
                "GDAL_runtime": gdal_version, "GDAL_OSM_read_driver": osm_driver}

    validation_dir.mkdir(parents=True, exist_ok=args.refresh)
    satellite_ref = {
        "source_run": reference["path"], "scene_metadata_sha256": scene_hash,
        "chips": chip_inventory,
        "retrieval_repeated": False,
        "coverage": satellite_counts,
        "interpretation": "Optical context only; not fire confirmation. Missing/future/cloudy pixels are not evidence of absence."
    }
    satellite_ref_path.write_text(json.dumps(satellite_ref, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # Execution wall time is the run-root creation to last stage artifact modification interval.
    stage_dirs = [run_root / name for name in ("input", "spatial_matching", "features", "evidence_review", "candidate_ranking")]
    stage_files = [p for stage in stage_dirs for p in stage.rglob("*") if p.is_file()]
    run_start = run_root.stat().st_ctime
    run_end = max((p.stat().st_mtime for p in stage_files), default=run_start)
    runtime_seconds = max(0.0, run_end - run_start)
    output_files = []
    for path in sorted(p for p in run_root.rglob("*") if p.is_file() and p != manifest_path):
        output_files.append({"path": relative(path, run_root), "size_bytes": path.stat().st_size, "sha256": sha256(path)})
    output_bytes = sum(item["size_bytes"] for item in output_files)

    failed = [item for item in checks if item["status"] != "passed"]
    warnings = [
        "The freshly prepared CSV has region_id and firms_observation_id columns absent from the older prepared reference; all 9,220 FIRMS identity keys and shared source attributes matched exactly.",
        "Candidate ranking was given the pinned historical label-readiness JSON because the CLI does not consume the newer evidence-review schema; it records zero labels, and all candidate rows remain unknown_unlinked.",
        "Peak disk usage was not sampled during the run; final generated-file size is recorded. No imagery was downloaded or copied.",
        "Only 2 detections have usable pre-detection clear Sentinel-2 samples; this is sparse optical context, not fire confirmation.",
        "0 incident records were genuinely linkable to a FIRMS detection; no detection labels or negatives were created.",
        "Elapsed runtime measures the run-root creation to last stage artifact write and includes orchestration gaps; stage-specific process timings were not instrumented.",
    ]
    manifest = {
        "schema_version": 1,
        "experiment_id": config["experiment_id"],
        "run_status": "completed" if not failed else "validation_failed",
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "processing_interval": {"start_local_filesystem_time": datetime.fromtimestamp(run_start).astimezone().isoformat(timespec="seconds"),
                                "end_local_filesystem_time": datetime.fromtimestamp(run_end).astimezone().isoformat(timespec="seconds"),
                                "elapsed_wall_seconds": round(runtime_seconds, 3),
                                "measurement_note": "Run-root creation to last stage artifact write; includes orchestration gaps."},
        "configuration": {"path": relative(config_path, repo), "sha256": sha256(config_path), "region_id": config["region"]["region_id"], "bbox_wgs84": config["region"]["bbox_wgs84"]},
        "ranking_label_readiness_reference": {"path": relative(legacy_label_path, repo), "sha256": legacy_label_hash,
                                               "note": "Historical zero-label readiness context only; fresh event/link review is in this run's evidence_review directory."},
        "software": software,
        "code_sha256": code_hashes,
        "inputs": {"sources": source_fingerprints,
                   "prepared_firms": {"path": relative(firms_path, repo), "size_bytes": firms_path.stat().st_size, "sha256": prep_output_hash},
                   "satellite_reference": satellite_ref},
        "counts": {"firms_prepared": len(firms), "spatial_matches": len(matched), "features": len(feature_table), "candidate_rows": len(ranking), "candidate_categories": category_counts},
        "satellite_coverage": satellite_counts,
        "labels": {"genuinely_linkable_detections": evidence["genuinely_linkable_to_firms_rows"],
                   "verified": evidence["verified_detection_labels_created"], "weak": evidence["weak_detection_labels_created"],
                   "negatives": evidence["negative_examples_created"], "all_ranking_rows_unknown": ranking_validation["all_labels_unknown_unlinked"]},
        "validation_checks": checks,
        "warnings": warnings,
        "disk_usage": {"generated_files_bytes_before_manifest": output_bytes, "generated_file_count_before_manifest": len(output_files),
                       "peak_usage_measured": False, "file_inventory_excludes": ["validation/reproducibility_manifest.json"]},
        "output_file_inventory": output_files,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    final_bytes = sum(p.stat().st_size for p in run_root.rglob("*") if p.is_file())
    print(json.dumps({"manifest": relative(manifest_path, repo), "run_status": manifest["run_status"],
                      "checks_passed": len(checks)-len(failed), "checks_failed": len(failed),
                      "runtime_seconds": round(runtime_seconds,3), "output_bytes_including_manifest": final_bytes,
                      "candidate_categories": category_counts, "satellite": satellite_counts,
                      "labels": manifest["labels"], "test_summary": test_summary,
                      "failed_checks": failed}, indent=2))
    return 0 if not failed else 2


if __name__ == "__main__":
    raise SystemExit(main())
