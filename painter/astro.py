"""Compact sun and moon positions (low-precision almanac formulas).

Accurate to a few tenths of a degree, which is plenty for "is the moon up?"
and "is it dusk?". Kept deliberately simple so firmware/painting_frame/astro.cpp
can mirror it line for line.
"""

from __future__ import annotations

import math

D2R = math.pi / 180.0


def _norm(deg: float) -> float:
    return deg % 360.0


def julian_day(unix_seconds: float) -> float:
    return unix_seconds / 86400.0 + 2440587.5


def sun_ecliptic(jd: float) -> tuple[float, float]:
    """(ecliptic longitude, obliquity) in degrees."""
    n = jd - 2451545.0
    L = _norm(280.460 + 0.9856474 * n)
    g = _norm(357.528 + 0.9856003 * n) * D2R
    lam = L + 1.915 * math.sin(g) + 0.020 * math.sin(2 * g)
    eps = 23.439 - 0.0000004 * n
    return _norm(lam), eps


def moon_ecliptic(jd: float) -> tuple[float, float, float]:
    """(ecliptic longitude, latitude, horizontal parallax) in degrees."""
    T = (jd - 2451545.0) / 36525.0

    def s(a, b):
        return math.sin(_norm(a + b * T) * D2R)

    def c(a, b):
        return math.cos(_norm(a + b * T) * D2R)

    lam = (218.32 + 481267.881 * T
           + 6.29 * s(135.0, 477198.87) - 1.27 * s(259.3, -413335.36)
           + 0.66 * s(235.7, 890534.22) + 0.21 * s(269.9, 954397.74)
           - 0.19 * s(357.5, 35999.05) - 0.11 * s(186.5, 966404.03))
    beta = (5.13 * s(93.3, 483202.02) + 0.28 * s(228.2, 960400.89)
            - 0.28 * s(318.3, 6003.15) - 0.17 * s(217.6, -407332.21))
    par = (0.9508 + 0.0518 * c(135.0, 477198.87) + 0.0095 * c(259.3, -413335.38)
           + 0.0078 * c(235.7, 890534.22) + 0.0028 * c(269.9, 954397.70))
    return _norm(lam), beta, par


def _altitude(lam: float, beta: float, eps: float, jd: float, lat: float, lon: float) -> float:
    l, b, e = lam * D2R, beta * D2R, eps * D2R
    ra = math.atan2(math.sin(l) * math.cos(e) - math.tan(b) * math.sin(e), math.cos(l))
    dec = math.asin(math.sin(b) * math.cos(e) + math.cos(b) * math.sin(e) * math.sin(l))
    gmst = _norm(280.46061837 + 360.98564736629 * (jd - 2451545.0))
    ha = (gmst + lon) * D2R - ra
    phi = lat * D2R
    return math.asin(math.sin(phi) * math.sin(dec) + math.cos(phi) * math.cos(dec) * math.cos(ha)) / D2R


def sky(unix_seconds: float, lat: float, lon: float) -> dict:
    jd = julian_day(unix_seconds)
    sun_lam, eps = sun_ecliptic(jd)
    moon_lam, moon_beta, par = moon_ecliptic(jd)
    sun_alt = _altitude(sun_lam, 0.0, eps, jd, lat, lon)
    geo = _altitude(moon_lam, moon_beta, eps, jd, lat, lon)
    moon_alt = geo - par * math.cos(geo * D2R)          # seen from the surface, not Earth's center

    elong = math.acos(math.cos(moon_beta * D2R) * math.cos((moon_lam - sun_lam) * D2R))
    illum = (1 - math.cos(elong)) / 2
    waxing = _norm(moon_lam - sun_lam) < 180.0
    if illum < 0.03:
        phase = "new"
    elif illum > 0.97:
        phase = "full"
    elif 0.40 <= illum <= 0.60:
        phase = "first_quarter" if waxing else "last_quarter"
    elif illum < 0.40:
        phase = "waxing_crescent" if waxing else "waning_crescent"
    else:
        phase = "waxing_gibbous" if waxing else "waning_gibbous"
    return {"sun_alt": round(sun_alt, 1), "moon_alt": round(moon_alt, 1), "moon_up": moon_alt > 0,
            "moon_illum": round(illum, 3), "moon_waxing": waxing, "moon_phase": phase}
