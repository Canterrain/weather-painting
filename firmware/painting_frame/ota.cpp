#include "ota.h"
#include <HTTPClient.h>
#include <HTTPUpdate.h>
#include <WiFiClientSecure.h>
#include "version.h"

#define LOG Serial1

String latest_firmware_version() {
  WiFiClientSecure tls;
  tls.setInsecure();   // the image is checked by the bootloader; the site is public
  HTTPClient http;
  http.setConnectTimeout(10000);
  if (!http.begin(tls, FIRMWARE_URL "version.txt")) return "";
  String v;
  if (http.GET() == 200) v = http.getString();
  http.end();
  v.trim();
  return v;
}

static void parse(const String &v, int out[3]) {
  out[0] = out[1] = out[2] = 0;
  int part = 0;
  for (size_t i = 0; i < v.length() && part < 3; ++i) {
    char c = v[i];
    if (c >= '0' && c <= '9') out[part] = out[part] * 10 + (c - '0');
    else if (c == '.') ++part;
    else break;   // "-preview" and so on
  }
}

bool is_newer(const String &latest) {
  if (!latest.length()) return false;
  int a[3], b[3];
  parse(latest, a);
  parse(FW_VERSION, b);
  for (int i = 0; i < 3; ++i)
    if (a[i] != b[i]) return a[i] > b[i];
  return false;
}

bool install_firmware_update(String &error) {
  WiFiClientSecure tls;
  tls.setInsecure();
  HTTPUpdate updater;
  updater.rebootOnUpdate(false);
  updater.setFollowRedirects(HTTPC_FORCE_FOLLOW_REDIRECTS);
  LOG.println("[ota] downloading " FIRMWARE_URL "firmware.bin");
  t_httpUpdate_return r = updater.update(tls, FIRMWARE_URL "firmware.bin");
  if (r == HTTP_UPDATE_OK) {
    LOG.println("[ota] installed; restarting");
    return true;
  }
  error = updater.getLastErrorString();
  LOG.printf("[ota] failed: %s\n", error.c_str());
  return false;
}
