import io
import os
from contextlib import nullcontext
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError

import numpy as np
from astropy.io import fits
from astropy.wcs import WCS

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import SkySolver as sky


def solution(width=640, height=480):
    wcs = WCS(naxis=2)
    wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    wcs.wcs.crpix = [width / 2 + .5, height / 2 + .5]
    wcs.wcs.crval = [83.8, -5.4]
    wcs.wcs.cd = [[-.001, .0001], [.0001, .001]]
    header = wcs.to_header()
    # SkySolver emits a CD matrix, rather than astropy's PC + CDELT encoding.
    for key in list(header):
        if key.startswith(("PC", "CDELT")):
            del header[key]
    for i in range(2):
        for j in range(2):
            header[f"CD{i+1}_{j+1}"] = wcs.wcs.cd[i, j]
    xy = np.array([[40 + i * 37, 50 + i * 23] for i in range(12)])
    matched = np.column_stack([xy, wcs.all_pix2world(xy, 0)]).tolist()
    return {"solved": True, "width": width, "height": height,
            "wcs": {"ctype": "RA---TAN"}, "matched": matched,
            "fits_header": header.tostring()}, wcs


class SkySolverTests(unittest.TestCase):
    def test_coordinates_match_siril_asnet_export_and_filtering(self):
        stars = [SimpleNamespace(xpos=10.5+i, ypos=20.5+i, A=100+i) for i in range(12)]
        stars += [SimpleNamespace(xpos=float("nan"), ypos=10, A=10),
                  SimpleNamespace(xpos=20, ypos=30, A=-1)]
        payload = sky.make_star_payload(stars, 640, 480)
        self.assertEqual(len(payload["stars"]), 12)
        self.assertEqual(payload["stars"][0], [21, 448, 111])
        for star in stars[:12]:
            row = next(row for row in payload["stars"] if row[2] == star.A)
            self.assertEqual(row[0] + 1, star.xpos + .5)
            self.assertEqual(row[1] + 1, 480 - star.ypos + .5)

    def test_header_replaces_stale_wcs_preserves_data_metadata(self):
        for roworder in ("TOP-DOWN", "BOTTOM-UP"):
            with self.subTest(roworder=roworder):
                original = fits.PrimaryHDU(np.ones((480, 640), dtype=np.uint16)).header
                original["EXPTIME"] = 120.4
                original["ROWORDER"] = roworder
                original["OBJECT"] = "my target"
                original["PC1_1"] = 99
                original["CDELT1"] = 99
                original["A_ORDER"] = 5
                original["A_5_0"] = 99
                original["OBJCTRA"] = "00 00 00"
                result, _ = solution()
                # The real sirilpy C string has unpadded lines and END + NUL.
                raw = "\n".join(card.image.rstrip() for card in original.cards) + "\nEND\0"
                text, center, _ = sky.build_header(raw, result, 640, 480)
                header = sky.parse_header(text)
                for key in ("BITPIX", "NAXIS1", "NAXIS2", "BSCALE", "BZERO",
                            "EXPTIME", "ROWORDER", "OBJECT"):
                    self.assertEqual(header[key], original[key])
                for key in ("PC1_1", "CDELT1", "A_ORDER", "A_5_0", "OBJCTRA"):
                    self.assertNotIn(key, header)
                self.assertTrue(header["PLTSOLVD"])
                self.assertLess(text.index("CRVAL1"), text.index("\nEND"))
                np.testing.assert_allclose(center, [83.8, -5.4], atol=1e-8)

    def test_refuse_mismatched_or_unrepresentable_solution(self):
        result, _ = solution()
        for update in ({"width": 641}, {"wcs": None, "fits_header": None},
                       {"matched": []},
                       {"matched": [[1, 1, 83.8, -5.4]] * 10}):
            with self.subTest(update=update):
                with self.assertRaises(sky.SkySolverError):
                    sky.build_header(fits.Header().tostring(), result | update, 640, 480)

    def test_sip_distortion_is_preserved(self):
        result, _ = solution()
        header = sky.parse_header(result["fits_header"])
        header["CTYPE1"] = "RA---TAN-SIP"
        header["CTYPE2"] = "DEC--TAN-SIP"
        header["A_ORDER"] = 2
        header["B_ORDER"] = 2
        header["A_2_0"] = 1e-7
        header["B_0_2"] = -2e-7
        wcs = WCS(header, naxis=2)
        xy = np.array(result["matched"])[:, :2]
        result["matched"] = np.column_stack([xy, wcs.all_pix2world(xy, 0)]).tolist()
        result["fits_header"] = header.tostring()
        text, _, _ = sky.build_header(fits.Header().tostring(), result, 640, 480)
        actual = sky.parse_header(text)
        self.assertEqual(actual["A_2_0"], 1e-7)
        self.assertEqual(actual["B_0_2"], -2e-7)

    def test_failed_siril_verification_restores_original_header(self):
        siril = Mock()
        siril.is_image_loaded.return_value = True
        siril.is_sequence_loaded.return_value = False
        siril.get_image_filename.return_value = "unsaved.fit"
        siril.get_image_shape.return_value = (1, 480, 640)
        original = fits.Header({"OBJECT": "original"}).tostring()
        siril.get_image_fits_header.return_value = original
        siril.get_image_stars.return_value = [
            SimpleNamespace(xpos=10.5+i, ypos=20.5+i, A=100+i) for i in range(12)]
        siril.image_lock.return_value = nullcontext()
        siril.pix2radec.side_effect = ValueError("not plate solved")
        result, _ = solution()
        with patch.object(sky, "solve", return_value=result):
            with self.assertRaisesRegex(ValueError, "not plate solved"):
                sky.run(siril)
        self.assertEqual(siril.set_image_metadata_from_header_string.call_count, 2)
        self.assertEqual(siril.set_image_metadata_from_header_string.call_args.args[0], original)

    def test_siril_check_catches_mirrored_solution(self):
        result, _ = solution()
        _, _, wcs = sky.build_header(fits.Header().tostring(), result, 640, 480)

        def siril_like(solution_wcs):
            # Siril 1.4: pix2wcs2(x, ry - y) with FITS pixcrd = (x + .5, y + .5).
            siril = Mock()
            siril.pix2radec.side_effect = lambda x, y: tuple(
                solution_wcs.all_pix2world([[x + .5, 480 - y + .5]], 1)[0])
            return siril

        sky.verify_in_siril(siril_like(wcs), wcs, 640, 480)
        mirrored = wcs.deepcopy()
        mirrored.wcs.cd = wcs.wcs.cd @ np.diag([1, -1])
        mirrored.wcs.crpix = [wcs.wcs.crpix[0], 480 + 1 - wcs.wcs.crpix[1]]
        with self.assertRaisesRegex(sky.SkySolverError, "座標検証"):
            sky.verify_in_siril(siril_like(mirrored), wcs, 640, 480)

    def test_errors_reach_user_with_old_sirilpy_without_is_headless(self):
        # Siril 1.4.0 ships sirilpy 1.0.8, which has no is_headless().
        siril = Mock(spec=["connect", "disconnect", "connected", "error_messagebox"])
        siril.connected = True
        siril.connect.side_effect = lambda: None
        fake = SimpleNamespace(check_module_version=lambda _: True,
                               SirilInterface=lambda: siril,
                               ensure_installed=Mock(side_effect=sky.SkySolverError("boom")))
        with patch.dict(sys.modules, {"sirilpy": fake}), \
                patch.object(sys, "argv", ["SkySolver.py"]), \
                patch.dict(os.environ, {}), \
                patch("sys.stderr", new_callable=io.StringIO) as err:
            os.environ.pop("SIRIL_HEADLESS", None)
            self.assertEqual(sky.main(), 1)
        siril.error_messagebox.assert_called_once_with("SkySolver: boom")
        siril.disconnect.assert_called_once()
        self.assertIn("boom", err.getvalue())

    def test_messagebox_failure_does_not_hide_original_error(self):
        siril = Mock()
        siril.connected = True
        siril.is_headless.return_value = False
        siril.error_messagebox.side_effect = RuntimeError("no GUI")
        fake = SimpleNamespace(check_module_version=lambda _: True,
                               SirilInterface=lambda: siril,
                               ensure_installed=Mock(side_effect=sky.SkySolverError("boom")))
        with patch.dict(sys.modules, {"sirilpy": fake}), \
                patch.object(sys, "argv", ["SkySolver.py"]), \
                patch("sys.stderr", new_callable=io.StringIO) as err:
            self.assertEqual(sky.main(), 1)
        self.assertIn("boom", err.getvalue())

    def test_too_few_stars_never_sends_a_request(self):
        with self.assertRaises(sky.SkySolverError):
            sky.make_star_payload([], 640, 480)

    def test_rate_limit_retry_and_payload_is_only_star_data(self):
        response = io.BytesIO(json.dumps({"solved": True}).encode())
        opener = Mock(side_effect=[HTTPError(sky.API_URL, 429, "busy",
                                             {"Retry-After": "2"}, io.BytesIO(b'{}')), response])
        sleep = Mock()
        result = sky.solve({"stars": [[1, 2, 3]]}, opener=opener, sleep=sleep, log=lambda _: None)
        self.assertTrue(result["solved"])
        self.assertEqual(opener.call_count, 2)
        self.assertGreaterEqual(sleep.call_args.args[0], 2)
        self.assertLess(sleep.call_args.args[0], 3)
        self.assertEqual(json.loads(opener.call_args.args[0].data), {"stars": [[1, 2, 3]]})

    def test_invalid_responses_and_long_rate_limit_are_not_applied(self):
        for data in (b'{"solved": false, "error": "no match"}', b'[]', b'not json'):
            with self.subTest(data=data), self.assertRaises(sky.SkySolverError):
                sky.solve({}, opener=lambda *a, **k: io.BytesIO(data))
        opener = Mock(side_effect=HTTPError(sky.API_URL, 429, "busy",
                                            {"Retry-After": "600"}, io.BytesIO(b'{}')))
        with self.assertRaises(sky.SkySolverError):
            sky.solve({}, opener=opener, sleep=lambda _: self.fail("must not wait"))


if __name__ == "__main__":
    unittest.main()
