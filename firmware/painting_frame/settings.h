// What the owner sets on the settings page, kept in flash (Preferences).
//
// For development, an optional config.h (not in git; see config.example.h)
// can pre-fill these the first time the firmware runs on a board.
#pragma once
#include <Arduino.h>

enum PaintingSource : uint8_t {
  SOURCE_SITE = 0,      // download from a site: the default painting, or site_url if set
  SOURCE_UPLOADED = 1,  // layers uploaded from the settings page (/mine on the SD card)
};

struct Settings {
  String ssid, password;
  String location;            // e.g. "Cincinnati,OH,US"
  PaintingSource source = SOURCE_SITE;
  String site_url;            // empty = DEFAULT_SITE_URL
  bool auto_update = true;    // install new firmware by itself
  uint8_t refresh_minutes = 30;

  String painting_url() const;
  bool has_wifi() const { return ssid.length() > 0; }
};

void load_settings(Settings &s);
void save_settings(const Settings &s);
