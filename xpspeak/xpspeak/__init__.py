"""XPSPeak for Mac — a faithful re-implementation of XPSPeak 4.1.

Original XPSPeak 4.1 written by Raymund W.M. Kwok (CUHK), Visual Basic 6, 1999.
This is an independent native re-implementation in Python/PyQt, replicating the
peak functions, background routines, constraints and workflow of the original.
"""

__version__ = "0.1.0"

# Hard limits inherited from the original program.
MAX_POINTS = 5000
MAX_PEAKS_TOTAL = 51
MAX_PEAKS_PER_REGION = 10
