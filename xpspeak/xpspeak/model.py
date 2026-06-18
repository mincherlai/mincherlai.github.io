"""Data model: Peak, Region, Spectrum and parameter constraints."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional

import numpy as np

from . import functions as fx

# The six fittable parameters of a peak (GL-sum). GL-product ignores ts/tl.
PEAK_PARAMS = ("position", "area", "fwhm", "gl", "ts", "tl")


@dataclass
class Constraint:
    """A reference of one parameter to the same parameter of another peak.

    value semantics:
      mode == "add"  ->  this = peaks[ref].param + value
      mode == "mult" ->  this = peaks[ref].param * value
    When ref is None the parameter is free (subject only to bounds).
    """
    ref: Optional[int] = None      # index of referenced peak within the region
    mode: str = "add"              # "add" or "mult"
    value: float = 0.0
    lower: float = -np.inf         # bound applied when free
    upper: float = np.inf
    fixed: bool = False            # this single parameter is held fixed

    def to_dict(self):
        d = asdict(self)
        # JSON cannot encode infinities portably; use null.
        d["lower"] = None if not np.isfinite(self.lower) else self.lower
        d["upper"] = None if not np.isfinite(self.upper) else self.upper
        return d

    @classmethod
    def from_dict(cls, d):
        d = dict(d)
        d["lower"] = -np.inf if d.get("lower") is None else d["lower"]
        d["upper"] = np.inf if d.get("upper") is None else d["upper"]
        return cls(**d)


@dataclass
class Peak:
    name: str = ""
    peak_type: str = "s"           # s / p / d / f
    position: float = 0.0
    area: float = 1000.0
    fwhm: float = 1.0
    gl: float = 30.0               # %Gaussian-Lorentzian
    ts: float = 0.0                # asymmetry tail strength (GL-sum only)
    tl: float = 1.0                # asymmetry tail length (GL-sum only)
    sos: float = 0.0               # spin-orbit splitting (eV), doublets
    fix: bool = False              # exclude whole peak from region/all optimise
    constraints: dict = field(default_factory=lambda: {p: Constraint() for p in PEAK_PARAMS})

    def curve(self, x: np.ndarray, func_type: str, region_shift: float = 0.0) -> np.ndarray:
        return fx.peak_curve(
            x,
            func_type=func_type,
            peak_type=self.peak_type,
            position=self.position + region_shift,
            area=self.area,
            fwhm=self.fwhm,
            gl=self.gl,
            ts=self.ts,
            tl=self.tl,
            sos=self.sos,
        )

    def actual_fwhm(self, x: np.ndarray, func_type: str) -> float:
        return fx.actual_fwhm(x, self.curve(x, func_type))

    def to_dict(self):
        d = asdict(self)
        d["constraints"] = {k: c.to_dict() for k, c in self.constraints.items()}
        return d

    @classmethod
    def from_dict(cls, d):
        d = dict(d)
        cons = d.pop("constraints", {})
        peak = cls(**d)
        peak.constraints = {p: Constraint.from_dict(cons[p]) if p in cons else Constraint()
                            for p in PEAK_PARAMS}
        return peak


@dataclass
class Region:
    name: str = "Region"
    be: np.ndarray = field(default_factory=lambda: np.array([]))     # binding energy
    intensity: np.ndarray = field(default_factory=lambda: np.array([]))  # raw counts
    # Background
    bg_type: str = "Shirley"       # None / Linear / Shirley / Shirley+Linear / Tougaard
    bg_navg: int = 1
    bg_slope: float = 0.0          # Shirley+Linear
    bg_b1: float = 100.0           # Tougaard
    bg_c: float = 1643.0           # Tougaard
    bg_range: Optional[tuple] = None   # (be_lo, be_hi); None = whole region
    region_shift: float = 0.0
    peaks: list = field(default_factory=list)

    # ---- background ---------------------------------------------------
    def _range_mask(self):
        if self.bg_range is None:
            return np.ones(self.be.shape, dtype=bool)
        lo, hi = sorted(self.bg_range)
        return (self.be >= lo) & (self.be <= hi)

    def background(self) -> np.ndarray:
        from . import background as bg
        out = np.zeros_like(self.intensity)
        mask = self._range_mask()
        if not np.any(mask):
            return out
        x, y = self.be[mask], self.intensity[mask]
        t = self.bg_type
        if t in (None, "None"):
            b = np.zeros_like(y)
        elif t == "Linear":
            b = bg.linear_background(x, y, self.bg_navg)
        elif t == "Shirley":
            b = bg.shirley_background(x, y, self.bg_navg)
        elif t == "Shirley+Linear":
            b = bg.shirley_linear_background(x, y, self.bg_slope, self.bg_navg)
        elif t == "Tougaard":
            b = bg.tougaard_background(x, y, self.bg_b1, self.bg_c, self.bg_navg)
        else:
            b = np.zeros_like(y)
        out[mask] = b
        return out

    # ---- peaks --------------------------------------------------------
    def func_type(self, gl_mode: str) -> str:
        return "product" if gl_mode == "product" else "sum"

    def sum_curve(self, gl_mode: str) -> np.ndarray:
        """Sum of all peak curves (without background) on the region grid."""
        ft = self.func_type(gl_mode)
        total = np.zeros_like(self.intensity, dtype=float)
        for pk in self.peaks:
            total += pk.curve(self.be, ft, self.region_shift)
        return total

    def envelope(self, gl_mode: str) -> np.ndarray:
        """Background + sum of peaks — the full model overlaid on the data."""
        return self.background() + self.sum_curve(gl_mode)

    def residual(self, gl_mode: str) -> np.ndarray:
        return self.intensity - self.envelope(gl_mode)

    def to_dict(self):
        return {
            "name": self.name,
            "be": self.be.tolist(),
            "intensity": self.intensity.tolist(),
            "bg_type": self.bg_type,
            "bg_navg": self.bg_navg,
            "bg_slope": self.bg_slope,
            "bg_b1": self.bg_b1,
            "bg_c": self.bg_c,
            "bg_range": list(self.bg_range) if self.bg_range else None,
            "region_shift": self.region_shift,
            "peaks": [p.to_dict() for p in self.peaks],
        }

    @classmethod
    def from_dict(cls, d):
        r = cls(
            name=d.get("name", "Region"),
            be=np.array(d.get("be", [])),
            intensity=np.array(d.get("intensity", [])),
            bg_type=d.get("bg_type", "Shirley"),
            bg_navg=d.get("bg_navg", 1),
            bg_slope=d.get("bg_slope", 0.0),
            bg_b1=d.get("bg_b1", 100.0),
            bg_c=d.get("bg_c", 1643.0),
            bg_range=tuple(d["bg_range"]) if d.get("bg_range") else None,
            region_shift=d.get("region_shift", 0.0),
        )
        r.peaks = [Peak.from_dict(p) for p in d.get("peaks", [])]
        return r


@dataclass
class Spectrum:
    """Top-level document: an ordered set of regions plus global options."""
    regions: list = field(default_factory=list)
    gl_mode: str = "sum"           # "sum" or "product"
    filename: Optional[str] = None

    def to_dict(self):
        return {
            "format": "xpspeak-mac",
            "version": 1,
            "gl_mode": self.gl_mode,
            "regions": [r.to_dict() for r in self.regions],
        }

    @classmethod
    def from_dict(cls, d):
        s = cls(gl_mode=d.get("gl_mode", "sum"))
        s.regions = [Region.from_dict(r) for r in d.get("regions", [])]
        return s
