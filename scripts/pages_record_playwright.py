#!/usr/bin/env python3
"""
Record videos for each HTML page in a directory using Playwright and convert to MP4.

Usage:
    python3 scripts/pages_record_playwright.py --src embedded_pages --out output_videos --durations 5 --width 1920 --height 1080

This will create subfolders in the output dir named by duration (e.g., output_videos/5s)
"""

import argparse
import shutil
import subprocess
import time
from pathlib import Path


def convert_webm_to_mp4(webm_path: Path, mp4_path: Path):
    cmd = [
        'ffmpeg', '-y', '-loglevel', 'error',
        '-i', str(webm_path),
        '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
        str(mp4_path)
    ]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        print('ffmpeg failed for', webm_path, p.stderr)
        return False
    return True


def record_pages(src_dir: Path, out_dir: Path, durations, width, height, keep_webm=False):
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        print('Playwright not available. Run: python3 -m pip install playwright && python3 -m playwright install')
        raise

    src_dir = src_dir.resolve()
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    recordings_dir = Path('.playwright_recordings')
    recordings_dir.mkdir(parents=True, exist_ok=True)

    pages = sorted(src_dir.glob('*.html'))
    if not pages:
        print('No pages found in', src_dir)
        return

    with sync_playwright() as p:
        browser = p.chromium.launch()
        for duration in durations:
            duration_dir = out_dir / f'{duration}s'
            duration_dir.mkdir(parents=True, exist_ok=True)
            rec_tmp_dir = recordings_dir / f'{duration}s'
            rec_tmp_dir.mkdir(parents=True, exist_ok=True)

            for page_file in pages:
                # create a unique recording subdir per page to avoid name collisions
                page_tmp_dir = rec_tmp_dir / page_file.stem
                if page_tmp_dir.exists():
                    shutil.rmtree(page_tmp_dir)
                page_tmp_dir.mkdir(parents=True, exist_ok=True)

                context = browser.new_context(record_video_dir=str(page_tmp_dir), record_video_size={"width": width, "height": height})
                page = context.new_page()
                page.goto(page_file.as_uri())
                # Wait for the given duration; if you want to wait for network idle, replace with page.wait_for_load_state('networkidle') then delay.
                page.wait_for_timeout(duration * 1000)
                # Closing the page/context flushes the video to disk
                page.close()
                context.close()

                # Find the webm file in page_tmp_dir
                webms = sorted(page_tmp_dir.glob('*.webm'))
                if not webms:
                    # Some Playwright versions write into a subdir or name differently; try to find the newest file in page_tmp_dir
                    cand = sorted(page_tmp_dir.rglob('*'))
                    webms = [f for f in cand if f.suffix.lower() == '.webm']
                if not webms:
                    print('No video produced for', page_file)
                    continue
                webm_path = webms[-1]
                mp4_out = duration_dir / f'{page_file.stem}.mp4'
                ok = convert_webm_to_mp4(webm_path, mp4_out)
                if ok:
                    print(f'Recorded {page_file.name} -> {mp4_out} ({duration}s)')
                else:
                    print('Failed to convert', webm_path)
                if not keep_webm:
                    try:
                        webm_path.unlink()
                    except Exception:
                        pass

        browser.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--src', default='embedded_pages', help='Source pages dir (default: embedded_pages)')
    parser.add_argument('--out', default='output_videos', help='Output videos base dir (default: output_videos)')
    parser.add_argument('--durations', type=int, nargs='+', default=[5], help='Durations in seconds to record (default: 5)')
    parser.add_argument('--width', type=int, default=1920)
    parser.add_argument('--height', type=int, default=1080)
    parser.add_argument('--keep-webm', action='store_true', help='Do not delete intermediate webm recordings')
    args = parser.parse_args()

    record_pages(Path(args.src), Path(args.out), args.durations, args.width, args.height, args.keep_webm)
