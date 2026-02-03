#!/usr/bin/env bash
set -euo pipefail

export DISPLAY=${DISPLAY:-:0}

# Persistent profile volume
USER_DATA_DIR=/data/chrome
mkdir -p "$USER_DATA_DIR"
chown -R chrome:chrome /data

# Start Chromium as non-root
exec su -s /bin/bash -c "\
  chromium \
    --user-data-dir=${USER_DATA_DIR} \
    --no-first-run \
    --no-sandbox \
    --disable-dev-shm-usage \
    --disable-features=TranslateUI \
    --start-maximized \
    https://gemini.google.com/\
" chrome
