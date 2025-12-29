#!/bin/bash
# Database Management Script (SQLite Only)
#
# Usage:
#   ./scripts/manage_database.sh backup [daily|weekly|monthly]
#   ./scripts/manage_database.sh restore <backup-file>
#   ./scripts/manage_database.sh check
#   ./scripts/manage_database.sh list
#
# This script manages SQLite database backup, restore, and health checks

set -e

# Configuration
BACKUP_ROOT="${BACKUP_DIR:-./backups}"
RETENTION_DAILY=7
RETENTION_WEEKLY=4
RETENTION_MONTHLY=6

# SQLite Database Configuration
SQLITE_DB="logs/monitoring.db"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Print colored output
print_success() {
    echo -e "${GREEN}$1${NC}"
}

print_error() {
    echo -e "${RED}$1${NC}"
}

print_warning() {
    echo -e "${YELLOW}$1${NC}"
}

# Check if SQLite database exists
check_db_exists() {
    if [ ! -f "$SQLITE_DB" ]; then
        print_error "Database not found: $SQLITE_DB"
        return 1
    fi
    return 0
}

# ============================================================================
# BACKUP OPERATIONS
# ============================================================================

backup_sqlite() {
    local backup_type="${1:-manual}"
    local backup_dir="$BACKUP_ROOT/$backup_type"
    
    mkdir -p "$backup_dir"
    
    local timestamp=$(date +%Y%m%d_%H%M%S)
    local backup_file="$backup_dir/sqlite_${timestamp}.db"
    
    echo "==================================="
    echo "SQLite Backup ($backup_type)"
    echo "==================================="
    
    if ! check_db_exists; then
        exit 1
    fi
    
    # Online backup using SQLite's .backup command
    sqlite3 "$SQLITE_DB" ".backup '$backup_file'"
    
    if [ -f "$backup_file" ]; then
        local size=$(du -h "$backup_file" | cut -f1)
        print_success "Backup completed: $backup_file ($size)"
        
        # Apply retention policy
        apply_retention "$backup_type" "$backup_dir"
    else
        print_error "Backup failed"
        exit 1
    fi
}

apply_retention() {
    local backup_type="$1"
    local backup_dir="$2"
    local retention_days
    
    case "$backup_type" in
        daily)
            retention_days=$RETENTION_DAILY
            ;;
        weekly)
            retention_days=$((RETENTION_WEEKLY * 7))
            ;;
        monthly)
            retention_days=$((RETENTION_MONTHLY * 30))
            ;;
        *)
            return 0
            ;;
    esac
    
    echo "Applying retention policy: keep last $retention_days days"
    
    # Find and delete old backups
    local deleted=0
    while IFS= read -r -d '' file; do
        rm -f "$file"
        ((deleted++))
    done < <(find "$backup_dir" -name "*.db" -type f -mtime +$retention_days -print0)
    
    if [ $deleted -gt 0 ]; then
        echo "Deleted $deleted old backup(s)"
    fi
}

# ============================================================================
# RESTORE OPERATIONS
# ============================================================================

restore_sqlite() {
    local backup_file="$1"
    
    if [ -z "$backup_file" ]; then
        print_error "Usage: $0 restore <backup-file>"
        exit 1
    fi
    
    if [ ! -f "$backup_file" ]; then
        print_error "Backup file not found: $backup_file"
        exit 1
    fi
    
    echo "==================================="
    echo "SQLite Restore"
    echo "==================================="
    echo "Backup file: $backup_file"
    echo "Target: $SQLITE_DB"
    echo ""
    
    # Create backup of current database
    if [ -f "$SQLITE_DB" ]; then
        local current_backup="${SQLITE_DB}.before_restore_$(date +%Y%m%d_%H%M%S)"
        cp "$SQLITE_DB" "$current_backup"
        print_success "Current database backed up to: $current_backup"
    fi
    
    # Restore from backup
    cp "$backup_file" "$SQLITE_DB"
    
    # Remove WAL files
    rm -f "${SQLITE_DB}-wal" "${SQLITE_DB}-shm"
    
    print_success "Database restored successfully"
    
    # Verify integrity
    echo ""
    check_integrity
}

# ============================================================================
# HEALTH CHECK OPERATIONS
# ============================================================================

check_integrity() {
    echo "Running integrity check..."
    
    if ! check_db_exists; then
        return 1
    fi
    
    local result=$(sqlite3 "$SQLITE_DB" "PRAGMA integrity_check;")
    
    if [ "$result" = "ok" ]; then
        print_success "Integrity check: PASSED"
        return 0
    else
        print_error "Integrity check: FAILED"
        echo "$result"
        return 1
    fi
}

health_check() {
    echo "==================================="
    echo "Database Health Check"
    echo "Type: sqlite"
    echo "Date: $(date)"
    echo "==================================="
    echo ""
    
    echo "SQLite Health Check"
    echo "-------------------"
    
    # Check if database exists
    if ! check_db_exists; then
        print_error "Database not found"
        exit 1
    fi
    
    print_success "Database file: OK"
    
    # Check database connection
    if sqlite3 "$SQLITE_DB" "SELECT 1;" > /dev/null 2>&1; then
        print_success "Database connection: OK"
    else
        print_error "Database connection: FAILED"
        exit 1
    fi
    
    # Check tables exist
    if sqlite3 "$SQLITE_DB" "SELECT name FROM sqlite_master WHERE type='table' AND name='requests';" | grep -q "requests"; then
        local row_count=$(sqlite3 "$SQLITE_DB" "SELECT COUNT(*) FROM requests;")
        print_success "Requests table: OK ($row_count rows)"
    else
        print_error "Requests table: NOT FOUND"
        exit 1
    fi
    
    # Check recent activity
    local recent=$(sqlite3 "$SQLITE_DB" "SELECT COUNT(*) FROM requests WHERE timestamp > datetime('now', '-1 hour');")
    print_success "Recent activity (last hour): $recent requests"
    
    # Check database size
    if [ -f "$SQLITE_DB" ]; then
        local size=$(du -h "$SQLITE_DB" | cut -f1)
        print_success "Database size: $size"
    fi
    
    # Check integrity
    check_integrity
    
    # Check WAL mode
    local journal_mode=$(sqlite3 "$SQLITE_DB" "PRAGMA journal_mode;")
    if [ "$journal_mode" = "wal" ]; then
        print_success "WAL mode: Enabled"
    else
        print_warning "WAL mode: Disabled (currently: $journal_mode)"
    fi
    
    echo ""
    echo "==================================="
    print_success "Health Check: PASSED"
    echo "==================================="
}

# ============================================================================
# LIST OPERATIONS
# ============================================================================

list_backups() {
    echo "==================================="
    echo "Available Backups"
    echo "==================================="
    echo ""
    
    local found_backups=false
    
    for backup_type in daily weekly monthly manual; do
        local backup_dir="$BACKUP_ROOT/$backup_type"
        if [ -d "$backup_dir" ]; then
            local count=$(find "$backup_dir" -name "*.db" -type f 2>/dev/null | wc -l)
            if [ $count -gt 0 ]; then
                echo "[$backup_type backups]"
                find "$backup_dir" -name "*.db" -type f -printf "%TY-%Tm-%Td %TH:%TM  %s bytes  %p\n" | sort -r
                echo ""
                found_backups=true
            fi
        fi
    done
    
    if [ "$found_backups" = false ]; then
        echo "No backups found in $BACKUP_ROOT"
    fi
}

# ============================================================================
# MAIN
# ============================================================================

show_usage() {
    cat << 'USAGE'
SQLite Database Management Script

USAGE:
    ./scripts/manage_database.sh <command> [options]

COMMANDS:
    backup [daily|weekly|monthly]   Create database backup
    restore <backup-file>           Restore database from backup
    check                           Run health check
    list                            List available backups

EXAMPLES:
    # Create daily backup
    ./scripts/manage_database.sh backup daily
    
    # Create manual backup
    ./scripts/manage_database.sh backup
    
    # Restore from backup
    ./scripts/manage_database.sh restore backups/daily/sqlite_20250129_120000.db
    
    # Run health check
    ./scripts/manage_database.sh check
    
    # List all backups
    ./scripts/manage_database.sh list

BACKUP RETENTION:
    Daily:   7 days
    Weekly:  4 weeks
    Monthly: 6 months
USAGE
}

# Main command handler
case "${1:-help}" in
    backup)
        backup_sqlite "${2:-manual}"
        ;;
    restore)
        restore_sqlite "$2"
        ;;
    check)
        health_check
        ;;
    list)
        list_backups
        ;;
    help|--help|-h)
        show_usage
        ;;
    *)
        print_error "Unknown command: $1"
        echo ""
        show_usage
        exit 1
        ;;
esac
