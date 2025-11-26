#!/usr/bin/env bash
# Upload output_videos to SharePoint using rclone.
# Usage:
#   ./scripts/upload_to_sharepoint.sh add remote:site/path
# Prerequisite: rclone must be configured with a remote that can access your SharePoint site.
# Example:
#   ./scripts/upload_to_sharepoint.sh sharepoint:MySite/Shared%20Documents/Slides
set -euo pipefail
if [ "$#" -lt 1 ]; then
  echo "Usage: $0 <rclone-remote:destination-path>"
  exit 1
fi
REMOTE="$1"
SRC_DIR="output_videos"
if [ ! -d "$SRC_DIR" ]; then
  echo "Source directory '$SRC_DIR' not found. Build videos first with 'make videos'." >&2
  exit 1
fi
echo "Uploading videos from $SRC_DIR to $REMOTE..."
rclone copy "$SRC_DIR" "$REMOTE" --verbose
echo "Upload complete."
