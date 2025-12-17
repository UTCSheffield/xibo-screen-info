#!/usr/bin/env python3
"""
Create a build folder that contains copies of the pages and output images, plus navigational index files.

Usage:
  python3 scripts/create_build.py --pages embedded_pages --images output_images --build build

This script copies `pages` and `output_images` into `<build>/pages` and `<build>/output_images`, adds `index.html` files to list contents for navigation, and creates `build/index.html` as a copy of a randomly selected page.
"""

import argparse
import shutil
import random
from pathlib import Path


def copy_tree(src: Path, dst: Path):
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def make_pages_index(pages_dir: Path):
    links = []
    for p in sorted(pages_dir.glob('*.html')):
        links.append(f'<li><a href="{p.name}">{p.name}</a></li>')
    html = ['<!doctype html>', '<html lang="en">', '<head>', '  <meta charset="utf-8">', '  <meta name="viewport" content="width=device-width, initial-scale=1">', '  <title>Pages</title>', '</head>', '<body>', '<h1>Pages</h1>', '<ul>']
    html.extend(links)
    html.extend(['</ul>', '</body>', '</html>'])
    (pages_dir / 'index.html').write_text('\n'.join(html), encoding='utf-8')


def make_images_index(images_dir: Path):
    items = []
    for img in sorted(images_dir.glob('*')):
        if img.suffix.lower() in ['.png', '.jpg', '.jpeg', '.webp', '.gif']:
            items.append(f'<li><a href="{img.name}">{img.name}</a></li>')
    html = ['<!doctype html>', '<html lang="en">', '<head>', '  <meta charset="utf-8">', '  <meta name="viewport" content="width=device-width, initial-scale=1">', '  <title>Images</title>', '</head>', '<body>', '<h1>Output images</h1>', '<ul>']
    html.extend(items)
    html.extend(['</ul>', '</body>', '</html>'])
    (images_dir / 'index.html').write_text('\n'.join(html), encoding='utf-8')


def make_videos_index(videos_dir: Path):
    # Create an index page for the top-level videos dir and subfolder indexes for each duration
    # e.g. output_videos/5s/index.html and output_videos/index.html
    duration_links = []
    # If there are subfolders (e.g., 10s, 60s), list them and create an index for each
    for sub in sorted([p for p in videos_dir.iterdir() if p.is_dir()]):
        items = []
        for vid in sorted(sub.glob('*')):
            if vid.suffix.lower() in ['.mp4', '.webm', '.mov', '.mkv']:
                items.append(f'<li><a href="{vid.name}">{vid.name}</a></li>')
        html = ['<!doctype html>', '<html lang="en">', '<head>', '  <meta charset="utf-8">', '  <meta name="viewport" content="width=device-width, initial-scale=1">', f'  <title>Videos ({sub.name})</title>', '</head>', '<body>', f'<h1>Videos ({sub.name})</h1>', '<ul>']
        html.extend(items)
        html.extend(['</ul>', '</body>', '</html>'])
        (sub / 'index.html').write_text('\n'.join(html), encoding='utf-8')
        duration_links.append(f'<li><a href="{sub.name}/index.html">{sub.name}</a></li>')

    # If there are videos directly under videos_dir (no subfolder), list them
    root_items = []
    for vid in sorted(videos_dir.glob('*')):
        if vid.is_file() and vid.suffix.lower() in ['.mp4', '.webm', '.mov', '.mkv']:
            root_items.append(f'<li><a href="{vid.name}">{vid.name}</a></li>')

    html = ['<!doctype html>', '<html lang="en">', '<head>', '  <meta charset="utf-8">', '  <meta name="viewport" content="width=device-width, initial-scale=1">', '  <title>Videos</title>', '</head>', '<body>', '<h1>Output videos</h1>', '<ul>']
    html.extend(duration_links)
    if root_items:
        html.extend(['</ul>', '<h2>Other videos</h2>', '<ul>'])
        html.extend(root_items)
    html.extend(['</ul>', '</body>', '</html>'])
    (videos_dir / 'index.html').write_text('\n'.join(html), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--pages', default='embedded_pages', help='Source pages directory to copy into build/pages')
    parser.add_argument('--images', default='output_images', help='Source images directory to copy into build/output_images')
    parser.add_argument('--videos', default=None, help='Source videos directory to copy into build/output_videos')
    parser.add_argument('--build', default='build', help='Build directory to create')
    parser.add_argument('--seed', type=int, default=None, help='Random seed (for reproducible random page selection)')
    args = parser.parse_args()

    pages_src = Path(args.pages).resolve()
    images_src = Path(args.images).resolve()
    build_dir = Path(args.build).resolve()

    if not pages_src.exists():
        raise SystemExit(f"Pages source not found: {pages_src}")
    if not images_src.exists():
        raise SystemExit(f"Images source not found: {images_src}")

    build_dir.mkdir(parents=True, exist_ok=True)
    build_pages_dir = build_dir / 'pages'
    build_images_dir = build_dir / 'output_images'
    build_videos_dir = build_dir / 'output_videos'

    # Copy pages and images
    copy_tree(pages_src, build_pages_dir)
    copy_tree(images_src, build_images_dir)

    # Copy videos (optional)
    if args.videos:
        videos_src = Path(args.videos).resolve()
        if videos_src.exists():
            copy_tree(videos_src, build_videos_dir)
            make_videos_index(build_videos_dir)
        else:
            print('No videos directory found at', videos_src, '— skipping video copy')

    # Create index files
    make_pages_index(build_pages_dir)
    make_images_index(build_images_dir)

    # Create top-level build index (choose a random page)
    pages = [p for p in sorted(build_pages_dir.glob('*.html')) if p.name.lower() != 'index.html']
    if not pages:
        print('No non-index pages found in build, skipping build index creation')
        return
    if args.seed is not None:
        random.seed(args.seed)
    chosen = random.choice(pages)
    index_path = build_dir / 'index.html'
    index_path.write_bytes(chosen.read_bytes())
    print('Created build index as copy of', chosen.name)
    # Create .nojekyll to ensure Github Pages serves files without Jekyll processing
    (build_dir / '.nojekyll').write_text('', encoding='utf-8')
    print('Wrote build/.nojekyll to ignore Jekyll processing')

if __name__ == '__main__':
    main()
