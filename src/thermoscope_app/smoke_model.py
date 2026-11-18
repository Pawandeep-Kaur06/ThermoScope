"""Smoke-plume CV preprocessing and inference contracts.

This module predicts only visible-smoke evidence in compatible Sentinel-2
multispectral GeoTIFFs. It is intentionally separate from FIRMS/OSM evidence.
"""
from __future__ import annotations

import json
import base64
import io
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

EXPECTED_ALL_BANDS = ("B01", "B02", "B03", "B04", "B05", "B06", "B07", "B08", "B8A", "B09", "B10", "B11", "B12")
MODEL_BAND_INDEXES = (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 13)
CHANNEL_MEANS = np.array([809.2, 900.5, 1061.4, 1091.7, 1384.5, 1917.8,
                          2105.2, 2186.3, 2224.8, 2346.8, 1901.2, 1460.42], dtype=np.float32)
CHANNEL_STDS = np.array([441.8, 624.7, 640.8, 718.1, 669.1, 767.5,
                         843.3, 947.9, 882.4, 813.7, 716.9, 674.8], dtype=np.float32)
MAX_MODEL_DIMENSION = 120


class SmokeInputError(ValueError):
    """Uploaded raster does not satisfy the published smoke-model contract."""


def _normalized_band_name(description: str) -> str:
    text = "".join(ch for ch in description.upper() if ch.isalnum())
    if text.startswith("BAND"):
        text = text[4:]
    if text.isdigit():
        text = f"B{text.zfill(2)}"
    if text == "B8A":
        return text
    if text.startswith("B") and text[1:].isdigit():
        return f"B{text[1:].zfill(2)}"
    return text


def validate_band_order(descriptions: tuple[str | None, ...], *, confirmed: bool = False) -> str:
    """Require metadata verification or explicit uploader confirmation.

    Dataset chips do not carry band descriptions, so a deliberate confirmation
    is required for that known 13-band order. RGB/four-band files are rejected.
    """
    if len(descriptions) != 13:
        raise SmokeInputError("Smoke model requires a 13-band Sentinel-2 L2A GeoTIFF; RGB and four-band chips are incompatible.")
    cleaned = tuple(_normalized_band_name(str(value)) if value else "" for value in descriptions)
    if any(cleaned):
        if cleaned != EXPECTED_ALL_BANDS:
            raise SmokeInputError(f"Band metadata order mismatch: expected {', '.join(EXPECTED_ALL_BANDS)}.")
        return "band_descriptions_verified"
    if confirmed:
        return "uploader_confirmed_published_band_order"
    raise SmokeInputError("Band descriptions are absent. Confirm the 13-band Sentinel-2 L2A order before smoke inference.")


def prepare_stack_from_dataset(dataset: Any, *, band_order_confirmed: bool = False,
                               crop_size: int = 120) -> tuple[np.ndarray, str]:
    """Read the 12 model channels, pad undersized rasters like the source code,
    center crop for inference, and apply the published channel normalization.
    Returns CHW float32 and the source of band-order validation.
    """
    if dataset.width > MAX_MODEL_DIMENSION or dataset.height > MAX_MODEL_DIMENSION:
        raise SmokeInputError("Smoke inference requires a 90–120 pixel Sentinel-2 chip; crop larger scenes before upload.")
    validation = validate_band_order(tuple(dataset.descriptions), confirmed=band_order_confirmed)
    if dataset.width < 90 or dataset.height < 90:
        raise SmokeInputError("Smoke model needs at least a 90×90 pixel image window.")
    if dataset.count != 13:
        raise SmokeInputError("Smoke model requires exactly 13 source bands.")
    if any(dtype != "uint16" for dtype in dataset.dtypes):
        raise SmokeInputError("Smoke model expects uint16 Sentinel-2 reflectance samples in the training scale.")
    array = dataset.read(MODEL_BAND_INDEXES).astype(np.float32, copy=False)
    if not np.isfinite(array).all():
        raise SmokeInputError("Image has non-finite raster values.")
    valid = np.all(dataset.read_masks(MODEL_BAND_INDEXES) > 0, axis=0)
    if float(valid.mean()) < 0.5:
        raise SmokeInputError("More than half the multispectral chip is nodata or masked.")
    array = np.where(valid[None, :, :], array, CHANNEL_MEANS[:, None, None])
    pad_h, pad_w = max(0, 120 - array.shape[1]), max(0, 120 - array.shape[2])
    if pad_h or pad_w:
        array = np.pad(array, ((0, 0), (0, pad_h), (0, pad_w)), mode="edge")
    if crop_size != 120:
        top, left = (120 - crop_size) // 2, (120 - crop_size) // 2
        array = array[:, top:top + crop_size, left:left + crop_size]
    array = (array - CHANNEL_MEANS[:, None, None]) / CHANNEL_STDS[:, None, None]
    return np.ascontiguousarray(array, dtype=np.float32), validation


def build_published_resnet50(*, pretrained: bool = False):
    """Construct the released modified ResNet-50 topology.

    The upstream code requests ImageNet-pretrained ResNet-50 then replaces its
    12-channel stem and binary head. We expose that download explicitly.
    """
    import torch
    from torchvision.models import ResNet50_Weights, resnet50

    weights = ResNet50_Weights.IMAGENET1K_V2 if pretrained else None
    model = resnet50(weights=weights)
    model.conv1 = torch.nn.Conv2d(12, 64, kernel_size=3, stride=2, padding=3, bias=False)
    model.fc = torch.nn.Linear(4 * 512, 1)
    return model


def build_tiny_smoke_cnn():
    """Low-memory 12-band baseline for CPU-only environments."""
    import torch
    from torch import nn

    def block(input_channels: int, output_channels: int) -> list[nn.Module]:
        return [nn.Conv2d(input_channels, output_channels, 3, padding=1, bias=False),
                nn.BatchNorm2d(output_channels), nn.ReLU(inplace=True), nn.MaxPool2d(2)]

    return nn.Sequential(
        *block(12, 16), *block(16, 32), *block(32, 64), *block(64, 96),
        nn.AdaptiveAvgPool2d(1), nn.Flatten(), nn.Dropout(0.25), nn.Linear(96, 1),
    )


def build_tiny_smoke_unet():
    """Compact U-Net for the dataset's 1,427 polygon-annotated plume masks."""
    import torch
    from torch import nn
    import torch.nn.functional as F

    class DoubleConv(nn.Module):
        def __init__(self, in_channels: int, out_channels: int):
            super().__init__()
            self.layers = nn.Sequential(
                nn.Conv2d(in_channels, out_channels, 3, padding=1, bias=False),
                nn.BatchNorm2d(out_channels), nn.ReLU(inplace=True),
                nn.Conv2d(out_channels, out_channels, 3, padding=1, bias=False),
                nn.BatchNorm2d(out_channels), nn.ReLU(inplace=True),
            )

        def forward(self, x):
            return self.layers(x)

    class TinyUNet(nn.Module):
        def __init__(self):
            super().__init__()
            self.enc1, self.enc2 = DoubleConv(12, 8), DoubleConv(8, 16)
            self.bottleneck = DoubleConv(16, 32)
            self.up2 = nn.ConvTranspose2d(32, 16, 2, stride=2)
            self.dec2 = DoubleConv(32, 16)
            self.up1 = nn.ConvTranspose2d(16, 8, 2, stride=2)
            self.dec1 = DoubleConv(16, 8)
            self.output = nn.Conv2d(8, 1, 1)

        def forward(self, x):
            first = self.enc1(x)
            second = self.enc2(F.max_pool2d(first, 2))
            center = self.bottleneck(F.max_pool2d(second, 2))
            up = self.up2(center)
            up = F.interpolate(up, size=second.shape[-2:], mode="bilinear", align_corners=False)
            up = self.dec2(torch.cat((up, second), dim=1))
            up = self.up1(up)
            up = F.interpolate(up, size=first.shape[-2:], mode="bilinear", align_corners=False)
            return self.output(self.dec1(torch.cat((up, first), dim=1)))

    return TinyUNet()


@lru_cache(maxsize=2)
def _load_checkpoint(checkpoint_path: str):
    import torch

    path = Path(checkpoint_path)
    checkpoint = torch.load(path, map_location="cpu", weights_only=True)
    config_path = path.with_suffix(".json")
    config = json.loads(config_path.read_text(encoding="utf-8")) if config_path.is_file() else {}
    architecture = config.get("architecture")
    if architecture not in {"published_resnet50_12band", "thermoscope_tiny_cnn_12band"}:
        raise SmokeInputError("Checkpoint architecture/configuration is missing or unsupported.")
    model = build_published_resnet50(pretrained=False) if architecture == "published_resnet50_12band" else build_tiny_smoke_cnn()
    model.load_state_dict(checkpoint)
    model.eval()
    return model


@lru_cache(maxsize=2)
def _load_segmentation_checkpoint(checkpoint_path: str):
    import torch

    path = Path(checkpoint_path)
    checkpoint = torch.load(path, map_location="cpu", weights_only=True)
    config_path = path.with_suffix(".json")
    config = json.loads(config_path.read_text(encoding="utf-8")) if config_path.is_file() else {}
    if config.get("architecture") != "thermoscope_tiny_unet_12band":
        raise SmokeInputError("Segmentation checkpoint configuration is missing or unsupported.")
    model = build_tiny_smoke_unet()
    model.load_state_dict(checkpoint)
    model.eval()
    return model, config


def predict_smoke_upload(filename: str, contents: bytes, *, checkpoint_path: Path,
                         band_order_confirmed: bool = False,
                         segmentation_checkpoint_path: Path | None = None) -> dict[str, Any]:
    """Return an explicit unavailable/incompatible state or a smoke score."""
    suffix = Path(filename).suffix.lower()
    if suffix not in {".tif", ".tiff"}:
        return {"status": "unsupported_input", "prediction": None,
                "message": "Visible-smoke inference requires a 13-band Sentinel-2 GeoTIFF; RGB files are not supported."}
    if not checkpoint_path.is_file():
        return {"status": "unavailable", "prediction": None,
                "message": "No trained smoke-plume model weights are installed."}
    try:
        import rasterio
        from rasterio.io import MemoryFile
        import torch

        with MemoryFile(contents) as memory, memory.open() as dataset:
            array, verification = prepare_stack_from_dataset(dataset, band_order_confirmed=band_order_confirmed,
                                                             crop_size=90)
            rgb_raw = dataset.read((4, 3, 2)).astype(np.float32)
        model = _load_checkpoint(str(checkpoint_path.resolve()))
        with torch.inference_mode():
            logit = float(model(torch.from_numpy(array[None])).reshape(-1)[0].item())
        score = 1.0 / (1.0 + float(np.exp(-np.clip(logit, -80, 80))))
        config = json.loads(checkpoint_path.with_suffix(".json").read_text(encoding="utf-8"))
        threshold = float(config.get("decision_threshold", 0.5))
        result = {"status": "available", "model": config.get("model_name", "ThermoScope visible-smoke image model"),
                "prediction": "visible_smoke_cue" if score >= threshold else "no_visible_smoke_cue",
                "smoke_score_uncalibrated": score, "threshold": threshold,
                "band_validation": verification,
                "limitation": "This is a visible-smoke cue, not evidence of fire, cause, or thermal source."}
        seg_path = segmentation_checkpoint_path or checkpoint_path.parent / "thermoscope_smoke_unet_v1.pth"
        if seg_path.is_file():
            seg_model, seg_config = _load_segmentation_checkpoint(str(seg_path.resolve()))
            with torch.inference_mode():
                mask_probability = torch.sigmoid(seg_model(torch.from_numpy(array[None])))[0, 0].numpy()
            mask_threshold = float(seg_config.get("decision_threshold", 0.5))
            binary = mask_probability >= mask_threshold
            rgb = np.stack([_scale_for_display(channel) for channel in rgb_raw], axis=-1)
            top, left = max(0, (rgb.shape[0] - 90) // 2), max(0, (rgb.shape[1] - 90) // 2)
            rgb = rgb[top:top + 90, left:left + 90]
            rgba = np.zeros((90, 90, 4), dtype=np.uint8)
            rgba[..., 0] = 255
            rgba[..., 1] = 80
            rgba[..., 3] = binary.astype(np.uint8) * 150
            overlay = Image.alpha_composite(Image.fromarray(rgb, "RGB").convert("RGBA"), Image.fromarray(rgba, "RGBA"))
            encoded = io.BytesIO()
            overlay.save(encoded, format="PNG")
            result["segmentation"] = {
                "status": "available", "mask_threshold": mask_threshold,
                "predicted_smoke_pixel_fraction": float(binary.mean()),
                "overlay_data_url": "data:image/png;base64," + base64.b64encode(encoded.getvalue()).decode("ascii"),
                "label_semantics": "visible smoke plume mask; not fire/cause/thermal evidence",
            }
        else:
            result["segmentation"] = {"status": "unavailable", "message": "No trained smoke-segmentation weights are installed."}
        return result
    except SmokeInputError as exc:
        return {"status": "incompatible_input", "prediction": None, "message": str(exc)}
    except Exception as exc:
        return {"status": "inference_error", "prediction": None, "message": f"Smoke inference failed safely: {exc}"}


def _scale_for_display(channel: np.ndarray) -> np.ndarray:
    low, high = np.percentile(channel, (2, 98))
    if high <= low:
        high = low + 1
    return np.clip((channel - low) * (255.0 / (high - low)), 0, 255).astype(np.uint8)
