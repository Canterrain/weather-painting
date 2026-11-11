"""Fetch weather from Open-Meteo (free, no API key) and turn it into a
"world state": a flat dict of values the scene's layer rules can read.

Things that build up over time (snow on the ground, snow on the roof,
puddles) are simulated hour by hour over the last 3 days, so the painting
changes gradually instead of flipping on and off with the current reading.
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from . import astro

OPEN_METEO = "https://api.open-meteo.com/v1/forecast"
GEOCODING = "https://geocoding-api.open-meteo.com/v1/search"
HOURLY = ["temperature_2m", "precipitation", "rain", "showers", "snowfall", "snow_depth",
          "weather_code", "cloud_cover", "wind_speed_10m", "is_day"]


def fetch_open_meteo(lat: float, lon: float, timeout: float = 20) -> dict:
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": ",".join(HOURLY),
        "current": "temperature_2m,precipitation,rain,showers,snowfall,weather_code,cloud_cover,wind_speed_10m,is_day",
        "past_days": 3,
        "forecast_days": 1,
        "timezone": "auto",
        "timeformat": "unixtime",   # plain timestamps: the firmware parses the same response
    }
    url = OPEN_METEO + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.load(r)


def geocode(location: str, timeout: float = 10) -> dict:
    """'Cincinnati,OH,US' -> {lat, lon, timezone, name} via Open-Meteo's geocoder.

    Open-Meteo matches on the place name only, so extra parts ('OH', 'US')
    are used to pick the right result among same-named places."""
    name, *hints = [p.strip() for p in location.split(",")]
    url = GEOCODING + "?" + urllib.parse.urlencode({"name": name, "count": 10, "language": "en", "format": "json"})
    with urllib.request.urlopen(url, timeout=timeout) as r:
        results = json.load(r).get("results") or []
    if not results:
        raise ValueError(f"Open-Meteo couldn't find a place called {name!r}")

    def score(res):
        fields = {str(res.get(k, "")).lower() for k in ("admin1", "country_code", "country")}
        state_codes = {US_STATES.get(str(res.get("admin1", "")).lower(), "").lower()}
        return sum(h.lower() in fields | state_codes for h in hints)

    best = max(results, key=score)  # ties keep Open-Meteo's order (largest population first)
    return {"lat": best["latitude"], "lon": best["longitude"], "timezone": best.get("timezone", "auto"),
            "name": ", ".join(str(best[k]) for k in ("name", "admin1", "country_code") if best.get(k))}


US_STATES = {n.lower(): c for c, n in {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
    "CT": "Connecticut", "DE": "Delaware", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
    "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York", "NC": "North Carolina",
    "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
    "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas",
    "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming", "DC": "District of Columbia"}.items()}


# --- WMO weather codes -> simple condition names ---------------------------

def condition_for(code: int) -> str:
    if code == 0:
        return "clear"
    if code in (1, 2):
        return "partly_cloudy"
    if code == 3:
        return "overcast"
    if code in (45, 48):
        return "fog"
    if code in (51, 53, 55):
        return "drizzle"
    if code in (56, 57, 66, 67):
        return "freezing_rain"
    if code in (61, 63, 65, 80, 81, 82):
        return "rain"
    if code in (71, 73, 75, 77, 85, 86):
        return "snow"
    if code in (95, 96, 99):
        return "thunderstorm"
    return "overcast"


# --- Sun and moon ------------------------------------------------------------

def sky_state(lat: float, lon: float, unix_seconds: float) -> dict:
    """Sun altitude and moon position/phase (see astro.py; mirrored in the firmware)."""
    return astro.sky(unix_seconds, lat, lon)


def time_phase(sun_alt: float, local_hour: int) -> str:
    """night / dawn / day / dusk from the sun's altitude."""
    if sun_alt < -6:
        return "night"
    if sun_alt < 6:
        return "dawn" if local_hour < 12 else "dusk"
    return "day"


def season_for(month: int, lat: float) -> str:
    north = ["winter", "winter", "spring", "spring", "spring", "summer",
             "summer", "summer", "autumn", "autumn", "autumn", "winter"][month - 1]
    if lat >= 0:
        return north
    return {"winter": "summer", "summer": "winter", "spring": "autumn", "autumn": "spring"}[north]


# --- Accumulation model ------------------------------------------------------

def simulate_accumulation(hours: list[dict]) -> dict:
    """Walk the hourly history (oldest first, ending at 'now') and keep a
    running total of ground snow, roof snow and puddle water."""
    snow = roof = puddle = 0.0
    for h in hours:
        t = h["temp"]
        snowfall = h["snowfall"]            # cm this hour
        rain = h["rain"]                    # mm this hour (rain + showers)
        sunny = h["is_day"]

        # ground snow: builds from snowfall, melts above freezing (faster in rain)
        snow += snowfall
        melt = 0.0
        if t > 0:
            melt = min(snow, 0.12 * t + 0.04 * rain + (0.05 if sunny else 0))
            snow -= melt

        # roof snow: a bit less sticks (wind), melts sooner (warm house, sun)
        roof += snowfall * 0.9
        if t > -1.5:
            roof = max(0.0, roof - (0.2 * (t + 1.5) + 0.06 * rain + (0.08 if sunny else 0)))

        # puddles: rain and snowmelt fill them; they drain and evaporate
        if t > 0:
            puddle += rain + melt * 0.5
        puddle -= puddle * 0.035 + (0.04 * max(t, 0) / 10 if sunny else 0.0)
        puddle = min(max(puddle, 0.0), 30.0)

    return {"snow_model_cm": snow, "roof_model_cm": roof, "puddle_mm": puddle}


def build_state(data: dict, lat: float, lon: float, now: float | None = None) -> dict:
    """`data` is an Open-Meteo response fetched with timeformat=unixtime;
    `now` is a unix timestamp (defaults to the current time)."""
    now = time.time() if now is None else now
    local = datetime.fromtimestamp(now + data.get("utc_offset_seconds", 0), timezone.utc)

    hourly = data["hourly"]
    times = hourly["time"]
    idx = max((i for i, t in enumerate(times) if t <= now), default=0)

    def v(key, i, default=0.0):
        x = hourly[key][i]
        return default if x is None else x

    history = [{
        "temp": v("temperature_2m", i),
        "snowfall": v("snowfall", i),
        "rain": v("rain", i) + v("showers", i),
        "is_day": bool(v("is_day", i)),
    } for i in range(idx + 1)]
    acc = simulate_accumulation(history)

    api_snow_cm = v("snow_depth", idx) * 100.0
    snow_depth = max(acc["snow_model_cm"], api_snow_cm)
    roof_snow = max(acc["roof_model_cm"], 0.5 * api_snow_cm if v("temperature_2m", idx) < 1 else 0.0)

    cur = data.get("current", {})
    code = int(cur.get("weather_code", v("weather_code", idx)))
    cond = condition_for(code)
    temp = cur.get("temperature_2m", v("temperature_2m", idx))
    rain_now = (cur.get("rain") or 0) + (cur.get("showers") or 0)
    snow_now = cur.get("snowfall") or 0.0
    cloud = cur.get("cloud_cover", v("cloud_cover", idx))
    last24 = history[-24:]

    sky = sky_state(lat, lon, now)
    phase = time_phase(sky["sun_alt"], local.hour)

    state = {
        # time
        "hour": local.hour,
        "month": local.month,
        "season": season_for(local.month, lat),
        "phase": phase,
        "is_day": phase == "day",
        "is_night": phase == "night",
        **sky,
        # weather right now
        "temp_c": round(temp, 1),
        "cloud_cover": round(cloud),
        "wind_kmh": round(cur.get("wind_speed_10m", v("wind_speed_10m", idx))),
        "weather_code": code,
        "condition": cond,
        "rain_mm_h": round(rain_now, 2),
        "snowfall_cm_h": round(snow_now, 2),
        "is_raining": cond in ("rain", "drizzle", "freezing_rain", "thunderstorm") or rain_now > 0.1,
        "is_snowing": cond == "snow" or snow_now > 0.05,
        "is_foggy": cond == "fog",
        "is_stormy": cond == "thunderstorm",
        # accumulated
        "snow_depth_cm": round(snow_depth, 1),
        "roof_snow_cm": round(roof_snow, 1),
        "puddle_mm": round(acc["puddle_mm"], 1),
        "puddles_frozen": acc["puddle_mm"] > 0.5 and temp < -1,
        "rain_last_24h_mm": round(sum(h["rain"] for h in last24), 1),
        "snow_last_24h_cm": round(sum(h["snowfall"] for h in last24), 1),
        "ground_wet": sum(h["rain"] for h in history[-3:]) > 0.2,
    }
    state["stars_visible"] = state["is_night"] and state["cloud_cover"] < 40
    return state


# A calm, clear midday used as the base for offline scenarios.
DEFAULT_STATE = {
    "hour": 12, "month": 6, "season": "summer", "phase": "day", "is_day": True, "is_night": False,
    "sun_alt": 45.0, "moon_alt": -20.0, "moon_up": False, "moon_illum": 0.5, "moon_waxing": True,
    "moon_phase": "first_quarter",
    "temp_c": 18.0, "cloud_cover": 10, "wind_kmh": 5, "weather_code": 0, "condition": "clear",
    "rain_mm_h": 0.0, "snowfall_cm_h": 0.0, "is_raining": False, "is_snowing": False,
    "is_foggy": False, "is_stormy": False,
    "snow_depth_cm": 0.0, "roof_snow_cm": 0.0, "puddle_mm": 0.0, "puddles_frozen": False,
    "rain_last_24h_mm": 0.0, "snow_last_24h_cm": 0.0, "ground_wet": False, "stars_visible": False,
}


def derive(state: dict) -> dict:
    """Recompute the convenience flags after manual overrides (scenarios)."""
    s = dict(state)
    s["is_day"] = s["phase"] == "day"
    s["is_night"] = s["phase"] == "night"
    s["stars_visible"] = s["is_night"] and s["cloud_cover"] < 40
    return s
