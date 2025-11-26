#!/usr/bin/env python3
"""
Embed local images into HTML files inside a data URL so the HTML becomes standalone.

Usage:
  python3 scripts/embed_images_in_html.py --src pages --out embedded_pages

This will copy all .html files from `pages` to `embedded_pages` and replace <img src="..."> where src points to local files with `data:image/png;base64,...` data urls.
"""

import os
import sys
import argparse
import base64
from bs4 import BeautifulSoup
from pathlib import Path
import mimetypes


def embed_images_in_file(src_path: Path, out_path: Path, src_dir: Path):
    html = src_path.read_text(encoding='utf-8')
    soup = BeautifulSoup(html, 'html.parser')
    for img in soup.find_all('img'):
        src = img.get('src')
        if not src:
            continue
        # If src is already a data URL, skip
        if src.startswith('data:'):
            continue
        # Resolve relative path
        # Only embed if it is a local file (no scheme, not starting with http)
        if src.startswith('http://') or src.startswith('https://'):
            continue
        # For file URLs starting with / or ./, make path relative to src_dir
        img_path = (src_dir / src).resolve()
        if not img_path.exists():
            # try also relative to the html file itself
            img_path = src_path.parent.joinpath(src).resolve()
            if not img_path.exists():
                print(f"Warning: referenced image not found: {src} in {src_path}")
                continue
        mime, _ = mimetypes.guess_type(str(img_path))
        if not mime:
            mime = 'application/octet-stream'
        data = img_path.read_bytes()
        b64 = base64.b64encode(data).decode('ascii')
        data_url = f'data:{mime};base64,{b64}'
        img['src'] = data_url
    # Also handle inline style url(...) usages (e.g., background-image: url('..'))
    for tag in soup.find_all(attrs={"style": True}):
        style = tag['style']
        # find url(...) occurrences
        import re
        def repl(match):
            url = match.group(1).strip('"\'')
            if url.startswith('data:') or url.startswith('http'):
                return f'url({url})'
            img_path = (src_path.parent / url).resolve()
            if not img_path.exists():
                img_path = (src_dir / url).resolve()
            if not img_path.exists():
                return f'url({url})'
            mime, _ = mimetypes.guess_type(str(img_path))
            if not mime:
                mime = 'application/octet-stream'
            b64 = base64.b64encode(img_path.read_bytes()).decode('ascii')
            return f"url('data:{mime};base64,{b64}')"
        new_style = re.sub(r"url\(([^)]+)\)", repl, style)
        tag['style'] = new_style
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(str(soup), encoding='utf-8')
    print('Wrote embedded HTML:', out_path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--src', default='pages', help='Source pages directory')
    parser.add_argument('--out', default='embedded_pages', help='Output directory for embedded HTML')
    args = parser.parse_args()

    src_dir = Path(args.src).resolve()
    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    html_files = list(src_dir.glob('*.html'))
    if not html_files:
        print('No HTML files found in', src_dir)
        return
    for f in html_files:
        out_path = out_dir / f.name
        embed_images_in_file(f, out_path, src_dir)

if __name__ == '__main__':
    main()
