"""Every season x weather combination, for testing a scene.

Used by the Studio page's contact sheet, `gallery --combos`, the publish
check, and the frame's demo mode (publish writes them to demo.txt).
"""

from __future__ import annotations

from .weather import DEFAULT_STATE, derive

SEASONS = {  # season -> (month, a typical temperature)
    "spring": (4, 14), "summer": (7, 27), "autumn": (10, 12), "winter": (1, -3),
}

COLD = ("winter", "autumn", "spring")   # seasons where snow is plausible

# name, title, seasons it's plausible in (None = all), state changes
CONDITIONS = [
    ("clear", "Clear day", None, {"cloud_cover": 5}),
    ("partly_cloudy", "Partly cloudy", None, {"cloud_cover": 60}),
    ("overcast", "Overcast", None, {"cloud_cover": 95}),
    ("light_rain", "Light rain", None,
     {"cloud_cover": 90, "rain_mm_h": 1.0, "puddle_mm": 2, "ground_wet": True, "rain_last_24h_mm": 3}),
    ("downpour", "Downpour, puddles", None,
     {"cloud_cover": 100, "rain_mm_h": 6.0, "puddle_mm": 12, "ground_wet": True, "rain_last_24h_mm": 25}),
    ("thunderstorm", "Thunderstorm", None,
     {"cloud_cover": 100, "rain_mm_h": 8.0, "is_stormy": True, "puddle_mm": 12, "ground_wet": True}),
    ("fog", "Foggy morning", None, {"cloud_cover": 100, "is_foggy": True, "hour": 8}),
    ("flurries", "First flurries", COLD,
     {"cloud_cover": 90, "snowfall_cm_h": 0.3, "snow_depth_cm": 0.5, "roof_snow_cm": 0.5, "temp_c": -1}),
    ("snowing", "Snowing steadily", ("winter",),
     {"cloud_cover": 100, "snowfall_cm_h": 1.5, "snow_depth_cm": 8, "roof_snow_cm": 6, "temp_c": -4}),
    ("blizzard", "Blizzard", ("winter",),
     {"cloud_cover": 100, "snowfall_cm_h": 4.0, "snow_depth_cm": 25, "roof_snow_cm": 10, "temp_c": -9,
      "wind_kmh": 50}),
    ("after_snow", "Sunny after a snowfall", ("winter",),
     {"cloud_cover": 5, "snow_depth_cm": 15, "roof_snow_cm": 8, "temp_c": -5}),
    ("night_full", "Night, full moon", None,
     {"phase": "night", "cloud_cover": 5, "hour": 23, "moon_up": True, "moon_illum": 1.0, "moon_waxing": True}),
    # a different phase each season, so the demo shows the moon's shading
    ("night_waxing_crescent", "Night, waxing crescent moon", ("spring",),
     {"phase": "night", "cloud_cover": 5, "hour": 20, "moon_up": True, "moon_illum": 0.2, "moon_waxing": True}),
    ("night_first_quarter", "Night, first quarter moon", ("summer",),
     {"phase": "night", "cloud_cover": 5, "hour": 22, "moon_up": True, "moon_illum": 0.5, "moon_waxing": True}),
    ("night_waning_gibbous", "Night, waning gibbous moon", ("autumn",),
     {"phase": "night", "cloud_cover": 5, "hour": 23, "moon_up": True, "moon_illum": 0.75, "moon_waxing": False}),
    ("night_waning_crescent", "Night, waning crescent moon", ("winter",),
     {"phase": "night", "cloud_cover": 5, "hour": 4, "moon_up": True, "moon_illum": 0.2, "moon_waxing": False}),
    ("night_cloudy", "Night, cloudy", None, {"phase": "night", "cloud_cover": 95, "hour": 23}),
]


def moon_phase_name(illum: float, waxing: bool) -> str:
    """Same cut-offs as astro.py and the firmware."""
    if illum < 0.03:
        return "new"
    if illum > 0.97:
        return "full"
    if 0.40 <= illum <= 0.60:
        return "first_quarter" if waxing else "last_quarter"
    if illum < 0.40:
        return "waxing_crescent" if waxing else "waning_crescent"
    return "waxing_gibbous" if waxing else "waning_gibbous"


def complete(state: dict) -> dict:
    """Fill in the values that follow from others, so a hand-made state is
    consistent (is_raining from rain_mm_h, moon_phase from moon_illum, ...)."""
    s = dict(DEFAULT_STATE)
    s.update(state)
    s["is_raining"] = s["rain_mm_h"] > 0
    s["is_snowing"] = s["snowfall_cm_h"] > 0
    s["puddles_frozen"] = s["puddle_mm"] > 0 and s["temp_c"] <= -2
    s["moon_illum"] = round(float(s["moon_illum"]), 3)
    s["moon_phase"] = moon_phase_name(s["moon_illum"], bool(s["moon_waxing"]))
    s["condition"] = ("thunderstorm" if s["is_stormy"] else "snow" if s["is_snowing"] else
                      "rain" if s["is_raining"] else "fog" if s["is_foggy"] else
                      "overcast" if s["cloud_cover"] >= 70 else "clear")
    if s["phase"] != "day":
        s["sun_alt"] = -3.0 if s["phase"] in ("dawn", "dusk") else -30.0
    s["moon_alt"] = 30.0 if s["moon_up"] else -20.0
    return derive(s)


def combos(plausible_only: bool = True) -> list[tuple[str, str, dict]]:
    """[(name, title, state)] for every season x condition."""
    out = []
    for season, (month, temp) in SEASONS.items():
        for name, title, seasons, changes in CONDITIONS:
            if plausible_only and seasons is not None and season not in seasons:
                continue
            s = {"season": season, "month": month, "temp_c": temp}
            s.update(changes)
            out.append((f"{season}_{name}", f"{season.capitalize()}: {title}", complete(s)))
    return out
