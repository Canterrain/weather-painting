// Weather painting, standalone: the reTerminal does everything itself.
//
// Each wake: Wi-Fi -> time -> sync layers/rules from the painting's site ->
// weather from Open-Meteo -> decide layers -> rebuild + redraw only if the
// painting changed -> deep sleep.
//
// The front buttons (frame hung with them on the right), top to bottom:
//   top     redraw now; in the demo, back to the weather; in settings, close
//   middle  demo: every season x weather in turn; in the demo, skip a season
//   bottom  settings page (Wi-Fi, city, painting, updates)
//
// With no Wi-Fi saved, the frame opens its setup network instead (portal.h).
//
// Board: XIAO_ESP32S3, Tools > PSRAM > OPI PSRAM. Libraries: Seeed_GFX, ArduinoJson.

#include <WiFi.h>
#include <SPI.h>
#include <SD.h>
#include <Preferences.h>
#include <time.h>
#include "esp_sleep.h"
#include "TFT_eSPI.h"
#include "demo.h"
#include "generated.h"
#include "ota.h"
#include "portal.h"
#include "render.h"
#include "rules.h"
#include "screens.h"
#include "settings.h"
#include "sync.h"
#include "version.h"
#include "weather.h"

#ifndef EPAPER_ENABLE
#error "driver.h must select BOARD_SCREEN_COMBO 523 (reTerminal E1004)"
#endif

#define LOG Serial1
static constexpr int PIN_SD_EN = 16, PIN_SD_DET = 15, PIN_SD_CS = 14;
static constexpr int BUS_SCK = 7, BUS_MISO = 8, BUS_MOSI = 9;
static constexpr int BTN_TOP = 3, BTN_MIDDLE = 4, BTN_BOTTOM = 5;
static constexpr uint64_t WAKE_BUTTONS = (1ULL << BTN_TOP) | (1ULL << BTN_MIDDLE) | (1ULL << BTN_BOTTOM);
static constexpr uint32_t DAY = 24 * 3600;

EPaper epaper;
static Settings settings;

RTC_DATA_ATTR uint32_t g_signature = 0;   // what's on the panel now
RTC_DATA_ATTR uint32_t g_failures = 0;
RTC_DATA_ATTR int32_t g_demo = -1;        // demo case on the panel, -1 = showing the weather
RTC_DATA_ATTR uint32_t g_notice = 0;      // which problem screen is up, so it's drawn once
RTC_DATA_ATTR int32_t g_pending = 0;      // a button pressed while busy, handled on the next wake

// Presses while awake are caught by an interrupt, so they count even in the
// middle of a redraw.
static volatile int g_pressed = 0;
static void IRAM_ATTR on_press(void *pin) {
  if (!g_pressed) g_pressed = (int)(intptr_t)pin;
}

static uint32_t fnv(uint32_t h, const String &s) {
  for (size_t i = 0; i < s.length(); ++i) { h ^= (uint8_t)s[i]; h *= 16777619u; }
  return h;
}

static bool any_button_down() {
  return digitalRead(BTN_TOP) == LOW || digitalRead(BTN_MIDDLE) == LOW || digitalRead(BTN_BOTTOM) == LOW;
}

static void sleep_for(uint32_t seconds) {
  while (any_button_down()) delay(20);
  WiFi.disconnect(true);
  WiFi.mode(WIFI_OFF);
  if (g_pressed) {   // pressed while we were busy: wake straight up to handle it
    g_pending = g_pressed;
    seconds = 1;
  }
  LOG.printf("sleeping %u s\n", (unsigned)seconds);
  LOG.flush();
  esp_sleep_enable_timer_wakeup((uint64_t)seconds * 1000000ULL);
  esp_sleep_enable_ext1_wakeup(WAKE_BUTTONS, ESP_EXT1_WAKEUP_ANY_LOW);
  esp_deep_sleep_start();
}

// ---- the panel --------------------------------------------------------------

static uint8_t *new_frame() {
  uint8_t *f = (uint8_t *)ps_malloc((size_t)EPD_WIDTH * EPD_HEIGHT / 2);
  if (!f) { LOG.println("!! out of memory"); sleep_for(60); }
  return f;
}

static Canvas canvas_for(uint8_t *frame) { return Canvas{frame, EPD_WIDTH, EPD_HEIGHT, CANVAS_ROTATE}; }

static void push(uint8_t *frame) {
  uint32_t t = millis();
  epaper.pushImage(0, 0, EPD_WIDTH, EPD_HEIGHT, (uint16_t *)frame);
  epaper.update();
  epaper.sleep();
  LOG.printf("panel refreshed in %.1f s\n", (millis() - t) / 1000.0);
}

static void show_screen(const String &title, const String &body) {
  uint8_t *frame = new_frame();
  draw_screen(canvas_for(frame), title.c_str(), body.c_str());
  push(frame);
  free(frame);
  g_signature = 0;   // the painting is redrawn next time
}

// A problem worth telling the owner about: shown once, then the frame tries
// again later.
static void fail_and_sleep(const char *why, const char *title = nullptr, const String &body = "") {
  LOG.printf("!! %s\n", why);
  g_failures++;
  if (title) {
    uint32_t id = fnv(2166136261u, why);
    if (g_notice != id) {
      show_screen(title, body);
      g_notice = id;
    }
  }
  uint32_t mins = min<uint32_t>(5u << min<uint32_t>(g_failures - 1, 3), settings.refresh_minutes);
  sleep_for(mins * 60);
}

// ---- network ----------------------------------------------------------------

static bool connect_wifi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(settings.ssid.c_str(), settings.password.c_str());
  uint32_t t = millis();
  while (WiFi.status() != WL_CONNECTED) {
    if (millis() - t > 20000) return false;
    delay(200);
  }
  return true;
}

static bool sync_clock() {
  configTime(0, 0, "pool.ntp.org", "time.google.com");
  uint32_t t = millis();
  while (time(nullptr) < 1700000000) {
    if (millis() - t > 15000) return false;
    delay(100);
  }
  return true;
}

static bool load_place(Place &place) {
  Preferences prefs;
  prefs.begin("painting", false);
  String saved = prefs.getString("loc", "");
  if (saved == settings.location) {
    place.lat = prefs.getDouble("lat", 0);
    place.lon = prefs.getDouble("lon", 0);
    place.name = prefs.getString("name", "");
    prefs.end();
    return true;
  }
  bool ok = geocode(settings.location, place);
  if (ok) {
    prefs.putString("loc", settings.location);
    prefs.putDouble("lat", place.lat);
    prefs.putDouble("lon", place.lon);
    prefs.putString("name", place.name);
  }
  prefs.end();
  return ok;
}

// Once a day, if allowed: install newer firmware from the project site.
static void maybe_update_firmware() {
  if (!settings.auto_update) return;
  Preferences prefs;
  prefs.begin("painting", false);
  uint32_t now = time(nullptr), last = prefs.getUInt("ota_t", 0);
  if (now - last < DAY) { prefs.end(); return; }
  prefs.putUInt("ota_t", now);
  prefs.end();
  String latest = latest_firmware_version();
  LOG.printf("[ota] this is %s, the site has %s\n", FW_VERSION, latest.length() ? latest.c_str() : "(unreachable)");
  if (!is_newer(latest)) return;
  String error;
  if (install_firmware_update(error)) ESP.restart();
}

// ---- the painting -------------------------------------------------------------

static String painting_dir() { return settings.source == SOURCE_UPLOADED ? "/mine" : "/wp"; }

static bool read_text(const String &path, String &out) {
  File f = SD.open(path);
  if (!f) return false;
  out = f.readString();
  f.close();
  return true;
}

static bool load_scene(Scene &scene) {
  if (settings.source == SOURCE_UPLOADED) return parse_scene(STANDARD_SCENE, scene);
  String text;
  return read_text("/wp/scene.txt", text) && parse_scene(text, scene);
}

// Uploaded paintings don't have every layer; leave out the ones that aren't there.
static std::vector<Decision> present(const std::vector<Decision> &all, const String &dir) {
  std::vector<Decision> out;
  for (auto &d : all)
    if (SD.exists(dir + "/layers/" + d.file)) out.push_back(d);
  return out;
}

static void build_and_show(const Scene &scene, const std::vector<Decision> &layers, const String &caption = "") {
  uint8_t *frame = new_frame();
  if (!render_painting(scene, layers, frame, painting_dir())) {
    free(frame);
    fail_and_sleep("couldn't build the painting");
  }
  if (caption.length()) draw_caption(canvas_for(frame), caption.c_str());
  push(frame);
  free(frame);
  g_notice = 0;
}

// ---- settings and demo ----------------------------------------------------------

static void run_demo(bool starting);

static void open_settings(bool setup_mode) {
  WiFi.disconnect(true);
  PortalExit how = run_portal(settings, setup_mode, show_screen);
  g_notice = 0;
  g_signature = 0;
  if (how == PORTAL_DEMO) {
    g_demo = 0;
    run_demo(true);
  }
  g_demo = -1;
  ESP.restart();   // a fresh start with the new settings draws the painting
}

static void run_demo(bool starting) {
  // fetch the latest painting when the demo starts; after that everything
  // comes from the SD card
  if (starting && settings.source == SOURCE_SITE && connect_wifi() && sync_clock()) {
    bool changed = false;
    sync_site(settings.painting_url(), changed);
  }
  WiFi.disconnect(true);
  WiFi.mode(WIFI_OFF);
  Scene scene;
  if (!load_scene(scene)) {
    g_demo = -1;
    fail_and_sleep("no painting on the SD card");
  }
  g_signature = 0;   // the weather painting gets redrawn when the demo ends
  int count = demo_count();
  g_pressed = 0;

  while (true) {
    State state;
    String title;
    String season = load_demo_case(g_demo, state, title);
    g_demo = ((g_demo % count) + count) % count;
    LOG.printf("demo %d/%d: %s\n", (int)g_demo + 1, count, title.c_str());
    std::vector<Decision> layers = present(decide(scene, state), painting_dir());
    build_and_show(scene, layers, "Demo " + String(g_demo + 1) + "/" + String(count) + "   " + title);

    int pressed = g_pressed;
    g_pressed = 0;
    if (pressed == BTN_TOP) {
      LOG.println("leaving demo mode");
      g_demo = -1;
      ESP.restart();   // back to the weather, redrawn
    } else if (pressed == BTN_BOTTOM) {
      g_demo = -1;
      open_settings(false);
    } else if (pressed == BTN_MIDDLE) {
      // skip to the first case of the next season
      int i = g_demo + 1;
      for (; i < g_demo + count; ++i) {
        State s;
        String t;
        if (load_demo_case(i, s, t) != season) break;
      }
      g_demo = i;
    } else {
      g_demo++;
    }
  }
}

// ---- wake -----------------------------------------------------------------------

void setup() {
  LOG.begin(115200, SERIAL_8N1, 44, 43);
  for (int pin : {BTN_TOP, BTN_MIDDLE, BTN_BOTTOM}) pinMode(pin, INPUT);
  esp_sleep_wakeup_cause_t cause = esp_sleep_get_wakeup_cause();
  int button = 0;
  if (cause == ESP_SLEEP_WAKEUP_EXT1) {
    uint64_t pins = esp_sleep_get_ext1_wakeup_status();
    for (int pin : {BTN_TOP, BTN_MIDDLE, BTN_BOTTOM}) if (pins & (1ULL << pin)) button = pin;
  } else if (g_pending) {
    button = g_pending;
  }
  g_pending = 0;
  bool force = button || cause == ESP_SLEEP_WAKEUP_UNDEFINED;
  LOG.printf("\n== weather painting %s (wake %d, button %d) ==\n", FW_VERSION, (int)cause, button);
  for (int pin : {BTN_TOP, BTN_MIDDLE, BTN_BOTTOM})
    attachInterruptArg(pin, on_press, (void *)(intptr_t)pin, FALLING);
  while (any_button_down()) delay(20);   // the press that woke us isn't a new one
  g_pressed = 0;

  load_settings(settings);

  pinMode(PIN_SD_EN, OUTPUT); digitalWrite(PIN_SD_EN, HIGH);
  pinMode(PIN_SD_DET, INPUT_PULLUP);
  delay(50);
  epaper.begin();
  SPIClass &spi = epaper.getSPIinstance();
  spi.end();
  spi.begin(BUS_SCK, BUS_MISO, BUS_MOSI, -1);
  if (!SD.begin(PIN_SD_CS, spi, 40000000, "/sd", 32))
    fail_and_sleep("no SD card", "No memory card",
                   "The frame keeps the painting on a microSD card, and it can't find one.\n\n"
                   "Check that the card is pushed all the way in, then press the top button.");
  if (!SD.exists("/wp")) SD.mkdir("/wp");

  if (!settings.has_wifi()) open_settings(true);
  if (button == BTN_BOTTOM) open_settings(false);
  if (button == BTN_MIDDLE && g_demo < 0) { g_demo = 0; run_demo(true); }
  if (g_demo >= 0) run_demo(false);   // e.g. woke up after a failure mid-demo
  if (!settings.location.length()) open_settings(false);

  if (!connect_wifi())
    fail_and_sleep("Wi-Fi didn't connect", "Can't reach the Wi-Fi",
                   "The frame couldn't connect to " + settings.ssid + ". It keeps trying.\n\n"
                   "To change the network or password, press the bottom button and follow the steps.");
  if (!sync_clock()) fail_and_sleep("couldn't get the time");
  maybe_update_firmware();

  String version = "uploaded";
  if (settings.source == SOURCE_SITE) {
    bool site_changed = false;
    version = sync_site(settings.painting_url(), site_changed);
  }
  Scene scene;
  if (!load_scene(scene))
    fail_and_sleep("no painting yet", "No painting yet",
                   "The frame couldn't download its painting from " + settings.painting_url() + "\n\n"
                   "It keeps trying. To choose another painting, press the bottom button.");

  Place place;
  if (!load_place(place))
    fail_and_sleep("couldn't look up the location", "Can't find your city",
                   "The frame couldn't find \"" + settings.location + "\".\n\n"
                   "Press the bottom button to open settings and enter it as City,State,Country.");
  LOG.printf("location %s (%.3f, %.3f)\n", place.name.c_str(), place.lat, place.lon);

  State state;
  double now = (double)time(nullptr);
  if (!fetch_state(place, now, state)) fail_and_sleep("weather fetch failed");
  WiFi.disconnect(true);
  WiFi.mode(WIFI_OFF);
  g_failures = 0;
  state.print(LOG);

  std::vector<Decision> layers = present(decide(scene, state), painting_dir());
  if (layers.empty())
    fail_and_sleep("no layers", "No painting yet",
                   "My own painting is chosen, but no layers are uploaded.\n\n"
                   "Press the bottom button to open settings and upload them.");
  uint32_t sig = fnv(fnv(2166136261u, version), painting_dir());
  LOG.printf("%d layers:", (int)layers.size());
  for (auto &d : layers) {
    LOG.printf(" %s", d.id.c_str());
    if (d.amount < 65535) LOG.printf("(%.2f)", d.amount / 65535.0);
    sig = fnv(sig, d.file + ":" + d.amount + ":" + d.opacity);
  }
  LOG.println();

  const StateValue *raining = state.get("is_raining"), *snowing = state.get("is_snowing");
  bool active = (raining && raining->num) || (snowing && snowing->num);
  uint32_t next = (active ? settings.refresh_minutes / 2 : settings.refresh_minutes) * 60;

  if (!force && sig == g_signature) {
    LOG.println("painting unchanged");
    sleep_for(next);
  }
  build_and_show(scene, layers);
  g_signature = sig;
  sleep_for(next);
}

void loop() {}
