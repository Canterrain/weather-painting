# Painting Your Own

[Back to the project](../README.md)

The frame shows one painting that never moves. On top of it sit separately painted pieces, like snow on the branches, rain, or the moon, that the frame shows, hides, or changes as the real weather changes. You can replace Julia's tree with a painting of your own and upload it from the frame's settings page. You don't need Python, GitHub, or any software beyond what you paint and export with.

## The Rules for Every File

- **1600 × 1200 pixels**, landscape. Every file is exactly that size.
- **PNG with transparency.** Paint only the piece itself. Everywhere else is see-through.
- **Same framing.** Every piece lines up with the others exactly, like sheets of tracing paper.
- **Exact names.** Lower case, as listed below.

Pixels per inch doesn't matter. If your editor asks when exporting, leave the default; only the 1600 × 1200 pixel size counts.

## Colors

The screen has six inks: white, black, red, yellow, blue, and green. Everything else is made by mixing dots of those inks.

- Clean, saturated washes and their two-color mixes (orange, pink, purple, sky blue, lime, brown) look great.
- Flat muted grays, beige, taupe, sage, and dusty pastels turn speckly.
- Keep clear light and dark contrast, and don't put dark navy next to black.

## What to Paint

The frame lays the pieces down from bottom to top. Only **sky_clear** and **ground_summer** are needed to start. Any piece that doesn't exist yet is skipped, so the frame works from the first upload and gains detail as you add more.

### Sky

| File | What to paint | When it shows |
| --- | --- | --- |
| `sky_clear.png` | A clear day sky, painted all the way down to the bottom edge, behind the ground and tree. No see-through areas. | Always, at the bottom of the stack |
| `sky_cloudy.png` | A partly cloudy sky, also painted all the way down. | Clouds cover half to most of the sky, and fog |
| `sky_stormy.png` | A heavy, gray sky. | Overcast, raining, snowing, or storms |
| `sun.png` | The sun, alone, where it sits in the sky. | Daytime with mostly clear skies |

### Ground and Tree

Keep the ground's horizon and the trunk in the same place in every season. Only the colors and leaves change.

| File | What to paint | When it shows |
| --- | --- | --- |
| `ground_spring.png` | Fresh green ground. | Spring |
| `ground_summer.png` | Summer ground. | Summer |
| `ground_fall.png` | Golden, dormant ground. | Fall |
| `ground_winter.png` | Winter ground, under snow. | Winter, and whenever snow is lying in any other season |
| `tree_spring.png` | The tree in spring. | Spring |
| `tree_summer.png` | The tree in full leaf. | Summer |
| `tree_fall.png` | The tree in fall color. | Fall |
| `tree_winter.png` | The bare tree. | Winter |
| `snow_branches.png` | Snow resting along the branches of the winter tree. | Winter, after real snow, until it warms up |

### Fog and Falling Weather

| File | What to paint | When it shows |
| --- | --- | --- |
| `fog.png` | A pale, soft mist over the ground and the bottom of the tree, fading out higher up. | Fog |
| `snowfall_light.png` | A few falling flakes across the picture. | Light snow |
| `snowfall_heavy.png` | More flakes. | Steady snow |
| `snowfall_blizzard.png` | Lots of flakes. | Heavy snow |
| `rain_light.png` | A few raindrops, and small puddles if you like. | Light rain |
| `rain_heavy.png` | Many raindrops and bigger puddles. | Heavy rain |

### Night

| File | What to paint | When it shows |
| --- | --- | --- |
| `night.png` | A dark, even wash over the whole picture. The frame lays it over everything like a glaze. | After dark |
| `moon.png` | A full moon, alone, where it sits in the sky. | At night when the moon is up and the sky is clear enough |

Paint the moon full. The frame shades it to the real phase every night, from a thin crescent to full, lit from the right while it's waxing and from the left while it's waning.

## Painting on Paper or on a Tablet

**On a tablet** (Procreate, Photoshop, Rebelle): keep everything in one file with one layer per piece, then export each layer as its own PNG with transparency.

**On paper:** paint each piece on its own sheet, lined up by tracing over a print of the base painting, with small marks in the corners. Scan every sheet the same way, then remove the paper in an editor so only the paint is left. Julia painted the tree on paper and cleaned each piece up in Photoshop.

Pieces lighter than what's under them, like snow and the moon, can't be painted white on white. Paint them with white gouache on dark paper, or add them on a tablet.

## Upload to the Frame

1. Press the frame's **bottom** button and open the address it shows.
2. Under **Painting**, choose **My own painting**.
3. Drop your PNG files on the upload box. Your browser converts them and sends them to the frame's memory card. A full-size layer takes about 20 seconds.
4. Press **Use this painting**, then **Close settings**.

The list under the upload box shows which pieces the frame has and which are still missing. Upload a file again to replace it.

Press the **middle** button to see your painting in every season and kind of weather. That's the quickest way to check that everything lines up.

## Preview on a Computer

If you have Python 3, the painter tools show your painting in any weather before it goes to the frame:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m painter --scene my_painting studio
```

Put your files in `my_painting/layers/` and copy `painting/scene.yaml` into `my_painting/`. The studio opens in your browser with controls for season, weather, time of day, and the moon, plus a grid of every combination. It redraws when you save a layer.

`python -m painter check my_layer.png` shows how a single file will look on the screen's six inks.

## Share Your Painting

Uploaded layers stay on your frame. To let other frames use your painting, publish it as a website and choose **Another site** in their settings. See [Publishing on GitHub](publishing.md#publish-a-painting).
