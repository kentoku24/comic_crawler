#!/usr/bin/env bash
set -euo pipefail

export DISPLAY=${DISPLAY:-:0}

# Persistent profile volume
USER_DATA_DIR=/data/chrome
mkdir -p "$USER_DATA_DIR"
chown -R chrome:chrome /data

# Optional: load OpenClaw Browser Relay extension (unpacked)
# Mount an unpacked extension directory into the container at /opt/openclaw-relay
# (must contain manifest.json). Example mount is documented in README.
EXT_DIR=${RELAY_EXT_DIR:-/opt/openclaw-relay}
EXT_ARGS=""
if [ -f "${EXT_DIR}/manifest.json" ]; then
  EXT_ARGS="--disable-extensions-except=${EXT_DIR} --load-extension=${EXT_DIR}"
fi

# Start Chromium as non-root
exec su -s /bin/bash -c "\
  chromium \
    --user-data-dir=${USER_DATA_DIR} \
    --no-first-run \
    --no-sandbox \
    --disable-dev-shm-usage \
    --disable-features=TranslateUI \
    --start-maximized \
    ${EXT_ARGS} \
    https://gemini.google.com/\
" chrome
