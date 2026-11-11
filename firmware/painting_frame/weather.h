// Open-Meteo weather + geocoding, and the state the rules read.
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
