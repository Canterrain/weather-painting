#include "sync.h"
#include <WiFi.h>
#include <HTTPClient.h>
#include <SD.h>
#include <WiFiClientSecure.h>
#include <map>

#define LOG Serial1

struct Entry { uint32_t size; String sha; };

static String read_file(const char *path) {
  File f = SD.open(path);
  if (!f) return "";
  String s = f.readString();
  f.close();
  return s;
}

// "WPM1 <version>\nfile <path> <size> <sha>\n..." -> version, entries
static String parse_manifest(const String &text, std::map<String, Entry> &out) {
  String version;
  int pos = 0;
  while (pos < (int)text.length()) {
    int end = text.indexOf('\n', pos);
    if (end < 0) end = text.length();
    String line = text.substring(pos, end);
    pos = end + 1;
    if (line.startsWith("WPM1 ")) version = line.substring(5);
    else if (line.startsWith("file ")) {
      int a = line.indexOf(' ', 5), b = line.indexOf(' ', a + 1);
      if (a < 0 || b < 0) continue;
      out[line.substring(5, a)] = Entry{(uint32_t)line.substring(a + 1, b).toInt(), line.substring(b + 1)};
    }
  }
  version.trim();
  return version;
}

static bool begin(HTTPClient &http, WiFiClientSecure &tls, const String &url) {
  http.setConnectTimeout(10000);
  http.setTimeout(20000);
  http.setFollowRedirects(HTTPC_STRICT_FOLLOW_REDIRECTS);   // GitHub release files redirect to storage
  if (url.startsWith("https")) { tls.setInsecure(); return http.begin(tls, url); }
  return http.begin(url);
}

static bool fetch_text(const String &url, String &out) {
  HTTPClient http;
  WiFiClientSecure tls;
  if (!begin(http, tls, url)) return false;
  int code = http.GET();
  if (code == 200) out = http.getString();
  http.end();
  return code == 200;
}

static void ensure_dirs(const String &path) {
  for (int i = 1; i < (int)path.length(); ++i)
    if (path[i] == '/') { String d = path.substring(0, i); if (!SD.exists(d)) SD.mkdir(d); }
}

static bool download(const String &url, const String &dest, uint32_t size) {
  HTTPClient http;
  WiFiClientSecure tls;
  if (!begin(http, tls, url)) return false;
  if (http.GET() != 200) { http.end(); return false; }
  String tmp = dest + ".part";
  ensure_dirs(dest);
  File out = SD.open(tmp, FILE_WRITE);
  if (!out) { http.end(); return false; }
  WiFiClient *s = http.getStreamPtr();
  static uint8_t buf[16384];
  uint32_t got = 0, last = millis();
  while (got < size && millis() - last < 20000) {
    int n = s->read(buf, min<uint32_t>(sizeof(buf), size - got));
    if (n > 0) {
      if (out.write(buf, n) != (size_t)n) { LOG.printf("[sync] SD write failed in %s\n", dest.c_str()); break; }
      got += n;
      last = millis();
    } else delay(1);
  }
  out.close();
  http.end();
  File check = SD.open(tmp);
  uint32_t on_card = check ? check.size() : 0;
  if (check) check.close();
  if (got != size || on_card != size) {
    LOG.printf("[sync] %s: got %u, on card %u, expected %u\n", dest.c_str(), got, on_card, size);
    SD.remove(tmp);
    return false;
  }
  SD.remove(dest);
  return SD.rename(tmp, dest);
}

// A GitHub release (the gallery) keeps its files side by side, not in
// folders, so a painting there has layers/x.wpl as x.wpl.
static String remote_path(const String &base, const String &rel) {
  if (base.indexOf("/releases/download/") < 0) return rel;
  return rel.substring(rel.lastIndexOf('/') + 1);
}

String sync_site(const String &base_url, bool &changed) {
  changed = false;
  String base = base_url.endsWith("/") ? base_url : base_url + "/";
  String local_text = read_file("/wp/manifest.txt");
  std::map<String, Entry> local, remote;
  String local_version = parse_manifest(local_text, local);

  String remote_text;
  if (!fetch_text(base + "manifest.txt", remote_text)) {
    LOG.println("[sync] couldn't reach the site; using what's on the card");
    return local_version;
  }
  String remote_version = parse_manifest(remote_text, remote);
  if (remote_version.length() == 0) return local_version;
  // Even when the version matches, every file is checked (present, right
  // size), so a damaged or deleted file is fetched again.
  if (remote_version != local_version)
    LOG.printf("[sync] new version %s (card has %s)\n", remote_version.c_str(),
               local_version.length() ? local_version.c_str() : "nothing");
  uint32_t t0 = millis(), bytes = 0;
  for (auto &kv : remote) {
    const String &rel = kv.first;
    String dest = "/wp/" + rel;
    auto it = local.find(rel);
    bool same = it != local.end() && it->second.sha == kv.second.sha;
    if (same) {
      File f = SD.open(dest);
      same = f && f.size() == kv.second.size;
      if (f) f.close();
    }
    if (same) continue;
    uint32_t t = millis();
    if (!download(base + remote_path(base, rel), dest, kv.second.size)) {
      LOG.printf("[sync] download of %s failed; will retry next time\n", rel.c_str());
      return local_version;   // keep the old manifest, so the next wake tries again
    }
    bytes += kv.second.size;
    LOG.printf("[sync]   %-40s %6.2f MB in %4.1f s\n", rel.c_str(), kv.second.size / 1e6, (millis() - t) / 1000.0);
  }
  if (remote_version != local_version) {
    File m = SD.open("/wp/manifest.txt", FILE_WRITE);
    if (m) { m.print(remote_text); m.close(); }
  }
  if (bytes) {
    LOG.printf("[sync] %.1f MB in %.1f s\n", bytes / 1e6, (millis() - t0) / 1000.0);
    changed = true;
  }
  return remote_version;
}
