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

For future deployments to new servers:

**Required Manual Steps:**
- [ ] Transfer Docker image to new server
- [ ] Copy `manage_container.py` to new server
- [ ] Copy `.env.example` to new server
- [ ] Create `.env` file with credentials
- [ ] Install Python dependencies: `pip install docker rich python-dotenv`
- [ ] Verify Docker is installed and running
- [ ] Verify port 8000 is available (or custom port configured)

**Auto-handled by manage_container.py:**
- [x] Create logs directory
- [x] Set proper permissions
- [x] Configure container with namespace bypass
- [x] Mount volumes correctly
- [x] Start container with correct settings

**Post-Deployment Verification:**
- [ ] Container started successfully (`./manage_container.py status`)
- [ ] Health check endpoint responds (`curl http://localhost:8000/health`)
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

#### Issue 3: Docker User Namespace Issues

**Error:**
```
Permission denied errors despite correct ownership
```

**Cause:** Docker daemon running with `--userns-remap`

**Solution:** The container now runs with these settings to bypass namespace issues:
```python
user='root'           # Run as root inside container
userns_mode='host'    # Bypass user namespace remapping
```

This is already configured in `manage_container.py` (lines 734-735).

### Security Considerations

#### Protecting Secrets

**Never commit these to version control:**
- `.env` file (contains GITLAB_TOKEN, BFA_SECRET_KEY)
- `logs/` directory (contains pipeline logs)

**Verify .gitignore includes:**
```
.env
logs/
*.log
```

#### File Permissions

**Recommended permissions:**
```bash
.env            → 644 (rw-r--r--) - readable by owner and group
logs/           → 755 (rwxr-xr-x) - writable by owner, readable by others
manage_container.py → 755 (rwxr-xr-x) - executable
```

#### Network Security

**Firewall rules:**
```bash
# Allow only specific IPs to access webhook (GitLab server)
sudo ufw allow from <gitlab-server-ip> to any port 8000

# Or use nginx reverse proxy with SSL
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

#### 6. Test the Webhook

1. Click **"Add webhook"** to save

2. Scroll down to find your webhook in the list

3. Click **"Test" → "Pipeline events"**

4. Check your server logs for the test event:
   ```bash
   tail -f logs/application.log
   ```

5. Expected response: `200 OK` with JSON response

#### 7. Verify Event Reception

Trigger a real pipeline and verify logs are extracted:

1. **Push a commit or manually run a pipeline**

2. **Check server logs:**
   ```bash
   tail -f logs/application.log
   ```

   You should see:
   - `Webhook received | event_type=Pipeline Hook`
   - `Pipeline info extracted | pipeline_id=XXXXX`
   - `Pipeline processing completed`

3. **Verify logs were saved:**
   ```bash
   ls -lah logs/
   ```

   You should see log files corresponding to the pipeline that just ran.

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
   - Use reverse proxy (nginx, Apache) with SSL certificate
   - Use Let's Encrypt for free SSL certificates

2. **Configure webhook secret token**
   - Use strong random tokens (32+ characters)
   - Rotate tokens periodically

3. **Restrict network access**
   - Use firewall rules to allow only GitLab IP ranges
   - GitLab.com IP ranges: https://docs.gitlab.com/ee/user/gitlab_com/

4. **Monitor webhook activity**
   - Review logs regularly
   - Set up alerts for failed requests

5. **Limit webhook scope**
   - Only enable Pipeline events
   - Consider separate webhooks for different purposes

### Testing with curl

You can test the webhook endpoint manually:

```bash
curl -X POST http://localhost:8000/webhook/gitlab \
  -H "Content-Type: application/json" \
  -H "X-Gitlab-Event: Pipeline Hook" \
  -H "X-Gitlab-Token: your_secret_token" \
  -d @test_payload.json
```

**Example test payload:**
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

#### Step 1: Test Webhook Endpoint

```bash
# Test that the endpoint is accessible
curl http://your-log-extractor:8000/health

# Expected response:
# {"status":"healthy","service":"gitlab-log-extractor","version":"1.0.0"}
```

#### Step 2: Manual Webhook Test

```bash
curl -X POST http://your-log-extractor:8000/webhook/jenkins \
    -H 'Content-Type: application/json' \
    -H 'X-Jenkins-Token: your_secret_token' \
    -d '{
        "job_name": "test-pipeline",
        "build_number": 1,
        "build_url": "https://jenkins.example.com/job/test-pipeline/1/",
        "status": "FAILURE",
        "jenkins_url": "https://jenkins.example.com"
    }'

# Expected response:
# {
#   "status": "success",
#   "message": "Jenkins build logs queued for extraction",
#   "job_name": "test-pipeline",
#   "build_number": 1,
#   "request_id": "a1b2c3d4"
# }
```

#### Step 3: Trigger Jenkins Build

1. Run a Jenkins pipeline that has the webhook configured
2. Let it fail (or complete)
3. Check the logs:

```bash
# View container logs
./manage_container.py logs

# Or check API request logs
tail -f logs/api-requests.log
```

#### Step 4: Verify API Received Data

Check your API endpoint to confirm it received the payload with:
- Job name and build number
- All stages
- Parallel blocks (if any)
- Full console logs

### Jenkins Troubleshooting

#### "Jenkins integration is not enabled"

**Solution:**
```bash
grep JENKINS_ENABLED .env  # Should be: true
./manage_container.py restart
```

#### "Failed to fetch console log"

**Problem:** Can't retrieve logs from Jenkins

**Solution:**
```bash
# Test Jenkins API access manually
curl -u username:api_token \
    https://jenkins.example.com/job/my-pipeline/123/consoleText

# Check:
# 1. JENKINS_URL is correct (no trailing slash)
# 2. JENKINS_USER is correct
# 3. JENKINS_API_TOKEN is valid
# 4. Network connectivity from container to Jenkins

# Verify configuration
grep JENKINS_ .env
```

#### "Parallel blocks not detected"

**Problem:** All stages show `is_parallel: false`

**Solution:**
- Jenkins must be using **Scripted Pipeline** or **Declarative Pipeline** with `parallel` keyword
- Console log must contain `[Pipeline] parallel` markers
- If using Blue Ocean, check that the plugin is installed:
  - Jenkins → Manage Plugins → Installed → search for "Blue Ocean"

#### "API POST failed"

**Problem:** Logs extracted but not posted to API

**Solution:**
```bash
# Check API configuration
grep API_POST .env

# Test API endpoint manually
curl -X POST http://bfa-server:8000/api/analyze \
    -H 'Content-Type: application/json' \
    -H 'Authorization: Bearer your_token' \
    -d '{"test": "data"}'

# Check logs for error details
grep "API" logs/api-requests.log
```

#### Viewing Detailed Logs

```bash
# Enable debug logging
# Edit .env:
LOG_LEVEL=DEBUG

# Restart service
./manage_container.py restart

# View logs in real-time
./manage_container.py logs
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

**Validation Rules:**

| Variable | Required | Default | Validation |
|----------|----------|---------|------------|
| `BFA_HOST` | Yes (if API enabled) | - | Hostname or IP address |
| `BFA_SECRET_KEY` | Yes (if API enabled) | - | Any string (used as Bearer token) |
| `API_POST_ENABLED` | No | `false` | Must be `true` or `false` |
| `API_POST_TIMEOUT` | No | `30` | Integer between 1-300 |
| `API_POST_RETRY_ENABLED` | No | `true` | Must be `true` or `false` |
| `API_POST_SAVE_TO_FILE` | No | `false` | Must be `true` or `false` |

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

### Field Descriptions

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `repo` | string | Repository name (short form, without org/group) | `"api-backend"` |
| `branch` | string | Git branch or tag name | `"main"`, `"feature/xyz"` |
| `commit` | string | Short commit SHA (7 characters) | `"abc123d"` |
| `job_name` | array of strings | List of **all** job names in pipeline | `["build", "test", "deploy"]` |
| `pipeline_id` | string | Pipeline ID as string | `"12345"` |
| `triggered_by` | string | Username who triggered pipeline, or source type | `"john.doe"`, `"push"`, `"schedule"` |
| `failed_steps` | array of objects | **Only failed jobs** with extracted error lines | See below |

**failed_steps Object:**

| Field | Type | Description |
|-------|------|-------------|
| `step_name` | string | Name of the failed job |
| `error_lines` | array of strings | Extracted error lines from job log (max 50 lines per job) |

### Error Line Extraction

The system **automatically extracts error lines** from job logs by detecting these patterns (case-insensitive):

**Error Keywords:**
- `error`, `err!`, `failed`, `failure`, `exception`, `traceback`
- `fatal`, `critical`, `exit code`

**Error Types:**
- `SyntaxError`, `TypeError`, `AssertionError`, `ValueError`, `RuntimeError`
- `AttributeError`, `ImportError`, `KeyError`, etc.

**Test Failures:**
- `tests failed`, `assertion failed`, `expected X but got Y`

**Build Failures:**
- `build failed`, `compilation error`, `npm ERR!`, `ERESOLVE`

**Automatic Cleaning:**
- ✓ Removes timestamps (e.g., `2024-01-01 10:00:00`)
- ✓ Removes ANSI color codes
- ✓ Trims whitespace
- ✓ Removes duplicate lines
- ✓ Limits to 50 error lines per job (configurable)

### Example: Full Logs vs Error Extraction

**Original Job Log (2.3 KB):**
```
Step 1/5 : FROM node:18-alpine
 ---> abc123
Step 2/5 : WORKDIR /app
 ---> Using cache
 ---> def456
Step 3/5 : COPY package*.json ./
 ---> 789ghi
Step 4/5 : RUN npm ci
npm ERR! code ERESOLVE
npm ERR! ERESOLVE unable to resolve dependency tree
npm ERR! Could not resolve dependency:
npm ERR! peer react@"^17.0.0" from react-dom@17.0.2
ERROR: npm install failed
ERROR: Build failed with exit code 1
The command '/bin/sh -c npm ci' returned a non-zero code: 1
```

**Extracted error_lines (0.2 KB):**
```json
[
  "npm ERR! code ERESOLVE",
  "npm ERR! ERESOLVE unable to resolve dependency tree",
  "npm ERR! Could not resolve dependency:",
  "npm ERR! peer react@\"^17.0.0\" from react-dom@17.0.2",
  "ERROR: npm install failed",
  "ERROR: Build failed with exit code 1"
]
```

### Successful Pipelines

If `LOG_SAVE_PIPELINE_STATUS=failed` (recommended):
- ✓ **Successful pipelines are ignored** - no API call is made
- ✓ Only failed pipelines trigger API posting
- ✓ Reduces API traffic by 80-90% in typical environments

If `LOG_SAVE_PIPELINE_STATUS=all`:
- Successful pipelines will have `failed_steps: []` (empty array)

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

#### Step 1: Check Configuration

```bash
# Verify environment variables are set:
grep "^API_POST" .env

# Expected output:
# API_POST_ENABLED=true
# BFA_HOST=bfa-server.example.com
# BFA_SECRET_KEY=your_secret_key

# Check if configuration loaded correctly:
grep "API posting" logs/application.log

# Expected output:
# INFO | API posting enabled: http://bfa-server.example.com:8000/api/analyze
```

#### Step 2: Test API Endpoint Manually

```bash
# Test with curl:
curl -X POST http://bfa-server.example.com:8000/api/analyze \
  -H "Authorization: Bearer your_token" \
  -H "Content-Type: application/json" \
  -d '{
    "repo": "test",
    "branch": "main",
    "commit": "abc123",
    "job_name": ["test"],
    "pipeline_id": "99999",
    "triggered_by": "test",
    "failed_steps": []
  }'

# Expected response:
# {"status": "ok", "results": []}
```

#### Step 3: Send Test Webhook

```bash
# Use built-in test command:
./manage_container.py test

# This triggers a test pipeline event
# Check if API POST was attempted:
tail -20 logs/api-requests.log
```

#### Step 4: Check API Request Log

```bash
# View last 50 lines:
tail -50 logs/api-requests.log

# Look for:
# - REQUEST line (should show your API URL)
# - RESPONSE line (should show 200 OK)
# - Any error messages
```

#### Step 5: Check Application Log

```bash
# Search for API-related errors:
grep -i "api post" logs/application.log

# Search for specific pipeline:
grep "pipeline_id=12345" logs/application.log
```

#### Step 6: Verify Network Connectivity

```bash
# Test if API is reachable:
curl -I http://bfa-server.example.com:8000/api/analyze

# Expected:
# HTTP/1.1 200 OK (or 405 Method Not Allowed for GET)

# Check DNS resolution:
nslookup bfa-server.example.com

# Check connectivity:
ping bfa-server.example.com
```

#### Step 7: Check Container Logs

```bash
# If using Docker:
docker logs bfa-gitlab-pipeline-extractor | grep -i "api"

# Or:
./manage_container.py logs | grep -i "api"
```

**Common Debug Commands:**

```bash
# 1. Is API posting enabled?
grep "API_POST_ENABLED" .env

# 2. What's the BFA Host?
grep "BFA_HOST" .env

# 3. Recent API requests:
tail -n 100 logs/api-requests.log

# 4. Failed API requests:
grep "STATUS=failed" logs/api-requests.log

# 5. Successful API requests:
grep "STATUS=success" logs/api-requests.log

# 6. Retry attempts:
grep "Retry attempt" logs/api-requests.log

# 7. Fallback to file storage:
grep "falling back to file" logs/api-requests.log
```

## 5.4 API Endpoint Requirements

### Your API Must Handle

**HTTP Method:** `POST`

**Headers:**
- `Content-Type: application/json`
- `Authorization: Bearer <token>` (if token configured)

**Request Body:** JSON payload (see [Payload Format](#api-payload-format))

**Expected Response:**

**Success (200-299):**
```json
{
  "status": "success",
  "message": "Logs received and processed",
  "id": "unique-tracking-id",
  "timestamp": "2024-01-01T10:05:00Z"
}
```

**Error (400-599):**
```json
{
  "status": "error",
  "message": "Database connection failed",
  "error_code": "DB_CONNECTION_ERROR"
}
```

### API Endpoint Implementation Example

**Python FastAPI:**
```python
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
import uvicorn

app = FastAPI()

# Define payload models
class FailedStep(BaseModel):
    step_name: str
    error_lines: List[str]

class PipelinePayload(BaseModel):
    repo: str
    branch: str
    commit: str
    job_name: List[str]
    pipeline_id: str
    triggered_by: str
    failed_steps: List[FailedStep]

@app.post('/api/analyze')
async def receive_logs(
    payload: PipelinePayload,
    authorization: Optional[str] = Header(None)
):
    # Verify authentication
    if authorization != 'Bearer your_secret_token':
        raise HTTPException(status_code=401, detail="Unauthorized")

    # Access payload fields
    print(f"Pipeline {payload.pipeline_id} failed in {payload.repo}@{payload.branch} ({payload.commit})")
    print(f"Triggered by: {payload.triggered_by}")
    print(f"Failed steps: {len(payload.failed_steps)}")

    # Log each failed step with errors
    for step in payload.failed_steps:
        print(f"  - {step.step_name}: {len(step.error_lines)} errors")
        for error in step.error_lines[:3]:  # Show first 3 errors
            print(f"    • {error}")

    # Store in database, send notifications, etc.
    # Example: await store_in_database(payload)
    # Example: await send_slack_notification(payload.repo, payload.branch, payload.failed_steps)

    # Return success
    return {
        "status": "success",
        "message": f"Received {len(payload.failed_steps)} failed steps",
        "pipeline_id": payload.pipeline_id,
        "timestamp": datetime.utcnow().isoformat()
    }

if __name__ == '__main__':
    uvicorn.run(app, host='0.0.0.0', port=8000)
```

**Node.js Express:**
```javascript
const express = require('express');
const app = express();

app.use(express.json({ limit: '10mb' }));  // Smaller limit due to simplified format

app.post('/api/analyze', (req, res) => {
    // Verify authentication
    const authHeader = req.headers.authorization;
    if (authHeader !== 'Bearer your_secret_token') {
        return res.status(401).json({ error: 'Unauthorized' });
    }

    // Parse new simplified payload
    const { repo, branch, commit, pipeline_id, triggered_by, failed_steps } = req.body;

    console.log(`Pipeline ${pipeline_id} failed in ${repo}@${branch} (${commit})`);
    console.log(`Triggered by: ${triggered_by}`);
    console.log(`Failed steps: ${failed_steps.length}`);

    // Log each failed step with errors
    failed_steps.forEach(step => {
        console.log(`  - ${step.step_name}: ${step.error_lines.length} errors`);
        step.error_lines.slice(0, 3).forEach(error => {  // Show first 3 errors
            console.log(`    • ${error}`);
        });
    });

    // Process logs (your logic here)
    // Example: storeInDatabase(req.body)
    // Example: sendSlackNotification(repo, branch, failed_steps)

    // Return success
    res.json({
        status: 'success',
        message: `Received ${failed_steps.length} failed steps`,
        pipeline_id: pipeline_id,
        timestamp: new Date().toISOString()
    });
});

app.listen(8000, () => {
    console.log('API listening on port 8000');
});
```

## 5.5 API Testing

### Step 1: Set Up Test API

**Option A: Use httpbin.org (Public Test Service)**
```bash
# In .env:
BFA_HOST=httpbin.org/post
BFA_SECRET_KEY=test_token

# Restart:
./manage_container.py restart
```

**Option B: Run Local Test Server**
```python
# test_api_server.py
from fastapi import FastAPI, Request
from pydantic import BaseModel
from typing import List
import uvicorn

app = FastAPI()

class FailedStep(BaseModel):
    step_name: str
    error_lines: List[str]

class PipelinePayload(BaseModel):
    repo: str
    branch: str
    commit: str
    job_name: List[str]
    pipeline_id: str
    triggered_by: str
    failed_steps: List[FailedStep]

@app.post('/api/analyze')
async def receive_logs(payload: PipelinePayload, request: Request):
    print("="*80)
    print("Received API POST:")
    print(f"Headers: {dict(request.headers)}")
    print(f"\nPayload:")
    print(f"  Repo: {payload.repo}")
    print(f"  Branch: {payload.branch}")
    print(f"  Commit: {payload.commit}")
    print(f"  Pipeline ID: {payload.pipeline_id}")
    print(f"  Triggered by: {payload.triggered_by}")
    print(f"  Failed steps: {len(payload.failed_steps)}")

    for step in payload.failed_steps:
        print(f"\n  Failed step: {step.step_name}")
        print(f"    Errors: {len(step.error_lines)}")
        for error in step.error_lines[:3]:
            print(f"      - {error}")

    print("="*80)
    return {"status": "ok", "results": []}

if __name__ == '__main__':
    uvicorn.run(app, host='0.0.0.0', port=5000, log_level='info')
```

```bash
# Install FastAPI and uvicorn:
pip install fastapi uvicorn

# Run test server:
python test_api_server.py

# In another terminal, configure:
# Update .env with: BFA_HOST=localhost:5000
```

### Step 2: Trigger Test Webhook

```bash
# Send test webhook:
./manage_container.py test

# Or manually:
curl -X POST http://localhost:8000/webhook/gitlab \
  -H "Content-Type: application/json" \
  -d @test_payload.json
```

### Step 3: Verify Results

```bash
# Check API request log:
tail -20 logs/api-requests.log

# Should show:
# - REQUEST to your API
# - RESPONSE 200 OK
# - STATUS=success

# Check test server output:
# Should show received payload details
```

## 5.6 API Troubleshooting

### Issue: API Posting Not Working

**Symptoms:**
- No entries in `logs/api-requests.log`
- Logs only saved to files

**Solutions:**

1. **Check if enabled:**
   ```bash
   grep "API_POST_ENABLED" .env
   # Should be: API_POST_ENABLED=true
   ```

2. **Check BFA Host is set:**
   ```bash
   grep "BFA_HOST" .env
   # Should have valid hostname
   ```

3. **Check startup logs:**
   ```bash
   grep "API posting" logs/application.log
   # Should say "enabled" not "disabled"
   ```

4. **Restart service:**
   ```bash
   ./manage_container.py restart
   ```

### Issue: Getting 401 Unauthorized

**Symptoms:**
- `RESPONSE: 401 Unauthorized` in api-requests.log

**Solutions:**

1. **Check BFA Secret Key is set:**
   ```bash
   grep "BFA_SECRET_KEY" .env
   ```

2. **Verify token is correct:**
   - Compare with your API's expected token

3. **Test manually:**
   ```bash
   curl -X POST http://bfa-server:8000/api/analyze \
     -H "Authorization: Bearer your_token" \
     -d '{"test": true}'
   ```

### Issue: Timeout Errors

**Symptoms:**
- `RESPONSE: timeout` in logs
- `DURATION=30000ms` (or timeout value)

**Solutions:**

1. **Increase timeout:**
   ```bash
   # In .env:
   API_POST_TIMEOUT=60  # Increase to 60 seconds
   ```

2. **Check API performance:**
   - Is your API slow to respond?
   - Processing large payloads?

3. **Check network:**
   - Network latency between services
   - Firewall rules

### Issue: Connection Refused

**Symptoms:**
- `Connection refused` error
- `Failed to establish connection`

**Solutions:**

1. **Check API is running:**
   ```bash
   curl -I http://bfa-server:8000/api/analyze
   ```

2. **Check firewall:**
   - Is port open?
   - Can container reach external network?

3. **Check URL:**
   - Correct protocol (http vs https)?
   - Correct domain/IP?
   - Correct port?

### Issue: Large Payloads Failing

**Symptoms:**
- Works for small pipelines
- Fails for large pipelines (many jobs)
- 413 Payload Too Large

**Solutions:**

1. **Increase API payload limit:**
   - Flask: `app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024`
   - Express: `express.json({ limit: '100mb' })`
   - Nginx: `client_max_body_size 100M;`

2. **Filter jobs to reduce payload:**
   ```bash
   LOG_SAVE_JOB_STATUS=failed  # Only send failed jobs
   ```

### Issue: Logs Not in api-requests.log

**Symptoms:**
- API requests happening but not logged

**Solutions:**

1. **Check log file exists:**
   ```bash
   ls -lh logs/api-requests.log
   ```

2. **Check permissions:**
   ```bash
   ls -la logs/
   # Should be writable by container user (1000)
   ```

3. **Check log rotation:**
   - May have rotated to api-requests.log.1
   ```bash
   ls -lh logs/api-requests.log*
   ```

---

# 6. Operations & Monitoring

## 6.1 Testing

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
curl -X POST http://localhost:8000/webhook/gitlab \
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
./manage_container.py remove --force
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

### Create Test Webhook Payload

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

### Test Webhook

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

#### Method 1: Docker Logs (Console Output)

View logs in real-time from Docker console:

```bash
# Follow live logs
./manage_container.py logs

# Or directly with Docker
docker logs -f bfa-gitlab-pipeline-extractor

# Last 100 lines
docker logs --tail 100 bfa-gitlab-pipeline-extractor

# Monitor 100 lines
docker logs -f --tail 100 bfa-gitlab-pipeline-extractor

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
# View logs inside container using docker exec
docker exec bfa-gitlab-pipeline-extractor tail -f /app/logs/application.log
docker exec bfa-gitlab-pipeline-extractor grep ERROR /app/logs/application.log
docker exec bfa-gitlab-pipeline-extractor tail -f /app/logs/api-requests.log
```

#### Method 4: Watch Mode (Auto-refresh)

```bash
# Refresh every 2 seconds
watch -n 2 'tail -20 ./logs/application.log'

# Monitor multiple logs
watch -n 5 'echo "=== APPLICATION ===" && tail -10 ./logs/application.log && echo && echo "=== API REQUESTS ===" && tail -10 ./logs/api-requests.log'
```

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

# Performance issues (> 10 seconds) - check duration_ms in logs
grep "duration_ms" logs/application.log | awk -F'|' '$6 ~ /[0-9]{5,}/ {print}'

# Extract all pipeline IDs
grep -oP 'pipeline_id=\K[0-9]+' logs/application.log | sort -u

# Top 10 most logged pipelines
grep -oP 'pipeline_id=\K[0-9]+' logs/application.log | sort | uniq -c | sort -rn | head -10
```

#### Search with awk (for pipe-delimited logs)

```bash
# Extract specific fields
awk -F'|' '{print $1, $2, $5}' logs/application.log | tail -20

# Filter by level
awk -F'|' '$2 ~ /ERROR/ {print}' logs/application.log

# Count by level
awk -F'|' '{gsub(/^[ \t]+|[ \t]+$/, "", $2); print $2}' logs/application.log | sort | uniq -c
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
docker exec bfa-gitlab-pipeline-extractor ls -la /app/logs
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

### Real-World Examples

#### Example 1: Check Today's Activity

```bash
# View dashboard
python scripts/monitor_dashboard.py --hours 24

# Export to CSV
python scripts/monitor_dashboard.py --export today.csv --hours 24

# Check via API
curl http://localhost:8000/monitor/summary?hours=24 | jq
```

#### Example 2: Troubleshoot Failed Pipeline

```bash
# Find pipeline in recent requests
python scripts/monitor_dashboard.py --recent 100 | grep failed

# Get details for specific pipeline
python scripts/monitor_dashboard.py --pipeline 12345

# Or via API
curl http://localhost:8000/monitor/pipeline/12345 | jq
```

#### Example 3: Track Performance Over Time

```bash
# Export last week
python scripts/monitor_dashboard.py --export week.csv --hours 168

# Open in Excel and create charts for:
# - Requests per day
# - Success rate trend
# - Average processing time
# - Jobs processed per day
```

#### Example 4: Monitor Active Processing

```bash
# Check current processing
sqlite3 logs/monitoring.db "
SELECT pipeline_id, status, timestamp
FROM requests
WHERE status = 'processing'
ORDER BY timestamp DESC;
"
```

#### Example 5: Generate Weekly Report

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
python scripts/monitor_dashboard.py --export weekly_data.csv --hours 168
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
# Verify token is valid
curl --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
  "https://gitlab.com/api/v4/user"

# Check token has 'api' scope in GitLab settings
```

### Issue 5: Logs Not Being Saved

```bash
# Check directory exists and permissions
ls -la logs/
chmod 755 logs/

# Verify LOG_OUTPUT_DIR in .env
cat .env | grep LOG_OUTPUT_DIR

# Check server logs for errors
tail -f logs/application.log
```

### Issue 6: Database/Connection Errors

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

# 7. Database Maintenance

## Quick Start

For common database operations, use the **`manage_database.sh` script** which simplifies most tasks:

```bash
# Database Operations
./scripts/manage_database.sh backup daily       # Create backup
./scripts/manage_database.sh restore <file>     # Restore from backup
./scripts/manage_database.sh check              # Health check
./scripts/manage_database.sh list               # List backups
```

## Debug Commands

Useful commands for debugging SQLite database issues:

```bash
# Check database file size
du -h logs/monitoring.db*

# Check database integrity
sqlite3 logs/monitoring.db "PRAGMA integrity_check;"

# Check database version
sqlite3 logs/monitoring.db "SELECT sqlite_version();"

# Check WAL mode status
sqlite3 logs/monitoring.db "PRAGMA journal_mode;"

# Check database configuration
sqlite3 logs/monitoring.db "PRAGMA compile_options;"

# View database schema
sqlite3 logs/monitoring.db ".schema"

# Count total records
sqlite3 logs/monitoring.db "SELECT COUNT(*) FROM requests;"

# Check recent activity
sqlite3 logs/monitoring.db "SELECT COUNT(*) FROM requests WHERE timestamp > datetime('now', '-1 hour');"
```

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

## 7.4 Database Troubleshooting

### Issue: Database is Locked

**Symptoms:**
```
database is locked
```

**Causes:**
- Long-running queries
- Multiple processes accessing the database
- Stale WAL file

**Solutions:**

```bash
# Check for long-running processes
lsof logs/monitoring.db

# Force checkpoint WAL
sqlite3 logs/monitoring.db "PRAGMA wal_checkpoint(TRUNCATE);"

# Check if service is still running
./manage_container.py status

# If necessary, restart service
./manage_container.py restart
```

### Issue: Database Corruption

**Symptoms:**
```
database disk image is malformed
integrity_check fails
```

**Causes:**
- Disk I/O errors
- Power failure during write
- File system corruption

**Solutions:**

**Step 1: Try recovery**
```bash
# Attempt SQLite recovery
sqlite3 logs/monitoring.db ".recover" | sqlite3 recovered.db

# If recovery works:
./manage_container.py stop
mv logs/monitoring.db logs/monitoring.db.corrupt
mv recovered.db logs/monitoring.db
./manage_container.py start
```

**Step 2: Restore from backup**
```bash
# If recovery fails, restore from backup
./manage_container.py stop
cp logs/monitoring.db.backup_YYYYMMDD logs/monitoring.db

# Remove WAL files
rm logs/monitoring.db-wal
rm logs/monitoring.db-shm

# Restart service
./manage_container.py start
```

**Prevention:**
- Regular backups (automated via cron)
- Integrity checks (weekly)
- Monitor disk health
- Use reliable storage (avoid NFS for SQLite)

### Issue: Slow Queries

**Symptoms:**
- Monitoring dashboard slow to load
- API endpoints timeout
- High CPU usage

**Causes:**
- Large database file
- Missing indexes (not applicable in simple schema)
- Fragmentation
- Too many old records

**Solutions:**

**Step 1: Check database size**
```bash
# Check file size
du -h logs/monitoring.db

# Count records
sqlite3 logs/monitoring.db "SELECT COUNT(*) FROM requests;"
```

**Step 2: Run VACUUM to optimize**
```bash
sqlite3 logs/monitoring.db "VACUUM;"

# This can take several minutes for large databases
# Expected size reduction: 20-50%
```

**Step 3: Rebuild indexes**
```bash
sqlite3 logs/monitoring.db "REINDEX;"
```

**Step 4: Archive old data**
```bash
# Archive data older than 90 days
sqlite3 -header -csv logs/monitoring.db "
SELECT * FROM requests
WHERE timestamp < datetime('now', '-90 days')
" > archive_$(date +%Y%m%d).csv

# Delete old records
sqlite3 logs/monitoring.db "
DELETE FROM requests WHERE timestamp < datetime('now', '-90 days');
VACUUM;
"
```

**Step 5: Check query performance**
```bash
# Enable query timer
sqlite3 logs/monitoring.db
.timer ON
.stats ON

# Run slow query to identify bottleneck
SELECT status, COUNT(*) FROM requests GROUP BY status;
```

**Prevention:**
- Regular VACUUM (weekly)
- Archive old data (monthly)
- Monitor database size
- Set up automated cleanup

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
