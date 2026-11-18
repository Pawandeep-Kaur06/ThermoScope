"""Small, explicit cache primitives shared by ThermoScope pipeline stages.

Artifacts are reusable only when their recorded input/configuration key matches
and their on-disk size and SHA-256 still match the completion manifest.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


def file_fingerprint(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Cache input is missing or not a file: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    stat = path.stat()
    return {"path": str(path.resolve()), "size_bytes": stat.st_size,
            "mtime_ns": stat.st_mtime_ns, "sha256": digest.hexdigest()}


def cache_key(*, stage: str, inputs: dict[str, Any], configuration: dict[str, Any],
              code_path: str | Path | None = None) -> str:
    def content_identity(value: Any) -> Any:
        if isinstance(value, dict):
            # Timestamps remain available in provenance fingerprints, but touching
            # an unchanged file does not invalidate a content-addressed stage cache.
            return {key: content_identity(item) for key, item in value.items() if key != "mtime_ns"}
        if isinstance(value, (list, tuple)):
            return [content_identity(item) for item in value]
        return value
    payload: dict[str, Any] = {"stage": stage, "inputs": content_identity(inputs),
                               "configuration": content_identity(configuration)}
    if code_path is not None:
        payload["code"] = file_fingerprint(code_path)["sha256"]
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def artifact_record(path: str | Path) -> dict[str, Any]:
    fp = file_fingerprint(path)
    return {"path": fp["path"], "size_bytes": fp["size_bytes"], "sha256": fp["sha256"]}


def manifest_path(artifact: str | Path) -> Path:
    return Path(str(artifact) + ".cache.json")


def cache_hit(artifact: str | Path, key: str) -> bool:
    artifact = Path(artifact)
    meta = manifest_path(artifact)
    if not artifact.is_file() or not meta.is_file():
        return False
    try:
        saved = json.loads(meta.read_text(encoding="utf-8"))
        record = saved["artifact"]
        return (saved.get("cache_key") == key and artifact.stat().st_size == record["size_bytes"]
                and file_fingerprint(artifact)["sha256"] == record["sha256"])
    except (OSError, ValueError, KeyError, TypeError):
        return False


def write_manifest(artifact: str | Path, *, key: str, source: str,
                   metadata: dict[str, Any] | None = None) -> Path:
    artifact = Path(artifact)
    data = {"cache_key": key, "source": source, "retrieved_or_generated_at_utc": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(timespec="seconds"),
            "artifact": artifact_record(artifact), "metadata": metadata or {}}
    path = manifest_path(artifact)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(data, stream, indent=2, default=str)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    finally:
        Path(temp_name).unlink(missing_ok=True)
    return path


def atomic_json(path: str | Path, payload: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, indent=2, default=str)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    finally:
        Path(temp_name).unlink(missing_ok=True)
