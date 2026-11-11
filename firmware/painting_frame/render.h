// Builds the painting from the SD card's layer files, a band of rows at a
// time, using the same compositor as the Mac (wp_compose.c).
#pragma once
#include <vector>
#include "rules.h"

// Reads the layers from <dir>/layers on the SD card and fills `frame`
// (width*height/2 bytes, 4bpp panel codes). Returns false on error.
bool render_painting(const Scene &scene, const std::vector<Decision> &layers, uint8_t *frame,
                     const String &dir);
