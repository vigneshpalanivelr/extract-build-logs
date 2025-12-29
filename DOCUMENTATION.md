# GitLab Pipeline Log Extractor - Complete Documentation

> **Comprehensive guide for setup, configuration, operations, and maintenance**

**Last Updated:** 2025-12-29
**Version:** 2.0

---

## 📚 Table of Contents

### 1. Quick Start & Deployment
- [1.1 Quick Deployment Guide](#11-quick-deployment-guide)
  - [Problem & Solution](#the-problem-you-encountered)
  - [3-Step Setup](#solution-3-steps)
  - [Why This Happened](#why-this-happened)
- [1.2 Full Deployment Guide](#12-full-deployment-guide)
  - [Prerequisites](#prerequisites)
  - [Transferring Docker Image](#transferring-docker-image)
  - [Configuration Setup](#configuration-setup)
  - [Deployment Checklist](#deployment-checklist)
  - [Troubleshooting Common Issues](#troubleshooting-common-deployment-issues)

### 2. Setup & Installation
- [2.1 Initial Setup](#21-initial-setup)
  - [Prerequisites](#prerequisites-1)
  - [Environment Configuration](#environment-configuration)
- [2.2 Running the Application](#22-running-the-application)
  - [Docker Deployment (Recommended)](#option-1-docker-recommended-for-production)
  - [Direct Python Deployment](#option-2-direct-python)
  - [Systemd Service](#option-3-systemd-service-linux)
- [2.3 Docker Operations](#23-docker-operations)
  - [Common Commands](#common-commands)
  - [Monitoring & Testing](#monitoring--testing)

### 3. GitLab Webhook Setup
- [3.1 Webhook Configuration](#31-webhook-configuration)
  - [Prerequisites](#prerequisites-2)
  - [Setup Steps](#setup-steps)
  - [Testing the Webhook](#testing-the-webhook)
- [3.2 Webhook Troubleshooting](#32-webhook-troubleshooting)
  - [Common Issues](#webhook-troubleshooting-issues)
  - [Security Best Practices](#security-best-practices)

### 4. Jenkins Integration
- [4.1 Jenkins Setup](#41-jenkins-setup)
  - [Overview](#jenkins-overview)
  - [Configuration](#jenkins-configuration)
  - [Jenkinsfile Examples](#jenkinsfile-setup)
- [4.2 Jenkins API Integration](#42-jenkins-api-integration)
  - [Payload Format](#jenkins-api-payload-format)
  - [Testing](#jenkins-testing)
  - [Troubleshooting](#jenkins-troubleshooting)

### 5. API Posting
- [5.1 API Configuration](#51-api-configuration)
  - [Overview](#api-overview)
  - [Environment Variables](#api-environment-variables)
  - [Payload Format](#api-payload-format)
- [5.2 API Authentication & Requests](#52-api-authentication--requests)
  - [Bearer Token Authentication](#bearer-token-authentication)
  - [Request/Response Details](#api-request-and-response-details)
  - [Operating Modes](#operating-modes)
- [5.3 API Retry & Logging](#53-api-retry--logging)
  - [Retry Logic](#retry-logic)
  - [Request Logging](#api-request-logging)
  - [Debugging](#api-debugging)

### 6. Operations & Monitoring
- [6.1 Testing](#61-testing)
- [6.2 Application Logging](#62-application-logging)
  - [Logging Features](#application-logging-features)
  - [Log Files & Formats](#log-files-and-formats)
  - [Log Rotation](#log-rotation-behavior)
  - [Viewing & Searching Logs](#viewing-logs)
  - [Request ID Tracking](#request-id-tracking)
- [6.3 Monitoring Dashboard](#63-monitoring-dashboard)
  - [What is Tracked](#what-is-tracked)
  - [CLI Dashboard](#cli-dashboard-tool)
  - [API Endpoints](#monitoring-api-endpoints)
  - [Database Queries](#database-queries)
- [6.4 Common Issues & Solutions](#64-common-issues--solutions)

### 7. Database Maintenance
- [7.1 SQLite Maintenance](#71-sqlite-maintenance)
  - [Daily Tasks](#daily-tasks)
  - [Weekly Tasks](#weekly-tasks)
  - [Monthly Tasks](#monthly-tasks)
- [7.2 Backup & Restore](#72-backup--restore)
  - [Backup Strategies](#backup-strategies)
  - [Restore Procedures](#restore-procedures)
  - [Automated Scripts](#automated-backup-scripts)
- [7.3 Health Checks](#73-health-checks)
  - [Database Health](#database-health-check)
  - [Best Practices](#database-best-practices)

### 8. Appendices
- [8.1 FAQ](#81-faq)
- [8.2 Security Considerations](#82-security-considerations)
- [8.3 Getting Help](#83-getting-help)

---

# 1. Quick Start & Deployment

## 1.1 Quick Deployment Guide

### 🎯 The Problem You Encountered

When shipping a Docker image from one server to another:
- ✅ Docker image contains: Application code, dependencies
- ❌ Docker image does NOT contain: `.env` file, `logs/` directory

This causes permission errors on the new server.

### ✅ Solution (3 Steps)

#### 1️⃣ Create .env File
```bash
cd /home/user/extract-build-logs/
cp .env.example .env
nano .env  # Add your GITLAB_URL and GITLAB_TOKEN
```

#### 2️⃣ Create Logs Directory
```bash
mkdir -p logs
chmod 755 logs
chown $USER:$USER logs  # Use your username
```

#### 3️⃣ Start Container
```bash
./manage_container.py start
```

### 🔍 Why This Happened

#### Root Cause Analysis

**Issue #1: Missing .env File**
```
Docker Mount Behavior:
  If file doesn't exist → Docker creates it as directory → Permission denied

Your daemon: --userns-remap user:group
  Container UID 0 → Host UID 100000+ (no write permission)
```

**Issue #2: Missing logs Directory**
```
Docker Volume Mount:
  If directory doesn't exist → Docker creates it with wrong ownership

Result: Container can't write logs
```

#### Why It Worked on Build Server

| Server A (Build)           | Server B (Deploy)          |
|----------------------------|----------------------------|
| ✅ .env file exists        | ❌ .env file missing       |
| ✅ logs/ directory exists  | ❌ logs/ directory missing |
| ✅ Permissions correct     | ❌ No pre-existing files   |

---

## 1.2 Full Deployment Guide

### Prerequisites

- Docker installed on the target server
- Docker image transferred to target server
- Access to GitLab instance with API token
- Port 8000 (or custom port) available

### Transferring Docker Image

**Option A: Using Docker Registry** (Recommended)
```bash
# On build server (Server A)
docker tag bfa-gitlab-pipeline-extractor your-registry/bfa-gitlab-pipeline-extractor:latest
docker push your-registry/bfa-gitlab-pipeline-extractor:latest

# On deployment server (Server B)
docker pull your-registry/bfa-gitlab-pipeline-extractor:latest
docker tag your-registry/bfa-gitlab-pipeline-extractor:latest bfa-gitlab-pipeline-extractor
```

**Option B: Using docker save/load**
```bash
# On build server (Server A)
docker save bfa-gitlab-pipeline-extractor | gzip > bfa-extractor.tar.gz
scp bfa-extractor.tar.gz user@server-b:/tmp/

# On deployment server (Server B)
gunzip -c /tmp/bfa-extractor.tar.gz | docker load
```

### Configuration Setup

**Required Files:**
```bash
extract-build-logs/
├── .env.example        # Configuration template
├── manage_container.py # Container management script
└── logs/               # Will be auto-created
```

**Create .env Configuration:**
```bash
# Create .env from template
cp .env.example .env

# Edit with your credentials
nano .env
```

**Required Settings:**
```bash
# GitLab Configuration (REQUIRED)
GITLAB_URL=https://gitlab.example.com
GITLAB_TOKEN=glpat-xxxxxxxxxxxxxxxxxxxx

# Webhook Configuration (OPTIONAL)
WEBHOOK_PORT=8000
WEBHOOK_SECRET=your_webhook_secret

# BFA Configuration (OPTIONAL - for API posting)
BFA_HOST=bfa-server.example.com
BFA_SECRET_KEY=your_bfa_secret_key
```

### Deployment Checklist

- [ ] Docker installed and running
- [ ] Docker image transferred and loaded
- [ ] Repository files copied (manage_container.py, .env.example)
- [ ] `.env` file created with proper credentials
- [ ] `.env` file has correct permissions (644)
- [ ] Logs directory created (or will be auto-created)
- [ ] Port 8000 is available
- [ ] Python dependencies installed (`pip install docker rich python-dotenv`)
- [ ] Container started successfully
- [ ] Health check endpoint responds
- [ ] GitLab webhook configured and tested

### Troubleshooting Common Deployment Issues

#### Issue 1: "Permission denied" when mounting .env

**Error:**
```
docker: Error response from daemon: error while creating mount source path
'/home/user/extract-build-logs/.env': permission denied.
```

**Solution:**
```bash
# Create .env file
cp .env.example .env
nano .env

# Verify it exists
ls -la .env
```

#### Issue 2: "Cannot write to log directory"

**Solution:**
```bash
# Option 1: Let manage_container.py auto-create it
./manage_container.py start

# Option 2: Create manually with proper permissions
mkdir -p logs
chmod 755 logs
chown $USER:$USER logs
```

---

# 2. Setup & Installation

## 2.1 Initial Setup

### Prerequisites

- Python 3.8 or higher
- GitLab access token with 'api' scope
- Docker (for containerized deployment)

### Environment Configuration

**Quick Start:**
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
vi .env  # Update GITLAB_URL, GITLAB_TOKEN, etc.
```

## 2.2 Running the Application

### Option 1: Docker (Recommended for Production)

```bash
# Build and start
./manage_container.py build
./manage_container.py start

# Check status
./manage_container.py status

# Update after code changes
./manage_container.py remove
./manage_container.py build && ./manage_container.py restart
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

**Setup:**
```bash
# 1. Clone/copy the repository to /opt
sudo mkdir -p /opt
sudo cp -r . /opt/extract-build-logs
cd /opt/extract-build-logs

# 2. Configure environment
sudo cp .env.example .env
sudo nano .env  # Edit GITLAB_URL, GITLAB_TOKEN, etc.

# 3. Build Docker image
sudo ./manage_container.py build

# 4. Install systemd service
sudo cp scripts/gitlab-log-extractor.service /etc/systemd/system/
sudo systemctl daemon-reload

# 5. Start and enable service
sudo systemctl start gitlab-log-extractor
sudo systemctl enable gitlab-log-extractor

# 6. Verify it's running
sudo systemctl status gitlab-log-extractor
curl http://localhost:8000/health
```

**Manage the service:**
```bash
# View status
sudo systemctl status gitlab-log-extractor

# View logs
sudo journalctl -u gitlab-log-extractor -f

# Restart service
sudo systemctl restart gitlab-log-extractor

# Stop service
sudo systemctl stop gitlab-log-extractor
```

## 2.3 Docker Operations

### Common Commands

```bash
./manage_container.py build      # Build/rebuild image
./manage_container.py start      # Start container
./manage_container.py stop       # Stop container
./manage_container.py restart    # Restart container
./manage_container.py status     # View status and resource usage
./manage_container.py logs       # View live logs
./manage_container.py monitor    # View monitoring dashboard
./manage_container.py test       # Send test webhook
./manage_container.py remove     # Remove container/image (interactive)
```

### Monitoring & Testing

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

---

# 3. GitLab Webhook Setup

## 3.1 Webhook Configuration

### Prerequisites

- Access to GitLab project settings (Maintainer or Owner role)
- Running webhook server
- Server accessible from GitLab

### Setup Steps

#### 1. Navigate to Webhook Settings

1. Go to your GitLab project
2. Navigate to **Settings → Webhooks**

#### 2. Configure Webhook URL

Enter your server URL:
```
http://your-server-ip:8000/webhook/gitlab
```

**Examples:**
- Production: `https://logs.internal.com/webhook/gitlab`
- Local (with ngrok): `https://abc123.ngrok.io/webhook/gitlab`
- Local network: `http://192.168.1.100:8000/webhook/gitlab`

#### 3. Set Secret Token (Recommended)

```bash
# Generate a secure token
openssl rand -hex 32

# Add to GitLab webhook settings
# Add same token to .env:
WEBHOOK_SECRET=your_generated_token_here
```

#### 4. Select Trigger Events

**Enable only Pipeline events:**
- ✓ **Pipeline events** (REQUIRED)

Disable all other events unless you plan to handle them.

#### 5. Configure SSL Verification

- **Production**: Enable SSL verification
- **Development**: Disable if using self-signed certificates

### Testing the Webhook

```bash
# 1. Click "Add webhook" in GitLab

# 2. Click "Test" → "Pipeline events"

# 3. Check server logs
tail -f logs/application.log

# 4. Verify logs were saved
ls -lah logs/
```

## 3.2 Webhook Troubleshooting

### Webhook Troubleshooting Issues

#### Webhook Returns 401 Unauthorized

**Problem:** Secret token mismatch

**Solution:**
- Verify `WEBHOOK_SECRET` in `.env` matches GitLab webhook secret
- Check for extra spaces or newlines in token

#### Webhook Returns 500 Internal Server Error

**Solution:**
- Check server logs: `tail -f logs/application.log`
- Verify `GITLAB_TOKEN` has correct permissions
- Ensure `GITLAB_URL` is correct

#### Connection Refused

**Solution:**
- Verify server is running: `curl http://localhost:8000/health`
- Check firewall rules
- For local development, use ngrok

### Security Best Practices

1. **Always use HTTPS in production**
2. **Configure webhook secret token** (32+ characters)
3. **Restrict network access** to GitLab IP ranges
4. **Monitor webhook activity** regularly
5. **Limit webhook scope** to Pipeline events only

---

# 4. Jenkins Integration

## 4.1 Jenkins Setup

### Jenkins Overview

The Jenkins integration allows you to:
- Automatically extract build logs from Jenkins
- Parse console logs to identify stages and parallel execution
- Post structured log data to your API endpoint
- Handle Blue Ocean API data for better stage information

**Flow:**
```
Jenkins Pipeline Completes
    ↓
Jenkinsfile post{} block sends webhook via curl
    ↓
Log Extractor receives webhook at /webhook/jenkins
    ↓
Fetches console log via Jenkins REST API
    ↓
Parses parallel blocks from console log
    ↓
Posts structured data to your API
```

### Jenkins Configuration

**Step 1: Generate Jenkins API Token**
1. Log into Jenkins
2. Go to your user profile → **Configure**
3. Under **API Token**, click **Add new Token**
4. Copy the generated token

**Step 2: Configure Environment Variables**

```bash
# Enable Jenkins integration
JENKINS_ENABLED=true

# Jenkins connection details
JENKINS_URL=https://jenkins.example.com
JENKINS_USER=your_username
JENKINS_API_TOKEN=your_api_token_here

# Optional: Webhook secret
JENKINS_WEBHOOK_SECRET=your_secret_token

# Enable API posting
API_POST_ENABLED=true
BFA_HOST=bfa-server.example.com
BFA_SECRET_KEY=your_secret_key
```

**Step 3: Restart Service**
```bash
./manage_container.py restart
```

### Jenkinsfile Setup

**Option A: Post on Failures Only** (Recommended)

```groovy
pipeline {
    agent any

    stages {
        stage('Build') {
            steps {
                echo "Building..."
                sh './build.sh'
            }
        }

        stage('Test') {
            parallel {
                stage('Unit Tests') {
                    steps {
                        sh './test_unit.sh'
                    }
                }
                stage('Integration Tests') {
                    steps {
                        sh './test_integration.sh'
                    }
                }
            }
        }
    }

    post {
        failure {
            script {
                sh """
                    curl -X POST http://your-log-extractor:8000/webhook/jenkins \\
                        -H 'Content-Type: application/json' \\
                        -H 'X-Jenkins-Token: your_secret_token' \\
                        -d '{
                            "job_name": "${env.JOB_NAME}",
                            "build_number": ${env.BUILD_NUMBER},
                            "build_url": "${env.BUILD_URL}",
                            "status": "${currentBuild.result}",
                            "jenkins_url": "${env.JENKINS_URL}"
                        }' || true
                """
            }
        }
    }
}
```

## 4.2 Jenkins API Integration

### Jenkins API Payload Format

```json
{
  "source": "jenkins",
  "job_name": "my-pipeline",
  "build_number": 123,
  "build_url": "https://jenkins.example.com/job/my-pipeline/123/",
  "status": "FAILURE",
  "duration_ms": 45000,
  "timestamp": "2025-11-05T10:30:00Z",
  "stages": [
    {
      "stage_name": "Build",
      "stage_id": "1",
      "status": "SUCCESS",
      "duration_ms": 10000,
      "is_parallel": false,
      "log_content": "... build logs here ..."
    },
    {
      "stage_name": "Test",
      "stage_id": "2",
      "status": "FAILURE",
      "duration_ms": 30000,
      "is_parallel": true,
      "parallel_blocks": [
        {
          "block_name": "Unit Tests",
          "status": "SUCCESS",
          "log_content": "..."
        },
        {
          "block_name": "Integration Tests",
          "status": "FAILURE",
          "log_content": "... error details ..."
        }
      ]
    }
  ]
}
```

### Jenkins Testing

```bash
# Test webhook endpoint
curl http://your-log-extractor:8000/health

# Manual webhook test
curl -X POST http://your-log-extractor:8000/webhook/jenkins \
    -H 'Content-Type: application/json' \
    -H 'X-Jenkins-Token: your_secret_token' \
    -d '{
        "job_name": "test-pipeline",
        "build_number": 1,
        "build_url": "https://jenkins.example.com/job/test-pipeline/1/",
        "status": "FAILURE"
    }'
```

### Jenkins Troubleshooting

#### "Jenkins integration is not enabled"

**Solution:**
```bash
grep JENKINS_ENABLED .env  # Should be: true
./manage_container.py restart
```

#### "Failed to fetch console log"

**Solution:**
```bash
# Test Jenkins API access manually
curl -u username:api_token \
    https://jenkins.example.com/job/my-pipeline/123/consoleText

# Verify configuration
grep JENKINS_ .env
```

---

# 5. API Posting

## 5.1 API Configuration

### API Overview

The API posting feature allows you to **send pipeline logs to an external API** instead of (or in addition to) saving them to files.

**Use Cases:**
- Centralized log aggregation
- Real-time log analysis
- Integration with monitoring systems
- Custom log processing pipelines

**Key Features:**
- ✓ HTTP POST with JSON payload
- ✓ Bearer token authentication
- ✓ Automatic retry with exponential backoff
- ✓ Fallback to file storage on failure
- ✓ Dual mode (API + file simultaneously)
- ✓ 97-99% smaller payloads (error extraction)

### API Environment Variables

```bash
# ============================================================================
# BFA Server Configuration (Required for API Posting)
# ============================================================================

# BFA Host - hostname or IP (without http:// prefix)
BFA_HOST=bfa-server.example.com

# BFA Secret Key - used for Bearer token authentication
BFA_SECRET_KEY=your_bfa_secret_key

# ============================================================================
# API Posting Configuration
# ============================================================================

# Enable/disable API posting
API_POST_ENABLED=true

# Request timeout in seconds (default: 30, range: 1-300)
API_POST_TIMEOUT=30

# Enable retry on failure (default: true)
API_POST_RETRY_ENABLED=true

# Save to file even if API succeeds (dual mode, default: false)
API_POST_SAVE_TO_FILE=false
```

**API Endpoint (Auto-constructed):**
```
http://{BFA_HOST}:8000/api/analyze
```

### API Payload Format

**Simplified Format (v2.0) - Error Extraction:**

```json
{
  "repo": "api-backend",
  "branch": "feature/user-auth",
  "commit": "abc123d",
  "job_name": ["build:docker", "test:unit", "test:integration"],
  "pipeline_id": "12345",
  "triggered_by": "john.doe",
  "failed_steps": [
    {
      "step_name": "build:docker",
      "error_lines": [
        "npm ERR! code ERESOLVE",
        "npm ERR! ERESOLVE unable to resolve dependency tree",
        "ERROR: Build failed with exit code 1"
      ]
    },
    {
      "step_name": "test:integration",
      "error_lines": [
        "AssertionError: expected 401 but got 500",
        "TypeError: Cannot read property 'id' of undefined"
      ]
    }
  ]
}
```

**Error Line Extraction:**
- Automatically extracts error lines from logs
- Detects patterns: `error`, `failed`, `exception`, `traceback`, `fatal`
- Removes timestamps, ANSI codes, duplicates
- Limits to 50 error lines per job

**Payload Size Comparison:**

| Pipeline Type | Old Format | New Format | Reduction |
|--------------|------------|------------|-----------|
| Small (3 jobs, 10KB logs) | ~30 KB | ~1 KB | **97%** |
| Medium (10 jobs, 100KB logs) | ~1 MB | ~3 KB | **99.7%** |
| Large (50 jobs, 500KB logs) | ~25 MB | ~15 KB | **99.9%** |

## 5.2 API Authentication & Requests

### Bearer Token Authentication

```http
POST /api/analyze HTTP/1.1
Host: bfa-server.example.com:8000
Authorization: Bearer your_bfa_secret_key
Content-Type: application/json

{payload}
```

**Security:**
- ✓ Token is masked in logs (`Bearer *****`)
- ✓ Token never written to log files
- ✓ Same secret key used for JWT token signing

### API Request and Response Details

**Success Response (HTTP 200):**
```json
{
  "status": "ok",
  "results": [
    {
      "error_hash": "60b7634d...",
      "source": "slack_posted",
      "step_name": "unit-test",
      "error_text": "semi colon missing",
      "fix": "## Fix: Semi colon missing\n\n**Root Cause:** Missing semicolon...\n\n**Code Fix:**\n```javascript\nconst value = obj.property;\n```"
    }
  ]
}
```

**Failure Response (HTTP != 200):**
```json
{
  "error": "Invalid payload format",
  "message": "Missing required field: pipeline_id",
  "code": "INVALID_PAYLOAD"
}
```

### Operating Modes

**Mode 1: API Only (Default)**
```bash
API_POST_ENABLED=true
API_POST_SAVE_TO_FILE=false
```
- Try API first, fallback to files on failure

**Mode 2: Dual Mode (API + File)**
```bash
API_POST_ENABLED=true
API_POST_SAVE_TO_FILE=true
```
- POST to API AND save to file (always)

**Mode 3: File Only**
```bash
API_POST_ENABLED=false
```
- Save to files only, no API calls

## 5.3 API Retry & Logging

### Retry Logic

**Exponential Backoff:**
```
Attempt 1: Immediate POST
  ↓ (fails)
Wait 2 seconds

Attempt 2: Retry POST
  ↓ (fails)
Wait 4 seconds (2^1 * 2)

Attempt 3: Retry POST
  ↓ (fails)
Wait 8 seconds (2^2 * 2)

Attempt 4: Final retry
```

**Configuration:**
```bash
API_POST_RETRY_ENABLED=true
RETRY_ATTEMPTS=3
RETRY_DELAY=2
```

**Retriable errors:** Network errors, timeouts, HTTP 500-599, 429
**Non-retriable:** HTTP 400-499 (except 429)

### API Request Logging

**Log File:** `logs/api-requests.log`

**Format:**
```
[2024-01-01 10:05:00] PIPELINE_ID=12345 STATUS=success DURATION=234ms
REQUEST: POST http://bfa-server:8000/api/analyze
  Headers: Authorization: Bearer *****, Content-Type: application/json
  Payload Size: 1234 bytes (5 jobs)
RESPONSE: 200 OK
  Body: {"status": "ok", "results": [...]}
```

**Rotation:**
- Size limit: 50 MB per file
- Backups: 10 rotated files
- Total storage: ~550 MB

### API Debugging

```bash
# Check configuration
grep "^API_POST" .env

# Test API endpoint manually
curl -X POST http://bfa-server:8000/api/analyze \
  -H "Authorization: Bearer your_token" \
  -H "Content-Type: application/json" \
  -d '{...}'

# Send test webhook
./manage_container.py test

# Check API request log
tail -50 logs/api-requests.log

# Search for failures
grep "STATUS=failed" logs/api-requests.log
```

---

# 6. Operations & Monitoring

## 6.1 Testing

**Create Test Webhook Payload:**
```bash
cat > test_payload.json << 'EOF'
{
  "object_kind": "pipeline",
  "object_attributes": {
    "id": 12345,
    "ref": "main",
    "status": "success"
  },
  "project": {
    "id": 123,
    "name": "test-project"
  },
  "builds": []
}
EOF
```

**Test Webhook:**
```bash
curl -X POST http://localhost:8000/webhook/gitlab \
  -H "Content-Type: application/json" \
  -H "X-Gitlab-Event: Pipeline Hook" \
  -d @test_payload.json
```

## 6.2 Application Logging

### Application Logging Features

- ✓ **Request ID tracking** - Trace single pipeline across all log entries
- ✓ **Project names** - Human-readable logs with project names
- ✓ **Aligned columns** - Pipe-delimited format for easy parsing
- ✓ **Multiple log files** - Separate application and API logs
- ✓ **Automatic rotation** - Size-based rotation with configurable backups
- ✓ **Sensitive data masking** - Tokens automatically redacted
- ✓ **DEBUG level logging** - Detailed troubleshooting information

### Log Files and Formats

| File | Purpose | Size Limit | Backups | Total Storage |
|------|---------|------------|---------|---------------|
| **application.log** | All application logs | 100 MB | 10 | ~1.1 GB |
| **api-requests.log** | API posting requests/responses | 50 MB | 10 | ~550 MB |

**Example logs:**
```
2025-10-29 17:52:05.836 | INFO  | webhook_listener | a1b2c3d4 | Webhook received | event_type=Pipeline Hook
2025-10-29 17:52:05.837 | INFO  | webhook_listener | a1b2c3d4 | Pipeline info extracted | pipeline_id=12345
2025-10-29 17:52:06.450 | ERROR | storage_manager  | a1b2c3d4 | Failed to save log | job_id=789
```

### Log Rotation Behavior

**Automatic rotation when size limits reached:**
```bash
application.log (100 MB)     →  application.log.1 (100 MB)  # Rotated
application.log (0 KB)       ←  New file created
application.log.10           →  DELETED (exceeded backup count)
```

**Key points:**
- Happens automatically in real-time
- No restart required
- Logs persist across container restarts (volume mount)

### Viewing Logs

**Method 1: Docker Logs (Console Output)**
```bash
./manage_container.py logs
docker logs -f bfa-gitlab-pipeline-extractor
```

**Method 2: Log Files (Most Detailed)**
```bash
# Tail application log (real-time)
tail -f ./logs/application.log

# Last 100 lines
tail -n 100 ./logs/application.log

# Real-time with color highlighting
tail -f ./logs/application.log | grep --color=always -E 'ERROR|WARN|$'
```

**Method 3: Inside Container**
```bash
docker exec bfa-gitlab-pipeline-extractor tail -f /app/logs/application.log
```

**Searching Logs:**

```bash
# Search by request ID
grep "a1b2c3d4" logs/application.log

# Search by pipeline ID
grep "pipeline_id=12345" logs/application.log*

# Search by project name
grep "project_name=my-app" logs/application.log

# All errors
grep "| ERROR |" logs/application.log

# Logs from specific date
grep "2025-10-29" logs/application.log
```

### Request ID Tracking

Every webhook request gets a unique **Request ID** (e.g., `a1b2c3d4`) that appears in all related logs.

**Example:**
```
2025-10-31 06:15:13.670 | INFO  | webhook_listener    | 4729a324 | Request ID 4729a324 tracking pipeline 1061175
2025-10-31 06:15:13.670 | INFO  | pipeline_extractor  | 4729a324 | Extracted info for pipeline 1061175
2025-10-31 06:15:13.925 | INFO  | log_fetcher         | 4729a324 | Successfully fetched logs for 5 jobs
2025-10-31 06:15:13.926 | INFO  | webhook_listener    | 4729a324 | Pipeline processing completed
```

**Benefits:**
```bash
# See everything that happened for one request
grep "4729a324" logs/application.log

# Track across all log files
grep "4729a324" logs/*.log
```

## 6.3 Monitoring Dashboard

### What is Tracked

Every webhook request is tracked with:

| Field | Description | Example |
|-------|-------------|---------|
| `id` | Unique request ID | 1, 2, 3... |
| `timestamp` | When request was received | 2024-01-01T12:00:00Z |
| `project_id` | GitLab project ID | 123 |
| `pipeline_id` | GitLab pipeline ID | 789 |
| `pipeline_type` | Type of pipeline | main, child, merge_request |
| `status` | Processing status | queued, processing, completed, failed |
| `processing_time` | Time to process (seconds) | 12.5 |
| `job_count` | Number of jobs | 5 |
| `error_message` | Error message if failed | Connection timeout |

### CLI Dashboard Tool

```bash
# Show 24-hour summary (default)
python scripts/monitor_dashboard.py

# Show 48-hour summary
python scripts/monitor_dashboard.py --hours 48

# Show recent 100 requests
python scripts/monitor_dashboard.py --recent 100

# Show details for specific pipeline
python scripts/monitor_dashboard.py --pipeline 12345

# Export data to CSV
python scripts/monitor_dashboard.py --export data.csv
```

**Dashboard Output Example:**
```
======================================================================
  PIPELINE MONITORING DASHBOARD - Last 24 Hours
======================================================================

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
╚═══════════╩═══════╝
```

### Monitoring API Endpoints

**1. Monitoring Summary**
```bash
curl http://localhost:8000/monitor/summary?hours=24 | jq
```

**Response:**
```json
{
  "time_period_hours": 24,
  "total_requests": 250,
  "by_status": {
    "completed": 200,
    "failed": 15,
    "skipped": 25
  },
  "success_rate": 93.0,
  "avg_processing_time_seconds": 14.2
}
```

**2. Recent Requests**
```bash
curl http://localhost:8000/monitor/recent?limit=10 | jq
```

**3. Pipeline Details**
```bash
curl http://localhost:8000/monitor/pipeline/12345 | jq
```

**4. Export to CSV**
```bash
curl -O http://localhost:8000/monitor/export/csv?hours=24
```

### Database Queries

```bash
# Connect to database
sqlite3 logs/monitoring.db

# Total requests
SELECT COUNT(*) FROM requests;

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
```

## 6.4 Common Issues & Solutions

### Issue 1: Port Already in Use

```bash
# Find process using port
lsof -i :8000

# Kill the process
kill -9 <PID>

# Or change port in .env
echo "WEBHOOK_PORT=8001" >> .env
```

### Issue 2: Configuration Not Found

```bash
# Check .env file exists
ls -la .env

# Verify .env content
cat .env

# Export variables manually
export GITLAB_URL=https://gitlab.com
export GITLAB_TOKEN=your_token
```

### Issue 3: GitLab API Authentication Failed

```bash
# Verify token is valid
curl --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
  "https://gitlab.com/api/v4/user"

# Check token has 'api' scope in GitLab settings
```

### Issue 4: Logs Not Being Saved

```bash
# Check directory exists and permissions
ls -la logs/
chmod 755 logs/

# Verify LOG_OUTPUT_DIR in .env
cat .env | grep LOG_OUTPUT_DIR

# Check server logs for errors
tail -f logs/application.log
```

---

# 7. Database Maintenance

## 7.1 SQLite Maintenance

### Daily Tasks

**Backup Database:**
```bash
# Online backup (no downtime)
sqlite3 logs/monitoring.db ".backup logs/monitoring.db.backup_$(date +%Y%m%d)"

# Compressed backup
sqlite3 logs/monitoring.db ".dump" | gzip > backup_$(date +%Y%m%d).sql.gz
```

**Check Database Size:**
```bash
# Database file size
du -h logs/monitoring.db*

# Row count
sqlite3 logs/monitoring.db "
SELECT COUNT(*) as total_requests FROM requests;
"
```

### Weekly Tasks

**VACUUM Database (Reclaim Space):**
```bash
# Full vacuum
sqlite3 logs/monitoring.db "VACUUM;"

# Check size before and after
du -h logs/monitoring.db
```

**Integrity Check:**
```bash
sqlite3 logs/monitoring.db "PRAGMA integrity_check;"
# Expected output: "ok"
```

**Analyze Statistics:**
```bash
sqlite3 logs/monitoring.db "ANALYZE;"
```

### Monthly Tasks

**Archive Old Data:**
```bash
# Export old data to CSV
sqlite3 -header -csv logs/monitoring.db "
SELECT * FROM requests
WHERE timestamp < datetime('now', '-90 days')
" > archive_$(date +%Y%m%d).csv

# Delete old data
sqlite3 logs/monitoring.db "
DELETE FROM requests WHERE timestamp < datetime('now', '-90 days');
VACUUM;
"
```

## 7.2 Backup & Restore

### Backup Strategies

**Daily Backups (Recommended):**

```bash
#!/bin/bash
# backup-daily.sh

BACKUP_DIR="/backups/daily"
RETENTION_DAYS=7

mkdir -p $BACKUP_DIR

# SQLite backup
sqlite3 logs/monitoring.db ".backup $BACKUP_DIR/sqlite_$(date +%Y%m%d).db"

# Delete old backups
find $BACKUP_DIR -name "*.db" -mtime +$RETENTION_DAYS -delete

echo "Backup completed: $(date)"
```

**Schedule with cron:**
```bash
# Run daily at 2 AM
0 2 * * * /path/to/backup-daily.sh >> /var/log/backup.log 2>&1
```

### Restore Procedures

**From Backup File:**
```bash
# Stop service
./manage_container.py stop

# Replace database
cp logs/monitoring.db.backup_20250105 logs/monitoring.db

# Remove WAL files
rm logs/monitoring.db-wal
rm logs/monitoring.db-shm

# Start service
./manage_container.py start
```

**From SQL Dump:**
```bash
./manage_container.py stop

# Remove old database
rm logs/monitoring.db*

# Restore from dump
gunzip -c backup_20250105.sql.gz | sqlite3 logs/monitoring.db

./manage_container.py start
```

### Automated Backup Scripts

**Using Database Management Script:**

```bash
# Daily backup (keeps last 7)
./scripts/manage_database.sh backup daily

# Weekly backup (keeps last 4)
./scripts/manage_database.sh backup weekly

# Monthly backup (keeps last 6)
./scripts/manage_database.sh backup monthly

# List available backups
./scripts/manage_database.sh list

# Restore from backup
./scripts/manage_database.sh restore backups/daily/sqlite_20250107.db
```

**Cron Schedule:**
```bash
# Daily backup at 2 AM
0 2 * * * cd /path/to/extract-build-logs && ./scripts/manage_database.sh backup daily

# Weekly backup on Sunday at 3 AM
0 3 * * 0 cd /path/to/extract-build-logs && ./scripts/manage_database.sh backup weekly

# Monthly backup on 1st at 4 AM
0 4 1 * * cd /path/to/extract-build-logs && ./scripts/manage_database.sh backup monthly
```

## 7.3 Health Checks

### Database Health Check

```bash
# Run health check
./scripts/manage_database.sh check
```

**Example output:**
```
===================================
Database Health Check
Type: sqlite
Date: Thu Jan  7 10:30:00 UTC 2025
===================================

SQLite Health Check
-------------------
Database connection: ✓ OK
Requests table: ✓ OK (1234 rows)
Recent activity (last hour): ✓ 45 requests
Database size: ✓ 12 MB
Integrity check: ✓ OK
WAL mode: ✓ Enabled

===================================
✓ Health Check: PASSED
===================================
```

**Schedule with cron:**
```bash
# Every hour
0 * * * * cd /path/to/extract-build-logs && ./scripts/manage_database.sh check >> /var/log/db-health.log 2>&1
```

### Database Best Practices

**SQLite:**
1. Always stop service before file-based backups
2. Use WAL mode (enabled by default)
3. Regular VACUUM - weekly for active databases
4. Keep database small - archive data older than 90 days
5. Integrity checks - weekly minimum
6. Single writer - don't run multiple instances

**General:**
1. Test restores - backup is only good if restore works
2. Monitor disk space - keep 50% free
3. Automate backups - don't rely on manual processes
4. Off-site backups - copy to cloud/remote location
5. Document procedures - ensure team knows how to restore

---

# 8. Appendices

## 8.1 FAQ

**Q: What are the webhook endpoints?**
A:
- GitLab: `http://your-host:8000/webhook/gitlab`
- Jenkins: `http://your-host:8000/webhook/jenkins`

**Q: How do I test the webhook?**
A: Run `./manage_container.py test` to send a test webhook

**Q: Where are logs stored?**
A: In `logs/` directory:
- `application.log` - All application logs (DEBUG level)
- `api-requests.log` - API posting requests/responses
- `monitoring.db` - SQLite database with request tracking

**Q: Can I query the database while server is running?**
A: Yes, SQLite with WAL mode supports concurrent reads

**Q: How long is data kept?**
A:
- Logs: Automatically rotated based on size
- Monitoring data: Forever, unless manually cleaned via `cleanup_old_records()`

**Q: What does the remove command do?**
A: Interactively asks what to remove:
- Container only (keeps image)
- Container and image
- Logs are always preserved

**Q: How to backup data?**
A:
- Logs: `tar -czf logs_backup.tar.gz ./logs`
- Database: `./scripts/manage_database.sh backup daily`

## 8.2 Security Considerations

### Protecting Secrets

**Never commit to version control:**
- `.env` file (contains tokens and secrets)
- `logs/` directory

**Verify .gitignore:**
```
.env
logs/
*.log
```

**File Permissions:**
```bash
.env            → 644 (rw-r--r--)
logs/           → 755 (rwxr-xr-x)
manage_container.py → 755 (rwxr-xr-x)
```

### Network Security

**Firewall rules:**
```bash
# Allow only GitLab server IP
sudo ufw allow from <gitlab-server-ip> to any port 8000

# Or use nginx reverse proxy with SSL
```

**HTTPS in Production:**
- Use reverse proxy (nginx) with SSL certificate
- Use Let's Encrypt for free SSL certificates
- Always use HTTPS for webhook URLs

## 8.3 Getting Help

1. **Check Logs**: Always check `logs/application.log` first
2. **View Container Status**: Run `./manage_container.py status`
3. **Test Endpoints**: Run `./manage_container.py test`
4. **Enable Debug Logging**: Set `LOG_LEVEL=DEBUG` in .env
5. **Check GitHub Issues**: Look for similar problems

**When reporting issues, include:**
- Python version
- Operating system
- Error messages from logs
- Container status output
- Configuration (with secrets redacted)

---

**© 2025 GitLab Pipeline Log Extractor**
**Documentation Version:** 2.0
**Last Updated:** 2025-12-29
