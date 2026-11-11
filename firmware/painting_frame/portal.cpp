#include "portal.h"
#include <DNSServer.h>
#include <ESPmDNS.h>
#include <SD.h>
#include <Update.h>
#include <WebServer.h>
#include <WiFi.h>
#include <algorithm>
#include <vector>
#include "generated.h"
#include "ota.h"
#include "settings_page.h"
#include "version.h"
#include "weather.h"

#define LOG Serial1

static const uint32_t IDLE_MS = 15 * 60 * 1000;
static const int PIN_TOP_BUTTON = 3;

static WebServer *srv;
static Settings *cfg;
static bool g_setup_mode;
static volatile bool g_exit = false;
static PortalExit g_exit_kind = PORTAL_DONE;
static uint32_t g_last_request = 0;
static File g_upload;
static String g_upload_name, g_upload_error;
static bool g_update_ok = false;

static String json_escape(const String &s) {
  String o;
  for (size_t i = 0; i < s.length(); ++i) {
    char c = s[i];
    if (c == '"' || c == '\\') { o += '\\'; o += c; }
    else if ((uint8_t)c < 0x20) { char b[8]; snprintf(b, sizeof b, "\\u%04x", c); o += b; }
    else o += c;
  }
  return o;
}

static String q(const String &s) { return "\"" + json_escape(s) + "\""; }

static void reply(int code, const String &json) {
  srv->send(code, "application/json", json);
}

static void ok(const String &extra = "") {
  reply(200, "{\"ok\":true" + (extra.length() ? "," + extra : String("")) + "}");
}

static void fail(const String &message) {
  reply(400, "{\"ok\":false,\"error\":" + q(message) + "}");
}

// only plain layer file names: letters, digits, _ and .wpl
static bool safe_name(const String &n) {
  if (!n.endsWith(".wpl") || n.length() > 80) return false;
  for (size_t i = 0; i < n.length(); ++i) {
    char c = n[i];
    if (!(isalnum((unsigned char)c) || c == '_' || c == '.')) return false;
  }
  return true;
}

static String uploaded_list() {
  String out = "[";
  File dir = SD.open("/mine/layers");
  bool first = true;
  if (dir) {
    for (File f = dir.openNextFile(); f; f = dir.openNextFile()) {
      String n = f.name();
      if (n.endsWith(".wpl")) {
        if (!first) out += ",";
        out += "{\"name\":" + q(n) + ",\"bytes\":" + String((uint32_t)f.size()) + "}";
        first = false;
      }
      f.close();
    }
    dir.close();
  }
  return out + "]";
}

static void handle_state() {
  bool online = WiFi.status() == WL_CONNECTED;
  String j = "{";
  j += "\"version\":" + q(FW_VERSION) + ",";
  j += "\"setupMode\":" + String(g_setup_mode ? "true" : "false") + ",";
  j += "\"online\":" + String(online ? "true" : "false") + ",";
  j += "\"ip\":" + q(online ? WiFi.localIP().toString() : "") + ",";
  j += "\"ssid\":" + q(cfg->ssid) + ",";
  j += "\"location\":" + q(cfg->location) + ",";
  j += "\"source\":" + String(cfg->source) + ",";
  j += "\"siteUrl\":" + q(cfg->site_url) + ",";
  j += "\"defaultSite\":" + q(DEFAULT_SITE_URL) + ",";
  j += "\"autoUpdate\":" + String(cfg->auto_update ? "true" : "false") + ",";
  j += "\"refreshMinutes\":" + String(cfg->refresh_minutes) + ",";
  j += "\"canvas\":[" + String(CANVAS_W) + "," + String(CANVAS_H) + "],";
  j += "\"rotate\":" + String(CANVAS_ROTATE) + ",";
  j += "\"uploaded\":" + uploaded_list() + ",";
  j += "\"layers\":" + String(STANDARD_LAYERS);
  j += "}";
  reply(200, j);
}

static void handle_scan() {
  int n = WiFi.scanNetworks();
  String j = "[";
  for (int i = 0; i < n; ++i) {
    if (WiFi.SSID(i).length() == 0) continue;
    if (j.length() > 1) j += ",";
    j += "{\"ssid\":" + q(WiFi.SSID(i)) + ",\"rssi\":" + String(WiFi.RSSI(i)) + ",\"open\":" +
         String(WiFi.encryptionType(i) == WIFI_AUTH_OPEN ? "true" : "false") + "}";
  }
  WiFi.scanDelete();
  reply(200, j + "]");
}

static void handle_wifi() {
  String ssid = srv->arg("ssid");
  if (!ssid.length()) return fail("Choose a Wi-Fi network.");
  cfg->ssid = ssid;
  if (srv->hasArg("password")) cfg->password = srv->arg("password");
  save_settings(*cfg);
  ok();
  if (g_setup_mode) {
    // try it now, keeping the setup network up, so the page can say whether it worked
    WiFi.disconnect();
    WiFi.begin(cfg->ssid.c_str(), cfg->password.c_str());
  }
}

static void handle_location() {
  String loc = srv->arg("location");
  loc.trim();
  if (!loc.length()) return fail("Enter a city, like Cincinnati,OH,US");
  if (WiFi.status() == WL_CONNECTED) {
    Place place;
    if (!geocode(loc, place)) return fail("Couldn't find \"" + loc + "\". Try City,State,Country.");
    cfg->location = loc;
    save_settings(*cfg);
    return ok("\"found\":" + q(place.name));
  }
  cfg->location = loc;   // no internet yet (setup network): it's looked up after setup
  save_settings(*cfg);
  ok("\"found\":\"\"");
}

static void handle_painting() {
  int source = srv->arg("source").toInt();
  if (source != SOURCE_SITE && source != SOURCE_UPLOADED) return fail("Unknown painting source.");
  String url = srv->arg("siteUrl");
  url.trim();
  if (url.length() && !url.startsWith("http://") && !url.startsWith("https://"))
    return fail("The site address should start with https://");
  cfg->source = (PaintingSource)source;
  cfg->site_url = url;
  save_settings(*cfg);
  ok();
}

static void handle_options() {
  if (srv->hasArg("autoUpdate")) cfg->auto_update = srv->arg("autoUpdate") == "1";
  if (srv->hasArg("refreshMinutes")) cfg->refresh_minutes = constrain(srv->arg("refreshMinutes").toInt(), 10, 180);
  save_settings(*cfg);
  ok();
}

// one converted layer (.wpl) into /mine/layers, sent as the raw request body
// with its name in X-Name. The library reads a raw body in big blocks; a
// multipart form goes through it a byte at a time and runs at a few KB/s.
static uint8_t g_buf[16384];
static size_t g_buf_used = 0;

static void flush_upload() {
  if (g_upload && g_buf_used && g_upload.write(g_buf, g_buf_used) != g_buf_used) {
    g_upload_error = "The SD card is full or failing.";
    g_upload.close();
  }
  g_buf_used = 0;
}

static void handle_upload_data() {
  HTTPRaw &up = srv->raw();
  if (up.status == RAW_START) {
    g_upload_error = "";
    g_buf_used = 0;
    g_upload_name = srv->header("X-Name");
    if (!safe_name(g_upload_name)) { g_upload_error = "Bad file name."; return; }
    if (!SD.exists("/mine")) SD.mkdir("/mine");
    if (!SD.exists("/mine/layers")) SD.mkdir("/mine/layers");
    g_upload = SD.open("/mine/layers/" + g_upload_name + ".part", FILE_WRITE);
    if (!g_upload) g_upload_error = "Couldn't write to the SD card.";
  } else if (up.status == RAW_WRITE) {
    // gather the network's small blocks into big SD card writes
    for (size_t off = 0; off < up.currentSize && g_upload;) {
      size_t n = std::min(up.currentSize - off, sizeof g_buf - g_buf_used);
      memcpy(g_buf + g_buf_used, up.buf + off, n);
      g_buf_used += n;
      off += n;
      if (g_buf_used == sizeof g_buf) flush_upload();
    }
  } else if (up.status == RAW_END || up.status == RAW_ABORTED) {
    flush_upload();
    if (g_upload) g_upload.close();
    String part = "/mine/layers/" + g_upload_name + ".part", dest = "/mine/layers/" + g_upload_name;
    if (up.status == RAW_ABORTED) g_upload_error = "The upload was interrupted.";
    if (g_upload_error.length()) { SD.remove(part); return; }
    SD.remove(dest);
    if (!SD.rename(part, dest)) g_upload_error = "Couldn't save the file.";
  }
  g_last_request = millis();
}

static void handle_upload_done() {
  if (g_upload_error.length()) return fail(g_upload_error);
  ok("\"name\":" + q(g_upload_name));
}

static void handle_delete() {
  String name = srv->arg("name");
  if (name == "*") {
    File dir = SD.open("/mine/layers");
    std::vector<String> names;
    if (dir) {
      for (File f = dir.openNextFile(); f; f = dir.openNextFile()) { names.push_back(f.name()); f.close(); }
      dir.close();
    }
    for (auto &n : names) SD.remove("/mine/layers/" + n);
    return ok();
  }
  if (!safe_name(name)) return fail("Bad file name.");
  SD.remove("/mine/layers/" + name);
  ok();
}

static void handle_check_update() {
  if (WiFi.status() != WL_CONNECTED) return fail("Connect the frame to your Wi-Fi first.");
  String latest = latest_firmware_version();
  if (!latest.length()) return fail("Couldn't reach the update site.");
  ok("\"current\":" + q(FW_VERSION) + ",\"latest\":" + q(latest) + ",\"newer\":" + (is_newer(latest) ? "true" : "false"));
}

static void handle_install_update() {
  if (WiFi.status() != WL_CONNECTED) return fail("Connect the frame to your Wi-Fi first.");
  String error;
  if (!install_firmware_update(error)) return fail("The update failed: " + error);
  ok();
  delay(500);
  ESP.restart();
}

// a firmware .bin uploaded from the computer, as the raw request body
static void handle_firmware_data() {
  HTTPRaw &up = srv->raw();
  if (up.status == RAW_START) {
    g_upload_error = "";
    g_update_ok = false;
    if (!Update.begin(UPDATE_SIZE_UNKNOWN)) g_upload_error = Update.errorString();
  } else if (up.status == RAW_WRITE) {
    if (!g_upload_error.length() && Update.write(up.buf, up.currentSize) != up.currentSize)
      g_upload_error = Update.errorString();
  } else if (up.status == RAW_END) {
    if (!g_upload_error.length()) {
      if (Update.end(true)) g_update_ok = true;
      else g_upload_error = Update.errorString();
    }
  } else if (up.status == RAW_ABORTED) {
    Update.abort();
    g_upload_error = "The upload was interrupted.";
  }
  g_last_request = millis();
}

static void handle_firmware_done() {
  if (!g_update_ok) return fail("That file couldn't be installed: " + g_upload_error);
  ok();
  delay(500);
  ESP.restart();
}

// every request counts as activity for the idle timeout
static std::function<void()> touch(void (*f)()) {
  return [f] { g_last_request = millis(); f(); };
}

PortalExit run_portal(Settings &settings, bool setup_mode,
                      std::function<void(const String &, const String &)> show) {
  cfg = &settings;
  g_exit = false;
  g_exit_kind = PORTAL_DONE;

  if (!setup_mode) {
    WiFi.mode(WIFI_STA);
    WiFi.begin(settings.ssid.c_str(), settings.password.c_str());
    for (uint32_t t = millis(); WiFi.status() != WL_CONNECTED && millis() - t < 20000;) delay(200);
    if (WiFi.status() != WL_CONNECTED) {
      LOG.println("[portal] home Wi-Fi unreachable; opening the setup network instead");
      setup_mode = true;
    }
  }
  g_setup_mode = setup_mode;

  DNSServer dns;
  if (setup_mode) {
    WiFi.mode(WIFI_AP_STA);
    WiFi.softAP(SETUP_AP_NAME, SETUP_AP_PASSWORD);
    dns.start(53, "*", WiFi.softAPIP());   // every name leads here, so phones show the page
  }
  if (MDNS.begin(MDNS_NAME)) MDNS.addService("http", "tcp", 80);

  WebServer server(80);
  srv = &server;
  const char *headers[] = {"X-Name"};
  server.collectHeaders(headers, 1);
  server.on("/", HTTP_GET, [] { g_last_request = millis(); srv->send_P(200, "text/html; charset=utf-8", SETTINGS_PAGE); });
  server.on("/api/state", HTTP_GET, touch(handle_state));
  server.on("/api/scan", HTTP_GET, touch(handle_scan));
  server.on("/api/wifi", HTTP_POST, touch(handle_wifi));
  server.on("/api/location", HTTP_POST, touch(handle_location));
  server.on("/api/painting", HTTP_POST, touch(handle_painting));
  server.on("/api/options", HTTP_POST, touch(handle_options));
  server.on("/api/upload", HTTP_POST, touch(handle_upload_done), handle_upload_data);
  server.on("/api/delete", HTTP_POST, touch(handle_delete));
  server.on("/api/check-update", HTTP_POST, touch(handle_check_update));
  server.on("/api/install-update", HTTP_POST, touch(handle_install_update));
  server.on("/api/firmware", HTTP_POST, touch(handle_firmware_done), handle_firmware_data);
  server.on("/api/demo", HTTP_POST, [] { ok(); g_exit_kind = PORTAL_DEMO; g_exit = true; });
  server.on("/api/done", HTTP_POST, [] { ok(); g_exit_kind = PORTAL_DONE; g_exit = true; });
  server.onNotFound([] {
    if (g_setup_mode) {   // captive-portal checks and stray addresses: send them to the page
      srv->sendHeader("Location", "http://192.168.4.1/");
      srv->send(302, "text/plain", "");
    } else {
      srv->send(404, "text/plain", "Not found");
    }
  });
  server.begin();

  if (setup_mode) {
    LOG.printf("[portal] setup network %s is up: http://192.168.4.1\n", SETUP_AP_NAME);
    show("Let's set up your painting",
         "1.  On your phone, join the Wi-Fi network " SETUP_AP_NAME " (password: " SETUP_AP_PASSWORD ").\n\n"
         "2.  A setup page should open by itself. If it doesn't, go to http://192.168.4.1\n\n"
         "Press the top button on the frame when you're done.");
  } else {
    String ip = WiFi.localIP().toString();
    LOG.printf("[portal] settings at http://" MDNS_NAME ".local and http://%s\n", ip.c_str());
    show("Settings are open",
         "On a phone or computer on the " + settings.ssid + " network, go to:\n\n"
         "http://" MDNS_NAME ".local\n\nor http://" + ip + "\n\n"
         "Press the top button on the frame when you're done.");
  }

  g_last_request = millis();
  while (!g_exit) {
    if (setup_mode) dns.processNextRequest();
    server.handleClient();
    if (millis() - g_last_request > IDLE_MS) { LOG.println("[portal] idle; closing"); break; }
    if (digitalRead(PIN_TOP_BUTTON) == LOW) { LOG.println("[portal] top button; closing"); break; }
    delay(2);
  }
  delay(300);   // let the last reply go out
  server.stop();
  if (setup_mode) dns.stop();
  MDNS.end();
  srv = nullptr;
  return g_exit_kind;
}
