# SPDX-License-Identifier: MIT
# Local Siril integration, 2026. Source and support notes: README.md beside this file.
"""Plate solve the current Siril image with https://skysolver.app.

Only detected star positions and amplitudes leave the computer. No image upload,
API key or local catalogue is needed. Run from Siril 1.4+ (Scripts or pyscript).
"""

import argparse
import json
import math
import os
import random
import re
import ssl
import sys
import time
import urllib.error
import urllib.request

VERSION = "1.0.1"
API_URL = "https://skysolver.app/api/v1/solve/stars"
MAX_STARS = 2000  # Siril 1.4 findstar's maximum (API accepts up to 10,000).
MAX_RESPONSE = 4 * 1024 * 1024

# Celestial WCS only: never copy image dimensions, BITPIX, scaling or exposure
# from the remote header. Remove old PC/CDELT and SIP when replacing a solution.
WCS_KEY = re.compile(
    r"^(?:WCSAXES|WCSNAME|CTYPE[12]|CUNIT[12]|CRPIX[12]|CRVAL[12]|"
    r"CDELT[12]|CROTA[12]|(?:CD|PC)[12]_[12]|RADESYS|RADECSYS|EQUINOX|"
    r"LONPOLE|LATPOLE|(?:A|B|AP|BP)_(?:ORDER|DMAX|\d+_\d+)|"
    r"(?:PV|PS)[12]_\d+)$"
)


class SkySolverError(RuntimeError):
    """An error the user can act on without a Python traceback."""


def separation_deg(ra1, dec1, ra2, dec2):
    """Great-circle distance in degrees (haversine, stable for tiny angles)."""
    ra1, dec1, ra2, dec2 = map(math.radians, (ra1, dec1, ra2, dec2))
    h = (math.sin((dec2 - dec1) / 2) ** 2
         + math.cos(dec1) * math.cos(dec2) * math.sin((ra2 - ra1) / 2) ** 2)
    return math.degrees(2 * math.asin(min(1.0, math.sqrt(h))))


def is_headless(siril):
    """sirilpy 1.0.26 added is_headless(); Siril 1.4.0 ships sirilpy 1.0.8."""
    method = getattr(siril, "is_headless", None)
    if callable(method):
        return bool(method())
    return os.getenv("SIRIL_HEADLESS") is not None


def make_star_payload(stars, width, height, time_limit_ms=30000):
    """Use exactly Siril 1.4's solve-field coordinate conversion.

    Siril's star centres are edge based and measured down from the display top.
    Its FITS table exporter writes X=xpos+0.5, Y=height-ypos+0.5 (1-based).
    Subtracting one gives the API's 0-based coordinates in FITS array order.
    Therefore the returned FITS WCS needs no flip, even with ROWORDER=TOP-DOWN.
    See src/algos/star_finder.c:save_list_as_FITS_table in Siril 1.4.5.
    """
    if not (8 <= width <= 100000 and 8 <= height <= 100000):
        raise SkySolverError("画像サイズがSkySolverの対応範囲外です。")
    if not 1000 <= time_limit_ms <= 30000:
        raise SkySolverError("探索時間は1～30秒で指定してください。")
    rows = []
    for star in stars or []:
        x = float(star.xpos) - 0.5
        y = height - float(star.ypos) - 0.5
        flux = float(star.A)
        if (all(math.isfinite(v) for v in (x, y, flux)) and flux > 0
                and 0 <= x < width and 0 <= y < height):
            rows.append([x, y, flux])
    rows.sort(key=lambda row: row[2], reverse=True)
    rows = rows[:MAX_STARS]
    if len(rows) < 10:
        raise SkySolverError(
            f"有効な星が{len(rows)}個しかありません。動的PSFの検出設定を調整し、"
            "星が10個以上検出される画像で実行してください。"
        )
    return {"width": width, "height": height, "stars": rows,
            "pixel_origin": 0, "epoch": "J2000", "time_limit_ms": time_limit_ms}


def solve(payload, log=print, *, opener=None, sleep=time.sleep):
    """Bounded requests; honour rate limiting without repeated blind retries."""
    if opener is None:
        import certifi
        context = ssl.create_default_context(cafile=certifi.where())
        opener = lambda req, timeout: urllib.request.urlopen(
            req, timeout=timeout, context=context)
    body = json.dumps(payload, allow_nan=False).encode("utf-8")
    for attempt in range(3):
        req = urllib.request.Request(
            API_URL, data=body, method="POST",
            headers={"Content-Type": "application/json", "Accept": "application/json",
                     "User-Agent": f"Siril-SkySolver/{VERSION}"})
        try:
            with opener(req, timeout=45) as response:
                data = response.read(MAX_RESPONSE + 1)
            if len(data) > MAX_RESPONSE:
                raise SkySolverError("APIの応答が大きすぎます。")
            result = json.loads(data)
            if not isinstance(result, dict):
                raise SkySolverError("APIから不正な応答が返りました。")
            if result.get("solved") is not True:
                reason = str(result.get("error", "no solution"))[:300]
                raise SkySolverError(f"座標を解決できませんでした: {reason}")
            return result
        except urllib.error.HTTPError as exc:
            try:
                info = json.loads(exc.read(4096))
                detail = str(info.get("message", info.get("error", "")))[:300]
            except (ValueError, AttributeError):
                detail = ""
            if exc.code == 429 and attempt < 2:
                try:
                    delay = max(1.0, float(exc.headers.get("Retry-After", "3")))
                except ValueError:
                    delay = 3.0
                if not math.isfinite(delay) or delay > 60:
                    raise SkySolverError("APIが混雑しています。しばらく待って再実行してください。") from exc
                log(f"SkySolver混雑中。{delay:.0f}秒後に再試行します。")
                sleep(delay + random.uniform(0, 1))
                continue
            raise SkySolverError(f"APIエラー HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise SkySolverError(f"SkySolverへ接続できませんでした: {exc}") from exc
        except (ValueError, UnicodeError) as exc:
            raise SkySolverError("APIの応答を読み取れませんでした。") from exc


def parse_header(text):
    from astropy.io import fits
    # sirilpy's shared-memory string includes the C NUL terminator. Without
    # removing it astropy treats END\0 as an ordinary card, so appended WCS
    # cards end up after END and CFITSIO silently ignores them.
    text = text.rstrip("\x00")
    return fits.Header.fromstring(text, sep="\n" if "\n" in text else "")


def build_header(original, result, width, height):
    """Validate remote WCS, then replace only the celestial solution."""
    import numpy as np
    from astropy.wcs import WCS

    if result.get("width") != width or result.get("height") != height:
        raise SkySolverError("APIの画像サイズが一致しないため、適用を中止しました。")
    text = result.get("fits_header")
    if not result.get("wcs") or not isinstance(text, str) or not text.strip():
        raise SkySolverError("この解はSiril対応のTAN/SIP形式ではありません（全天・魚眼など）。")
    remote = parse_header(text)
    if remote.get("CTYPE1") not in ("RA---TAN", "RA---TAN-SIP") or remote.get(
            "CTYPE2") not in ("DEC--TAN", "DEC--TAN-SIP"):
        raise SkySolverError("対応していないWCS投影形式です。")
    for key in ("A_ORDER", "B_ORDER", "AP_ORDER", "BP_ORDER"):
        if key in remote and not 0 <= remote[key] <= 5:
            raise SkySolverError("SIP歪み補正の次数がSirilの対応範囲外です。")
    for key in ("CRVAL1", "CRVAL2", "CRPIX1", "CRPIX2",
                "CD1_1", "CD1_2", "CD2_1", "CD2_2"):
        if key not in remote or not math.isfinite(float(remote[key])):
            raise SkySolverError(f"WCSの{key}が不正です。")
    if remote.get("RADESYS", "ICRS").upper() != "ICRS":
        raise SkySolverError("APIがJ2000/ICRS以外の座標を返しました。")
    wcs_header = remote.copy()
    wcs_header["NAXIS"] = 2
    wcs_header["NAXIS1"] = width
    wcs_header["NAXIS2"] = height
    wcs = WCS(wcs_header, naxis=2)
    if not np.isfinite(wcs.pixel_scale_matrix).all() or abs(np.linalg.det(
            wcs.pixel_scale_matrix)) < 1e-20:
        raise SkySolverError("WCSの変換行列が不正です。")
    center = wcs.all_pix2world([[width / 2 - .5, height / 2 - .5]], 0)[0]
    if not np.isfinite(center).all() or not -90 <= center[1] <= 90:
        raise SkySolverError("WCSの中心座標が不正です。")
    # Test the supplied matched stars against the actual FITS WCS, rather than
    # assuming the separate JSON wcs object uses FITS's CRPIX convention.
    matched = np.asarray(result.get("matched", []), dtype=float)
    if matched.ndim != 2 or matched.shape[0] < 10 or matched.shape[1] < 4:
        raise SkySolverError("WCSを検証するための一致星が不足しています。")
    pixels = wcs.all_world2pix(matched[:, 2:4], 0)
    residual = np.linalg.norm(pixels - matched[:, :2], axis=1)
    if not np.isfinite(residual).all() or np.median(residual) > 3:
        raise SkySolverError("返されたWCSと一致星の位置が整合しません。")
    merged = parse_header(original)
    for key in list(merged.keys()):
        if WCS_KEY.fullmatch(key) or key in ("RA", "DEC", "RA_D", "DEC_D", "OBJCTRA", "OBJCTDEC"):
            merged.remove(key, remove_all=True, ignore_missing=True)
    for card in remote.cards:
        if WCS_KEY.fullmatch(card.keyword):
            merged[card.keyword] = (card.value, card.comment)
    merged["RADESYS"] = "ICRS"
    merged["RA"] = (float(center[0]), "[deg] Image center ICRS RA")
    merged["DEC"] = (float(center[1]), "[deg] Image center ICRS Dec")
    merged["PLTSOLVD"] = (True, "Solved by SkySolver.app")
    merged.add_history(f"Siril SkySolver {VERSION}: J2000/ICRS, star-list API")
    return merged.tostring(sep="\n", endcard=True, padding=False), center, wcs


def verify_in_siril(siril, wcs, width, height):
    """Compare Siril's own pix2radec with the validated WCS at five points.

    Siril's pix2radec takes edge-based display coordinates with y measured from
    the top and converts them to FITS as (x + 0.5, height - y + 0.5) (1-based).
    The centre alone cannot reveal a mirrored solution, so check the corners.
    """
    import numpy as np
    scale = math.sqrt(abs(np.linalg.det(wcs.pixel_scale_matrix)))
    points = [(width / 2, height / 2), (0, 0), (width, 0), (0, height), (width, height)]
    for x, y in points:
        actual = siril.pix2radec(x, y)
        if actual is None or not all(math.isfinite(v) for v in actual):
            raise SkySolverError("SirilがWCSを認識しませんでした。")
        expected = wcs.all_pix2world([[x - .5, height - y - .5]], 0)[0]
        if separation_deg(actual[0], actual[1], *expected) > 0.1 * scale:
            raise SkySolverError("Sirilでの座標検証に失敗しました。")


def run(siril, time_limit_ms=30000):
    siril.cmd("requires", "1.4.0")
    if not siril.is_image_loaded() or siril.is_sequence_loaded():
        raise SkySolverError("処理する画像を単独で開いてから実行してください（シーケンスは対象外です）。")
    filename = siril.get_image_filename()
    siril.log("SkySolver: 星を検出しています。画像は送信しません。")
    # A new detection avoids reusing a manually selected subset or old stars.
    siril.cmd("findstar", f"-maxstars={MAX_STARS}")
    with siril.image_lock():
        if siril.get_image_filename() != filename or siril.is_sequence_loaded():
            raise SkySolverError("対象画像が変わったため処理を中止しました。")
        shape = siril.get_image_shape()
        if not shape or len(shape) != 3:
            raise SkySolverError("画像サイズを取得できませんでした。")
        _, height, width = shape
        original = siril.get_image_fits_header()
        if not original:
            raise SkySolverError("画像ヘッダーを取得できませんでした。")
        payload = make_star_payload(siril.get_image_stars(), width, height, time_limit_ms)
        siril.log(f"SkySolver: {len(payload['stars'])}個の星の座標・明るさを送信中…")
        result = solve(payload, log=siril.log)
        header, center, wcs = build_header(original, result, width, height)
        siril.undo_save_state("SkySolver plate solution")
        try:
            if not siril.set_image_metadata_from_header_string(header):
                raise SkySolverError("SirilにWCSを設定できませんでした。")
            verify_in_siril(siril, wcs, width, height)
        except Exception:
            siril.set_image_metadata_from_header_string(original)
            raise
    siril.log(f"SkySolver 完了: RA {center[0]:.6f}°, Dec {center[1]:+.6f}° (ICRS/J2000)")
    siril.log("注釈表示・PCC/SPCCに使用できます。WCSを残すにはFITS形式で保存してください。")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--time-limit", type=int, default=30, choices=range(1, 31),
                        metavar="1..30", help="SkySolverの探索時間（秒、既定30）")
    args = parser.parse_args()
    import sirilpy
    if not sirilpy.check_module_version(">=1.0.0"):
        raise SystemExit("sirilpy 1.0.0以上が必要です。Sirilを更新してください。")
    siril = sirilpy.SirilInterface()
    try:
        siril.connect()
        sirilpy.ensure_installed("astropy", "certifi")
        run(siril, args.time_limit * 1000)
    except Exception as exc:
        message = f"SkySolver: {exc}"
        print(message, file=sys.stderr, flush=True)
        try:
            if siril.connected and not is_headless(siril):
                siril.error_messagebox(message)
        except Exception:  # Never hide the original error behind a GUI failure.
            pass
        return 1
    finally:
        if siril.connected:
            siril.disconnect()
    return 0


if __name__ == "__main__":
    sys.exit(main())
