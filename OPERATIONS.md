# GitLab Pipeline Log Extractor - Operations Guide

Complete guide for debugging, monitoring, and operating the GitLab Pipeline Log Extraction System.

## Table of Contents

### Part 1: Setup & Debugging
- [Quick Start](#quick-start)
- [Setup & Installation](#setup--installation)
  - [Environment Setup](#environment-setup)
  - [Install Dependencies](#install-dependencies)
  - [Configuration](#configuration)
  - [GitLab Access Token](#gitlab-access-token)
- [Running the Application](#running-the-application)
  - [Method 1: Using Main Script](#method-1-using-main-script-recommended)
  - [Method 2: Using Uvicorn Directly](#method-2-using-uvicorn-directly)
  - [Method 3: Background Process](#method-3-background-process)
  - [Method 4: Systemd Service](#method-4-using-systemd-linux-production)
  - [Method 5: Docker Deployment](#method-5-docker-deployment-recommended-for-production)
- [Docker Operations](#docker-operations)
  - [Quick Start with Docker](#quick-start-with-docker)
  - [Container Management](#container-management)
  - [Monitoring in Docker](#monitoring-in-docker)
  - [Troubleshooting Docker](#troubleshooting-docker)
- [Testing](#testing)
  - [Run Unit Tests](#run-unit-tests)
  - [Test Individual Modules](#test-individual-modules)
  - [Test API Endpoints](#test-api-endpoints)
- [Common Issues & Solutions](#common-issues--solutions)
  - [Port Already in Use](#issue-1-port-already-in-use)
  - [Import Errors](#issue-2-import-errors)
  - [Configuration Not Found](#issue-3-configuration-not-found)
  - [GitLab API Authentication Failed](#issue-4-gitlab-api-authentication-failed)
  - [Webhook Returns 401](#issue-5-webhook-returns-401-unauthorized)
  - [Logs Not Being Saved](#issue-6-logs-not-being-saved)
  - [Connection Errors](#issue-7-databaseconnection-errors)
- [Debugging Scripts](#debugging-scripts)
  - [Debug Configuration](#debug-configuration)
  - [Debug GitLab Connection](#debug-gitlab-connection)
  - [Debug Storage](#debug-storage)
  - [Check Dependencies](#check-all-dependencies)
- [Monitoring & Logs](#monitoring--logs)
  - [View Server Logs](#view-server-logs)
  - [Monitor Storage](#monitor-storage)
  - [Monitor System Resources](#monitor-system-resources)
- [Application Logging System](#application-logging-system)
  - [Logging Overview](#logging-overview)
  - [Log Files and Formats](#log-files-and-formats)
  - [Log Rotation Behavior](#log-rotation-behavior)
  - [Application Restart Behavior](#application-restart-behavior)
  - [Viewing Logs](#viewing-logs)
  - [Searching Logs](#searching-logs)
  - [Request ID Tracking](#request-id-tracking)
  - [Log Storage and Retention](#log-storage-and-retention)
  - [Log Configuration](#log-configuration)
  - [Troubleshooting with Logs](#troubleshooting-with-logs)
- [Manual Testing](#manual-testing)
  - [Create Test Payload](#create-test-webhook-payload)
  - [Test Webhook Locally](#test-webhook-locally)
  - [Test with ngrok](#test-with-ngrok-for-local-gitlab-testing)
- [Troubleshooting Checklist](#troubleshooting-checklist)

### Part 2: Monitoring & Tracking
- [Monitoring Overview](#monitoring-overview)
- [What is Tracked](#what-is-tracked)
  - [Automatic Tracking](#automatic-tracking)
  - [Request Status Flow](#request-status-flow)
- [Monitoring Dashboard](#monitoring-dashboard)
  - [CLI Dashboard Tool](#cli-dashboard-tool)
  - [Dashboard Output Example](#dashboard-output-example)
- [API Endpoints](#api-endpoints)
  - [Monitoring Summary](#1-monitoring-summary)
  - [Recent Requests](#2-recent-requests)
  - [Pipeline Details](#3-pipeline-details)
  - [Export to CSV](#4-export-to-csv)
- [Viewing Statistics](#viewing-statistics)
  - [Method 1: CLI Dashboard](#method-1-cli-dashboard-recommended)
  - [Method 2: API Calls](#method-2-api-calls)
  - [Method 3: Interactive Docs](#method-3-interactive-api-docs)
  - [Method 4: Direct SQL](#method-4-direct-database-query)
- [Exporting Data](#exporting-data)
  - [CSV Export via CLI](#csv-export-via-cli)
  - [CSV Export via API](#csv-export-via-api)
  - [Analyze in Excel](#analyze-in-excelgoogle-sheets)
- [Database](#database)
  - [Database Location](#database-location)
  - [Database Schema](#database-schema)
  - [Querying the Database](#querying-the-database)
- [Real-World Examples](#real-world-examples)
  - [Check Today's Activity](#example-1-check-todays-activity)
  - [Troubleshoot Failed Pipeline](#example-2-troubleshoot-failed-pipeline)
  - [Track Performance](#example-3-track-performance-over-time)
  - [Monitor Active Processing](#example-4-monitor-active-processing)
  - [Generate Reports](#example-5-generate-weekly-report)
- [Advanced Operations](#advanced-operations)
  - [Real-Time Monitoring](#real-time-monitoring)
  - [Cleanup Old Data](#cleanup-old-data)
  - [Integration with Monitoring Tools](#integration-with-monitoring-tools)
- [FAQ](#faq)

---

# Part 1: Setup & Debugging

## Quick Start

```bash
# 1. Clone and navigate
git clone <repository-url>
cd extract-build-logs

# 2. Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
nano .env  # Edit with your settings

# 5. Start server
python src/webhook_listener.py
```

---

## Setup & Installation

### Environment Setup

```bash
# Check Python version (requires 3.8+)
python3 --version

# Create virtual environment
python3 -m venv venv

# Activate virtual environment
# Linux/Mac:
source venv/bin/activate

# Windows (PowerShell):
.\venv\Scripts\Activate.ps1

# Windows (Command Prompt):
venv\Scripts\activate.bat

# Verify activation (should show venv path)
which python  # Linux/Mac
where python  # Windows
```

### Install Dependencies

```bash
# Install all dependencies
pip install -r requirements.txt

# Verify installations
pip list

# Expected packages:
# - fastapi==0.109.0
# - uvicorn==0.27.0
# - requests==2.31.0
# - python-dotenv==1.0.0
# - pytest==7.4.3
# - httpx==0.26.0
# - tabulate==0.9.0
```

### Configuration

```bash
# Copy environment template
cp .env.example .env

# Edit configuration
nano .env  # or vim, code, etc.

# Required settings:
# GITLAB_URL=https://gitlab.com
# GITLAB_TOKEN=your_token_here

# Optional settings (with defaults):
# WEBHOOK_PORT=8000
# WEBHOOK_SECRET=
# LOG_OUTPUT_DIR=./logs
# RETRY_ATTEMPTS=3
# RETRY_DELAY=2
# LOG_LEVEL=INFO

# Validate environment file
cat .env
```

### GitLab Access Token

```bash
# Create GitLab token:
# 1. Go to GitLab → Profile → Access Tokens
# 2. Name: "Pipeline Log Extractor"
# 3. Scopes: Select "api"
# 4. Create token
# 5. Copy token and add to .env

# Test token validity
curl --header "PRIVATE-TOKEN: your_token_here" \
  "https://gitlab.com/api/v4/user"

# Expected: Your user details in JSON
```

---

## Running the Application

### Method 1: Using Main Script (Recommended)

```bash
# Standard run
python src/webhook_listener.py

# Expected output:
# ============================================================
# GitLab Pipeline Log Extraction System
# ============================================================
# INFO - Initializing GitLab Pipeline Log Extractor...
# INFO - Configuration loaded successfully
# INFO - GitLab URL: https://gitlab.com
# INFO - Webhook Port: 8000
# INFO - Log Output Directory: ./logs
# INFO - All components initialized successfully
# INFO - Starting webhook server on port 8000...
# INFO - Press Ctrl+C to stop
```

### Method 2: Using Uvicorn Directly

```bash
# Basic run
uvicorn src.webhook_listener:app --host 0.0.0.0 --port 8000

# With auto-reload (for development)
uvicorn src.webhook_listener:app --reload --host 0.0.0.0 --port 8000

# With custom log level
uvicorn src.webhook_listener:app --log-level debug --host 0.0.0.0 --port 8000

# With specific number of workers (production)
uvicorn src.webhook_listener:app --workers 4 --host 0.0.0.0 --port 8000
```

### Method 3: Background Process

```bash
# Run in background (Linux/Mac)
nohup python src/webhook_listener.py > server.log 2>&1 &

# Get process ID
echo $!

# Check if running
ps aux | grep webhook_listener

# Stop background process
kill <process_id>
```

### Method 4: Using systemd (Linux Production)

```bash
# Create systemd service file
sudo nano /etc/systemd/system/gitlab-log-extractor.service

# Add content:
# [Unit]
# Description=GitLab Pipeline Log Extractor
# After=network.target
#
# [Service]
# Type=simple
# User=your_user
# WorkingDirectory=/path/to/extract-build-logs
# Environment="PATH=/path/to/venv/bin"
# ExecStart=/path/to/venv/bin/python src/webhook_listener.py
# Restart=always
#
# [Install]
# WantedBy=multi-user.target

# Enable and start service
sudo systemctl daemon-reload
sudo systemctl enable gitlab-log-extractor
sudo systemctl start gitlab-log-extractor

# Check status
sudo systemctl status gitlab-log-extractor

# View logs
sudo journalctl -u gitlab-log-extractor -f
```

### Method 5: Docker Deployment (Recommended for Production)

```bash
# 1. Build the Docker image
./manage-container.sh build

# 2. Start the container
./manage-container.sh start

# 3. Check status
./manage-container.sh status

# 4. View logs
./manage-container.sh logs

# Container will automatically:
# - Restart on failure
# - Persist logs to ./logs directory
# - Use configuration from .env file
```

**What happens behind the scenes:**
- Container runs on port 8000
- Logs directory is mounted as volume (persistent storage)
- .env file is mounted read-only for configuration
- Health checks run every 30 seconds
- Automatic restart on failure

**Benefits:**
- Isolated environment
- Easy deployment and rollback
- Consistent across environments
- No Python virtual environment needed on host
- Resource limits enforced

---

## Docker Operations

### Quick Start with Docker

**Prerequisites:**
```bash
# Check Docker is installed
docker --version

# Create .env file if not exists
cp .env.example .env
nano .env  # Edit with your settings
```

**Build and Run:**
```bash
# Build image
./manage-container.sh build

# Start container
./manage-container.sh start

# Verify it's running
./manage-container.sh status
```

**Expected Output:**
```
[INFO] Building Docker image: gitlab-pipeline-extractor
[SUCCESS] Image built successfully!
[INFO] Starting new container: gitlab-pipeline-extractor
[SUCCESS] Container started successfully!
[INFO] Webhook endpoint: http://localhost:8000/webhook
[INFO] Health check: http://localhost:8000/health
[INFO] API docs: http://localhost:8000/docs
```

### Container Management

**All commands use the management script:**

```bash
# Build/Rebuild image
./manage-container.sh build

# Start container (creates if needed)
./manage-container.sh start

# Stop container
./manage-container.sh stop

# Restart container
./manage-container.sh restart

# View container status and resource usage
./manage-container.sh status

# View live logs (Ctrl+C to exit)
./manage-container.sh logs

# Open shell inside container
./manage-container.sh shell

# Remove container (keeps logs)
./manage-container.sh remove

# Remove container and image (keeps logs)
./manage-container.sh cleanup

# View help
./manage-container.sh help
```

**Container Status Example:**
```bash
$ ./manage-container.sh status

[INFO] Container status:
[SUCCESS] Container is RUNNING

CONTAINER ID   STATUS          PORTS
abc123def456   Up 2 hours      0.0.0.0:8000->8000/tcp

[INFO] Health status: healthy

[INFO] Resource usage:
CONTAINER                      CPU %     MEM USAGE / LIMIT     NET I/O
gitlab-pipeline-extractor      0.50%     125MiB / 1GiB         1.5kB / 2.3kB
```

### Monitoring in Docker

**View Monitoring Dashboard:**
```bash
# 24-hour summary (default)
./manage-container.sh monitor

# Custom time range
./manage-container.sh monitor --hours 48

# Recent requests
./manage-container.sh monitor --recent 100

# Specific pipeline
./manage-container.sh monitor --pipeline 12345
```

**Export Monitoring Data:**
```bash
# Export to CSV
./manage-container.sh export monitoring_data.csv

# Or use default filename (monitoring_export.csv)
./manage-container.sh export
```

**Access API Endpoints:**
```bash
# Health check
curl http://localhost:8000/health

# Monitoring summary
curl http://localhost:8000/monitor/summary?hours=24

# Recent requests
curl http://localhost:8000/monitor/recent?limit=50

# Export CSV
curl http://localhost:8000/monitor/export/csv -o data.csv
```

**Direct Database Access:**
```bash
# Enter container shell
./manage-container.sh shell

# Inside container
sqlite3 /app/logs/monitoring.db

# Run queries
SELECT COUNT(*) FROM requests;
SELECT status, COUNT(*) FROM requests GROUP BY status;
```

### Testing in Docker

**Send Test Webhook:**
```bash
# Send sample webhook payload
./manage-container.sh test

# Expected output:
# [INFO] Testing webhook endpoint with sample payload...
# {"status":"queued","message":"Pipeline event queued for processing","request_id":1}
# [SUCCESS] Test webhook sent!
# [INFO] Check logs with: ./manage-container.sh logs
```

**Manual Testing:**
```bash
# Test health endpoint
curl http://localhost:8000/health

# Test with custom payload
curl -X POST http://localhost:8000/webhook \
  -H "Content-Type: application/json" \
  -H "X-Gitlab-Event: Pipeline Hook" \
  -d @test_payload.json
```

### Troubleshooting Docker

**Container won't start:**
```bash
# Check if .env file exists
ls -la .env

# Verify image exists
docker images | grep gitlab-pipeline-extractor

# Check Docker logs
docker logs gitlab-pipeline-extractor

# Remove and recreate
./manage-container.sh remove
./manage-container.sh start
```

**Port already in use:**
```bash
# Find process using port 8000
sudo lsof -i :8000
# or
sudo netstat -tulpn | grep 8000

# Kill the process
sudo kill <PID>

# Or change port in .env
echo "WEBHOOK_PORT=8001" >> .env

# Restart container
./manage-container.sh restart
```

**Container unhealthy:**
```bash
# Check health status
docker inspect --format='{{.State.Health.Status}}' gitlab-pipeline-extractor

# View health check logs
docker inspect --format='{{range .State.Health.Log}}{{.Output}}{{end}}' gitlab-pipeline-extractor

# Check application logs
./manage-container.sh logs

# Restart container
./manage-container.sh restart
```

**Permission issues with logs directory:**
```bash
# Check directory permissions
ls -ld ./logs

# Fix permissions (container runs as UID 1000)
sudo chown -R 1000:1000 ./logs

# Or make it world-writable (less secure)
chmod 777 ./logs

# Restart container
./manage-container.sh restart
```

**Logs not persisting:**
```bash
# Verify volume mount
docker inspect gitlab-pipeline-extractor | grep -A 10 Mounts

# Check if logs directory exists on host
ls -la ./logs

# Verify files are created
./manage-container.sh shell
ls -la /app/logs
```

**GitLab connection issues:**
```bash
# Check .env configuration
cat .env

# Test from inside container
./manage-container.sh shell
curl -H "PRIVATE-TOKEN: $GITLAB_TOKEN" $GITLAB_URL/api/v4/projects

# Verify network connectivity
docker exec gitlab-pipeline-extractor curl -I https://gitlab.com
```

**Update after code changes:**
```bash
# Rebuild image
./manage-container.sh build

# Restart with new image
./manage-container.sh restart

# Verify new version
./manage-container.sh logs
```

**View resource usage over time:**
```bash
# Real-time stats
docker stats gitlab-pipeline-extractor

# Or use management script
./manage-container.sh status
```

**Backup and restore:**
```bash
# Backup logs and database
tar -czf backup_$(date +%Y%m%d).tar.gz ./logs

# Restore
tar -xzf backup_20240101.tar.gz

# Restart container to use restored data
./manage-container.sh restart
```

**Container Lifecycle:**
```
1. Build:   ./manage-container.sh build
            ↓
2. Start:   ./manage-container.sh start
            ↓
3. Monitor: ./manage-container.sh status / logs
            ↓
4. Update:  Code changes → build → restart
            ↓
5. Stop:    ./manage-container.sh stop (when needed)
```

**Production Checklist:**
- [ ] .env file created with correct credentials
- [ ] WEBHOOK_SECRET set for security
- [ ] Logs directory has correct permissions (UID 1000)
- [ ] Port 8000 is accessible from GitLab
- [ ] Firewall allows incoming connections
- [ ] Monitoring dashboard accessible
- [ ] Backup strategy in place
- [ ] Health checks passing
- [ ] Container restart policy verified

---

## Testing

### Run Unit Tests

```bash
# Run all tests
pytest tests/

# Run with verbose output
pytest -v tests/

# Run specific test file
pytest tests/test_pipeline_extractor.py

# Run with coverage
pytest --cov=src tests/

# Generate HTML coverage report
pytest --cov=src --cov-report=html tests/
# Open htmlcov/index.html in browser
```

### Test Individual Modules

```bash
# Test configuration loader
python src/config_loader.py

# Test error handler
python src/error_handler.py

# Test storage manager
python src/storage_manager.py

# Test pipeline extractor
python src/pipeline_extractor.py
```

### Test API Endpoints

```bash
# Test health endpoint
curl http://localhost:8000/health

# Expected response:
# {"status":"healthy","service":"gitlab-log-extractor","version":"1.0.0"}

# Test stats endpoint
curl http://localhost:8000/stats

# Test webhook endpoint (with sample payload)
curl -X POST http://localhost:8000/webhook \
  -H "Content-Type: application/json" \
  -H "X-Gitlab-Event: Pipeline Hook" \
  -H "X-Gitlab-Token: your_secret_token" \
  -d @test_payload.json
```

---

## Common Issues & Solutions

### Issue 1: Port Already in Use

```bash
# Problem:
# ERROR - [Errno 48] Address already in use

# Solution 1: Find process using port
lsof -i :8000  # Mac/Linux
netstat -ano | findstr :8000  # Windows

# Solution 2: Kill the process
kill -9 <PID>  # Mac/Linux
taskkill /PID <PID> /F  # Windows

# Solution 3: Change port in .env
echo "WEBHOOK_PORT=8001" >> .env
```

### Issue 2: Import Errors

```bash
# Problem:
# ModuleNotFoundError: No module named 'fastapi'

# Solution: Install dependencies
pip install -r requirements.txt

# Verify installation
pip show fastapi

# If still failing, check Python path
which python
echo $PYTHONPATH
```

### Issue 3: Configuration Not Found

```bash
# Problem:
# ValueError: GITLAB_URL environment variable is required

# Solution 1: Check .env file exists
ls -la .env

# Solution 2: Verify .env content
cat .env

# Solution 3: Export variables manually
export GITLAB_URL=https://gitlab.com
export GITLAB_TOKEN=your_token

# Solution 4: Load .env explicitly
python -c "from dotenv import load_dotenv; load_dotenv(); import os; print(os.getenv('GITLAB_URL'))"
```

### Issue 4: GitLab API Authentication Failed

```bash
# Problem:
# GitLabAPIError: Authentication failed. Check GITLAB_TOKEN

# Solution 1: Verify token is valid
curl --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
  "https://gitlab.com/api/v4/user"

# Solution 2: Check token has 'api' scope
# Go to GitLab → Profile → Access Tokens
# Verify 'api' checkbox is selected

# Solution 3: Regenerate token
# Create new token with 'api' scope
# Update .env file
```

### Issue 5: Webhook Returns 401 Unauthorized

```bash
# Problem:
# Webhook authentication failed

# Solution 1: Check secret token matches
# In .env:
cat .env | grep WEBHOOK_SECRET

# In GitLab webhook settings:
# Settings → Webhooks → Secret Token field

# Solution 2: Disable secret validation temporarily
# Comment out in .env:
# WEBHOOK_SECRET=

# Restart server
```

### Issue 6: Logs Not Being Saved

```bash
# Problem:
# Logs not appearing in logs/ directory

# Solution 1: Check directory exists and permissions
ls -la logs/
chmod 755 logs/

# Solution 2: Verify LOG_OUTPUT_DIR in .env
cat .env | grep LOG_OUTPUT_DIR

# Solution 3: Check server logs for errors
tail -f webhook_server.log

# Solution 4: Test storage manually
python -c "from src.storage_manager import StorageManager; \
  sm = StorageManager('./logs'); \
  sm.save_log(123, 789, 456, 'test', 'log content', {}); \
  print('Success!')"
```

### Issue 7: Database/Connection Errors

```bash
# Problem:
# Connection timeout to GitLab API

# Solution 1: Check network connectivity
ping gitlab.com
curl -I https://gitlab.com

# Solution 2: Check firewall rules
# Allow outbound HTTPS (443) to GitLab

# Solution 3: Increase retry settings in .env
RETRY_ATTEMPTS=5
RETRY_DELAY=3

# Solution 4: Test API directly
curl -v "https://gitlab.com/api/v4/projects"
```

---

## Debugging Scripts

### Debug Configuration

```bash
# debug_config.py
cat > debug_config.py << 'EOF'
#!/usr/bin/env python3
"""Debug configuration loading"""
import sys
sys.path.insert(0, 'src')

from config_loader import ConfigLoader

try:
    config = ConfigLoader.load()
    print("✓ Configuration loaded successfully")
    print(f"  GitLab URL: {config.gitlab_url}")
    print(f"  Webhook Port: {config.webhook_port}")
    print(f"  Log Directory: {config.log_output_dir}")
    print(f"  Retry Attempts: {config.retry_attempts}")
    print(f"  Log Level: {config.log_level}")
except Exception as e:
    print(f"✗ Configuration error: {e}")
    sys.exit(1)
EOF

chmod +x debug_config.py
python debug_config.py
```

### Debug GitLab Connection

```bash
# debug_gitlab.py
cat > debug_gitlab.py << 'EOF'
#!/usr/bin/env python3
"""Debug GitLab API connection"""
import sys
sys.path.insert(0, 'src')

from config_loader import ConfigLoader
from log_fetcher import LogFetcher

try:
    config = ConfigLoader.load()
    fetcher = LogFetcher(config)

    print("Testing GitLab API connection...")
    print("✓ GitLab API connection successful")

except Exception as e:
    print(f"✗ GitLab API error: {e}")
    sys.exit(1)
EOF

chmod +x debug_gitlab.py
python debug_gitlab.py
```

### Debug Storage

```bash
# debug_storage.py
cat > debug_storage.py << 'EOF'
#!/usr/bin/env python3
"""Debug storage operations"""
import sys
sys.path.insert(0, 'src')

from storage_manager import StorageManager

try:
    manager = StorageManager("./logs")

    print("Testing storage write...")
    path = manager.save_log(
        project_id=123,
        pipeline_id=789,
        job_id=456,
        job_name="test",
        log_content="Test log content",
        job_details={"status": "success"}
    )
    print(f"✓ Log saved to: {path}")

    metadata = manager.get_pipeline_metadata(123, 789)
    print(f"✓ Metadata retrieved: {metadata is not None}")

    stats = manager.get_storage_stats()
    print(f"✓ Stats: {stats}")

except Exception as e:
    print(f"✗ Storage error: {e}")
    sys.exit(1)
EOF

chmod +x debug_storage.py
python debug_storage.py
```

### Check All Dependencies

```bash
# check_dependencies.sh
cat > check_dependencies.sh << 'EOF'
#!/bin/bash
echo "Checking Python dependencies..."

dependencies=(
    "fastapi"
    "uvicorn"
    "requests"
    "python-dotenv"
    "pytest"
    "httpx"
    "tabulate"
)

for dep in "${dependencies[@]}"; do
    if python -c "import $dep" 2>/dev/null; then
        version=$(pip show $dep | grep Version | awk '{print $2}')
        echo "✓ $dep ($version)"
    else
        echo "✗ $dep (not installed)"
    fi
done
EOF

chmod +x check_dependencies.sh
bash check_dependencies.sh
```

---

## Monitoring & Logs

### View Server Logs

```bash
# Real-time log viewing
tail -f webhook_server.log

# View last 100 lines
tail -n 100 webhook_server.log

# Search for errors
grep ERROR webhook_server.log

# Search for specific pipeline
grep "pipeline_id.*12345" webhook_server.log

# Count requests by status
grep "Processing pipeline" webhook_server.log | wc -l
```

### Monitor Storage

```bash
# Watch logs directory
watch -n 5 'ls -lah logs/'

# Count total log files
find logs/ -name "*.log" | wc -l

# Check storage size
du -sh logs/

# List recent pipelines
find logs/ -type d -name "pipeline_*" | head -10
```

### Monitor System Resources

```bash
# CPU and memory usage
top -p $(pgrep -f webhook_listener)

# Detailed process info
ps aux | grep webhook_listener

# Network connections
netstat -an | grep :8000
lsof -i :8000
```

---

## Application Logging System

The system includes a comprehensive logging infrastructure that tracks all operations, errors, and performance metrics with automatic rotation and retention management.

### Logging Overview

**Features:**
- ✅ Pipe-delimited plain text format for easy parsing
- ✅ Multiple specialized log files (application, access, performance)
- ✅ Request ID correlation across all logs
- ✅ Automatic sensitive data masking (tokens, secrets)
- ✅ Automatic log rotation with size limits
- ✅ DEBUG level logging for detailed troubleshooting
- ✅ Both console and file output
- ✅ Logs visible in Docker container output
- ✅ Persistent storage across container restarts

**Log Format:**
```
timestamp | level | logger | request_id | message | context
```

**Example:**
```
2025-10-29 17:52:05.836 | INFO | webhook_listener | a1b2c3d4 | Webhook received | pipeline_id=12345 project_id=100
2025-10-29 17:52:06.123 | INFO | log_fetcher | a1b2c3d4 | Pipeline logs fetched | job_count=5 duration_ms=287
2025-10-29 17:52:06.450 | ERROR | storage_manager | a1b2c3d4 | Failed to save log | job_id=789 error_type=IOError
```

---

### Log Files and Formats

The system maintains **3 specialized log files**, all stored in the `logs/` directory:

#### 1. application.log
**Purpose:** All application logs including errors, warnings, info, and debug messages

**Settings:**
- Level: DEBUG and above
- Size Limit: 100 MB per file
- Backups: 10 rotated files
- Total Storage: ~1.1 GB (100 MB × 11 files)

**What's logged:**
- Webhook processing flow
- Pipeline extraction steps
- API calls to GitLab
- File operations
- Errors with full stack traces
- Configuration loading
- Background task execution

**Example:**
```
2025-10-29 17:52:05.836 | INFO | webhook_listener | a1b2c3d4 | Webhook received | event_type=Pipeline Hook source_ip=192.168.1.100
2025-10-29 17:52:05.842 | DEBUG | webhook_listener | a1b2c3d4 | Validating webhook payload | pipeline_id=12345
2025-10-29 17:52:05.845 | INFO | webhook_listener | a1b2c3d4 | Pipeline event queued | pipeline_id=12345 project_id=100
2025-10-29 17:52:06.000 | INFO | webhook_listener | a1b2c3d4 | Starting pipeline log extraction | pipeline_id=12345
2025-10-29 17:52:06.287 | INFO | webhook_listener | a1b2c3d4 | Pipeline logs fetched | job_count=5 duration_ms=287
2025-10-29 17:52:06.450 | ERROR | storage_manager | a1b2c3d4 | Failed to save log | job_id=789 error_type=IOError
```

#### 2. access.log
**Purpose:** HTTP request logging for all webhook requests

**Settings:**
- Level: INFO and above
- Size Limit: 50 MB per file
- Backups: 20 rotated files
- Total Storage: ~1.05 GB (50 MB × 21 files)

**What's logged:**
- All incoming webhook requests
- Source IP addresses
- Event types
- Request paths
- Processing outcomes

**Example:**
```
2025-10-29 17:52:05.837 | INFO | access | a1b2c3d4 | Webhook request | source_ip=192.168.1.100 event_type=Pipeline Hook path=/webhook
2025-10-29 17:52:15.123 | INFO | access | b2c3d4e5 | Webhook request | source_ip=10.0.0.50 event_type=Pipeline Hook path=/webhook
```

#### 3. performance.log
**Purpose:** Performance metrics and timing information

**Settings:**
- Level: INFO and above
- Size Limit: 50 MB per file
- Backups: 10 rotated files
- Total Storage: ~550 MB (50 MB × 11 files)

**What's logged:**
- Request processing times
- API call durations
- File operation times
- Job processing metrics
- Background task performance

**Example:**
```
2025-10-29 17:52:06.500 | INFO | performance | a1b2c3d4 | Webhook processed | pipeline_id=12345 duration_ms=664 operation=webhook_handler
2025-10-29 17:52:15.234 | INFO | performance | a1b2c3d4 | Pipeline processing metrics | pipeline_id=12345 total_duration_ms=9234 fetch_duration_ms=287 save_duration_ms=8947 job_count=5 success_count=5 error_count=0
```

**Total Storage Capacity:** ~2.7 GB across all log files

---

### Log Rotation Behavior

Logs automatically rotate when they reach their size limit. **No data is lost** until the backup count is exceeded.

#### How Rotation Works

When `application.log` reaches 100 MB:

```
Before rotation:
./logs/
├── application.log (100 MB)        ← Full, needs rotation
├── application.log.1 (100 MB)
├── application.log.2 (100 MB)
└── ...

After rotation:
./logs/
├── application.log (0 KB)          ← New empty file, logging continues here
├── application.log.1 (100 MB)      ← Was application.log
├── application.log.2 (100 MB)      ← Was application.log.1
├── application.log.3 (100 MB)      ← Was application.log.2
└── ...
└── application.log.10 (100 MB)     ← Oldest kept
    application.log.11              ← DELETED (exceeded backupCount)
```

**Key Points:**
- ✅ Rotation happens automatically in real-time
- ✅ No application restart required
- ✅ No interruption to logging
- ✅ Old files are numbered sequentially
- ✅ Oldest file (beyond backup count) is deleted
- ✅ You always have current file + N backups

#### Rotation Settings

| Log File | Size Limit | Backups | Total Files | Total Storage |
|----------|------------|---------|-------------|---------------|
| application.log | 100 MB | 10 | 11 | 1.1 GB |
| access.log | 50 MB | 20 | 21 | 1.05 GB |
| performance.log | 50 MB | 10 | 11 | 550 MB |

#### Accessing Rotated Logs

```bash
# View current log
cat logs/application.log

# View previous rotation
cat logs/application.log.1

# View all logs (newest first)
cat logs/application.log logs/application.log.{1..10}

# Search across all rotated files
grep "pipeline_id=12345" logs/application.log*

# Count total lines across all files
cat logs/application.log* | wc -l

# View oldest logs
cat logs/application.log.10
```

---

### Application Restart Behavior

**Important:** Log files persist across application restarts. No data is lost.

#### What Happens During Restart

1. **Application stops** (container restart, server reboot, manual stop)
2. **Existing log files are preserved** - NOT deleted or truncated
3. **Application starts**
4. **Logging resumes appending** to existing files at current size
5. **Rotation continues** from where it left off

#### Example Timeline

```
Day 1, 10:00 AM - Application starts
                - application.log created (0 KB)

Day 1, 5:00 PM  - application.log grows to 45 MB

Day 1, 6:00 PM  - Container/server restarts

Day 1, 6:01 PM  - Application starts again
                - Finds existing application.log (45 MB)
                - Appends new logs to it (continues from 45 MB)

Day 2, 3:00 PM  - application.log reaches 100 MB → rotates automatically
                - Creates new application.log (0 KB)
                - Renames old to application.log.1 (100 MB)
```

#### Docker Volume Mount

Logs persist because they're mounted to the host:

```bash
# In manage-container.sh:
docker run -d \
  -v "$(pwd)/logs:/app/logs" \  # Host directory mapped to container
  ...
```

**This means:**
- ✅ Logs survive container deletion
- ✅ Logs survive container recreation
- ✅ Logs survive host reboots
- ✅ You can access logs from host even when container is stopped

```bash
# View logs from host (even when container is stopped)
cat ./logs/application.log

# Backup logs (container can be running or stopped)
tar -czf logs_backup_$(date +%Y%m%d).tar.gz ./logs
```

---

### Viewing Logs

#### Method 1: Docker Logs (Console Output)

View logs in real-time from Docker console:

```bash
# Follow live logs
./manage-container.sh logs

# Or directly with Docker
docker logs -f gitlab-pipeline-extractor

# Last 100 lines
docker logs --tail 100 gitlab-pipeline-extractor

# Logs since specific time
docker logs --since "2025-10-29T10:00:00" gitlab-pipeline-extractor
```

**What you see:** Console handler output (INFO and above from all loggers)

#### Method 2: Log Files (Most Detailed)

Read log files directly for complete DEBUG-level information:

```bash
# Tail application log (real-time)
tail -f ./logs/application.log

# Last 100 lines
tail -n 100 ./logs/application.log

# View with less (scrollable)
less ./logs/application.log

# Real-time with color highlighting
tail -f ./logs/application.log | grep --color=always -E 'ERROR|WARN|$'
```

#### Method 3: Inside Container

```bash
# Enter container
./manage-container.sh shell

# Inside container
tail -f /app/logs/application.log
grep ERROR /app/logs/application.log
cat /app/logs/performance.log
```

#### Method 4: Watch Mode (Auto-refresh)

```bash
# Refresh every 2 seconds
watch -n 2 'tail -20 ./logs/application.log'

# Monitor multiple logs
watch -n 5 'echo "=== APPLICATION ===" && tail -10 ./logs/application.log && echo && echo "=== PERFORMANCE ===" && tail -10 ./logs/performance.log'
```

---

### Searching Logs

#### Search by Request ID

Track a complete request flow:

```bash
# Find all logs for specific request
grep "a1b2c3d4" logs/application.log

# Search across all rotated files
grep "a1b2c3d4" logs/application.log*

# With context (5 lines before/after)
grep -C 5 "a1b2c3d4" logs/application.log
```

#### Search by Pipeline ID

```bash
# Find all logs for pipeline
grep "pipeline_id=12345" logs/application.log*

# Count occurrences
grep -c "pipeline_id=12345" logs/application.log

# Extract only those lines
grep "pipeline_id=12345" logs/application.log > pipeline_12345_logs.txt
```

#### Search by Log Level

```bash
# All errors
grep "| ERROR |" logs/application.log

# All errors and warnings
grep -E "| ERROR | | WARN |" logs/application.log

# Count errors in last hour (assuming recent log)
grep "| ERROR |" logs/application.log | tail -1000 | wc -l
```

#### Search by Time Range

```bash
# Logs from specific date
grep "2025-10-29" logs/application.log

# Logs from specific hour
grep "2025-10-29 17:" logs/application.log

# Logs from specific time range
grep "2025-10-29 17:5[0-9]" logs/application.log
```

#### Complex Searches

```bash
# Failed requests with error details
grep "| ERROR |" logs/application.log | grep "pipeline_id"

# Performance issues (> 10 seconds)
awk -F'|' '$6 ~ /duration_ms/ && $6 ~ /[0-9]{5,}/ {print}' logs/performance.log

# Extract all pipeline IDs
grep -oP 'pipeline_id=\K[0-9]+' logs/application.log | sort -u

# Top 10 most logged pipelines
grep -oP 'pipeline_id=\K[0-9]+' logs/application.log | sort | uniq -c | sort -rn | head -10
```

#### Search with jq (if logs were JSON)

For pipe-delimited logs, use awk:

```bash
# Extract specific fields
awk -F'|' '{print $1, $2, $5}' logs/application.log | tail -20

# Filter by level
awk -F'|' '$2 ~ /ERROR/ {print}' logs/application.log

# Count by level
awk -F'|' '{gsub(/^[ \t]+|[ \t]+$/, "", $2); print $2}' logs/application.log | sort | uniq -c
```

---

### Request ID Tracking

Every webhook request gets a unique **Request ID** that appears in all related logs.

#### How It Works

```python
# 1. Webhook receives request
request_id = str(uuid.uuid4())[:8]  # e.g., "a1b2c3d4"
set_request_id(request_id)

# 2. Request ID automatically added to ALL logs in this context
logger.info("Webhook received")        # Includes request_id=a1b2c3d4
logger.info("Processing pipeline")     # Includes request_id=a1b2c3d4
logger.error("Error occurred")         # Includes request_id=a1b2c3d4

# 3. Request ID propagates to background tasks
background_tasks.add_task(process_pipeline, request_id)

# 4. Cleared after request completes
clear_request_id()
```

#### Benefits

**1. Complete Request Tracing**
```bash
# See everything that happened for one request
grep "a1b2c3d4" logs/application.log
```

**2. Cross-File Correlation**
```bash
# Find request in all log files
grep "a1b2c3d4" logs/application.log logs/access.log logs/performance.log
```

**3. Debugging Async Operations**
```bash
# Track background task execution
grep "a1b2c3d4" logs/application.log | grep "background\|async\|task"
```

#### Example: Tracing a Complete Request

```bash
$ grep "a1b2c3d4" logs/*.log

logs/access.log:
2025-10-29 17:52:05.837 | INFO | access | a1b2c3d4 | Webhook request | source_ip=192.168.1.100

logs/application.log:
2025-10-29 17:52:05.836 | INFO | webhook_listener | a1b2c3d4 | Webhook received | pipeline_id=12345
2025-10-29 17:52:05.845 | INFO | webhook_listener | a1b2c3d4 | Pipeline event queued | pipeline_id=12345
2025-10-29 17:52:06.000 | INFO | webhook_listener | a1b2c3d4 | Starting pipeline log extraction
2025-10-29 17:52:06.287 | INFO | log_fetcher | a1b2c3d4 | Pipeline logs fetched | job_count=5
2025-10-29 17:52:15.234 | INFO | storage_manager | a1b2c3d4 | All logs saved successfully

logs/performance.log:
2025-10-29 17:52:06.500 | INFO | performance | a1b2c3d4 | Webhook processed | duration_ms=664
2025-10-29 17:52:15.234 | INFO | performance | a1b2c3d4 | Pipeline processing metrics | total_duration_ms=9234
```

---

### Log Storage and Retention

#### Current Storage

```bash
# Check log directory size
du -sh ./logs

# Check each log file
ls -lh ./logs/*.log

# Check with backups
ls -lh ./logs/application.log*
ls -lh ./logs/access.log*
ls -lh ./logs/performance.log*

# Detailed breakdown
du -h ./logs/* | sort -h
```

#### Storage Capacity Planning

**Maximum storage (if all files reach max size):**
- application.log: 1.1 GB (100MB × 11)
- access.log: 1.05 GB (50MB × 21)
- performance.log: 550 MB (50MB × 11)
- **Total: ~2.7 GB**

**Typical usage patterns:**
- Low traffic (< 100 webhooks/day): ~100-200 MB/day
- Medium traffic (100-1000 webhooks/day): ~500 MB - 1 GB/day
- High traffic (> 1000 webhooks/day): ~2-5 GB/day

#### Cleanup Strategies

**Option 1: Manual Cleanup (Delete Old Rotations)**
```bash
# Delete all backups older than .3 (keeps newest 3)
rm logs/application.log.{4..10}
rm logs/access.log.{4..20}
rm logs/performance.log.{4..10}

# Delete all backups (keeps only current)
rm logs/*.log.[0-9]*
```

**Option 2: Archive and Compress**
```bash
# Archive logs older than 7 days
find ./logs -name "*.log.[5-9]" -o -name "*.log.1[0-9]" | \
  tar -czf logs_archive_$(date +%Y%m%d).tar.gz -T -

# Delete archived files
find ./logs -name "*.log.[5-9]" -o -name "*.log.1[0-9]" -delete

# Compression ratio typically 10:1 (1GB → 100MB)
```

**Option 3: Automated Cleanup Script**
```bash
# cleanup_logs.sh
#!/bin/bash
LOGS_DIR="./logs"
ARCHIVE_DIR="./logs_archive"
DAYS_TO_KEEP=30

# Create archive directory
mkdir -p "$ARCHIVE_DIR"

# Archive and compress old rotated logs
find "$LOGS_DIR" -name "*.log.[5-9]" -o -name "*.log.1[0-9]" | \
  tar -czf "$ARCHIVE_DIR/logs_$(date +%Y%m%d_%H%M%S).tar.gz" -T - && \
  find "$LOGS_DIR" -name "*.log.[5-9]" -o -name "*.log.1[0-9]" -delete

# Delete archives older than specified days
find "$ARCHIVE_DIR" -name "*.tar.gz" -mtime +$DAYS_TO_KEEP -delete

echo "Cleanup complete!"
```

**Option 4: Reduce Backup Count**

Edit `src/logging_config.py` to keep fewer backups:

```python
# Before (keeps 10 backups = 1.1 GB total)
backupCount=10

# After (keeps 5 backups = 600 MB total)
backupCount=5
```

#### Backup Recommendations

```bash
# Daily backup (automated via cron)
0 2 * * * tar -czf /backup/logs_$(date +\%Y\%m\%d).tar.gz ./logs

# Weekly backup (keeps 4 weeks)
0 3 * * 0 tar -czf /backup/weekly_logs_$(date +\%Y\%W).tar.gz ./logs && \
  find /backup -name "weekly_logs_*.tar.gz" -mtime +28 -delete

# Cloud backup (example with rclone)
0 4 * * * rclone sync ./logs remote:backup/pipeline-logs
```

---

### Log Configuration

Log behavior is configured in `src/logging_config.py` and controlled by environment variables.

#### Environment Variables

```bash
# In .env file:
LOG_LEVEL=DEBUG           # Logging level: DEBUG, INFO, WARNING, ERROR, CRITICAL
LOG_DIR=./logs           # Directory for log files
```

#### Modify Log Levels

**Change global log level:**
```bash
# In .env
LOG_LEVEL=INFO           # Less verbose
LOG_LEVEL=DEBUG          # More verbose (default)
LOG_LEVEL=WARNING        # Only warnings and errors
```

**Restart required:**
```bash
./manage-container.sh restart
```

#### Modify Rotation Settings

Edit `src/logging_config.py`:

```python
# Application log settings
app_handler = logging.handlers.RotatingFileHandler(
    filename=self.log_dir / 'application.log',
    maxBytes=100 * 1024 * 1024,  # Change size limit here
    backupCount=10,               # Change backup count here
    encoding='utf-8'
)
```

**After changes:**
```bash
# Rebuild and restart container
./manage-container.sh build
./manage-container.sh restart
```

#### Disable Specific Logs

**Disable performance logging:**
```python
# In src/logging_config.py, comment out performance logger setup
# perf_logger.addHandler(perf_handler)
```

**Disable access logging:**
```python
# In src/logging_config.py, comment out access logger setup
# access_logger.addHandler(access_handler)
```

---

### Troubleshooting with Logs

#### Problem: Container won't start

```bash
# Check Docker container logs
docker logs gitlab-pipeline-extractor

# Check if log directory has permission issues
ls -la ./logs
chmod 755 ./logs

# Check application log for startup errors
cat ./logs/application.log | grep ERROR
```

#### Problem: No logs appearing in files

```bash
# Check log directory exists and is writable
ls -la ./logs
touch ./logs/test.txt && rm ./logs/test.txt

# Check LOG_DIR setting
cat .env | grep LOG_DIR

# Check Docker volume mount
docker inspect gitlab-pipeline-extractor | grep -A 5 Mounts

# Verify inside container
./manage-container.sh shell
ls -la /app/logs
```

#### Problem: Logs filling up disk

```bash
# Check current usage
du -sh ./logs

# Check disk space
df -h .

# Immediate cleanup (delete old rotations)
rm ./logs/*.log.[5-9]* ./logs/*.log.1[0-9]*

# Reduce backup counts in src/logging_config.py
# Then rebuild container
```

#### Problem: Can't find specific request

```bash
# Search all log files including rotated
grep "pipeline_id=12345" ./logs/*.log*

# Search by date
grep "2025-10-29" ./logs/application.log*

# Search by request ID (returned in API response)
grep "a1b2c3d4" ./logs/*.log*
```

#### Problem: Performance degradation

```bash
# Check log file sizes
ls -lh ./logs/*.log

# If files are huge, rotation might be failing
# Force rotation by moving current log
mv ./logs/application.log ./logs/application.log.backup
# Container will create new file automatically

# Check for I/O errors in system logs
dmesg | grep -i error
```

#### Problem: Sensitive data in logs

Tokens and secrets are automatically masked:

```bash
# Tokens are automatically masked
grep "token" ./logs/application.log

# Example output:
# Using token: glpat-****
# Authorization: ****
```

If you find unmasked sensitive data:

```bash
# Report it (add pattern to SensitiveDataFilter in src/logging_config.py)
# Then remove from logs:
sed -i 's/your-secret-token/****REDACTED****/g' ./logs/*.log*
```

---

## Manual Testing

### Create Test Webhook Payload

```bash
# test_payload.json
cat > test_payload.json << 'EOF'
{
  "object_kind": "pipeline",
  "object_attributes": {
    "id": 12345,
    "ref": "main",
    "sha": "abc123",
    "status": "success",
    "source": "push",
    "duration": 120,
    "created_at": "2024-01-01T00:00:00Z",
    "finished_at": "2024-01-01T00:02:00Z",
    "stages": ["build", "test"]
  },
  "project": {
    "id": 123,
    "name": "test-project",
    "path_with_namespace": "group/test-project"
  },
  "user": {
    "name": "Test User",
    "username": "testuser"
  },
  "builds": [
    {
      "id": 456,
      "name": "build",
      "stage": "build",
      "status": "success"
    }
  ]
}
EOF
```

### Test Webhook Locally

```bash
# Send test webhook
curl -X POST http://localhost:8000/webhook \
  -H "Content-Type: application/json" \
  -H "X-Gitlab-Event: Pipeline Hook" \
  -H "X-Gitlab-Token: your_secret" \
  -d @test_payload.json \
  -v

# Test without secret
curl -X POST http://localhost:8000/webhook \
  -H "Content-Type: application/json" \
  -H "X-Gitlab-Event: Pipeline Hook" \
  -d @test_payload.json
```

### Test with ngrok (for local GitLab testing)

```bash
# Install ngrok
# Download from https://ngrok.com/download

# Start ngrok tunnel
ngrok http 8000

# Copy the HTTPS URL (e.g., https://abc123.ngrok.io)
# Use this URL in GitLab webhook settings:
# https://abc123.ngrok.io/webhook

# View ngrok dashboard
# http://127.0.0.1:4040
```

---

## Troubleshooting Checklist

Before asking for help, verify:

- [ ] Python version is 3.8 or higher: `python --version`
- [ ] Virtual environment is activated: `which python`
- [ ] All dependencies installed: `pip list`
- [ ] .env file exists and configured: `cat .env`
- [ ] GitLab token is valid: Test with curl
- [ ] Port 8000 is not in use: `lsof -i :8000`
- [ ] logs/ directory has write permissions: `ls -la logs/`
- [ ] Server starts without errors: Check logs
- [ ] Health endpoint responds: `curl http://localhost:8000/health`
- [ ] GitLab webhook is configured correctly
- [ ] Firewall allows incoming connections on port 8000

---

# Part 2: Monitoring & Tracking

## Monitoring Overview

The system automatically tracks **every webhook request** and maintains a complete history in a SQLite database.

**What you get:**
- ✅ Request counts and rates
- ✅ Processing status tracking
- ✅ Success/failure metrics
- ✅ Performance data (processing times)
- ✅ Error tracking with messages
- ✅ Export capabilities (CSV, JSON, SQL)

**Access methods:**
1. **CLI Dashboard** - `python monitor_dashboard.py`
2. **REST API** - `/monitor/summary`, `/monitor/recent`, etc.
3. **CSV Export** - For Excel/analysis
4. **Direct SQL** - Query `logs/monitoring.db`

---

## What is Tracked

### Automatic Tracking

Every webhook request is tracked with the following information:

| Field | Description | Example |
|-------|-------------|---------|
| `id` | Unique request ID | 1, 2, 3... |
| `timestamp` | When request was received | 2024-01-01T12:00:00Z |
| `project_id` | GitLab project ID | 123 |
| `pipeline_id` | GitLab pipeline ID | 789 |
| `pipeline_type` | Type of pipeline | main, child, merge_request |
| `status` | Processing status | queued, processing, completed, failed |
| `ref` | Git branch/tag | main, develop, v1.0.0 |
| `sha` | Git commit SHA | abc123... |
| `source` | Pipeline trigger source | push, web, schedule |
| `event_type` | GitLab event type | Pipeline Hook |
| `client_ip` | Client IP address | 192.168.1.100 |
| `processing_time` | Time to process (seconds) | 12.5 |
| `job_count` | Number of jobs in pipeline | 5 |
| `success_count` | Jobs successfully processed | 4 |
| `error_count` | Jobs that failed | 1 |
| `error_message` | Error message if failed | Connection timeout |
| `metadata` | Full pipeline info (JSON) | {...} |

### Request Status Flow

```
RECEIVED → IGNORED    (Wrong event type)
         → SKIPPED    (Pipeline not ready)
         → QUEUED → PROCESSING → COMPLETED  (Success)
                               → FAILED     (Error)
```

---

## Monitoring Dashboard

### CLI Dashboard Tool

```bash
# Show 24-hour summary (default)
python monitor_dashboard.py

# Show 48-hour summary
python monitor_dashboard.py --hours 48

# Show recent 100 requests
python monitor_dashboard.py --recent 100

# Show details for specific pipeline
python monitor_dashboard.py --pipeline 12345

# Export data to CSV
python monitor_dashboard.py --export pipeline_data.csv

# Export last 24 hours to CSV
python monitor_dashboard.py --export data.csv --hours 24
```

### Dashboard Output Example

```
======================================================================
  PIPELINE MONITORING DASHBOARD - Last 24 Hours
======================================================================

Generated: 2024-01-01T12:00:00Z

📊 OVERALL STATISTICS
   Total Requests:      150
   Success Rate:        92.3%
   Avg Processing Time: 12.5s
   Total Jobs Processed: 450

📈 REQUESTS BY STATUS
╔═══════════╦═══════╗
║ Status    ║ Count ║
╠═══════════╬═══════╣
║ Completed ║   120 ║
║ Failed    ║    10 ║
║ Skipped   ║    15 ║
║ Processing║     5 ║
╚═══════════╩═══════╝

🔀 REQUESTS BY PIPELINE TYPE
╔════════════════╦═══════╗
║ Type           ║ Count ║
╠════════════════╬═══════╣
║ Main           ║   100 ║
║ Child          ║    30 ║
║ Merge_Request  ║    20 ║
╚════════════════╩═══════╝
```

---

## API Endpoints

### 1. Monitoring Summary

Get overall statistics for a time period.

**Endpoint:** `GET /monitor/summary?hours=24`

**Example:**
```bash
curl http://localhost:8000/monitor/summary?hours=48 | jq
```

**Response:**
```json
{
  "time_period_hours": 48,
  "total_requests": 250,
  "by_status": {
    "completed": 200,
    "failed": 15,
    "skipped": 25,
    "processing": 10
  },
  "by_type": {
    "main": 180,
    "child": 50,
    "merge_request": 20
  },
  "success_rate": 93.0,
  "avg_processing_time_seconds": 14.2,
  "total_jobs_processed": 750
}
```

### 2. Recent Requests

Get most recent pipeline requests.

**Endpoint:** `GET /monitor/recent?limit=50`

**Example:**
```bash
curl http://localhost:8000/monitor/recent?limit=10 | jq
```

### 3. Pipeline Details

Get all requests for a specific pipeline.

**Endpoint:** `GET /monitor/pipeline/{pipeline_id}`

**Example:**
```bash
curl http://localhost:8000/monitor/pipeline/12345 | jq
```

### 4. Export to CSV

Download monitoring data as CSV file.

**Endpoint:** `GET /monitor/export/csv?hours=24`

**Example:**
```bash
# Download last 24 hours
curl -O http://localhost:8000/monitor/export/csv?hours=24

# Download all data
curl -O http://localhost:8000/monitor/export/csv
```

---

## Viewing Statistics

### Method 1: CLI Dashboard (Recommended)

```bash
# Quick summary
python monitor_dashboard.py

# Detailed recent requests
python monitor_dashboard.py --recent 50
```

### Method 2: API Calls

```bash
# Get summary
curl http://localhost:8000/monitor/summary | jq

# Get recent requests
curl http://localhost:8000/monitor/recent?limit=10 | jq
```

### Method 3: Interactive API Docs

Visit http://localhost:8000/docs and explore monitoring endpoints interactively.

### Method 4: Direct Database Query

```bash
# Connect to database
sqlite3 logs/monitoring.db

# Run queries
SELECT COUNT(*) FROM requests;
SELECT status, COUNT(*) FROM requests GROUP BY status;
```

---

## Exporting Data

### CSV Export via CLI

```bash
# Export all data
python monitor_dashboard.py --export all_pipelines.csv

# Export last 24 hours
python monitor_dashboard.py --export today.csv --hours 24

# Export last week
python monitor_dashboard.py --export week.csv --hours 168
```

### CSV Export via API

```bash
# Download CSV file
curl -o pipelines.csv http://localhost:8000/monitor/export/csv?hours=24
```

### Analyze in Excel/Google Sheets

1. Export CSV: `python monitor_dashboard.py --export data.csv`
2. Open in Excel/Google Sheets
3. Create pivot tables, charts, and analysis

---

## Database

### Database Location

**Default:** `logs/monitoring.db`

### Database Schema

```sql
CREATE TABLE requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    project_id INTEGER,
    pipeline_id INTEGER,
    pipeline_type TEXT,
    status TEXT NOT NULL,
    ref TEXT,
    sha TEXT,
    source TEXT,
    event_type TEXT,
    client_ip TEXT,
    processing_time REAL,
    job_count INTEGER,
    success_count INTEGER,
    error_count INTEGER,
    error_message TEXT,
    metadata TEXT
);
```

### Querying the Database

**Common queries:**

```bash
sqlite3 logs/monitoring.db

# Total requests
SELECT COUNT(*) as total_requests FROM requests;

# Requests by status
SELECT status, COUNT(*) as count
FROM requests
GROUP BY status
ORDER BY count DESC;

# Average processing time
SELECT AVG(processing_time) as avg_time
FROM requests
WHERE status = 'completed';

# Failed pipelines
SELECT pipeline_id, error_message, timestamp
FROM requests
WHERE status = 'failed'
ORDER BY timestamp DESC
LIMIT 10;

# Success rate per day
SELECT
    DATE(timestamp) as date,
    COUNT(*) as total,
    SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) as completed,
    ROUND(100.0 * SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) / COUNT(*), 2) as success_rate
FROM requests
WHERE status IN ('completed', 'failed')
GROUP BY DATE(timestamp)
ORDER BY date DESC;
```

---

## Real-World Examples

### Example 1: Check Today's Activity

```bash
# View dashboard
python monitor_dashboard.py --hours 24

# Export to CSV
python monitor_dashboard.py --export today.csv --hours 24

# Check via API
curl http://localhost:8000/monitor/summary?hours=24 | jq
```

### Example 2: Troubleshoot Failed Pipeline

```bash
# Find pipeline in recent requests
python monitor_dashboard.py --recent 100 | grep failed

# Get details for specific pipeline
python monitor_dashboard.py --pipeline 12345

# Or via API
curl http://localhost:8000/monitor/pipeline/12345 | jq
```

### Example 3: Track Performance Over Time

```bash
# Export last week
python monitor_dashboard.py --export week.csv --hours 168

# Open in Excel and create charts for:
# - Requests per day
# - Success rate trend
# - Average processing time
# - Jobs processed per day
```

### Example 4: Monitor Active Processing

```bash
# Check current processing
sqlite3 logs/monitoring.db "
SELECT pipeline_id, status, timestamp
FROM requests
WHERE status = 'processing'
ORDER BY timestamp DESC;
"
```

### Example 5: Generate Weekly Report

```bash
# Get summary for last 7 days
curl http://localhost:8000/monitor/summary?hours=168 | jq '
{
  period: "Last 7 days",
  total_requests: .total_requests,
  success_rate: "\(.success_rate)%",
  total_jobs: .total_jobs_processed,
  avg_time: "\(.avg_processing_time_seconds)s",
  breakdown: .by_status
}' | tee weekly_report.json

# Export detailed data
python monitor_dashboard.py --export weekly_data.csv --hours 168
```

---

## Advanced Operations

### Real-Time Monitoring

**Watch Mode (Linux/Mac):**

```bash
# Refresh dashboard every 30 seconds
watch -n 30 python monitor_dashboard.py

# Monitor processing requests
watch -n 5 'curl -s http://localhost:8000/monitor/summary | jq .by_status'
```

**Tail Logs + Monitor:**

```bash
# Terminal 1: Watch logs
tail -f webhook_server.log | grep "pipeline"

# Terminal 2: Dashboard
python monitor_dashboard.py
```

### Cleanup Old Data

```python
from src.monitoring import PipelineMonitor

monitor = PipelineMonitor()

# Remove records older than 30 days
deleted = monitor.cleanup_old_records(days=30)
print(f"Deleted {deleted} old records")

monitor.close()
```

Or via SQL:

```bash
sqlite3 logs/monitoring.db "
DELETE FROM requests
WHERE timestamp < datetime('now', '-30 days');
VACUUM;
"
```

### Integration with Monitoring Tools

**Prometheus/Grafana (example):**

```python
# Add /metrics endpoint
@app.get('/metrics')
async def metrics():
    summary = monitor.get_summary(hours=1)
    return {
        "pipeline_requests_total": summary['total_requests'],
        "pipeline_success_rate": summary['success_rate'],
        "pipeline_processing_time_avg": summary['avg_processing_time_seconds']
    }
```

**Alerting:**

```bash
# Check for high failure rate
python -c "
from src.monitoring import PipelineMonitor
m = PipelineMonitor()
s = m.get_summary(hours=1)
if s['success_rate'] < 90:
    print(f'ALERT: Success rate is {s[\"success_rate\"]}%')
m.close()
"
```

---

## FAQ

**Q: Where is monitoring data stored?**
A: In `logs/monitoring.db` (SQLite database)

**Q: Can I query the database while the server is running?**
A: Yes, SQLite supports concurrent reads.

**Q: How long is data kept?**
A: Forever, unless you manually clean it up. Run `monitor.cleanup_old_records(days=30)` periodically.

**Q: Can I export data for a specific project?**
A: Yes, via SQL:
```sql
SELECT * FROM requests WHERE project_id = 123;
```

**Q: Does monitoring affect performance?**
A: Minimal impact. Database writes are non-blocking and very fast.

**Q: How to backup monitoring data?**
A: Simply copy the `logs/monitoring.db` file.

---

## Getting Help

1. **Check Logs**: Always check `webhook_server.log` first
2. **Run Debug Scripts**: Use the debug scripts above
3. **Test Endpoints**: Verify each endpoint works individually
4. **Enable Debug Logging**: Set `LOG_LEVEL=DEBUG` in .env
5. **Check GitHub Issues**: Look for similar problems
6. **Provide Details**: When reporting issues, include:
   - Python version
   - Operating system
   - Error messages
   - Relevant log excerpts
   - Configuration (with secrets redacted)

---

**Last Updated**: 2024
**For more information**, see [README.md](README.md)
