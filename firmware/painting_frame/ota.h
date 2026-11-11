// Firmware updates over Wi-Fi from the project site (FIRMWARE_URL):
// version.txt holds the newest version, firmware.bin the app image.
#pragma once
#include <Arduino.h>

// The newest version on the site, or "" if it couldn't be read.
String latest_firmware_version();

// true if `latest` is a higher dotted version than this firmware.
bool is_newer(const String &latest);

// Downloads and installs firmware.bin. On success the caller restarts.
bool install_firmware_update(String &error);
