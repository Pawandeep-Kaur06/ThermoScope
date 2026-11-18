"""Inventory smoke images and create deterministic location-grouped splits.

The Zenodo tarballs only contain positive/negative folders, not published split
IDs. This script creates a new location-held-out split; it never claims to
reproduce the paper's unavailable site assignment.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path

import rasterio
from pyproj import Transformer
from sklearn.model_selection import GroupShuffleSplit

FILENAME = re.compile(r"^(?P<site>.+?)_(?P<date>2019-\d{2}-\d{2})T(?P<hour>\d{2})[_:](?P<minute>\d{2})[_:](?P<second>\d{2}(?:\.\d+)?)Z_(?P<sequence>\d+)$")
FIELDS = [
    "sample_id", "source_relative_path", "label", "label_text", "label_source",
    "site_group_id", "acquisition_datetime_utc", "scene_sequence", "longitude",
    "latitude", "crs", "width", "height", "band_count", "dtype",
    "segmentation_json", "segmentation_status", "split",
]


def _parse_stem(stem: str) -> dict[str, str]:
    match = FILENAME.match(stem)
    if not match:
        raise ValueError(f"Unrecognized dataset image filename: {stem}")
    values = match.groupdict()
    values["acquisition_datetime_utc"] = (
        f"{values['date']}T{values['hour']}:{values['minute']}:{values['second']}Z"
    )
    return values


def _location_split(records: list[dict[str, object]], seed: int = 20261117) -> dict[str, str]:
    sites = sorted({str(row["site_group_id"]) for row in records})
    if len(sites) < 10:
        raise ValueError("Too few independent site groups for a train/validation/test split.")
    site_labels: dict[str, list[int]] = {}
    for row in records:
        site_labels.setdefault(str(row["site_group_id"]), []).append(int(row["label"]))
    site_rows = [{"site": site, "positive_fraction": sum(site_labels[site]) / len(site_labels[site]),
                  "image_count": len(site_labels[site])} for site in sites]
    # Repeated, seeded group shuffle candidates are scored for approximate
    # 70/15/15 image proportions and class balance without splitting a site.
    best: tuple[float, dict[str, str]] | None = None
    for trial in range(50):
        first = next(GroupShuffleSplit(n_splits=1, train_size=.70, random_state=seed + trial)
                     .split(site_rows, groups=sites))
        train_sites = {sites[i] for i in first[0]}
        holdout_sites = [site for site in sites if site not in train_sites]
        second = next(GroupShuffleSplit(n_splits=1, train_size=.50, random_state=seed + 1000 + trial)
                      .split(holdout_sites, groups=holdout_sites))
        val_sites = {holdout_sites[i] for i in second[0]}
        test_sites = set(holdout_sites) - val_sites
        assignment = {site: "train" for site in train_sites}
        assignment.update({site: "validation" for site in val_sites})
        assignment.update({site: "test" for site in test_sites})
        split_counts = {key: [0, 0] for key in ("train", "validation", "test")}
        for row in records:
            split_counts[assignment[str(row["site_group_id"])]][int(row["label"])] += 1
        totals = {key: sum(value) for key, value in split_counts.items()}
        total = sum(totals.values())
        fractions = {"train": .70, "validation": .15, "test": .15}
        score = sum(abs(totals[k] / total - fractions[k]) for k in fractions)
        global_positive = sum(int(row["label"]) for row in records) / total
        score += sum(abs(split_counts[k][1] / max(totals[k], 1) - global_positive) for k in fractions)
        if best is None or score < best[0]:
            best = (score, assignment)
    assert best is not None
    return best[1]


def build_manifest(dataset_dir: Path) -> tuple[list[dict[str, object]], dict[str, object]]:
    image_root = dataset_dir / "images"
    label_root = dataset_dir / "segmentation_labels"
    image_paths = sorted(image_root.rglob("*.tif"))
    if not image_paths:
        raise FileNotFoundError(f"No image GeoTIFF files under {image_root}")
    masks = {p.stem.removesuffix("_features"): p for p in label_root.glob("*_features.json")}
    inventory: list[dict[str, object]] = []
    schema_counts: dict[tuple[object, ...], int] = {}
    duplicate_ids: set[str] = set()
    seen_stems: set[str] = set()
    for path in image_paths:
        stem = path.stem
        if stem in seen_stems:
            duplicate_ids.add(stem)
        seen_stems.add(stem)
        parsed = _parse_stem(stem)
        label_text = path.parent.name.lower()
        if label_text not in {"positive", "negative"}:
            raise ValueError(f"Unexpected label folder {label_text!r} for {path}")
        with rasterio.open(path) as raster:
            if raster.count != 13 or not (1 <= raster.width <= 120 and 1 <= raster.height <= 120):
                raise ValueError(f"Unexpected raster shape/bands: {path} {raster.count} {raster.width}x{raster.height}")
            if any(dtype != "uint16" for dtype in raster.dtypes):
                raise ValueError(f"Unexpected raster dtype in {path}: {raster.dtypes}")
            if raster.crs is None:
                raise ValueError(f"Raster lacks CRS: {path}")
            schema = (raster.width, raster.height, raster.count, tuple(raster.dtypes), raster.crs.to_string())
            schema_counts[schema] = schema_counts.get(schema, 0) + 1
            bounds = raster.bounds
            transformer = Transformer.from_crs(raster.crs, "EPSG:4326", always_xy=True)
            longitude, latitude = transformer.transform((bounds.left + bounds.right) / 2,
                                                         (bounds.bottom + bounds.top) / 2)
        mask = masks.get(stem)
        segmentation_status = "not_annotated"
        if mask:
            annotation = json.loads(mask.read_text(encoding="utf-8"))
            polygon_count = sum(
                len(result.get("value", {}).get("points", [])) >= 3
                for completion in annotation.get("completions", [])
                for result in completion.get("result", [])
                if "points" in result.get("value", {})
            )
            segmentation_status = "polygon_annotation" if polygon_count else "empty_annotation_review_required"
        inventory.append({
            "sample_id": stem,
            "source_relative_path": path.relative_to(dataset_dir).as_posix(),
            "label": int(label_text == "positive"), "label_text": label_text,
            "label_source": "Zenodo manual visible-smoke presence/absence class",
            "site_group_id": parsed["site"],
            "acquisition_datetime_utc": parsed["acquisition_datetime_utc"],
            "scene_sequence": parsed["sequence"], "longitude": longitude, "latitude": latitude,
            "crs": schema[-1], "width": schema[0], "height": schema[1],
            "band_count": schema[2], "dtype": "uint16",
            "segmentation_json": str(mask.relative_to(dataset_dir).as_posix()) if mask else "",
            "segmentation_status": segmentation_status,
        })
    if duplicate_ids:
        raise ValueError(f"Duplicate image identifiers found: {sorted(duplicate_ids)[:5]}")
    assignment = _location_split(inventory)
    for row in inventory:
        row["split"] = assignment[str(row["site_group_id"])]
    split_sites: dict[str, set[str]] = {name: set() for name in ("train", "validation", "test")}
    split_counts = {name: {"negative": 0, "positive": 0, "images": 0, "sites": 0,
                           "polygon_masks": 0, "empty_masks": 0} for name in split_sites}
    for row in inventory:
        split = str(row["split"])
        split_sites[split].add(str(row["site_group_id"]))
        counts = split_counts[split]
        counts["images"] += 1
        counts[str(row["label_text"])] += 1
        counts["polygon_masks"] += row["segmentation_status"] == "polygon_annotation"
        counts["empty_masks"] += row["segmentation_status"] == "empty_annotation_review_required"
    for split, sites_in_split in split_sites.items():
        split_counts[split]["sites"] = len(sites_in_split)
    if any(split_sites[a] & split_sites[b] for a, b in (("train", "validation"), ("train", "test"), ("validation", "test"))):
        raise AssertionError("Location leakage in generated split")
    quality = {
        "image_count": len(inventory), "unique_site_count": len({str(r["site_group_id"]) for r in inventory}),
        "segmentation_json_count": len(masks), "matched_segmentation_count": sum(bool(r["segmentation_json"]) for r in inventory),
        "schema_counts": [{"width": s[0], "height": s[1], "bands": s[2], "dtypes": list(s[3]), "crs": s[4], "count": c}
                          for s, c in schema_counts.items()],
        "split_counts": split_counts,
        "split_method": "new deterministic GroupShuffleSplit by site; not the paper's original split because site assignment files were not present in the Zenodo archives",
        "seed": 20261117,
        "class_definition": {"positive": "manual image annotation: visible smoke plume present", "negative": "manual image annotation: no visible smoke plume"},
        "label_caveat": "not fire/no-fire or industrial thermal-source labels",
    }
    return inventory, quality


def prepare(dataset_dir: Path, output_dir: Path) -> Path:
    if output_dir.exists():
        raise FileExistsError(f"Refusing to overwrite {output_dir}")
    inventory, quality = build_manifest(dataset_dir)
    output_dir.mkdir(parents=True)
    with (output_dir / "manifest.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(inventory)
    (output_dir / "dataset_quality.json").write_text(json.dumps(quality, indent=2) + "\n", encoding="utf-8")
    return output_dir


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(f"Prepared {prepare(args.dataset_dir, args.output_dir)}")


if __name__ == "__main__":
    main()
