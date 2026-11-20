"""Local-only ThermoScope image upload application (Python standard-library server)."""
from __future__ import annotations

import argparse
import json
import os
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from src.thermoscope_app.core import (EvidenceRepository, UploadError, cv_inference,
                                      inspect_upload, load_jharkhand_map_data)
from src.thermoscope_app.smoke_model import predict_smoke_upload

ROOT = Path(__file__).resolve().parents[2]
HTML_PATH = ROOT / "app" / "index.html"


def _multipart_parts(content_type: str, body: bytes) -> dict[str, tuple[str | None, bytes]]:
    header = f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode() + body
    message = BytesParser(policy=policy.default).parsebytes(header)
    if not message.is_multipart():
        raise ValueError("Expected a multipart/form-data upload.")
    parts: dict[str, tuple[str | None, bytes]] = {}
    for part in message.iter_parts():
        disposition = part.get_content_disposition()
        name = part.get_param("name", header="content-disposition")
        if disposition != "form-data" or not name:
            continue
        parts[name] = (part.get_filename(), part.get_payload(decode=True) or b"")
    return parts


class Handler(BaseHTTPRequestHandler):
    server_version = "ThermoScopeLocal/1.0"

    def log_message(self, _format, *args):  # noqa: A003 - do not log uploaded filenames or local paths
        return

    def _send(self, status: int, payload: bytes, content_type: str, *, cache: str = "no-store") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(payload)

    def _json(self, status: int, obj) -> None:
        self._send(status, json.dumps(obj, ensure_ascii=False, allow_nan=False).encode("utf-8"), "application/json; charset=utf-8")

    def do_GET(self):  # noqa: N802
        path = urlparse(self.path).path
        if path == "/":
            if not HTML_PATH.is_file():
                self._json(500, {"error": "Application interface is missing."})
                return
            self._send(200, HTML_PATH.read_bytes(), "text/html; charset=utf-8")
        elif path == "/api/health":
            missing = self.server.repository.check_inputs()
            smoke_available = self.server.smoke_model_path.is_file()
            segmentation_available = self.server.smoke_segmentation_model_path.is_file()
            self._json(200, {"status": "ok", "fire_classifier": "unavailable",
                             "smoke_model": "available" if smoke_available else "unavailable",
                             "smoke_segmentation": "available" if segmentation_available else "unavailable",
                             "evidence_inputs_missing": missing})
        elif path == "/api/map-boundary":
            try:
                self._json(200, load_jharkhand_map_data())
            except (OSError, ValueError, KeyError) as exc:
                self._json(503, {"error": f"Local study boundary is unavailable: {exc}"})
        elif path == "/map.js":
            script_path = ROOT / "app" / "map.js"
            if script_path.is_file():
                self._send(200, script_path.read_bytes(), "text/javascript; charset=utf-8")
            else:
                self._json(404, {"error": "Map interaction script is missing."})
        else:
            self._json(404, {"error": "Not found"})

    def do_POST(self):  # noqa: N802
        request_path = urlparse(self.path).path
        if request_path == "/api/area-evidence":
            self._area_evidence()
            return
        if request_path != "/api/analyze":
            self._json(404, {"error": "Not found"})
            return
        content_length = int(self.headers.get("Content-Length", "0"))
        max_body = 25 * 1024 * 1024 + 128 * 1024
        if content_length <= 0 or content_length > max_body:
            self._json(413, {"error": "Request is empty or exceeds the 25 MiB upload limit."})
            return
        try:
            parts = _multipart_parts(self.headers.get("Content-Type", ""), self.rfile.read(content_length))
            filename, contents = parts.get("image", (None, b""))
            if not filename:
                raise UploadError("Choose a satellite image before analysis.")
            image = inspect_upload(filename, contents)
            fields = {name: raw.decode("utf-8", errors="replace") for name, (part_filename, raw) in parts.items() if name != "image"}
            smoke = predict_smoke_upload(
                filename, contents, checkpoint_path=self.server.smoke_model_path,
                band_order_confirmed=fields.get("band_order_confirmed", "") == "true",
                segmentation_checkpoint_path=self.server.smoke_segmentation_model_path,
            )
            lon_text, lat_text = fields.get("longitude", "").strip(), fields.get("latitude", "").strip()
            longitude = float(lon_text) if lon_text else image.get("longitude")
            latitude = float(lat_text) if lat_text else image.get("latitude")
            acquired = fields.get("acquisition_date", "").strip() or image.get("acquisition_date")
            if acquired:
                from datetime import date
                acquired = date.fromisoformat(acquired).isoformat()
            if longitude is not None and latitude is not None:
                image["longitude"], image["latitude"] = float(longitude), float(latitude)
                if image["metadata_source"] == "none":
                    image["metadata_source"] = "user-entered WGS84 coordinates"
            image["acquisition_date"] = acquired
            result = {"image": image, "cv": cv_inference(image["preview_data_url"]),
                      "smoke": smoke, "analysis": None,
                      "needs_location": longitude is None or latitude is None}
            if longitude is not None and latitude is not None:
                radius = float(fields.get("radius_m", "1000"))
                lookback = int(fields.get("lookback_days", "30"))
                if not 100 <= radius <= 10_000:
                    raise ValueError("Search radius must be between 100 m and 10 km.")
                if not 1 <= lookback <= 3650:
                    raise ValueError("Lookback period must be between 1 and 3,650 days.")
                result["analysis"] = self.server.repository.analyze(
                    float(longitude), float(latitude), acquired, radius, lookback
                )
                result["analysis"]["cv"] = result["cv"]
                result["analysis"]["smoke"] = smoke
            self._json(200, result)
        except (UploadError, ValueError) as exc:
            self._json(400, {"error": str(exc)})
        except Exception:
            self._json(500, {"error": "Analysis failed safely. Check the local evidence inputs and try again."})

    def _area_evidence(self) -> None:
        """Search local evidence around a map-selected center, without an image upload."""
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length <= 0 or content_length > 16_384:
                self._json(413, {"error": "Area-selection request is empty or too large."})
                return
            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
            longitude, latitude = float(payload["longitude"]), float(payload["latitude"])
            radius = float(payload.get("radius_m", 1_000))
            lookback = int(payload.get("lookback_days", 30))
            acquired = payload.get("acquisition_date") or None
            if not 100 <= radius <= 10_000:
                raise ValueError("Search radius must be between 100 m and 10 km.")
            if not 1 <= lookback <= 3650:
                raise ValueError("Lookback period must be between 1 and 3,650 days.")
            if acquired:
                from datetime import date
                acquired = date.fromisoformat(str(acquired)).isoformat()
            analysis = self.server.repository.analyze(longitude, latitude, acquired, radius, lookback)
            self._json(200, {"analysis": analysis, "map_selection": True})
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            self._json(400, {"error": f"Could not search the selected map area: {exc}"})
        except Exception:
            self._json(500, {"error": "Area evidence search failed safely. Check local evidence inputs and try again."})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.environ.get("THERMOSCOPE_HOST", "127.0.0.1"),
                        help="Bind address; defaults to local-only access")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8765")))
    parser.add_argument("--firms", type=Path, default=EvidenceRepository.local_default().firms_path)
    parser.add_argument("--osm", type=Path, default=EvidenceRepository.local_default().osm_path)
    parser.add_argument("--features", type=Path, default=EvidenceRepository.local_default().features_path)
    parser.add_argument("--satellite-metadata", type=Path, default=EvidenceRepository.local_default().satellite_metadata_path)
    parser.add_argument("--smoke-model", type=Path, default=ROOT / "models" / "thermoscope_smoke_tiny_v1.pth")
    parser.add_argument("--smoke-segmentation-model", type=Path,
                        default=ROOT / "models" / "thermoscope_smoke_unet_v1.pth")
    args = parser.parse_args()
    local_hosts = {"127.0.0.1", "localhost", "::1"}
    public_bind_enabled = os.environ.get("THERMOSCOPE_ALLOW_PUBLIC_BIND") == "1"
    if args.host not in local_hosts and not (args.host == "0.0.0.0" and public_bind_enabled):
        parser.error("For privacy, this app only supports loopback host addresses.")
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.repository = EvidenceRepository(args.firms, args.osm, args.features, args.satellite_metadata)
    server.smoke_model_path = args.smoke_model.resolve()
    server.smoke_segmentation_model_path = args.smoke_segmentation_model.resolve()
    access = "container network" if args.host == "0.0.0.0" else "local-only"
    print(f"ThermoScope is available on {args.host}:{args.port} ({access}; Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nThermoScope stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
