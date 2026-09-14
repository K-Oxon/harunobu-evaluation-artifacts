# harunobu evaluation artifacts

Reproduction code and derived evaluation results for the paper *harunobu: A Software Tool for Checking the Machine Readability of Government Data*.

## Quick start

```console
just build-paper-assets  # Rebuild paper tables and aggregate figures from tracked results
just reproduce-estat     # Replay the frozen 600-file e-Stat evaluation
just reproduce-layout    # Re-run the DECO and TableSense layout evaluations
just verify              # Validate dependencies, metadata, checksums, and generated outputs
```

## 概要

このリポジトリには、[harunobu](https://github.com/digital-go-jp/machine_readability_rule/tree/main/sample_app)の評価スクリプト、評価条件を固定するメタデータ、派生した評価結果、論文図表の生成コードを収録している。

## 再現コマンド

| コマンド | ネットワーク | 処理 |
| --- | --- | --- |
| `just build-paper-assets` | 不要 | `results/`から`figures/tables/`と集計図を再生成する |
| `just reproduce-estat` | 必要 | e-Stat 600件を取得・照合し、LibreOffice変換、AI-OFF採点、分母補正を実行する |
| `just reproduce-layout` | 必要 | DECOとTableSenseの固定版を取得し、レイアウト評価を実行する |
| `just verify` | 不要 | 依存関係、メタデータ、チェックサム、リポジトリ構成、生成結果を検査する |

Python依存関係は`uv.lock`、harunobuは`pyproject.toml`に記載したcommitで固定しています。`reproduce-estat`にはLibreOffice、`reproduce-layout`にはLibreOfficeと`bsdtar`が必要である。

## 評価結果

e-Statの測定記録は`results/estat/rulescore-tier1.json`、集計後のファイル×ルール状態は`results/estat/file-rule-states.csv`。論文図表に使用する集計値は`figures/tables/*.csv`へ生成される。列定義は[results/README.md](results/README.md)に記載する。

## 集計サンプル

<details>

<summary>ルール別・省庁別・統計種別通過率</summary>

```sql
INSTALL httpfs;
LOAD httpfs;

WITH rules AS (
    SELECT
        "ID" AS rule_id,
        "ルール名称" AS rule_name
    FROM read_csv(
        'https://raw.githubusercontent.com/digital-go-jp/machine_readability_rule/refs/heads/main/machine-readability-rules.csv',
        header = true,
        all_varchar = true
    )
),
counts AS (
    SELECT
        rule_id,
        gov_org,
        stat_type,
        COUNT(*) AS n_files,
        COUNT(*) FILTER (WHERE file_state = 'pass') AS n_pass,
        COUNT(*) FILTER (WHERE file_state = 'fail') AS n_fail,
        COUNT(*) FILTER (
            WHERE file_state IN ('abstain', 'no_table')
        ) AS n_excluded
    FROM read_csv(
        'results/estat/file-rule-states.csv',
        header = true,
        all_varchar = true
    )
    GROUP BY rule_id, gov_org, stat_type
)
SELECT
    c.rule_id,
    r.rule_name,
    c.gov_org,
    c.stat_type,
    c.n_files,
    c.n_pass,
    c.n_fail,
    c.n_excluded,
    c.n_pass + c.n_fail AS n_applicable,
    ROUND(
        100.0 * c.n_pass / NULLIF(c.n_pass + c.n_fail, 0),
        2
    ) AS pass_rate_pct
FROM counts AS c
LEFT JOIN rules AS r ON c.rule_id = r.rule_id
ORDER BY c.rule_id, c.gov_org, c.stat_type;
```
    
</details>

## ライセンスと引用

コードは[MIT License](LICENSE)、本プロジェクトが作成した結果・集計表・図は[CC BY 4.0](LICENSE-DATA)である。第三者データの出所と条件は[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)、引用情報は[CITATION.cff](CITATION.cff)に記載。
