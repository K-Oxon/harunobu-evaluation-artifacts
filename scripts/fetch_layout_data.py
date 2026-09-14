"""Download and verify pinned DECO and TableSense inputs. Depends on network access and bsdtar and writes data under data/deco/ and data/tablesense/."""

from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

from scripts import paths


@dataclass(frozen=True)
class Asset:
    name: str
    url: str
    digest: str
    algorithm: str = "sha256"


DECO_FILES = (
    Asset(
        "annotated.zip",
        "https://raw.githubusercontent.com/ddenron/deco_dataset/39d72ec07f40dd01065f936eee7e6dce24d0c5f6/annotated_files/annotated.zip",
        "81ee1ccdc36ca992afe1326aa831c29b4ccd4e10e95f82ee9e2f1c1003351181",
    ),
    Asset(
        "exported_annotations.zip",
        "https://raw.githubusercontent.com/ddenron/annotations_exporter/25a285bb7a1143087278b5eb61ed78d95861b2b0/data/exported_annotations.zip",
        "1830f48336023ad948d06dec78f762920980e4f0931dd5d2bd2e1769397958fc",
    ),
)
TABLESENSE_ANNOTATION = Asset(
    "TableSenseTableRangeAnnotations.txt",
    "https://raw.githubusercontent.com/microsoft/TableSense/3001191378dfc196e7546dab67cbd1094db8919a/dataset/Table%20range%20annotations.txt",
    "5f37900c872af48b03024321327eb2c94005265ea439e66caae28a4637c1cee9",
)
TABLESENSE_ARCHIVES = (
    Asset("VEnron2.7z", "https://ndownloader.figshare.com/files/8639470", "9a724c5f667f7fa371619774a1b19c4b", "md5"),
    Asset("VEUSES.7z", "https://ndownloader.figshare.com/files/7889902", "46f5b8b4233473b2e2b7d388c56a0ea0", "md5"),
    Asset("VFUSE.7z", "https://ndownloader.figshare.com/files/7889911", "e822971e2a76e033516b6e6adeb605e7", "md5"),
)


def digest(path: Path, algorithm: str) -> str:
    value = hashlib.new(algorithm)
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def fetch(asset: Asset, directory: Path, timeout: float) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / asset.name
    if target.exists() and digest(target, asset.algorithm) == asset.digest:
        print(f"verified {target}")
        return target
    part = target.with_suffix(target.suffix + ".part")
    request = urllib.request.Request(asset.url, headers={"User-Agent": "harunobu-evaluation-artifacts/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response, part.open("wb") as output:
        shutil.copyfileobj(response, output, length=1024 * 1024)
    actual = digest(part, asset.algorithm)
    if actual != asset.digest:
        raise SystemExit(f"checksum mismatch for {asset.name}: expected {asset.digest}, got {actual}")
    part.replace(target)
    print(f"downloaded and verified {target}")
    return target


def install_deco(timeout: float) -> None:
    archive_dir = paths.DECO_DIR / "raw"
    workbook_zip, annotation_zip = [fetch(asset, archive_dir, timeout) for asset in DECO_FILES]
    with tempfile.TemporaryDirectory(prefix="deco-") as temp_name:
        temp = Path(temp_name)
        with zipfile.ZipFile(workbook_zip) as archive:
            archive.extractall(temp / "workbooks")
        with zipfile.ZipFile(annotation_zip) as archive:
            archive.extractall(temp / "annotations")
        paths.DECO_XLSX_DIR.mkdir(parents=True, exist_ok=True)
        for source in (temp / "workbooks").rglob("*.xlsx"):
            shutil.copy2(source, paths.DECO_XLSX_DIR / source.name)
        annotation_dir = paths.DECO_RANGE_CSV.parent
        annotation_dir.mkdir(parents=True, exist_ok=True)
        for filename, destination in (
            ("rangeAnnotations.csv", paths.DECO_RANGE_CSV),
            ("cellAnnotations.csv", paths.DECO_CELL_CSV),
        ):
            matches = list((temp / "annotations").rglob(filename))
            if len(matches) != 1:
                raise SystemExit(f"expected one {filename}, found {len(matches)}")
            shutil.copy2(matches[0], destination)


def install_tablesense(timeout: float) -> None:
    archive_dir = paths.TABLESENSE_DIR / "raw-archives"
    annotation = fetch(TABLESENSE_ANNOTATION, archive_dir, timeout)
    paths.TABLESENSE_TSV.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(annotation, paths.TABLESENSE_TSV)
    paths.TABLESENSE_RAW_DIR.mkdir(parents=True, exist_ok=True)
    for asset in TABLESENSE_ARCHIVES:
        archive = fetch(asset, archive_dir, timeout)
        subprocess.run(["bsdtar", "-xf", str(archive), "-C", str(paths.TABLESENSE_RAW_DIR)], check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dataset", choices=("all", "deco", "tablesense"), default="all")
    parser.add_argument("--timeout", type=float, default=300.0)
    args = parser.parse_args()
    if args.dataset in ("all", "deco"):
        install_deco(args.timeout)
    if args.dataset in ("all", "tablesense"):
        install_tablesense(args.timeout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
