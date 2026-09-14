// 図: e-Stat 母集団から 600 件までの絞り込み(第5章)。数値は tables/tab-population.csv(build_tables.py が生成)を読む。
#set page(width: auto, height: auto, margin: 4pt)
#set text(font: ("Helvetica", "Hiragino Kaku Gothic ProN"), size: 7pt)

#let rows = csv("tables/tab-population.csv").slice(1)
#let widths = (330pt, 305pt, 280pt, 255pt, 232pt, 210pt)
#let fills = (luma(250), luma(245), luma(238), luma(230), luma(222), rgb("#cfe3f3"))

#stack(
  dir: ttb,
  spacing: 2.5pt,
  ..rows.enumerate().map(((i, r)) => align(center, box(
    width: widths.at(i), stroke: 0.5pt, fill: fills.at(i), inset: (x: 6pt, y: 3pt), radius: 2pt,
    grid(columns: (1fr, auto), align: (left + horizon, right + horizon), column-gutter: 6pt,
      text(size: 6.8pt, r.at(0)),
      text(weight: "bold", size: 7.5pt)[#r.at(1) #text(weight: "regular", size: 6pt, r.at(2))],
    ),
  ))),
)
