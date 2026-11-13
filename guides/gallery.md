# The Gallery

[Back to the project](../README.md)

The gallery is a set of paintings by people who've made their own, which any frame can choose from **Painting → From the gallery** on its settings page. Every painting is reviewed before it joins.

## Submit a Painting

1. Paint your layers as described in the [painting guide](painting.md). Each is a 1600 × 1200 PNG named as in the guide. Only `sky_clear.png` and `ground_summer.png` are required, but the more seasons and weather you paint, the more your painting does.
2. Put all the PNGs in one zip file, up to 25 MB.
3. Open the **[submission form](https://github.com/Canterrain/weather-painting/issues/new?template=painting.yml)**. You'll need a free GitHub account.
4. Give your painting a name, say how you'd like to be credited, choose a license, and drag the zip into the **Layers** box.

A few minutes later a check posts on your submission. It lists the layers it found and anything wrong, with a picture of your painting in several kinds of weather, as the frame's screen shows them. To fix something, edit your submission and attach a new zip; the check runs again.

The gallery takes hand-made paintings only: painted or drawn by you, on paper or on a tablet, with no part made or changed with AI. Paintings must be suitable for all ages.

### Licenses

Every license lets people download your painting and show it on their frames. They differ in what else is allowed:

| License | Others may |
| --- | --- |
| CC BY-NC-ND 4.0 | Show it, with credit. Not sell it or share changed versions. Julia's painting uses this. |
| CC BY-NC 4.0 | Also share changed versions, with credit. Not sell it. |
| CC BY 4.0 | Use it for anything, with credit. |

## Review Submissions

This part is for the repository's owner.

Submissions arrive as issues labeled **painting**. The Gallery workflow (`.github/workflows/gallery.yml`, which runs `tools/gallery.py`) checks each one when it's opened or edited, using `painter/submission.py`, and posts the result. Its preview is kept in a pre-release named `submission-<issue>`, so it can be shown on the issue.

- **To approve,** add the **approved** label. The workflow checks the painting again, publishes the frame's files as a release named `gallery-<name>`, adds the painting to `docs/gallery.json`, comments, and closes the issue. Frames see it in the gallery a few minutes later, once Pages updates.
- **To decline,** close the issue as *not planned*, with a comment saying why. The preview pre-release is deleted.
- **To remove** a painting later, delete its entry from `docs/gallery.json` and push. Frames already showing it keep it until their owner chooses another; delete its release too if it should stop downloading.

Only the owner's label approves a painting. Labels from anyone else are ignored.

The repository needs two labels, **painting** and **approved**, before the first submission.
