# Third-party notices

この文書は、再現処理が参照する第三者データとソフトウェアの出所、利用条件、公開リポジトリでの扱いを記録します。

取得日、固定版、チェックサムは各データディレクトリのREADMEに記録します。

## e-Stat

- 提供者: 政府統計の総合窓口e-Stat
- 利用条件: [e-Stat利用規約](https://www.e-stat.go.jp/terms-of-use)
- 公開範囲: 取得対象を固定するmanifest、測定結果、補正後集計、論文用集計
- 非公開: 取得したExcel原本と変換途中のファイル

e-Stat由来の加工物には、e-Statを出典として表示し、加工した資料であることを明示します。

`data/estat/frame/`は、e-Statの公開カタログから本評価用に抽出・正規化した加工物です。
`data/estat/tier1/`はその加工フレームからの抽出と取得・変換の記録、`results/estat/`はharunobuによる派生評価結果です。

## DECO

- データセット: [ddenron/deco_dataset](https://github.com/ddenron/deco_dataset)
- 注釈生成ツール: [ddenron/annotations_exporter](https://github.com/ddenron/annotations_exporter)
- 公開範囲: 集計済みの評価結果だけ
- 非公開: 原本、注釈、セル値を読めるオーバーレイPDF

固定commitと取得ファイルのSHA-256は[data/deco/README.md](data/deco/README.md)に記録しています。DECOの原本と注釈はこのリポジトリから再配布しません。

## TableSense

- 注釈と参照実装: [microsoft/TableSense](https://github.com/microsoft/TableSense)
- 注釈の利用条件: [Open Use of Data Agreement](https://github.com/microsoft/TableSense/blob/main/LICENSE)
- VEnron2: [10.6084/m9.figshare.4798042.v3](https://doi.org/10.6084/m9.figshare.4798042.v3), CC0
- VEUSES: [10.6084/m9.figshare.4797991.v1](https://doi.org/10.6084/m9.figshare.4797991.v1), CC0
- VFUSE: [10.6084/m9.figshare.4798000.v3](https://doi.org/10.6084/m9.figshare.4798000.v3), CC0
- 公開範囲: 集計済みの評価結果だけ
- 非公開: 原本と注釈

固定commit、Figshare file ID、配布者のチェックサムは[data/tablesense/README.md](data/tablesense/README.md)に記録しています。

## harunobu

- 上流: [digital-go-jp/machine_readability_rule](https://github.com/digital-go-jp/machine_readability_rule)
- v1で固定したcommit: `516bd2c060eb529ec1c3a1976ee07267c323f354`

公開スクリプトが直接利用するharunobuと各ライブラリは`pyproject.toml`と`uv.lock`で固定しています。
