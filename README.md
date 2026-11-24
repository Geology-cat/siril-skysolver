# SkySolver for Siril

[Siril](https://siril.org/) で開いている画像を、無料のオンライン解析サービス [SkySolver](https://skysolver.app/api-docs) でブラインドプレートソルブする Python スクリプトです。撮影位置・焦点距離・API キー・ローカル星表の準備は不要です。

解決すると、Siril の注釈表示や PCC/SPCC（測光色補正）の前提になる天球座標情報（WCS）が画像に設定されます。

> English: A Siril 1.4+ Python script that blind plate-solves the loaded image with the free SkySolver.app star-list API. Only detected star positions and brightnesses are sent — never the image itself. Copy `SkySolver.py` into a Siril script folder, run `reloadscripts`, then choose **Scripts → Python Scripts → SkySolver**.

## 動作環境

- Siril 1.4.0 以上（同梱の sirilpy 1.0.8 以上）。macOS / Windows / Linux
- インターネット接続
- 初回実行時、Siril の Python 環境に不足している `astropy` と `certifi` を自動で導入します。

## インストール

`SkySolver.py` を Siril のスクリプトフォルダにコピーし、Siril 下部のコマンド欄で `reloadscripts` を実行します（Siril の再起動でも反映されます）。

| OS | 既定のスクリプトフォルダ |
| --- | --- |
| macOS | `~/Library/Application Support/org.siril.Siril/scripts` |
| Windows | `%APPDATA%\siril\scripts` |
| Linux | `~/.siril/scripts` または `~/siril/scripts` |

フォルダがなければ作成してください。好きなフォルダに置き、Siril の **環境設定 → スクリプト** でスクリプトの検索パスに追加する方法もあります。

**macOS のインストーラー:** `install.command` をダブルクリックすると上記フォルダにコピーします（既存の別バージョンはバックアップします）。ブラウザでダウンロードした場合は macOS にブロックされることがあるので、右クリック → **開く** を選ぶか、ターミナルで `zsh install.command` を実行してください。

**アンインストール:** コピーした `SkySolver.py` を削除し、`reloadscripts` を実行します。

## 使い方

1. 解決したい画像を単独で開きます（シーケンスは対象外）。
2. **スクリプト → Pythonスクリプト → SkySolver** を実行します。メニューにない場合はコマンド欄で次を実行します。

   ```text
   pyscript SkySolver.py
   ```

3. コンソールに「SkySolver 完了」と中心座標が出たら成功です。
4. 結果を残すには **FITS 形式で保存** してください。元のファイルへの自動保存はしません。GUI では取り消し（Undo）もできます。

探索時間（既定 30 秒、1〜30 秒）を短くする例：

```text
pyscript SkySolver.py --time-limit 12
```

PCC/SPCC のカタログ取得や色補正そのものは Siril で実行してください。本スクリプトが行うのはプレートソルブだけで、Siril 標準の「画像プレートソルバー」とは独立して動きます。

## 送信するデータ

- 送信先は `https://skysolver.app/api/v1/solve/stars` だけです。
- 送るのは画像の縦横サイズ、Siril が検出した最大 2,000 個の星の座標と明るさ、探索オプションのみです。画像そのもの、FITS ヘッダー、ファイル名、撮影日時・場所は送りません。
- SkySolver は無料・匿名（アカウント不要）のサービスで、接続元ごとにレート制限があります。混雑時は API の `Retry-After` に従って最大 2 回再試行し、60 秒を超える待ち時間を求められた場合は中止します。バッチ処理には向きません。

## 対応範囲と制限

- モノクロ・RGB 画像に対応します。RGB は Siril の既定の緑チャンネルで星を検出します。
- 未デベイヤーの CFA（カラーカメラの RAW）画像は、先にデベイヤーしてください。
- 星が 10 個以上必要です。少ない場合は **動的 PSF** の検出設定を調整してください。
- 適用できる解は TAN / TAN-SIP（SIP は 5 次まで）です。全天・魚眼など、SkySolver が投影モデルだけを返す画像は Siril に適用できません。
- FITS の `ROWORDER`（BOTTOM-UP / TOP-DOWN）どちらの画像でも動作します。

## 安全のための検証

- 画素を反転・リサイズ・ストレッチしません。
- 星座標は Siril 自身の Astrometry.net 連携と同じ座標変換で送ります。
- API から返った WCS は、画像サイズ・投影形式・変換行列・一致星の残差を検証してから、古い WCS（PC/CDELT・SIP 係数を含む）を置き換えます。露出時間などそれ以外のヘッダーは保持します。
- 適用後、Siril 自身の座標変換（`pix2radec`）で中心と四隅を確認し、食い違えば元のヘッダーに戻します。四隅も見るので、上下反転した（鏡像の）解は適用されません。

## ファイル

- `SkySolver.py`: 本体（このファイル 1 つで動作します）
- `install.command`: macOS 用インストーラー
- `tests/`: 単体テストと Siril 実機テスト。手順は [tests/README.md](tests/README.md)
- `VALIDATION.md`: 検証記録

## 参照

- [SkySolver API](https://skysolver.app/api-docs)
- [Siril Python API (sirilpy)](https://siril.readthedocs.io/en/stable/Python-API.html)
- [Siril 1.4.5 の星リスト出力（座標変換の根拠）](https://gitlab.com/free-astro/siril/-/blob/1.4.5/src/algos/star_finder.c)

## ライセンス・免責

MIT License（[LICENSE](LICENSE)）。本スクリプトは Siril 開発チームおよび SkySolver.app とは無関係の非公式ツールです。SkySolver の提供状況や利用条件は同サービスに従ってください。
