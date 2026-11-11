#include "settings.h"
#include <Preferences.h>
#include "version.h"

#if __has_include("config.h")
#include "config.h"
#endif

String Settings::painting_url() const {
  String url = site_url.length() ? site_url : String(DEFAULT_SITE_URL);
  return url.endsWith("/") ? url : url + "/";
}

void load_settings(Settings &s) {
  Preferences p;
  p.begin("painting", true);
  bool fresh = !p.isKey("ver");
  s.ssid = p.getString("ssid", "");
  s.password = p.getString("pass", "");
  s.location = p.getString("city", "");
  s.source = (PaintingSource)p.getUChar("source", SOURCE_SITE);
  s.site_url = p.getString("site", "");
  s.auto_update = p.getBool("autoupd", true);
  s.refresh_minutes = p.getUChar("refresh", 30);
  p.end();
  if (!fresh) return;
#ifdef WIFI_SSID
  s.ssid = WIFI_SSID;
  s.password = WIFI_PASSWORD;
#endif
#ifdef LOCATION
  s.location = LOCATION;
#endif
#ifdef SITE_URL
  s.site_url = SITE_URL;
#endif
#ifdef REFRESH_MINUTES
  s.refresh_minutes = REFRESH_MINUTES;
#endif
  save_settings(s);
}

void save_settings(const Settings &s) {
  Preferences p;
  p.begin("painting", false);
  p.putUChar("ver", 1);
  p.putString("ssid", s.ssid);
  p.putString("pass", s.password);
  p.putString("city", s.location);
  p.putUChar("source", s.source);
  p.putString("site", s.site_url);
  p.putBool("autoupd", s.auto_update);
  p.putUChar("refresh", s.refresh_minutes);
  p.end();
}
