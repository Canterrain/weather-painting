#include "weather.h"
#include <ArduinoJson.h>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>
#include <math.h>
#include <time.h>
#include "astro.h"

#define LOG Serial1

// the airport report last used, for the settings page (kept through sleep)
RTC_DATA_ATTR static char g_report[80] = "";
const char *last_report() { return g_report; }

// Python's round(x, ndigits) rounds half to even; rint() does the same.
static double pyround(double x, int nd) {
  double m = pow(10.0, nd);
  return rint(x * m) / m;
}

static String url_encode(const String &s) {
  String out;
  const char *hex = "0123456789ABCDEF";
  for (size_t i = 0; i < s.length(); ++i) {
    char c = s[i];
    if (isalnum((unsigned char)c) || c == '-' || c == '_' || c == '.' || c == '~') out += c;
    else { out += '%'; out += hex[(c >> 4) & 15]; out += hex[c & 15]; }
  }
  return out;
}

static bool https_get(const String &url, String &body) {
  WiFiClientSecure tls;
  tls.setInsecure();   // public weather data, nothing secret
  HTTPClient http;
  http.setConnectTimeout(10000);
  http.setTimeout(20000);
  if (!http.begin(tls, url)) return false;
  int code = http.GET();
  if (code == 200) body = http.getString();
  else LOG.printf("[weather] HTTP %d for %s\n", code, url.c_str());
  http.end();
  return code == 200;
}

// --- geocoding ---------------------------------------------------------------

static const char *US_STATES[][2] = {
  {"alabama", "al"}, {"alaska", "ak"}, {"arizona", "az"}, {"arkansas", "ar"}, {"california", "ca"},
  {"colorado", "co"}, {"connecticut", "ct"}, {"delaware", "de"}, {"florida", "fl"}, {"georgia", "ga"},
  {"hawaii", "hi"}, {"idaho", "id"}, {"illinois", "il"}, {"indiana", "in"}, {"iowa", "ia"},
  {"kansas", "ks"}, {"kentucky", "ky"}, {"louisiana", "la"}, {"maine", "me"}, {"maryland", "md"},
  {"massachusetts", "ma"}, {"michigan", "mi"}, {"minnesota", "mn"}, {"mississippi", "ms"},
  {"missouri", "mo"}, {"montana", "mt"}, {"nebraska", "ne"}, {"nevada", "nv"}, {"new hampshire", "nh"},
  {"new jersey", "nj"}, {"new mexico", "nm"}, {"new york", "ny"}, {"north carolina", "nc"},
  {"north dakota", "nd"}, {"ohio", "oh"}, {"oklahoma", "ok"}, {"oregon", "or"}, {"pennsylvania", "pa"},
  {"rhode island", "ri"}, {"south carolina", "sc"}, {"south dakota", "sd"}, {"tennessee", "tn"},
  {"texas", "tx"}, {"utah", "ut"}, {"vermont", "vt"}, {"virginia", "va"}, {"washington", "wa"},
  {"west virginia", "wv"}, {"wisconsin", "wi"}, {"wyoming", "wy"}, {"district of columbia", "dc"},
};

static String state_code(String admin1) {
  admin1.toLowerCase();
  for (auto &s : US_STATES) if (admin1 == s[0]) return s[1];
  return "";
}

bool geocode(const String &location, Place &out) {
  // "Cincinnati,OH,US": name to search, then hints to pick among same-named places
  String parts[6];
  int nparts = 0, start = 0;
  while (nparts < 6) {
    int comma = location.indexOf(',', start);
    String p = location.substring(start, comma < 0 ? location.length() : comma);
    p.trim();
    parts[nparts++] = p;
    if (comma < 0) break;
    start = comma + 1;
  }
  String body;
  String url = "https://geocoding-api.open-meteo.com/v1/search?count=10&language=en&format=json&name=" +
               url_encode(parts[0]);
  if (!https_get(url, body)) return false;
  JsonDocument doc;
  if (deserializeJson(doc, body)) return false;
  JsonArray results = doc["results"].as<JsonArray>();
  if (results.isNull() || results.size() == 0) return false;

  int best = -1, best_score = -1, i = 0;
  for (JsonObject r : results) {
    String a1 = r["admin1"] | "", cc = r["country_code"] | "", country = r["country"] | "";
    a1.toLowerCase(); cc.toLowerCase(); country.toLowerCase();
    String code = state_code(a1);
    int score = 0;
    for (int h = 1; h < nparts; ++h) {
      String hint = parts[h];
      hint.toLowerCase();
      if (hint == a1 || hint == cc || hint == country || hint == code) score++;
    }
    if (score > best_score) { best_score = score; best = i; }   // ties keep Open-Meteo's order
    ++i;
  }
  JsonObject r = results[best];
  out.lat = r["latitude"];
  out.lon = r["longitude"];
  out.name = String((const char *)(r["name"] | "")) + ", " + (const char *)(r["admin1"] | "") + ", " +
             (const char *)(r["country_code"] | "");
  return true;
}

// --- weather -----------------------------------------------------------------

static const char *condition_for(int code) {
  switch (code) {
    case 0: return "clear";
    case 1: case 2: return "partly_cloudy";
    case 3: return "overcast";
    case 45: case 48: return "fog";
    case 51: case 53: case 55: return "drizzle";
    case 56: case 57: case 66: case 67: return "freezing_rain";
    case 61: case 63: case 65: case 80: case 81: case 82: return "rain";
    case 71: case 73: case 75: case 77: case 85: case 86: return "snow";
    case 95: case 96: case 99: return "thunderstorm";
    default: return "overcast";
  }
}

static const char *season_for(int month, double lat) {
  static const char *north[12] = {"winter", "winter", "spring", "spring", "spring", "summer",
                                  "summer", "summer", "autumn", "autumn", "autumn", "winter"};
  const char *s = north[month - 1];
  if (lat >= 0) return s;
  if (!strcmp(s, "winter")) return "summer";
  if (!strcmp(s, "summer")) return "winter";
  if (!strcmp(s, "spring")) return "autumn";
  return "spring";
}

static const char *time_phase(double sun_alt, int local_hour) {
  if (sun_alt < -6) return "night";
  if (sun_alt < 6) return local_hour < 12 ? "dawn" : "dusk";
  return "day";
}

// --- airport weather reports (METAR) ----------------------------------------
// What's falling right now comes from the nearest airport's report when one
// is close by: a forecast model can lag a passing storm by half an hour and
// rarely knows about thunder. A port of observe() in painter/weather.py.

static const double REPORT_KM = 50;          // farthest airport worth believing
static const double REPORT_MAX_AGE = 90;     // minutes before a report is too old

static double distance_km(double lat1, double lon1, double lat2, double lon2) {
  double p1 = lat1 * M_PI / 180, p2 = lat2 * M_PI / 180, dl = (lon2 - lon1) * M_PI / 180;
  double a = pow(sin((p2 - p1) / 2), 2) + cos(p1) * cos(p2) * pow(sin(dl / 2), 2);
  return 6371.0 * 2 * asin(sqrt(a));
}

struct Observed {
  double rain = 0, snow = 0;
  bool thunder = false, fog = false, freezing = false, drizzle_only = true;
};

// '-TSRA BR', 'VCSH', '+SN FZFG' -> rain and snow rates, thunder, fog
static Observed read_weather(const String &wx) {
  static const double RAIN[3] = {1.0, 4.0, 10.0}, DRIZZLE[3] = {0.2, 0.5, 1.0}, SNOW[3] = {0.3, 1.2, 3.0};
  Observed o;
  int start = 0;
  while (start < (int)wx.length()) {
    int end = wx.indexOf(' ', start);
    if (end < 0) end = wx.length();
    String g = wx.substring(start, end);
    start = end + 1;
    if (!g.length()) continue;
    int level = 1;                                   // light, moderate, heavy
    if (g[0] == '-') { level = 0; g.remove(0, 1); }
    else if (g[0] == '+') { level = 2; g.remove(0, 1); }
    bool nearby = g.startsWith("VC");                // within 10 miles, not here
    for (int i = nearby ? 2 : 0; i < (int)g.length(); i += 2) {
      String c = g.substring(i, i + 2);
      if (c == "TS") o.thunder = true;               // thunder nearby is still heard
      if (nearby) continue;
      if (c == "FZ") o.freezing = true;
      else if (c == "RA" || c == "UP" || c == "GR" || c == "GS") { o.rain = fmax(o.rain, RAIN[level]); o.drizzle_only = false; }
      else if (c == "DZ") o.rain = fmax(o.rain, DRIZZLE[level]);
      else if (c == "SN" || c == "SG" || c == "PL" || c == "IC") o.snow = fmax(o.snow, SNOW[level]);
      else if (c == "FG") o.fog = true;
    }
  }
  return o;
}


static void observe(const Place &place, double now, State &st) {
  double dlat = REPORT_KM / 111.0, dlon = dlat / fmax(cos(place.lat * M_PI / 180), 0.1);
  char box[96];
  snprintf(box, sizeof box, "%.2f,%.2f,%.2f,%.2f", place.lat - dlat, place.lon - dlon, place.lat + dlat, place.lon + dlon);
  String body;
  if (!https_get(String("https://aviationweather.gov/api/data/metar?format=json&hours=2&bbox=") + box, body) ||
      !body.length()) {
    LOG.println("[weather] no airport report nearby; using the forecast");
    g_report[0] = 0;
    return;
  }
  JsonDocument filter;
  for (const char *k : {"icaoId", "obsTime", "lat", "lon", "wxString", "rawOb"}) filter[0][k] = true;
  JsonDocument doc;
  if (deserializeJson(doc, body, DeserializationOption::Filter(filter))) { g_report[0] = 0; return; }
  body = String();

  JsonObject best;
  double best_km = 1e9, best_time = 0;
  for (JsonObject r : doc.as<JsonArray>()) {
    if (r["lat"].isNull() || r["obsTime"].isNull()) continue;
    double t = r["obsTime"].as<double>();
    if (now - t > REPORT_MAX_AGE * 60) continue;
    if (strstr(r["rawOb"] | "", " AO1")) continue;   // an automatic station with no precipitation sensor
    double km = distance_km(place.lat, place.lon, r["lat"].as<double>(), r["lon"].as<double>());
    if (km > REPORT_KM) continue;
    km = rint(km * 10) / 10;
    if (km < best_km || (km == best_km && t > best_time)) { best = r; best_km = km; best_time = t; }
  }
  if (best.isNull()) {
    LOG.println("[weather] no recent airport report within 50 km; using the forecast");
    g_report[0] = 0;
    return;
  }

  String wx = best["wxString"] | "";
  Observed o = read_weather(wx);
  const char *cond;
  if (o.thunder) cond = "thunderstorm";
  else if (o.snow > 0) cond = "snow";
  else if (o.rain > 0) cond = o.freezing ? "freezing_rain" : o.drizzle_only ? "drizzle" : "rain";
  else if (o.fog) cond = "fog";
  else cond = st.get("cloud_cover")->num >= 70 ? "overcast" : "clear";
  st.set("condition", cond);
  st.set("rain_mm_h", o.rain);
  st.set("snowfall_cm_h", o.snow);
  st.set("is_raining", o.rain > 0);
  st.set("is_snowing", o.snow > 0);
  st.set("is_foggy", o.fog);
  st.set("is_stormy", o.thunder);

  snprintf(g_report, sizeof g_report, "%s, %.0f km away: %s (%.0f min ago)", (const char *)(best["icaoId"] | "?"),
           best_km, wx.length() ? wx.c_str() : "no weather", (now - best_time) / 60);
  LOG.printf("[weather] airport %s\n", g_report);
}

static double num(JsonVariant v) { return v.isNull() ? 0.0 : v.as<double>(); }

bool fetch_state(const Place &place, double now, State &st) {
  String url = String("https://api.open-meteo.com/v1/forecast?latitude=") + String(place.lat, 4) +
               "&longitude=" + String(place.lon, 4) +
               "&hourly=temperature_2m,precipitation,rain,showers,snowfall,snow_depth,weather_code,"
               "cloud_cover,wind_speed_10m,is_day"
               "&current=temperature_2m,precipitation,rain,showers,snowfall,weather_code,cloud_cover,"
               "wind_speed_10m,is_day"
               "&past_days=3&forecast_days=1&timezone=auto&timeformat=unixtime";
  String body;
  if (!https_get(url, body)) return false;
  JsonDocument doc;
  DeserializationError err = deserializeJson(doc, body);
  body = String();
  if (err) { LOG.printf("[weather] JSON error %s\n", err.c_str()); return false; }

  JsonObject hourly = doc["hourly"], cur = doc["current"];
  JsonArray times = hourly["time"];
  int n = times.size();
  if (n == 0) return false;
  int idx = 0;
  for (int i = 0; i < n; ++i) if (times[i].as<double>() <= now) idx = i;

  // accumulation, hour by hour (simulate_accumulation in weather.py)
  double snow = 0, roof = 0, puddle = 0, rain24 = 0, snow24 = 0, rain3 = 0;
  for (int i = 0; i <= idx; ++i) {
    double t = num(hourly["temperature_2m"][i]);
    double snowfall = num(hourly["snowfall"][i]);
    double rain = num(hourly["rain"][i]) + num(hourly["showers"][i]);
    bool sunny = num(hourly["is_day"][i]) != 0;

    snow += snowfall;
    double melt = 0;
    if (t > 0) {
      melt = fmin(snow, 0.12 * t + 0.04 * rain + (sunny ? 0.05 : 0));
      snow -= melt;
    }
    roof += snowfall * 0.9;
    if (t > -1.5) roof = fmax(0.0, roof - (0.2 * (t + 1.5) + 0.06 * rain + (sunny ? 0.08 : 0)));
    if (t > 0) puddle += rain + melt * 0.5;
    puddle -= puddle * 0.035 + (sunny ? 0.04 * fmax(t, 0) / 10 : 0.0);
    puddle = fmin(fmax(puddle, 0.0), 30.0);

    if (i > idx - 24) { rain24 += rain; snow24 += snowfall; }
    if (i > idx - 3) rain3 += rain;
  }

  double api_snow_cm = num(hourly["snow_depth"][idx]) * 100.0;
  double snow_depth = fmax(snow, api_snow_cm);
  double roof_snow = fmax(roof, num(hourly["temperature_2m"][idx]) < 1 ? 0.5 * api_snow_cm : 0.0);

  int code = cur["weather_code"].isNull() ? (int)num(hourly["weather_code"][idx]) : cur["weather_code"].as<int>();
  const char *cond = condition_for(code);
  double temp = cur["temperature_2m"].isNull() ? num(hourly["temperature_2m"][idx]) : num(cur["temperature_2m"]);
  // "current" amounts are totals over its interval (15 minutes), not per hour
  double per_hour = 3600.0 / (num(cur["interval"]) > 0 ? num(cur["interval"]) : 3600.0);
  double rain_now = (num(cur["rain"]) + num(cur["showers"])) * per_hour;
  double snow_now = num(cur["snowfall"]) * per_hour;
  double cloud = cur["cloud_cover"].isNull() ? num(hourly["cloud_cover"][idx]) : num(cur["cloud_cover"]);
  double wind = cur["wind_speed_10m"].isNull() ? num(hourly["wind_speed_10m"][idx]) : num(cur["wind_speed_10m"]);

  time_t local = (time_t)(now + num(doc["utc_offset_seconds"]));
  struct tm tm_local;
  gmtime_r(&local, &tm_local);
  int hour = tm_local.tm_hour, month = tm_local.tm_mon + 1;

  SkyState sky = sky_at(now, place.lat, place.lon);
  double sun_alt = pyround(sky.sun_alt, 1);
  const char *phase = time_phase(sun_alt, hour);
  bool is_night = !strcmp(phase, "night");
  int cloud_i = (int)rint(cloud);

  st.set("hour", hour);
  st.set("month", month);
  st.set("season", season_for(month, place.lat));
  st.set("phase", phase);
  st.set("is_day", !strcmp(phase, "day"));
  st.set("is_night", is_night);
  st.set("sun_alt", sun_alt);
  st.set("moon_alt", pyround(sky.moon_alt, 1));
  st.set("moon_up", sky.moon_up);
  st.set("moon_illum", pyround(sky.moon_illum, 3));
  st.set("moon_waxing", sky.moon_waxing);
  st.set("moon_phase", sky.moon_phase);
  st.set("temp_c", pyround(temp, 1));
  st.set("cloud_cover", cloud_i);
  st.set("wind_kmh", (int)rint(wind));
  st.set("weather_code", code);
  st.set("condition", cond);
  st.set("rain_mm_h", pyround(rain_now, 2));
  st.set("snowfall_cm_h", pyround(snow_now, 2));
  st.set("is_raining", !strcmp(cond, "rain") || !strcmp(cond, "drizzle") || !strcmp(cond, "freezing_rain") ||
                           !strcmp(cond, "thunderstorm") || rain_now > 0.1);
  st.set("is_snowing", !strcmp(cond, "snow") || snow_now > 0.05);
  st.set("is_foggy", !strcmp(cond, "fog"));
  st.set("is_stormy", !strcmp(cond, "thunderstorm"));
  st.set("snow_depth_cm", pyround(snow_depth, 1));
  st.set("roof_snow_cm", pyround(roof_snow, 1));
  st.set("puddle_mm", pyround(puddle, 1));
  st.set("puddles_frozen", puddle > 0.5 && temp < -1);
  st.set("rain_last_24h_mm", pyround(rain24, 1));
  st.set("snow_last_24h_cm", pyround(snow24, 1));
  st.set("ground_wet", rain3 > 0.2);
  st.set("stars_visible", is_night && cloud_i < 40);
  observe(place, now, st);
  return true;
}
