"""Verify and convert manifest workbooks into scoring inputs. Depends on LibreOffice, openpyxl, and harunobu and writes data/estat/tier1/xlsx/ and results/estat/conversion-replay.json."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import openpyxl

from scripts import paths

_SOFFICE = "soffice"
_SINGLE_TIMEOUT = 120



STATUS_KINDS: tuple[str, ...] = (
    "ok",
    "missing_source",
    "dl_failed",
    "sha256_mismatch",
    "convert_failed",
    "timeout",
    "content_rejected",
    "unreadable",
    "empty",
)


def load_manifest_entries(manifest_path: Path) -> list[dict]:
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    return list(data["entries"])


def scoring_name(file_name: str) -> str:
    p = Path(file_name)
    return p.name if p.suffix.lower() == ".xlsx" else p.stem + ".xlsx"


def _soffice_convert(xls_path: Path, outdir: Path, timeout: int = _SINGLE_TIMEOUT) -> None:
    with tempfile.TemporaryDirectory(prefix="lo_profile_") as profile:
        subprocess.run(
            [
                _SOFFICE,
                "--headless",
                "--norestore",
                f"-env:UserInstallation=file://{profile}",
                "--convert-to",
                "xlsx",
                "--outdir",
                str(outdir),
                str(xls_path),
            ],
            check=True,
            capture_output=True,
            timeout=timeout,
        )


def _harunobu_reject_reason(path: Path) -> str | None:
    try:
        from harunobu.core.reader import UnsupportedFormatError, validate_file_content
    except Exception:
        return None
    try:
        validate_file_content(path)
        return None
    except UnsupportedFormatError as exc:
        return str(exc)


def _validate_xlsx(path: Path) -> tuple[int, int]:
    wb = openpyxl.load_workbook(path, read_only=True, data_only=False)
    try:
        n_nonempty = 0
        for ws in wb.worksheets:
            for row in ws.iter_rows(values_only=True):
                n_nonempty += sum(1 for v in row if v is not None and str(v).strip() != "")
        return len(wb.worksheets), n_nonempty
    finally:
        wb.close()


def build_one(entry: dict, files_dir: Path, xlsx_dir: Path, *, force: bool) -> dict:
    file_name = entry.get("file_name")
    if not file_name:
        return {
            "file_name": None, "scoring_name": None, "status": "dl_failed",
            "note": f"manifest に file_name なし(dl_status={entry.get('dl_status')!r} "
                    f"{entry.get('dl_error') or ''})".strip(),
        }
    src = files_dir / file_name
    dst = xlsx_dir / scoring_name(file_name)
    res: dict = {"file_name": file_name, "scoring_name": dst.name, "status": "ok", "note": ""}

    if not src.exists():
        return {**res, "status": "missing_source", "note": f"{src} なし(DL 実体は main 側)"}

    if dst.exists() and not force:
        pass
    elif src.suffix.lower() == ".xlsx":
        actual = hashlib.sha256(src.read_bytes()).hexdigest()
        if entry.get("sha256") and actual != entry["sha256"]:
            return {**res, "status": "sha256_mismatch", "note": f"manifest={entry['sha256'][:12]} actual={actual[:12]}"}
        reject = _harunobu_reject_reason(src)
        if reject is None:
            shutil.copy2(src, dst)
            res["note"] = "copied"
        else:

            try:
                with tempfile.TemporaryDirectory(prefix="ss_resave_") as tmp:
                    _soffice_convert(src, Path(tmp))
                    produced = Path(tmp) / dst.name
                    if not produced.exists():
                        return {**res, "status": "convert_failed", "note": f"再保存で soffice 出力なし: {reject}"}
                    shutil.move(str(produced), str(dst))
            except subprocess.TimeoutExpired:
                return {**res, "status": "timeout", "note": f"soffice > {_SINGLE_TIMEOUT}s"}
            except subprocess.CalledProcessError as exc:
                return {**res, "status": "convert_failed", "note": f"soffice exit={exc.returncode}"}
            if _harunobu_reject_reason(dst) is not None:
                return {**res, "status": "content_rejected", "note": f"再保存後も harunobu 拒否: {reject}"}
            res["note"] = "resaved"
            res["resave_reason"] = reject
    else:
        try:
            with tempfile.TemporaryDirectory(prefix="ss_convert_") as tmp:
                _soffice_convert(src, Path(tmp))
                produced = Path(tmp) / dst.name
                if not produced.exists():
                    return {**res, "status": "convert_failed", "note": "soffice 出力なし"}
                shutil.move(str(produced), str(dst))
        except subprocess.TimeoutExpired:
            return {**res, "status": "timeout", "note": f"soffice > {_SINGLE_TIMEOUT}s"}
        except subprocess.CalledProcessError as exc:
            return {**res, "status": "convert_failed", "note": f"soffice exit={exc.returncode}"}
        res["note"] = "converted"

    try:
        n_sheets, n_nonempty = _validate_xlsx(dst)
    except Exception as exc:  # noqa: BLE001
        return {**res, "status": "unreadable", "note": f"{type(exc).__name__}: {exc}"}
    res["n_sheets"] = n_sheets
    res["n_nonempty_cells"] = n_nonempty

    res["sha256_out"] = hashlib.sha256(dst.read_bytes()).hexdigest()
    if n_nonempty == 0:
        return {**res, "status": "empty", "note": "非空セルなし"}
    return res


def build_all(entries: list[dict], files_dir: Path, xlsx_dir: Path, *, force: bool, quiet: bool = False) -> dict:
    xlsx_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for entry in entries:
        res = build_one(entry, files_dir, xlsx_dir, force=force)
        results.append(res)
        if not quiet and res["status"] != "ok":
            print(f"  [NG:{res['status']}] {res['file_name']} {res['note']}", flush=True)
        elif not quiet and len(results) % 50 == 0:
            print(f"  [{len(results)}/{len(entries)}] ...", flush=True)

    results.sort(key=lambda r: (r["file_name"] or ""))
    by_status = {k: sum(1 for r in results if r["status"] == k) for k in STATUS_KINDS}
    unknown = [r["status"] for r in results if r["status"] not in STATUS_KINDS]
    return {
        "n_entries": len(results),
        "n_ok": by_status["ok"],
        "n_failed": len(results) - by_status["ok"],
        "by_status": {k: v for k, v in by_status.items() if v},
        "unknown_status": sorted(set(unknown)),
        "files": results,
    }


def parse_args(argv: list[str] | None = None, *, defaults: dict | None = None) -> argparse.Namespace:
    d = defaults or {}
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--manifest", type=Path, default=d.get("manifest"))
    parser.add_argument("--files-dir", type=Path, default=d.get("files_dir"))
    parser.add_argument("--xlsx-dir", type=Path, default=d.get("xlsx_dir"))
    parser.add_argument("--out-json", type=Path, default=d.get("out_json"))
    parser.add_argument("--force", action="store_true", help="構築済みも再コピー/再変換する")
    parser.add_argument("--no-json", action="store_true", help="結果 JSON を書かない(スモーク用)")
    args = parser.parse_args(argv)
    for name in ("manifest", "files_dir", "xlsx_dir"):
        if getattr(args, name) is None:
            parser.error(f"--{name.replace('_', '-')} が必要です")
    return args


def main(argv: list[str] | None = None, *, defaults: dict | None = None) -> int:
    args = parse_args(argv, defaults=defaults)
    entries = load_manifest_entries(args.manifest)
    summary = build_all(entries, args.files_dir, args.xlsx_dir, force=args.force)

    if not args.no_json and args.out_json:
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        args.out_json.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"→ {args.out_json}")
    print(f"xlsx_dir={args.xlsx_dir} ok={summary['n_ok']} failed={summary['n_failed']}")
    if summary["n_failed"]:
        print("  内訳: " + ", ".join(f"{k}×{v}" for k, v in summary["by_status"].items() if k != "ok"))
    return 1 if summary["n_failed"] else 0


STARTER_SET_DEFAULTS = {
    "manifest": paths.ESTAT_DIR / "starter-set" / "manifest.json",
    "files_dir": paths.ESTAT_DIR / "starter-set" / "files",
    "xlsx_dir": paths.ESTAT_DIR / "starter-set" / "xlsx",
    "out_json": paths.ROOT / "docs" / "experiments" / "starter-set-conversion.json",
}

TIER1_DEFAULTS = {
    "manifest": paths.ESTAT_DIR / "tier1" / "manifest.json",
    "files_dir": paths.ESTAT_DIR / "tier1" / "files",
    "xlsx_dir": paths.ESTAT_DIR / "tier1" / "xlsx",
    "out_json": paths.RESULTS_DIR / "estat" / "conversion-replay.json",
}


if __name__ == "__main__":
    raise SystemExit(main(defaults=TIER1_DEFAULTS))
