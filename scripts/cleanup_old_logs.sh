#!/bin/bash

################################################################################
# Log Cleanup Script for GitLab & Jenkins Pipeline Log Extraction System
#
# This script cleans up old pipeline/build logs based on retention period.
#
# Usage:
#   ./cleanup_old_logs.sh [options]
#
# Options:
#   --dry-run            Show what would be deleted without actually deleting
#   --days N             Override retention days (default: from .env or 90)
#   --gitlab-only        Clean only GitLab logs
#   --jenkins-only       Clean only Jenkins logs
#   --verbose            Show detailed output
#   --help               Show this help message
#
# Environment Variables (from .env):
#   LOG_RETENTION_DAYS   Number of days to retain logs (default: 90)
#   LOG_OUTPUT_DIR       Log directory path (default: ./logs)
#
################################################################################

set -euo pipefail

# Default values
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
LOG_DIR="${LOG_OUTPUT_DIR:-./logs}"
RETENTION_DAYS="${LOG_RETENTION_DAYS:-90}"
DRY_RUN=false
VERBOSE=false
CLEAN_GITLAB=true
CLEAN_JENKINS=true

# Counters
GITLAB_DIRS_DELETED=0
JENKINS_DIRS_DELETED=0
TOTAL_SIZE_FREED=0

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Functions
print_help() {
    sed -n '2,/^$/p' "$0" | sed 's/^# \?//'
    exit 0
}

log_info() {
    echo -e "${BLUE}[INFO]${NC} $*"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $*"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $*"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $*"
}

log_verbose() {
    if [ "$VERBOSE" = true ]; then
        echo -e "${BLUE}[DEBUG]${NC} $*"
    fi
}

# Load environment variables from .env if it exists
load_env() {
    local env_file="$PROJECT_ROOT/.env"
    if [ -f "$env_file" ]; then
        log_verbose "Loading configuration from $env_file"
        # Export variables from .env
        set -a
        # shellcheck disable=SC1090
        source <(grep -E '^(LOG_RETENTION_DAYS|LOG_OUTPUT_DIR)=' "$env_file" | sed 's/^/export /')
        set +a

        # Update variables if set in .env
        LOG_DIR="${LOG_OUTPUT_DIR:-$LOG_DIR}"
        RETENTION_DAYS="${LOG_RETENTION_DAYS:-$RETENTION_DAYS}"
    else
        log_warning ".env file not found, using defaults"
    fi
}

# Get directory size in bytes
get_dir_size() {
    local dir="$1"
    if [ -d "$dir" ]; then
        du -sb "$dir" 2>/dev/null | cut -f1
    else
        echo "0"
    fi
}

# Format bytes to human readable
format_bytes() {
    local bytes=$1
    if [ "$bytes" -lt 1024 ]; then
        echo "${bytes}B"
    elif [ "$bytes" -lt 1048576 ]; then
        echo "$(( bytes / 1024 ))KB"
    elif [ "$bytes" -lt 1073741824 ]; then
        echo "$(( bytes / 1048576 ))MB"
    else
        echo "$(( bytes / 1073741824 ))GB"
    fi
}

# Clean GitLab pipeline logs
clean_gitlab_logs() {
    log_info "Cleaning GitLab pipeline logs older than ${RETENTION_DAYS} days..."

    local base_dir="$LOG_DIR"

    if [ ! -d "$base_dir" ]; then
        log_warning "GitLab log directory does not exist: $base_dir"
        return
    fi

    # Find project directories (format: {project-name}_{id})
    local project_count=0
    local pipeline_count=0

    while IFS= read -r -d '' project_dir; do
        ((project_count++)) || true

        # Find pipeline directories inside project (format: pipeline_{id})
        while IFS= read -r -d '' pipeline_dir; do
            # Check if directory is older than retention days
            local dir_age_days
            dir_age_days=$(find "$pipeline_dir" -maxdepth 0 -type d -mtime +"$RETENTION_DAYS" | wc -l)

            if [ "$dir_age_days" -gt 0 ]; then
                local dir_size
                dir_size=$(get_dir_size "$pipeline_dir")

                log_verbose "Found old GitLab pipeline: $pipeline_dir ($(format_bytes "$dir_size"))"

                if [ "$DRY_RUN" = true ]; then
                    echo "[DRY RUN] Would delete: $pipeline_dir"
                else
                    rm -rf "$pipeline_dir"
                    log_verbose "Deleted: $pipeline_dir"
                fi

                ((GITLAB_DIRS_DELETED++)) || true
                TOTAL_SIZE_FREED=$((TOTAL_SIZE_FREED + dir_size))
                ((pipeline_count++)) || true
            fi
        done < <(find "$project_dir" -maxdepth 1 -type d -name "pipeline_*" -print0 2>/dev/null)

        # Remove empty project directories
        if [ -d "$project_dir" ] && [ -z "$(ls -A "$project_dir" 2>/dev/null)" ]; then
            if [ "$DRY_RUN" = true ]; then
                echo "[DRY RUN] Would delete empty project dir: $project_dir"
            else
                rmdir "$project_dir"
                log_verbose "Deleted empty project directory: $project_dir"
            fi
        fi
    done < <(find "$base_dir" -maxdepth 1 -type d -name "*_*" ! -name "jenkins-builds" -print0 2>/dev/null)

    if [ "$pipeline_count" -gt 0 ]; then
        log_success "Cleaned $GITLAB_DIRS_DELETED GitLab pipeline directories"
    else
        log_info "No GitLab pipelines older than ${RETENTION_DAYS} days found"
    fi
}

# Clean Jenkins build logs
clean_jenkins_logs() {
    log_info "Cleaning Jenkins build logs older than ${RETENTION_DAYS} days..."

    local jenkins_base="$LOG_DIR/jenkins-builds"

    if [ ! -d "$jenkins_base" ]; then
        log_warning "Jenkins log directory does not exist: $jenkins_base"
        return
    fi

    # Find job directories
    local job_count=0
    local build_count=0

    while IFS= read -r -d '' job_dir; do
        ((job_count++)) || true

        # Find build directories (numeric directories)
        while IFS= read -r -d '' build_dir; do
            # Check if directory is older than retention days
            local dir_age_days
            dir_age_days=$(find "$build_dir" -maxdepth 0 -type d -mtime +"$RETENTION_DAYS" | wc -l)

            if [ "$dir_age_days" -gt 0 ]; then
                local dir_size
                dir_size=$(get_dir_size "$build_dir")

                log_verbose "Found old Jenkins build: $build_dir ($(format_bytes "$dir_size"))"

                if [ "$DRY_RUN" = true ]; then
                    echo "[DRY RUN] Would delete: $build_dir"
                else
                    rm -rf "$build_dir"
                    log_verbose "Deleted: $build_dir"
                fi

                ((JENKINS_DIRS_DELETED++)) || true
                TOTAL_SIZE_FREED=$((TOTAL_SIZE_FREED + dir_size))
                ((build_count++)) || true
            fi
        done < <(find "$job_dir" -maxdepth 1 -type d -regex '.*/[0-9]+$' -print0 2>/dev/null)

        # Remove empty job directories
        if [ -d "$job_dir" ] && [ -z "$(ls -A "$job_dir" 2>/dev/null)" ]; then
            if [ "$DRY_RUN" = true ]; then
                echo "[DRY RUN] Would delete empty job dir: $job_dir"
            else
                rmdir "$job_dir"
                log_verbose "Deleted empty job directory: $job_dir"
            fi
        fi
    done < <(find "$jenkins_base" -maxdepth 1 -type d ! -path "$jenkins_base" -print0 2>/dev/null)

    if [ "$build_count" -gt 0 ]; then
        log_success "Cleaned $JENKINS_DIRS_DELETED Jenkins build directories"
    else
        log_info "No Jenkins builds older than ${RETENTION_DAYS} days found"
    fi
}

# Print summary
print_summary() {
    echo ""
    echo "=========================================="
    echo "Cleanup Summary"
    echo "=========================================="
    echo "Retention period:      ${RETENTION_DAYS} days"
    echo "GitLab pipelines:      $GITLAB_DIRS_DELETED deleted"
    echo "Jenkins builds:        $JENKINS_DIRS_DELETED deleted"
    echo "Total space freed:     $(format_bytes "$TOTAL_SIZE_FREED")"
    echo "Dry run mode:          $DRY_RUN"
    echo "=========================================="
}

# Parse command line arguments
parse_args() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            --dry-run)
                DRY_RUN=true
                shift
                ;;
            --days)
                RETENTION_DAYS="$2"
                shift 2
                ;;
            --gitlab-only)
                CLEAN_GITLAB=true
                CLEAN_JENKINS=false
                shift
                ;;
            --jenkins-only)
                CLEAN_GITLAB=false
                CLEAN_JENKINS=true
                shift
                ;;
            --verbose)
                VERBOSE=true
                shift
                ;;
            --help|-h)
                print_help
                ;;
            *)
                log_error "Unknown option: $1"
                echo "Use --help for usage information"
                exit 1
                ;;
        esac
    done
}

# Main execution
main() {
    parse_args "$@"

    # Change to project root
    cd "$PROJECT_ROOT" || exit 1

    # Load environment
    load_env

    # Make LOG_DIR absolute if relative
    if [[ ! "$LOG_DIR" = /* ]]; then
        LOG_DIR="$PROJECT_ROOT/$LOG_DIR"
    fi

    # Display configuration
    echo "=========================================="
    echo "Log Cleanup Script"
    echo "=========================================="
    echo "Log directory:         $LOG_DIR"
    echo "Retention period:      ${RETENTION_DAYS} days"
    echo "Dry run:               $DRY_RUN"
    echo "Clean GitLab:          $CLEAN_GITLAB"
    echo "Clean Jenkins:         $CLEAN_JENKINS"
    echo "=========================================="
    echo ""

    # Check if log directory exists
    if [ ! -d "$LOG_DIR" ]; then
        log_error "Log directory does not exist: $LOG_DIR"
        exit 1
    fi

    # Perform cleanup
    if [ "$CLEAN_GITLAB" = true ]; then
        clean_gitlab_logs
    fi

    if [ "$CLEAN_JENKINS" = true ]; then
        clean_jenkins_logs
    fi

    # Print summary
    print_summary

    if [ "$DRY_RUN" = true ]; then
        echo ""
        log_warning "This was a dry run. No files were actually deleted."
        log_info "Run without --dry-run to perform actual cleanup."
    fi
}

# Run main function
main "$@"
