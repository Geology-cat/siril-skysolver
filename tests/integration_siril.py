"""Run using Siril's pyscript command after loading a disposable test image."""
import json
from pathlib import Path
import sys

import numpy as np
import sirilpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import SkySolver

siril = sirilpy.SirilInterface()
siril.connect()
try:
    output = ROOT / "tests" / "output"
    output.mkdir(exist_ok=True)
    before = siril.get_image_pixeldata().copy()
    header_before = siril.get_image_fits_header(return_as="dict")
    (output / "original_header.txt").write_text(siril.get_image_fits_header())
    real_solve = SkySolver.solve
    def record_solve(*args, **kwargs):
        cache = output / "live_solution.json"
        if "--cached" in sys.argv and cache.exists():
            return json.loads(cache.read_text())
        result = real_solve(*args, **kwargs)
        cache.write_text(json.dumps(result, indent=2))
        return result
    SkySolver.solve = record_solve
    real_set = siril.set_image_metadata_from_header_string
    def record_set(header):
        (output / "sent_header.txt").write_text(header)
        result = real_set(header)
        (output / "received_header.txt").write_text(siril.get_image_fits_header())
        return result
    siril.set_image_metadata_from_header_string = record_set
    solution = SkySolver.run(siril)
    after = siril.get_image_pixeldata()
    np.testing.assert_array_equal(before, after)
    header_after = siril.get_image_fits_header(return_as="dict")
    assert header_after["PLTSOLVD"] is True
    for key in ("NAXIS1", "NAXIS2", "BITPIX", "EXPTIME", "ROWORDER"):
        if key in header_before:
            assert header_before[key] == header_after[key], key
    (output / "live_solution.json").write_text(json.dumps(solution, indent=2))
    (output / "applied_header.txt").write_text(siril.get_image_fits_header())
    siril.cmd("save", f'"{output / "solved.fit"}"')
    siril.log("INTEGRATION_OK: API solution recognised by Siril, pixel values unchanged")
finally:
    siril.disconnect()
