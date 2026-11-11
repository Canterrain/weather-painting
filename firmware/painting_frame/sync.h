// Keeps the SD card in step with the published site (painter publish):
// downloads manifest.txt, then only the files whose checksum changed.
#pragma once
#include <Arduino.h>

// Files live under /wp on the SD card, mirroring the site:
//   /wp/manifest.txt  /wp/scene.txt  /wp/layers/*.wpl
// Returns the manifest version now on the card ("" if nothing usable).
String sync_site(const String &base_url, bool &changed);
