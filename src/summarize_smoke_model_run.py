"""Attach provenance to smoke-model predictions and create review figures."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio
from sklearn.metrics import (ConfusionMatrixDisplay, PrecisionRecallDisplay,
                             RocCurveDisplay)

from src.train_smoke_model import _metrics, _select_training_rows

ROOT = Path(__file__).resolve().parents[1]


def _rgb(path: Path) -> np.ndarray:
    with rasterio.open(path) as src:
        values = src.read((4, 3, 2)).astype(np.float32)
    result = []
    for channel in values:
        low, high = np.percentile(channel, (2, 98))
        result.append(np.clip((channel - low) / max(float(high - low), 1.0), 0, 1))
    return np.stack(result, axis=-1)


def summarize(manifest_path: Path, dataset_dir: Path, train_run_dir: Path,
              output_dir: Path, training_sample_cap: int = 4000, seed: int = 20261117) -> Path:
    if output_dir.exists():
        raise FileExistsError(f"Refusing to overwrite {output_dir}")
    manifest = pd.read_csv(manifest_path)
    test_rows = manifest[manifest.split == "test"].reset_index(drop=True)
    raw = pd.read_csv(train_run_dir / "test_predictions.csv")
    if len(raw) != len(test_rows) or not np.array_equal(raw.label.to_numpy(), test_rows.label.to_numpy()):
        raise ValueError("Prediction rows do not align with the manifest's stable test ordering")
    config = json.loads((ROOT / "models" / "thermoscope_smoke_tiny_v1.json").read_text(encoding="utf-8"))
    threshold = float(config["decision_threshold"])
    pred = raw.prediction.to_numpy(dtype=int)
    scores = raw.smoke_score_uncalibrated.to_numpy(dtype=float)
    metrics = _metrics(test_rows.label.to_numpy(dtype=int), scores, threshold)
    enriched = test_rows[["sample_id", "source_relative_path", "label", "label_text", "site_group_id",
                          "acquisition_datetime_utc", "longitude", "latitude", "split"]].copy()
    enriched["smoke_score_uncalibrated"] = scores
    enriched["decision_threshold"] = threshold
    enriched["prediction"] = pred
    enriched["error_type"] = np.select(
        [(enriched.label == 0) & (enriched.prediction == 1),
         (enriched.label == 1) & (enriched.prediction == 0)],
        ["false_positive_vs_manual_smoke_label", "false_negative_vs_manual_smoke_label"], default="correct_vs_manual_smoke_label"
    )
    train_sample = _select_training_rows(manifest[manifest.split == "train"], training_sample_cap, seed)
    output_dir.mkdir(parents=True)
    enriched.to_csv(output_dir / "test_predictions_with_provenance.csv", index=False)
    train_sample[["sample_id", "source_relative_path", "label", "label_text", "site_group_id",
                  "acquisition_datetime_utc", "longitude", "latitude"]].to_csv(
        output_dir / "training_sample_manifest.csv", index=False
    )
    error_rows = enriched[enriched.error_type != "correct_vs_manual_smoke_label"]
    error_rows.to_csv(output_dir / "test_error_review_queue.csv", index=False)
    (output_dir / "metrics.json").write_text(json.dumps({
        "model": config["model_name"], "test_metrics": metrics,
        "training_sites": int(manifest[manifest.split == "train"].site_group_id.nunique()),
        "validation_sites": int(manifest[manifest.split == "validation"].site_group_id.nunique()),
        "test_sites": int(manifest[manifest.split == "test"].site_group_id.nunique()),
        "test_rows": len(enriched), "error_counts": enriched.error_type.value_counts().to_dict(),
        "label_warning": "Errors are disagreements with subjective manual visible-smoke labels; no fire/source claims are supported.",
    }, indent=2) + "\n", encoding="utf-8")

    figure, axes = plt.subplots(2, 2, figsize=(12, 9))
    ConfusionMatrixDisplay.from_predictions(test_rows.label, pred, labels=[0, 1],
                                            display_labels=["No visible smoke", "Visible smoke"],
                                            cmap="Blues", ax=axes[0, 0], colorbar=False)
    axes[0, 0].set_title("Location-held-out test confusion matrix")
    RocCurveDisplay.from_predictions(test_rows.label, scores, ax=axes[0, 1])
    axes[0, 1].set_title("ROC curve")
    PrecisionRecallDisplay.from_predictions(test_rows.label, scores, ax=axes[1, 0])
    axes[1, 0].set_title("Precision–recall curve")
    axes[1, 1].hist(scores[test_rows.label.to_numpy() == 0], bins=30, alpha=.7, label="No visible smoke")
    axes[1, 1].hist(scores[test_rows.label.to_numpy() == 1], bins=30, alpha=.7, label="Visible smoke")
    axes[1, 1].axvline(threshold, color="black", linestyle="--", label=f"Validation threshold {threshold:.2f}")
    axes[1, 1].set(xlabel="Uncalibrated smoke score", ylabel="Images", title="Held-out score distribution")
    axes[1, 1].legend(fontsize=8)
    figure.suptitle("Manual visible-smoke label agreement · European 2019 sites")
    figure.tight_layout()
    figure.savefig(output_dir / "classification_evaluation.png", dpi=190)
    plt.close(figure)

    examples = pd.concat([
        enriched[enriched.error_type == "false_positive_vs_manual_smoke_label"].nlargest(4, "smoke_score_uncalibrated"),
        enriched[enriched.error_type == "false_negative_vs_manual_smoke_label"].nsmallest(4, "smoke_score_uncalibrated"),
    ])
    if not examples.empty:
        fig, axs = plt.subplots(2, 4, figsize=(14, 7))
        for axis, (_, row) in zip(axs.flat, examples.iterrows()):
            axis.imshow(_rgb(dataset_dir / Path(row.source_relative_path)))
            axis.set_title(f"{row.error_type.replace('_vs_manual_smoke_label', '')} · score {row.smoke_score_uncalibrated:.2f}\nsite {row.site_group_id} · {row.acquisition_datetime_utc[:10]}", fontsize=8)
            axis.axis("off")
        for axis in list(axs.flat)[len(examples):]:
            axis.axis("off")
        fig.suptitle("High-confidence disagreements to review visually; no cloud/source cause assigned")
        fig.tight_layout()
        fig.savefig(output_dir / "classification_error_examples.png", dpi=190)
        plt.close(fig)
    return output_dir


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--dataset-dir", type=Path, required=True)
    parser.add_argument("--train-run-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(f"Wrote {summarize(args.manifest, args.dataset_dir, args.train_run_dir, args.output_dir)}")


if __name__ == "__main__":
    main()
