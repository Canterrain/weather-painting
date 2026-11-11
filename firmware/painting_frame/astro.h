// Sun and moon positions: a line-for-line port of painter/astro.py.
#pragma once
#include <stdint.h>

struct SkyState {
  double sun_alt;
  double moon_alt;
  bool moon_up;
  double moon_illum;
  bool moon_waxing;
  const char *moon_phase;   // "new", "waxing_crescent", ... "full", ...
};

SkyState sky_at(double unix_seconds, double lat, double lon);
