"""Build publication CSV and Typst tables from tracked evaluation results. Uses figures._lib and writes to figures/tables/."""

from __future__ import annotations

import statistics

import _lib as L




RULE_DETAILS = {
    "L1-01": ("ファイル構造", "拡張子とファイル内容を照合"),
    "L1-02": ("表領域", "推定表を数え、1シート内の複数表を検出"),
    "L1-03": ("表領域", "表内の空行と空列、表間の空行を検出"),
    "L1-04": ("表外セル", "表外と推定した表題、注記、出典等を検出"),
    "L1-05": ("ヘッダー領域", "ヘッダー領域の欠落と連番の項目名を検出"),
    "L1-06": ("セル内容", "前後空白、連続スペース、全角スペース、体裁用改行を検出"),
    "L1-07": ("セル内容", "改行や区切り記号から複数値を推定"),
    "L1-08": ("セル内容、表領域", "文字辞書とUnicode範囲に基づいて検出し、xlsxでは警告"),
    "L1-09": ("ヘッダー領域、セル内容", "空白とゼロの混在列を抽出し、ゼロの不自然さを判定"),
    "L1-10": ("ファイル構造、表領域", "表内の画像、図形、グラフを検出"),
    "L1-11": ("セル書式", "列内の色、太字、斜体の使い分けを検出"),
    "L1-12": ("ファイル構造、表領域", "表と重なる結合を検出し、データ領域の結合を違反とする"),
    "L1-13": ("ファイル構造", "使用範囲内の非表示行と非表示列を検出"),
    "L1-14": ("CSVの物理行", "セル内改行とクォート不整合を検出"),
    "L1-15": ("CSVの引用符、列数", "引用符の不整合と列数不一致を検出"),
    "L2-01": ("列型、セル内容", "数値主体列で、単位や注記を伴う文字列を検出"),
    "L2-02": ("行見出し、セル内容", "行見出しの省略記号と途中の空白を検出"),
    "L2-03": ("ヘッダー領域", "ヘッダー領域の値を列ごとに連結し、空欄、重複、セル結合を検出"),
    "L2-04": ("セル内容", "値の分布と文字列の類似度から表記揺れを推定"),
    "L2-05": ("セル内容", "「その他」を含む低頻度値から詳細の混在を推定"),
    "L2-06": ("ファイル構造、表領域", "表内の数式セルと参照切れを検出"),
    "L3-01": ("表領域、ヘッダー領域", "表の開始行、ヘッダー領域直後のデータ開始、ヘッダー行数を検査"),
    "L3-02": ("なし", "―"),
    "L3-03": ("なし", "―"),
    "L3-04": ("ヘッダー領域、セル内容", "数値列の項目名から単位表記を検査"),
    "L3-05": ("ヘッダー領域、セル内容", "日付形式を分類し、非標準表記と形式の混在を検出"),
    "L3-06": ("ヘッダー領域、セル内容", "地域名の略称と地域コード列の欠落を検出"),
    "L3-07": ("複数ファイルのヘッダー領域", "項目名の集合、列数、列順を比較"),
    "L3-08": ("なし", "―"),
    "L3-09": ("ヘッダー領域、セル内容", "列数、時間軸の項目名、番号付き項目名から横持ちを推定"),
}

RULE_ORDER = (
    [f"L1-{i:02d}" for i in range(1, 16)]
    + [f"L2-{i:02d}" for i in range(1, 7)]
    + [f"L3-{i:02d}" for i in range(1, 10)]
)

CSV_RULE_LABELS = {
    "L1-14": "1 行 1 データ（CSV）",
    "L1-15": "CSVのクォート",
}

RULE_CONDITIONS = {
    "L1-05": "AI補助",
    "L1-09": "AI必須",
    "L1-11": "AI補助",
    "L1-14": "CSV/TSVのみ",
    "L1-15": "CSV/TSVのみ",
    "L2-01": "AI補助",
    "L2-02": "AI補助",
    "L2-04": "AI補助",
    "L2-05": "AI補助",
    "L3-02": "判定対象外",
    "L3-03": "判定対象外",
    "L3-04": "AI補助",
    "L3-06": "AI補助",
    "L3-07": "一括評価のみ",
    "L3-08": "判定対象外",
    "L3-09": "AI補助",
}


def build_rules_table() -> None:
    labels = L.rule_labels() | CSV_RULE_LABELS
    assert set(RULE_DETAILS) == set(RULE_ORDER)

    rows, csv_rows = [], []
    for rid in RULE_ORDER:
        inp, method = RULE_DETAILS[rid]
        condition = RULE_CONDITIONS.get(rid, "―")
        typ_label = (
            ("raw", "数値データの#linebreak()数値属性")
            if rid == "L2-01"
            else labels[rid]
        )
        typ_input = (
            ("raw", "複数ファイルの#linebreak()ヘッダー領域")
            if rid == "L3-07"
            else inp
        )
        rows.append([rid, typ_label, typ_input, method, condition])
        csv_rows.append([rid, labels[rid], inp, method, condition])

    print("[tab-rules] 2026年ルール30項目の主な入力と判定方法")
    L.write_csv("tab-rules", ["rule_id", "rule_name", "input", "method", "condition"], csv_rows)
    L.typ_table(
        "tab-rules",
        columns=["auto", "1.1fr", "1.15fr", "2.7fr", "1fr"],
        header=["ID", "ルール", "主な入力", "判定方法", "実行条件"],
        rows=rows,
        caption="harunobuによる2026年ルールの判定方法",
        label="tab:rules", wide=True,
    )




def _eval_summary(ev: dict) -> dict:
    pf = [r for r in ev["per_file"] if r.get("eob") and r.get("gt_tables") is not None]
    e2 = ev["micro"]["eob"]["EoB-2"]
    cov = ev["micro"]["coverage"]
    gt_n = sum(r["gt_tables"] for r in pf)
    pred_n = e2["tp"] + e2["fp"]
    return {
        "n_files": len(pf), "gt": gt_n, "pred": pred_n, "ratio": pred_n / gt_n,
        "f1": e2["f1"], "coverage": cov["coverage"], "purity": cov["purity"],
    }


def build_layout_table() -> None:
    deco = _eval_summary(L.load_deco_eval())
    ts = _eval_summary(L.load_tablesense_eval())
    print(f"[tab-layout] DECO n={deco['n_files']} ratio={deco['ratio']:.2f} | "
          f"TS n={ts['n_files']} ratio={ts['ratio']:.2f}")

    def f3(x): return f"{x:.3f}"
    def f2(x): return f"{x:.2f}"

    spec = [
        ("評価ファイル数", f"{deco['n_files']:,}", f"{ts['n_files']:,}"),
        ("アノテーション上の表数 / 推定表数", f"{deco['gt']:,} / {deco['pred']:,}", f"{ts['gt']:,} / {ts['pred']:,}"),
        ("推定表数 ÷ アノテーション上の表数", f"{deco['ratio']:.2f}", f"{ts['ratio']:.2f}"),
        ("EoB-2 micro F1", f3(deco["f1"]), f3(ts["f1"])),
        ("coverage / purity", f"{f2(deco['coverage'])} / {f2(deco['purity'])}",
         f"{f2(ts['coverage'])} / {f2(ts['purity'])}"),
    ]
    L.write_csv("tab-layout-metrics", ["metric", "DECO", "TableSense"], [list(s) for s in spec])
    L.typ_table(
        "tab-layout-metrics",
        columns=["auto"] * 3,
        header=["指標", "DECO", "TableSense"],
        rows=[list(s) for s in spec],
        caption="公開データ2組の表領域アノテーションとharunobu推定の照合結果",
        label="tab:layout-metrics",
    )




GROUPS = {
    "単辺±1": [f"shift_{s}{d}" for s in ("top", "bottom", "left", "right") for d in ("-1", "+1")],
    "単辺±2": [f"shift_{s}{d}" for s in ("top", "bottom", "left", "right") for d in ("-2", "+2")],
    "四辺複合": ["expand_all1", "shrink_all1", "expand_all2", "shrink_all2"],
    "過分割": ["split_blank", "split_2", "split_3"],
    "Header±1": ["header+1", "header-1"],
    "実レイアウト": ["detector"],
}
LAYOUT_DEPENDENCY_ROWS = [
    (
        "推定値を直接判定",
        "推定表数、表とヘッダー領域の開始位置、データ開始位置、ヘッダー行数を適否条件に使用",
        "L1-02, L3-01",
    ),
    (
        "領域関係を判定",
        "推定表領域内・表間の空行・空列または表外セルを検査",
        "L1-03, L1-04",
    ),
    (
        "検査範囲",
        "表領域、ヘッダー領域、データ領域、列型が検査セルを規定",
        "L1-05〜07, L1-10〜12, L2-01, L2-03, L2-06, L3-04〜06, L3-09",
    ),
    (
        "判定値・適用可否",
        "L2-02は行見出しとデータ領域、L2-04およびL2-05はデータ領域、列型、非空件数および値の種類数を使用",
        "L2-02, L2-04, L2-05",
    ),
    (
        "ファイル・シート単位",
        "ファイル形式またはシートの使用範囲を検査",
        "L1-01, L1-13",
    ),
    (
        "判定値を固定",
        ".xlsxでは適合判定を維持し、警告候補セルを推定表領域から取得",
        "L1-08",
    ),
]


def flip_rates(sens: dict) -> dict[str, dict[str, float]]:
    pf = sens["per_file"]
    out: dict[str, dict[str, float]] = {}
    for rid in L.EXCEL_RULES:
        out[rid] = {}
        for g, variants in GROUPS.items():
            n = flips = 0
            for rec in pf:
                base = rec["baseline"]["rules"].get(rid)
                if base is None:
                    continue
                for v in variants:
                    var = rec["variants"].get(v)
                    if var is None:
                        continue
                    changed = var["rules"].get(rid)
                    if changed is None:
                        continue
                    n += 1
                    flips += changed != base
            out[rid][g] = 100 * flips / n if n else float("nan")
    return out


def build_sensitivity_table() -> None:

    sens = L.load_sensitivity()
    fr = flip_rates(sens)
    L.write_csv(
        "tab-sensitivity",
        ["relation", "role", "rules"],
        LAYOUT_DEPENDENCY_ROWS,
    )
    L.typ_table(
        "tab-sensitivity",
        columns=["auto"] * 3,
        header=["関係", "判定への入り方", "ルール"],
        rows=[list(row) for row in LAYOUT_DEPENDENCY_ROWS],
        caption="レイアウト推定とルール判定の関係",
        label="tab:sensitivity",
    )

    L.write_csv("tab-sensitivity-by-rule", ["rule_id"] + list(GROUPS),
                [[r] + [f"{fr[r][g]:.1f}" for g in GROUPS] for r in L.EXCEL_RULES])







POPULATION = [
    ("e-Stat 政府統計(ファイル掲載あり)", 739, "調査", "REPORT-20260717 §2"),
    ("うち Excel 実体を持つ調査(実効母集団)", 677, "調査", "REPORT-20260717 §2"),
    ("Excel ファイル", 997_608, "ファイル", "REPORT-20260717 §2"),
    ("期・地域反復を畳んだテンプレート", 118_793, "テンプレ", "ADR 2026-07-06 §11.1(scheme v2)"),
    ("抽出フレーム(種別不明の 3 調査を除外)", None, "テンプレ", "tier1-selection.json(セル母数の和)"),
    ("層化無作為抽出(20 セル×30 件)", None, "テンプレ", "tier1-selection.json"),
]
ORG_ORDER = ["総務省", "経済産業省", "厚生労働省", "農林水産省", "国土交通省", "その他集約"]
STAT_ORDER = ["基幹統計", "一般統計", "業務統計"]


def build_sample_tables() -> None:
    sel = L.load_selection()
    cells = {c["cell"]: c for c in sel["cells"]}
    frame_n = sum(c["pool_n_templates"] for c in sel["cells"])
    n_sel, n_surv = sel["n_selected"], sel["n_distinct_surveys"]
    print(f"[tab-sample] frame={frame_n:,} selected={n_sel} surveys={n_surv} seed={sel['seed']}")

    pop_rows = []
    for label, n, unit, src in POPULATION:
        if n is None:
            n = frame_n if "フレーム" in label else n_sel
        pop_rows.append([label, f"{n:,}", unit, src])
    L.write_csv("tab-population", ["stage", "n", "unit", "source"], pop_rows)

    rows, csv_rows = [], []
    for st in STAT_ORDER:
        r = [st]
        for org in ORG_ORDER:
            c = cells[f"{st}×{org}"]
            mark = "†" if (c["pool_top_survey_share"] or 0) > 0.5 else ""
            r.append(f"{c['pool_n_templates']:,}{mark}")
            csv_rows.append([st, org, c["pool_n_templates"], c["pool_n_surveys"], c["pool_top_survey_share"],
                             c["n_selected"], c["selected_n_surveys"]])
        rows.append(r)
    ref = [cells[k] for k in cells if k.startswith("加工統計") or k.startswith("その他×")]
    ref_txt = " / ".join(f"{c['stat_type']} {c['pool_n_templates']:,}" for c in ref)
    for c in ref:
        csv_rows.append([c["stat_type"], "(府省を層にしない)", c["pool_n_templates"], c["pool_n_surveys"],
                         c["pool_top_survey_share"], c["n_selected"], c["selected_n_surveys"]])
    rows.append(["参照セル(府省で層化しない)"] + [f"{c['stat_type']} {c['pool_n_templates']:,}" for c in ref] + [""] * (6 - len(ref)))
    L.write_csv("tab-sample-cells", ["stat_type", "gov_org", "pool_templates", "pool_surveys", "top_survey_share",
                                     "n_selected", "selected_surveys"], csv_rows)
    L.typ_table(
        "tab-sample-cells",
        columns=["auto"] * 7,
        header=["統計種別 / 府省"] + ORG_ORDER,
        rows=rows,
        caption=f"抽出フレーム（テンプレート数{frame_n:,}）の層化格子。各セルから30テンプレートを無作為抽出し、"
                f"計{n_sel}件（{n_surv}調査）とした。",
        note="†は単一調査がセルの過半を占めることを示す。",
        label="tab:sample-cells", wide=True,
    )




AI_INFLATED = {"L1-05", "L1-11", "L2-01", "L2-02", "L2-04", "L2-05", "L3-04", "L3-06", "L3-09"}




def build_rule_pass_table() -> None:
    run = L.load_tier1_run()
    labels, unscored = L.rule_labels(), L.unscored_reason()




    states = L.load_file_rule_states()
    moved = L.check_states_against_c1(states, run)
    corrected = {r["rule_id"]: r for r in L.rule_pass_stats(states, run)["overall"]}
    rows, csv_rows = [], []
    for c1 in run["aggregate"]["overall"]["per_rule"]:
        rid = c1["rule_id"]
        if rid not in L.EXCEL_RULES:
            continue
        name = labels[rid] + ("‡" if rid in AI_INFLATED else "")
        if c1["n_applicable"] == 0:
            reason = {"ai_gated": "AI補助必須", "not_implemented": "判定対象外", "bulk_only": "一括評価専用"}[unscored[rid][0]]
            rows.append([rid, f"{labels[rid]}（{reason}）", "0", "―"])
            csv_rows.append([rid, labels[rid], c1["severity"], 0, "", "", "", "", reason, 0])
            continue
        r = corrected[rid]
        rows.append([rid, name, f"{r['n_applicable']}", L.pct(r["pass_rate"])])
        csv_rows.append([rid, labels[rid], r["severity"], r["n_applicable"], r["pass_rate"], r["ci95_low"],
                         r["ci95_high"], r["weighted_pass_rate"], "", moved.get(rid, (0, 0))[0]])
    L.write_csv("tab-rule-pass", ["rule_id", "label", "severity", "n_applicable", "pass_rate", "ci95_low",
                                  "ci95_high", "weighted_pass_rate", "unscored_reason",
                                  "n_files_all_tables_abstain"], csv_rows)
    L.typ_table(
        "tab-rule-pass",
        columns=["auto"] * 4,
        header=["ID", "ルール", "適用ファイル数", "判定通過率（%）"],
        rows=rows,
        caption="e-Stat由来600ファイルのルール別判定通過率",
        label="tab:rule-pass", wide=True,
    )
    changed = {rid: n for rid, (n, _) in moved.items() if n}
    print(f"[tab-rule-pass] C1 から分母を訂正したルール: {changed}")




STAT_TYPES = ["基幹統計", "一般統計", "業務統計", "加工統計", "その他"]




def _file_stats(files: list[dict], key: str, value: str) -> tuple[int, float]:
    fs = [f for f in files if f["ok"] and f["strata"].get(key) == value]
    tables = [f["n_tables"] for f in fs]
    return len(fs), statistics.median(tables)


def _pass(group: dict, rid: str) -> str:
    for r in group["per_rule"]:
        if r["rule_id"] == rid:
            return L.pct(r["pass_rate"], 0) if r["n_applicable"] else "―"
    return "―"


def build_strata_tables() -> None:
    run = L.load_tier1_run()
    files = run["files"]
    agg = run["aggregate"]
    ov = agg["overall"]

    def csv_row(label: str, g: dict, n_files: int, med_tables: float) -> list:
        l1 = g["levels"]["L1"]
        return [label, f"{n_files}", f"{med_tables:g}", _pass(g, "L1-02"), _pass(g, "L3-01"),
                f"{l1['mean_score']:.1f}", f"{100 * l1['n_zero'] / g['n_ok']:.0f}"]

    csv_header = ["統計種別", "n", "検出表数（中央値）", "L1-02 判定通過率（%）", "L3-01 判定通過率（%）",
                  "L1平均点", "L1強制0点（%）"]
    st = agg["by_stratum"]["stat_type"]
    csv_rows = []
    for s in STAT_TYPES:
        n, mt = _file_stats(files, "stat_type", s)
        csv_rows.append(csv_row(s, st[s], n, mt))
    allf = [f for f in files if f["ok"]]
    csv_rows.append(csv_row("全体", ov, len(allf), statistics.median(f["n_tables"] for f in allf)))
    L.write_csv("tab-stat-type", csv_header, csv_rows)

    paper_columns = [0, 1, 5, 6]
    paper_header = [csv_header[i] for i in paper_columns]
    paper_rows = [[row[i] for i in paper_columns] for row in csv_rows]
    L.typ_table(
        "tab-stat-type",
        columns=["auto"] * 4,
        header=paper_header,
        rows=paper_rows,
        caption="統計種別ごとのharunobuのL1判定結果。",
        note="L1平均点は100点満点である。L1強制0点は、L1の強制0点項目が一つ以上不適合となった割合であり、"
             "L1の全項目が不適合であることを意味しない。基幹統計等は2026年ルールの適用対象外である。",
        label="tab:stat-type", wide=True,
    )

    print(f"[tab-strata] stat_type rows={len(paper_rows)}")





if __name__ == "__main__":
    L.TAB_DIR.mkdir(parents=True, exist_ok=True)
    build_rules_table()
    build_layout_table()
    build_sensitivity_table()
    build_sample_tables()
    build_rule_pass_table()
    build_strata_tables()
    print("done:", L.TAB_DIR.relative_to(L.ROOT))
