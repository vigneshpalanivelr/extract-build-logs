#!/bin/bash
# Pipeline Logs Database Backup Script
#
# Usage: ./scripts/backup-database.sh [daily|weekly|monthly]
#
# This script automatically backs up the database (PostgreSQL or SQLite)
# and applies retention policies to keep disk usage manageable.

set -e

# Configuration
BACKUP_ROOT="${BACKUP_DIR:-./backups}"
RETENTION_DAILY=7
RETENTION_WEEKLY=4
RETENTION_MONTHLY=6

BACKUP_TYPE="${1:-daily}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="$BACKUP_ROOT/$BACKUP_TYPE"

# Create backup directory
mkdir -p "$BACKUP_DIR"

# Detect database type
DB_TYPE="sqlite"  # default
if [ -f .env ] && grep -q "^DATABASE_URL=" .env; then
    if [ -n "$(grep "^DATABASE_URL=" .env | grep -v "^DATABASE_URL=$")" ]; then
        DB_TYPE="postgresql"
    fi
fi

echo "==================================="
echo "Pipeline Logs Backup"
echo "Type: $BACKUP_TYPE"
echo "Database: $DB_TYPE"
echo "Date: $(date)"
echo "==================================="

# Perform backup based on database type
if [ "$DB_TYPE" = "postgresql" ]; then
    BACKUP_FILE="$BACKUP_DIR/postgres_${BACKUP_TYPE}_${TIMESTAMP}.sql.gz"

    echo "Backing up PostgreSQL database..."

    if command -v docker-compose &> /dev/null; then
        # Using docker-compose
        docker-compose exec -T postgres pg_dump -U logextractor pipeline_logs | \
            gzip > "$BACKUP_FILE"

        # Get database size
        DB_SIZE=$(docker-compose exec -T postgres psql -U logextractor -d pipeline_logs -t -c \
            "SELECT pg_size_pretty(pg_database_size('pipeline_logs'));" | tr -d '[:space:]')
    else
        echo "Error: docker-compose not found"
        exit 1
    fi

else
    # SQLite backup
    BACKUP_FILE="$BACKUP_DIR/sqlite_${BACKUP_TYPE}_${TIMESTAMP}.db.gz"

    echo "Backing up SQLite database..."

    if [ ! -f logs/pipeline-logs/monitoring.db ]; then
        echo "Error: SQLite database not found at logs/pipeline-logs/monitoring.db"
        exit 1
    fi

    # Create uncompressed backup first
    sqlite3 logs/pipeline-logs/monitoring.db ".backup ${BACKUP_FILE%.gz}"

    # Compress it
    gzip "${BACKUP_FILE%.gz}"

    # Get database size
    DB_SIZE=$(du -h logs/pipeline-logs/monitoring.db | cut -f1)
fi

# Check backup was created
if [ ! -f "$BACKUP_FILE" ]; then
    echo "Error: Backup file was not created!"
    exit 1
fi

BACKUP_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)

echo ""
echo "✓ Backup created: $BACKUP_FILE"
echo "✓ Database size: $DB_SIZE"
echo "✓ Backup size: $BACKUP_SIZE"
echo ""

# Apply retention policy
case $BACKUP_TYPE in
    daily)
        RETENTION=$RETENTION_DAILY
        ;;
    weekly)
        RETENTION=$RETENTION_WEEKLY
        ;;
    monthly)
        RETENTION=$RETENTION_MONTHLY
        ;;
    *)
        echo "Warning: Unknown backup type '$BACKUP_TYPE', keeping all backups"
        RETENTION=999999
        ;;
esac

echo "Applying retention policy: keep last $RETENTION backups"

# Count current backups
BACKUP_COUNT=$(ls -1 "$BACKUP_DIR"/*.gz 2>/dev/null | wc -l)
echo "Current backups in $BACKUP_DIR: $BACKUP_COUNT"

# Delete old backups if over retention limit
if [ $BACKUP_COUNT -gt $RETENTION ]; then
    DELETED=0
    ls -t "$BACKUP_DIR"/*.gz | tail -n +$((RETENTION + 1)) | while read old_backup; do
        echo "  Deleting old backup: $(basename $old_backup)"
        rm "$old_backup"
        DELETED=$((DELETED + 1))
    done
    echo "✓ Cleaned up old backups"
else
    echo "✓ No cleanup needed (under retention limit)"
fi

# Calculate total backup size
TOTAL_SIZE=$(du -sh "$BACKUP_ROOT" | cut -f1)
echo "✓ Total backup directory size: $TOTAL_SIZE"

# Log to syslog if available
if command -v logger &> /dev/null; then
    logger -t pipeline-logs-backup "Backup completed: $BACKUP_FILE ($BACKUP_SIZE)"
fi

echo "==================================="
echo "Backup completed successfully!"
echo "==================================="

exit 0
