#!/bin/bash
set -e

# GitLab Pipeline Log Extractor - Docker Entrypoint Script
# This script validates environment and starts the application

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "=========================================="
echo "GitLab Pipeline Log Extractor"
echo "=========================================="

# Check if .env file exists
if [ -f ".env" ]; then
    echo "[OK] Loading configuration from .env file"
    # Export variables from .env file
    export $(grep -v '^#' .env | xargs)
else
    echo "[WARNING] No .env file found, using environment variables"
fi

# Validate required environment variables
if [ -z "$GITLAB_URL" ]; then
    echo -e "${RED}ERROR: GITLAB_URL environment variable is required${NC}"
    exit 1
fi

if [ -z "$GITLAB_TOKEN" ]; then
    echo -e "${RED}ERROR: GITLAB_TOKEN environment variable is required${NC}"
    exit 1
fi

# Set defaults for optional variables
export WEBHOOK_PORT="${WEBHOOK_PORT:-8000}"
export LOG_OUTPUT_DIR="${LOG_OUTPUT_DIR:-./logs}"
export RETRY_ATTEMPTS="${RETRY_ATTEMPTS:-3}"
export RETRY_DELAY="${RETRY_DELAY:-2}"
export LOG_LEVEL="${LOG_LEVEL:-INFO}"

echo "[OK] Configuration validated"
echo "  - GitLab URL: $GITLAB_URL"
echo "  - Webhook Port: $WEBHOOK_PORT"
echo "  - Log Directory: $LOG_OUTPUT_DIR"
echo "  - Log Level: $LOG_LEVEL"

# Create logs directory if it doesn't exist
mkdir -p "$LOG_OUTPUT_DIR"
echo "[OK] Log directory ready: $LOG_OUTPUT_DIR"

# Check if we can write to logs directory
if [ ! -w "$LOG_OUTPUT_DIR" ]; then
    echo -e "${RED}ERROR: Cannot write to log directory: $LOG_OUTPUT_DIR${NC}"
    exit 1
fi

echo "=========================================="
echo "Starting FastAPI server on port $WEBHOOK_PORT..."
echo "=========================================="

# Start uvicorn with dynamic port from environment
# Use 'python -m uvicorn' instead of 'uvicorn' to avoid PATH issues
exec python -m uvicorn src.webhook_listener:app \
    --host 0.0.0.0 \
    --port "$WEBHOOK_PORT" \
    --log-level "${LOG_LEVEL,,}"
