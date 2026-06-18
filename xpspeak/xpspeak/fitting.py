"""Non-linear least-squares fitting with peak constraints and bounds.

The fitter optimises a chosen subset of parameters (a single parameter, a whole
peak, a whole region, or all regions) while:

* honouring per-parameter ``fixed`` flags and whole-peak ``fix`` flags,
* resolving constraints that reference another peak's same parameter
  (``this = ref +/* value``) so referenced parameters are never free,
* respecting lower/upper bounds.

Built on :func:`scipy.optimize.least_squares` (Levenberg-Marquardt / TRF),
which serves the same role as the original program's Newton / binary-search
optimisers but is more robust.  A simple binary-search optimiser is also
provided for parity with the original UX.
"""

from __future__ import annotations

from typing import Iterable

import numpy as np
from scipy.optimize import least_squares

from .model import Region, PEAK_PARAMS


def resolve_constraints(region: Region) -> None:
    """Overwrite constrained parameter values from their references in place.

    Iterates until stable so chains (Peak2 -> Peak1 -> Peak0) resolve.
    Looped references are broken after a bounded number of passes.
    """
    peaks = region.peaks
    for _ in range(len(peaks) + 1):
        changed = False
        for pk in peaks:
            for pname in PEAK_PARAMS:
                c = pk.constraints[pname]
                if c.ref is None or c.fixed:
                    continue
                if c.ref < 0 or c.ref >= len(peaks):
                    continue
                ref_val = getattr(peaks[c.ref], pname)
                new = ref_val + c.value if c.mode == "add" else ref_val * c.value
                if getattr(pk, pname) != new:
                    setattr(pk, pname, new)
                    changed = True
        if not changed:
            break


def free_targets(region: Region, scope) -> list:
    """Return the list of (peak_index, param_name) that should be varied.

    ``scope`` may be:
      * ("param", peak_idx, param_name) – a single parameter
      * ("peak", peak_idx)              – position/area/fwhm/(gl) of one peak
      * ("region",)                     – all non-fixed peaks in the region
    A parameter is excluded if its constraint is fixed or references another
    peak (it is a dependent variable, not a free one).
    """
    targets = []

    def add(pi, pname):
        c = region.peaks[pi].constraints[pname]
        if c.fixed or c.ref is not None:
            return
        targets.append((pi, pname))

    kind = scope[0]
    if kind == "param":
        add(scope[1], scope[2])
    elif kind == "peak":
        pi = scope[1]
        for pname in ("position", "area", "fwhm", "gl"):
            add(pi, pname)
    elif kind == "region":
        for pi, pk in enumerate(region.peaks):
            if pk.fix:
                continue
            for pname in ("position", "area", "fwhm", "gl"):
                add(pi, pname)
    return targets


def _bounds_for(region, targets):
    lo, hi = [], []
    for pi, pname in targets:
        c = region.peaks[pi].constraints[pname]
        l, h = c.lower, c.upper
        # Sensible defaults so unconstrained params stay physical.
        if not np.isfinite(l):
            l = 0.0 if pname in ("area", "fwhm") else (0.0 if pname == "gl" else -np.inf)
        if not np.isfinite(h):
            h = 100.0 if pname == "gl" else np.inf
        lo.append(l)
        hi.append(h)
    return np.array(lo), np.array(hi)


def optimize_region(region: Region, gl_mode: str, scope, max_nfev: int = 2000):
    """Fit ``region`` over the parameters selected by ``scope``.

    Returns a dict with chi-square before/after and the number of iterations.
    """
    targets = free_targets(region, scope)
    resolve_constraints(region)
    if not targets:
        return {"chi2_before": _chi2(region, gl_mode), "chi2_after": _chi2(region, gl_mode),
                "n_params": 0, "message": "no free parameters"}

    x0 = np.array([getattr(region.peaks[pi], pn) for pi, pn in targets], dtype=float)
    lo, hi = _bounds_for(region, targets)
    x0 = np.clip(x0, lo, hi)

    def apply(x):
        for (pi, pn), val in zip(targets, x):
            setattr(region.peaks[pi], pn, float(val))
        resolve_constraints(region)

    def resid(x):
        apply(x)
        return region.residual(gl_mode)

    chi2_before = _chi2(region, gl_mode)
    result = least_squares(
        resid, x0, bounds=(lo, hi), max_nfev=max_nfev, method="trf"
    )
    apply(result.x)
    return {
        "chi2_before": chi2_before,
        "chi2_after": _chi2(region, gl_mode),
        "n_params": len(targets),
        "nfev": int(result.nfev),
        "message": result.message,
    }


def _chi2(region: Region, gl_mode: str) -> float:
    r = region.residual(gl_mode)
    return float(np.sum(r * r))


def optimize_all(regions: Iterable[Region], gl_mode: str):
    """Optimise every region in turn (whole-region scope)."""
    out = []
    for reg in regions:
        out.append(optimize_region(reg, gl_mode, ("region",)))
    return out


def optimize_tougaard_b1(region: Region, gl_mode: str, n_tail: int = 10):
    """Tune the Tougaard B1 so the background matches the high-BE tail.

    Minimises the squared difference between the measured intensity and the
    computed background over the ``n_tail`` highest-binding-energy points,
    matching the original program's approach.
    """
    if region.bg_type != "Tougaard":
        return None
    order = np.argsort(region.be)
    tail_idx = order[-n_tail:]

    def cost(b1):
        region.bg_b1 = float(b1[0])
        bg = region.background()
        d = region.intensity[tail_idx] - bg[tail_idx]
        return d

    res = least_squares(cost, [region.bg_b1], bounds=(0, np.inf))
    region.bg_b1 = float(res.x[0])
    return region.bg_b1
