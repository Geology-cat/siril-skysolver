# テスト

## 単体テスト（Siril 不要・通信なし）

Python 3.10 以上で実行できます。

```sh
python3 -m venv .venv
.venv/bin/pip install -r tests/requirements.txt
.venv/bin/python -m unittest discover -s tests -v
```

## Siril 実機テスト（実 API を使用）

公開サンプル画像 [Astrometry.net demo/apod4.jpg](https://github.com/dstndstn/astrometry.net/blob/main/demo/apod4.jpg)（北斗七星）を使います。画像はリポジトリに含めていないので、先に取得してください。

```sh
mkdir -p tests/data
curl -L -o tests/data/apod4.jpg https://raw.githubusercontent.com/dstndstn/astrometry.net/main/demo/apod4.jpg
```

リポジトリのルートで Siril のコンソールモードから実行します（macOS の例）。

```sh
/Applications/Siril.app/Contents/MacOS/siril-cli -d "$PWD" -s tests/integration.ssf
```

ログに `SKYCHECK_OK` が出れば成功です。

- `integration_sky_check.py`: 解いた WCS で Siril の検出星を天球座標に変換し、北斗七星 7 星と照合します。
- `integration_siril.py`: 画素値が変わらないこと、ヘッダーの画像構造が保たれることを確認し、`tests/output/` に結果を保存します。読み込み済みの使い捨て画像に対して `pyscript tests/integration_siril.py` で実行します。

どちらもユーザーの画像には実行しないでください。
