# GitLab Pipeline Log Extractor - Operations Guide

Complete guide for debugging, monitoring, and operating the GitLab Pipeline Log Extraction System.

## Table of Contents

### Part 1: Setup & Operations
- [Quick Start](#quick-start)
- [Setup & Installation](#setup--installation)
- [Running the Application](#running-the-application)
- [Docker Operations](#docker-operations)
- [Testing](#testing)
- [Common Issues & Solutions](#common-issues--solutions)
- [Debugging Scripts](#debugging-scripts)
- [Application Logging System](#application-logging-system)
- [Manual Testing](#manual-testing)
- [Troubleshooting Checklist](#troubleshooting-checklist)

### Part 2: Monitoring & Tracking
- [Monitoring Overview](#monitoring-overview)
- [What is Tracked](#what-is-tracked)
- [Monitoring Dashboard](#monitoring-dashboard)
- [API Endpoints](#api-endpoints)
- [Viewing Statistics](#viewing-statistics)
- [Exporting Data](#exporting-data)
- [Database](#database)
- [Real-World Examples](#real-world-examples)
- [Advanced Operations](#advanced-operations)
- [FAQ](#faq)

---

# Part 1: Setup & Operations

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

**Prerequisites:**
- Python 3.8 or higher
- GitLab access token with 'api' scope
- Docker (for containerized deployment)

**Key Steps:**
1. Create virtual environment: `python3 -m venv venv && source venv/bin/activate`
2. Install dependencies: `pip install -r requirements.txt`
3. Configure environment: `cp .env.example .env` and edit with your settings
4. Set required variables: `GITLAB_URL` and `GITLAB_TOKEN`
5. Start server: `python src/webhook_listener.py` or use Docker

---

## Running the Application

### Option 1: Docker (Recommended for Production)

```bash
# Build and start
./manage_container.py build
./manage_container.py start

# Check status
./manage_container.py status

# View logs
./manage_container.py logs
```

**Benefits:** Isolated environment, automatic restarts, persistent storage, easy deployment

### Option 2: Direct Python

```bash
# Standard run
python src/webhook_listener.py

# Development mode (auto-reload)
uvicorn src.webhook_listener:app --reload --host 0.0.0.0 --port 8000

# Background process
nohup python src/webhook_listener.py > server.log 2>&1 &
```

### Option 3: Systemd Service (Linux)

```bash
# Create service file at /etc/systemd/system/gitlab-log-extractor.service
# See README.md for full configuration

sudo systemctl start gitlab-log-extractor
sudo systemctl enable gitlab-log-extractor
sudo systemctl status gitlab-log-extractor
```

---

## Docker Operations

**Quick Start:**
```bash
# Build and start
./manage_container.py build
./manage_container.py start
./manage_container.py status
```

**Common Commands:**
```bash
./manage_container.py build      # Build/rebuild image
./manage_container.py start      # Start container
./manage_container.py stop       # Stop container
./manage_container.py restart    # Restart container
./manage_container.py status     # View status and resource usage
./manage_container.py logs       # View live logs
./manage_container.py shell      # Open shell inside container
./manage_container.py monitor    # View monitoring dashboard
./manage_container.py test       # Send test webhook
./manage_container.py remove     # Remove container
./manage_container.py cleanup    # Remove container and image
```

**Monitoring & Testing:**
```bash
# View monitoring dashboard
./manage_container.py monitor --hours 24

# Export monitoring data
./manage_container.py export data.csv

# Send test webhook
./manage_container.py test

# Access API endpoints
curl http://localhost:8000/health
curl http://localhost:8000/monitor/summary?hours=24
```

### Troubleshooting Docker

**Common Issues:**
```bash
# Container won't start
docker logs bfa-gitlab-pipeline-extractor
./manage_container.py remove && ./manage_container.py start

# Port already in use
sudo lsof -i :8000
sudo kill <PID>

# Permission issues
sudo chown -R 1000:1000 ./logs

# Update after code changes
./manage_container.py build && ./manage_container.py restart

# Backup logs
tar -czf backup_$(date +%Y%m%d).tar.gz ./logs
```

**Production Checklist:**
- [ ] .env configured with GITLAB_URL and GITLAB_TOKEN
- [ ] WEBHOOK_SECRET set for security
- [ ] Logs directory permissions correct (UID 1000)
- [ ] Port 8000 accessible from GitLab
- [ ] Health checks passing: `curl http://localhost:8000/health`

---

## Testing

### Run Unit Tests

```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=src --cov=. --cov-report=term-missing

# Generate HTML coverage report
pytest tests/ --cov=src --cov=. --cov-report=html
# Open htmlcov/index.html in browser

# Run specific test file
pytest tests/test_pipeline_extractor.py -v

# Run specific test
pytest tests/test_pipeline_extractor.py::TestClass::test_method -v

# Run tests matching pattern
pytest tests/ -k "test_config" -v
```

### Test Container Management Script

```bash
# Run all tests for manage_container.py
pytest tests/test_manage_container.py -v

# Run with coverage
pytest tests/test_manage_container.py --cov=manage_container --cov-report=term-missing

# Test specific functionality
pytest tests/test_manage_container.py::TestLoadConfig -v
pytest tests/test_manage_container.py::TestBuildImage -v
pytest tests/test_manage_container.py::TestStartContainer -v
```

### Parallel Testing

```bash
# Install pytest-xdist for parallel execution
pip install pytest-xdist

# Run tests in parallel (4 workers)
pytest tests/ -n 4 -v

# Run tests in parallel with coverage
pytest tests/ -n auto --cov=src --cov-report=term-missing
```

### Watch Mode

```bash
# Install pytest-watch
pip install pytest-watch

# Auto-run tests on file changes
ptw tests/ -- -v
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

### Integration Testing

```bash
# End-to-end Docker workflow
./manage_container.py build
./manage_container.py start --yes
./manage_container.py status
./manage_container.py test
./manage_container.py logs --no-follow | tail -20
./manage_container.py monitor
./manage_container.py export test_data.csv
./manage_container.py cleanup --force
```

### Debugging Tests

```bash
# Run with maximum verbosity
pytest tests/ -vvv -s

# Show local variables on failure
pytest tests/ --showlocals

# Drop into debugger on failure
pytest tests/ --pdb

# Run specific failing test with full output
pytest tests/test_file.py::test_name -vv -s
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

**Test Configuration:**
```bash
python src/config_loader.py
```

**Test Individual Components:**
```bash
python src/storage_manager.py
python src/error_handler.py
python src/pipeline_extractor.py
```

**Check Dependencies:**
```bash
pip list | grep -E "fastapi|uvicorn|requests|python-dotenv|pytest"
```

---

## Monitoring & Logs

**View Logs:**
```bash
# Real-time
tail -f logs/application.log

# Search for errors
grep ERROR logs/application.log

# Search for specific pipeline
grep "pipeline_id=12345" logs/application.log
```

**Monitor Storage:**
```bash
# Check storage size
du -sh logs/

# Count log files
find logs/ -name "*.log" | wc -l
```

**System Resources:**
```bash
# Docker
./manage_container.py status

# Direct Python
top -p $(pgrep -f webhook_listener)
```

---

## Application Logging System

The system includes a comprehensive logging infrastructure that tracks all operations, errors, and performance metrics with automatic rotation and retention management.

### Logging Overview

**Features:**
- ✓ **Aligned columns** for easy reading
- ✓ **Project names** in logs instead of just IDs
- ✓ **Request ID tracking** with project and pipeline information
- ✓ Pipe-delimited plain text format for easy parsing
- ✓ Multiple specialized log files (application, access, performance)
- ✓ Request ID correlation across all logs
- ✓ Automatic sensitive data masking (tokens, secrets)
- ✓ Automatic log rotation with size limits
- ✓ DEBUG level logging for detailed troubleshooting
- ✓ **Flexible log filtering** by pipeline/job status and project
- ✓ Both console and file output
- ✓ Logs visible in Docker container output
- ✓ Persistent storage across container restarts

**Log Format (Aligned Columns):**
```
timestamp              | level    | logger                          | req_id   | message                   | context
2025-10-31 06:15:13.670 | INFO     | src.webhook_listener           | 4729a324 | Webhook received          | event_type=Pipeline Hook source_ip=192.168.1.100
```

**Column Widths:**
- Timestamp: 23 chars (fixed)
- Level: 8 chars (padded)
- Logger: 30 chars (padded/truncated)
- Request ID: 8 chars (padded)
- Message: Variable
- Context: Variable

**Example (Showing Request ID Tracking):**
```
2025-10-31 06:15:13.670 | INFO     | src.webhook_listener           | 4729a324 | Request ID 4729a324 tracking pipeline 1061175 from project 'my-app' (ID: 123)
2025-10-31 06:15:13.670 | INFO     | src.pipeline_extractor         | 4729a324 | Extracted info for pipeline 1061175 from project 'my-app' (type: main, status: success)
2025-10-31 06:15:13.700 | INFO     | src.webhook_listener           | 4729a324 | Starting pipeline log extraction for 'my-app'
2025-10-31 06:15:13.925 | INFO     | src.log_fetcher                | 4729a324 | Successfully fetched logs for 0 jobs
2025-10-31 06:15:13.926 | INFO     | src.webhook_listener           | 4729a324 | Pipeline processing completed for 'my-app'
```

**Benefits:**
- Easy to trace a single pipeline across all log entries using Request ID
- Project names make logs human-readable
- Aligned columns improve readability for manual review
- Pipe-delimited format allows easy parsing with grep, awk, or log analysis tools

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
- ✓ Rotation happens automatically in real-time
- ✓ No application restart required
- ✓ No interruption to logging
- ✓ Old files are numbered sequentially
- ✓ Oldest file (beyond backup count) is deleted
- ✓ You always have current file + N backups

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
- ✓ Logs survive container deletion
- ✓ Logs survive container recreation
- ✓ Logs survive host reboots
- ✓ You can access logs from host even when container is stopped

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
./manage_container.py logs

# Or directly with Docker
docker logs -f bfa-gitlab-pipeline-extractor

# Last 100 lines
docker logs --tail 100 bfa-gitlab-pipeline-extractor

# Logs since specific time
docker logs --since "2025-10-29T10:00:00" bfa-gitlab-pipeline-extractor
```

**What you see:** Console handler output (respects LOG_LEVEL from .env configuration)

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
./manage_container.py shell

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

#### Search by Project Name

```bash
# Find all logs for a specific project
grep "project_name=my-app" logs/application.log

# Search with project name in message
grep "from project 'my-app'" logs/application.log

# Extract all project names
grep -oP "project_name=\K[^' |]+" logs/application.log | sort -u

# Count logs by project
grep -oP "project_name=\K[^' |]+" logs/application.log | sort | uniq -c | sort -rn
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
./manage_container.py restart
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
./manage_container.py build
./manage_container.py restart
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

### Log Filtering Configuration

The system supports flexible filtering to control which logs are saved, reducing storage requirements while maintaining visibility into important events.

#### Filtering Options

All filtering is configured via environment variables in `.env`:

```bash
# ============================================================================
# LOG FILTERING CONFIGURATION
# ============================================================================

# Which pipeline statuses to save logs for
# Options: all, failed, success, running, canceled, skipped
# Multiple values: failed,canceled,skipped
LOG_SAVE_PIPELINE_STATUS=all

# Which projects to save logs for (comma-separated project IDs)
# Leave empty to save all projects
LOG_SAVE_PROJECTS=

# Which projects to exclude from logging
LOG_EXCLUDE_PROJECTS=

# Which job statuses to save logs for
# Options: all, failed, success, canceled, skipped
LOG_SAVE_JOB_STATUS=all

# Save pipeline metadata even if logs are filtered
LOG_SAVE_METADATA_ALWAYS=true
```

#### Common Filtering Scenarios

**Scenario 1: Save only failed pipeline logs (90% storage reduction)**
```bash
LOG_SAVE_PIPELINE_STATUS=failed,canceled
LOG_SAVE_JOB_STATUS=all
LOG_SAVE_METADATA_ALWAYS=true
```

**Result:**
- Only pipelines with status `failed` or `canceled` will have logs saved
- Metadata for all pipelines is still saved (for tracking)
- Logs show: "Pipeline X skipped - status 'success' not in filter [failed,canceled]"

**Scenario 2: Save logs only for specific projects**
```bash
LOG_SAVE_PROJECTS=123,456,789
LOG_SAVE_PIPELINE_STATUS=all
LOG_SAVE_JOB_STATUS=all
```

**Result:**
- Only projects with IDs 123, 456, or 789 will have logs saved
- All other projects are skipped
- Logs show: "Pipeline X from 'other-project' (ID: 999) skipped - not in whitelist [123,456,789]"

**Scenario 3: Exclude noisy test projects**
```bash
LOG_EXCLUDE_PROJECTS=999,888
LOG_SAVE_PIPELINE_STATUS=all
LOG_SAVE_JOB_STATUS=all
```

**Result:**
- All projects except 999 and 888 will have logs saved
- Logs show: "Pipeline X from 'test-project' (ID: 999) skipped - in blacklist [999,888]"

**Scenario 4: Save all pipelines, but only failed job logs**
```bash
LOG_SAVE_PIPELINE_STATUS=all
LOG_SAVE_JOB_STATUS=failed,canceled
LOG_SAVE_METADATA_ALWAYS=true
```

**Result:**
- All pipeline metadata is saved
- Only job logs with status `failed` or `canceled` are saved
- Successful jobs are skipped
- Logs show: "Job 456 'test-job' from 'my-app' skipped - status 'success' not in filter [failed,canceled]"

#### Filtering Benefits

- **Storage Savings**: Reduce storage by 70-90% by saving only failed pipelines
- **Focus on Failures**: Makes it easier to find and debug problems
- **Multi-Project Support**: Easily add/remove projects without code changes
- **Flexible**: Combine filters for fine-grained control
- **Visibility**: Always know what's being filtered via logs

#### Monitoring Filtered Logs

Check how many logs are being filtered:

```bash
# Count filtered pipelines
grep "skipped - status" logs/application.log | wc -l

# See which projects are being filtered
grep "skipped - not in whitelist" logs/application.log

# Count skipped jobs
grep "Job.*skipped" logs/application.log | wc -l
```

---

### Troubleshooting with Logs

#### Problem: Container won't start

```bash
# Check Docker container logs
docker logs bfa-gitlab-pipeline-extractor

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
docker inspect bfa-gitlab-pipeline-extractor | grep -A 5 Mounts

# Verify inside container
./manage_container.py shell
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
- ✓ Request counts and rates
- ✓ Processing status tracking
- ✓ Success/failure metrics
- ✓ Performance data (processing times)
- ✓ Error tracking with messages
- ✓ Export capabilities (CSV, JSON, SQL)

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

OVERALL STATISTICS
   Total Requests:      150
   Success Rate:        92.3%
   Avg Processing Time: 12.5s
   Total Jobs Processed: 450

REQUESTS BY STATUS
╔═══════════╦═══════╗
║ Status    ║ Count ║
╠═══════════╬═══════╣
║ Completed ║   120 ║
║ Failed    ║    10 ║
║ Skipped   ║    15 ║
║ Processing║     5 ║
╚═══════════╩═══════╝

REQUESTS BY PIPELINE TYPE
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
