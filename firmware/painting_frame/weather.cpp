#include "weather.h"
#include <ArduinoJson.h>
#include <HTTPClient.h>
#include <PNGdec.h>
#include <WiFiClientSecure.h>
#include <math.h>
#include <algorithm>
#include <vector>
#include <string.h>
#include <time.h>
#include "astro.h"

#define LOG Serial1

// the airport report last used, for the settings page (kept through sleep)
RTC_DATA_ATTR static char g_report[160] = "";
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
// What's falling right now is decided by blend(): weather radar over this
// exact spot, nearby airports' reports and the forecast vote together. Radar
// sees rain where you are, airports say what kind it is and hear thunder,
// and the forecast knows whether a storm is coming or going. A port of
// blend() in painter/weather.py.

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


// --- weather radar (RainViewer) -----------------------------------------------
// Radar from national weather services, free and without a key for personal,
// non-commercial use, with credit (settings page and README). Where a country
// shares no radar, RainViewer's coverage map says so and radar sits out.

static const int RADAR_ZOOM = 7;           // RainViewer's highest, about 1 km per pixel here
static const int RADAR_RADIUS_PX = 2;      // look about 2 km around the spot
static const double RADAR_MAX_AGE = 30;    // minutes before a radar frame is too old
static const int RADAR_WET_DBZ = 20;       // weaker echoes are mostly drizzle aloft or noise
static const int RADAR_NONE = -32;

// RainViewer's Universal Blue colors for -32..75 dBZ, rain only (snow coloring
// off); repeated colors keep the lower strength. From its published table, as
// used in SDupuie's esp32-weather-alarm-clock fork of the round display.
static const uint32_t RADAR_COLORS[] = {
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
};

static int radar_dbz(uint32_t rgb) {
  for (int i = 22; i < (int)(sizeof RADAR_COLORS / sizeof *RADAR_COLORS); ++i)
    if (RADAR_COLORS[i] == rgb) return i - 32;
  return RADAR_NONE;
}

static bool https_get_bytes(const String &url, std::vector<uint8_t> &out) {
  WiFiClientSecure tls;
  tls.setInsecure();   // public weather data, nothing secret
  HTTPClient http;
  http.setConnectTimeout(10000);
  http.setTimeout(20000);
  if (!http.begin(tls, url)) return false;
  int code = http.GET();
  bool ok = code == 200;
  if (ok) {
    int len = http.getSize();
    auto *stream = http.getStreamPtr();
    out.clear();
    uint8_t buf[1024];
    uint32_t t = millis();
    while (http.connected() && (len < 0 || (int)out.size() < len) && millis() - t < 20000) {
      int n = stream->readBytes(buf, sizeof buf);
      if (n <= 0) { if (len < 0) break; else continue; }
      out.insert(out.end(), buf, buf + n);
    }
    ok = len < 0 || (int)out.size() == len;
  } else {
    LOG.printf("[weather] HTTP %d for %s\n", code, url.c_str());
  }
  http.end();
  return ok;
}

// What a tile looks like around one pixel: the strongest echo, or for the
// coverage map whether that pixel is opaque (no radar).
struct TileLook {
  int px, py;
  int dbz = RADAR_NONE;
  bool opaque = false;
};

static int tile_row(PNGDRAW *d) {
  TileLook *look = (TileLook *)d->pUser;
  int dy = d->y - look->py;
  if (dy < -RADAR_RADIUS_PX || dy > RADAR_RADIUS_PX) return 1;
  int bpp = d->iPixelType == PNG_PIXEL_TRUECOLOR_ALPHA ? 4 : d->iPixelType == PNG_PIXEL_TRUECOLOR ? 3 : 0;
  if (!bpp) return 0;   // RainViewer sends 8-bit RGBA; anything else isn't read
  for (int dx = -RADAR_RADIUS_PX; dx <= RADAR_RADIUS_PX; ++dx) {
    if (dx * dx + dy * dy > RADAR_RADIUS_PX * RADAR_RADIUS_PX) continue;
    int x = constrain(look->px + dx, 0, d->iWidth - 1);
    const uint8_t *p = d->pPixels + x * bpp;
    bool visible = bpp == 3 || p[3] != 0;
    if (dx == 0 && dy == 0) look->opaque = visible;
    if (visible) look->dbz = max(look->dbz, radar_dbz(((uint32_t)p[0] << 16) | (p[1] << 8) | p[2]));
  }
  return 1;
}

static bool look_at_tile(const String &url, TileLook &look) {
  std::vector<uint8_t> png_bytes;
  if (!https_get_bytes(url, png_bytes) || png_bytes.empty()) return false;
  PNG *png = new PNG();
  bool ok = png->openRAM(png_bytes.data(), png_bytes.size(), tile_row) == PNG_SUCCESS &&
            png->decode(&look, 0) == PNG_SUCCESS;
  png->close();
  delete png;
  return ok;
}

// The strongest radar echo (dBZ) within a couple of km in the latest frame;
// false where there's no radar or it's out of date.
static bool radar_echo(const Place &place, double now, int &dbz, int &age_min) {
  String body;
  if (!https_get("https://api.rainviewer.com/public/weather-maps.json", body)) return false;
  JsonDocument doc;
  if (deserializeJson(doc, body)) return false;
  body = String();
  JsonArray past = doc["radar"]["past"];
  if (past.size() == 0) return false;
  JsonObject frame = past[past.size() - 1];
  double frame_time = frame["time"] | 0.0;
  if (now - frame_time > RADAR_MAX_AGE * 60) return false;
  String host = doc["host"] | "", path = frame["path"] | "";

  int n = 1 << RADAR_ZOOM;
  double xf = (place.lon + 180) / 360 * n;
  double yf = (1 - asinh(tan(place.lat * M_PI / 180)) / M_PI) / 2 * n;
  int x = (int)xf, y = (int)yf;
  String xyz = "/256/" + String(RADAR_ZOOM) + "/" + String(x) + "/" + String(y);
  TileLook look;
  look.px = (int)((xf - x) * 256);
  look.py = (int)((yf - y) * 256);

  TileLook coverage = look;
  if (!look_at_tile(host + "/v2/coverage/0" + xyz + "/0/0_0.png", coverage) || coverage.opaque) return false;
  if (!look_at_tile(host + path + xyz + "/2/0_0.png", look)) return false;
  dbz = look.dbz;
  age_min = (int)lrint((now - frame_time) / 60);
  return true;
}

// Rain rate from echo strength (Marshall-Palmer, Z = 200 R^1.6).
static double radar_rain_mm_h(int dbz) { return rint(pow(pow(10, dbz / 10.0) / 200, 1 / 1.6) * 10) / 10; }

struct Station {
  String id, wx;
  double km = 0, time = 0;
  Observed o;
};

// How much an airport's vote counts: the same as the forecast's at 12 km,
// a third of it at 25 km.
static double station_weight(double km) { return 1.0 / (1.0 + pow(km / 12.0, 2)); }

static const double FORECAST_WEIGHT = 0.5;
static const double RADAR_WEIGHT = 1.5;    // radar over the spot outweighs the forecast and a nearby airport together
static const double THUNDER_KM = 30;   // thunder is heard this far, and means storm clouds overhead
static const double FOG_KM = 25;       // fog is local: farther airports don't count

// The latest recent report from each airport within REPORT_KM that can sense
// rain, nearest first.
static std::vector<Station> stations(const Place &place, double now) {
  std::vector<Station> out;
  double dlat = REPORT_KM / 111.0, dlon = dlat / fmax(cos(place.lat * M_PI / 180), 0.1);
  char box[96];
  snprintf(box, sizeof box, "%.2f,%.2f,%.2f,%.2f", place.lat - dlat, place.lon - dlon, place.lat + dlat, place.lon + dlon);
  String body;
  if (!https_get(String("https://aviationweather.gov/api/data/metar?format=json&hours=2&bbox=") + box, body) ||
      !body.length())
    return out;
  JsonDocument filter;
  for (const char *k : {"icaoId", "obsTime", "lat", "lon", "wxString", "rawOb"}) filter[0][k] = true;
  JsonDocument doc;
  if (deserializeJson(doc, body, DeserializationOption::Filter(filter))) return out;
  body = String();

  for (JsonObject r : doc.as<JsonArray>()) {
    if (r["lat"].isNull() || r["obsTime"].isNull()) continue;
    double t = r["obsTime"].as<double>();
    if (now - t > REPORT_MAX_AGE * 60) continue;
    if (strstr(r["rawOb"] | "", " AO1")) continue;   // an automatic station with no precipitation sensor
    double km = distance_km(place.lat, place.lon, r["lat"].as<double>(), r["lon"].as<double>());
    if (km > REPORT_KM) continue;
    String id = r["icaoId"] | "?";
    Station *same = nullptr;
    for (auto &s : out) if (s.id == id) same = &s;
    if (same && same->time >= t) continue;
    Station s;
    s.id = id;
    s.wx = (const char *)(r["wxString"] | "");
    s.km = km;
    s.time = t;
    s.o = read_weather(s.wx);
    if (same) *same = s;
    else out.push_back(s);
  }
  std::sort(out.begin(), out.end(), [](const Station &a, const Station &b) { return a.km < b.km; });
  return out;
}

// Rain or not is a vote: each airport counts more the closer it is, and the
// forecast votes for this exact spot, wet if it has rain or snow now or within
// half an hour (soon_rain, soon_snow). A storm the forecast missed is caught
// when the airports around agree on it; a shower at one airport 25 km away
// that the forecast says won't reach here is left out. What kind and how hard
// comes from the nearest airport measuring it.
static void blend(const Place &place, double now, double soon_rain, double soon_snow, State &st) {
  std::vector<Station> near = stations(place, now);
  int dbz = RADAR_NONE, radar_age = 0;
  bool have_radar = radar_echo(place, now, dbz, radar_age);
  if (near.empty() && !have_radar) {
    LOG.println("[weather] no radar or recent airport report nearby; using the forecast");
    g_report[0] = 0;
    return;
  }
  auto n = [&](const char *k) { return st.get(k)->num; };
  String fcond = st.get("condition")->text;
  bool forecast_wet = n("is_raining") || n("is_snowing") || soon_rain > 0.2 || soon_snow > 0.1;
  double vote = forecast_wet ? FORECAST_WEIGHT : -FORECAST_WEIGHT;
  for (auto &s : near) vote += station_weight(s.km) * (s.o.rain > 0 || s.o.snow > 0 ? 1 : -1);
  bool radar_wet = have_radar && dbz >= RADAR_WET_DBZ;
  if (have_radar) vote += radar_wet ? RADAR_WEIGHT : -RADAR_WEIGHT;
  bool falling = vote > 0;

  double rain = 0, snow = 0;
  bool freezing = false, drizzle_only = true;
  if (falling) {
    const Station *measured = nullptr;
    for (auto &s : near) if (s.o.rain > 0 || s.o.snow > 0) { measured = &s; break; }
    if (measured) {
      rain = measured->o.rain;
      snow = measured->o.snow;
      freezing = measured->o.freezing;
      drizzle_only = measured->o.drizzle_only;
    } else {   // what kind comes from the forecast
      rain = fmax(n("rain_mm_h"), soon_rain);
      snow = fmax(n("snowfall_cm_h"), soon_snow);
      drizzle_only = fcond == "drizzle";
      freezing = fcond == "freezing_rain";
    }
    if (radar_wet) {   // how hard comes from radar
      double rate = radar_rain_mm_h(dbz);
      if (snow > 0 && rain == 0) snow = rate;   // about 1 cm of snow per mm of water
      else { snow = snow > 0 ? rate : 0; rain = rate; }
      drizzle_only = drizzle_only && (measured || fcond == "drizzle");
    }
  }
  bool thunder = n("is_stormy") != 0;
  for (auto &s : near) if (s.o.thunder && s.km <= THUNDER_KM) thunder = true;
  bool fog = near[0].km <= FOG_KM ? near[0].o.fog : n("is_foggy") != 0;

  const char *cond;
  if (thunder) cond = "thunderstorm";
  else if (snow > 0) cond = "snow";
  else if (rain > 0) cond = freezing ? "freezing_rain" : drizzle_only ? "drizzle" : "rain";
  else if (fog) cond = "fog";
  else cond = n("cloud_cover") >= 70 ? "overcast" : "clear";
  st.set("condition", cond);
  st.set("rain_mm_h", pyround(rain, 2));
  st.set("snowfall_cm_h", pyround(snow, 2));
  st.set("is_raining", rain > 0);
  st.set("is_snowing", snow > 0);
  st.set("is_foggy", fog);
  st.set("is_stormy", thunder);

  String r;
  if (have_radar) r += "radar " + String(dbz) + " dBZ; ";
  for (size_t i = 0; i < near.size() && i < 3; ++i)
    r += near[i].id + " " + String((int)lrint(near[i].km)) + " km: " + (near[i].wx.length() ? near[i].wx : "dry") + "; ";
  r += String("forecast: ") + (forecast_wet ? "wet" : "dry");
  strlcpy(g_report, r.c_str(), sizeof g_report);
  LOG.printf("[weather] airports %s -> %s\n", g_report, cond);
}

static double num(JsonVariant v) { return v.isNull() ? 0.0 : v.as<double>(); }

// puddles (simulate_accumulation in weather.py)
static const double PUDDLE_FULL_MM = 12.0;   // deeper than this runs off
static const double PUDDLE_SOAK = 0.08;      // share that soaks in each hour
static const double PUDDLE_EVAPORATE = 3.0;  // shallow puddle edges dry faster than open ground

// What the frame saw falling, hour by hour, so rain and snow the radar and
// airports caught still fill puddles and cover the ground when the
// forecast's history missed them. Kept through sleep; a restart loses it,
// which only means going by the forecast alone for a few days.
struct SeenHour {
  double hour_end;   // as the forecast's hourly times: the hour up to here
  float rain_mm, snow_cm;
};
static const int SEEN_HOURS = 72;
RTC_DATA_ATTR static SeenHour g_seen[SEEN_HOURS];
RTC_DATA_ATTR static double g_seen_time = 0;             // the last wake counted
RTC_DATA_ATTR static float g_seen_rain = 0, g_seen_snow = 0;   // its rates
RTC_DATA_ATTR static float g_seen_lat = 0, g_seen_lon = 0;

static SeenHour *seen_hour(double hour_end, bool make) {
  SeenHour &s = g_seen[(long)(hour_end / 3600) % SEEN_HOURS];
  if (s.hour_end != hour_end) {
    if (!make) return nullptr;
    s = {hour_end, 0, 0};
  }
  return &s;
}

// Add what fell since the last wake: the average of its rates and these,
// over the time between. Gaps over an hour aren't guessed at.
static void tally(const Place &place, double now, double hour_end, double rain, double snow) {
  if (distance_km(place.lat, place.lon, g_seen_lat, g_seen_lon) > 5) {
    memset(g_seen, 0, sizeof g_seen);   // a new place: what fell elsewhere doesn't count
    g_seen_time = 0;
    g_seen_lat = place.lat;
    g_seen_lon = place.lon;
  }
  double gap_h = (now - g_seen_time) / 3600.0;
  if (g_seen_time > 0 && gap_h > 0 && gap_h <= 1.0 && (rain + g_seen_rain + snow + g_seen_snow) > 0) {
    SeenHour *s = seen_hour(hour_end, true);
    s->rain_mm += (g_seen_rain + rain) / 2 * gap_h;
    s->snow_cm += (g_seen_snow + snow) / 2 * gap_h;
  }
  g_seen_time = now;
  g_seen_rain = rain;
  g_seen_snow = snow;
}

bool fetch_state(const Place &place, double now, State &st) {
  String url = String("https://api.open-meteo.com/v1/forecast?latitude=") + String(place.lat, 4) +
               "&longitude=" + String(place.lon, 4) +
               "&hourly=temperature_2m,precipitation,rain,showers,snowfall,snow_depth,weather_code,"
               "cloud_cover,wind_speed_10m,is_day,et0_fao_evapotranspiration"
               "&current=temperature_2m,precipitation,rain,showers,snowfall,weather_code,cloud_cover,"
               "wind_speed_10m,is_day"
               "&minutely_15=precipitation,snowfall&forecast_minutely_15=3"
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
    if (SeenHour *seen = seen_hour(times[i].as<double>(), false)) {
      rain = fmax(rain, seen->rain_mm);
      snowfall = fmax(snowfall, seen->snow_cm);
    }
    bool sunny = num(hourly["is_day"][i]) != 0;

    snow += snowfall;
    double melt = 0;
    if (t > 0) {
      melt = fmin(snow, 0.12 * t + 0.04 * rain + (sunny ? 0.05 : 0));
      snow -= melt;
    }
    roof += snowfall * 0.9;
    if (t > -1.5) roof = fmax(0.0, roof - (0.2 * (t + 1.5) + 0.06 * rain + (sunny ? 0.08 : 0)));
    if (t > 0) puddle = fmin(puddle + rain + melt * 0.5, PUDDLE_FULL_MM);
    puddle -= puddle * PUDDLE_SOAK + PUDDLE_EVAPORATE * num(hourly["et0_fao_evapotranspiration"][i]);
    puddle = fmax(puddle, 0.0);

    if (i > idx - 24) { rain24 += rain; snow24 += snowfall; }
    if (i > idx - 3) rain3 += rain;
  }
  // and what's been seen so far this hour, which the history doesn't have yet
  double hour_end = times[idx].as<double>() + 3600;
  if (SeenHour *seen = seen_hour(hour_end, false)) {
    if (num(hourly["temperature_2m"][idx]) > 0) puddle = fmin(puddle + seen->rain_mm, PUDDLE_FULL_MM);
    snow += seen->snow_cm;
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

  time_t local_now = (time_t)(now + num(doc["utc_offset_seconds"]));
  struct tm tm_local;
  gmtime_r(&local_now, &tm_local);
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
  // the forecast's heaviest rain and snow here from now through the next half
  // hour, from its 15-minute steps
  double soon_rain = 0, soon_snow = 0;
  JsonObject m15 = doc["minutely_15"];
  JsonArray m_times = m15["time"];
  for (size_t i = 0; i < m_times.size(); ++i) {
    double t = m_times[i].as<double>();
    if (t < now - 900 || t > now + 1800) continue;
    soon_rain = fmax(soon_rain, num(m15["precipitation"][i]) * 4);
    soon_snow = fmax(soon_snow, num(m15["snowfall"][i]) * 4);
  }
  doc.clear();
  blend(place, now, soon_rain, soon_snow, st);
  tally(place, now, hour_end, st.get("rain_mm_h")->num, st.get("snowfall_cm_h")->num);
  return true;
}
