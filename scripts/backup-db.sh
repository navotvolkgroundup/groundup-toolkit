#!/bin/bash
# SQLite Backup — safe backup of founder-scout database
# Uses SQLite .backup command for consistent snapshot even during writes.
# Retains 14 days of backups.
#
# Usage: scripts/backup-db.sh
# Cron:  0 3 * * * $TOOLKIT_ROOT/scripts/backup-db.sh >> /var/log/daily-maintenance.log 2>&1

set -e

TOOLKIT_ROOT="${TOOLKIT_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
DB_PATH="$TOOLKIT_ROOT/skills/founder-scout/data/founder-scout.db"
BACKUP_DIR="$TOOLKIT_ROOT/data/backups"
RETENTION_DAYS=14

TIMESTAMP=$(date -u +'%Y-%m-%dT%H:%M:%SZ')
DATE_TAG=$(date -u +'%Y%m%d')

log() { echo "[$TIMESTAMP] DB Backup: $1"; }

if [ ! -f "$DB_PATH" ]; then
    log "Database not found at $DB_PATH — skipping"
    exit 0
fi

mkdir -p "$BACKUP_DIR"

BACKUP_FILE="$BACKUP_DIR/founder-scout-${DATE_TAG}.db"

if [ -f "$BACKUP_FILE" ]; then
    log "Backup already exists for today — skipping"
    exit 0
fi

log "Backing up $DB_PATH → $BACKUP_FILE"
sqlite3 "$DB_PATH" ".backup '$BACKUP_FILE'"

# Verify backup is non-empty
if [ ! -s "$BACKUP_FILE" ]; then
    log "FAIL: Backup file is empty"
    rm -f "$BACKUP_FILE"
    exit 1
fi

SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
log "Backup complete ($SIZE)"

# Clean up old backups
DELETED=0
find "$BACKUP_DIR" -name 'founder-scout-*.db' -mtime +$RETENTION_DAYS -delete 2>/dev/null && \
    DELETED=$(find "$BACKUP_DIR" -name 'founder-scout-*.db' | wc -l)
log "Retained backups: $(ls "$BACKUP_DIR"/founder-scout-*.db 2>/dev/null | wc -l)"
