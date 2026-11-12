// Open-Meteo weather + geocoding, nearby airports' reports, and the state
// the rules read.
// A port of painter/weather.py (fetch_open_meteo, geocode, build_state).
#pragma once
#include "state.h"

struct Place {
  double lat = 0, lon = 0;
  String name;
};

// "Cincinnati,OH,US" -> coordinates, via Open-Meteo's geocoder.
bool geocode(const String &location, Place &out);

// Fetches the weather and fills `state`. `now` is unix time (UTC).
bool fetch_state(const Place &place, double now, State &state);

// The nearby airports' reports the last fetch weighed, and the forecast's
// vote ("KLUK 9 km: TSRA BR; KCVG 16 km: RA BR; forecast: dry"), or "" when
// there were none and the forecast decided alone.
const char *last_report();
