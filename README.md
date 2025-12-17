# xibo-screen-info
Small tools to transform PowerPoint slides to standalone HTML slides and to create static PNG images from each HTML page.

This repo contains utilities for building static PNG images from HTML pages (with optional image embedding):
- `scripts/embed_images_in_html.py` — embeds local <img> resources into data URLs so that HTML pages are portable.
- `scripts/html_to_images.py` — renders the HTML pages to PNG images using headless Chromium (preferred) or Playwright (fallback).
- `scripts/watch_and_build.py` — watches `pages/` for changes and automatically re-embeds and re-renders pages (default: embed then render). Use `--skip-embed` to render directly from `pages`.
- `scripts/install_cron.sh` — helper script to set up a daily 7am build and a user systemd service to run the watcher.
- `Makefile` — helper targets: `embed`, `build-images` (embed+render), `build-images-direct` (render from pages), `watch`, and `install-cron`.

Requirements
------------
- Python 3.10+ with pip
- pip packages from `requirements.txt` (beautifulsoup4, watchdog, playwright)
- Chromium / Chrome (optional) or Playwright with downloaded browsers (fallback)

Install
-------
```bash
python3 -m pip install -r requirements.txt --user
# If you want the Playwright fallback, install browsers
python3 -m playwright install --with-deps
```

Usage
-----
1) Embed images into pages (creates `embedded_pages/`):
```bash
python3 scripts/embed_images_in_html.py --src pages --out embedded_pages
```

2) Render the embedded pages to PNG images (creates `output_images/`). If you don't want embedding, render directly from `pages/`:
```bash
# With embedded pages (recommended):
python3 scripts/html_to_images.py --src embedded_pages --out output_images --width 1920 --height 1080
# Or render directly from pages without embedding:
python3 scripts/html_to_images.py --src pages --out output_images --width 1920 --height 1080
```

3) Use `Makefile` helper targets:
```bash
make embed
make build-images      # embed + render
make build-images-direct # render directly from pages (skip embedding)
make watch             # watch and rebuild on changes (default: embed+render)
```

4) Automatically run daily at 7am and run a watcher at boot:
```bash
sudo bash scripts/install_cron.sh
# optional: enable user service
systemctl --user daemon-reload
systemctl --user enable --now slides-watcher.service
```

Notes
-----
- `html_to_images.py` prefers a Chromium binary on PATH. If none exists it will try Playwright (which requires `python -m playwright install` to download browsers).
- The watcher uses the `watchdog` Python package to respond to filesystem changes and rebuild images automatically.
- `embedded_pages` contains HTML with images converted to `data:` URLs so files are portable and self-contained.

If your pages are already self-contained (no local images or they are hosted and reachable), you can skip the embed stage and directly render from `pages/`.

If you'd like, I can extend these to:
- Convert exported slide HTML pages to inline CSS and accurate CSS positioning of text rather than overlaying editable text on top of images.
- Add options for output formats (jpg, webp), resize options, or more advanced screenshot behavior (emulate device sizes, remove scrollbars, add transparent backgrounds, etc.).

Build directory
--------------
This project also supports creating a `build/` folder that contains copies of the generated `pages` (embedded or un-embedded) and `output_images` along with convenient `index.html` files.

- `build/index.html`: a copy of one page chosen at random from `build/pages/` (selected during build). This gives an immediate single page to preview.
- `build/pages/index.html`: an index listing all pages (links to `build/pages/<page>.html`).
- `build/output_images/index.html`: an index listing all rendered images (links to files in `build/output_images/`).
 - `build/output_images/index.html`: an index listing all rendered images (links to files in `build/output_images/`).
 - `build/output_videos/index.html`: if videos exist, an index of generated videos. Videos are copied into `build/output_videos/<duration>/` (for example `5s` subfolder by default) and indexed by `create_build.py` when the `--videos` argument is supplied.

Create the build directory (after running `make build-images` or `make build-images-direct`):

```bash
make build-images   # creates build/ with embedded pages
make build-images-direct # creates build/ with direct pages (no embedding)
```

Or to explicitly call the builder:

```bash
python3 scripts/create_build.py --pages embedded_pages --images output_images --build build --seed 42
# If you have generated videos, include them in the build using --videos
python3 scripts/create_build.py --pages embedded_pages --images output_images --videos output_videos --build build --seed 42
```

The `--seed` option ensures repeatable random page selection for `build/index.html`.
Videos
------
You can create MP4 videos from the static PNGs in `output_images/` using ffmpeg. The repository contains a helper script `scripts/images_to_videos.py` and Makefile targets.

```bash
make videos                # create 5s videos in output_videos/5s from output_images/
make build-videos          # run make build-images then make videos (embedded)
make build-videos-direct   # run make build-images-direct then make videos (no embed)
```

Requirements: `ffmpeg` must be installed on the machine that runs the command (`sudo apt install ffmpeg` on Ubuntu). The images -> 5s video pipeline will create `output_videos/5s/` subfolder.

Playwright-based recordings
----------------------------
If your HTML pages include animations, transitions, or you want a video output that matches the browser rendering, use the Playwright recorder which captures pages into webm then converts them to MP4 with ffmpeg.

Usage (Makefile):
```bash
make record-playwright         # Record pages in embedded_pages to output_videos/ (records 5s by default)
make build-record-playwright   # build images, then record pages (5s), then update build/ (copies output_videos into build/)
make record-playwright-long    # record 10s and 60s variants (occasional/long runs)
make build-record-playwright-long # build, then record 10s/60s, then update build/
```

Requirements: Playwright and Chromium browsers must be installed (`python3 -m playwright install --with-deps`) and ffmpeg must be available.

Upload videos to SharePoint
---------------------------
To upload generated videos to SharePoint, use `rclone` configured for your SharePoint/OneDrive remote. Setup `rclone` as usual and then run the upload script (example):

```bash
# assume your rclone remote is called `sharepoint:` and you want to upload to "MySite/Shared Documents/Slides"
./scripts/upload_to_sharepoint.sh "sharepoint:MySite/Shared%20Documents/Slides"
```

If you prefer, add an action to your GitHub Actions workflow to push the created videos into a SharePoint via rclone (or use the SharePoint REST API) with secure credentials.


GitHub Pages
------------
You can use the included GitHub Actions workflow (`.github/workflows/deploy.yml`) to build and deploy the `build/` directory to the `gh-pages` branch automatically when you push to `main`.

Steps:

1) Ensure repository Pages is configured to serve from `gh-pages` branch (you can also select the `docs/` folder if you prefer, but the workflow provided deploys to `gh-pages`).
2) Push a commit to `main` and GitHub Actions will run the build and publish `build/` as the GitHub Pages site.

If your Pages site doesn't appear immediately, allow a few minutes or check the Actions run logs for errors.

Serving locally
---------------
You can serve the `build/` directory locally to test the site or preview the layout. Use the `make serve` target, which defaults to port `8000`:

```bash
make serve            # serve on port 8000
PORT=9000 make serve  # serve on port 9000
```

The server uses Python's built-in `http.server` and is intended for quick local preview; for production and deployment use GitHub Pages (workflows already set up).

Background serving
-------------------
If you prefer a background server, use `make serve-bg`. This will start the HTTP server in the background and write the PID to `build/serve.pid` and logs to `build/serve.log`.

```bash
# start background server (default port 8000)
make serve-bg
# start background server on different port
PORT=9000 make serve-bg

# view server logs
make serve-logs

# stop the background server
make serve-stop
```

Note: The `serve-bg` target uses `nohup` so it survives the terminal closing (depending on your system). Kill the background process using `make serve-stop` (or kill the stored PID manually).

