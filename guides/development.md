# Building the Firmware

[Back to the project](../README.md)

Most people can use the browser installer. These instructions are for changing the firmware or packaging a new version.

## Arduino IDE

The sketch is `firmware/painting_frame/painting_frame.ino`.

1. Install the ESP32 board package by Espressif Systems.
2. Choose **XIAO_ESP32S3** as the board.
3. Choose **OPI PSRAM** under PSRAM. Leave the partition scheme at its default, which has room for updates over Wi-Fi.
4. Install **Seeed_GFX** from [Seeed Studio's repository](https://github.com/Seeed-Studio/Seeed_GFX), and **ArduinoJson** and **PNGdec** from the Library Manager.
5. Open `painting_frame.ino`, compile, then upload.

The current local build uses:

| Component | Version |
| --- | --- |
| Arduino ESP32 core | 3.3.10 |
| Seeed_GFX | 2.0.3 |
| ArduinoJson | 7.4.3 |
| PNGdec | 1.1.6 |

`driver.h` selects the reTerminal E1004 screen for Seeed_GFX.

To skip the setup network while developing, copy `config.example.h` to `config.h` and fill it in. Its values are used only the first time the frame starts with empty settings. `config.h` is ignored by Git, and the packaging script leaves it out of published firmware.

## Arduino CLI

From the project root, with Arduino CLI and those libraries installed:

```bash
arduino-cli compile --fqbn esp32:esp32:XIAO_ESP32S3:PSRAM=opi --build-path .arduino/build firmware/painting_frame
```

```bash
arduino-cli upload --fqbn esp32:esp32:XIAO_ESP32S3:PSRAM=opi --port YOUR_SERIAL_PORT --input-dir .arduino/build firmware/painting_frame
```

Replace `YOUR_SERIAL_PORT` with the port reported by `arduino-cli board list`. On a Mac, the frame shows up as `/dev/cu.wchusbserial…`.

The frame logs to its USB serial port at 115200 baud: weather, the layers it chose, render and refresh times, and how long it's sleeping.

## Generated Files

Two headers are made from other files in the project. Don't edit them by hand.

| File | Made from |
| --- | --- |
| `generated.h` | `painting/scene.yaml` (the standard layout for uploaded paintings) and `painter/combos.py` (the demo) |
| `settings_page.h` | `web/settings.html` |

After changing any of those, regenerate them, then rebuild the firmware:

```bash
.venv/bin/python -m painter firmware-data
```

The command checks every rule in the standard layout against the demo combinations before it writes anything.

## How It Works

The frame does everything itself; no computer or server is involved once it's set up. Each time it wakes, it:

1. Connects to Wi-Fi and gets the weather for your city from [Open-Meteo](https://open-meteo.com/).
2. Checks what's falling right now. Three sources vote: weather radar from [RainViewer](https://www.rainviewer.com/) over your exact spot, nearby airports' weather reports from the [Aviation Weather Center](https://aviationweather.gov/data/api/), and the forecast for your spot, which counts as wet if rain is due within half an hour. Radar counts most, since it sees rain where you are within about 10 minutes. Airports count more the closer they are, and they say what kind of weather it is: rain, snow, drizzle, thunder, or fog. That catches a storm the forecast missed, and leaves out a shower at one distant airport that's heading elsewhere. Radar gives how hard it's falling; the nearest airport measuring it, or the forecast, says whether it's rain or snow. Where a country shares no radar, or no airport within 50 km has reported in the last 90 minutes, the others decide without it. The settings page shows the last check.
3. Works out the season, the sun and moon positions, and the moon's phase on the frame itself.
4. Checks the painting's website for changed layers, and downloads only those to the memory card.
5. Decides which layers to show, and how far, from the rules in `scene.txt`.
6. Composes the layers row by row and dithers them to the screen's six inks.
7. Redraws the screen only if the result changed, then sleeps.

`wp_compose.c` is the compositor. The painter tools on a computer run the same file, so a preview there matches the screen pixel for pixel.

| Path | What's there |
| --- | --- |
| `painting_frame.ino` | Startup, buttons, the demo, and sleep |
| `settings.*`, `portal.*`, `web/` | Saved settings and the settings page |
| `weather.*`, `astro.*`, `state.h` | Weather, airport reports, sun, moon, and season |
| `sync.*`, `rules.*`, `render.*`, `wp_compose.*` | Downloading, choosing, and composing layers |
| `text.*`, `screens.*` | Setup and problem screens, and demo captions |
| `ota.*`, `version.h` | Updates over Wi-Fi |

## Prepare a Browser Installer Build

Raise `FW_VERSION` in `firmware/painting_frame/version.h`, then from the project root:

```bash
python3 tools/prepare_installer.py
```

The script compiles the current source, validates the chip, image headers, partition layout, and flash regions, then writes the four firmware parts, manifest, build information, checksums, and `version.txt` into `docs/firmware/`. Frames compare `version.txt` with their own version once a day and install `firmware.bin` when it's newer.

It requires Python 3 and the Arduino CLI environment described above. It does not upload to a frame or publish anything.

The installer deliberately uses separate flash parts. Sending a padded merged image would also overwrite the space holding saved settings, even when the person installing didn't ask for an erase.

Preview the installer with:

```bash
python3 -m http.server 8765 --bind 127.0.0.1 --directory docs
```

Open [http://localhost:8765](http://localhost:8765). Web Serial requires HTTPS when hosted; localhost is fine for local development. The installer library is loaded from ESP Web Tools and needs internet access.

## Publishing

See [Publishing on GitHub](publishing.md) for the repository and GitHub Pages setup, release checks, and publishing paintings and updates.
