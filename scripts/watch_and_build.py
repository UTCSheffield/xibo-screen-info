#!/usr/bin/env python3
"""
Watch `pages` directory and rebuild embedded pages and rendered images on change.

Usage:
  python3 scripts/watch_and_build.py --pages pages --embedded embedded_pages --out output_images

Note: This requires `watchdog` to be installed (see requirements.txt)
"""

import argparse
import time
import subprocess
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import threading

DEBOUNCE_SECONDS = 1.0

class DebounceHandler(FileSystemEventHandler):
    def __init__(self, callback):
        super().__init__()
        self.callback = callback
        self.timer = None
        self.lock = threading.Lock()

    def _schedule(self):
        with self.lock:
            if self.timer:
                self.timer.cancel()
            self.timer = threading.Timer(DEBOUNCE_SECONDS, self._run)
            self.timer.start()

    def _run(self):
        with self.lock:
            self.timer = None
        self.callback()

    def on_any_event(self, event):
        self._schedule()


def build_all(pages_dir: Path, embedded_dir: Path, out_dir: Path):
    print('Building embedded HTML and images...')
    subprocess.run(['python3', 'scripts/embed_images_in_html.py', '--src', str(pages_dir), '--out', str(embedded_dir)])
    subprocess.run(['python3', 'scripts/html_to_images.py', '--src', str(embedded_dir), '--out', str(out_dir)])
    print('Build complete.')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--pages', default='pages', help='Original pages dir')
    parser.add_argument('--embedded', default='embedded_pages', help='Embedded pages dir')
    parser.add_argument('--out', default='output_images', help='Output images dir')
    parser.add_argument('--build', default='build', help='Build directory to copy pages and output images into')
    parser.add_argument('--skip-embed', action='store_true', help='Skip embedding stage and render directly from pages dir')
    args = parser.parse_args()

    pages = Path(args.pages).resolve()
    embedded = Path(args.embedded).resolve()
    out = Path(args.out).resolve()
    build_dir = Path(args.build).resolve()

    if not pages.exists():
        print('Pages directory does not exist:', pages)
        return

    # initial build
    if args.skip_embed:
        print('Building images directly from pages (skip embedding).')
        subprocess.run(['python3', 'scripts/html_to_images.py', '--src', str(pages), '--out', str(out)])
        # create build copy
        subprocess.run(['python3', 'scripts/create_build.py', '--pages', str(pages), '--images', str(out), '--build', str(build_dir)])
    else:
        build_all(pages, embedded, out, build_dir)

    if args.skip_embed:
        event_handler = DebounceHandler(lambda: (subprocess.run(['python3', 'scripts/html_to_images.py', '--src', str(pages), '--out', str(out)]), subprocess.run(['python3', 'scripts/create_build.py', '--pages', str(pages), '--images', str(out), '--build', str(build_dir)])))
    else:
        event_handler = DebounceHandler(lambda: build_all(pages, embedded, out, build_dir))
    observer = Observer()
    observer.schedule(event_handler, str(pages), recursive=True)
    print('Watching', pages, 'for changes. Ctrl-C to stop.')
    observer.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()

if __name__ == '__main__':
    main()
