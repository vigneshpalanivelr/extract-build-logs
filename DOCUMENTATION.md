# GitLab & Jenkins Pipeline Log Extraction System - Complete Documentation

> **Comprehensive guide for setup, configuration, operations, and maintenance**

**Last Updated:** 2025-12-30
**Version:** 3.0

---

## Table of Contents

### 1. System Overview
- [1.1 Features & Capabilities](#11-features--capabilities)
- [1.2 Architecture & Components](#12-architecture--components)
- [1.3 Module Documentation](#13-module-documentation)
- [1.4 Project Structure](#14-project-structure)
- [1.5 Data Flow & Processing](#15-data-flow--processing)

### 2. Quick Start
- [2.1 Quick Deployment (Docker)](#21-quick-deployment-docker)
- [2.2 Manual Installation](#22-manual-installation)
- [2.3 First Steps & Verification](#23-first-steps--verification)

### 3. Configuration
- [3.1 Environment Variables Reference](#31-environment-variables-reference)
- [3.2 GitLab Webhook Setup](#32-gitlab-webhook-setup)
- [3.3 Jenkins Integration](#33-jenkins-integration)
- [3.4 API Posting Setup](#34-api-posting-setup)
- [3.5 Log Filtering Configuration](#35-log-filtering-configuration)
- [3.6 Configuration Examples & Scenarios](#36-configuration-examples--scenarios)

### 4. Usage & Operations
- [4.1 Running the Application](#41-running-the-application)
- [4.2 Docker Operations](#42-docker-operations)
- [4.3 Application Logging](#43-application-logging)
- [4.4 Monitoring & Tracking](#44-monitoring--tracking)
- [4.5 Usage Examples](#45-usage-examples)
- [4.6 API Endpoints Reference](#46-api-endpoints-reference)

### 5. Advanced Topics
- [5.1 Production Deployment](#51-production-deployment)
- [5.2 Testing & CI/CD Pipeline](#52-testing--cicd-pipeline)
- [5.3 Database Maintenance](#53-database-maintenance)
- [5.4 Troubleshooting & Common Issues](#54-troubleshooting--common-issues)

### 6. Reference
- [6.1 Development & Contributing](#61-development--contributing)
- [6.2 Security Considerations](#62-security-considerations)
- [6.3 FAQ](#63-faq)
- [6.4 API Design History](#64-api-design-history)

---

# 1. System Overview

## 1.1 Features & Capabilities

### Multi-Source Support
- **GitLab Integration**: Full webhook integration for pipeline events
- **Jenkins Integration**: Build log extraction with parallel stage parsing
- Automatic log extraction from all jobs/stages
- Support for multiple pipeline types (main, child, merge request)

### Advanced Logging System
- **Aligned log columns** for easy reading
- **Project names** in logs instead of just IDs
- **Request ID tracking** to trace pipeline processing across all entries
- **Pipe-delimited format** for easy parsing
- **Consolidated logging**: Single application.log file
- **Configurable log levels** (DEBUG, INFO, WARNING, ERROR, CRITICAL)
- **Automatic log rotation** with size limits
- **Sensitive data masking** using `[REDACTED***]` format

**Example Startup Logs:**
```
2025-12-30 10:15:00.123 | INFO  | src.webhook_listener    | N/A      | ======================================================================
2025-12-30 10:15:00.124 | INFO  | src.webhook_listener    | N/A      | GitLab Pipeline Log Extractor - Initializing
2025-12-30 10:15:00.125 | INFO  | src.webhook_listener    | N/A      | ======================================================================
2025-12-30 10:15:00.126 | INFO  | src.webhook_listener    | N/A      | Configuration .env loaded successfully | operation=config_load
2025-12-30 10:15:00.127 | INFO  | src.webhook_listener    | N/A      | GitLab URL: https://gitlab.example.com
2025-12-30 10:15:00.128 | INFO  | src.webhook_listener    | N/A      | Webhook receiver Port: 8000
2025-12-30 10:15:00.129 | DEBUG | src.webhook_listener    | N/A      | GitLab Token: glpa...[REDACTED***]vf1
2025-12-30 10:15:00.130 | INFO  | src.webhook_listener    | N/A      | Initializing 7 components...
2025-12-30 10:15:00.131 | DEBUG | src.webhook_listener    | N/A      | 1. Pipeline extractor initialized
2025-12-30 10:15:00.132 | DEBUG | src.webhook_listener    | N/A      | 2. Log fetcher initialized
2025-12-30 10:15:00.133 | DEBUG | src.webhook_listener    | N/A      | 3. Storage manager initialized
2025-12-30 10:15:00.134 | DEBUG | src.monitoring          | N/A      | 4. SQLite database initialized with WAL mode: logs/monitoring.db
2025-12-30 10:15:00.135 | INFO  | src.webhook_listener    | N/A      | 6. API Poster endpoint: http://api.example.com:8000/api/analyze
2025-12-30 10:15:00.136 | INFO  | src.api_poster          | N/A      | 6. API Poster log file: logs/api-requests.log
2025-12-30 10:15:00.137 | DEBUG | src.api_poster          | N/A      | 6. API Poster initialized
2025-12-30 10:15:00.138 | INFO  | src.webhook_listener    | N/A      | 7. Jenkins integration: DISABLED
2025-12-30 10:15:00.139 | INFO  | src.webhook_listener    | N/A      | All components initialized successfully
```

### Flexible Log Filtering
Configure which logs to save based on:
- **Pipeline status** (all, failed, success, running, canceled, skipped)
- **Project whitelist/blacklist** (save specific projects or exclude noisy ones)
- **Job status** (all, failed, success, canceled, skipped)
- **Metadata-only mode** for tracking without storing logs

**Example: Pipeline Processing with Filtering**
```
2025-12-30 10:20:15.456 | INFO  | src.webhook_listener    | a1b2c3d4 | Request ID a1b2c3d4 tracking pipeline 1061175 from project 'my-app' (ID: 123)
2025-12-30 10:20:15.457 | INFO  | src.pipeline_extractor  | a1b2c3d4 | Extracted info for pipeline 1061175 from project 'my-app' (type: main, status: failed)
2025-12-30 10:20:15.458 | INFO  | src.webhook_listener    | a1b2c3d4 | Pipeline queued for processing | pipeline_id=1061175 project_id=123
2025-12-30 10:20:15.500 | INFO  | src.webhook_listener    | a1b2c3d4 | Starting pipeline log extraction for 'my-app' | pipeline_id=1061175
2025-12-30 10:20:16.234 | INFO  | src.webhook_listener    | a1b2c3d4 | Job filtering: 5 jobs to fetch, 2 jobs skipped by filter | pipeline_id=1061175
```

### API Posting
Send extracted logs to external API endpoints:
- **Configurable modes**: API only, dual (API + file), or file only
- **Bearer token authentication** with JWT support
- **Retry logic** with exponential backoff
- **Request/response logging** to `logs/api-requests.log`
- **Fallback to file storage** if API fails

**Example: API Posting Flow**
```
2025-12-30 10:20:18.789 | INFO  | src.api_poster          | a1b2c3d4 | Posting pipeline logs to API for 'my-app' (pipeline 1061175) | job_count=5
2025-12-30 10:20:19.234 | INFO  | src.api_poster          | a1b2c3d4 | Formatted API payload for pipeline 1061175 | payload_size_bytes=45678
2025-12-30 10:20:20.567 | INFO  | src.api_poster          | a1b2c3d4 | Successfully posted pipeline 1061175 logs to API | duration_ms=1250
```

### Error Handling & Reliability
- **Automatic retry** with exponential backoff
- **Circuit breaker pattern** for cascade failure prevention
- **Comprehensive error logging**
- **Request correlation** via unique request IDs

**Example: Retry Logic in Action**
```
2025-12-30 10:25:30.123 | ERROR | src.log_fetcher         | b2c3d4e5 | Failed to fetch log for job 789: Connection timeout
2025-12-30 10:25:30.124 | INFO  | src.error_handler       | b2c3d4e5 | Retrying operation (attempt 1/3) with 2.0s backoff
2025-12-30 10:25:32.456 | INFO  | src.log_fetcher         | b2c3d4e5 | Retry attempt 1: Fetching log for job 789
2025-12-30 10:25:34.789 | INFO  | src.log_fetcher         | b2c3d4e5 | Successfully fetched log for job 789 | size_bytes=12345 | retry_succeeded=true
```

### Structured Storage
- **Organized by project** name and ID
- **Directory structure**: `{project-name}_{id}/pipeline_{id}/`
- **Metadata files** with complete pipeline/job information
- **Individual log files** per job

**Example Directory Structure:**
```
logs/
├── my-app_123/
│   ├── pipeline_1061175/
│   │   ├── metadata.json
│   │   ├── job_456_build.log
│   │   ├── job_457_test_unit.log
│   │   └── job_459_deploy.log
│   └── pipeline_1061180/
│       ├── metadata.json
│       └── job_460_build.log
├── application.log          # All application logs
├── api-requests.log         # API posting logs
└── monitoring.db            # SQLite tracking database
```

### Modern Async Architecture
- **FastAPI-based async server** with automatic API documentation
- **Interactive API Docs**: Swagger UI at `/docs`, ReDoc at `/redoc`
- **Background processing**: Non-blocking webhook responses
- **Health monitoring**: Health check and statistics endpoints
- **High performance**: Async/await for better concurrency

### Production Ready
- **Docker containerization** with optimized images
- **Comprehensive monitoring** with SQLite tracking database
- **Security**: Webhook secret validation, sensitive data masking
- **Automated testing**: Unit tests with CI/CD integration
- **Log rotation**: Automatic with configurable size limits

## 1.2 Architecture & Components

*For complete architecture diagrams, see [README.md - Architecture Section](README.md#architecture)*

The system consists of several key components working together:

### Core Components

1. **Webhook Listener** (`webhook_listener.py`)
   - FastAPI async web server
   - Receives webhook events from GitLab/Jenkins
   - Validates webhook secrets
   - Queues background processing

2. **Pipeline Extractor** (`pipeline_extractor.py`)
   - Parses webhook payloads
   - Identifies pipeline types (main/child/MR)
   - Filters jobs based on configuration

3. **Log Fetcher** (`log_fetcher.py`)
   - Communicates with GitLab/Jenkins API
   - Fetches job logs with retry logic
   - Handles authentication

4. **Storage Manager** (`storage_manager.py`)
   - Creates directory structures
   - Saves log files and metadata
   - Manages file organization

5. **API Poster** (`api_poster.py`)
   - Posts logs to external API endpoints
   - Handles authentication and retries
   - Logs all API requests/responses

6. **Monitoring** (`monitoring.py`)
   - SQLite database for tracking
   - Records all webhook requests
   - Provides statistics and reporting

7. **Error Handler** (`error_handler.py`)
   - Implements retry logic with exponential backoff
   - Circuit breaker pattern
   - Comprehensive error tracking

## 1.3 Module Documentation

### Module Connection Diagram

```
webhook_listener.py (Main Entry Point)
    ↓
    ├── config_loader.py (Configuration)
    ├── pipeline_extractor.py (Parse Events)
    ├── log_fetcher.py (Fetch Logs)
    │   ├── error_handler.py (Retry Logic)
    │   └── config_loader.py
    ├── storage_manager.py (Save Files)
    ├── api_poster.py (Post to API)
    │   └── token_manager.py (JWT Auth)
    └── monitoring.py (Track Requests)
```

### Core Application Files

| File | Purpose | Key Responsibilities |
|------|---------|---------------------|
| `webhook_listener.py` | Main server | FastAPI server, webhook handling, background processing |
| `pipeline_extractor.py` | Event parsing | Parse payloads, identify types, filter jobs |
| `log_fetcher.py` | API client | Fetch logs from GitLab/Jenkins, handle authentication |
| `storage_manager.py` | File storage | Create directories, save logs, manage metadata |
| `api_poster.py` | API integration | POST logs to external APIs, handle retries |
| `monitoring.py` | Tracking | SQLite database, statistics, reporting |
| `error_handler.py` | Error handling | Retry logic, circuit breaker, error tracking |
| `config_loader.py` | Configuration | Load environment variables, validate settings |
| `logging_config.py` | Logging | Configure logging, format output, mask secrets |
| `token_manager.py` | Authentication | JWT token generation and management |

## 1.4 Project Structure

```
extract-build-logs/
│
├── src/                          # Main application code
│   ├── webhook_listener.py      # FastAPI server and main entry point
│   ├── pipeline_extractor.py    # Pipeline event parsing
│   ├── log_fetcher.py            # GitLab/Jenkins API client
│   ├── storage_manager.py        # File system storage
│   ├── api_poster.py             # API posting functionality
│   ├── monitoring.py             # SQLite tracking database
│   ├── config_loader.py          # Configuration management
│   ├── error_handler.py          # Retry logic
│   ├── logging_config.py         # Logging configuration
│   └── token_manager.py          # JWT token management
│
├── tests/                        # Test suite
│   ├── test_pipeline_extractor.py
│   ├── test_storage_manager.py
│   ├── test_error_handler.py
│   ├── test_api_poster.py
│   └── test_webhook_listener.py
│
├── scripts/                      # Utility scripts
│   ├── manage_database.sh        # Database management
│   └── monitor_dashboard.py      # Monitoring dashboard
│
├── logs/                         # Output directory (created automatically)
│   ├── {project-name}_{id}/      # Organized by project
│   │   └── pipeline_{id}/        # Then by pipeline
│   │       ├── metadata.json     # Pipeline metadata
│   │       └── job_{id}_{name}.log  # Job logs
│   ├── application.log           # Application logs
│   ├── api-requests.log          # API request logs
│   └── monitoring.db             # SQLite tracking database
│
├── .env                          # Environment configuration
├── .env.example                  # Configuration template
├── requirements.txt              # Python dependencies
├── Dockerfile                    # Docker image definition
├── log-extractor-entrypoint.sh   # Container entrypoint script
├── manage_container.py           # Container management tool
├── README.md                     # Quick start guide
└── DOCUMENTATION.md              # This file
```

## 1.5 Data Flow & Processing

### Complete Event Processing Flow

1. **Webhook Received**
   - GitLab/Jenkins sends POST request to `/webhook/gitlab` or `/webhook/jenkins`
   - Webhook listener validates secret token
   - Request assigned unique request ID for tracking

2. **Event Parsing**
   - Pipeline extractor identifies pipeline type (main/child/MR)
   - Extracts pipeline metadata (ID, project, status, jobs)
   - Applies filtering based on configuration

3. **Background Processing**
   - Non-blocking response returned to GitLab/Jenkins (200 OK)
   - Background task queued for log extraction
   - All logs tagged with request ID for correlation

4. **Log Fetching**
   - For each job in pipeline:
     - Fetch log content via API
     - Retry on failures with exponential backoff
     - Track fetch status and errors

5. **Storage/API Posting**
   - **File Mode**: Save logs to filesystem with metadata
   - **API Mode**: POST logs to external API endpoint
   - **Dual Mode**: Both file and API saving
   - Fallback to file storage if API fails

6. **Monitoring**
   - Record request in SQLite database
   - Track processing status and duration
   - Log errors and failures

**Example: Complete Processing Flow Logs**
```
# 1. Webhook received
2025-12-30 10:20:15.456 | INFO  | src.webhook_listener    | a1b2c3d4 | Webhook received | event=Pipeline Hook

# 2. Event parsed
2025-12-30 10:20:15.457 | INFO  | src.pipeline_extractor  | a1b2c3d4 | Extracted info for pipeline 1061175 | project=my-app type=main status=failed jobs=7

# 3. Queued for processing
2025-12-30 10:20:15.458 | INFO  | src.webhook_listener    | a1b2c3d4 | Pipeline queued for processing | pipeline_id=1061175

# 4. Background processing starts
2025-12-30 10:20:15.500 | INFO  | src.webhook_listener    | a1b2c3d4 | Starting pipeline log extraction | pipeline_id=1061175

# 5. Fetching logs
2025-12-30 10:20:16.234 | INFO  | src.log_fetcher         | a1b2c3d4 | Fetching logs for 7 jobs
2025-12-30 10:20:17.123 | INFO  | src.log_fetcher         | a1b2c3d4 | Fetched log for job 456 (build) | size_bytes=12345
2025-12-30 10:20:18.456 | INFO  | src.log_fetcher         | a1b2c3d4 | Fetched log for job 457 (test) | size_bytes=23456

# 6. Storing/posting
2025-12-30 10:20:19.789 | INFO  | src.api_poster          | a1b2c3d4 | Posting logs to API | job_count=7
2025-12-30 10:20:20.567 | INFO  | src.api_poster          | a1b2c3d4 | Successfully posted to API | duration_ms=778

# 7. Complete
2025-12-30 10:20:20.568 | INFO  | src.webhook_listener    | a1b2c3d4 | Pipeline processing complete | duration_s=5.1 jobs_processed=7
```

---

# 2. Quick Start

## 2.1 Quick Deployment (Docker)

### The Problem

When shipping a Docker image from one server to another:
- Docker image contains: Application code, dependencies
- NOT included: `.env` file, `logs/` directory

This can cause permission errors on the new server.

### Solution (3 Steps)

#### Step 1: Create .env File
```bash
cd /home/user/extract-build-logs/
cp .env.example .env
nano .env  # Add your GITLAB_URL and GITLAB_TOKEN
```

#### Step 2: Create Logs Directory
```bash
mkdir -p logs
chmod 755 logs
```

#### Step 3: Start Container
```bash
./manage_container.py start
```

**Your webhook is now available at:** `http://your-server:8000/webhook/gitlab`

### Verification

```bash
# Check container status
./manage_container.py status

# Check health endpoint
curl http://localhost:8000/health
# Expected: {"status":"healthy","service":"gitlab-log-extractor","version":"1.0.0"}

# View logs
./manage_container.py logs
```

**Example: Successful Startup**
```
Container: bfa-gitlab-pipeline-extractor
Status: running (healthy)
Uptime: 2 minutes
Memory: 245 MB / 2 GB
CPU: 0.5%
Port Mapping: 0.0.0.0:8000 -> 8000/tcp

Recent Logs:
2025-12-30 10:15:00.139 | INFO  | src.webhook_listener    | N/A      | All components initialized successfully
2025-12-30 10:15:00.140 | INFO  | uvicorn.server          | N/A      | Started server process
2025-12-30 10:15:00.141 | INFO  | uvicorn.server          | N/A      | Waiting for application startup
2025-12-30 10:15:00.142 | INFO  | uvicorn.server          | N/A      | Application startup complete
2025-12-30 10:15:00.143 | INFO  | uvicorn.server          | N/A      | Uvicorn running on http://0.0.0.0:8000
```

## 2.2 Manual Installation

### Prerequisites

- Python 3.8 or higher
- GitLab instance (GitLab.com or self-hosted)
- GitLab Personal Access Token with `api` scope
- Network connectivity to GitLab API

### Installation Steps

**1. Clone Repository**
```bash
git clone <repository-url>
cd extract-build-logs
```

**2. Create Virtual Environment**
```bash
python3 -m venv venv

# On Linux/Mac:
source venv/bin/activate

# On Windows:
venv\Scripts\activate
```

**3. Install Dependencies**
```bash
pip install -r requirements.txt
```

**4. Configure Environment**
```bash
cp .env.example .env
nano .env  # Edit with your settings
```

**Minimum Required Configuration:**
```bash
GITLAB_URL=https://gitlab.com
GITLAB_TOKEN=your_gitlab_token_here
WEBHOOK_PORT=8000
```

**5. Start the Server**
```bash
python src/webhook_listener.py
```

## 2.3 First Steps & Verification

### Verify Installation

**1. Check Server Health**
```bash
curl http://localhost:8000/health
```

**Expected Response:**
```json
{
  "status": "healthy",
  "service": "gitlab-log-extractor",
  "version": "1.0.0"
}
```

**2. Access API Documentation**
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

**3. Check Application Logs**
```bash
tail -f logs/application.log
```

**4. Verify Directory Structure**
```bash
ls -la logs/
# Should show: application.log, monitoring.db
```

### Next Steps

1. **Configure GitLab Webhook** → See [Section 3.2](#32-gitlab-webhook-setup)
2. **Configure Log Filtering** (optional) → See [Section 3.5](#35-log-filtering-configuration)
3. **Enable API Posting** (optional) → See [Section 3.4](#34-api-posting-setup)
4. **Set up Monitoring** → See [Section 4.4](#44-monitoring--tracking)

---

# 3. Configuration

## 3.1 Environment Variables Reference

All configuration is done through environment variables in the `.env` file.

### Required Settings

```bash
# GitLab Configuration (REQUIRED)
GITLAB_URL=https://gitlab.com
GITLAB_TOKEN=your_gitlab_token_here
```

### Optional Settings

#### Server Configuration
```bash
WEBHOOK_PORT=8000                    # Server port (default: 8000)
WEBHOOK_SECRET=your_webhook_secret   # Webhook validation secret
LOG_OUTPUT_DIR=./logs                # Log storage directory
LOG_LEVEL=INFO                       # Logging level (DEBUG, INFO, WARNING, ERROR)
RETRY_ATTEMPTS=3                     # API retry attempts
RETRY_DELAY=2                        # Retry delay in seconds
```

#### Log Filtering
```bash
# Pipeline status filter
LOG_SAVE_PIPELINE_STATUS=all         # Options: all, failed, success, running, canceled, skipped

# Project filtering
LOG_SAVE_PROJECTS=                   # Comma-separated project IDs to include (empty = all)
LOG_EXCLUDE_PROJECTS=                # Comma-separated project IDs to exclude

# Job status filter
LOG_SAVE_JOB_STATUS=all              # Options: all, failed, success, canceled, skipped

# Metadata-only mode
LOG_SAVE_METADATA_ALWAYS=true        # Save metadata even if logs are filtered
```

#### API Posting Configuration
```bash
# BFA Configuration (required for API posting)
BFA_HOST=bfa-server.example.com      # BFA server hostname
BFA_SECRET_KEY=your_bfa_secret_key   # Secret key for JWT token generation

# API Posting
API_POST_ENABLED=false               # Enable API posting
API_POST_TIMEOUT=30                  # Request timeout in seconds
API_POST_RETRY_ENABLED=true          # Enable retry logic
API_POST_SAVE_TO_FILE=false          # Dual mode: save to both API and files
```

#### Jenkins Integration
```bash
JENKINS_ENABLED=false                         # Enable Jenkins integration
JENKINS_URL=https://jenkins.example.com       # Jenkins server URL
JENKINS_USER=your_username                    # Jenkins username
JENKINS_API_TOKEN=your_jenkins_token          # Jenkins API token
JENKINS_WEBHOOK_SECRET=your_webhook_secret    # Jenkins webhook secret
```

### Configuration Validation

The system validates configuration on startup:

```
2025-12-30 10:15:00.126 | INFO  | src.webhook_listener    | N/A      | Configuration .env loaded successfully
2025-12-30 10:15:00.127 | INFO  | src.webhook_listener    | N/A      | GitLab URL: https://gitlab.example.com
2025-12-30 10:15:00.128 | INFO  | src.webhook_listener    | N/A      | Webhook receiver Port: 8000
```

**Validation Errors:**
```
ERROR: Invalid GITLAB_URL format (must start with http:// or https://)
ERROR: GITLAB_TOKEN too short (minimum 10 characters)
ERROR: Invalid WEBHOOK_PORT: 99999 (must be 1-65535)
ERROR: BFA_HOST required when API_POST_ENABLED is true
```

## 3.2 GitLab Webhook Setup

### Prerequisites

- GitLab project with admin/maintainer access
- Running webhook server (see [Quick Start](#2-quick-start))
- Webhook secret token (optional but recommended)

### Setup Steps

**1. Navigate to Webhook Settings**
- Go to your GitLab project
- Settings → Webhooks

**2. Add Webhook URL**
```
http://your-server:8000/webhook/gitlab
```

**3. Configure Secret Token**
- Generate a secure secret: `openssl rand -hex 32`
- Add to GitLab webhook configuration
- Add same secret to `.env`: `WEBHOOK_SECRET=your_secret_here`

**4. Select Trigger Events**
- Enable **Pipeline events** only
- Disable all other events

**5. Configure Options**
- ✓ Enable SSL verification (if using HTTPS)
- ✓ Push events (optional, for testing)

**6. Add Webhook**
- Click "Add webhook"

**7. Test the Webhook**
- Click "Test" → "Pipeline events"
- Check server logs for confirmation

**Example: Successful Webhook Test**
```
2025-12-30 10:30:15.123 | INFO  | src.webhook_listener    | c4d5e6f7 | Webhook received | event=Pipeline Hook
2025-12-30 10:30:15.124 | INFO  | src.pipeline_extractor  | c4d5e6f7 | Extracted info for pipeline 123456 | project=test-project type=main
2025-12-30 10:30:15.125 | INFO  | src.webhook_listener    | c4d5e6f7 | Pipeline queued for processing | pipeline_id=123456
```

### Webhook Payload Example

GitLab sends a JSON payload like this:
```json
{
  "object_kind": "pipeline",
  "object_attributes": {
    "id": 123456,
    "status": "success",
    "ref": "main",
    "sha": "abc123..."
  },
  "project": {
    "id": 789,
    "name": "my-project",
    "web_url": "https://gitlab.com/myorg/my-project"
  },
  "builds": [...]
}
```

### Troubleshooting

**Issue: 401 Unauthorized**
- Check `WEBHOOK_SECRET` matches GitLab webhook configuration
- Check for extra spaces or newlines in secret

**Issue: Webhook not triggering**
- Verify webhook URL is accessible from GitLab server
- Check firewall/network settings
- Test with `curl` from GitLab server

**Issue: 500 Internal Server Error**
- Check server logs: `tail -f logs/application.log`
- Verify all required environment variables are set
- Check GitLab token has correct permissions

## 3.3 Jenkins Integration

### Overview

Jenkins integration allows extracting build logs including parallel execution blocks.

### Configuration

Add to `.env`:
```bash
JENKINS_ENABLED=true
JENKINS_URL=https://jenkins.example.com
JENKINS_USER=your_username
JENKINS_API_TOKEN=your_api_token
JENKINS_WEBHOOK_SECRET=your_webhook_secret
```

### Obtaining Jenkins API Token

1. Log in to Jenkins
2. Click your name → Configure
3. API Token → Add new Token
4. Copy token and add to `.env`

### Jenkins Webhook Setup

**1. Install Generic Webhook Trigger Plugin**
- Manage Jenkins → Manage Plugins
- Install "Generic Webhook Trigger Plugin"

**2. Configure Job Webhook**
- Job → Configure → Build Triggers
- Enable "Generic Webhook Trigger"
- Add POST content parameters
- Set token: same as `JENKINS_WEBHOOK_SECRET`

**3. Webhook URL**
```
http://your-server:8000/webhook/jenkins
```

### Jenkinsfile Integration

Add to your Jenkinsfile:
```groovy
pipeline {
    agent any

    post {
        always {
            script {
                // Extract build logs and send to webhook server
                def buildUrl = env.BUILD_URL
                def jobName = env.JOB_NAME
                def buildNumber = env.BUILD_NUMBER

                // Webhook server will fetch logs via Jenkins API
                sh """
                curl -X POST http://your-server:8000/webhook/jenkins \
                    -H "Content-Type: application/json" \
                    -H "X-Jenkins-Token: ${JENKINS_WEBHOOK_SECRET}" \
                    -d '{"job_name":"${jobName}","build_number":${buildNumber},"build_url":"${buildUrl}"}'
                """
            }
        }
    }
}
```

### Example: Jenkins Logs with Parallel Stages

```
2025-12-30 10:35:15.456 | INFO  | src.webhook_listener    | d5e6f7g8 | Jenkins webhook received | job=my-pipeline build=42
2025-12-30 10:35:16.123 | INFO  | src.jenkins_extractor   | d5e6f7g8 | Extracted Jenkins build info | stages=5 parallel_blocks=2
2025-12-30 10:35:16.234 | INFO  | src.jenkins_log_fetcher | d5e6f7g8 | Fetching logs for parallel stage: test-unit
2025-12-30 10:35:16.345 | INFO  | src.jenkins_log_fetcher | d5e6f7g8 | Fetching logs for parallel stage: test-integration
2025-12-30 10:35:17.456 | INFO  | src.storage_manager     | d5e6f7g8 | Saved Jenkins logs | job=my-pipeline build=42 files=5
```

## 3.4 API Posting Setup

### Overview

API posting sends extracted logs to an external API endpoint instead of (or in addition to) saving them to files.

### Configuration

Add to `.env`:
```bash
# BFA Configuration (required)
BFA_HOST=bfa-server.example.com
BFA_SECRET_KEY=your_bfa_secret_key

# Enable API posting
API_POST_ENABLED=true
API_POST_TIMEOUT=30
API_POST_RETRY_ENABLED=true
API_POST_SAVE_TO_FILE=false  # false = API only, true = dual mode
```

### Operating Modes

**1. API Only Mode** (default when `API_POST_ENABLED=true`)
```bash
API_POST_ENABLED=true
API_POST_SAVE_TO_FILE=false
```
- Logs are POSTed to API only
- Falls back to file storage if API fails
- Reduces storage requirements

**2. Dual Mode** (API + File)
```bash
API_POST_ENABLED=true
API_POST_SAVE_TO_FILE=true
```
- Logs saved to both API and files
- Maximum reliability
- Higher storage requirements

**3. File Only Mode** (traditional)
```bash
API_POST_ENABLED=false
```
- Logs saved to files only
- No API integration

### API Endpoint

The API endpoint is automatically constructed as:
```
http://${BFA_HOST}:8000/api/analyze
```

### Authentication

Uses Bearer token authentication with JWT:
- If `BFA_SECRET_KEY` is set: Generates JWT tokens locally
- If `BFA_HOST` is set (no secret): Fetches tokens from BFA server
- Token included in `Authorization: Bearer <token>` header

### API Request Format

The system POSTs JSON payloads:
```json
{
  "pipeline_id": 123456,
  "project_id": 789,
  "project_name": "my-app",
  "status": "failed",
  "ref": "main",
  "sha": "abc123...",
  "pipeline_type": "main",
  "created_at": "2025-12-30T10:00:00Z",
  "duration": 120.5,
  "user": {
    "username": "johndoe",
    "email": "john@example.com"
  },
  "stages": ["build", "test", "deploy"],
  "jobs": [
    {
      "job_id": 456,
      "job_name": "build:production",
      "log_content": "Full build logs...",
      "status": "success",
      "stage": "build",
      "duration": 60.2
    }
  ]
}
```

### Request Logging

All API requests/responses are logged to `logs/api-requests.log`:
```
[2025-12-30 10:20:20] PIPELINE_ID=123456 PROJECT_ID=789 URL=http://api.example.com:8000/api/analyze STATUS=200 DURATION=1250ms RESPONSE={"success":true}
```

### Example: API Posting Logs

```
2025-12-30 10:20:18.789 | INFO  | src.api_poster          | a1b2c3d4 | Posting pipeline logs to API for 'my-app' (pipeline 123456) | job_count=5
2025-12-30 10:20:19.234 | INFO  | src.api_poster          | a1b2c3d4 | Formatted API payload | payload_size_bytes=45678
2025-12-30 10:20:19.235 | INFO  | src.api_poster          | a1b2c3d4 | Sending POST request to http://api.example.com:8000/api/analyze
2025-12-30 10:20:20.567 | INFO  | src.api_poster          | a1b2c3d4 | API returned success | http_status=200 duration_ms=1333
2025-12-30 10:20:20.568 | INFO  | src.api_poster          | a1b2c3d4 | Successfully posted pipeline 123456 logs to API
```

### Retry Logic

Automatic retry with exponential backoff:
- Attempt 1: Immediate
- Attempt 2: Wait 2s
- Attempt 3: Wait 4s
- Attempt 4: Wait 8s

```
2025-12-30 10:25:30.123 | ERROR | src.api_poster          | b2c3d4e5 | API POST failed: Connection timeout
2025-12-30 10:25:30.124 | INFO  | src.api_poster          | b2c3d4e5 | Retrying API POST (attempt 1/3) after 2.0s
2025-12-30 10:25:32.456 | INFO  | src.api_poster          | b2c3d4e5 | Retry attempt 1: Sending POST request
2025-12-30 10:25:34.789 | INFO  | src.api_poster          | b2c3d4e5 | API POST succeeded on retry | attempt=1
```

## 3.5 Log Filtering Configuration

### Overview

Log filtering reduces storage by saving only relevant logs based on pipeline status, project, or job status.

### Pipeline Status Filtering

Save logs only for specific pipeline statuses:
```bash
LOG_SAVE_PIPELINE_STATUS=failed,canceled
```

**Options:** `all`, `failed`, `success`, `running`, `canceled`, `skipped`

**Examples:**
```bash
# Save only failed pipelines (reduce storage by ~90%)
LOG_SAVE_PIPELINE_STATUS=failed

# Save failed and canceled pipelines
LOG_SAVE_PIPELINE_STATUS=failed,canceled

# Save all pipelines (default)
LOG_SAVE_PIPELINE_STATUS=all
```

### Project Filtering

**Whitelist specific projects:**
```bash
LOG_SAVE_PROJECTS=123,456,789
```

**Blacklist noisy projects:**
```bash
LOG_EXCLUDE_PROJECTS=999,888,777
```

**Note:** If `LOG_SAVE_PROJECTS` is set, `LOG_EXCLUDE_PROJECTS` is ignored.

### Job Status Filtering

Save logs only for specific job statuses within a pipeline:
```bash
LOG_SAVE_JOB_STATUS=failed,canceled
```

**Options:** `all`, `failed`, `success`, `canceled`, `skipped`

**Example:**
```bash
# Save all pipelines but only failed job logs
LOG_SAVE_PIPELINE_STATUS=all
LOG_SAVE_JOB_STATUS=failed
```

### Metadata-Only Mode

Track all pipelines but save logs only for filtered ones:
```bash
LOG_SAVE_METADATA_ALWAYS=true
```

When `true`:
- Metadata saved for all pipelines
- Logs saved only for filtered pipelines
- Useful for tracking all activity while reducing storage

### Example: Filtering in Action

**Configuration:**
```bash
LOG_SAVE_PIPELINE_STATUS=failed
LOG_SAVE_JOB_STATUS=all
LOG_SAVE_METADATA_ALWAYS=true
```

**Logs:**
```
# Successful pipeline - metadata saved, logs skipped
2025-12-30 10:40:15.456 | INFO  | src.webhook_listener    | e6f7g8h9 | Pipeline 789 status: success - metadata saved, logs skipped by filter

# Failed pipeline - metadata and logs saved
2025-12-30 10:45:15.456 | INFO  | src.webhook_listener    | f7g8h9i0 | Pipeline 790 status: failed - saving logs (filter match)
2025-12-30 10:45:16.234 | INFO  | src.webhook_listener    | f7g8h9i0 | Job filtering: 5 jobs to fetch, 0 jobs skipped by filter
```

## 3.6 Configuration Examples & Scenarios

### Scenario 1: Production - Failed Logs Only

**Goal:** Save storage by storing only failed pipeline logs.

```bash
# GitLab Configuration
GITLAB_URL=https://gitlab.com
GITLAB_TOKEN=glpat-xxxxxxxxxxxxxxxxxxxx

# Log Filtering
LOG_SAVE_PIPELINE_STATUS=failed,canceled
LOG_SAVE_METADATA_ALWAYS=true

# Storage reduced by ~90%
```

### Scenario 2: Development - Specific Projects Only

**Goal:** Track only development projects.

```bash
# GitLab Configuration
GITLAB_URL=https://gitlab.com
GITLAB_TOKEN=glpat-xxxxxxxxxxxxxxxxxxxx

# Project Filtering
LOG_SAVE_PROJECTS=123,456,789  # Dev project IDs

# All other projects ignored
```

### Scenario 3: CI/CD Monitoring - All Pipelines, Failed Jobs

**Goal:** Track all pipeline activity, save logs for failed jobs only.

```bash
# GitLab Configuration
GITLAB_URL=https://gitlab.com
GITLAB_TOKEN=glpat-xxxxxxxxxxxxxxxxxxxx

# Log Filtering
LOG_SAVE_PIPELINE_STATUS=all
LOG_SAVE_JOB_STATUS=failed,canceled
LOG_SAVE_METADATA_ALWAYS=true

# Metadata for all pipelines, logs for failed jobs only
```

### Scenario 4: API Posting with File Fallback

**Goal:** Post logs to API, fall back to files if API fails.

```bash
# GitLab Configuration
GITLAB_URL=https://gitlab.com
GITLAB_TOKEN=glpat-xxxxxxxxxxxxxxxxxxxx

# BFA Configuration
BFA_HOST=bfa-server.example.com
BFA_SECRET_KEY=your_bfa_secret_key

# API Posting
API_POST_ENABLED=true
API_POST_SAVE_TO_FILE=false  # API only, fallback to file on error
API_POST_RETRY_ENABLED=true
```

### Scenario 5: Dual Mode - Maximum Reliability

**Goal:** Save logs to both API and files for redundancy.

```bash
# GitLab Configuration
GITLAB_URL=https://gitlab.com
GITLAB_TOKEN=glpat-xxxxxxxxxxxxxxxxxxxx

# BFA Configuration
BFA_HOST=bfa-server.example.com
BFA_SECRET_KEY=your_bfa_secret_key

# API Posting
API_POST_ENABLED=true
API_POST_SAVE_TO_FILE=true  # Dual mode: both API and files
API_POST_RETRY_ENABLED=true

# Higher storage usage but maximum reliability
```

### Scenario 6: Multi-Platform - GitLab + Jenkins

**Goal:** Extract logs from both GitLab and Jenkins.

```bash
# GitLab Configuration
GITLAB_URL=https://gitlab.com
GITLAB_TOKEN=glpat-xxxxxxxxxxxxxxxxxxxx

# Jenkins Configuration
JENKINS_ENABLED=true
JENKINS_URL=https://jenkins.example.com
JENKINS_USER=your_username
JENKINS_API_TOKEN=your_jenkins_token

# Both platforms supported simultaneously
```

---

*Due to length constraints, I'm creating this as DOCUMENTATION_NEW.md. This is Section 1-3 complete. Sections 4-6 will continue in the same file.*

**Status: Sections 1-3 complete (System Overview, Quick Start, Configuration)**
**Next: Sections 4-6 (Usage & Operations, Advanced Topics, Reference)**

# 4. Usage & Operations

## 4.1 Running the Application

### Option 1: Docker (Recommended for Production)

**Start Container:**
```bash
./manage_container.py start
```

**Stop Container:**
```bash
./manage_container.py stop
```

**Restart Container:**
```bash
./manage_container.py restart
```

**View Status:**
```bash
./manage_container.py status
```

**Example Output:**
```
Container: bfa-gitlab-pipeline-extractor
Status: running (healthy)
Uptime: 2 hours, 15 minutes
Memory: 245 MB / 2 GB (12.3%)
CPU: 0.5%
Port Mapping: 0.0.0.0:8000 -> 8000/tcp

Health Check: Healthy
Last Check: 2 seconds ago
Checks Passed: 145 / 145 (100%)
```

### Option 2: Direct Python

**Start Server:**
```bash
# Activate virtual environment
source venv/bin/activate

# Start server
python src/webhook_listener.py
```

**Run in Background:**
```bash
nohup python src/webhook_listener.py > server.log 2>&1 &
```

**Using Uvicorn Directly:**
```bash
# Basic
uvicorn src.webhook_listener:app --host 0.0.0.0 --port 8000

# With auto-reload (development)
uvicorn src.webhook_listener:app --reload --host 0.0.0.0 --port 8000

# With workers (production)
uvicorn src.webhook_listener:app --host 0.0.0.0 --port 8000 --workers 4
```

### Option 3: Systemd Service (Linux)

**Create Service File:**
```bash
sudo nano /etc/systemd/system/gitlab-log-extractor.service
```

**Service Configuration:**
```ini
[Unit]
Description=GitLab Pipeline Log Extractor
After=network.target

[Service]
Type=simple
User=your_username
WorkingDirectory=/home/user/extract-build-logs
Environment="PATH=/home/user/extract-build-logs/venv/bin"
ExecStart=/home/user/extract-build-logs/venv/bin/python src/webhook_listener.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

**Enable and Start:**
```bash
sudo systemctl daemon-reload
sudo systemctl enable gitlab-log-extractor
sudo systemctl start gitlab-log-extractor
sudo systemctl status gitlab-log-extractor
```

## 4.2 Docker Operations

### Common Commands

**Build Image:**
```bash
./manage_container.py build
```

**View Logs:**
```bash
# Live logs
./manage_container.py logs

# Last 100 lines
docker logs --tail 100 bfa-gitlab-pipeline-extractor

# Since specific time
docker logs --since "2025-12-30T10:00:00" bfa-gitlab-pipeline-extractor
```

**Execute Commands in Container:**
```bash
# Open shell
docker exec -it bfa-gitlab-pipeline-extractor /bin/bash

# Run specific command
docker exec bfa-gitlab-pipeline-extractor ls -la /app/logs

# View file
docker exec bfa-gitlab-pipeline-extractor cat /app/logs/application.log
```

**Container Management:**
```bash
# Remove container (keeps data)
./manage_container.py remove

# Remove everything (including data)
docker rm -f bfa-gitlab-pipeline-extractor
docker volume prune

# Rebuild from scratch
./manage_container.py build
./manage_container.py start
```

### Monitoring & Testing

**Test Webhook Endpoint:**
```bash
./manage_container.py test
```

**View Configuration:**
```bash
./manage_container.py config
```

**Export Monitoring Data:**
```bash
./manage_container.py export data.csv
```

**Monitoring Dashboard:**
```bash
./manage_container.py monitor --hours 24
```

## 4.3 Application Logging

### Logging Features

- **Request ID tracking** - Trace single pipeline across all log entries
- **Project names** - Human-readable logs with project names
- **Aligned columns** - Pipe-delimited format for easy parsing
- **Multiple log files** - Separate application and API logs
- **Automatic rotation** - Size-based rotation with configurable backups
- **Sensitive data masking** - Tokens automatically redacted with `[REDACTED***]`
- **Configurable log levels** - DEBUG, INFO, WARNING, ERROR, CRITICAL

### Log Files

| File | Purpose | Size Limit | Backups | Total Storage |
|------|---------|------------|---------|---------------|
| **application.log** | All application logs | 100 MB | 10 | ~1.1 GB |
| **api-requests.log** | API posting requests/responses | 50 MB | 10 | ~550 MB |

### Log Format

```
TIMESTAMP | LEVEL | LOGGER | REQUEST_ID | MESSAGE | CONTEXT
```

**Example Logs:**
```
2025-12-30 10:20:15.456 | INFO  | src.webhook_listener    | a1b2c3d4 | Webhook received | event_type=Pipeline Hook
2025-12-30 10:20:15.457 | INFO  | src.pipeline_extractor  | a1b2c3d4 | Extracted info for pipeline 1061175 | project=my-app type=main
2025-12-30 10:20:15.500 | INFO  | src.webhook_listener    | a1b2c3d4 | Starting pipeline log extraction | pipeline_id=1061175
2025-12-30 10:20:16.234 | INFO  | src.webhook_listener    | a1b2c3d4 | Job filtering: 5 jobs to fetch | pipeline_id=1061175
2025-12-30 10:20:20.568 | INFO  | src.webhook_listener    | a1b2c3d4 | Pipeline processing complete | duration_s=5.1 jobs=5
```

### Viewing Logs

**Method 1: Docker Logs**
```bash
# Follow live logs
./manage_container.py logs

# Last 100 lines
docker logs --tail 100 bfa-gitlab-pipeline-extractor
```

**Method 2: Log Files (Most Detailed)**
```bash
# Tail application log
tail -f ./logs/application.log

# View with color highlighting
tail -f ./logs/application.log | grep --color=always -E 'ERROR|WARN|$'

# API request logs
tail -f ./logs/api-requests.log
```

**Method 3: Inside Container**
```bash
docker exec bfa-gitlab-pipeline-extractor tail -f /app/logs/application.log
docker exec bfa-gitlab-pipeline-extractor grep ERROR /app/logs/application.log
```

### Searching Logs

**By Request ID:**
```bash
# Find all logs for specific request
grep "a1b2c3d4" logs/application.log

# With context (5 lines before/after)
grep -C 5 "a1b2c3d4" logs/application.log
```

**By Pipeline ID:**
```bash
grep "pipeline_id=12345" logs/application.log*
```

**By Project Name:**
```bash
grep "project_name=my-app" logs/application.log
grep "from project 'my-app'" logs/application.log
```

**By Log Level:**
```bash
# Only errors
grep "| ERROR |" logs/application.log

# Errors and warnings
grep -E "| ERROR | | WARN |" logs/application.log
```

### Request ID Tracking

Every webhook request gets a unique 8-character request ID that tracks the entire processing flow:

**Example: Complete Request Flow**
```
2025-12-30 10:20:15.456 | INFO  | src.webhook_listener    | a1b2c3d4 | Request ID a1b2c3d4 tracking pipeline 1061175
2025-12-30 10:20:15.457 | INFO  | src.pipeline_extractor  | a1b2c3d4 | Extracted info for pipeline 1061175
2025-12-30 10:20:15.500 | INFO  | src.webhook_listener    | a1b2c3d4 | Starting pipeline log extraction
2025-12-30 10:20:16.123 | INFO  | src.log_fetcher         | a1b2c3d4 | Fetching logs for 5 jobs
2025-12-30 10:20:17.234 | INFO  | src.log_fetcher         | a1b2c3d4 | Fetched log for job 456 (build)
2025-12-30 10:20:18.345 | INFO  | src.log_fetcher         | a1b2c3d4 | Fetched log for job 457 (test)
2025-12-30 10:20:19.456 | INFO  | src.api_poster          | a1b2c3d4 | Posting pipeline logs to API
2025-12-30 10:20:20.567 | INFO  | src.api_poster          | a1b2c3d4 | Successfully posted to API
2025-12-30 10:20:20.568 | INFO  | src.webhook_listener    | a1b2c3d4 | Pipeline processing complete | duration_s=5.1
```

To trace a complete request:
```bash
grep "a1b2c3d4" logs/application.log
```

## 4.4 Monitoring & Tracking

### What is Tracked

The system automatically tracks every webhook request in a SQLite database (`logs/monitoring.db`):

- Total requests received
- Processing status (queued, processing, completed, failed, skipped)
- Success/failure rates
- Processing times
- Job counts per pipeline
- Error messages
- Pipeline types

### CLI Dashboard Tool

**View Recent Requests:**
```bash
python scripts/monitor_dashboard.py

# Show last 100 requests
python scripts/monitor_dashboard.py --recent 100

# Show requests from last 24 hours
python scripts/monitor_dashboard.py --hours 24
```

**Example Output:**
```
GitLab Pipeline Log Extractor - Monitoring Dashboard
====================================================

Summary (Last 24 hours):
  Total Requests: 145
  Completed: 132 (91.0%)
  Failed: 8 (5.5%)
  Skipped: 5 (3.4%)

Processing Times:
  Average: 5.2s
  Median: 4.8s
  P95: 12.3s
  P99: 18.7s

Recent Requests:
┏━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━┓
┃ Pipeline ┃ Project    ┃ Status      ┃ Jobs      ┃ Duration  ┃
┡━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━┩
│ 1061175  │ my-app     │ completed   │ 5         │ 5.1s      │
│ 1061180  │ other-app  │ completed   │ 3         │ 3.2s      │
│ 1061185  │ my-app     │ failed      │ 7         │ 12.5s     │
└──────────┴────────────┴─────────────┴───────────┴───────────┘
```

**Export to CSV:**
```bash
python scripts/monitor_dashboard.py --export pipeline_data.csv
```

### Monitoring API Endpoints

**Get Summary Statistics:**
```bash
curl http://localhost:8000/monitor/summary?hours=24
```

**Response:**
```json
{
  "total_requests": 145,
  "completed": 132,
  "failed": 8,
  "skipped": 5,
  "success_rate": 91.0,
  "average_duration_seconds": 5.2,
  "total_jobs_processed": 678
}
```

**Get Recent Requests:**
```bash
curl http://localhost:8000/monitor/recent?limit=50
```

**Get Specific Pipeline Details:**
```bash
curl http://localhost:8000/monitor/pipeline/12345
```

**Download CSV Export:**
```bash
curl -O http://localhost:8000/monitor/export/csv?hours=24
```

### Database Queries

Query the SQLite database directly:

```bash
sqlite3 logs/monitoring.db "SELECT * FROM requests ORDER BY timestamp DESC LIMIT 10"
```

**Useful Queries:**

```sql
-- Success rate by project
SELECT 
    project_name,
    COUNT(*) as total,
    SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed,
    ROUND(100.0 * SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) / COUNT(*), 2) as success_rate
FROM requests
WHERE timestamp > datetime('now', '-24 hours')
GROUP BY project_name
ORDER BY total DESC;

-- Average processing time by pipeline type
SELECT 
    pipeline_type,
    AVG(processing_duration_seconds) as avg_duration,
    COUNT(*) as count
FROM requests
WHERE status = 'completed'
GROUP BY pipeline_type;

-- Failed requests
SELECT pipeline_id, project_name, error_message, timestamp
FROM requests
WHERE status = 'failed'
ORDER BY timestamp DESC
LIMIT 20;
```

## 4.5 Usage Examples

### Example 1: Monitor Failed Pipelines

**Goal:** Get notified when pipelines fail.

**Configuration:**
```bash
LOG_SAVE_PIPELINE_STATUS=failed
LOG_SAVE_METADATA_ALWAYS=true
```

**Monitor:**
```bash
# Watch for failed pipelines
watch -n 10 'sqlite3 logs/monitoring.db "SELECT pipeline_id, project_name, timestamp FROM requests WHERE status = \"failed\" ORDER BY timestamp DESC LIMIT 5"'
```

### Example 2: Track Specific Project

**Goal:** Monitor all activity for a specific project.

**Search Logs:**
```bash
# Real-time monitoring
tail -f logs/application.log | grep "project_name=my-app"

# Count today's pipelines
grep "project_name=my-app" logs/application.log | grep "$(date +%Y-%m-%d)" | wc -l
```

### Example 3: Investigate Slow Pipeline

**Goal:** Debug why a pipeline is processing slowly.

**1. Find the request ID:**
```bash
grep "pipeline_id=12345" logs/application.log | head -1
# Output: 2025-12-30 10:20:15.456 | INFO | src.webhook_listener | a1b2c3d4 | ...
```

**2. Trace complete flow:**
```bash
grep "a1b2c3d4" logs/application.log
```

**3. Analyze timing:**
```bash
grep "a1b2c3d4" logs/application.log | awk '{print $2, $3, $NF}'
```

### Example 4: Export Data for Analysis

**Goal:** Analyze pipeline trends over time.

**Export Data:**
```bash
# Export last 7 days
python scripts/monitor_dashboard.py --hours 168 --export last_7_days.csv

# Import into Excel, Google Sheets, or pandas for analysis
```

## 4.6 API Endpoints Reference

### Health Check

**Endpoint:** `GET /health`

**Response:**
```json
{
  "status": "healthy",
  "service": "gitlab-log-extractor",
  "version": "1.0.0"
}
```

**Usage:**
```bash
curl http://localhost:8000/health
```

### Storage Statistics

**Endpoint:** `GET /stats`

**Response:**
```json
{
  "total_projects": 5,
  "total_pipelines": 23,
  "total_jobs": 156,
  "total_size_bytes": 45678901,
  "total_size_mb": 43.56
}
```

**Usage:**
```bash
curl http://localhost:8000/stats
```

### GitLab Webhook

**Endpoint:** `POST /webhook/gitlab`

**Headers:**
- `X-Gitlab-Event`: Event type (must be "Pipeline Hook")
- `X-Gitlab-Token`: Webhook secret token
- `Content-Type`: application/json

**Request Body:** GitLab pipeline webhook payload

**Responses:**
- `200 OK`: Successfully processed or queued
- `400 Bad Request`: Invalid JSON payload
- `401 Unauthorized`: Invalid secret token
- `500 Internal Server Error`: Processing error

### Jenkins Webhook

**Endpoint:** `POST /webhook/jenkins`

**Headers:**
- `X-Jenkins-Token`: Webhook secret token
- `Content-Type`: application/json

**Request Body:**
```json
{
  "job_name": "my-pipeline",
  "build_number": 42,
  "build_url": "https://jenkins.example.com/job/my-pipeline/42/"
}
```

### Interactive API Documentation

**Swagger UI:** http://localhost:8000/docs
**ReDoc:** http://localhost:8000/redoc


# 5. Advanced Topics

## 5.1 Production Deployment

### Docker Secrets (Docker Swarm/Compose)

**Use Docker secrets for sensitive configuration:**

```yaml
# docker-compose.yml
version: '3.8'

services:
  gitlab-log-extractor:
    image: bfa-gitlab-pipeline-extractor
    secrets:
      - gitlab_token
      - bfa_secret_key
    environment:
      GITLAB_URL: https://gitlab.com
      GITLAB_TOKEN_FILE: /run/secrets/gitlab_token
      BFA_SECRET_KEY_FILE: /run/secrets/bfa_secret_key
    ports:
      - "8000:8000"
    volumes:
      - ./logs:/app/logs

secrets:
  gitlab_token:
    external: true
  bfa_secret_key:
    external: true
```

**Create secrets:**
```bash
echo "glpat-xxxxxxxxxxxxxxxxxxxx" | docker secret create gitlab_token -
echo "your_bfa_secret_key" | docker secret create bfa_secret_key -
```

### Kubernetes Deployment

**Kubernetes manifest:**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: gitlab-log-extractor
spec:
  replicas: 2
  selector:
    matchLabels:
      app: gitlab-log-extractor
  template:
    metadata:
      labels:
        app: gitlab-log-extractor
    spec:
      containers:
      - name: extractor
        image: bfa-gitlab-pipeline-extractor:latest
        ports:
        - containerPort: 8000
        env:
        - name: GITLAB_URL
          value: "https://gitlab.com"
        - name: GITLAB_TOKEN
          valueFrom:
            secretKeyRef:
              name: gitlab-secrets
              key: token
        volumeMounts:
        - name: logs
          mountPath: /app/logs
      volumes:
      - name: logs
        persistentVolumeClaim:
          claimName: log-extractor-logs
---
apiVersion: v1
kind: Service
metadata:
  name: gitlab-log-extractor
spec:
  selector:
    app: gitlab-log-extractor
  ports:
  - port: 8000
    targetPort: 8000
  type: LoadBalancer
```

**Create secrets:**
```bash
kubectl create secret generic gitlab-secrets \
  --from-literal=token='glpat-xxxxxxxxxxxxxxxxxxxx'
```

### Production Monitoring and Logging

**1. Health Check Monitoring:**
```bash
# Add to monitoring system (Prometheus, Datadog, etc.)
curl http://localhost:8000/health

# Expected response
{"status":"healthy","service":"gitlab-log-extractor","version":"1.0.0"}
```

**2. Log Aggregation:**
- Forward logs to centralized logging (ELK, Splunk, CloudWatch)
- Use structured logging format for easy parsing
- Monitor error rates and processing times

**3. Metrics Collection:**
```bash
# Monitor via API
curl http://localhost:8000/monitor/summary?hours=1

# Track:
# - Request rate (requests/min)
# - Success rate (% completed)
# - Processing time (avg, p95, p99)
# - Error count
```

### High Availability

**Load Balancing:**
- Run multiple instances behind a load balancer
- Each instance processes webhooks independently
- Shared storage for logs (NFS, S3)

**Considerations:**
- Webhook events may be delivered to different instances
- Each instance tracks its own requests in monitoring.db
- File storage requires shared filesystem or S3
- API posting is instance-independent

## 5.2 Testing & CI/CD Pipeline

### Test Suite Overview

| Test Module | Tests | Coverage | Focus Area |
|-------------|-------|----------|------------|
| `test_api_poster.py` | 20 | 99.80% | API posting, timeouts, errors, retry logic |
| `test_error_handler.py` | 12 | 84% | Retry with backoff, circuit breaker |
| `test_pipeline_extractor.py` | 8 | 86% | Pipeline data extraction, filtering |
| `test_storage_manager.py` | 10 | 78% | File storage, metadata management |
| `test_webhook_listener.py` | 15 | 95.45% | Webhook handling, routing |

### Run All Tests

```bash
# Run all tests
pytest tests/

# Run with coverage report
pytest --cov=src tests/ --cov-report=term-missing

# Run specific test file
pytest tests/test_api_poster.py -v

# Run with debugging output
pytest tests/ -v -s
```

### CI/CD Pipeline

The project includes comprehensive GitLab CI/CD configuration:

**Pipeline Stages:**

1. **Lint Stage** (Code Quality)
   - Flake8: PEP 8 compliance
   - Pylint: Comprehensive linting (advisory)

2. **Test Stage**
   - Pytest: Unit tests execution
   - All tests must pass

3. **Coverage Stage**
   - Coverage report generation
   - HTML and XML formats
   - Coverage threshold tracking

**Local CI Testing:**
```bash
# Run linters
flake8 src/ tests/ --max-line-length=120
pylint src/ --max-line-length=120

# Run tests with coverage
pytest tests/ --cov=src --cov-report=html --cov-report=term-missing

# View HTML coverage report
open coverage_html/index.html
```

### Manual Testing

**Test Webhook Endpoint:**
```bash
curl -X POST http://localhost:8000/webhook/gitlab \
  -H "Content-Type: application/json" \
  -H "X-Gitlab-Event: Pipeline Hook" \
  -H "X-Gitlab-Token: your_secret" \
  -d '{
    "object_kind":"pipeline",
    "object_attributes":{
      "id":123,"status":"success","ref":"main"
    },
    "project":{"id":789,"name":"test-project"}
  }'
```

**Expected Response:**
```json
{
  "status": "success",
  "message": "Pipeline logs queued for extraction",
  "pipeline_id": 123,
  "project_id": 789
}
```

## 5.3 Database Maintenance

### SQLite Maintenance

#### Daily Tasks

**Check Database Health:**
```bash
./scripts/manage_database.sh check
```

**Example Output:**
```
Database Health Check
====================
Database: logs/monitoring.db
Size: 12.5 MB
Total Requests: 1,234
Status: Healthy
WAL Mode: Enabled
```

#### Weekly Tasks

**Create Backup:**
```bash
# Automatic backup with timestamp
./scripts/manage_database.sh backup weekly
```

**List Backups:**
```bash
./scripts/manage_database.sh list
```

**Example Output:**
```
Available Backups:
- monitoring_backup_2025-12-30_10-30-00.db (12.5 MB)
- monitoring_backup_2025-12-23_10-30-00.db (11.2 MB)
- monitoring_backup_2025-12-16_10-30-00.db (10.8 MB)
```

#### Monthly Tasks

**Vacuum Database:**
```bash
sqlite3 logs/monitoring.db "VACUUM;"
```

**Optimize:**
```bash
sqlite3 logs/monitoring.db "PRAGMA optimize;"
```

**Archive Old Data:**
```sql
-- Delete requests older than 90 days
DELETE FROM requests WHERE timestamp < datetime('now', '-90 days');

-- Vacuum after deletion
VACUUM;
```

### Backup & Restore

**Manual Backup:**
```bash
# Create backup
./scripts/manage_database.sh backup manual

# With custom name
cp logs/monitoring.db backups/monitoring_$(date +%Y%m%d).db
```

**Restore from Backup:**
```bash
./scripts/manage_database.sh restore monitoring_backup_2025-12-30.db
```

**Automated Backup Script:**
```bash
#!/bin/bash
# Add to crontab: 0 2 * * * /path/to/backup.sh

BACKUP_DIR="/backups/gitlab-log-extractor"
DB_PATH="/home/user/extract-build-logs/logs/monitoring.db"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/monitoring_$TIMESTAMP.db"

# Create backup
cp "$DB_PATH" "$BACKUP_FILE"

# Compress
gzip "$BACKUP_FILE"

# Delete backups older than 30 days
find "$BACKUP_DIR" -name "monitoring_*.db.gz" -mtime +30 -delete

echo "Backup created: $BACKUP_FILE.gz"
```

## 5.4 Troubleshooting & Common Issues

### Server Won't Start

**Issue:** Port already in use
```
ERROR: Port 8000 is already in use
```

**Solution:**
```bash
# Check what's using the port
lsof -i :8000

# Kill the process
kill -9 <PID>

# Or change WEBHOOK_PORT in .env
WEBHOOK_PORT=8001
```

---

**Issue:** Permission denied
```
ERROR: Permission denied: '/app/logs/application.log'
```

**Solution:**
```bash
# Check permissions
ls -la logs/

# Fix permissions
chmod 755 logs/
chmod 644 logs/*.log

# For Docker
./manage_container.py stop
rm -rf logs/*
./manage_container.py start
```

### Webhook Returns 401

**Issue:** Secret token mismatch

**Solution:**
1. Verify `WEBHOOK_SECRET` in `.env` matches GitLab webhook secret
2. Check for extra spaces or newlines
3. Regenerate secret if needed:
```bash
# Generate new secret
openssl rand -hex 32

# Update .env
WEBHOOK_SECRET=<new_secret>

# Update GitLab webhook configuration
# Restart server
```

### Logs Not Being Saved

**Issue:** Logs filtered by configuration

**Check Configuration:**
```bash
grep "LOG_SAVE" .env
```

**Common Causes:**
- `LOG_SAVE_PIPELINE_STATUS=failed` but pipeline succeeded
- `LOG_SAVE_PROJECTS` doesn't include project ID
- `LOG_EXCLUDE_PROJECTS` includes project ID

**Check Application Logs:**
```bash
grep "skipped by filter" logs/application.log
```

**Example:**
```
2025-12-30 10:20:15.456 | INFO | src.webhook_listener | a1b2c3d4 | Pipeline 123 status: success - logs skipped by filter (only saving failed)
```

---

**Issue:** Permission denied writing logs

**Solution:**
```bash
# Check directory exists and is writable
ls -la logs/

# Create directory
mkdir -p logs
chmod 755 logs

# For Docker, let manage_container.py handle it
./manage_container.py start
```

### API Calls Failing

**Issue:** Invalid GitLab token

**Check Token:**
```bash
# Test token manually
curl -H "PRIVATE-TOKEN: ${GITLAB_TOKEN}" https://gitlab.com/api/v4/user
```

**Expected Response:**
```json
{
  "id": 123,
  "username": "your_username",
  ...
}
```

**If Invalid:**
1. Verify token has `api` scope
2. Check token hasn't expired
3. Generate new token in GitLab → Profile → Access Tokens

---

**Issue:** Connection timeouts

**Check Connectivity:**
```bash
# Test GitLab connectivity
curl -I https://gitlab.com

# Test from container
docker exec bfa-gitlab-pipeline-extractor curl -I https://gitlab.com
```

**Check Logs:**
```bash
grep "Connection timeout" logs/application.log
grep "retry" logs/application.log
```

**Increase Timeout:**
```bash
# In .env
RETRY_ATTEMPTS=5
RETRY_DELAY=5
```

### API Posting Failures

**Issue:** API endpoint not reachable

**Check Configuration:**
```bash
grep "BFA_HOST" .env
grep "API_POST" .env
```

**Test API Endpoint:**
```bash
curl -I http://${BFA_HOST}:8000/api/analyze
```

**Check API Logs:**
```bash
tail -f logs/api-requests.log
```

**Example Failure:**
```
[2025-12-30 10:20:20] PIPELINE_ID=123 URL=http://api.example.com/analyze STATUS=500 ERROR="Internal Server Error"
```

**Solutions:**
1. Verify BFA_HOST is correct
2. Check API endpoint is running
3. Verify network connectivity
4. Check BFA_SECRET_KEY is valid
5. Enable fallback to file storage:
```bash
API_POST_SAVE_TO_FILE=true  # Dual mode
```

### High Memory Usage

**Check Memory Usage:**
```bash
./manage_container.py status
```

**Solutions:**
1. Reduce log retention period
2. Enable log filtering to reduce logs saved
3. Increase Docker memory limit:
```bash
# In manage_container.py or docker-compose.yml
mem_limit: 2g
```

### Database Issues

**Issue:** Database locked

**Check:**
```bash
# See if database is in use
lsof logs/monitoring.db
```

**Solution:**
```bash
# Stop all processes using database
./manage_container.py stop

# Check for WAL files
ls -la logs/monitoring.db*

# Restart
./manage_container.py start
```

---

**Issue:** Database corruption

**Symptoms:**
```
ERROR: database disk image is malformed
```

**Recovery:**
```bash
# Create backup
cp logs/monitoring.db logs/monitoring.db.corrupt

# Try to recover
sqlite3 logs/monitoring.db ".recover" | sqlite3 logs/monitoring_recovered.db

# If recovery works, replace
mv logs/monitoring_recovered.db logs/monitoring.db

# If recovery fails, restore from backup
./scripts/manage_database.sh restore monitoring_backup_latest.db
```

---

# 6. Reference

## 6.1 Development & Contributing

### Development Setup

**1. Clone Repository:**
```bash
git clone <repository-url>
cd extract-build-logs
```

**2. Create Development Environment:**
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install pytest pytest-cov flake8 pylint
```

**3. Run in Development Mode:**
```bash
# With auto-reload
uvicorn src.webhook_listener:app --reload --host 0.0.0.0 --port 8000
```

### Adding New Features

**1. Create Feature Branch:**
```bash
git checkout -b feature/your-feature-name
```

**2. Write Code:**
- Add code in `src/`
- Follow existing code style
- Add docstrings
- Handle errors appropriately

**3. Write Tests:**
- Add tests in `tests/`
- Aim for >80% coverage
- Test success and error cases

**4. Run Tests:**
```bash
pytest tests/ --cov=src --cov-report=term-missing
flake8 src/ tests/
pylint src/
```

**5. Update Documentation:**
- Update README.md if needed
- Update DOCUMENTATION.md with new features
- Add configuration examples

**6. Create Pull Request:**
- Push changes to your branch
- Create PR with clear description
- Include test results

### Code Style

- Follow PEP 8
- Use type hints where appropriate
- Maximum line length: 120 characters
- Use meaningful variable names
- Add comments for complex logic

## 6.2 Security Considerations

### Protecting Secrets

**Never commit secrets to version control:**
- .env file is in .gitignore
- Use environment variables
- Use Docker secrets in production

**Rotate Secrets Regularly:**
```bash
# Generate new secret
openssl rand -hex 32

# Update .env
WEBHOOK_SECRET=new_secret

# Update GitLab webhook configuration
```

### Network Security

**Firewall Rules:**
```bash
# Allow only GitLab server IP
sudo ufw allow from <gitlab-server-ip> to any port 8000

# Or use nginx reverse proxy with SSL
```

**HTTPS/SSL:**
- Use reverse proxy (nginx, Apache) for SSL termination
- Enable SSL verification in GitLab webhook
- Use Let's Encrypt for free SSL certificates

### Sensitive Data Masking

All tokens are automatically masked in logs using `[REDACTED***]` format:
```
GitLab Token: glpa...[REDACTED***]vf1
BFA Secret Key: secr...[REDACTED***]key
```

## 6.3 FAQ

**Q: Can I run multiple instances?**
A: Yes, but they need separate ports or load balancer. Each tracks its own requests.

**Q: What happens if the server crashes during processing?**
A: Webhook responses are non-blocking. GitLab/Jenkins won't retry, but the request is logged in monitoring.db.

**Q: How much storage do logs require?**
A: Depends on pipeline frequency and log filtering. Example: 100 pipelines/day × 5 jobs × 100KB/job = ~50MB/day

**Q: Can I delete old logs safely?**
A: Yes. Delete old pipeline directories in logs/. The monitoring database tracks all requests regardless.

**Q: Does it support GitLab self-hosted?**
A: Yes. Set `GITLAB_URL` to your GitLab instance URL.

**Q: Can I use it without Docker?**
A: Yes. See [Manual Installation](#22-manual-installation) section.

**Q: How do I upgrade to a new version?**
A: Pull new code, rebuild Docker image, restart container. Logs and monitoring database are preserved.

## 6.4 API Design History

### Version 1.0 (Initial Release)
- Basic webhook receiving
- File-based log storage
- Simple error handling

### Version 2.0 (API Posting)
- Added API posting capability
- Dual mode (API + file)
- JWT authentication support
- Request/response logging

### Version 3.0 (Current)
- Improved logging with request ID tracking
- Log filtering by status/project/job
- Jenkins integration
- Enhanced monitoring dashboard
- Reorganized documentation

---

**End of Documentation**

For quick reference, see [README.md](README.md)

**Support:**
- Report issues in the repository
- Check logs for troubleshooting
- Review this documentation

**Last Updated:** 2025-12-30
**Version:** 3.0
