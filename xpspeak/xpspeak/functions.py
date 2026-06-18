"""Peak shape functions used by XPSPeak.

Two peak functions are supported, matching the original program:

* "GL sum"     – Gaussian-Lorentzian *sum* form, supports an asymmetric tail
                 (parameters TS, TL). Used by Phi Quantum 2000 software.
* "GL product" – Gaussian-Lorentzian *product* form, symmetric only.
                 Used by Kratos software (and XPSPeak <= 3.1).

All shapes are returned with unit height at the peak centre; the caller scales
by (area / numerical_area) so that the user-facing parameter is peak *area*,
exactly like the original (peak height is never exposed to the user).
"""

from __future__ import annotations

import numpy as np

# 4*ln(2) appears in the Gaussian half-width definition.
_FOUR_LN2 = 4.0 * np.log(2.0)


def gaussian(x: np.ndarray, e0: float, fwhm: float) -> np.ndarray:
    """Unit-height Gaussian with the given FWHM."""
    return np.exp(-_FOUR_LN2 * ((x - e0) / fwhm) ** 2)


def lorentzian(x: np.ndarray, e0: float, fwhm: float) -> np.ndarray:
    """Unit-height Lorentzian with the given FWHM."""
    return 1.0 / (1.0 + 4.0 * ((x - e0) / fwhm) ** 2)


def gl_product(x: np.ndarray, e0: float, fwhm: float, m: float) -> np.ndarray:
    """Gaussian-Lorentzian product, unit height.

    m is the Lorentzian fraction in [0, 1]: m=0 -> pure Gaussian,
    m=1 -> pure Lorentzian.  This is the symmetric function used by XPSPeak
    for the "GL product" option.
    """
    d2 = ((x - e0) / fwhm) ** 2
    gauss = np.exp(-_FOUR_LN2 * (1.0 - m) * d2)
    lorentz = 1.0 / (1.0 + 4.0 * m * d2)
    return gauss * lorentz


def gl_sum(x: np.ndarray, e0: float, fwhm: float, m: float) -> np.ndarray:
    """Gaussian-Lorentzian sum (symmetric core), unit height.

    GL(x) = (1-m) * Gaussian + m * Lorentzian
    """
    return (1.0 - m) * gaussian(x, e0, fwhm) + m * lorentzian(x, e0, fwhm)


def gl_sum_asymmetric(
    x: np.ndarray, e0: float, fwhm: float, m: float, ts: float, tl: float
) -> np.ndarray:
    """Asymmetric Gaussian-Lorentzian *sum* function.

    The symmetric GL-sum core is used for the high-binding-energy half of the
    peak.  On the low-binding-energy side an exponential tail is blended in,
    controlled by TS (tail strength / onset) and TL (tail length).  TS = 0
    reproduces the symmetric GL-sum function exactly.

    NOTE: the original XPSPeak 4.1 stores the exact tail expression as an OLE
    equation image in its manual (not machine-readable).  This implementation
    follows the documented behaviour (FWHM refers to the symmetric half; the
    asymmetric tail extends one side) and is parameterised so TS/TL behave the
    same way as in the original.  The exact constants will be cross-checked
    against the binary .xps sample files when the binary reader is added.
    """
    core = gl_sum(x, e0, fwhm, m)
    if ts <= 0.0:
        return core

    # Tail applies to the low-BE side (x < e0). Blend factor grows away from
    # the centre and saturates; TL sets the decay length in eV.
    d = x - e0
    tail_side = d < 0.0
    out = core.copy()
    if tl <= 0.0:
        return out
    # Exponential tail anchored at the symmetric value, strength TS.
    tail = ts * np.exp(d[tail_side] / max(tl, 1e-6))
    out[tail_side] = core[tail_side] * (1.0 - ts) + tail
    return np.clip(out, 0.0, None)


# Area ratios and naming for doublet (p/d/f) peaks.
# ratio = area(main) : area(secondary) following (2j+1) multiplicities.
DOUBLET = {
    "s": None,
    "p": (2.0, 1.0, "3/2", "1/2"),   # p3/2 : p1/2 = 2:1
    "d": (3.0, 2.0, "5/2", "3/2"),   # d5/2 : d3/2 = 3:2
    "f": (4.0, 3.0, "7/2", "5/2"),   # f7/2 : f5/2 = 4:3
}


def _shape(func_type, x, e0, fwhm, m, ts, tl):
    if func_type == "product":
        return gl_product(x, e0, fwhm, m)
    return gl_sum_asymmetric(x, e0, fwhm, m, ts, tl)


def peak_curve(
    x: np.ndarray,
    *,
    func_type: str,      # "sum" or "product"
    peak_type: str,      # "s", "p", "d", "f"
    position: float,
    area: float,
    fwhm: float,
    gl: float,           # %Gaussian-Lorentzian (0-100)
    ts: float = 0.0,
    tl: float = 0.0,
    sos: float = 0.0,    # spin-orbit splitting (eV), doublets only
) -> np.ndarray:
    """Return the full peak curve evaluated on x (already area-normalised).

    For doublets the two spin-orbit components are summed: the main component
    sits at ``position`` and the secondary at ``position + sos`` (higher BE),
    with the area split following the (2j+1) ratio.  FWHM is shared.
    """
    m = float(gl) / 100.0

    def _component(e0, frac):
        shp = _shape(func_type, x, e0, fwhm, m, ts, tl)
        norm = np.trapezoid(shp, x)
        if norm == 0:
            return np.zeros_like(x)
        # Height so that the integral of this component equals frac*area.
        return shp * (frac * area) / abs(norm)

    if peak_type == "s" or DOUBLET.get(peak_type) is None:
        return _component(position, 1.0)

    r_main, r_sec, _, _ = DOUBLET[peak_type]
    total = r_main + r_sec
    main = _component(position, r_main / total)
    sec = _component(position + sos, r_sec / total)
    return main + sec


def actual_fwhm(x: np.ndarray, curve: np.ndarray) -> float:
    """Numerically estimate the FWHM of a (possibly asymmetric/doublet) curve."""
    if curve.size == 0:
        return 0.0
    peak = curve.max()
    if peak <= 0:
        return 0.0
    half = peak / 2.0
    above = np.where(curve >= half)[0]
    if above.size < 2:
        return 0.0
    return abs(float(x[above[-1]] - x[above[0]]))
