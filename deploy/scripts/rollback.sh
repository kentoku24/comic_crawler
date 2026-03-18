#!/usr/bin/env bash
set -euo pipefail

APP_DIR=${APP_DIR:-/opt/myapp}
COMPOSE_FILE=${COMPOSE_FILE:-${APP_DIR}/docker-compose.yml}
ENV_FILE=${ENV_FILE:-${APP_DIR}/.env}

TARGET_IMAGE=${1:?usage: rollback.sh <image_ref_or_digest>}

if [ ! -f "$ENV_FILE" ]; then
  echo "ENV file not found: $ENV_FILE" >&2
  exit 1
fi

if grep -q '^APP_IMAGE=' "$ENV_FILE"; then
  sed -i "s|^APP_IMAGE=.*$|APP_IMAGE=${TARGET_IMAGE}|" "$ENV_FILE"
else
  echo "APP_IMAGE=${TARGET_IMAGE}" >> "$ENV_FILE"
fi

docker compose --project-directory "$APP_DIR" -f "$COMPOSE_FILE" pull app
docker compose --project-directory "$APP_DIR" -f "$COMPOSE_FILE" up -d app

echo "rollback completed: APP_IMAGE=${TARGET_IMAGE}"
