// Weather painting compositor, shared by the Mac preview tools (via ctypes)
// and the reTerminal firmware, so a preview is pixel-identical to the panel.
//
// Everything is integer maths: no floats, so results don't depend on the
// compiler or CPU.
//
// The canvas is built a band of rows at a time, so the device never needs the
// whole RGB painting in memory:
//
//   wp_ditherer_init(&d, width)
//   for each band:
//       fill rgb with the background
//       wp_compose_rows(layers, n, y0, rows, width, rgb)   // stack the layers
//       wp_finish_rows(&d, &tone, rgb, rows, out_idx)      // tone + dither
#pragma once
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define WP_INKS 6
#define WP_BLEND_NORMAL   0
#define WP_BLEND_MULTIPLY 1

// How encoded (.wpl v2) rows store their pixels.
#define WP_ENC_RGBA  0       // 4 bytes per painted pixel
#define WP_ENC_RGB   1       // 3 bytes, every painted pixel fully opaque
#define WP_ENC_ALPHA 2       // 1 byte: one color (`solid`) at varying opacity

// One layer's pixels available for this band, either as plain RGBA rows
// (`rgba`) or as encoded rows (`enc`, see painter/wpl.py):
//   per row: u16 nspans, nspans x (u16 x, u16 len), span pixels, [span growth bytes]
typedef struct {
    const uint8_t *rgba;     // RGBA8888 rows of the layer, starting at canvas row `rows_y0`
    const uint8_t *growth;   // optional growth (reveal) map, 1 byte per pixel, same rows; NULL = none
    const uint8_t *enc;      // encoded rows starting at canvas row `rows_y0`; used instead of rgba/growth
    uint8_t enc_mode;        // WP_ENC_*
    uint8_t enc_growth;      // encoded rows carry growth bytes
    uint8_t solid[3];        // color for WP_ENC_ALPHA
    int32_t x, y, w, h;      // where the whole layer sits on the canvas
    int32_t rows_y0;         // canvas row of rgba[0] (and growth[0])
    int32_t rows_n;          // how many rows the buffers hold
    uint16_t amount;         // 0..65535  (reveal amount)
    uint16_t feather;        // 1..65535  (reveal edge softness)
    uint8_t opacity;         // 0..255
    uint8_t blend;           // WP_BLEND_*
} wp_layer;

typedef struct {
    uint8_t ink_rgb[WP_INKS][3]; // what each ink looks like (index 0 = white, 1 = black)
    int16_t saturation_q8;       // 256 = unchanged
    int16_t contrast_q8;         // 256 = unchanged (pivot 128)
    int16_t brightness_q8;       // 256 = unchanged
    uint8_t fit_to_panel;        // map 0..255 onto the panel's black..white
} wp_tone;

typedef struct {
    int32_t width;
    int16_t *err_cur;            // 3 * (width + 2)
    int16_t *err_next;           // 3 * (width + 2)
} wp_ditherer;

// Stack layers onto rows [y0, y0 + rows) of `rgb` (RGB888, `width` wide).
void wp_compose_rows(const wp_layer *layers, int nlayers, int y0, int rows, int width, uint8_t *rgb);

// Tone-map and Floyd-Steinberg dither rows into ink indices (0..5).
// Rows must be fed in order, top to bottom, through the same ditherer.
void wp_finish_rows(wp_ditherer *d, const wp_tone *tone, uint8_t *rgb, int rows, uint8_t *out_idx);

// The ditherer's buffers are supplied by the caller (malloc / ps_malloc / numpy).
void wp_ditherer_init(wp_ditherer *d, int width, int16_t *buf_a, int16_t *buf_b);

#ifdef __cplusplus
}
#endif
