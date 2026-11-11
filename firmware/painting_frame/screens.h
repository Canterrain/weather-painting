// Full-panel text screens (setup, settings, problems) and the demo caption,
// drawn into a panel frame with text.h.
#pragma once
#include "text.h"

// A white screen with a large title and body text. In the body, "\n" starts
// a new line and "\n\n" leaves a gap.
void draw_screen(const Canvas &c, const char *title, const char *body);

// A boxed label in the bottom-left corner, over the painting.
void draw_caption(const Canvas &c, const char *text);
