#!/usr/bin/env bash
# Update the running stack on the VPS to the latest commit of the deploy branch.
#   sudo /opt/transcripciones/scripts/deploy.sh
set -euo pipefail
cd "$(dirname "$0")/.."
# Default to whatever branch the VPS already tracks (the repo has no "main").
BRANCH="${DEPLOY_BRANCH:-$(git rev-parse --abbrev-ref HEAD)}"
git fetch --quiet origin "$BRANCH"
git checkout --quiet "$BRANCH"
git reset --quiet --hard "origin/$BRANCH"
docker compose build --pull --quiet
docker compose up -d --remove-orphans
docker image prune -f >/dev/null
echo "deployed $(git rev-parse --short HEAD) at $(date -Is)"
docker compose ps
