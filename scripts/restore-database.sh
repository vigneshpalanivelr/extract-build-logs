#!/bin/bash
# Pipeline Logs Database Restore Script
#
# Usage: ./scripts/restore-database.sh <backup-file>
#
# Example:
#   ./scripts/restore-database.sh backups/daily/postgres_daily_20250105_020000.sql.gz
#   ./scripts/restore-database.sh backups/daily/sqlite_daily_20250105_020000.db.gz

set -e

if [ $# -eq 0 ]; then
    echo "Usage: $0 <backup-file>"
    echo ""
    echo "Available backups:"
    echo ""
    find backups -name "*.gz" -type f | sort -r | head -10
    exit 1
fi

BACKUP_FILE="$1"

if [ ! -f "$BACKUP_FILE" ]; then
    echo "Error: Backup file not found: $BACKUP_FILE"
    exit 1
fi

# Detect backup type from filename
if [[ "$BACKUP_FILE" == *"postgres"* ]]; then
    DB_TYPE="postgresql"
elif [[ "$BACKUP_FILE" == *"sqlite"* ]]; then
    DB_TYPE="sqlite"
else
    echo "Error: Cannot determine database type from filename"
    echo "Filename should contain 'postgres' or 'sqlite'"
    exit 1
fi

echo "==================================="
echo "Pipeline Logs Database Restore"
echo "Backup file: $BACKUP_FILE"
echo "Database type: $DB_TYPE"
echo "Date: $(date)"
echo "==================================="
echo ""

# Confirm before proceeding
read -p "!  This will REPLACE the current database. Continue? (yes/no): " CONFIRM

if [ "$CONFIRM" != "yes" ]; then
    echo "Restore cancelled."
    exit 0
fi

echo ""

if [ "$DB_TYPE" = "postgresql" ]; then
    echo "Restoring PostgreSQL database..."
    echo ""

    # Stop the application
    echo "1. Stopping log-extractor service..."
    if command -v docker-compose &> /dev/null; then
        docker-compose stop log-extractor
    fi

    # Drop and recreate database
    echo "2. Dropping existing database..."
    docker-compose exec -T postgres psql -U logextractor -c "DROP DATABASE IF EXISTS pipeline_logs;"

    echo "3. Creating fresh database..."
    docker-compose exec -T postgres psql -U logextractor -c "CREATE DATABASE pipeline_logs;"

    # Restore from backup
    echo "4. Restoring from backup..."
    if [[ "$BACKUP_FILE" == *.gz ]]; then
        gunzip -c "$BACKUP_FILE" | docker-compose exec -T postgres psql -U logextractor pipeline_logs
    else
        docker-compose exec -T postgres psql -U logextractor pipeline_logs < "$BACKUP_FILE"
    fi

    # Verify restore
    echo "5. Verifying restore..."
    ROW_COUNT=$(docker-compose exec -T postgres psql -U logextractor -d pipeline_logs -t -c "SELECT COUNT(*) FROM requests;" | tr -d '[:space:]')
    echo "   Restored $ROW_COUNT requests"

    # Start the application
    echo "6. Starting log-extractor service..."
    docker-compose start log-extractor

else
    # SQLite restore
    echo "Restoring SQLite database..."
    echo ""

    # Stop the application
    echo "1. Stopping service..."
    if [ -f manage_container.py ]; then
        python3 manage_container.py stop || ./manage_container.py stop
    fi

    # Backup current database (just in case)
    if [ -f logs/pipeline-logs/monitoring.db ]; then
        echo "2. Backing up current database..."
        cp logs/pipeline-logs/monitoring.db "logs/pipeline-logs/monitoring.db.before_restore_$(date +%Y%m%d_%H%M%S)"
    fi

    # Remove current database files
    echo "3. Removing current database files..."
    rm -f logs/pipeline-logs/monitoring.db*

    # Restore from backup
    echo "4. Restoring from backup..."
    if [[ "$BACKUP_FILE" == *.gz ]]; then
        gunzip -c "$BACKUP_FILE" > logs/pipeline-logs/monitoring.db
    else
        cp "$BACKUP_FILE" logs/pipeline-logs/monitoring.db
    fi

    # Verify restore
    echo "5. Verifying restore..."
    if sqlite3 logs/pipeline-logs/monitoring.db "PRAGMA integrity_check;" | grep -q "ok"; then
        echo "   ✓ Database integrity: OK"
    else
        echo "   ✗ Database integrity check failed!"
        exit 1
    fi

    ROW_COUNT=$(sqlite3 logs/pipeline-logs/monitoring.db "SELECT COUNT(*) FROM requests;")
    echo "   Restored $ROW_COUNT requests"

    # Start the application
    echo "6. Starting service..."
    if [ -f manage_container.py ]; then
        python3 manage_container.py start || ./manage_container.py start
    fi
fi

echo ""
echo "==================================="
echo "✓ Restore completed successfully!"
echo "==================================="
echo ""
echo "Next steps:"
echo "1. Check application logs: docker-compose logs -f log-extractor"
echo "2. Verify health: curl http://localhost:8000/health"
echo "3. Check data: Query the database to verify data is correct"

exit 0
