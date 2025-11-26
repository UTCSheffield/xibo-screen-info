# xibo-screen-info
A small repo to convert PowerPoint slides to a simple standalone HTML slideshow and to generate per-slide editable HTML pages.

## Included files
- `football_slideshow_template.html` — an HTML slideshow template with playback controls.
- `scripts/pptx_to_html.py` — a script to convert a PPTX into slide images and HTML slides/pages.
- `requirements.txt` — Python dependencies (e.g., python-pptx).

## Install requirements

```bash
python3 -m pip install -r requirements.txt
# On Debian/Ubuntu
sudo apt update && sudo apt install -y libreoffice
```

## Single slideshow

Create slide images and a single slideshow HTML:

```bash
mkdir -p slides
python3 scripts/pptx_to_html.py "Football fixtures 2025-11-25.pptx" -o football_slideshow.html --slides-dir slides
```

Open `football_slideshow.html` in a browser to view the slideshow. Slide notes are included as editable captions.

## Per-slide editable pages

If you'd like each slide as a standalone, editable HTML page (with contenteditable overlays), generate both slides and per-slide pages:

```bash
mkdir -p slides pages
python3 scripts/pptx_to_html.py "Football fixtures 2025-11-25.pptx" --per-slide --slides-dir slides --pages-dir pages
```

This creates `pages/slide-01.html`, `pages/slide-02.html`, etc. Each page embeds the converted PNG as a base64 data URL, and places editable overlay boxes for each text shape extracted from the slide. Pages are independent — they don't include Prev/Next navigation by default. Use the "Download HTML" button on a page to save the edited version.

## Notes
- The script uses LibreOffice `soffice` to export slides as PNGs, and `python-pptx` to extract text and notes. If conversion fails, verify LibreOffice is installed and on PATH.
- Text overlays use absolute positioning relative to the slide size; editing changes are purely client-side unless you save the edited HTML.
- This approach keeps the original visual layout as an image while allowing easy, in-browser editing of texts.

If you'd like the script to attempt a more faithful HTML conversion (breaking text into CSS-styled marks, converting shapes to DOM elements, etc.), I can extend it to extract fonts, colors, and shapes more precisely and create fully-structured HTML slides instead of overlaying text on an image.
