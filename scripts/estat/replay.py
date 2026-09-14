"""Download the frozen 600-file e-Stat sample and verify manifest SHA-256 values. Writes source workbooks under data/estat/tier1/files/."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import urllib.request
from pathlib import Path

from scripts import paths


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def entries(manifest: Path) -> list[dict]:
    document = json.loads(manifest.read_text(encoding="utf-8"))
    rows = document.get("entries")
    if not isinstance(rows, list) or len(rows) != 600:
        raise SystemExit(f"expected 600 manifest entries, got {len(rows) if isinstance(rows, list) else 'invalid'}")
    required = ("file_name", "representative_url", "sha256")
    for index, row in enumerate(rows):
        missing = [key for key in required if not row.get(key)]
        if missing:
            raise SystemExit(f"manifest entry {index} is missing {missing}")
    return rows


def download(row: dict, destination: Path, timeout: float) -> None:
    part = destination.with_suffix(destination.suffix + ".part")
    request = urllib.request.Request(
        row["representative_url"],
        headers={"User-Agent": "harunobu-evaluation-artifacts/1.0"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response, part.open("wb") as output:
        while chunk := response.read(1024 * 1024):
            output.write(chunk)
    actual = sha256(part)
    expected = row["sha256"]
    if actual != expected:
        raise SystemExit(
            f"SHA-256 mismatch for {row['file_name']}: expected {expected}, got {actual}; kept {part}"
        )
    os.replace(part, destination)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--manifest", type=Path, default=paths.ESTAT_MANIFEST)
    parser.add_argument("--files-dir", type=Path, default=paths.ESTAT_DIR / "tier1" / "files")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--sleep", type=float, default=0.5)
    parser.add_argument("--limit", type=int, default=0, help="download only the first N entries")
    args = parser.parse_args()

    rows = entries(args.manifest)
    if args.limit:
        rows = rows[: args.limit]
    args.files_dir.mkdir(parents=True, exist_ok=True)
    for index, row in enumerate(rows, start=1):
        target = args.files_dir / row["file_name"]
        if target.exists() and sha256(target) == row["sha256"]:
            print(f"[{index}/{len(rows)}] verified {target.name}")
            continue
        if target.exists():
            raise SystemExit(f"existing file has wrong SHA-256: {target}")
        if index > 1 and args.sleep:
            time.sleep(args.sleep)
        download(row, target, args.timeout)
        print(f"[{index}/{len(rows)}] downloaded and verified {target.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
