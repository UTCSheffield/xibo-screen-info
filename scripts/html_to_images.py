#!/usr/bin/env python3
"""
Render HTML files in a directory into PNG images using headless Chromium.

Usage:
  python3 scripts/html_to_images.py --src embedded_pages --out output_images --width 1920 --height 1080

If embedded pages don't exist, this script will fallback to `pages/`.
It writes PNG files of the same name but with .png extensions into the output directory.
"""

import argparse
import os
import shutil
import subprocess
from pathlib import Path

CHROME_CANDIDATES = [
    'chromium', 'chromium-browser', 'google-chrome', 'google-chrome-stable', 'chrome', 'chrome-browser'
]


def find_chrome():
    for name in CHROME_CANDIDATES:
        path = shutil.which(name)
        if path:
            return path
    return None


def render_html_to_png(chrome_path, html_path: Path, out_path: Path, width: int = 1920, height: int = 1080):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    url = html_path.as_uri()
    # Use headless chromium to render screenshot
    cmd = [chrome_path, '--headless', '--disable-gpu', f'--window-size={width},{height}', f'--screenshot={out_path}', url]
    # hide console output
    p = subprocess.run(cmd, capture_output=True)
    if p.returncode != 0:
        print('Error rendering', html_path, p.stdout, p.stderr)
    else:
        print('Rendered', html_path, '->', out_path)


def build_images(src_dir: Path, out_dir: Path, width: int, height: int):
    chrome = find_chrome()
    playwright_available = False
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
        playwright_available = True
    except Exception:
        playwright_available = False

    if not chrome and not playwright_available:
        print('No headless Chrome/Chromium found on PATH and Playwright not available. Please install Chromium or Google Chrome, or install Playwright (pip install playwright) and run `playwright install` for browsers.')
        return
    html_files = list(src_dir.glob('*.html'))
    if not html_files:
        print('No html files in', src_dir)
        return
    out_dir.mkdir(parents=True, exist_ok=True)
    for f in html_files:
        out_filename = f.with_suffix('.png').name
        out_path = out_dir / out_filename
        if chrome:
            render_html_to_png(chrome, f, out_path, width, height)
        else:
            # use Playwright to render
            from playwright.sync_api import sync_playwright  # type: ignore
            with sync_playwright() as p:
                browser = p.chromium.launch()
                page = browser.new_page(viewport={"width": width, "height": height})
                page.goto(f.as_uri())
                page.screenshot(path=str(out_path), full_page=True)
                browser.close()
            print('Rendered (playwright)', f, '->', out_path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--src', default='embedded_pages', help='Source html directory')
    parser.add_argument('--out', default='output_images', help='Output images directory')
    parser.add_argument('--width', type=int, default=1920, help='Window width')
    parser.add_argument('--height', type=int, default=1080, help='Window height')
    args = parser.parse_args()

    src_dir = Path(args.src).resolve()
    # Fallback
    if not src_dir.exists():
        src_dir = Path('pages').resolve()
    build_images(src_dir, Path(args.out).resolve(), args.width, args.height)

if __name__ == '__main__':
    main()
