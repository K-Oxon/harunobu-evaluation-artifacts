"""Re-run AI-OFF scoring and normalize table-level rule states for the frozen e-Stat sample. Depends on harunobu and writes intermediates under results/chapter4-evidence/."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sqlite3
import tempfile
from collections import defaultdict
from datetime import date, datetime, time as datetime_time, timezone
from pathlib import Path
from typing import Any, Iterable

from scripts import paths


DEFAULT_MANIFEST = paths.ESTAT_DIR / "tier1" / "manifest.json"
DEFAULT_C1 = paths.RESULTS_DIR / "estat" / "rulescore-tier1.json"
DEFAULT_XLSX_DIR = paths.ESTAT_DIR / "tier1" / "xlsx"
DEFAULT_OUTPUT_ROOT = paths.RESULTS_DIR / "chapter4-evidence"

SCHEMA_VERSION = "0.1.0"
NOT_IMPLEMENTED_RULES = frozenset({"L3-02", "L3-03", "L3-08"})
BULK_ONLY_RULES = frozenset({"L3-07"})
_SEMANTIC_SKIP = re.compile(
    r"(?:スキップ|判定対象外|チェック対象外|判定でき|検出されなかったため|特定でき|"
    r"情報がない|情報不足|報告済み|地域データ列が検出されませんでした)",
    re.IGNORECASE,
)

BASE_COLUMNS = [
    "stem",
    "scoring_file_name",
    "manifest_file_name",
    "source_format",
    "source_sha256",
    "scoring_sha256",
    "c1_file_hash",
    "c1_ok",
    "c1_error",
    "sheet_count",
    "n_tables",
    "n_failed_rules",
    "n_skipped_rules",
    "failed_rule_ids",
    "skipped_rule_ids",
    "cell",
    "gov_org",
    "gov_org_code",
    "stat_type",
    "gov_stats_code",
    "gov_stats_name",
    "survey_date",
    "table_shape",
    "representative_url",
]

NORMALIZED_COLUMNS = [
    "stem",
    "scoring_file_name",
    "manifest_file_name",
    "source_format",
    "source_sha256",
    "scoring_sha256",
    "c1_file_hash",
    "gov_stats_code",
    "gov_stats_name",
    "stat_type",
    "gov_org",
    "survey_date",
    "table_shape",
    "representative_url",
    "sheet_name",
    "sheet_hidden",
    "sheet_used_range",
    "sheet_table_count",
    "table_index",
    "table_range",
    "table_confidence",
    "header_rows",
    "header_range",
    "body_start_row",
    "body_end_row",
    "footer_rows",
    "stub_cols",
    "column_schemas",
    "rule_id",
    "passed",
    "tri_state",
    "execution_branch",
    "audit_status",
    "skipped",
    "confidence",
    "severity",
    "message",
    "n_violations_raw",
    "n_violations_unique_file_rule",
    "violation_ref",
]

VIOLATION_COLUMNS = [
    "violation_ref",
    "stem",
    "scoring_file_name",
    "sheet_name",
    "rule_id",
    "cell_range",
    "description",
    "severity",
]


FILE_RULE_STATE_COLUMNS = [
    "stem",
    "source_format",
    "stat_type",
    "gov_org",
    "cell",
    "rule_id",
    "n_tables",
    "n_tables_pass",
    "n_tables_fail",
    "n_tables_abstain",
    "file_state",
    "c1_passed",
    "c1_skipped",
]
FILE_STATE_NO_TABLE = "no_table"


class InputError(ValueError):
    pass


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise InputError(f"JSON object ではない: {path}")
    return data


def _index_unique(rows: Iterable[dict[str, Any]], name_key: str, label: str) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for row in rows:
        name = row.get(name_key)
        if not isinstance(name, str) or not name:
            raise InputError(f"{label} に {name_key} が無い行がある")
        stem = Path(name).stem
        if stem in indexed:
            raise InputError(f"{label} の stem が重複: {stem}")
        indexed[stem] = row
    return indexed


def _index_xlsx(xlsx_dir: Path) -> dict[str, Path]:
    indexed: dict[str, Path] = {}
    for path in sorted(xlsx_dir.glob("*.xlsx")):
        if path.stem in indexed:
            raise InputError(f"採点用 xlsx の stem が重複: {path.stem}")
        indexed[path.stem] = path
    return indexed


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_default(value: Any) -> str:
    if isinstance(value, (datetime, date, datetime_time)):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def load_joined_inputs(manifest_path: Path, c1_path: Path, xlsx_dir: Path) -> list[dict[str, Any]]:
    manifest_doc = _load_json(manifest_path)
    c1_doc = _load_json(c1_path)
    manifest = _index_unique(manifest_doc.get("entries", []), "file_name", "manifest")
    c1 = _index_unique(c1_doc.get("files", []), "file_name", "C1")
    xlsx = _index_xlsx(xlsx_dir)

    expected = set(manifest)
    problems: list[str] = []
    for label, actual in (("C1", set(c1)), ("xlsx", set(xlsx))):
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        if missing:
            problems.append(f"{label} missing={missing[:5]} (n={len(missing)})")
        if extra:
            problems.append(f"{label} extra={extra[:5]} (n={len(extra)})")
    if problems:
        raise InputError("stem join が一対一でない: " + "; ".join(problems))

    joined: list[dict[str, Any]] = []
    for stem in sorted(expected):
        scoring_sha256 = sha256_file(xlsx[stem])
        c1_hash = str(c1[stem].get("file_hash") or "")
        if c1_hash and not scoring_sha256.startswith(c1_hash):
            raise InputError(
                f"採点用ファイルが C1 と不一致: {xlsx[stem].name} "
                f"C1={c1_hash} actual={scoring_sha256[:len(c1_hash)]}"
            )
        source_name = str(manifest[stem]["file_name"])
        joined.append(
            {
                "stem": stem,
                "path": xlsx[stem],
                "manifest": manifest[stem],
                "c1": c1[stem],
                "scoring_sha256": scoring_sha256,
                "source_format": Path(source_name).suffix.lower().lstrip("."),
            }
        )
    return joined


def _candidate_row(item: dict[str, Any]) -> dict[str, Any]:
    manifest, c1 = item["manifest"], item["c1"]
    rules = {r["rule_id"]: r for r in c1.get("rules", [])}
    failed = sorted(rid for rid, r in rules.items() if not r.get("skipped") and not r.get("passed"))
    skipped = sorted(rid for rid, r in rules.items() if r.get("skipped"))
    row: dict[str, Any] = {
        "stem": item["stem"],
        "scoring_file_name": item["path"].name,
        "manifest_file_name": manifest["file_name"],
        "source_format": item["source_format"],
        "source_sha256": manifest.get("sha256", ""),
        "scoring_sha256": item["scoring_sha256"],
        "c1_file_hash": c1.get("file_hash", ""),
        "c1_ok": c1.get("ok"),
        "c1_error": c1.get("error") or "",
        "sheet_count": c1.get("sheet_count"),
        "n_tables": c1.get("n_tables"),
        "n_failed_rules": len(failed),
        "n_skipped_rules": len(skipped),
        "failed_rule_ids": ";".join(failed),
        "skipped_rule_ids": ";".join(skipped),
    }
    for key in BASE_COLUMNS[15:]:
        row[key] = manifest.get(key, "")
    for rule_id, rule in sorted(rules.items()):
        row[f"rule_{rule_id}"] = "skip" if rule.get("skipped") else ("pass" if rule.get("passed") else "fail")
    return row


def _write_csv_exclusive(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.stem}.", suffix=".tmp", dir=path.parent)
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        with temporary.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        try:
            os.link(temporary, path)
        except FileExistsError:
            return False
        return True
    finally:
        temporary.unlink(missing_ok=True)


def write_candidates(items: list[dict[str, Any]], output: Path) -> bool:
    rows = [_candidate_row(item) for item in items]
    rule_columns = sorted({key for row in rows for key in row if key.startswith("rule_")})
    return _write_csv_exclusive(output, rows, BASE_COLUMNS + rule_columns)


def _analysis_extras(result: Any) -> list[list[dict[str, Any]]]:
    return [
        [
            {
                "bodyStartRow": table.layout.body_start_row,
                "bodyEndRow": table.layout.body_end_row,
                "footerRows": table.layout.footer_rows,
                "stubCols": table.layout.stub_cols,
            }
            for table in sheet.tables
        ]
        for sheet in result.sheets
    ]


def _write_detailed_exclusive(result: Any, item: dict[str, Any], destination: Path) -> bool:
    from harunobu.output.json_writer import to_dict, write_json

    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        return False
    fd, temporary_name = tempfile.mkstemp(prefix=f".{destination.stem}.", suffix=".tmp", dir=destination.parent)
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        standard_writer_fallback = False
        try:
            write_json(result, str(temporary))
            document = _load_json(temporary)
        except TypeError:


            document = to_dict(result)
            standard_writer_fallback = True
        extras = _analysis_extras(result)
        for sheet_index, sheet in enumerate(document.get("sheets", [])):
            for table_index, table in enumerate(sheet.get("評価対象エリア", [])):
                table.update(extras[sheet_index][table_index])
        manifest, c1 = item["manifest"], item["c1"]
        document["chapter4Evidence"] = {
            "schemaVersion": SCHEMA_VERSION,
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "harunobuVersion": __import__("harunobu").__version__,
            "mode": "thorough",
            "ai": "off",
            "stem": item["stem"],
            "manifestFileName": manifest["file_name"],
            "sourceFormat": item["source_format"],
            "sourceSha256": manifest.get("sha256"),
            "scoringFileName": item["path"].name,
            "scoringSha256": item["scoring_sha256"],
            "c1FileHash": c1.get("file_hash"),
            "standardWriterFallback": standard_writer_fallback,
            "manifest": {
                key: manifest.get(key)
                for key in (
                    "cell", "gov_org", "gov_org_code", "stat_type", "gov_stats_code",
                    "gov_stats_name", "survey_date", "table_shape", "representative_url",
                )
            },
        }
        temporary.write_text(
            json.dumps(document, ensure_ascii=False, indent=2, default=_json_default) + "\n",
            encoding="utf-8",
        )
        try:
            os.link(temporary, destination)
        except FileExistsError:
            return False
        return True
    finally:
        temporary.unlink(missing_ok=True)


def _write_error(item: dict[str, Any], directory: Path, exc: Exception) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    path = directory / f"{item['stem']}.error.{stamp}.json"
    payload = {
        "stem": item["stem"],
        "scoring_file_name": item["path"].name,
        "error_type": type(exc).__name__,
        "error": str(exc),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def analyze_items(items: list[dict[str, Any]], detailed_dir: Path, *, limit: int = 0) -> tuple[int, int, int]:
    os.environ["HARUNOBU_AI_DISABLED"] = "1"
    from harunobu import Config, analyze

    selected = items[:limit] if limit > 0 else items
    created = skipped = failed = 0
    for index, item in enumerate(selected, start=1):
        destination = detailed_dir / f"{item['stem']}.json"
        if destination.exists():
            skipped += 1
            print(f"[{index}/{len(selected)}] SKIP {destination.name} (既存)", flush=True)
            continue
        try:
            result = analyze(item["path"], Config(mode="thorough"))
            if _write_detailed_exclusive(result, item, destination):
                created += 1
                print(f"[{index}/{len(selected)}] OK   {destination.name}", flush=True)
            else:
                skipped += 1
                print(f"[{index}/{len(selected)}] SKIP {destination.name} (既存)", flush=True)
        except Exception as exc:
            failed += 1
            error_path = _write_error(item, detailed_dir, exc)
            print(f"[{index}/{len(selected)}] ERR  {item['path'].name}: {exc} -> {error_path.name}", flush=True)
    return created, skipped, failed


def classify_execution(rule_id: str, check: dict[str, Any]) -> tuple[str, str]:
    passed = bool(check.get("合否"))
    if rule_id in NOT_IMPLEMENTED_RULES:
        return "not_implemented", "abstain"
    if rule_id in BULK_ONLY_RULES:
        return "bulk_only", "abstain"
    message = str(check.get("メッセージ") or "")
    if check.get("判定対象外") or float(check.get("信頼度") or 0.0) == 0.0 or _SEMANTIC_SKIP.search(message):
        return "semantic_skip", "abstain"
    if check.get("違反"):
        return "violation_checked", "pass" if passed else "fail"
    if passed:
        return "no_candidate", "pass"
    return "violation_checked", "fail"


def execution_audit_status(branch: str) -> str:
    return "needs_intermediate_metric" if branch == "no_candidate" else "mapped"


def _violation_key(stem: str, rule_id: str, violation: dict[str, Any]) -> tuple[str, ...]:
    return (
        stem,
        str(violation.get("シート") or ""),
        rule_id,
        str(violation.get("セル範囲") or ""),
        str(violation.get("説明") or ""),
    )


def _detail_paths(detailed_dir: Path) -> list[Path]:
    return [path for path in sorted(detailed_dir.glob("*.json")) if ".error." not in path.name]


def _validate_complete_details(paths_found: list[Path], items: list[dict[str, Any]]) -> None:
    expected = {item["stem"] for item in items}
    stems = [path.stem for path in paths_found]
    duplicates = sorted({stem for stem in stems if stems.count(stem) > 1})
    actual = set(stems)
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if duplicates or missing or extra:
        parts = []
        if duplicates:
            parts.append(f"duplicate={duplicates[:5]} (n={len(duplicates)})")
        if missing:
            parts.append(f"missing={missing[:5]} (n={len(missing)})")
        if extra:
            parts.append(f"extra={extra[:5]} (n={len(extra)})")
        raise InputError("詳細 JSON が全数揃っていない: " + "; ".join(parts))


def _load_detail(
    path: Path, item_by_stem: dict[str, dict[str, Any]]
) -> tuple[dict[str, Any], dict[str, Any]]:
    document = _load_json(path)
    evidence = document.get("chapter4Evidence") or {}
    stem = str(evidence.get("stem") or path.stem)
    item = item_by_stem.get(stem)
    if item is None:
        raise InputError(f"詳細 JSON が凍結入力に無い stem を持つ: {path}")
    if evidence.get("scoringSha256") != item["scoring_sha256"]:
        raise InputError(f"詳細 JSON の採点物 SHA-256 が不一致: {path}")
    return document, item


def _unique_violation_counts(document: dict[str, Any], stem: str) -> dict[tuple[str, str], int]:
    unique: dict[tuple[str, str], set[tuple[str, ...]]] = defaultdict(set)
    for sheet in document.get("sheets", []):
        for table in sheet.get("評価対象エリア", []):
            for check in table.get("評価内容", []):
                rule_id = str(check.get("ルールID") or "")
                for violation in check.get("違反", []):
                    unique[(stem, rule_id)].add(_violation_key(stem, rule_id, violation))
    return {key: len(values) for key, values in unique.items()}


def _iter_rule_rows(
    document: dict[str, Any],
    item: dict[str, Any],
    unique_counts: dict[tuple[str, str], int],
) -> Iterable[dict[str, Any]]:
    manifest = item["manifest"]
    for sheet in document.get("sheets", []):
        tables = sheet.get("評価対象エリア", [])
        for table_index, table in enumerate(tables, start=1):
            columns = table.get("columns", [])
            for check in table.get("評価内容", []):
                rule_id = str(check.get("ルールID") or "")
                branch, tri_state = classify_execution(rule_id, check)
                violations = check.get("違反", [])
                yield {
                    "stem": item["stem"],
                    "scoring_file_name": item["path"].name,
                    "manifest_file_name": manifest["file_name"],
                    "source_format": item["source_format"],
                    "source_sha256": manifest.get("sha256"),
                    "scoring_sha256": item["scoring_sha256"],
                    "c1_file_hash": item["c1"].get("file_hash"),
                    **{key: manifest.get(key) for key in NORMALIZED_COLUMNS[7:14]},
                    "sheet_name": sheet.get("シート名"),
                    "sheet_hidden": sheet.get("非表示"),
                    "sheet_used_range": sheet.get("使用範囲"),
                    "sheet_table_count": len(tables),
                    "table_index": table_index,
                    "table_range": table.get("範囲"),
                    "table_confidence": table.get("信頼度"),
                    "header_rows": table.get("ヘッダー行", []),
                    "header_range": table.get("ヘッダー範囲"),
                    "body_start_row": table.get("bodyStartRow"),
                    "body_end_row": table.get("bodyEndRow"),
                    "footer_rows": table.get("footerRows", []),
                    "stub_cols": table.get("stubCols", []),
                    "column_schemas": columns,
                    "rule_id": rule_id,
                    "passed": check.get("合否"),
                    "tri_state": tri_state,
                    "execution_branch": branch,
                    "audit_status": execution_audit_status(branch),
                    "skipped": check.get("判定対象外"),
                    "confidence": check.get("信頼度"),
                    "severity": check.get("重大度"),
                    "message": check.get("メッセージ") or "",
                    "n_violations_raw": len(violations),
                    "n_violations_unique_file_rule": unique_counts.get((item["stem"], rule_id), 0),
                    "violation_ref": f"{item['stem']}:{rule_id}" if violations else "",
                }


def normalize_documents(items: list[dict[str, Any]], detailed_dir: Path) -> list[dict[str, Any]]:
    item_by_stem = {item["stem"]: item for item in items}
    rows: list[dict[str, Any]] = []
    for path in _detail_paths(detailed_dir):
        document, item = _load_detail(path, item_by_stem)
        counts = _unique_violation_counts(document, item["stem"])
        rows.extend(_iter_rule_rows(document, item, counts))
    return rows


def _write_jsonl_exclusive(path: Path, rows: list[dict[str, Any]]) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.stem}.", suffix=".tmp", dir=path.parent)
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        with temporary.open("w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
        try:
            os.link(temporary, path)
        except FileExistsError:
            return False
        return True
    finally:
        temporary.unlink(missing_ok=True)


def _csv_ready(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: json.dumps(value, ensure_ascii=False, separators=(",", ":")) if isinstance(value, (list, dict)) else value
        for key, value in row.items()
    }


def write_normalized(rows: list[dict[str, Any]], jsonl_path: Path, csv_path: Path) -> tuple[bool, bool]:

    jsonl_created = _write_jsonl_exclusive(jsonl_path, rows)
    csv_created = _write_csv_exclusive(csv_path, [_csv_ready(row) for row in rows], NORMALIZED_COLUMNS)
    return jsonl_created, csv_created


def _iter_violations(document: dict[str, Any], stem: str) -> Iterable[tuple[str, ...]]:
    for sheet in document.get("sheets", []):
        for table in sheet.get("評価対象エリア", []):
            for check in table.get("評価内容", []):
                rule_id = str(check.get("ルールID") or "")
                for violation in check.get("違反", []):
                    key = _violation_key(stem, rule_id, violation)
                    yield (*key, str(violation.get("違反重大度") or ""))


def _insert_violation_batch(connection: sqlite3.Connection, batch: list[tuple[str, ...]]) -> None:
    connection.executemany(
        "INSERT OR IGNORE INTO violations "
        "(stem, sheet_name, rule_id, cell_range, description, severity) VALUES (?, ?, ?, ?, ?, ?)",
        batch,
    )


def _temporary_text_file(destination: Path) -> tuple[Path, Any]:
    fd, name = tempfile.mkstemp(prefix=f".{destination.stem}.", suffix=".tmp", dir=destination.parent)
    os.close(fd)
    path = Path(name)
    return path, path.open("w", encoding="utf-8", newline="")


def normalize_to_files(
    items: list[dict[str, Any]], detailed_dir: Path, normalized_dir: Path
) -> tuple[int, int, dict[str, bool]]:
    normalized_dir.mkdir(parents=True, exist_ok=True)
    item_by_stem = {item["stem"]: item for item in items}
    detail_paths = _detail_paths(detailed_dir)
    _validate_complete_details(detail_paths, items)
    destinations = {
        "table_jsonl": normalized_dir / "table-rules.jsonl",
        "table_csv": normalized_dir / "table-rules.csv",
        "violation_jsonl": normalized_dir / "violations.jsonl",
        "violation_csv": normalized_dir / "violations.csv",
    }
    db_fd, db_name = tempfile.mkstemp(prefix=".violations.", suffix=".sqlite3", dir=normalized_dir)
    os.close(db_fd)
    db_path = Path(db_name)
    temporary: dict[str, Path] = {}
    handles: dict[str, Any] = {}
    try:
        with sqlite3.connect(db_path) as connection:
            connection.execute(
                "CREATE TABLE violations ("
                "stem TEXT NOT NULL, sheet_name TEXT NOT NULL, rule_id TEXT NOT NULL, "
                "cell_range TEXT NOT NULL, description TEXT NOT NULL, severity TEXT NOT NULL, "
                "PRIMARY KEY (stem, sheet_name, rule_id, cell_range, description)) WITHOUT ROWID"
            )
            for index, path in enumerate(detail_paths, start=1):
                document, item = _load_detail(path, item_by_stem)
                batch: list[tuple[str, ...]] = []
                for violation in _iter_violations(document, item["stem"]):
                    batch.append(violation)
                    if len(batch) == 5000:
                        _insert_violation_batch(connection, batch)
                        batch.clear()
                if batch:
                    _insert_violation_batch(connection, batch)
                connection.commit()
                print(f"[normalize pass 1] {index}/{len(detail_paths)} {path.name}", flush=True)

            unique_counts = {
                (stem, rule_id): count
                for stem, rule_id, count in connection.execute(
                    "SELECT stem, rule_id, COUNT(*) FROM violations GROUP BY stem, rule_id"
                )
            }

            for key, destination in destinations.items():
                temporary[key], handles[key] = _temporary_text_file(destination)
            table_csv = csv.DictWriter(handles["table_csv"], fieldnames=NORMALIZED_COLUMNS)
            violation_csv = csv.DictWriter(handles["violation_csv"], fieldnames=VIOLATION_COLUMNS)
            table_csv.writeheader()
            violation_csv.writeheader()

            table_count = 0
            for index, path in enumerate(detail_paths, start=1):
                document, item = _load_detail(path, item_by_stem)
                for row in _iter_rule_rows(document, item, unique_counts):
                    handles["table_jsonl"].write(
                        json.dumps(row, ensure_ascii=False, separators=(",", ":"), default=_json_default) + "\n"
                    )
                    table_csv.writerow(_csv_ready(row))
                    table_count += 1
                print(f"[normalize pass 2] {index}/{len(detail_paths)} {path.name}", flush=True)

            violation_count = 0
            for stem, sheet, rule_id, cell_range, description, severity in connection.execute(
                "SELECT stem, sheet_name, rule_id, cell_range, description, severity "
                "FROM violations ORDER BY stem, sheet_name, rule_id, cell_range, description"
            ):
                item = item_by_stem[stem]
                row = {
                    "violation_ref": f"{stem}:{rule_id}",
                    "stem": stem,
                    "scoring_file_name": item["path"].name,
                    "sheet_name": sheet,
                    "rule_id": rule_id,
                    "cell_range": cell_range,
                    "description": description,
                    "severity": severity,
                }
                handles["violation_jsonl"].write(
                    json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
                )
                violation_csv.writerow(row)
                violation_count += 1

        for handle in handles.values():
            handle.close()
        handles.clear()
        created: dict[str, bool] = {}
        for key, destination in destinations.items():
            try:
                os.link(temporary[key], destination)
                created[key] = True
            except FileExistsError:
                created[key] = False
        return table_count, violation_count, created
    finally:
        for handle in handles.values():
            handle.close()
        for path in temporary.values():
            path.unlink(missing_ok=True)
        db_path.unlink(missing_ok=True)


def _file_state(n_pass: int, n_fail: int, n_abstain: int) -> str:
    if n_fail > 0:
        return "fail"
    if n_pass > 0:
        return "pass"
    if n_abstain > 0:
        return "abstain"
    return FILE_STATE_NO_TABLE


def summarize_file_rule_states(
    items: list[dict[str, Any]], table_rules_csv: Path
) -> list[dict[str, Any]]:
    csv.field_size_limit(min(2**31 - 1, 10**9))
    counts: dict[tuple[str, str], dict[str, int]] = {}
    known = {item["stem"] for item in items}
    with table_rules_csv.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        required = {"stem", "rule_id", "tri_state"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise InputError(f"table-rules.csv に列がない: {sorted(missing)}")
        for row in reader:
            stem = row["stem"]
            if stem not in known:
                raise InputError(f"table-rules.csv に未知の stem: {stem}")
            state = row["tri_state"]
            if state not in {"pass", "fail", "abstain"}:
                raise InputError(f"tri_state が三値でない: {stem} {row['rule_id']} {state!r}")
            bucket = counts.setdefault((stem, row["rule_id"]), {"pass": 0, "fail": 0, "abstain": 0})
            bucket[state] += 1

    rule_ids = sorted({rule_id for _, rule_id in counts})
    for item in items:
        for check in item["c1"].get("rules", []):
            if check.get("rule_id") and check["rule_id"] not in rule_ids:
                rule_ids.append(check["rule_id"])
    rule_ids.sort()

    rows: list[dict[str, Any]] = []
    for item in items:
        manifest = item["manifest"]
        c1_rules = {check.get("rule_id"): check for check in item["c1"].get("rules", [])}
        for rule_id in rule_ids:
            bucket = counts.get((item["stem"], rule_id), {"pass": 0, "fail": 0, "abstain": 0})
            c1_check = c1_rules.get(rule_id) or {}
            rows.append(
                {
                    "stem": item["stem"],
                    "source_format": item["source_format"],
                    "stat_type": manifest.get("stat_type"),
                    "gov_org": manifest.get("gov_org"),
                    "cell": manifest.get("cell"),
                    "rule_id": rule_id,
                    "n_tables": bucket["pass"] + bucket["fail"] + bucket["abstain"],
                    "n_tables_pass": bucket["pass"],
                    "n_tables_fail": bucket["fail"],
                    "n_tables_abstain": bucket["abstain"],
                    "file_state": _file_state(bucket["pass"], bucket["fail"], bucket["abstain"]),
                    "c1_passed": "" if not c1_check else bool(c1_check.get("passed")),
                    "c1_skipped": "" if not c1_check else bool(c1_check.get("skipped")),
                }
            )
    return rows


def write_file_rule_states(rows: list[dict[str, Any]], output: Path) -> bool:
    return _write_csv_exclusive(output, rows, FILE_RULE_STATE_COLUMNS)


def _common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--c1", type=Path, default=DEFAULT_C1)
    parser.add_argument("--xlsx-dir", type=Path, default=DEFAULT_XLSX_DIR)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="第4章 e-Stat 詳細証拠パイプライン")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("candidates", "analyze", "normalize", "file-rule-states", "all"):
        child = subparsers.add_parser(name)
        _common_arguments(child)
        if name in {"analyze", "all"}:
            child.add_argument("--limit", type=int, default=0, help="先頭N件だけ解析（0=全件）")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        items = load_joined_inputs(args.manifest, args.c1, args.xlsx_dir)
    except (OSError, json.JSONDecodeError, InputError) as exc:
        print(f"[入力エラー] {exc}")
        return 2

    normalized_dir = args.output_root / "normalized"
    candidates_path = normalized_dir / "candidates.csv"
    detailed_dir = args.output_root / "detailed"
    if args.command in {"candidates", "all"}:
        created = write_candidates(items, candidates_path)
        print(f"{'作成' if created else 'SKIP (既存)'}: {candidates_path} ({len(items)} files)")

    failed = 0
    if args.command in {"analyze", "all"}:
        created, skipped, failed = analyze_items(items, detailed_dir, limit=args.limit)
        print(f"詳細解析: created={created} skipped={skipped} failed={failed}")

    if args.command in {"normalize", "all"}:
        try:
            table_rows, violation_rows, created = normalize_to_files(items, detailed_dir, normalized_dir)
        except (OSError, sqlite3.Error, json.JSONDecodeError, InputError) as exc:
            print(f"[正規化エラー] {exc}")
            return 2
        print(
            f"正規化: table_rule_rows={table_rows} violation_rows={violation_rows} "
            + " ".join(f"{key}={'created' if made else 'skip(existing)'}" for key, made in created.items())
        )
    if args.command in {"file-rule-states", "all"}:
        states_path = args.output_root / "file-rule-states.csv"
        try:
            rows = summarize_file_rule_states(items, normalized_dir / "table-rules.csv")
        except (OSError, InputError) as exc:
            print(f"[三値集計エラー] {exc}")
            return 2
        created = write_file_rule_states(rows, states_path)
        print(f"{'作成' if created else 'SKIP (既存)'}: {states_path} ({len(rows)} rows)")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
