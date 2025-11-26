#!/usr/bin/env bash
# Install a crontab entry to run the builder at 7am daily and also start a watcher at boot (optional)
# Usage: sudo bash scripts/install_cron.sh

set -euo pipefail
ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
PYTHON=$(which python3 || true)
[ -z "$PYTHON" ] && echo 'python3 not found on PATH' && exit 1

CRON_CMD="$PYTHON $ROOT_DIR/scripts/watch_and_build.py --pages $ROOT_DIR/pages --embedded $ROOT_DIR/embedded_pages --out $ROOT_DIR/output_images"
# Add 7am build command
CRON_LINE="0 7 * * * $PYTHON $ROOT_DIR/scripts/embed_images_in_html.py --src $ROOT_DIR/pages --out $ROOT_DIR/embedded_pages && $PYTHON $ROOT_DIR/scripts/html_to_images.py --src $ROOT_DIR/embedded_pages --out $ROOT_DIR/output_images && $PYTHON $ROOT_DIR/scripts/create_build.py --pages $ROOT_DIR/embedded_pages --images $ROOT_DIR/output_images --build $ROOT_DIR/build >> $ROOT_DIR/cron_build.log 2>&1"
# Ensure embedded pages exist (optional): generate them before cron runs
CRON_PREP="$PYTHON $ROOT_DIR/scripts/embed_images_in_html.py --src $ROOT_DIR/pages --out $ROOT_DIR/embedded_pages"
CRON_PREP_LINE="@reboot $CRON_PREP >> $ROOT_DIR/cron_embed.log 2>&1"

# Install crontab entries (idempotent by grep)
( crontab -l 2>/dev/null || true ) | grep -F "$CRON_LINE" || ( (crontab -l 2>/dev/null || true) ; echo "$CRON_LINE" ) | crontab -
( crontab -l 2>/dev/null || true ) | grep -F "$CRON_PREP_LINE" || ( (crontab -l 2>/dev/null || true) ; echo "$CRON_PREP_LINE" ) | crontab -

# Provide a helper to run a background watcher using systemd user service (optional)
cat <<'SERVICE' > $ROOT_DIR/scripts/slides-watcher.service
[Unit]
Description=Slides HTML watcher and builder

[Service]
Type=simple
ExecStart=$PYTHON $ROOT_DIR/scripts/watch_and_build.py --pages $ROOT_DIR/pages --embedded $ROOT_DIR/embedded_pages --out $ROOT_DIR/output_images
Restart=always

[Install]
WantedBy=default.target
SERVICE

SVC_USER_DIR=~/.config/systemd/user
mkdir -p "$SVC_USER_DIR"
cp $ROOT_DIR/scripts/slides-watcher.service "$SVC_USER_DIR/"

cat <<EOF
Crontab entry installed to run at 7am daily and @reboot to ensure embedded pages are generated.
You can also enable a per-user systemd service to run the watcher in the background:

  systemctl --user daemon-reload
  systemctl --user enable --now slides-watcher.service

To uninstall, remove the crontab lines and disable the systemd service.
EOF
