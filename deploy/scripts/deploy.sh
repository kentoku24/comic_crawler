#!/usr/bin/env bash
set -euo pipefail

APP_DIR=${APP_DIR:-/opt/myapp}
COMPOSE_FILE=${COMPOSE_FILE:-${APP_DIR}/docker-compose.yml}
ENV_FILE=${ENV_FILE:-${APP_DIR}/.env}
DEPLOY_LOG=${DEPLOY_LOG:-${APP_DIR}/deploy.log}
HEALTHCHECK_URL=${HEALTHCHECK_URL:-http://127.0.0.1:8080/health}
HEALTHCHECK_ATTEMPTS=${HEALTHCHECK_ATTEMPTS:-12}
HEALTHCHECK_SLEEP=${HEALTHCHECK_SLEEP:-5}

IMAGE_REF=${1:?usage: deploy.sh <image_ref> <version> <commit_sha> <image_digest>}
VERSION=${2:?usage: deploy.sh <image_ref> <version> <commit_sha> <image_digest>}
COMMIT_SHA=${3:?usage: deploy.sh <image_ref> <version> <commit_sha> <image_digest>}
IMAGE_DIGEST=${4:?usage: deploy.sh <image_ref> <version> <commit_sha> <image_digest>}
TARGET_IMAGE="${IMAGE_REF}@${IMAGE_DIGEST#@}"

mkdir -p "$APP_DIR"
touch "$DEPLOY_LOG"
exec > >(tee -a "$DEPLOY_LOG") 2>&1

log() {
  printf '[%s] %s\n' "$(date -Is)" "$*"
}

with_lock() {
  exec 9>"${APP_DIR}/deploy.lock"
  flock -n 9
}

set_app_image() {
  local value=$1
  if grep -q '^APP_IMAGE=' "$ENV_FILE"; then
    sed -i "s|^APP_IMAGE=.*$|APP_IMAGE=${value}|" "$ENV_FILE"
  else
    echo "APP_IMAGE=${value}" >> "$ENV_FILE"
  fi
}

rollback() {
  if [ -z "${PREV_APP_IMAGE:-}" ]; then
    log "No previous APP_IMAGE recorded; cannot rollback automatically"
    exit 1
  fi

  log "Rolling back to ${PREV_APP_IMAGE}"
  set_app_image "$PREV_APP_IMAGE"
  docker compose --project-directory "$APP_DIR" -f "$COMPOSE_FILE" pull app
  docker compose --project-directory "$APP_DIR" -f "$COMPOSE_FILE" up -d app
  log "Rollback completed"
}

if ! with_lock; then
  log "Another deployment is in progress"
  exit 1
fi

if [ ! -f "$COMPOSE_FILE" ]; then
  log "Compose file not found: $COMPOSE_FILE"
  exit 1
fi

if [ ! -f "$ENV_FILE" ]; then
  cat > "$ENV_FILE" <<'EOF'
APP_IMAGE=ghcr.io/example/myapp:bootstrap
TZ=Asia/Tokyo
EOF
fi

PREV_APP_IMAGE="$(awk -F= '$1=="APP_IMAGE"{print $2}' "$ENV_FILE" | tail -n 1)"
log "Previous APP_IMAGE=${PREV_APP_IMAGE:-<empty>}"
log "Deploying image=${IMAGE_REF} digest=${IMAGE_DIGEST} version=${VERSION} commit=${COMMIT_SHA}"

set_app_image "$TARGET_IMAGE"

docker compose --project-directory "$APP_DIR" -f "$COMPOSE_FILE" pull app

docker compose --project-directory "$APP_DIR" -f "$COMPOSE_FILE" up -d app

ok=0
for _ in $(seq 1 "$HEALTHCHECK_ATTEMPTS"); do
  if curl -fsS "$HEALTHCHECK_URL" >/dev/null; then
    ok=1
    break
  fi
  sleep "$HEALTHCHECK_SLEEP"
done

if [ "$ok" -ne 1 ]; then
  log "Healthcheck failed: ${HEALTHCHECK_URL}"
  rollback
  exit 1
fi

cat > "${APP_DIR}/current-release.json" <<EOF
{"image":"${IMAGE_REF}","digest":"${IMAGE_DIGEST}","version":"${VERSION}","commit":"${COMMIT_SHA}","deployed_at":"$(date -Is)"}
EOF

log "Deployment succeeded"
