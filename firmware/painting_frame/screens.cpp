#include "screens.h"
#include <string.h>

static const int MARGIN = 110;

void draw_screen(const Canvas &c, const char *title, const char *body) {
  canvas_fill(c, 0, 0, c.width(), c.height(), INK_WHITE);
  canvas_fill(c, MARGIN, MARGIN, 160, 12, INK_BLUE);
  int y = draw_paragraph(c, &FreeSansBold24pt7b, MARGIN, MARGIN + 50, c.width() - 2 * MARGIN, title, INK_BLACK, 2);
  y += 40;
  // paragraphs separated by blank lines
  const char *p = body;
  char para[512];
  while (*p) {
    const char *end = strstr(p, "\n\n");
    size_t n = end ? (size_t)(end - p) : strlen(p);
    if (n >= sizeof(para)) n = sizeof(para) - 1;
    memcpy(para, p, n);
    para[n] = 0;
    y = draw_paragraph(c, &FreeSans24pt7b, MARGIN, y, c.width() - 2 * MARGIN, para, INK_BLACK) + 36;
    if (!end) break;
    p = end + 2;
  }
}

void draw_caption(const Canvas &c, const char *text) {
  const GFXfont *f = &FreeSansBold18pt7b;
  int pad = 18, w = text_width(f, text) + 2 * pad, h = f->yAdvance + 2 * pad;
  int x = 30, y = c.height() - h - 30;
  canvas_fill(c, x, y, w, h, INK_BLACK);
  canvas_fill(c, x + 4, y + 4, w - 8, h - 8, INK_WHITE);
  draw_text(c, f, x + pad, y + pad + f->yAdvance * 3 / 4, text, INK_BLACK);
}
