// The settings page: a small web server on the frame.
//
// Setup mode (no home Wi-Fi saved, or it can't be reached): the frame makes
// its own network, WeatherPainting-Setup, and any page a phone opens on it
// leads to the settings page at http://192.168.4.1.
//
// Settings mode (the bottom button): on the home network, at
// http://weatherpainting.local or the frame's IP address.
//
// Either way it stays open until "Done", the top button, or 15 quiet minutes.
#pragma once
#include <Arduino.h>
#include <functional>
#include "settings.h"

#define SETUP_AP_NAME     "WeatherPainting-Setup"
#define SETUP_AP_PASSWORD "watercolor"
#define MDNS_NAME         "weatherpainting"

enum PortalExit { PORTAL_DONE, PORTAL_DEMO };

// `show(title, body)` puts instructions on the panel once the page is up.
PortalExit run_portal(Settings &settings, bool setup_mode,
                      std::function<void(const String &title, const String &body)> show);
