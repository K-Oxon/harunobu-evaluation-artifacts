"""Cache normalized harunobu and DECO documents. Depends on the loaders and adapters and writes JSON files under results/cache/."""

from __future__ import annotations

import hashlib
from pathlib import Path

import harunobu

from scripts import paths
from scripts.ir import IR_SCHEMA_VERSION, IRDocument

_HARUNOBU_DIR = paths.RESULTS_DIR / "cache" / "harunobu"
_DECO_DIR = paths.RESULTS_DIR / "cache" / "deco"


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def harunobu_key(file_hash: str, mode: str, harunobu_version: str, schema_version: str) -> str:
    return f"{file_hash}_{harunobu_version}_{mode}_ir{schema_version}"


def deco_key(file_name: str, range_mtime: float, cell_mtime: float, schema_version: str) -> str:
    raw = f"{file_name}|{range_mtime}|{cell_mtime}|ir{schema_version}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def cached_adapt_file(path: str | Path, mode: str = "standard", *, use_cache: bool = True) -> IRDocument:
    from scripts.adapters.harunobu_adapter import adapt_file

    path = Path(path)
    if not use_cache:
        return adapt_file(path, mode=mode)

    key = harunobu_key(content_hash(path.read_bytes()), mode, harunobu.__version__, IR_SCHEMA_VERSION)
    cache_path = _HARUNOBU_DIR / f"{key}.json"
    if cache_path.exists():
        return IRDocument.model_validate_json(cache_path.read_text(encoding="utf-8"))

    doc = adapt_file(path, mode=mode)
    _HARUNOBU_DIR.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(doc.model_dump_json(indent=2), encoding="utf-8")
    return doc


def load_deco_cached(file_names: list[str], *, use_cache: bool = True) -> dict[str, IRDocument]:
    from scripts.loaders.deco import load_deco

    if not use_cache:
        return load_deco(file_names)

    range_mtime = paths.DECO_RANGE_CSV.stat().st_mtime
    cell_mtime = paths.DECO_CELL_CSV.stat().st_mtime

    result: dict[str, IRDocument] = {}
    misses: list[str] = []
    key_of: dict[str, str] = {}
    for fn in file_names:
        k = deco_key(fn, range_mtime, cell_mtime, IR_SCHEMA_VERSION)
        key_of[fn] = k
        cache_path = _DECO_DIR / f"{k}.json"
        if cache_path.exists():
            result[fn] = IRDocument.model_validate_json(cache_path.read_text(encoding="utf-8"))
        else:
            misses.append(fn)

    if misses:
        scanned = load_deco(misses)
        _DECO_DIR.mkdir(parents=True, exist_ok=True)
        for fn in misses:

            doc = scanned.get(fn, IRDocument(file_name=fn, source="deco", sheets=[]))
            (_DECO_DIR / f"{key_of[fn]}.json").write_text(doc.model_dump_json(indent=2), encoding="utf-8")
            result[fn] = doc

    return result
