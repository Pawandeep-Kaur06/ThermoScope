"""Train and evaluate a compact U-Net using the dataset's manual smoke masks."""
from __future__ import annotations

import argparse
import json
import random
import time
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio
import torch
from PIL import Image, ImageDraw
from sklearn.metrics import confusion_matrix
from torch import nn
from torch.utils.data import DataLoader, Dataset

from src.thermoscope_app.smoke_model import CHANNEL_MEANS, CHANNEL_STDS, MODEL_BAND_INDEXES, build_tiny_smoke_unet


def rasterize_labelstudio_mask(json_path: Path, *, scale: float = 1.2) -> np.ndarray:
    """Convert smoke polygons to a 120x120 mask using the source README scale."""
    annotation = json.loads(json_path.read_text(encoding="utf-8"))
    canvas = Image.new("L", (120, 120), 0)
    draw = ImageDraw.Draw(canvas)
    polygons = 0
    for completion in annotation.get("completions", []):
        for result in completion.get("result", []):
            value = result.get("value", {})
            if "smoke" not in value.get("polygonlabels", []):
                continue
            points = value.get("points", [])
            if len(points) < 3:
                continue
            coords = [(float(x) * scale, float(y) * scale) for x, y in points]
            if not np.isfinite(np.asarray(coords)).all():
                raise ValueError(f"Non-finite polygon coordinate in {json_path}")
            draw.polygon(coords, fill=1)
            polygons += 1
    if polygons == 0:
        raise ValueError(f"No smoke polygon annotation in {json_path}")
    return (np.asarray(canvas, dtype=np.uint8) > 0).astype(np.uint8)


class SegmentationDataset(Dataset):
    def __init__(self, rows: pd.DataFrame, dataset_dir: Path, *, training: bool):
        self.rows = rows.reset_index(drop=True)
        self.dataset_dir = dataset_dir
        self.training = training

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, index: int):
        row = self.rows.iloc[index]
        image_path = self.dataset_dir / Path(str(row.source_relative_path))
        with rasterio.open(image_path) as src:
            image = src.read(MODEL_BAND_INDEXES).astype(np.float32)
        image = np.pad(image, ((0, 0), (0, 120 - image.shape[1]), (0, 120 - image.shape[2])), mode="edge")
        image = (image - CHANNEL_MEANS[:, None, None]) / CHANNEL_STDS[:, None, None]
        if int(row.label) == 1:
            mask_path = self.dataset_dir / Path(str(row.segmentation_json))
            mask = rasterize_labelstudio_mask(mask_path)
        else:
            mask = np.zeros((120, 120), dtype=np.uint8)
        if self.training:
            top, left = random.randrange(31), random.randrange(31)
            image, mask = image[:, top:top + 90, left:left + 90], mask[top:top + 90, left:left + 90]
            if random.random() < .5:
                image, mask = image[:, :, ::-1], mask[:, ::-1]
            if random.random() < .5:
                image, mask = image[:, ::-1, :], mask[::-1, :]
            turns = random.randrange(4)
            image, mask = np.rot90(image, turns, axes=(1, 2)), np.rot90(mask, turns)
        else:
            image, mask = image[:, 15:105, 15:105], mask[15:105, 15:105]
        return (torch.from_numpy(np.ascontiguousarray(image, dtype=np.float32)),
                torch.from_numpy(np.ascontiguousarray(mask[None], dtype=np.float32)))


def _balanced_rows(rows: pd.DataFrame, *, max_positive: int, seed: int, training: bool) -> pd.DataFrame:
    positive = rows[(rows.label == 1) & (rows.segmentation_status == "polygon_annotation")]
    negative = rows[rows.label == 0]
    if training and max_positive and len(positive) > max_positive:
        positive = positive.sample(n=max_positive, random_state=seed)
    if len(negative) > len(positive):
        negative = negative.sample(n=len(positive), random_state=seed + 1)
    return pd.concat([positive, negative]).sample(frac=1, random_state=seed).reset_index(drop=True)


def _score(model, loader, device, threshold: float):
    truth_chunks, prediction_chunks = [], []
    with torch.inference_mode():
        for images, masks in loader:
            logits = model(images.to(device))
            prediction = torch.sigmoid(logits).cpu().numpy() >= threshold
            truth_chunks.append(masks.numpy().astype(np.uint8).reshape(-1))
            prediction_chunks.append(prediction.astype(np.uint8).reshape(-1))
    truth = np.concatenate(truth_chunks).astype(bool)
    pred = np.concatenate(prediction_chunks).astype(bool)
    matrix = confusion_matrix(truth, pred, labels=[False, True])
    tn, fp, fn, tp = matrix.ravel()
    precision = tp / max(tp + fp, 1)
    recall = tp / max(tp + fn, 1)
    iou = tp / max(tp + fp + fn, 1)
    dice = 2 * tp / max(2 * tp + fp + fn, 1)
    return {"threshold": threshold, "pixel_precision": precision, "pixel_recall": recall,
            "pixel_iou": iou, "pixel_dice": dice, "confusion_matrix_true0_1_pred0_1": matrix.tolist(),
            "test_pixels": int(len(truth))}


def train(manifest_path: Path, dataset_dir: Path, output_dir: Path, model_path: Path,
          *, epochs: int = 2, batch_size: int = 2, max_positive: int = 256,
          seed: int = 20261117) -> dict[str, object]:
    for path in (output_dir, model_path, model_path.with_suffix(".json")):
        if path.exists():
            raise FileExistsError(f"Refusing to overwrite {path}")
    df = pd.read_csv(manifest_path)
    splits = {name: df[df.split == name].copy() for name in ("train", "validation", "test")}
    site_sets = {name: set(rows.site_group_id) for name, rows in splits.items()}
    if any(site_sets[a] & site_sets[b] for a, b in (("train", "validation"), ("train", "test"), ("validation", "test"))):
        raise ValueError("Location leakage detected")
    selected = {"train": _balanced_rows(splits["train"], max_positive=max_positive, seed=seed, training=True),
                "validation": _balanced_rows(splits["validation"], max_positive=0, seed=seed + 10, training=False),
                "test": _balanced_rows(splits["test"], max_positive=0, seed=seed + 20, training=False)}
    if any(rows.empty for rows in selected.values()):
        raise ValueError("Each split needs polygon-labelled positives and negative examples")
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.set_num_threads(min(4, torch.get_num_threads()))
    device = torch.device("cpu")
    loaders = {name: DataLoader(SegmentationDataset(rows, dataset_dir, training=name == "train"),
                                batch_size=batch_size, shuffle=name == "train", num_workers=0)
               for name, rows in selected.items()}
    model = build_tiny_smoke_unet().to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-4)
    # Foreground smoke pixels occupy a small share of chips; cap pos_weight to
    # prevent a few polygons dominating every gradient.
    positive_pixels = 0
    for row in selected["train"].itertuples():
        if row.label == 1:
            positive_pixels += int(rasterize_labelstudio_mask(dataset_dir / row.segmentation_json).sum())
    total_pixels = len(selected["train"]) * 120 * 120
    pos_weight = min(20.0, max(1.0, (total_pixels - positive_pixels) / max(positive_pixels, 1)))
    loss_fn = nn.BCEWithLogitsLoss(pos_weight=torch.tensor([pos_weight], dtype=torch.float32))
    started = time.monotonic()
    history = []
    best_loss, best_state = float("inf"), None
    for epoch in range(epochs):
        model.train()
        train_loss, count = 0.0, 0
        for images, masks in loaders["train"]:
            optimizer.zero_grad(set_to_none=True)
            logits = model(images)
            loss = loss_fn(logits, masks)
            loss.backward()
            optimizer.step()
            train_loss += float(loss.item()) * len(images)
            count += len(images)
        model.eval()
        val_loss, val_count = 0.0, 0
        with torch.inference_mode():
            for images, masks in loaders["validation"]:
                loss = loss_fn(model(images), masks)
                val_loss += float(loss.item()) * len(images)
                val_count += len(images)
        train_mean, val_mean = train_loss / max(count, 1), val_loss / max(val_count, 1)
        history.append({"epoch": epoch + 1, "train_loss": train_mean, "validation_loss": val_mean})
        if val_mean < best_loss:
            best_loss = val_mean
            best_state = {key: value.detach().cpu().clone() for key, value in model.state_dict().items()}
        print(f"epoch={epoch + 1}/{epochs} train_loss={train_mean:.5f} validation_loss={val_mean:.5f}", flush=True)
    if best_state is None:
        raise RuntimeError("No segmentation checkpoint produced")
    model.load_state_dict(best_state)
    model.eval()
    y_val_chunks, p_val_chunks = [], []
    with torch.inference_mode():
        for images, masks in loaders["validation"]:
            probabilities = torch.sigmoid(model(images)).numpy()
            y_val_chunks.append(masks.numpy().astype(np.uint8).reshape(-1))
            p_val_chunks.append(probabilities.astype(np.float32).reshape(-1))
    y_val, p_val = np.concatenate(y_val_chunks).astype(bool), np.concatenate(p_val_chunks)
    thresholds = np.linspace(.05, .95, 37)
    threshold = max(thresholds, key=lambda t: _score_from_arrays(y_val, p_val, t)["pixel_iou"])
    metrics = _score(model, loaders["test"], device, float(threshold))

    output_dir.mkdir(parents=True)
    model_path.parent.mkdir(parents=True, exist_ok=True)
    if model_path.exists() or model_path.with_suffix(".json").exists():
        raise FileExistsError("Segmentation checkpoint/config exists; refusing overwrite")
    temp_model = model_path.with_name(model_path.name + ".tmp")
    torch.save(best_state, temp_model)
    temp_model.replace(model_path)
    config = {
        "architecture": "thermoscope_tiny_unet_12band", "model_name": "ThermoScope visible-smoke Tiny U-Net v1",
        "task": "segment manually annotated visible smoke polygons", "input_channels": 12,
        "source_band_indexes_1based": list(MODEL_BAND_INDEXES), "crop_size": 90,
        "polygon_scale": 1.2, "decision_threshold": float(threshold), "score_is_calibrated_probability": False,
        "seed": seed, "epochs": epochs, "batch_size": batch_size, "max_positive_training_images": max_positive,
        "actual_train_images": len(selected["train"]), "train_polygon_images": int((selected["train"].label == 1).sum()),
        "validation_polygon_images": int((selected["validation"].label == 1).sum()),
        "test_polygon_images": int((selected["test"].label == 1).sum()), "positive_pixel_weight": pos_weight,
        "split_manifest": str(manifest_path), "split_method": "site-grouped new split; not original paper partition",
        "trained_at_utc": datetime.now(timezone.utc).isoformat(), "runtime_seconds": round(time.monotonic() - started, 3),
        "scientific_limit": "Mask labels are subjective manual visible-smoke polygons, not fire labels.",
    }
    model_path.with_suffix(".json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    report = {"metrics": metrics, "split_sample_counts": {name: {"images": len(rows),
              "positive_polygon_images": int((rows.label == 1).sum()), "negative_images": int((rows.label == 0).sum()),
              "unique_sites": int(rows.site_group_id.nunique())} for name, rows in selected.items()},
              "interpretation": "Pixel metrics compare predictions with manually drawn visible-smoke polygons, not independent pixel ground truth or fire labels."}
    (output_dir / "metrics.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    pd.DataFrame(history).to_csv(output_dir / "training_history.csv", index=False)
    figure, axis = plt.subplots(figsize=(6, 4))
    axis.plot([r["epoch"] for r in history], [r["train_loss"] for r in history], label="Train")
    axis.plot([r["epoch"] for r in history], [r["validation_loss"] for r in history], label="Validation")
    axis.set(xlabel="Epoch", ylabel="BCE loss", title="Smoke mask training")
    axis.legend(); figure.tight_layout(); figure.savefig(output_dir / "loss.png", dpi=180); plt.close(figure)
    return report


def _score_from_arrays(truth: np.ndarray, probabilities: np.ndarray, threshold: float) -> dict[str, float]:
    predicted = probabilities >= threshold
    tp = int(np.logical_and(truth, predicted).sum())
    fp = int(np.logical_and(~truth, predicted).sum())
    fn = int(np.logical_and(truth, ~predicted).sum())
    return {"pixel_iou": tp / max(tp + fp + fn, 1), "pixel_dice": 2 * tp / max(2 * tp + fp + fn, 1)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--dataset-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=2)
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument("--max-positive", type=int, default=256)
    parser.add_argument("--seed", type=int, default=20261117)
    args = parser.parse_args()
    print(json.dumps(train(args.manifest, args.dataset_dir, args.output_dir, args.model_path,
                           epochs=args.epochs, batch_size=args.batch_size,
                           max_positive=args.max_positive, seed=args.seed), indent=2))


if __name__ == "__main__":
    main()
