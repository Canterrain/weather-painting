# Weather Painting

A watercolor painting that changes with the weather outside your window.

The painting is always the same tree on the same hill. When it snows where you live, snow falls in the painting and settles on the branches. Rain brings raindrops and puddles. The tree changes with the seasons, and at night the real moon rises in its real phase.

Built for the Seeed Studio reTerminal E1004, a 13.3" color e-paper frame. The painting is by Julia Hendrickson, painted by hand on paper.

## ✨ Features

- Live weather for your city, with no account or API key, checked against the nearest airport's weather report so rain, snow, and thunderstorms show up as they happen
- A tree for every season: spring, summer, fall, and winter
- Falling snow in three strengths, and snow that stays on the branches and ground after it stops
- Light and heavy rain
- Sunny, cloudy, stormy, and foggy skies
- The moon in its real phase, shaded from a thin crescent to full every night
- A demo of every season and kind of weather
- Wi-Fi setup from your phone, with no credentials to put in the code
- A settings page for changing Wi-Fi, your city, or the painting later
- Upload a painting of your own from your browser
- Installation over USB from your browser, then updates over Wi-Fi

E-paper only uses power while it changes, so the frame sleeps between checks and the picture stays on screen.

## 🛠 Hardware

- A Seeed Studio reTerminal E1004, from [Amazon](https://link.amazon/B09WHcVBu) or [Seeed Studio](https://seeedtechnologycoltd.sjv.io/YVa1rB) (affiliate links)
- A microSD card, any size, formatted as FAT32
- A USB-C data cable and a computer for the first installation

Nothing else is needed. The frame does all the work itself; no Raspberry Pi or computer stays running.

## 🚀 Quick Start

### Install the software

Use Chrome, Edge, or a Firefox version with Web Serial support on a desktop or laptop. Safari and mobile browsers aren't supported by this installer.

1. Put the microSD card in the frame.
2. Plug the frame into your computer with a USB **data** cable.
3. Open the **[Weather Painting installer](https://canterrain.github.io/weather-painting/)**.
4. Click **Connect**, choose your frame, and select **Install**.
5. For a first installation, select **Erase device**. Wait for installation to finish and the frame to restart.

You don't need Arduino IDE to use the browser installer. If you'd rather build it yourself, see the [build guide](guides/development.md).

### Connect to Wi-Fi

1. Open your phone or computer's **Wi-Fi settings** and join **WeatherPainting-Setup**. The password is **watercolor**.
2. The setup page usually opens by itself. If it doesn't, open [http://192.168.4.1](http://192.168.4.1).
3. Choose your home Wi-Fi network and enter its password.
4. Enter your city, then state or region, then country, for example **Cincinnati, OH, US**.
5. Press **Close settings**. The frame downloads the painting and draws it. The first download takes a few minutes.

## Using the Frame

Hang the frame in landscape with its buttons on the right. It checks the weather every 30 minutes, or every 15 while it's raining or snowing, and redraws only when the painting has changed. A redraw takes about 45 seconds.

| Button | What it does |
| --- | --- |
| **Top** | Redraw now. In the demo, go back to the real weather. In settings, close them. |
| **Middle** | Start the demo. In the demo, skip ahead to the next season. |
| **Bottom** | Open settings. |

The demo shows all 46 combinations of season and weather in turn, with a label for each, so you don't have to wait for a blizzard to see one.

### Settings

Press the bottom button. The screen shows the settings address, usually **[http://weatherpainting.local](http://weatherpainting.local)**. If that doesn't open, use the IP address shown on the screen.

From settings you can:

- Change Wi-Fi networks or your city
- Choose the painting: Julia's, your own, or one published by someone else
- Upload and remove layers of your own painting
- Start the demo
- Turn automatic updates on or off, check for an update, or install firmware from a file

Settings close after 15 minutes without use.

## 🎨 Paint Your Own

The painting is made of separate layers: skies, a ground and tree for each season, snow, fog, rain, night, and the moon. Paint your own on paper or a tablet, export each piece as a 1600 × 1200 PNG, and drop them on the settings page. Only a sky and a summer ground are needed to start.

The [painting guide](guides/painting.md) lists every layer, what to paint, and when the frame shows it.

## Updating

With **Install updates automatically** on, the default, the frame checks once a day and installs new versions over Wi-Fi. You can also press **Check for an update** in settings.

The USB installer works for updates too. Leave **Erase device** unchecked to keep your settings.

## Development

The firmware uses Arduino for ESP32. The painter tools are Python, for previewing and publishing paintings on a computer. See the [build guide](guides/development.md) for dependencies, local builds, and preparing a new version.

| Path | What's there |
| --- | --- |
| `firmware/painting_frame/` | The frame's firmware and settings page |
| `painting/` | Julia's painting and the standard layer layout |
| `painter/` | Preview, check, and publish tools for paintings |
| `scenarios/` | Weather situations used to check the rules |
| `docs/` | GitHub Pages installer, firmware, and published painting |
| `guides/` | Painting, development, and publishing instructions |
| `tools/` | Firmware packaging |

## Related Projects

- [Bread Proof Monitor](https://github.com/Canterrain/bread-proof-monitor), a dough rise monitor for ESP32
- [Round Weather Display](https://github.com/Canterrain/round-weather-display), a round clock and weather display for Raspberry Pi or ESP32-P4
- [Weather Display](https://github.com/Canterrain/weather-display), a wider clock and weather display for under a cabinet or on a desk
- [Inky Planner](https://github.com/Canterrain/Inky-Planner), a daily planner for Raspberry Pi and Inky e-paper displays

## 📃 License

The code is licensed under the [Creative Commons Attribution–NonCommercial 4.0 International License](https://creativecommons.org/licenses/by-nc/4.0/). See [LICENSE](LICENSE). Third-party libraries retain their own licenses.

The paintings in `painting/layers/` and `docs/painting/` are © 2026 Julia Hendrickson and licensed under the [Creative Commons Attribution–NonCommercial–NoDerivatives 4.0 International License](https://creativecommons.org/licenses/by-nc-nd/4.0/). You're welcome to show them on your own frame. Please don't sell them or share altered versions. See [painting/LICENSE](painting/LICENSE).

© 2026 Josh Hendrickson

Made by [Josh Hendrickson](https://anoraker.com) · Painting by Julia Hendrickson
