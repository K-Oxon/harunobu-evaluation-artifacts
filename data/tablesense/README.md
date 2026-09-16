# TableSense data

参照したデータセットは以下の通り。

- [microsoft/TableSense](https://github.com/microsoft/TableSense/tree/3001191378dfc196e7546dab67cbd1094db8919a), commit `3001191378dfc196e7546dab67cbd1094db8919a`
- `Table range annotations.txt`: SHA-256 `5f37900c872af48b03024321327eb2c94005265ea439e66caae28a4637c1cee9`
- [VEnron2 v3](https://doi.org/10.6084/m9.figshare.4798042.v3), file `8639470`: MD5 `9a724c5f667f7fa371619774a1b19c4b`
- [VEUSES v1](https://doi.org/10.6084/m9.figshare.4797991.v1), file `7889902`: MD5 `46f5b8b4233473b2e2b7d388c56a0ea0`
- [VFUSE v3](https://doi.org/10.6084/m9.figshare.4798000.v3), file `7889911`: MD5 `e822971e2a76e033516b6e6adeb605e7`

TableSenseの利用条件は[Open Use of Data Agreement](https://github.com/microsoft/TableSense/blob/3001191378dfc196e7546dab67cbd1094db8919a/LICENSE)、Figshareの3コーパスはCC0である。

`just reproduce-layout`は上記ファイルを取得してチェックサムを照合し、評価結果を`results/layout/eval-tablesense-replay.json`へ出力する。
