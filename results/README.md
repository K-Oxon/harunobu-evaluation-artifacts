# Results

評価結果のCSVまたはJSON。

## e-Stat

```text
estat/rulescore-tier1.json
  -> 表単位の適用可否をファイル単位へ集計
estat/file-rule-states.csv
  -> ルール別・統計種別別の集計
../figures/tables/*.csv
```

`rulescore-tier1.json`は600件のAI-OFF測定記録である。`file-rule-states.csv`は600ファイル×28ルールの16,800行で、ファイル単位での集計入力です。

`file-rule-states.csv`の主要列は次のとおりです。

| 列 | 内容 |
| --- | --- |
| `stem` | 拡張子を除いたファイル識別子 |
| `source_format` | 取得時のファイル形式 |
| `stat_type` | 統計種別 |
| `gov_org` | 標本設計上の省庁区分 |
| `cell` | 層化抽出セル |
| `rule_id` | harunobuのルールID |
| `n_tables`, `n_pass`, `n_fail`, `n_abstain` | 表数と表単位の状態内訳 |
| `file_state` | `pass`、`fail`、`abstain`、`no_table`のいずれか |
| `c1_passed`, `c1_skipped` | 元のC1測定記録との照合値 |

`abstain`と`no_table`は、そのルールの通過率の分母から除外します。標本重みは`rulescore-tier1.json`の`files[].weight`を使用します。

## レイアウト評価

- `layout/eval-deco.json`: DECOに対する表領域・セルロール評価
- `layout/eval-tablesense.json`: TableSenseに対する表領域評価
- `layout/score-sensitivity-injection.json`: 注入したレイアウト摂動に対するルール採点感度
- `layout/score-sensitivity-realdata.json`: DECO実データに対するルール採点感度
