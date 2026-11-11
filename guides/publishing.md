# Publishing on GitHub

[Back to the project](../README.md)

The repository's `docs/` folder is the project's website. It holds the USB installer, the firmware that frames update to over Wi-Fi, and Julia's painting, which frames download layer by layer. This guide covers publishing and maintaining them together.

## Project Addresses

- Repository: `Canterrain/weather-painting`
- Installer: `https://canterrain.github.io/weather-painting/`
- Painting: `https://canterrain.github.io/weather-painting/painting/`
- Firmware updates: `https://canterrain.github.io/weather-painting/firmware/`

The painting and firmware addresses are built into the firmware (`version.h`). When publishing a fork under another name, update them there and in the README and installer links.

## Release Checks

- Keep the README, installer, and `version.h` addresses aligned with the repository name.
- Licensing: the code is CC BY-NC 4.0, © 2026 Josh Hendrickson. Julia's paintings are CC BY-NC-ND 4.0, © 2026 Julia Hendrickson.
- Run a USB browser installation on a reTerminal E1004, complete Wi-Fi setup, and check that the painting downloads and draws.
- Check that an update with Erase device unchecked keeps settings, and a fresh erased install starts setup correctly.
- Check that a frame on the previous version finds and installs the new one from **Check for an update**.

## Repository Contents

Publish the firmware sources, painter tools, painting, README, guides, and `docs/`. The `.gitignore` excludes local build products, previews, Python environments, OS metadata, and `config.h`.

Use the compiled release files, never a dump read from a personal frame.

## Enable GitHub Pages

After the repository and its reviewed files are on GitHub:

1. Open **Settings → Pages**.
2. Under Build and deployment, choose **Deploy from a branch**.
3. Select **main** and **/docs**, then save.
4. Wait for the Pages deployment to complete and open the address GitHub provides.
5. Confirm the install page, `firmware/manifest.json`, `firmware/version.txt`, all four `.bin` files, and `painting/manifest.txt` are served, then test the installer over USB.

`docs/.nojekyll` keeps Jekyll processing out of the deployment.

See [GitHub's publishing-source instructions](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site).

## Publish a Firmware Update

1. Raise `FW_VERSION` in `firmware/painting_frame/version.h`.
2. Prepare the firmware: `python3 tools/prepare_installer.py`.
3. Test the firmware on a frame and inspect `docs/firmware/build-info.json` and `SHA256SUMS`.
4. Commit the source and its generated firmware together.
5. Push the reviewed change. Pages republishes from `main` and `/docs`.

Frames with automatic updates on install it within a day. Others get it from **Check for an update** in settings.

Don't package from a stale build directory. The preparation script always compiles first and refuses unexpected chip, partition, or flash-header settings. If a future version changes the partition layout, it can't be installed over Wi-Fi; the installer instructions would need to require a USB install with an erase.

## Publish a Painting

1. Put the layers in `painting/layers/` with the names from the [painting guide](painting.md).
2. Preview them: `.venv/bin/python -m painter studio`.
3. Publish: `.venv/bin/python -m painter publish`.
4. Commit `painting/` and `docs/painting/` together, then push.

`publish` checks every rule against the scenarios in `scenarios/` and every demo combination, then writes the layers in the frame's format, the compiled rules, and a manifest to `docs/painting/`. Frames compare the manifest each time they wake and download only the layers that changed.

To publish a painting of your own instead, fork this repository, replace the layers, publish, and enable Pages on your fork. Frames use it when **Another site** is set to `https://YOUR_NAME.github.io/weather-painting/painting/`.

If you change `painting/scene.yaml`, also run `.venv/bin/python -m painter firmware-data` and publish a firmware update. The frame's built-in copy of the layout is used for uploaded paintings and the list on the settings page.

## Installer References

- [Bread Proof Monitor installer source](https://github.com/Canterrain/bread-proof-monitor/blob/main/docs/index.html)
- [ESP Web Tools documentation](https://esphome.github.io/esp-web-tools/)

Weather Painting uses its own Wi-Fi setup network after installation. It doesn't implement Improv Serial provisioning, so the installer skips that optional step.
