"""Background subtraction routines: Shirley, Linear, Shirley+Linear, Tougaard.

Conventions
-----------
* Arrays are stored in the program's working order, but background maths is
  done on intensity vs. an index running from the low-BE endpoint to the
  high-BE endpoint.  Helpers below take (x, y) already restricted to the
  region's background range, with x = binding energy.
* Endpoint intensities can be averaged over n points (1/3/5/7/9) to stabilise
  the endpoints on a noisy baseline.
"""

from __future__ import annotations

import numpy as np

AVERAGE_CHOICES = (1, 3, 5, 7, 9)


def _endpoint_value(y: np.ndarray, idx: int, navg: int) -> float:
    """Average ``navg`` points of y centred on idx (clamped to bounds)."""
    if navg <= 1:
        return float(y[idx])
    half = navg // 2
    lo = max(0, idx - half)
    hi = min(len(y), idx + half + 1)
    return float(np.mean(y[lo:hi]))


def linear_background(x: np.ndarray, y: np.ndarray, navg: int = 1) -> np.ndarray:
    """Straight line connecting the two endpoints."""
    y0 = _endpoint_value(y, 0, navg)
    y1 = _endpoint_value(y, -1, navg)
    if len(x) < 2:
        return np.full_like(y, y0)
    t = (x - x[0]) / (x[-1] - x[0])
    return y0 + (y1 - y0) * t


def shirley_background(
    x: np.ndarray,
    y: np.ndarray,
    navg: int = 1,
    max_iter: int = 100,
    tol: float = 1e-6,
) -> np.ndarray:
    """Iterative Shirley background.

    The Shirley background at each point is proportional to the integrated
    signal (above background) on the high-kinetic-energy side.  We iterate
    until convergence.  Endpoints are pinned to (optionally averaged) data.
    """
    y0 = _endpoint_value(y, 0, navg)
    y1 = _endpoint_value(y, -1, navg)
    n = len(y)
    if n < 2:
        return np.full_like(y, y0)

    # Work on a monotonically increasing energy axis so the cumulative
    # integral direction is well defined; restore order at the end.
    order = np.argsort(x)
    xs = x[order]
    ys = y[order]
    # Background endpoints follow the sorted order.
    lo, hi = ys[0], ys[-1]

    bg = np.linspace(lo, hi, n)
    for _ in range(max_iter):
        # Signal above current background.
        s = np.clip(ys - bg, 0.0, None)
        # Cumulative area from high-energy end.
        area_total = np.trapezoid(s, xs)
        if area_total <= 0:
            break
        new_bg = np.empty(n)
        for i in range(n):
            area_i = np.trapezoid(s[i:], xs[i:])
            new_bg[i] = lo + (hi - lo) * area_i / area_total
        if np.max(np.abs(new_bg - bg)) < tol * max(abs(hi - lo), 1.0):
            bg = new_bg
            break
        bg = new_bg

    # Undo the sort.
    out = np.empty(n)
    out[order] = bg
    return out


def shirley_linear_background(
    x: np.ndarray, y: np.ndarray, slope: float = 0.0, navg: int = 1
) -> np.ndarray:
    """Shirley background plus a straight line of the given slope.

    The line starts at zero at the low-BE endpoint and adds ``slope`` * (BE -
    BE_lowend).  A positive slope raises the high-BE side.  slope = 0 reduces to
    the plain Shirley background.  Used when the Shirley background would
    otherwise exceed the signal (see Cu2p_bg sample).
    """
    base = shirley_background(x, y, navg=navg)
    if slope == 0.0:
        return base
    be_low = x[np.argmax(x)] if x[0] < x[-1] else x[0]
    # Low-BE endpoint is the smaller binding energy.
    be_low = np.min(x)
    return base + slope * (x - be_low)


def tougaard_background(
    x: np.ndarray,
    y: np.ndarray,
    b1: float,
    c: float = 1643.0,
    navg: int = 1,
) -> np.ndarray:
    """Two-parameter universal Tougaard background.

    K(E) = B1 * T / (C + T**2)**2 ,  T = E_loss.
    The background at kinetic energy E is B1 * integral over E' > E of
    K(E'-E) * (y(E') - bg(E')).  We approximate with the measured signal
    (single pass), which matches the original program's practical behaviour.
    ``b1`` can be optimised separately (see fitting.optimize_tougaard_b1).
    """
    n = len(y)
    if n < 2:
        return np.zeros_like(y)
    order = np.argsort(x)          # increasing BE
    xs = x[order]
    ys = y[order]
    y0 = _endpoint_value(ys, 0, navg)

    # Kinetic energy increases as binding energy decreases.
    ke = -xs
    bg = np.empty(n)
    s = ys - y0
    for i in range(n):
        loss = ke - ke[i]
        mask = loss > 0
        if not np.any(mask):
            bg[i] = y0
            continue
        kernel = b1 * loss[mask] / (c + loss[mask] ** 2) ** 2
        bg[i] = y0 + np.trapezoid(kernel * s[mask], xs[mask])
    out = np.empty(n)
    out[order] = bg
    return out
