// 図: harunobu の処理パイプライン（第2章）。just tdp-figs で fig-pipeline.pdf を再生成する。
// 出典: harunobu ARCHITECTURE.md / docs/design-docs/layout-detection.md / core/analyzer.py / core/scorer.py
#set page(width: auto, height: auto, margin: 4pt)
#let coreTitleSize = 8pt
#let bodySize = 7pt
#let moduleTitleSize = 6.5pt
#let detailSize = 5.8pt
#let arrowSize = 11pt
#set text(font: ("Helvetica", "Hiragino Kaku Gothic ProN"), size: bodySize)

#let endpoint(body, w: auto) = box(
  width: w,
  stroke: 0.7pt + black,
  fill: white,
  inset: (x: 4pt, y: 4pt),
  radius: 2pt,
  align(center + horizon, body),
)

#let interface(body) = box(
  stroke: 0.5pt + luma(110),
  fill: luma(252),
  inset: (x: 6pt, y: 3pt),
  radius: 2pt,
  body,
)

#let step(body) = box(
  width: 100%,
  stroke: 0.5pt + luma(90),
  fill: white,
  inset: (x: 3pt, y: 2pt),
  radius: 2pt,
  align(center + horizon, text(size: detailSize, body)),
)

#let stage(title, w, h, ..items) = box(
  width: w,
  height: h,
  stroke: 0.65pt + luma(55),
  fill: white,
  inset: (x: 4pt, y: 4pt),
  radius: 2pt,
  align(
    center + horizon,
    stack(
      dir: ttb,
      spacing: 2pt,
      align(center, text(size: moduleTitleSize, weight: "bold", title)),
      ..items.pos(),
    ),
  ),
)

#let flow-arrow = align(center + horizon, text(size: arrowSize)[→])
#let core-columns = (52pt, 9pt, 118pt, 9pt, 104pt, 9pt, 78pt)

#let core = box(
  width: 416pt,
  stroke: 1pt + luma(35),
  fill: luma(246),
  inset: (x: 7pt, y: 6pt),
  radius: 4pt,
  stack(
    dir: ttb,
    spacing: 5pt,
    align(
      left,
      stack(
        dir: ltr,
        spacing: 5pt,
        text(size: coreTitleSize, weight: "bold")[harunobu Core],
        text(size: detailSize, fill: luma(70))[共通判定処理],
      ),
    ),
    grid(
      columns: core-columns,
      gutter: 3pt,
      align: center + horizon,
      stage(
        [Reader], 52pt, 43pt,
        step[Excel / CSV#linebreak()読込・検証],
      ),
      flow-arrow,
      stage(
        [LayoutDetector#linebreak()（レイアウト推定）], 118pt, 112pt,
        step[① 非空セル領域の検出#linebreak()（空行1行で分割）],
        step[② 境界トリミング#linebreak()（表題、注記、出典を `others` へ）],
        step[③ ヘッダー領域の推定],
        step[④ 列スキーマ推定],
        step[⑤ 隣接表の統合とヘッダー継承],
      ),
      flow-arrow,
      stage(
        [MRChecker#linebreak()（ルール判定）], 104pt, 91pt,
        step[1ルール = 1プラグイン],
        step[表ごとに `check()` を並列実行],
        step[適合 / 不適合 / 判定不能#linebreak()+ confidence + 違反セル],
      ),
      flow-arrow,
      stage(
        [LevelScorer#linebreak()（採点）], 78pt, 76pt,
        step[レベル別0から100点],
        step[FATAL失敗 → 強制0点],
        step[CRITICAL / MAJOR / MINOR#linebreak()→ 固定減点],
      ),
    ),
    // AI補助は一部のルール判定だけが任意に呼び出す。
    grid(
      columns: core-columns,
      gutter: 3pt,
      align: center + horizon,
      [], [], [], [],
      stack(
        dir: ttb,
        spacing: 1pt,
        align(center, text(size: arrowSize)[↑]),
        box(
          width: 86pt,
          stroke: (dash: "dashed", thickness: 0.55pt, paint: luma(85)),
          fill: luma(252),
          inset: (x: 3pt, y: 2pt),
          radius: 2pt,
          align(center, stack(
            dir: ttb,
            spacing: 1pt,
            text(size: moduleTitleSize, weight: "bold")[AI補助（任意）],
            text(size: detailSize, fill: luma(75))[一部ルールのみ],
          )),
        ),
      ),
      [], [],
    ),
  ),
)

#stack(
  dir: ttb,
  spacing: 5pt,
  align(
    center,
    stack(
      dir: ltr,
      spacing: 5pt,
      text(size: moduleTitleSize, fill: luma(60))[利用インターフェース：],
      interface[CLI],
      interface[Python API],
      interface[Web UI],
    ),
  ),
  align(center, text(size: moduleTitleSize, fill: luma(60))[↓ 共通のCoreを呼び出す]),
  grid(
    columns: (46pt, 10pt, 416pt, 10pt, 50pt),
    gutter: 4pt,
    align: center + horizon,
    endpoint(w: 46pt)[Excel / CSV#linebreak()ファイル],
    flow-arrow,
    core,
    flow-arrow,
    endpoint(w: 50pt)[判定結果#linebreak()JSON / CSV],
  ),
)
