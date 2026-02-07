#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

# Ensure venv exists
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

pip -q install -U pip >/dev/null
pip -q install -r requirements.txt >/dev/null

# Suppress LibreSSL/urllib3 warning noise in output
export PYTHONWARNINGS="ignore"

python3 manga_watch/check.py manga_watch/urls.txt
