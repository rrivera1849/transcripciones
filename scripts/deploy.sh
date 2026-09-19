#!/usr/bin/env bash
# Update the running stack on the VPS to the latest commit of the deploy branch.
#   sudo /opt/transcripciones/scripts/deploy.sh
set -euo pipefail
cd "$(dirname "$0")/.."
BRANCH="${DEPLOY_BRANCH:-main}"
git fetch --quiet origin "$BRANCH"
git checkout --quiet "$BRANCH"
git reset --quiet --hard "origin/$BRANCH"
docker compose build --pull --quiet
docker compose up -d --remove-orphans
docker image prune -f >/dev/null
echo "deployed $(git rev-parse --short HEAD) at $(date -Is)"
docker compose ps
