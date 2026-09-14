"""Load tracked evaluation data and provide CSV, Typst, and PDF output helpers. Uses harunobu metadata and scripts.metrics; writes outputs under figures/."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

FIG_DIR = Path(__file__).resolve().parent
TAB_DIR = FIG_DIR / "tables"
ROOT = FIG_DIR.parent
RESULTS = ROOT / "results"
LAYOUT_RESULTS = RESULTS / "layout"
ESTAT_RESULTS = RESULTS / "estat"
TIER1 = ROOT / "data" / "estat" / "tier1"
MANIFEST = TIER1 / "manifest.json"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


COL_W_IN = 83 / 25.4
FULL_W_IN = 172 / 25.4


C_L1, C_L2, C_L3 = "#0072B2", "#E69F00", "#009E73"
C_GRAY, C_RED, C_BLUE2 = "#999999", "#D55E00", "#56B4E9"
LEVEL_COLOR = {1: C_L1, 2: C_L2, 3: C_L3}




def _latest(pattern: str, where: Path = RESULTS) -> Path:
    files = sorted(where.glob(pattern))
    if not files:
        raise SystemExit(f"{where}/{pattern} が無い。worktree の results/ からコピーするか再実行する")
    return files[-1]


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_tier1_run() -> dict:
    return load_json(ESTAT_RESULTS / "rulescore-tier1.json")


FILE_RULE_STATES = ESTAT_RESULTS / "file-rule-states.csv"


def load_file_rule_states() -> list[dict]:
    with FILE_RULE_STATES.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


class _FileRuleCheck:

    __slots__ = ("rule_id", "level", "severity", "passed", "skipped", "n_violations")

    def __init__(self, rule_id: str, level: int, severity: str | None, state: str):
        self.rule_id, self.level, self.severity = rule_id, level, severity
        self.passed = state == "pass"
        self.skipped = state not in ("pass", "fail")
        self.n_violations = 0


def rule_pass_stats(states: list[dict], run: dict, *, group_key: str | None = None,
                    rule_ids: list[str] | None = None) -> dict[str, list[dict]]:
    from scripts.metrics.rulestats import RuleAccumulator  # type: ignore

    meta = {r["rule_id"]: r for r in run["aggregate"]["overall"]["per_rule"]}
    weight = {f["file_name"].rsplit(".", 1)[0]: f.get("weight", 1.0) for f in run["files"] if f["ok"]}
    wanted = rule_ids or [r for r in meta]
    by_file: dict[str, dict[str, dict]] = {}
    for row in states:
        by_file.setdefault(row["stem"], {})[row["rule_id"]] = row
    accs: dict[str, RuleAccumulator] = {}
    for stem, rules in by_file.items():
        if stem not in weight:
            continue
        group = "overall" if group_key is None else next(iter(rules.values()))[group_key]
        acc = accs.setdefault(group, RuleAccumulator())
        checks = [_FileRuleCheck(rid, meta[rid]["level"], meta[rid]["severity"], rules[rid]["file_state"])
                  for rid in wanted if rid in rules]
        acc.add(checks, weight=weight[stem])
    return {g: acc.finalize() for g, acc in accs.items()}


def check_states_against_c1(states: list[dict], run: dict) -> dict[str, tuple[int, int]]:
    c1 = {r["rule_id"]: r for r in run["aggregate"]["overall"]["per_rule"]}
    new = {r["rule_id"]: r for r in rule_pass_stats(states, run)["overall"]}
    moved: dict[str, int] = {}
    for row in states:
        if row["file_state"] == "abstain" and row["c1_skipped"] == "False":
            assert row["c1_passed"] == "True", f"{row['stem']} {row['rule_id']}: abstain なのに C1 が fail"
            moved[row["rule_id"]] = moved.get(row["rule_id"], 0) + 1
    out: dict[str, tuple[int, int]] = {}
    for rid, r in c1.items():
        if rid not in new:
            continue
        n_moved = moved.get(rid, 0)
        d_pass = new[rid]["n_pass"] - r["n_pass"]
        d_appl = new[rid]["n_applicable"] - r["n_applicable"]
        assert d_appl == -n_moved and d_pass == -n_moved, \
            f"{rid}: C1 との差 pass{d_pass:+d} n{d_appl:+d} が訂正対象 {n_moved} 件と合わない"
        out[rid] = (n_moved, d_pass)
    return out


def load_manifest() -> dict:
    return load_json(MANIFEST)


def load_deco_eval() -> dict:
    return load_json(LAYOUT_RESULTS / "eval-deco.json")


def load_tablesense_eval() -> dict:
    return load_json(LAYOUT_RESULTS / "eval-tablesense.json")


def load_sensitivity() -> dict:
    return load_json(LAYOUT_RESULTS / "score-sensitivity-injection.json")


def load_sensitivity_realdata() -> dict:
    return load_json(LAYOUT_RESULTS / "score-sensitivity-realdata.json")


def load_selection() -> dict:
    return load_json(TIER1 / "selection.json")


def load_fingerprint() -> dict:
    return load_json(TIER1 / "fingerprint.json")




def rule_registry() -> dict[str, object]:
    from harunobu.rules.registry import registry  # type: ignore

    registry.discover()
    return {r.rule_id: r for r in registry.get_all()}


def rule_labels() -> dict[str, str]:
    from scripts.rule_labels import RULE_LABELS

    return dict(RULE_LABELS)


def unscored_reason() -> dict[str, tuple[str, str]]:
    from scripts.rule_labels import UNSCORED_REASON

    return dict(UNSCORED_REASON)


EXCEL_RULES = [f"L1-{i:02d}" for i in range(1, 14)] + [f"L2-{i:02d}" for i in range(1, 7)] + \
    [f"L3-{i:02d}" for i in range(1, 10)]




def write_csv(name: str, header: list[str], rows: list[list]) -> Path:
    out = TAB_DIR / f"{name}.csv"
    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)
    return out


def typ_escape(s: str) -> str:
    return (str(s).replace("\\", "\\\\").replace("#", "\\#").replace("*", "\\*")
            .replace("_", "\\_").replace("@", "\\@").replace("$", "\\$").replace("<", "\\<")
            .replace("[", "\\[").replace("]", "\\]"))


def typ_table(name: str, *, columns: list[str], header: list[str], rows: list[list],
              caption: str, label: str, wide: bool = False, note: str | None = None,
              source: str = "", placement: str = "top") -> Path:
    def cell(v) -> str:
        if isinstance(v, tuple) and len(v) == 2 and v[0] == "raw":
            return f"[{v[1]}]"
        return f"[{typ_escape(v)}]"

    lines = [f"// Generated by {source or 'build_tables.py'}; do not edit.",
             "#figure("]
    if wide:
        lines.append(f'  placement: {placement},\n  scope: "parent",')
    lines.append("  table(")
    lines.append(f"    columns: ({', '.join(columns)}),")
    lines.append("    align: left + horizon,")
    lines.append("    table.header(" + ", ".join(cell(h) for h in header) + "),")
    for r in rows:
        lines.append("    " + ", ".join(cell(v) for v in r) + ",")
    lines.append("  ),")
    cap = caption + (f" {note}" if note else "")
    lines.append(f"  caption: [{cap}],")
    lines.append(f") <{label}>")
    out = TAB_DIR / f"{name}.typ"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def pct(x, nd: int = 1) -> str:
    return "―" if x is None else f"{100 * x:.{nd}f}"




def mpl():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({
        "font.family": ["Hiragino Sans", "Hiragino Kaku Gothic ProN", "Helvetica", "sans-serif"],
        "font.size": 7.5,
        "font.weight": 300,
        "axes.titlesize": 8,
        "axes.labelsize": 7.5,
        "xtick.labelsize": 7,
        "ytick.labelsize": 7,
        "legend.fontsize": 6.5,
        "axes.unicode_minus": False,
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.linewidth": 0.6,
        "xtick.major.width": 0.5,
        "ytick.major.width": 0.5,
        "savefig.dpi": 300,
    })
    return plt


def save(fig, name: str) -> Path:
    out = FIG_DIR / f"{name}.pdf"
    fig.savefig(out, bbox_inches="tight", pad_inches=0.02)
    print(f"wrote {out.relative_to(ROOT)}")
    return out
