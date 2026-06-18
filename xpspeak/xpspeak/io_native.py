"""Native save/load (JSON) and ASCII exports (.DAT spectrum, .PAR parameters)."""

from __future__ import annotations

import json

import numpy as np

from .model import Spectrum
from . import functions as fx


def save_spectrum(spec: Spectrum, path: str) -> None:
    with open(path, "w") as f:
        json.dump(spec.to_dict(), f, indent=2)


def load_spectrum(path: str) -> Spectrum:
    with open(path, "r") as f:
        d = json.load(f)
    spec = Spectrum.from_dict(d)
    spec.filename = path
    return spec


def export_dat(region, gl_mode: str, path: str) -> None:
    """Export columns: BE, raw, background, envelope, peak1, peak2, ... (*.DAT)."""
    ft = region.func_type(gl_mode)
    bg = region.background()
    cols = [region.be, region.intensity, bg, region.envelope(gl_mode)]
    headers = ["BE", "Raw", "Background", "Envelope"]
    for i, pk in enumerate(region.peaks):
        cols.append(bg + pk.curve(region.be, ft, region.region_shift))
        headers.append(f"Peak{i}")
    data = np.column_stack(cols)
    with open(path, "w") as f:
        f.write("\t".join(headers) + "\n")
        for row in data:
            f.write("\t".join(f"{v:.6g}" for v in row) + "\n")


def export_par(region, gl_mode: str, path: str) -> None:
    """Export the peak parameter table (*.PAR)."""
    ft = region.func_type(gl_mode)
    lines = [f"Region: {region.name}",
             f"Function: GL {gl_mode}",
             f"Region shift: {region.region_shift}",
             f"Background: {region.bg_type}",
             ""]
    hdr = ["#", "Type", "Position", "Area", "FWHM", "%GL", "TS", "TL", "s.o.s", "ActualFWHM"]
    lines.append("\t".join(hdr))
    for i, pk in enumerate(region.peaks):
        afwhm = pk.actual_fwhm(region.be, ft)
        lines.append("\t".join(str(v) for v in [
            i, pk.peak_type, f"{pk.position:.4f}", f"{pk.area:.2f}",
            f"{pk.fwhm:.4f}", f"{pk.gl:.1f}", f"{pk.ts:.3f}", f"{pk.tl:.3f}",
            f"{pk.sos:.3f}", f"{afwhm:.4f}",
        ]))
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
