"""Siril 実機での天球照合テスト（公開サンプル apod4.jpg 専用）。

SkySolver で解いた後、Siril が検出した星を Siril 自身の pix2radec で
天球座標に変換し、写っている北斗七星 7 星と照合する。中心座標だけの検証では
上下反転（鏡像）の解を見逃すため、既知の恒星位置で独立に確かめる。

使い方は tests/README.md を参照。ユーザーの画像には使わないこと。
"""
from pathlib import Path
import sys

import sirilpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import SkySolver  # noqa: E402

# 北斗七星（J2000/ICRS、度）
DIPPER = {"Dubhe": (165.932, 61.751), "Merak": (165.460, 56.383),
          "Phecda": (178.457, 53.695), "Megrez": (183.857, 57.033),
          "Alioth": (193.507, 55.960), "Mizar": (200.981, 54.925),
          "Alkaid": (206.885, 49.313)}

siril = sirilpy.SirilInterface()
siril.connect()
try:
    SkySolver.run(siril, 20000)
    radec = [siril.pix2radec(s.xpos, s.ypos) for s in siril.get_image_stars()]
    matched = 0
    for name, (ra, dec) in DIPPER.items():
        dist = min(SkySolver.separation_deg(ra, dec, r, d) for r, d in radec)
        matched += dist < 0.3
        siril.log(f"CHECK {name}: 最寄りの検出星まで {dist * 60:.1f} 分角")
    if matched < 6:
        raise AssertionError(f"北斗七星との一致が {matched}/7 です（鏡像の疑い）")
    siril.log(f"SKYCHECK_OK: 北斗七星 {matched}/7 一致")
finally:
    siril.disconnect()
