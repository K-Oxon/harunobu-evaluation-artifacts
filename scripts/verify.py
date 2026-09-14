"""Validate repository metadata, tracked artifact checksums, prohibited paths, and generated paper assets and report failures to standard error."""

from __future__ import annotations

import csv
import gzip
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_NAMES = {".env", ".agents", ".claude", ".git", ".venv", ".uv-cache", "tests", "paper"}
FORBIDDEN_TEXT = re.compile(r"/" + r"Users/|\\" + r"Users\\|\.claude/" + "worktrees")
TEXT_SUFFIXES = {".csv", ".json", ".md", ".py", ".toml", ".typ", ".cff", ".txt"}


def fail(message: str) -> None:
    raise SystemExit(f"verify: {message}")


def load_json(relative: str):
    path = ROOT / relative
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"invalid JSON {relative}: {exc}")


def main() -> int:
    required = (
        "CITATION.cff",
        ".zenodo.json",
        "data/estat/frame/gov_stats_codes-2026-07-06.csv",
        "data/estat/frame/templates-v2.csv.gz",
        "data/estat/tier1/manifest.json",
        "results/estat/rulescore-tier1.json",
        "results/estat/file-rule-states.csv",
        "results/layout/eval-deco.json",
        "results/layout/eval-tablesense.json",
    )
    for relative in required:
        if not (ROOT / relative).is_file():
            fail(f"missing {relative}")

    manifest = load_json("data/estat/tier1/manifest.json")
    if manifest.get("n_entries") != 600 or len(manifest.get("entries", [])) != 600:
        fail("Tier 1 manifest is not exactly 600 entries")
    for row in manifest["entries"]:
        if not re.fullmatch(r"[0-9a-f]{64}", str(row.get("sha256", ""))):
            fail(f"missing expected SHA-256 for {row.get('file_name')}")

    rulescore = load_json("results/estat/rulescore-tier1.json")
    if len(rulescore.get("files", [])) != 600:
        fail("rulescore-tier1.json is not a 600-file run")
    with (ROOT / "results/estat/file-rule-states.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != 16_800 or len({row["stem"] for row in rows}) != 600:
        fail("file-rule-states.csv must contain 16,800 rows and 600 stems")
    if {row["file_state"] for row in rows} - {"pass", "fail", "abstain", "no_table"}:
        fail("file-rule-states.csv contains an unknown state")

    if len(load_json("results/layout/eval-deco.json").get("per_file", [])) != 839:
        fail("eval-deco.json must contain 839 records")
    if len(load_json("results/layout/eval-tablesense.json").get("per_file", [])) != 1_271:
        fail("eval-tablesense.json must contain 1,271 records")
    with gzip.open(ROOT / "data/estat/frame/templates-v2.csv.gz", "rt", encoding="utf-8", newline="") as stream:
        if sum(1 for _ in csv.reader(stream)) - 1 != 118_793:
            fail("templates-v2.csv.gz must contain 118,793 data rows")

    for path in ROOT.rglob("*"):
        if any(part in {".git", ".venv", ".uv-cache"} for part in path.relative_to(ROOT).parts) or not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        if any(part in FORBIDDEN_NAMES for part in relative.parts):
            fail(f"forbidden path: {relative}")
        if path.stat().st_size > 50 * 1024 * 1024:
            fail(f"unexpected tracked-sized file over 50 MiB: {relative}")
        if path.suffix.lower() in TEXT_SUFFIXES or path.name in {"justfile"}:
            text = path.read_text(encoding="utf-8", errors="replace")
            if FORBIDDEN_TEXT.search(text):
                fail(f"private absolute path in {relative}")
    print("verify: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
