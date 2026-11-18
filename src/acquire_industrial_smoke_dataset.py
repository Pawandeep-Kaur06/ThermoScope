"""Download and checksum the CC BY 4.0 industrial smoke dataset from Zenodo.

The destination must be a new directory. The image archive is large; this tool
checks licence, published sizes, free space, and Git ignore status first.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests

RECORD_ID = "4250706"
API_URL = f"https://zenodo.org/api/records/{RECORD_ID}"
EXPECTED_LICENSE = "cc-by-4.0"
FILES = {"images.tar.gz", "segmentation_labels.tar.gz", "README.md"}
CHUNK_SIZE = 8 * 1024 * 1024
MIN_EXTRA_SPACE_BYTES = 25_000_000_000


class AcquisitionError(RuntimeError):
    """Input, access, validation, or transfer could not be completed safely."""


def _hash_file(path: Path) -> tuple[int, str, str]:
    md5, sha256 = hashlib.md5(), hashlib.sha256()  # noqa: S324 - compare publisher's MD5
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(CHUNK_SIZE), b""):
            size += len(chunk)
            md5.update(chunk)
            sha256.update(chunk)
    return size, md5.hexdigest(), sha256.hexdigest()


def acquire(output_dir: Path) -> Path:
    output_dir = output_dir.resolve()
    if output_dir.exists():
        raise AcquisitionError(f"Destination already exists; refusing to overwrite: {output_dir}")
    output_dir.parent.mkdir(parents=True, exist_ok=True)

    response = requests.get(API_URL, timeout=(20, 60))
    response.raise_for_status()
    record = response.json()
    metadata = record.get("metadata", {})
    license_id = (metadata.get("license") or {}).get("id")
    if license_id != EXPECTED_LICENSE:
        raise AcquisitionError(f"Expected {EXPECTED_LICENSE} dataset licence, received {license_id!r}.")
    listed = {item["key"]: item for item in record.get("files", []) if item.get("key") in FILES}
    if set(listed) != FILES:
        raise AcquisitionError(f"Zenodo file listing changed; found {sorted(listed)}")

    required = sum(int(item["size"]) for item in listed.values()) + MIN_EXTRA_SPACE_BYTES
    free_bytes = shutil.disk_usage(output_dir.parent).free
    if free_bytes < required:
        raise AcquisitionError(
            f"Need {required:,} bytes free (archive plus {MIN_EXTRA_SPACE_BYTES:,} byte extraction margin); "
            f"only {free_bytes:,} bytes are available."
        )

    # Check ignore policy before creating the dataset. The project data/raw rule
    # is intentionally relied on; this is a local-only acquisition.
    import subprocess

    probe = output_dir.parent / output_dir.name / "images.tar.gz"
    check = subprocess.run(
        ["git", "check-ignore", "--quiet", str(probe)], cwd=Path(__file__).resolve().parents[1]
    )
    if check.returncode != 0:
        raise AcquisitionError(f"Planned archive path is not Git-ignored: {probe}")

    output_dir.mkdir(parents=False)
    files_report: list[dict[str, object]] = []
    try:
        for name in sorted(FILES):
            item = listed[name]
            target = output_dir / name
            temporary = output_dir / f".{name}.part"
            if target.exists() or temporary.exists():
                raise AcquisitionError(f"Unexpected pre-existing output: {target if target.exists() else temporary}")
            url = item.get("links", {}).get("self")
            if not url:
                raise AcquisitionError(f"Zenodo did not provide a download URL for {name}")
            digest_kind, expected_digest = str(item.get("checksum", "")).split(":", 1)
            if digest_kind != "md5" or not expected_digest:
                raise AcquisitionError(f"No supported published checksum for {name}")
            md5, sha256 = hashlib.md5(), hashlib.sha256()  # noqa: S324
            size = 0
            started = time.monotonic()
            with requests.get(url, stream=True, timeout=(30, 180)) as download:
                download.raise_for_status()
                with temporary.open("xb") as stream:
                    for chunk in download.iter_content(chunk_size=CHUNK_SIZE):
                        if chunk:
                            stream.write(chunk)
                            size += len(chunk)
                            md5.update(chunk)
                            sha256.update(chunk)
            expected_size = int(item["size"])
            if size != expected_size:
                raise AcquisitionError(f"{name}: received {size:,} bytes; expected {expected_size:,}")
            if md5.hexdigest().lower() != expected_digest.lower():
                raise AcquisitionError(f"{name}: published MD5 checksum mismatch")
            temporary.replace(target)
            files_report.append({
                "file": name, "size_bytes": size, "published_checksum": f"md5:{expected_digest}",
                "sha256": sha256.hexdigest(), "download_seconds": round(time.monotonic() - started, 3),
                "url": url,
            })

        manifest = {
            "record_id": RECORD_ID, "doi": record.get("doi"), "title": metadata.get("title"),
            "license": license_id, "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
            "files": files_report,
        }
        (output_dir / "acquisition_manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
    except Exception:
        # Keep any completed/partial files for inspection; never delete data
        # after a failed transfer. The next run must use a new directory.
        raise
    return output_dir


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        path = acquire(args.output_dir)
    except Exception as exc:
        print(f"Acquisition failed safely: {exc}", file=sys.stderr)
        return 2
    print(f"Dataset downloaded and verified: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
