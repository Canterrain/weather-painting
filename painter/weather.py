"""Fetch weather from Open-Meteo (free, no API key) and turn it into a
"world state": a flat dict of values the scene's layer rules can read.

What's falling right now is decided by blend(): weather radar over this
exact spot, nearby airports' weather reports and the forecast vote
together. Radar sees rain where you are, airports say what kind it is and
hear thunder, and the forecast knows whether a storm is coming or going.

Things that build up over time (snow on the ground, snow on the roof,
puddles) are simulated hour by hour over the last 3 days, so the painting
changes gradually instead of flipping on and off with the current reading.
"""

from __future__ import annotations

import json
import math
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from . import astro

OPEN_METEO = "https://api.open-meteo.com/v1/forecast"
GEOCODING = "https://geocoding-api.open-meteo.com/v1/search"
METAR = "https://aviationweather.gov/api/data/metar"
RAINVIEWER = "https://api.rainviewer.com/public/weather-maps.json"
HOURLY = ["temperature_2m", "precipitation", "rain", "showers", "snowfall", "snow_depth",
          "weather_code", "cloud_cover", "wind_speed_10m", "is_day", "et0_fao_evapotranspiration"]


def fetch_open_meteo(lat: float, lon: float, timeout: float = 20) -> dict:
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": ",".join(HOURLY),
        "current": "temperature_2m,precipitation,rain,showers,snowfall,weather_code,cloud_cover,wind_speed_10m,is_day",
        "minutely_15": "precipitation,snowfall",
        "forecast_minutely_15": 3,     # now and the next half hour
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

PUDDLE_FULL_MM = 12.0    # deeper than this runs off
PUDDLE_SOAK = 0.08        # share that soaks in each hour: half a day after a shower
PUDDLE_EVAPORATE = 3.0    # shallow puddle edges dry faster than open ground


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

        # puddles: rain and snowmelt fill them, past full it runs off; they
        # soak in, and evaporate as fast as the weather dries things (sun,
        # heat, wind and dry air), so a hot sunny afternoon dries a downpour
        if t > 0:
            puddle = min(puddle + rain + melt * 0.5, PUDDLE_FULL_MM)
        puddle -= puddle * PUDDLE_SOAK + PUDDLE_EVAPORATE * h.get("drying", 0.0)
        puddle = max(puddle, 0.0)

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
        "drying": v("et0_fao_evapotranspiration", i),   # mm/h the weather dries
    } for i in range(idx + 1)]
    acc = simulate_accumulation(history)

    api_snow_cm = v("snow_depth", idx) * 100.0
    snow_depth = max(acc["snow_model_cm"], api_snow_cm)
    roof_snow = max(acc["roof_model_cm"], 0.5 * api_snow_cm if v("temperature_2m", idx) < 1 else 0.0)

    cur = data.get("current", {})
    code = int(cur.get("weather_code", v("weather_code", idx)))
    cond = condition_for(code)
    temp = cur.get("temperature_2m", v("temperature_2m", idx))
    # "current" amounts are totals over its interval (15 minutes), not per hour
    per_hour = 3600 / (cur.get("interval") or 3600)
    rain_now = ((cur.get("rain") or 0) + (cur.get("showers") or 0)) * per_hour
    snow_now = (cur.get("snowfall") or 0.0) * per_hour
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


# --- airport weather reports (METAR) ----------------------------------------
# Airports worldwide report what's happening every hour, and again within
# minutes when it changes, including thunder from lightning detectors. The
# US aviation weather service publishes all of them, free and without a key.

REPORT_KM = 50          # farthest airport worth believing
REPORT_MAX_AGE = 90     # minutes before a report is too old to use

# rain and snow rates for light (-), moderate and heavy (+) reports
RAIN_MM_H = {"-": 1.0, "": 4.0, "+": 10.0}
DRIZZLE_MM_H = {"-": 0.2, "": 0.5, "+": 1.0}
SNOW_CM_H = {"-": 0.3, "": 1.2, "+": 3.0}


def fetch_reports(lat: float, lon: float, timeout: float = 15) -> list[dict]:
    """The last two hours of reports from airports in a box around a place."""
    dlat = REPORT_KM / 111.0
    dlon = dlat / max(math.cos(math.radians(lat)), 0.1)
    box = f"{lat - dlat:.2f},{lon - dlon:.2f},{lat + dlat:.2f},{lon + dlon:.2f}"
    url = METAR + "?" + urllib.parse.urlencode({"bbox": box, "format": "json", "hours": 2})
    with urllib.request.urlopen(url, timeout=timeout) as r:
        body = r.read()
    return json.loads(body) if body.strip() else []


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 6371.0 * 2 * math.asin(math.sqrt(a))


def read_weather(wx: str) -> dict:
    """A report's weather groups ('-TSRA BR', 'VCSH', '+SN FZFG') -> what's
    happening: rain and snow rates, thunder, fog."""
    out = {"rain_mm_h": 0.0, "snowfall_cm_h": 0.0, "thunder": False, "fog": False,
           "freezing": False, "drizzle_only": True}
    for group in (wx or "").split():
        intensity = group[0] if group[0] in "+-" else ""
        group = group.lstrip("+-")
        nearby = group.startswith("VC")   # within 10 miles, not here
        codes = [group[i:i + 2] for i in range(2 if nearby else 0, len(group), 2)]
        if "TS" in codes:
            out["thunder"] = True         # thunder nearby is still heard
        if nearby:
            continue
        if "FZ" in codes:
            out["freezing"] = True
        for c in codes:
            if c in ("RA", "UP", "GR", "GS"):
                out["rain_mm_h"] = max(out["rain_mm_h"], RAIN_MM_H[intensity])
                out["drizzle_only"] = False
            elif c == "DZ":
                out["rain_mm_h"] = max(out["rain_mm_h"], DRIZZLE_MM_H[intensity])
            elif c in ("SN", "SG", "PL", "IC"):
                out["snowfall_cm_h"] = max(out["snowfall_cm_h"], SNOW_CM_H[intensity])
            elif c == "FG":
                out["fog"] = True
    return out


def stations(reports: list[dict], lat: float, lon: float, now: float) -> list[dict]:
    """The latest recent report from each airport within REPORT_KM that can
    sense rain, nearest first, each with its distance and what it says."""
    latest = {}
    for r in reports:
        if r.get("lat") is None or r.get("obsTime") is None:
            continue
        if now - r["obsTime"] > REPORT_MAX_AGE * 60:
            continue
        if " AO1" in (r.get("rawOb") or ""):
            continue   # an automatic station with no precipitation sensor
        km = distance_km(lat, lon, r["lat"], r["lon"])
        if km > REPORT_KM:
            continue
        old = latest.get(r["icaoId"])
        if old is None or r["obsTime"] > old["obsTime"]:
            latest[r["icaoId"]] = dict(r, km=km, wx=read_weather(r.get("wxString")))
    return sorted(latest.values(), key=lambda r: r["km"])


def model_soon(data: dict, now: float) -> tuple[float, float]:
    """The forecast's heaviest rain (mm/h) and snow (cm/h) here from now
    through the next half hour, from its 15-minute steps."""
    m = data.get("minutely_15") or {}
    rain = snow = 0.0
    for i, t in enumerate(m.get("time") or []):
        if now - 900 <= t <= now + 1800:
            rain = max(rain, (m["precipitation"][i] or 0) * 4)
            snow = max(snow, (m["snowfall"][i] or 0) * 4)
    return rain, snow


# --- weather radar (RainViewer) ----------------------------------------------
# RainViewer publishes radar from national weather services as map tiles,
# free and without a key for personal, non-commercial use, with credit
# (on the settings page and in the README). Where a country shares no radar,
# its coverage map says so and radar sits out the vote.

RADAR_ZOOM = 7            # RainViewer's highest, about 1 km per pixel here
RADAR_RADIUS_PX = 2       # look about 2 km around the spot
RADAR_MAX_AGE = 30        # minutes before a radar frame is too old
RADAR_WET_DBZ = 20        # echoes weaker than this are mostly drizzle aloft or noise

# RainViewer's Universal Blue colors for -32..75 dBZ, rain only (snow coloring
# off); repeated colors keep the lower strength. From its published table,
# as used in SDupuie's esp32-weather-alarm-clock fork of the round display.
RADAR_COLORS = [
    0x000000, 0x000000, 0x000000, 0x000000, 0x000000, 0x000000, 0x000000, 0x000000,
    0x000000, 0x000000, 0x000000, 0x000000, 0x000000, 0x000000, 0x000000, 0x000000,
    0x000000, 0x000000, 0x000000, 0x000000, 0x000000, 0x000000, 0x636159, 0x66635A,
    0x69665C, 0x6C685D, 0x6F6B5F, 0x726E61, 0x757062, 0x787364, 0x7C7565, 0x7F7867,
    0x827B69, 0x857D6A, 0x88806C, 0x8B826D, 0x8E856F, 0x928871, 0x9E9375, 0xAA9E79,
    0xB6A97E, 0xC2B482, 0xCEC087, 0xD2C48B, 0xD6C88F, 0xDACC93, 0xDED097, 0x88DDEE,
    0x6CD1EB, 0x51C5E8, 0x36BAE5, 0x1BAEE2, 0x00A3E0, 0x009AD5, 0x0091CA, 0x0088BF,
    0x007FB4, 0x0077AA, 0x0070A3, 0x00699C, 0x006295, 0x005B8E, 0x005588, 0x005180,
    0x004E78, 0x004A70, 0x004768, 0xFFEE00, 0xFFE000, 0xFFD200, 0xFFC500, 0xFFB700,
    0xFFAA00, 0xFF9F00, 0xFF9500, 0xFF8B00, 0xFF8100, 0xFF4400, 0xF23600, 0xE62800,
    0xD91B00, 0xCD0D00, 0xC10000, 0xA80000, 0x8F0000, 0x760000, 0x5D0000, 0xFFAAFF,
    0xFF9FFF, 0xFF95FF, 0xFF8BFF, 0xFF81FF, 0xFF77FF, 0xFF6CFF, 0xFF62FF, 0xFF58FF,
    0xFF4EFF, 0xFFFFFF,
]
RADAR_DBZ = {}
for _i, _c in enumerate(RADAR_COLORS):
    if _i >= 22:
        RADAR_DBZ.setdefault(_c, _i - 32)


def tile_pixel(lat: float, lon: float, zoom: int = RADAR_ZOOM) -> tuple[int, int, int, int]:
    """Web map tile x, y and the pixel within its 256x256 image."""
    n = 2 ** zoom
    xf = (lon + 180) / 360 * n
    yf = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n
    x, y = int(xf), int(yf)
    return x, y, int((xf - x) * 256), int((yf - y) * 256)


def _png_rgba(url: str, timeout: float):
    import io
    from PIL import Image
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return Image.open(io.BytesIO(r.read())).convert("RGBA")


def fetch_radar(lat: float, lon: float, now: float, timeout: float = 15) -> dict | None:
    """The strongest radar echo (dBZ) within a couple of km, from the latest
    frame, or None where there's no radar or it's out of date."""
    with urllib.request.urlopen(RAINVIEWER, timeout=timeout) as r:
        maps = json.load(r)
    frames = maps.get("radar", {}).get("past") or []
    if not frames or now - frames[-1]["time"] > RADAR_MAX_AGE * 60:
        return None
    host, frame = maps["host"], frames[-1]
    x, y, px, py = tile_pixel(lat, lon)
    coverage = _png_rgba(f"{host}/v2/coverage/0/256/{RADAR_ZOOM}/{x}/{y}/0/0_0.png", timeout)
    if coverage.getpixel((px, py))[3]:
        return None   # opaque: no radar here
    tile = _png_rgba(f"{host}{frame['path']}/256/{RADAR_ZOOM}/{x}/{y}/2/0_0.png", timeout)
    dbz = -32
    for dy in range(-RADAR_RADIUS_PX, RADAR_RADIUS_PX + 1):
        for dx in range(-RADAR_RADIUS_PX, RADAR_RADIUS_PX + 1):
            if dx * dx + dy * dy > RADAR_RADIUS_PX ** 2:
                continue
            r_, g, b, a = tile.getpixel((min(max(px + dx, 0), 255), min(max(py + dy, 0), 255)))
            if a:
                dbz = max(dbz, RADAR_DBZ.get((r_ << 16) | (g << 8) | b, -32))
    return {"dbz": dbz, "age_min": round((now - frame["time"]) / 60)}


def radar_rain_mm_h(dbz: float) -> float:
    """Rain rate from echo strength (Marshall-Palmer, Z = 200 R^1.6)."""
    return round((10 ** (dbz / 10) / 200) ** (1 / 1.6), 1)


def station_weight(km: float) -> float:
    """How much an airport's vote counts: the same as the forecast's at
    12 km, a third of it at 25 km."""
    return 1.0 / (1.0 + (km / 12.0) ** 2)


FORECAST_WEIGHT = 0.5
RADAR_WEIGHT = 1.5     # radar over the spot outweighs the forecast and a nearby airport together
THUNDER_KM = 30        # thunder is heard this far, and means storm clouds overhead
FOG_KM = 25            # fog is local: farther airports don't count


def blend(state: dict, near: list[dict], soon: tuple[float, float], radar: dict | None = None) -> dict:
    """Decide what's falling right now from the airports' reports and the
    forecast for this spot.

    Rain or not is a vote: each airport counts more the closer it is, and the
    forecast votes for this exact spot, wet if it has rain or snow now or
    within half an hour. Radar over the spot, where there is radar, counts
    most. A storm the forecast missed is caught when radar or the airports
    around see it; a shower at one airport 25 km away that's heading
    elsewhere is left out. How hard comes from radar, or else the nearest
    airport measuring it; rain or snow from that airport, or the forecast."""
    if not near and radar is None:
        return state
    soon_rain, soon_snow = soon
    forecast_wet = state["is_raining"] or state["is_snowing"] or soon_rain > 0.2 or soon_snow > 0.1
    vote = FORECAST_WEIGHT if forecast_wet else -FORECAST_WEIGHT
    for r in near:
        w = r["wx"]
        vote += station_weight(r["km"]) * (1 if w["rain_mm_h"] or w["snowfall_cm_h"] else -1)
    radar_wet = radar is not None and radar["dbz"] >= RADAR_WET_DBZ
    if radar is not None:
        vote += RADAR_WEIGHT if radar_wet else -RADAR_WEIGHT
    falling = vote > 0

    rain = snow = 0.0
    freezing, drizzle_only = False, True
    if falling:
        measured = next((r for r in near if r["wx"]["rain_mm_h"] or r["wx"]["snowfall_cm_h"]), None)
        if measured:
            w = measured["wx"]
            rain, snow = w["rain_mm_h"], w["snowfall_cm_h"]
            freezing, drizzle_only = w["freezing"], w["drizzle_only"]
        else:   # what kind comes from the forecast
            rain = max(state["rain_mm_h"], soon_rain)
            snow = max(state["snowfall_cm_h"], soon_snow)
            drizzle_only = state["condition"] == "drizzle"
            freezing = state["condition"] == "freezing_rain"
        if radar_wet:   # how hard comes from radar
            rate = radar_rain_mm_h(radar["dbz"])
            if snow and not rain:
                snow = rate      # about 1 cm of snow per mm of water
            else:
                rain, snow = rate, (rate if snow else 0.0)
            drizzle_only = drizzle_only and bool(measured or state["condition"] == "drizzle")
    thunder = state["is_stormy"] or any(r["wx"]["thunder"] and r["km"] <= THUNDER_KM for r in near)
    fog_airport = next((r for r in near if r["km"] <= FOG_KM), None)
    fog = fog_airport["wx"]["fog"] if fog_airport else state["is_foggy"]

    if thunder:
        cond = "thunderstorm"
    elif snow:
        cond = "snow"
    elif rain:
        cond = "freezing_rain" if freezing else "drizzle" if drizzle_only else "rain"
    elif fog:
        cond = "fog"
    else:
        cond = "overcast" if state["cloud_cover"] >= 70 else "clear"
    s = dict(state)
    s.update({
        "condition": cond,
        "rain_mm_h": round(rain, 2),
        "snowfall_cm_h": round(snow, 2),
        "is_raining": rain > 0,
        "is_snowing": snow > 0,
        "is_foggy": fog,
        "is_stormy": thunder,
        "report": "; ".join(([f"radar {radar['dbz']} dBZ"] if radar else [])
                            + [f"{r['icaoId']} {r['km']:.0f} km: {r.get('wxString') or 'dry'}" for r in near[:3]]
                            + [f"forecast: {'wet' if forecast_wet else 'dry'}"]),
    })
    return s


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
