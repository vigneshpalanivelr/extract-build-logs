#!/bin/bash
# Database Health Check Script
#
# Usage: ./scripts/check-db-health.sh
#
# Returns exit code 0 if healthy, non-zero if problems detected

set -e

# Detect database type
DB_TYPE="sqlite"
if [ -f .env ] && grep -q "^DATABASE_URL=" .env; then
    if [ -n "$(grep "^DATABASE_URL=" .env | grep -v "^DATABASE_URL=$")" ]; then
        DB_TYPE="postgresql"
    fi
fi

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
