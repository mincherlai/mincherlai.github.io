"""Bridge between the JavaScript UI and the numpy/scipy engine, run in Pyodide.

All data crosses the JS<->Python boundary as JSON strings so we never deal with
proxy objects.  The browser holds region state as plain objects (the same shape
as Region.to_dict); this module turns them into Region instances, runs the
engine, and returns JSON the UI can plot.
"""

import json
import numpy as np

from xpspeak.model import Region
from xpspeak import io_import as imp
from xpspeak import fitting

_IMPORTERS = {
    "ascii": imp.import_ascii,
    "phi": imp.import_phi,
    "leybold": imp.import_leybold,
    "vamas": imp.import_vamas,
    "kratos": imp.import_kratos,
}


def import_text(fmt, text, filename="upload.dat"):
    """Parse uploaded file text in the given format; return JSON list of regions."""
    path = "/tmp/" + filename
    with open(path, "w") as f:
        f.write(text)
    regions = _IMPORTERS[fmt](path)
    return json.dumps([r.to_dict() for r in regions])


def compute(region_json, gl_mode):
    """Return everything the UI needs to draw the region (data, bg, peaks, fit)."""
    r = Region.from_dict(json.loads(region_json))
    order = np.argsort(r.be)
    be = r.be[order]
    raw = r.intensity[order]
    bg = r.background()[order]
    ft = r.func_type(gl_mode)

    peaks = []
    for pk in r.peaks:
        peaks.append((bg + pk.curve(r.be, ft, r.region_shift))[order].tolist())
    env = r.envelope(gl_mode)[order].tolist() if r.peaks else None
    resid = r.residual(gl_mode)
    chi2 = float(np.sum(resid * resid))
    actual = [float(pk.actual_fwhm(r.be, ft)) for pk in r.peaks]

    return json.dumps({
        "be": be.tolist(),
        "raw": raw.tolist(),
        "bg": bg.tolist(),
        "peaks": peaks,
        "envelope": env,
        "residual": resid[order].tolist(),
        "chi2": chi2,
        "actual_fwhm": actual,
        "has_bg": r.bg_type not in (None, "None"),
    })


def fit(region_json, gl_mode, scope_json):
    """Run the optimizer for the given scope; return the updated region + result."""
    r = Region.from_dict(json.loads(region_json))
    scope = json.loads(scope_json)
    # Coerce the peak index (JS numbers arrive as floats).
    if len(scope) > 1:
        scope = [scope[0], int(scope[1])] + [str(s) for s in scope[2:]]
    res = fitting.optimize_region(r, gl_mode, tuple(scope))
    return json.dumps({"region": r.to_dict(),
                       "result": {k: (v if isinstance(v, (int, float, str)) else str(v))
                                  for k, v in res.items()}})


def optimize_b1(region_json, gl_mode):
    r = Region.from_dict(json.loads(region_json))
    fitting.optimize_tougaard_b1(r, gl_mode)
    return json.dumps(r.to_dict())


def export_dat(region_json, gl_mode):
    """Return tab-separated .DAT text (BE, raw, bg, envelope, peaks)."""
    from xpspeak import io_native as io
    r = Region.from_dict(json.loads(region_json))
    io.export_dat(r, gl_mode, "/tmp/out.DAT")
    return open("/tmp/out.DAT").read()


def export_par(region_json, gl_mode):
    from xpspeak import io_native as io
    r = Region.from_dict(json.loads(region_json))
    io.export_par(r, gl_mode, "/tmp/out.PAR")
    return open("/tmp/out.PAR").read()
