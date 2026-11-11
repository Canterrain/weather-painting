// Demo mode: the season x weather test cases built into the firmware
// (generated.h, from painter/combos.py), so any painting, downloaded or
// uploaded, can be checked on the real panel.
#pragma once
#include <Arduino.h>
#include "state.h"

int demo_count();

// Loads case `index` (wrapped to the number of cases) into `state`, and its
// title (e.g. "Winter: Blizzard"). Returns the season.
String load_demo_case(int index, State &state, String &title);
