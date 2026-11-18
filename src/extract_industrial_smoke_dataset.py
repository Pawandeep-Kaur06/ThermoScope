"""Safely extract the verified smoke image and segmentation archives once."""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import tarfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

MIN_FREE_BYTES = 25_000_000_000
CHUNK_SIZE = 8 * 1024 * 1024
WINDOWS_INVALID = set('<>:"|?*')


def _portable_parts(rel: PurePosixPath) -> tuple[str, ...]:
    """Map archive components to deterministic Windows-safe names."""
    parts = tuple("".join("_" if char in WINDOWS_INVALID else char for char in part).rstrip(" .")
                  for part in rel.parts)
    if any(not part or part in {".", ".."} for part in parts):
        raise ValueError(f"Archive path has no safe Windows representation: {rel}")
    return parts


def safe_extract(archive: Path, destination: Path) -> list[dict[str, object]]:
    """Stream regular files/directories only; reject traversal and links."""
    records: list[dict[str, object]] = []
    root = destination.resolve()
    with tarfile.open(archive, mode="r|gz") as tar:
        for member in tar:
            rel = PurePosixPath(member.name)
            if rel.is_absolute() or not rel.parts or any(part in {"", ".", ".."} for part in rel.parts):
                raise ValueError(f"Unsafe archive path: {member.name!r}")
            portable = _portable_parts(rel)
            target = (root / Path(*portable)).resolve()
            if root not in target.parents and target != root:
                raise ValueError(f"Archive member escapes extraction directory: {member.name!r}")
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                raise ValueError(f"Unsupported archive member type for {member.name!r}")
            if target.exists():
                raise FileExistsError(f"Refusing to overwrite extracted file: {target}")
            target.parent.mkdir(parents=True, exist_ok=True)
            source = tar.extractfile(member)
            if source is None:
                raise ValueError(f"Cannot read archive member: {member.name!r}")
            with source, target.open("xb") as output:
                shutil.copyfileobj(source, output, length=CHUNK_SIZE)
            actual_size = target.stat().st_size
            if actual_size != member.size:
                raise IOError(f"Extracted size mismatch for {member.name}: {actual_size} != {member.size}")
            records.append({"archive_path": member.name, "relative_path": target.relative_to(root).as_posix(),
                            "size_bytes": actual_size})
    return records


def extract(raw_dir: Path, output_dir: Path) -> Path:
    raw_dir, output_dir = raw_dir.resolve(), output_dir.resolve()
    if output_dir.exists():
        raise FileExistsError(f"Output already exists; refusing to overwrite: {output_dir}")
    images = raw_dir / "images.tar.gz"
    labels = raw_dir / "segmentation_labels.tar.gz"
    for path in (images, labels):
        if not path.is_file():
            raise FileNotFoundError(path)
    free = shutil.disk_usage(output_dir.parent).free
    if free < MIN_FREE_BYTES:
        raise OSError(f"Need at least {MIN_FREE_BYTES:,} bytes free for extraction; available {free:,}")
    output_dir.mkdir(parents=True)
    records: list[dict[str, object]] = []
    for name, archive in (("images", images), ("segmentation_labels", labels)):
        records.extend(safe_extract(archive, output_dir / name))
    manifest = {
        "retrieved_from": "https://zenodo.org/records/4250706",
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "archives": [str(images), str(labels)],
        "file_count": len(records),
        "extracted_bytes": sum(int(row["size_bytes"]) for row in records),
        "files": records,
    }
    (output_dir / "extraction_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    with (output_dir / "extracted_files.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["archive_path", "relative_path", "size_bytes"])
        writer.writeheader()
        writer.writerows(records)
    return output_dir


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = extract(args.raw_dir, args.output_dir)
    print(f"Extracted {result}")


if __name__ == "__main__":
    main()
