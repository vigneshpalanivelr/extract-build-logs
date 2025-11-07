#!/bin/bash
# Database Management Script
#
# Usage:
#   ./scripts/manage_database.sh backup [daily|weekly|monthly]
#   ./scripts/manage_database.sh restore <backup-file>
#   ./scripts/manage_database.sh check
#   ./scripts/manage_database.sh list
#
# This script manages database backup, restore, and health checks
# for both PostgreSQL and SQLite databases.

set -e

# Configuration
BACKUP_ROOT="${BACKUP_DIR:-./backups}"
RETENTION_DAILY=7
RETENTION_WEEKLY=4
RETENTION_MONTHLY=6

# Detect database type
detect_db_type() {
    DB_TYPE="sqlite"  # default
    if [ -f .env ] && grep -q "^DATABASE_URL=" .env; then
        if [ -n "$(grep "^DATABASE_URL=" .env | grep -v "^DATABASE_URL=$")" ]; then
            DB_TYPE="postgresql"
        fi
    fi
}

# ============================================================================
# BACKUP FUNCTION
# ============================================================================

backup_database() {
    BACKUP_TYPE="${1:-daily}"
    TIMESTAMP=$(date +%Y%m%d_%H%M%S)
    BACKUP_DIR="$BACKUP_ROOT/$BACKUP_TYPE"

    # Create backup directory
    mkdir -p "$BACKUP_DIR"

    detect_db_type

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
}

# ============================================================================
# RESTORE FUNCTION
# ============================================================================

restore_database() {
    if [ $# -eq 0 ]; then
        echo "Usage: $0 restore <backup-file>"
        echo ""
        echo "Available backups:"
        echo ""
        find backups -name "*.gz" -type f 2>/dev/null | sort -r | head -10
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
    read -p "⚠  This will REPLACE the current database. Continue? (yes/no): " CONFIRM

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
}

# ============================================================================
# HEALTH CHECK FUNCTION
# ============================================================================

check_database() {
    detect_db_type

    echo "==================================="
    echo "Database Health Check"
    echo "Type: $DB_TYPE"
    echo "Date: $(date)"
    echo "==================================="
    echo ""

    EXIT_CODE=0

    if [ "$DB_TYPE" = "postgresql" ]; then
        echo "PostgreSQL Health Check"
        echo "-----------------------"

        # Connection test
        echo -n "Database connection: "
        if docker-compose exec -T postgres pg_isready -U logextractor > /dev/null 2>&1; then
            echo "✓ OK"
        else
            echo "✗ FAILED"
            EXIT_CODE=1
        fi

        # Table exists
        echo -n "Requests table: "
        if docker-compose exec -T postgres psql -U logextractor -d pipeline_logs -t -c \
            "SELECT COUNT(*) FROM requests;" > /dev/null 2>&1; then
            ROW_COUNT=$(docker-compose exec -T postgres psql -U logextractor -d pipeline_logs -t -c \
                "SELECT COUNT(*) FROM requests;" | tr -d '[:space:]')
            echo "✓ OK ($ROW_COUNT rows)"
        else
            echo "✗ FAILED"
            EXIT_CODE=1
        fi

        # Recent activity
        echo -n "Recent activity (last hour): "
        RECENT=$(docker-compose exec -T postgres psql -U logextractor -d pipeline_logs -t -c \
            "SELECT COUNT(*) FROM requests WHERE timestamp > NOW() - INTERVAL '1 hour';" | tr -d '[:space:]')
        echo "✓ $RECENT requests"

        # Database size
        echo -n "Database size: "
        DB_SIZE=$(docker-compose exec -T postgres psql -U logextractor -d pipeline_logs -t -c \
            "SELECT pg_size_pretty(pg_database_size('pipeline_logs'));" | tr -d '[:space:]')
        echo "✓ $DB_SIZE"

        # Active connections
        echo -n "Active connections: "
        CONNECTIONS=$(docker-compose exec -T postgres psql -U logextractor -d pipeline_logs -t -c \
            "SELECT count(*) FROM pg_stat_activity WHERE datname='pipeline_logs';" | tr -d '[:space:]')
        echo "✓ $CONNECTIONS"

        # Autovacuum status
        echo -n "Last autovacuum: "
        LAST_VACUUM=$(docker-compose exec -T postgres psql -U logextractor -d pipeline_logs -t -c \
            "SELECT COALESCE(last_autovacuum::text, 'never') FROM pg_stat_user_tables WHERE tablename='requests';" | tr -d '[:space:]')
        echo "✓ $LAST_VACUUM"

    else
        echo "SQLite Health Check"
        echo "-------------------"

        # File exists
        echo -n "Database file: "
        if [ -f logs/pipeline-logs/monitoring.db ]; then
            echo "✓ EXISTS"
        else
            echo "✗ NOT FOUND"
            EXIT_CODE=1
            exit $EXIT_CODE
        fi

        # Integrity check
        echo -n "Database integrity: "
        if sqlite3 logs/pipeline-logs/monitoring.db "PRAGMA integrity_check;" 2>/dev/null | grep -q "ok"; then
            echo "✓ OK"
        else
            echo "✗ FAILED"
            EXIT_CODE=1
        fi

        # Row count
        echo -n "Total requests: "
        ROW_COUNT=$(sqlite3 logs/pipeline-logs/monitoring.db "SELECT COUNT(*) FROM requests;" 2>/dev/null || echo "ERROR")
        if [ "$ROW_COUNT" != "ERROR" ]; then
            echo "✓ $ROW_COUNT"
        else
            echo "✗ FAILED"
            EXIT_CODE=1
        fi

        # Recent activity
        echo -n "Recent activity (last hour): "
        RECENT=$(sqlite3 logs/pipeline-logs/monitoring.db \
            "SELECT COUNT(*) FROM requests WHERE timestamp > datetime('now', '-1 hour');" 2>/dev/null || echo "0")
        echo "✓ $RECENT requests"

        # Database size
        echo -n "Database size: "
        DB_SIZE=$(du -h logs/pipeline-logs/monitoring.db | cut -f1)
        echo "✓ $DB_SIZE"

        # WAL mode
        echo -n "Journal mode: "
        WAL_MODE=$(sqlite3 logs/pipeline-logs/monitoring.db "PRAGMA journal_mode;" 2>/dev/null)
        if [ "$WAL_MODE" = "wal" ]; then
            echo "✓ WAL"
        else
            echo "⚠ $WAL_MODE (should be WAL)"
        fi

        # WAL file size (if exists)
        if [ -f logs/pipeline-logs/monitoring.db-wal ]; then
            WAL_SIZE=$(du -h logs/pipeline-logs/monitoring.db-wal | cut -f1)
            echo "WAL file size: ✓ $WAL_SIZE"
        fi
    fi

    echo ""
    echo "==================================="
    if [ $EXIT_CODE -eq 0 ]; then
        echo "✓ Health Check: PASSED"
    else
        echo "✗ Health Check: FAILED"
    fi
    echo "==================================="

    exit $EXIT_CODE
}

# ============================================================================
# LIST BACKUPS FUNCTION
# ============================================================================

list_backups() {
    echo "==================================="
    echo "Available Backups"
    echo "==================================="
    echo ""

    if [ ! -d "$BACKUP_ROOT" ]; then
        echo "No backups found (directory doesn't exist: $BACKUP_ROOT)"
        exit 0
    fi

    for backup_type in daily weekly monthly; do
        BACKUP_DIR="$BACKUP_ROOT/$backup_type"
        if [ -d "$BACKUP_DIR" ]; then
            BACKUP_COUNT=$(ls -1 "$BACKUP_DIR"/*.gz 2>/dev/null | wc -l)
            if [ $BACKUP_COUNT -gt 0 ]; then
                echo "[$backup_type backups] ($BACKUP_COUNT files)"
                echo "----------------------------------------"
                ls -lht "$BACKUP_DIR"/*.gz | head -5 | awk '{printf "  %s %s %s - %s\n", $6, $7, $8, $9}'
                if [ $BACKUP_COUNT -gt 5 ]; then
                    echo "  ... and $((BACKUP_COUNT - 5)) more"
                fi
                echo ""
            fi
        fi
    done

    # Show total size
    if [ -d "$BACKUP_ROOT" ]; then
        TOTAL_SIZE=$(du -sh "$BACKUP_ROOT" 2>/dev/null | cut -f1)
        echo "Total backup size: $TOTAL_SIZE"
    fi
}

# ============================================================================
# MAIN DISPATCH
# ============================================================================

show_usage() {
    echo "Database Management Script"
    echo ""
    echo "Usage:"
    echo "  $0 backup [daily|weekly|monthly]  - Create database backup"
    echo "  $0 restore <backup-file>           - Restore database from backup"
    echo "  $0 check                           - Run health check"
    echo "  $0 list                            - List available backups"
    echo ""
    echo "Examples:"
    echo "  $0 backup daily"
    echo "  $0 restore backups/daily/postgres_daily_20250107_020000.sql.gz"
    echo "  $0 check"
    echo "  $0 list"
    echo ""
}

# Main command dispatch
COMMAND="${1:-}"

case "$COMMAND" in
    backup)
        shift
        backup_database "$@"
        ;;
    restore)
        shift
        restore_database "$@"
        ;;
    check)
        check_database
        ;;
    list)
        list_backups
        ;;
    -h|--help|help)
        show_usage
        exit 0
        ;;
    *)
        echo "Error: Unknown command '$COMMAND'"
        echo ""
        show_usage
        exit 1
        ;;
esac

exit 0
