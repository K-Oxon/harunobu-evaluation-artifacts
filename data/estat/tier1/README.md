# e-Stat Tier 1 data

論文で評価した600件を固定して再実行するためのデータ。

- `manifest.json`: 取得URL、ファイル名、期待SHA-256、層、標本重み
- `selection.json`: 固定seedによる層化抽出の記録
- `fingerprint.json`: 取得ファイルの構造指紋
- `conversion.json`: LibreOffice変換と入力検証の記録

`just reproduce-estat`はmanifestのSHA-256を照合してから変換と採点を実行する。
