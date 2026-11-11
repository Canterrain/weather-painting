// scene.txt (from `python -m painter publish`) and the rule machine that
// decides which layers to draw. Mirrors painter/rules.py and
// painter/publish.py's decide(), which publishing checks against the Mac renderer.
#pragma once
#include <Arduino.h>
#include <vector>
#include "state.h"

struct SceneLayer {
  String id;
  uint8_t blend = 0;
  int steps = 10;
  uint16_t feather = 3932;
  bool has_growth = false;
  String file;                                  // single image, or
  std::vector<std::pair<double, String>> stages;  // swapped by amount
  std::vector<String> when, amount, opacity;    // compiled tokens
};

struct Scene {
  int width = 1200, height = 1600;
  uint8_t background[3] = {255, 255, 255};
  uint8_t inks[6][3];
  int tone[4] = {256, 256, 256, 1};             // saturation, contrast, brightness (q8), fit
  std::vector<SceneLayer> layers;
};

struct Decision {
  String id, file;
  uint16_t amount;     // q16
  uint8_t opacity;     // q8
  uint8_t blend;
  uint16_t feather;
};

bool parse_scene(const String &text, Scene &scene);
std::vector<Decision> decide(const Scene &scene, const State &state);
