#!/usr/bin/env python3
"""
Convert static images to short MP4 videos using ffmpeg.

Usage:
  python3 scripts/images_to_videos.py --src output_images --out output_videos --duration 10 --width 1920 --height 1080

Requirements: ffmpeg installed (apt: ffmpeg) or available on PATH.
"""

import argparse
from pathlib import Path
import shutil
import subprocess


def find_ffmpeg():
    return shutil.which('ffmpeg')


def convert_image_to_video(ffmpeg, img_path: Path, out_path: Path, duration: int, width: int, height: int):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg,
        '-y',
        '-loop', '1',
        '-i', str(img_path),
        '-c:v', 'libx264',
        '-t', str(duration),
        '-vf', f"scale={width}:{height},format=yuv420p",
        '-pix_fmt', 'yuv420p',
        str(out_path)
    ]
    print('Running:', ' '.join(cmd))
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        print('ffmpeg error:', p.stderr)
        return False
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--src', default='output_images', help='Source images directory')
    parser.add_argument('--out', default='output_videos', help='Output videos directory')
    parser.add_argument('--duration', type=int, default=10, help='Duration in seconds for each image video')
    parser.add_argument('--width', type=int, default=1920, help='Video width')
    parser.add_argument('--height', type=int, default=1080, help='Video height')
    args = parser.parse_args()

    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        print('ffmpeg not found on PATH. Please install ffmpeg and try again (apt install ffmpeg)')
        raise SystemExit(1)

    src_dir = Path(args.src).resolve()
    out_dir = Path(args.out).resolve()
    if not src_dir.exists():
        raise SystemExit('Source images directory not found: ' + str(src_dir))

    images = sorted([p for p in src_dir.iterdir() if p.suffix.lower() in ['.png', '.jpg', '.jpeg', '.gif', '.webp']])
    if not images:
        print('No images found in', src_dir)
        return

    for img in images:
        out_file = out_dir / (img.stem + '.mp4')
        ok = convert_image_to_video(ffmpeg, img, out_file, args.duration, args.width, args.height)
        if ok:
            print('Created video:', out_file)

if __name__ == '__main__':
    main()
