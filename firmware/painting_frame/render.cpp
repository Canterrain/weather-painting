#include "render.h"
#include <SD.h>
#include "wp_compose.h"

#define LOG Serial1

static const int BAND = 32;
static const uint8_t INK_CODE[WP_INKS] = {0x0, 0xF, 0x6, 0xB, 0xD, 0x2};  // white black red yellow blue green

struct OpenLayer {
  File f;
  uint16_t x, y, w, h;
  uint8_t flags, mode, solid[3];
  uint32_t *offsets = nullptr;   // h row offsets, relative to data start
  uint32_t data_start = 0, data_size = 0;
  uint8_t *buf = nullptr;
  size_t buf_cap = 0;
};

static String g_dir = "/wp";   // which painting: /wp (downloaded) or /mine (uploaded)

static bool open_layer(const String &file, OpenLayer &L) {
  L.f = SD.open(g_dir + "/layers/" + file);
  if (!L.f) return false;
  uint8_t hdr[32];
  if (L.f.read(hdr, 32) != 32 || memcmp(hdr, "WPL2", 4)) return false;
  L.x = hdr[4] | hdr[5] << 8; L.y = hdr[6] | hdr[7] << 8;
  L.w = hdr[8] | hdr[9] << 8; L.h = hdr[10] | hdr[11] << 8;
  L.flags = hdr[12]; L.mode = hdr[13];
  memcpy(L.solid, hdr + 14, 3);
  L.offsets = (uint32_t *)ps_malloc(4 * (size_t)L.h);
  if (!L.offsets || L.f.read((uint8_t *)L.offsets, 4 * L.h) != 4 * L.h) return false;
  L.data_start = 32 + 4 * L.h;
  L.data_size = L.f.size() - L.data_start;
  return true;
}

static void close_layer(OpenLayer &L) {
  if (L.f) L.f.close();
  free(L.offsets);
  free(L.buf);
}

// A layer that paints every pixel of the panel at full strength hides
// everything beneath it, so those layers needn't be read at all.
static bool covers_panel(const OpenLayer &F, const Decision &D, int W, int H) {
  return (F.flags & 2) && !(F.flags & 1) && F.x == 0 && F.y == 0 && F.w == W && F.h == H &&
         D.opacity == 255 && D.blend == WP_BLEND_NORMAL;
}

bool render_painting(const Scene &sc, const std::vector<Decision> &all, uint8_t *frame, const String &dir) {
  g_dir = dir;
  const int W = sc.width, H = sc.height;
  // find the topmost layer that covers the whole panel; start from there
  int first = 0;
  for (int i = (int)all.size() - 1; i > 0; --i) {
    OpenLayer probe;
    bool covers = open_layer(all[i].file, probe) && covers_panel(probe, all[i], W, H);
    close_layer(probe);
    if (covers) { first = i; break; }
  }
  if (first) LOG.printf("[render] skipping %d layer(s) hidden under %s\n", first, all[first].id.c_str());
  std::vector<Decision> decisions(all.begin() + first, all.end());

  const int n = decisions.size();
  std::vector<OpenLayer> files(n);
  std::vector<wp_layer> L(n > 0 ? n : 1);
  bool ok = true;
  for (int i = 0; i < n && ok; ++i) {
    if (!open_layer(decisions[i].file, files[i])) {
      LOG.printf("[render] can't open %s\n", decisions[i].file.c_str());
      ok = false;
    }
  }

  uint8_t *rgb = (uint8_t *)ps_malloc((size_t)W * BAND * 3);
  uint8_t *idx = (uint8_t *)ps_malloc((size_t)W * BAND);
  int16_t *ea = (int16_t *)ps_malloc(sizeof(int16_t) * 3 * (W + 2));
  int16_t *eb = (int16_t *)ps_malloc(sizeof(int16_t) * 3 * (W + 2));
  if (!rgb || !idx || !ea || !eb) ok = false;

  if (ok) {
    wp_tone tone;
    memcpy(tone.ink_rgb, sc.inks, sizeof(tone.ink_rgb));
    tone.saturation_q8 = sc.tone[0]; tone.contrast_q8 = sc.tone[1];
    tone.brightness_q8 = sc.tone[2]; tone.fit_to_panel = sc.tone[3];
    wp_ditherer d;
    wp_ditherer_init(&d, W, ea, eb);
    uint64_t t_read = 0, t_blend = 0, t_dither = 0;
    uint32_t bytes = 0, start = millis();

    for (int y0 = 0; y0 < H && ok; y0 += BAND) {
      int rows = min(BAND, H - y0);
      uint64_t a = micros();
      for (int i = 0; i < n; ++i) {
        OpenLayer &F = files[i];
        const Decision &D = decisions[i];
        wp_layer &l = L[i];
        memset(&l, 0, sizeof(l));
        l.x = F.x; l.y = F.y; l.w = F.w; l.h = F.h;
        l.amount = D.amount; l.feather = D.feather; l.opacity = D.opacity; l.blend = D.blend;
        l.enc_mode = F.mode; l.enc_growth = F.flags & 1;
        memcpy(l.solid, F.solid, 3);
        int top = max<int>(y0, F.y), bot = min<int>(y0 + rows, F.y + F.h);
        if (top >= bot) { l.rows_y0 = y0; l.rows_n = 0; continue; }
        uint32_t from = F.offsets[top - F.y];
        uint32_t to = (bot - F.y < F.h) ? F.offsets[bot - F.y] : F.data_size;
        size_t len = to - from;
        if (len > F.buf_cap) {
          free(F.buf);
          F.buf_cap = len + len / 4;
          F.buf = (uint8_t *)ps_malloc(F.buf_cap);
          if (!F.buf) { ok = false; break; }
        }
        F.f.seek(F.data_start + from);
        int got = F.f.read(F.buf, len);
        if (got != (int)len) {
          LOG.printf("[render] short read in %s: wanted %u bytes at %u, got %d (file is %u bytes)\n", D.file.c_str(),
                     (unsigned)len, (unsigned)(F.data_start + from), got, (unsigned)F.f.size());
          F.f.close();
          if (g_dir == "/wp") SD.remove(g_dir + "/layers/" + D.file);   // fetched again on the next wake
          ok = false;
          break;
        }
        bytes += len;
        l.enc = F.buf; l.rows_y0 = top; l.rows_n = bot - top;
      }
      if (!ok) break;
      uint64_t b = micros();
      for (int i = 0; i < rows * W; ++i) memcpy(rgb + i * 3, sc.background, 3);
      wp_compose_rows(L.data(), n, y0, rows, W, rgb);
      uint64_t c = micros();
      wp_finish_rows(&d, &tone, rgb, rows, idx);
      for (int r = 0; r < rows; ++r) {
        const uint8_t *src = idx + r * W;
        uint8_t *dst = frame + (size_t)(y0 + r) * W / 2;
        for (int x = 0; x < W; x += 2) dst[x >> 1] = (INK_CODE[src[x]] << 4) | INK_CODE[src[x + 1]];
      }
      uint64_t e = micros();
      t_read += b - a; t_blend += c - b; t_dither += e - c;
    }
    if (ok)
      LOG.printf("[render] %d layers in %.1f s: SD %.1f s (%.1f MB), blend %.1f s, dither %.1f s\n", n,
                 (millis() - start) / 1000.0, t_read / 1e6, bytes / 1e6, t_blend / 1e6, t_dither / 1e6);
  }
  for (auto &F : files) close_layer(F);
  free(rgb); free(idx); free(ea); free(eb);
  return ok;
}
