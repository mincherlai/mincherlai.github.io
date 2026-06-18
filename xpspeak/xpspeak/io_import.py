"""Importers for the ASCII spectrum formats supported by XPSPeak.

Each importer returns a list of :class:`xpspeak.model.Region` (data only —
binding energy + intensity + name; peaks/background are added by the user).

Supported:
  * generic ASCII two-column  (.prn, .txt, .dat)   -> import_ascii
  * Phi Multiplex ASCII       (.asc)               -> import_phi
  * Leybold ASCII             (.dat)               -> import_leybold
  * VAMAS 1988                (.txt)  single+multi -> import_vamas   (best effort)
  * Kratos Vision DES         (.des)               -> import_kratos  (partial)

All formats use CRLF in the original samples; we read tolerantly.
"""

from __future__ import annotations

import re
from typing import List

import numpy as np

from .model import Region


def _floats(s: str):
    return re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", s)


def _is_number(line: str) -> bool:
    line = line.strip()
    if not line:
        return False
    try:
        float(line)
        return True
    except ValueError:
        return False


def _read_lines(path: str) -> List[str]:
    with open(path, "r", errors="replace") as f:
        return [ln.rstrip("\r\n") for ln in f]


# --------------------------------------------------------------------------
# Generic two-column ASCII
# --------------------------------------------------------------------------
def import_ascii(path: str, name: str | None = None) -> List[Region]:
    be, inten = [], []
    for ln in _read_lines(path):
        nums = ln.replace(",", " ").split()
        if len(nums) >= 2:
            try:
                x = float(nums[0]); y = float(nums[1])
            except ValueError:
                continue
            be.append(x); inten.append(y)
    if not be:
        raise ValueError("No two-column numeric data found.")
    reg = Region(name=name or _basename(path), be=np.array(be), intensity=np.array(inten))
    return [reg]


# --------------------------------------------------------------------------
# Phi Multiplex ASCII
#   marker line, group name, then per region:
#     region-name line(s), ncycle, start_BE, step, npts, npts*intensity
# --------------------------------------------------------------------------
def import_phi(path: str) -> List[Region]:
    lines = [ln for ln in _read_lines(path)]
    i = 0
    n = len(lines)
    # Skip the leading marker line (e.g. "Point1").
    if i < n and not _is_number(lines[i]):
        i += 1
    group = ""
    if i < n and not _is_number(lines[i]):
        group = lines[i].strip()
        i += 1
    regions: List[Region] = []
    while i < n:
        # Collect region-name lines (non-numeric).
        names = []
        while i < n and not _is_number(lines[i]):
            names.append(lines[i].strip())
            i += 1
        if i >= n:
            break
        # Control block: ncycle, start, step, npts.
        ctrl = []
        while i < n and _is_number(lines[i]) and len(ctrl) < 4:
            ctrl.append(float(lines[i])); i += 1
        if len(ctrl) < 4:
            break
        _ncycle, start, step, npts = ctrl
        npts = int(round(npts))
        vals = []
        while i < n and len(vals) < npts and _is_number(lines[i]):
            vals.append(float(lines[i])); i += 1
        if not vals:
            continue
        be = start + step * np.arange(len(vals))
        rname = " ".join([p for p in [group] + names if p]) or _basename(path)
        regions.append(Region(name=rname, be=be, intensity=np.array(vals)))
    if not regions:
        raise ValueError("Could not parse Phi format.")
    return regions


# --------------------------------------------------------------------------
# Leybold ASCII
#   "comment"
#   TotalNumOfRegions=N
#   Region=k / "name" / Npoints=M / M*(BE intensity)
# --------------------------------------------------------------------------
def import_leybold(path: str) -> List[Region]:
    lines = _read_lines(path)
    regions: List[Region] = []
    i = 0
    n = len(lines)
    while i < n:
        ln = lines[i].strip()
        if ln.lower().startswith("region="):
            i += 1
            name = ""
            if i < n and not lines[i].strip().lower().startswith("npoints"):
                name = lines[i].strip().strip('"').strip()
                i += 1
            npts = 0
            if i < n and lines[i].strip().lower().startswith("npoints"):
                npts = int(_floats(lines[i])[0])
                i += 1
            be, inten = [], []
            while i < n and len(be) < npts:
                nums = lines[i].split()
                if len(nums) >= 2 and _is_number(nums[0]):
                    be.append(float(nums[0])); inten.append(float(nums[1]))
                    i += 1
                else:
                    break
            if be:
                regions.append(Region(name=name or f"Region {len(regions)+1}",
                                      be=np.array(be), intensity=np.array(inten)))
        else:
            i += 1
    if not regions:
        raise ValueError("Could not parse Leybold format.")
    return regions


# --------------------------------------------------------------------------
# VAMAS 1988 (best effort: VG ESCALAB single & multi region)
# --------------------------------------------------------------------------
def import_vamas(path: str) -> List[Region]:
    raw = [ln.strip() for ln in _read_lines(path)]
    # Number of blocks is given a few lines into the experiment header. We scan
    # for blocks heuristically: a block contains an abscissa label line followed
    # by units, start, increment, then later a count and ordinate values.
    regions: List[Region] = []
    i = 0
    n = len(raw)
    while i < n:
        # Find an abscissa label marker: a line naming the energy axis whose
        # next line is a unit and the two after are floats (start, increment).
        low = raw[i].lower()
        is_label = ("kinetic" in low or "binding" in low) and "energ" not in low[:0]
        is_label = ("kinetic" in low or "binding" in low)
        if is_label and i + 4 < n and _is_number(raw[i + 2]) and _is_number(raw[i + 3]):
            is_kinetic = "kinetic" in low
            start = float(raw[i + 2])
            increment = float(raw[i + 3])
            name = _vamas_block_name(raw, i)
            npts, data_start = _vamas_find_ordinates(raw, i + 4)
            if npts and data_start:
                vals = [float(raw[k]) for k in range(data_start, data_start + npts)]
                axis = start + increment * np.arange(len(vals))
                if is_kinetic:
                    exc = _vamas_excitation(raw, i)
                    be = (exc - axis) if exc else axis
                else:
                    be = axis
                regions.append(Region(name=name, be=be, intensity=np.array(vals)))
                i = data_start + npts
                continue
        i += 1
    if not regions:
        raise ValueError("Could not parse VAMAS format (best-effort reader).")
    return regions


def _vamas_excitation(raw, idx) -> float | None:
    """Find the X-ray source excitation energy (eV) preceding the abscissa.

    Scans backward for a float in the plausible anode range (Mg Ka 1253.6,
    Al Ka 1486.6, etc.) used to convert kinetic energy to binding energy.
    """
    for k in range(idx, max(0, idx - 40), -1):
        if _is_number(raw[k]):
            v = float(raw[k])
            if 1000.0 <= v <= 1700.0:
                return v
    return None


def _vamas_block_name(raw, idx) -> str:
    for k in range(idx - 1, max(0, idx - 20), -1):
        s = raw[k]
        if s and not _is_number(s) and s not in ("eV", "REGULAR", "NORM"):
            return s
    return "VAMAS region"


def _vamas_find_ordinates(raw, j):
    """Return (npts, data_start_index) by finding the ordinate count line.

    The ordinate count is the integer whose following numeric run matches it
    *exactly* (the block boundary is a non-numeric line or EOF).  Two layouts
    are tried: data immediately after the count, or after a min/max pair.
    Larger counts are preferred so spurious small integers (flags, channel
    counts) are not mistaken for the data length.
    """
    n = len(raw)
    best = (None, None, -1)
    while j < n:
        if _is_number(raw[j]) and float(raw[j]).is_integer():
            cnt = int(float(raw[j]))
            if cnt >= 8:
                for skip in (1, 3):   # right after count, or after min/max pair
                    start = j + skip
                    end = start + cnt
                    if end > n:
                        continue
                    if all(_is_number(raw[k]) for k in range(start, end)):
                        # Exact boundary: next line non-numeric or EOF.
                        if end >= n or not _is_number(raw[end]):
                            if cnt > best[2]:
                                best = (cnt, start, cnt)
        j += 1
    return best[0], best[1]


# --------------------------------------------------------------------------
# Kratos Vision DES (partial: spectrum only, KE -> BE)
# --------------------------------------------------------------------------
def import_kratos(path: str) -> List[Region]:
    lines = _read_lines(path)
    meta = {}
    for ln in lines:
        if "=" in ln and "{" not in ln and "}" not in ln:
            key, _, val = ln.partition("=")
            meta.setdefault(key.strip(), val.strip())
    try:
        start = float(_floats(meta["Abscissa start"])[0])
        inc = float(_floats(meta["Abscissa increment"])[0])
        npts = int(_floats(meta["# ordinate values"])[0])
    except (KeyError, IndexError):
        raise ValueError("DES header missing abscissa/ordinate fields.")
    label = meta.get("Abscissa label", "Kinetic Energy")
    exc = None
    if "Excitation energy" in meta:
        f = _floats(meta["Excitation energy"])
        if f:
            exc = float(f[0])

    # Find the trailing contiguous numeric block of length npts.
    vals = _trailing_numeric_block(lines, npts)
    if vals is None:
        raise ValueError("Could not locate DES ordinate data block.")
    axis = start + inc * np.arange(len(vals))
    if "Kinetic" in label and exc:
        be = exc - axis
    else:
        be = axis
    name = meta.get("Object name", _basename(path))
    return [Region(name=name, be=be, intensity=np.array(vals))]


def _trailing_numeric_block(lines, npts):
    nums = []
    for ln in lines:
        toks = ln.replace(",", " ").split()
        line_nums = [float(t) for t in toks if _is_number(t)]
        if len(toks) == len(line_nums) and line_nums:
            nums.extend(line_nums)
        else:
            # Reset on any non-pure-numeric line so we keep only a clean block.
            if len(nums) >= npts:
                break
            nums = []
    if len(nums) >= npts:
        return np.array(nums[:npts])
    return None


def _basename(path):
    import os
    return os.path.splitext(os.path.basename(path))[0]


# Registry used by the GUI's Import menu.
IMPORTERS = {
    "ASCII (.prn/.txt)": import_ascii,
    "Phi (.asc)": import_phi,
    "Leybold (.dat)": import_leybold,
    "VAMAS (.txt)": import_vamas,
    "Kratos DES (.des)": import_kratos,
}
