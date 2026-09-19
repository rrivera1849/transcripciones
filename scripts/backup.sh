#!/usr/bin/env bash
# Nightly backup of the database (users, jobs, transcripts, search index).
# Audio is deliberately NOT backed up: it is transient by design.
#   crontab: 15 3 * * * /opt/transcripciones/scripts/backup.sh >> /var/log/transcripciones-backup.log 2>&1
set -euo pipefail
cd "$(dirname "$0")/.."
BACKUP_DIR="${BACKUP_DIR:-./backups}"
KEEP_DAYS="${BACKUP_KEEP_DAYS:-60}"
mkdir -p "$BACKUP_DIR"
stamp="$(date +%Y%m%d-%H%M%S)"
out="$BACKUP_DIR/app-$stamp.sqlite3"
# Online, consistent copy through SQLite's backup API (safe while the app runs).
docker compose exec -T web sqlite3 /data/app.sqlite3 ".backup /data/backup-tmp.sqlite3"
mv data/backup-tmp.sqlite3 "$out"
gzip -f "$out"
find "$BACKUP_DIR" -name 'app-*.sqlite3.gz' -mtime +"$KEEP_DAYS" -delete
echo "backup written: $out.gz ($(du -h "$out.gz" | cut -f1))"
# Off-site copy (optional): install rclone, configure a remote named `b2`, then uncomment:
# rclone copy "$BACKUP_DIR" b2:transcripciones-backups --include 'app-*.sqlite3.gz'
