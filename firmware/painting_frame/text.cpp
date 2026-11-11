#include "text.h"
#include <string.h>

static void set_px(const Canvas &c, int x, int y, uint8_t ink) {
  int W = c.width(), H = c.height();
  if (x < 0 || y < 0 || x >= W || y >= H) return;
  int px, py;   // painting -> panel, the same turn publish gives the layers
  switch (c.rotate) {
    case 90:  px = c.panel_w - 1 - y; py = x; break;
    case 180: px = c.panel_w - 1 - x; py = c.panel_h - 1 - y; break;
    case 270: px = y; py = c.panel_h - 1 - x; break;
    default:  px = x; py = y; break;
  }
  uint8_t &b = c.frame[(py * c.panel_w + px) >> 1];
  b = (px & 1) ? (b & 0xF0) | ink : (b & 0x0F) | (ink << 4);
}

void canvas_fill(const Canvas &c, int x, int y, int w, int h, uint8_t ink) {
  for (int j = y; j < y + h; ++j)
    for (int i = x; i < x + w; ++i) set_px(c, i, j, ink);
}

static const GFXglyph *glyph(const GFXfont *f, char ch) {
  uint8_t u = (uint8_t)ch;
  if (u < f->first || u > f->last) u = '?';
  return &f->glyph[u - f->first];
}

int text_width(const GFXfont *font, const char *s, int scale) {
  int w = 0;
  for (; *s; ++s) w += glyph(font, *s)->xAdvance * scale;
  return w;
}

int draw_text(const Canvas &c, const GFXfont *font, int x, int y, const char *s, uint8_t ink, int scale) {
  for (; *s; ++s) {
    const GFXglyph *g = glyph(font, *s);
    const uint8_t *bits = font->bitmap + g->bitmapOffset;
    int bit = 0;
    for (int gy = 0; gy < g->height; ++gy)
      for (int gx = 0; gx < g->width; ++gx, ++bit)
        if (bits[bit >> 3] & (0x80 >> (bit & 7)))
          for (int sy = 0; sy < scale; ++sy)
            for (int sx = 0; sx < scale; ++sx)
              set_px(c, x + (g->xOffset + gx) * scale + sx, y + (g->yOffset + gy) * scale + sy, ink);
    x += g->xAdvance * scale;
  }
  return x;
}

int draw_paragraph(const Canvas &c, const GFXfont *font, int x, int y_top, int max_w, const char *s,
                   uint8_t ink, int scale) {
  int line_h = font->yAdvance * scale;
  int y = y_top + line_h * 3 / 4;   // first baseline
  char line[256];
  size_t len = 0;
  const char *p = s;
  while (*p) {
    // next word, with the space before it
    const char *w = p;
    while (*w == ' ') ++w;
    const char *e = w;
    while (*e && *e != ' ' && *e != '\n') ++e;
    char trial[256];
    size_t tl = 0;
    if (len) { memcpy(trial, line, len); tl = len; trial[tl++] = ' '; }
    size_t wl = (size_t)(e - w) < sizeof(trial) - tl - 1 ? (size_t)(e - w) : sizeof(trial) - tl - 1;
    memcpy(trial + tl, w, wl);
    trial[tl + wl] = 0;
    if (len && text_width(font, trial, scale) > max_w) {
      line[len] = 0;
      draw_text(c, font, x, y, line, ink, scale);
      y += line_h;
      len = 0;
      continue;   // the word starts the next line
    }
    memcpy(line, trial, tl + wl);
    len = tl + wl;
    p = e;
    if (*p == '\n') {
      line[len] = 0;
      draw_text(c, font, x, y, line, ink, scale);
      y += line_h;
      len = 0;
      ++p;
    }
  }
  if (len) { line[len] = 0; draw_text(c, font, x, y, line, ink, scale); y += line_h; }
  return y - line_h * 3 / 4;
}
