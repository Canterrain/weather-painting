// Open-Meteo weather + geocoding, the nearest airport's report, and the
// state the rules read.
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

// The airport report the last fetch used ("KLUK, 9 km away: TSRA BR (4 min
// ago)"), or "" when there wasn't one and the forecast was used.
const char *last_report();
