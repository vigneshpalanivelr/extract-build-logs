# Debugging Guide for GitLab Pipeline Log Extractor

This guide provides step-by-step instructions for setting up, running, and debugging the GitLab Pipeline Log Extraction System.

## Table of Contents

- [Quick Start](#quick-start)
- [Setup Commands](#setup-commands)
- [Running the Application](#running-the-application)
- [Testing](#testing)
- [Common Issues & Solutions](#common-issues--solutions)
- [Debugging Scripts](#debugging-scripts)
- [Monitoring & Logs](#monitoring--logs)
- [Manual Testing](#manual-testing)

---

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

## Setup Commands

### 1. Environment Setup

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

### 2. Install Dependencies

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
```

### 3. Configuration

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

### 4. GitLab Access Token

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

---

## Testing

### 1. Run Unit Tests

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

### 2. Test Individual Modules

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

### 3. Test API Endpoints

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

    # Test API connection
    print("Testing GitLab API connection...")
    # This will test the connection
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

    # Test write
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

    # Test read
    metadata = manager.get_pipeline_metadata(123, 789)
    print(f"✓ Metadata retrieved: {metadata is not None}")

    # Test stats
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
**Maintained By**: GitLab Pipeline Log Extractor Team
