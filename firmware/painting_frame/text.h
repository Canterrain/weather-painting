// Text and boxes drawn straight into a packed 4bpp panel frame, in the
// painting's own (landscape) coordinates, for captions and setup screens.
#pragma once
#include <stdint.h>
#ifdef ARDUINO
#include "TFT_eSPI.h"   // brings the GFX free fonts (LOAD_GFXFF in the board setup)
#else
#include <Fonts/GFXFF/gfxfont.h>
#endif

// panel ink codes
enum : uint8_t { INK_WHITE = 0x0, INK_BLACK = 0xF, INK_RED = 0x6, INK_YELLOW = 0xB, INK_BLUE = 0xD, INK_GREEN = 0x2 };

struct Canvas {
  uint8_t *frame;    // panel_w * panel_h / 2 bytes, left pixel in the high nibble
  int panel_w, panel_h;
  int rotate;        // display rotation, same as publish (0, 90, 180, 270)
  int width() const { return rotate % 180 ? panel_h : panel_w; }
  int height() const { return rotate % 180 ? panel_w : panel_h; }
};

void canvas_fill(const Canvas &c, int x, int y, int w, int h, uint8_t ink);
int text_width(const GFXfont *font, const char *s, int scale = 1);
// Draws one line; y is the baseline. Returns the x after the text.
int draw_text(const Canvas &c, const GFXfont *font, int x, int y, const char *s, uint8_t ink, int scale = 1);
// Word-wraps `s` to max_w; y_top is the top of the first line. Returns the
// y just below the last line.
int draw_paragraph(const Canvas &c, const GFXfont *font, int x, int y_top, int max_w, const char *s,
                   uint8_t ink, int scale = 1);
