# GitLab & Jenkins Pipeline Log Extraction System

A production-ready webhook server that automatically extracts and stores pipeline logs from GitLab and Jenkins with comprehensive error handling, retry logic, and structured metadata. Supports parallel execution blocks and API posting.

## Table of Contents

- [GitLab Pipeline Log Extraction System](#gitlab-pipeline-log-extraction-system)
  - [Table of Contents](#table-of-contents)
  - [Overview](#overview)
  - [Architecture](#architecture)
    - [System Architecture Diagram](#system-architecture-diagram)
    - [Data Flow Diagram](#data-flow-diagram)
  - [Features](#features)
  - [Project Structure](#project-structure)
    - [Directory Structure After Processing](#directory-structure-after-processing)
  - [Module Documentation](#-module-documentation)
    - [Module Connection Diagram](#module-connection-diagram)
    - [Files \& Folder Structure](#files--folder-structure)
      - [Core Application Files](#core-application-files)
      - [Test Files](#test-files)
    - [Module Functions \& Data Flow](#module-functions--data-flow)
      - [1. webhook\_listener.py (Main Server)](#1-webhook_listenerpy-main-server)
      - [2. pipeline\_extractor.py (Event Parser)](#2-pipeline_extractorpy-event-parser)
      - [3. log\_fetcher.py (API Client)](#3-log_fetcherpy-api-client)
      - [4. storage\_manager.py (File Storage)](#4-storage_managerpy-file-storage)
      - [5. config\_loader.py (Configuration)](#5-config_loaderpy-configuration)
      - [6. error\_handler.py (Retry Logic)](#6-error_handlerpy-retry-logic)
  - [Data Flow](#data-flow)
    - [Complete Event Processing Flow](#complete-event-processing-flow)
    - [Data Transformations](#data-transformations)
  - [Installation](#-installation)
    - [Prerequisites](#prerequisites)
    - [Step 1: Clone Repository](#step-1-clone-repository)
    - [Step 2: Create Virtual Environment](#step-2-create-virtual-environment)
    - [Step 3: Install Dependencies](#step-3-install-dependencies)
    - [Step 4: Configure Environment](#step-4-configure-environment)
    - [Step 5: Create GitLab Access Token](#step-5-create-gitlab-access-token)
  - [Docker Deployment](#docker-deployment)
    - [Quick Start with Docker](#quick-start-with-docker)
    - [Docker Commands](#docker-commands)
    - [Docker Monitoring](#docker-monitoring)
  - [Configuration](#configuration)
    - [Environment Variables](#environment-variables)
    - [GitLab Webhook Setup](#gitlab-webhook-setup)
  - [Usage](#usage)
    - [Start the Server](#start-the-server)
    - [Verify Server is Running](#verify-server-is-running)
    - [Access API Documentation](#access-api-documentation)
    - [Monitor Logs](#monitor-logs)
    - [View Storage Statistics](#view-storage-statistics)
  - [Monitoring \& Tracking](#monitoring--tracking)
    - [Quick Start](#quick-start)
    - [What is Tracked](#what-is-tracked)
    - [Monitoring API Endpoints](#monitoring-api-endpoints)
    - [Database Location](#database-location)
  - [API Documentation](#api-documentation)
    - [Webhook Events](#webhook-events)
      - [POST /webhook/gitlab](#post-webhookgitlab)
      - [GET /health](#get-health)
      - [GET /stats](#get-stats)
  - [Testing](#testing)
    - [Run All Tests](#run-all-tests)
    - [Manual Testing](#manual-testing)
  - [Troubleshooting](#-troubleshooting)
    - [Server Won't Start](#server-wont-start)
    - [Webhook Returns 401](#webhook-returns-401)
    - [Logs Not Being Saved](#logs-not-being-saved)
    - [API Calls Failing](#api-calls-failing)
  - [Development](#development)
    - [Adding New Features](#adding-new-features)
  - [Contributing](#contributing)

## Overview

This system provides a complete solution for:
- **GitLab Integration**: Receiving webhook events for pipeline completion
- **Jenkins Integration**: Extracting build logs with parallel stage support ([Setup Guide](JENKINS_INTEGRATION.md))
- Automatically extracting logs from all pipeline jobs/stages
- **API Posting**: Send structured logs to external API endpoints
- Storing logs with structured metadata for easy retrieval
- Handling failures with exponential backoff retry logic
- Supporting multiple pipeline types (main, child, merge request)
- **Parallel Execution**: Parse and extract parallel stage logs (Jenkins)

## Architecture

### System Architecture Diagram

```mermaid
graph TB
    subgraph "GitLab"
        GL[GitLab Server]
        PIPE[Pipeline Events]
    end

    subgraph "Webhook Server (Port 8000)"
        WH[Webhook Listener<br/>FastAPI Server]
        VAL[Webhook Validator<br/>Secret Token Check]
        PARSE[Pipeline Extractor<br/>Event Parser]
    end

    subgraph "Processing Layer"
        FETCH[Log Fetcher<br/>GitLab API Client]
        RETRY[Error Handler<br/>Retry Logic]
    end

    subgraph "Storage Layer"
        STORE[Storage Manager<br/>File System]
        META[Metadata Files<br/>JSON]
        LOGS[Log Files<br/>.log]
    end

    subgraph "Configuration"
        CONFIG[Config Loader<br/>Environment Variables]
    end

    GL -->|POST /webhook/gitlab| WH
    PIPE -.->|Pipeline Complete| GL
    WH --> VAL
    VAL -->|Valid| PARSE
    PARSE -->|Extract Info| FETCH
    FETCH -->|API Call| GL
    FETCH -.->|On Error| RETRY
    RETRY -.->|Retry| FETCH
    FETCH --> STORE
    STORE --> META
    STORE --> LOGS
    CONFIG -.->|Configuration| WH
    CONFIG -.->|Configuration| FETCH
    CONFIG -.->|Configuration| STORE

    style WH fill:#4CAF50
    style PARSE fill:#2196F3
    style FETCH fill:#FF9800
    style STORE fill:#9C27B0
    style RETRY fill:#F44336
```

### Data Flow Diagram

```mermaid
sequenceDiagram
    participant GitLab
    participant Webhook as Webhook Listener
    participant Extractor as Pipeline Extractor
    participant Fetcher as Log Fetcher
    participant Storage as Storage Manager
    participant FileSystem as File System

    GitLab->>Webhook: POST /webhook/gitlab (Pipeline Event)
    Webhook->>Webhook: Validate Secret Token
    Webhook->>Extractor: Extract Pipeline Info
    Extractor->>Extractor: Identify Pipeline Type
    Extractor->>Extractor: Filter Jobs to Fetch
    Extractor-->>Webhook: Pipeline Metadata

    Webhook->>Webhook: Queue Background Processing
    Webhook-->>GitLab: 200 OK (Acknowledged)

    Note over Webhook,Storage: Background Processing Starts

    Webhook->>Fetcher: Fetch Logs for Pipeline
    loop For Each Job
        Fetcher->>GitLab: GET /api/v4/projects/{id}/jobs/{job_id}/trace
        GitLab-->>Fetcher: Log Content
        alt API Call Fails
            Fetcher->>Fetcher: Retry with Exponential Backoff
        end
    end

    Fetcher-->>Storage: Job Logs + Metadata

    Storage->>FileSystem: Create Directory Structure
    Storage->>FileSystem: Save Log Files
    Storage->>FileSystem: Save/Update metadata.json
    FileSystem-->>Storage: Confirmation
    Storage-->>Webhook: Processing Complete
```

## Features

- **Multi-Source Support**:
  - **GitLab**: Full webhook integration for pipeline events
  - **Jenkins**: Build log extraction with parallel stage parsing ([Setup Guide](JENKINS_INTEGRATION.md))
- **Modern Async Server**: FastAPI-based async server with automatic API documentation
- **Interactive API Docs**: Automatic Swagger UI and ReDoc documentation at `/docs` and `/redoc`
- **Event Processing**: Identifies and processes different pipeline types (main, child, merge request)
- **Smart Filtering**: Only processes completed pipelines (success/failed)
- **Flexible Log Filtering**: Configure which logs to save based on:
  - Pipeline status (all, failed, success, running, canceled, skipped)
  - Project whitelist/blacklist (save specific projects or exclude noisy ones)
  - Job status (all, failed, success, canceled, skipped)
  - Optional metadata-only mode for tracking without storing logs
- **Log Extraction**:
  - GitLab: Fetches logs for all jobs in a pipeline via GitLab API
  - Jenkins: Fetches console logs and Blue Ocean stage data via Jenkins REST API
  - **Parallel Stage Support**: Automatically parses and extracts parallel execution blocks (Jenkins)
- **API Posting**: Send extracted logs to external API endpoints
  - Configurable modes: API only, dual (API + file), or file only
  - Bearer token authentication
  - Retry logic with exponential backoff
  - Request/response logging
- **Advanced Logging System**:
  - **Aligned log columns** for easy reading
  - **Project names** in logs instead of just IDs
  - **Request ID tracking** to trace pipeline processing across all log entries
  - **Pipe-delimited format** for easy parsing and analysis
  - **Multiple log files**: application.log, access.log, performance.log
  - **Configurable log levels** (DEBUG, INFO, WARNING, ERROR, CRITICAL)
  - **Automatic log rotation** with size limits
  - **Sensitive data masking** for tokens and secrets
- **Error Handling**:
  - Automatic retry with exponential backoff
  - Circuit breaker pattern for cascade failure prevention
  - Comprehensive error logging
- **Structured Storage**:
  - Organized by project name and ID for easy browsing
  - Directory structure: `{project-name}_{id}/pipeline_{id}/`
  - Metadata files with complete pipeline and job information
- **Security**: Optional webhook secret token validation
- **Background Processing**: Non-blocking webhook responses with FastAPI BackgroundTasks
- **Health Monitoring**: Health check and statistics endpoints
- **High Performance**: Async/await support for better concurrency
- **Production Ready**: Docker containerization, comprehensive monitoring, and testing

## Project Structure

```
extract-build-logs/
│
├── src/                          # Main application code
│   ├── __init__.py              # Package initialization
│   ├── webhook_listener.py     # FastAPI server and main entry point
│   ├── pipeline_extractor.py   # Pipeline event parsing and analysis
│   ├── log_fetcher.py           # GitLab API client for log retrieval
│   ├── storage_manager.py       # File system storage management
│   ├── config_loader.py         # Configuration and environment variables
│   └── error_handler.py         # Retry logic and error handling
│
├── tests/                        # Test suite
│   ├── __init__.py
│   ├── test_pipeline_extractor.py
│   ├── test_storage_manager.py
│   └── test_error_handler.py
│
├── logs/                         # Output directory for extracted logs
│   ├── {project-name}_{id}/     # Organized by project name and ID
│   │   └── pipeline_{id}/       # Then by pipeline
│   │       ├── metadata.json    # Pipeline and job metadata
│   │       └── job_{id}_{name}.log  # Individual job logs
│   ├── application.log          # Main application logs (aligned columns)
│   ├── access.log               # Webhook access logs
│   ├── performance.log          # Performance metrics
│   └── monitoring.db            # Monitoring database
│
├── config/                       # Configuration templates
│   └── webhook_setup.md         # GitLab webhook setup guide
│
├── .env.example                  # Environment variable template
├── requirements.txt              # Python dependencies
├── .gitignore                    # Git ignore rules
└── README.md                     # This file
```

### Directory Structure After Processing

```
logs/
├── project_123/
│   ├── pipeline_789/
│   │   ├── metadata.json
│   │   ├── job_456_build.log
│   │   ├── job_457_test_unit.log
│   │   └── job_458_deploy_production.log
│   └── pipeline_790/
│       ├── metadata.json
│       └── job_459_build.log
└── project_124/
    └── pipeline_791/
        ├── metadata.json
        └── job_460_test.log
```

## Module Documentation

### Module Connection Diagram

```mermaid
graph LR
    subgraph "Core Modules"
        WL[webhook_listener.py<br/>Main Server]
        PE[pipeline_extractor.py<br/>Event Parser]
        LF[log_fetcher.py<br/>API Client]
        SM[storage_manager.py<br/>File Storage]
    end

    subgraph "Support Modules"
        CL[config_loader.py<br/>Configuration]
        EH[error_handler.py<br/>Retry Logic]
    end

    WL -->|Uses| PE
    WL -->|Uses| LF
    WL -->|Uses| SM
    WL -->|Uses| CL
    LF -->|Uses| CL
    LF -->|Uses| EH
    SM -->|Uses| CL

    style WL fill:#4CAF50,stroke:#2E7D32,stroke-width:3px
    style PE fill:#2196F3
    style LF fill:#FF9800
    style SM fill:#9C27B0
    style CL fill:#607D8B
    style EH fill:#F44336
```

### Files & Folder Structure

#### Core Application Files

| File | Purpose | Key Responsibilities |
|------|---------|---------------------|
| `src/webhook_listener.py` | Main server entry point | - FastAPI async web server<br>- Webhook endpoint handling<br>- Background task processing<br>- Health & stats endpoints |
| `src/pipeline_extractor.py` | Event parsing | - Parse webhook payloads<br>- Identify pipeline types<br>- Filter jobs to process<br>- Generate summaries |
| `src/log_fetcher.py` | GitLab API client | - Fetch job logs<br>- Retrieve job/pipeline metadata<br>- Handle API authentication<br>- Manage API rate limits |
| `src/storage_manager.py` | File system storage | - Create directory structures<br>- Save log files<br>- Manage metadata<br>- Storage statistics |
| `src/config_loader.py` | Configuration management | - Load environment variables<br>- Validate settings<br>- Provide defaults<br>- Configuration object |
| `src/error_handler.py` | Error handling & retry | - Exponential backoff retry<br>- Circuit breaker pattern<br>- Custom exceptions<br>- Decorator utilities |

#### Test Files

| File | Tests For | Coverage |
|------|-----------|----------|
| `tests/test_api_poster.py` | API posting functionality | - Payload formatting<br>- HTTP requests (success/error)<br>- Timeout handling<br>- Retry logic<br>- Authentication<br>- Request logging |
| `tests/test_pipeline_extractor.py` | Pipeline extraction logic | - Type identification<br>- Job filtering<br>- Summary generation |
| `tests/test_storage_manager.py` | Storage operations | - File creation<br>- Metadata handling<br>- Statistics |
| `tests/test_error_handler.py` | Error handling | - Retry logic<br>- Backoff calculation<br>- Circuit breaker |

### Module Functions & Data Flow

#### 1. webhook_listener.py (Main Server)

**Purpose**: Receives webhooks and orchestrates log extraction

**Key Functions**:

```python
def init_app():
    """
    Initialize all application components.

    Data Flow: Environment → ConfigLoader → Component Initialization
    """

async def webhook_handler():
    """
    Process incoming webhook POST requests.

    Input: FastAPI Request with GitLab webhook payload
    Output: JSON response (200/401/400/500)

    Data Flow:
    Request → Validate Token → Extract Pipeline Info →
    Queue Processing → Return Response
    """

def process_pipeline_event(pipeline_info: Dict):
    """
    Background processing of pipeline logs.

    Input: Extracted pipeline information
    Output: Saved logs and metadata

    Data Flow:
    Pipeline Info → Fetch Jobs → For Each Job:
    (Fetch Log → Save Log) → Update Metadata
    """
```

**Dependencies**:
- `config_loader.Config`: Application configuration
- `pipeline_extractor.PipelineExtractor`: Event parsing
- `log_fetcher.LogFetcher`: API interactions
- `storage_manager.StorageManager`: File operations

#### 2. pipeline_extractor.py (Event Parser)

**Purpose**: Analyzes webhook events and identifies what to process

**Key Functions**:

```python
def extract_pipeline_info(webhook_payload: Dict) -> Dict:
    """
    Extract structured information from webhook.

    Input: Raw GitLab webhook JSON payload
    Output: Structured pipeline metadata dictionary

    Data Flow:
    Webhook JSON → Parse Attributes → Determine Type →
    Extract Jobs → Build Info Dictionary

    Output Format:
    {
        "pipeline_id": int,
        "project_id": int,
        "pipeline_type": str,  # main/child/merge_request
        "status": str,
        "builds": List[Dict]
    }
    """

def should_process_pipeline(pipeline_info: Dict) -> bool:
    """
    Business logic: determine if logs should be fetched.

    Input: Pipeline information
    Output: Boolean decision

    Logic:
    - Process if status in ["success", "failed"]
    - Skip if status in ["running", "pending"]
    """
```

**Dependencies**: None (pure logic)

#### 3. log_fetcher.py (API Client)

**Purpose**: Communicates with GitLab API to retrieve logs

**Key Functions**:

```python
@retry_on_failure(max_retries=3)
def fetch_job_log(project_id: int, job_id: int) -> str:
    """
    Fetch log content for specific job.

    Input: Project ID, Job ID
    Output: Raw log text

    API Call:
    GET /api/v4/projects/{project_id}/jobs/{job_id}/trace

    Error Handling:
    - 404: Return "[Log not available]"
    - 401/403: Raise authentication error
    - Other: Retry with exponential backoff
    """

def fetch_all_logs_for_pipeline(project_id: int,
                                 pipeline_id: int) -> Dict:
    """
    Fetch all logs for a pipeline.

    Input: Project ID, Pipeline ID
    Output: Dictionary mapping job_id to {details, log}

    Data Flow:
    Fetch Job List → For Each Job:
    (Fetch Details + Fetch Log) → Combine Results
    """
```

**Dependencies**:
- `config_loader.Config`: GitLab URL and token
- `error_handler.retry_on_failure`: Automatic retry

#### 4. storage_manager.py (File Storage)

**Purpose**: Persists logs and metadata to disk

**Key Functions**:

```python
def save_log(project_id: int, pipeline_id: int,
             job_id: int, job_name: str,
             log_content: str, job_details: Dict) -> Path:
    """
    Save job log to file system.

    Input: IDs, job name, log content, metadata
    Output: Path to saved file

    Data Flow:
    Create Pipeline Dir → Sanitize Filename →
    Write Log File → Update Metadata

    File Path:
    logs/project_{id}/pipeline_{id}/job_{id}_{name}.log
    """

def get_storage_stats() -> Dict:
    """
    Calculate storage statistics.

    Output:
    {
        "total_projects": int,
        "total_pipelines": int,
        "total_jobs": int,
        "total_size_mb": float
    }
    """
```

**Dependencies**: None (pure I/O)

#### 5. config_loader.py (Configuration)

**Purpose**: Centralized configuration management

**Key Functions**:

```python
@staticmethod
def load() -> Config:
    """
    Load configuration from environment.

    Input: Environment variables
    Output: Config dataclass object

    Required:
    - GITLAB_URL
    - GITLAB_TOKEN

    Optional (with defaults):
    - WEBHOOK_PORT (8000)
    - LOG_OUTPUT_DIR (./logs)
    - RETRY_ATTEMPTS (3)
    """
```

**Dependencies**: None

#### 6. error_handler.py (Retry Logic)

**Purpose**: Robust error handling with retries

**Key Functions**:

```python
def retry_with_backoff(func: Callable, *args, **kwargs) -> Any:
    """
    Execute function with exponential backoff retry.

    Input: Function to execute + arguments
    Output: Function result or RetryExhaustedError

    Retry Strategy:
    Attempt 1: Immediate
    Attempt 2: Wait base_delay (2s)
    Attempt 3: Wait base_delay * 2 (4s)
    Attempt 4: Wait base_delay * 4 (8s)
    """

@decorator
def retry_on_failure(max_retries=3, base_delay=2.0):
    """
    Decorator for automatic retry.

    Usage:
    @retry_on_failure(max_retries=3)
    def my_function():
        # May fail transiently
        pass
    """
```

**Dependencies**: None

## Data Flow

### Complete Event Processing Flow

```mermaid
flowchart TD
    Start([GitLab Pipeline Completes]) --> Webhook[Webhook POST to /webhook]
    Webhook --> ValidateSecret{Validate<br/>Secret Token?}
    ValidateSecret -->|Invalid| Reject[Return 401 Unauthorized]
    ValidateSecret -->|Valid| CheckEvent{Event Type =<br/>Pipeline Hook?}
    CheckEvent -->|No| Ignore[Return 200 Ignored]
    CheckEvent -->|Yes| ParsePayload[Extract Pipeline Info]

    ParsePayload --> DetermineType[Determine Pipeline Type]
    DetermineType --> MainType[Main Pipeline]
    DetermineType --> ChildType[Child Pipeline]
    DetermineType --> MRType[Merge Request Pipeline]

    MainType --> CheckStatus{Status =<br/>success/failed?}
    ChildType --> CheckStatus
    MRType --> CheckStatus

    CheckStatus -->|No| Skip[Return 200 Skipped]
    CheckStatus -->|Yes| Queue[Queue Background Processing]
    Queue --> Respond[Return 200 Success]

    Queue --> Background[Background Thread Starts]
    Background --> FetchJobList[Fetch All Jobs in Pipeline]

    FetchJobList --> LoopJobs{For Each Job}
    LoopJobs --> FetchLog[Fetch Job Log via API]
    FetchLog --> APICall{API Call<br/>Successful?}

    APICall -->|No| RetryCheck{Retries<br/>Remaining?}
    RetryCheck -->|Yes| Wait[Wait with Backoff]
    Wait --> FetchLog
    RetryCheck -->|No| LogError[Log Error]

    APICall -->|Yes| SaveLog[Save Log to File]
    SaveLog --> UpdateMeta[Update Metadata]
    UpdateMeta --> LoopJobs

    LoopJobs -->|All Done| Complete[Processing Complete]
    LogError --> LoopJobs

    style Start fill:#4CAF50
    style Webhook fill:#2196F3
    style Queue fill:#FF9800
    style Complete fill:#4CAF50
    style Reject fill:#F44336
    style LogError fill:#F44336
```

### Data Transformations

```
GitLab Webhook Payload
         ↓
pipeline_extractor.extract_pipeline_info()
         ↓
Structured Pipeline Info
{
  pipeline_id: 789,
  project_id: 123,
  pipeline_type: "main",
  status: "success",
  builds: [...]
}
         ↓
log_fetcher.fetch_all_logs_for_pipeline()
         ↓
Logs Dictionary
{
  456: {
    details: {name: "build", status: "success"},
    log: "Build started...\nBuild complete"
  }
}
         ↓
storage_manager.save_log()
         ↓
File System
logs/project_123/pipeline_789/job_456_build.log
logs/project_123/pipeline_789/metadata.json
```

## Installation

### Prerequisites

- Python 3.8 or higher
- GitLab instance (GitLab.com or self-hosted)
- GitLab Personal Access Token with `api` scope
- Network connectivity to GitLab API

### Step 1: Clone Repository

```bash
git clone <repository-url>
cd extract-build-logs
```

### Step 2: Create Virtual Environment

```bash
# Create virtual environment
python3 -m venv venv

# Activate virtual environment
# On Linux/Mac:
source venv/bin/activate
# On Windows:
venv\Scripts\activate
```

### Step 3: Install Dependencies

```bash
pip install -r requirements.txt
```

### Step 4: Configure Environment

```bash
# Copy environment template
cp .env.example .env

# Edit .env with your settings
nano .env  # or your preferred editor
```

### Step 5: Create GitLab Access Token

1. Go to GitLab → Profile → Access Tokens
2. Create a new token with `api` scope
3. Copy the token and add it to `.env`

---

## Docker Deployment

**Recommended for production deployments.** Docker provides isolated environment, easy deployment, and automatic restarts.

### Quick Start with Docker

**Prerequisites:**
```bash
# Check Docker is installed
docker --version

# Create .env file with your credentials
cp .env.example .env
nano .env  # Edit GITLAB_URL and GITLAB_TOKEN
```

**Build and Run:**
```bash
# Build Docker image
./manage_container.py build

# Start container
./manage_container.py start

# Verify it's running
./manage_container.py status
```

**Your webhook is now available at:** `http://your-server:8000/webhook`

### Docker Commands

**Container Lifecycle:**
```bash
# Build/rebuild image
./manage_container.py build

# Start container (creates if doesn't exist)
./manage_container.py start

# Stop container
./manage_container.py stop

# Restart container
./manage_container.py restart

# Remove container (keeps logs)
./manage_container.py remove
```

**Monitoring:**
```bash
# View status and resource usage
./manage_container.py status

# View live logs
./manage_container.py logs

# View monitoring dashboard
./manage_container.py monitor

# Export monitoring data
./manage_container.py export data.csv
```

**Maintenance:**
```bash
# Test webhook endpoint
./manage_container.py test

# Execute commands inside container
docker exec bfa-gitlab-pipeline-extractor <command>

# View all commands
./manage_container.py --help
```

### Docker Monitoring

**Check Health:**
```bash
curl http://localhost:8000/health
# {"status":"healthy","service":"gitlab-log-extractor","version":"1.0.0"}
```

**View Statistics:**
```bash
# Container resource usage
./manage_container.py status

# Monitoring dashboard
./manage_container.py monitor --hours 24

# API endpoints (same as non-Docker)
curl http://localhost:8000/monitor/summary
```

**Data Persistence:**
- Logs are stored in `./logs/` on the host
- Monitoring database: `./logs/monitoring.db`
- Configuration: `.env` file (mounted read-only)
- **Data persists** even when container is removed

**Benefits:**
- ✓ Isolated environment
- ✓ Automatic restart on failure
- ✓ No Python virtual environment needed
- ✓ Easy updates (rebuild + restart)
- ✓ Resource limits enforced
- ✓ Consistent across environments

**For detailed Docker operations, see:** [OPERATIONS.md - Docker Operations](OPERATIONS.md#docker-operations)

---

## Configuration

### Environment Variables

Edit `.env` file:

```bash
# ============================================================================
# REQUIRED SETTINGS
# ============================================================================
GITLAB_URL=https://gitlab.com
GITLAB_TOKEN=your_gitlab_token_here

# ============================================================================
# OPTIONAL SETTINGS
# ============================================================================
WEBHOOK_PORT=8000
WEBHOOK_SECRET=your_webhook_secret
LOG_OUTPUT_DIR=./logs
RETRY_ATTEMPTS=3
RETRY_DELAY=2
LOG_LEVEL=INFO

# ============================================================================
# LOG FILTERING CONFIGURATION (New!)
# ============================================================================
# Which pipeline statuses to save logs for
# Options: all, failed, success, running, canceled, skipped
# Multiple values: failed,canceled,skipped
# Default: all (saves logs from all pipelines)
LOG_SAVE_PIPELINE_STATUS=all

# Which projects to save logs for (comma-separated project IDs)
# Leave empty to save all projects
# Example: 123,456,789
LOG_SAVE_PROJECTS=

# Which projects to exclude from logging (comma-separated project IDs)
# Only used if LOG_SAVE_PROJECTS is empty
# Example: 999,888
LOG_EXCLUDE_PROJECTS=

# Which job statuses to save logs for within a pipeline
# Options: all, failed, success, canceled, skipped
# Default: all (saves logs from all jobs)
LOG_SAVE_JOB_STATUS=all

# Save pipeline metadata even if logs are filtered out
# Useful for tracking all pipelines even if only storing failed logs
# Options: true, false
# Default: true
LOG_SAVE_METADATA_ALWAYS=true

# ============================================================================
# API POSTING CONFIGURATION (New!)
# ============================================================================
# BFA Configuration (required for API posting)
BFA_HOST=bfa-server.example.com
BFA_SECRET_KEY=your_bfa_secret_key

# API POSTING CONFIGURATION
# ============================================================================
# Enable API posting for pipeline logs (instead of or in addition to file storage)
# When enabled, API endpoint is auto-constructed as: http://BFA_HOST:8000/api/analyze
API_POST_ENABLED=false
API_POST_TIMEOUT=30
API_POST_RETRY_ENABLED=true
API_POST_SAVE_TO_FILE=false  # false = API only, true = dual mode (API + file)
```

**Common Filtering Scenarios:**

```bash
# 1. Save only failed pipeline logs (reduce storage by ~90%)
LOG_SAVE_PIPELINE_STATUS=failed,canceled
LOG_SAVE_METADATA_ALWAYS=true

# 2. Save logs only for specific projects
LOG_SAVE_PROJECTS=123,456,789

# 3. Save all pipelines but only failed job logs
LOG_SAVE_PIPELINE_STATUS=all
LOG_SAVE_JOB_STATUS=failed,canceled

# 4. Exclude noisy test projects
LOG_EXCLUDE_PROJECTS=999,888
```

### GitLab Webhook Setup

1. Navigate to your GitLab project
2. Go to **Settings → Webhooks**
3. Add webhook URL: `http://your-server:8000/webhook`
4. Set secret token (same as `WEBHOOK_SECRET` in `.env`)
5. Enable **Pipeline events** only
6. Click **Add webhook**
7. Test with **Test → Pipeline events**

See [config/webhook_setup.md](config/webhook_setup.md) for detailed instructions.

### API Posting (New!)

Instead of (or in addition to) saving logs to files, you can configure the system to POST pipeline logs to an external API endpoint for centralized storage and processing.

**Key Features:**
- **Batched Requests**: One API POST per pipeline with all jobs included
- **Authentication**: Bearer token authentication support
- **Retry Logic**: Automatic retry with exponential backoff
- **Fallback**: Falls back to file storage if API fails
- **Dual Mode**: Can save to both API and files simultaneously
- **Request Logging**: All API requests/responses logged to `logs/api-requests.log`

**Configuration:**

```bash
# Configure BFA server (required for API posting)
BFA_HOST=bfa-server.example.com
BFA_SECRET_KEY=your_bfa_secret_key

# Enable API posting
# API endpoint auto-constructed as: http://BFA_HOST:8000/api/analyze
API_POST_ENABLED=true

# Set timeout (default: 30 seconds)
API_POST_TIMEOUT=30

# Enable retry logic (default: true)
API_POST_RETRY_ENABLED=true

# Dual mode: save to both API and files (default: false)
API_POST_SAVE_TO_FILE=false
```

**Operating Modes:**

1. **API Only** (default when `API_POST_ENABLED=true`):
   - `API_POST_ENABLED=true`
   - `API_POST_SAVE_TO_FILE=false`
   - Logs are POSTed to API only (file storage as fallback if API fails)

2. **Dual Mode** (API + File):
   - `API_POST_ENABLED=true`
   - `API_POST_SAVE_TO_FILE=true`
   - Logs are saved to both API and files

3. **File Only** (traditional):
   - `API_POST_ENABLED=false`
   - Logs are saved to files only

**API Request Format:**

The system POSTs JSON payloads with the following structure:

```json
{
  "pipeline_id": 12345,
  "project_id": 123,
  "project_name": "my-app",
  "status": "success",
  "ref": "main",
  "sha": "abc123...",
  "pipeline_type": "main",
  "created_at": "2024-01-01T00:00:00Z",
  "duration": 120.5,
  "user": {...},
  "stages": ["build", "test", "deploy"],
  "jobs": [
    {
      "job_id": 456,
      "job_name": "build:production",
      "log_content": "Full build logs...",
      "status": "success",
      "stage": "build",
      "duration": 60.2,
      ...
    },
    ...
  ]
}
```

**Request Logging:**

All API requests and responses are logged to `logs/api-requests.log`:

```
[2024-01-01 00:02:05] PIPELINE_ID=12345 PROJECT_ID=123 URL=https://api.example.com/logs STATUS=200 DURATION=1250ms RESPONSE={"success": true}
```

**See also:** [API_POSTING.md](API_POSTING.md) for complete API posting documentation.

### Configuration Loading Flow

Understanding how configuration is loaded, validated, and displayed throughout the application.

#### Overview

Configuration flows through three stages:
1. **Loading**: Environment variables → Config object
2. **Validation**: Verify required values and formats
3. **Display**: Show configuration at startup and in management tools

#### Detailed Flow

**1. Configuration Loading** (`src/config_loader.py`)

**Class:** `ConfigLoader`
**Method:** `ConfigLoader.load()` (lines 82-237)

```python
# Entry point
config = ConfigLoader.load()
```

**Process:**
- **Load from environment** using `os.getenv()` with defaults
- **Create Config dataclass** (lines 41-77) with all settings
- **Return validated Config object**

**Key Configuration Variables:**

| Variable | Default | Loaded In | Used By |
|----------|---------|-----------|---------|
| `GITLAB_URL` | (required) | line 98 | `log_fetcher.py`, `webhook_listener.py` |
| `GITLAB_TOKEN` | (required) | line 99 | `log_fetcher.py` |
| `BFA_HOST` | None | line 180 | Auto-constructs API endpoint: `http://BFA_HOST:8000/api/analyze` |
| `BFA_SECRET_KEY` | None | line 181 | `token_manager.py`, `api_poster.py` (Bearer auth) |
| `WEBHOOK_PORT` | 8000 | line 100 | `webhook_listener.py` |
| `LOG_LEVEL` | INFO | line 104 | `logging_config.py` |

**Config Dataclass Fields:**
```python
@dataclass
class Config:
    gitlab_url: str                      # GitLab instance URL
    gitlab_token: str                    # GitLab API token
    webhook_port: int                    # Server port (default: 8000)
    webhook_secret: Optional[str]        # Webhook validation secret
    log_output_dir: str                  # Log storage directory
    retry_attempts: int                  # API retry attempts
    retry_delay: int                     # Retry delay in seconds
    log_level: str                       # Logging level
    log_save_pipeline_status: str        # Pipeline filter
    log_save_job_status: str             # Job status filter
    log_save_projects: str               # Project whitelist
    log_exclude_projects: str            # Project blacklist
    log_save_metadata_always: bool       # Save metadata flag
    api_post_enabled: bool               # Enable API posting
    api_post_url: Optional[str]          # API endpoint URL
    api_post_auth_token: Optional[str]   # API Bearer token
    api_post_timeout: int                # Request timeout
    api_post_retry_enabled: bool         # Enable API retries
    api_post_save_to_file: bool          # Dual mode flag
    jenkins_enabled: bool                # Enable Jenkins support
    jenkins_url: Optional[str]           # Jenkins URL
    jenkins_user: Optional[str]          # Jenkins username
    jenkins_api_token: Optional[str]     # Jenkins API token
    jenkins_webhook_secret: Optional[str] # Jenkins webhook secret
    bfa_server: Optional[str]            # BFA server URL for token API
    bfa_secret_key: Optional[str]        # BFA JWT signing key
```

**2. Configuration Validation** (`src/config_loader.py`)

**Method:** `ConfigLoader.validate()` (lines 240-259)

**Checks:**
- ✓ GitLab URL format (must start with http:// or https://)
- ✓ GitLab token length (minimum 10 characters)
- ✓ Port range (1-65535)
- ✓ Log level validity (DEBUG, INFO, WARNING, ERROR, CRITICAL)
- ✓ API POST URL required when `API_POST_ENABLED=true`
- ✓ API POST URL format validation

**Validation Location in Code:**
```python
# config_loader.py lines 182-196
if not 1 <= webhook_port <= 65535:
    raise ValueError(f"Invalid WEBHOOK_PORT: {webhook_port}")

if log_level not in ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']:
    raise ValueError(f"Invalid LOG_LEVEL: {log_level}")

if api_post_enabled:
    if not bfa_host:
        raise ValueError("BFA_HOST is required when API_POST_ENABLED is true")
    # Note: BFA_SECRET_KEY is optional - if set, will be used for Bearer token authentication
```

**3. Configuration Display on Startup** (`src/webhook_listener.py`)

**Function:** `lifespan()` context manager (lines 143-223)

**Display Sequence:**
```python
# Lines 147-164: Basic configuration
logger.info("Configuration loaded successfully")
logger.debug(f"GitLab URL: {config.gitlab_url}")
logger.debug(f"Webhook Port: {config.webhook_port}")
logger.debug(f"Log Output Directory: {config.log_output_dir}")
logger.debug(f"Log Level: {config.log_level}")
logger.debug(f"Retry Attempts: {config.retry_attempts}")

# Lines 160-175: Masked tokens and BFA configuration (security)
masked_token = mask_token(config.gitlab_token)
logger.debug(f"GitLab Token: {masked_token}")

# BFA configuration logging
if config.bfa_server:
    logger.debug(f"BFA Server: {config.bfa_server}")
else:
    logger.debug("BFA Server: Not Set")

if config.bfa_secret_key:
    masked_bfa_key = mask_token(config.bfa_secret_key)
    logger.debug(f"BFA Secret Key: {masked_bfa_key}")
else:
    logger.debug("BFA Secret Key: Not Set")
    logger.error("BFA_SECRET_KEY is not set - JWT token generation disabled")

# Lines 201-210: API posting configuration
if config.api_post_enabled:
    logger.info("API posting is ENABLED")
    logger.debug(f"API endpoint: {config.api_post_url}")
    logger.debug(f"API timeout: {config.api_post_timeout}s")
```

**Startup Log Example (with BFA configured):**
```
======================================================================
GitLab Pipeline Log Extractor - Initializing
======================================================================
INFO  | Configuration loaded successfully
DEBUG | GitLab URL: https://gitlab.example.com
DEBUG | Webhook Port: 8000
DEBUG | Log Output Directory: ./logs
DEBUG | Log Level: DEBUG
DEBUG | GitLab Token: glpat-xxxx...xxxx
DEBUG | BFA Server: http://bfa-host:8000
DEBUG | BFA Secret Key: secret-xxxx...xxxx
INFO  | Initializing components...
DEBUG | Pipeline extractor initialized
DEBUG | Log fetcher initialized
DEBUG | Storage manager initialized
DEBUG | Pipeline monitor initialized
DEBUG | BFA JWT token manager initialized
INFO  | API posting is ENABLED
DEBUG | API endpoint: https://api.example.com/logs
```

**4. Configuration Display in Management Tool** (`manage_container.py`)

**Function:** `review_config()` (lines 365-528)

Displays configuration in organized tables:

**Tables Displayed:**
1. **Configuration Review** (lines 398-413)
   - GitLab URL, Token, Webhook Port, Secret
   - Log Level, Directory, Retry settings

2. **Log Filtering Settings** (lines 416-436)
   - Pipeline/Job status filters
   - Project whitelist/blacklist

3. **API Posting Configuration** (lines 438-453)
   - Only shown if `API_POST_ENABLED=true`
   - API URL, Auth Token, Timeout, Retry

4. **Jenkins Integration** (lines 455-469)
   - Only shown if `JENKINS_ENABLED=true`
   - Jenkins URL, User, API Token, Secret

5. **BFA JWT Token Generation** (lines 471-486)
   - BFA Server URL
   - BFA Secret Key (masked)
   - Token endpoint (/api/token)
   - Usage description
   - Warning status if BFA_SECRET_KEY not set

**Display Command:**
```bash
# Show full configuration
./manage_container.py config

# Or during container start
./manage_container.py start
```

**Example Output (with BFA configured):**
```
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Setting                     ┃ Value                                  ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ BFA Server                  │ http://bfa-host:8000                   │
│ BFA Secret Key              │ secret-a...k (8 chars)                 │
│ Token Endpoint              │ /api/token                             │
│ Token Usage                 │ Dynamic JWT for API authentication     │
└─────────────────────────────┴────────────────────────────────────────┘
```

**Example Output (without BFA configured):**
```
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Setting                     ┃ Value                                  ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ BFA Server                  │ Not Set                                │
│ BFA Secret Key              │ Not Set                                │
│ Token Endpoint              │ /api/token                             │
│ Token Usage                 │ Dynamic JWT for API authentication     │
│ Status                      │ ⚠ Token generation disabled            │
└─────────────────────────────┴────────────────────────────────────────┘
```

#### Configuration Debug Commands

**Test Configuration Loading:**
```bash
# Test config_loader.py directly
python src/config_loader.py

# Expected output:
# Configuration loaded successfully!
# GitLab URL: https://gitlab.example.com
# Webhook Port: 8000
# Log Output Directory: ./logs
```

**View Current Configuration:**
```bash
# Using management tool
./manage_container.py config

# Check environment file
cat .env

# Verify specific values
grep "BFA_HOST" .env
grep "BFA_SECRET_KEY" .env
```

**Verify Configuration at Runtime:**
```bash
# Check startup logs
tail -n 100 logs/application.log | grep -A 20 "Configuration loaded"

# Monitor real-time
tail -f logs/application.log | grep "config"
```

**Configuration Troubleshooting:**
```bash
# Test with different log levels
LOG_LEVEL=DEBUG python src/config_loader.py

# Validate .env file format
python -c "from dotenv import load_dotenv; load_dotenv(); print('✓ .env file is valid')"

# Check for missing required variables
python -c "
import os
from dotenv import load_dotenv
load_dotenv()
required = ['GITLAB_URL', 'GITLAB_TOKEN']
missing = [v for v in required if not os.getenv(v)]
if missing:
    print(f'❌ Missing: {missing}')
else:
    print('✓ All required variables set')
"
```

#### BFA Configuration: BFA_SERVER & BFA_SECRET_KEY vs GITLAB_TOKEN

**Important Distinction:**

| Token/Setting | Purpose | Used By | Required |
|---------------|---------|---------|----------|
| **GITLAB_TOKEN** | Authenticate with GitLab API to fetch logs | `log_fetcher.py` | ✅ Yes |
| **BFA_SERVER** | API server URL to obtain BFA_SECRET_KEY token | `token_manager.py` | ❌ No (optional) |
| **BFA_SECRET_KEY** | Sign JWT tokens for API authentication | `token_manager.py` | ❌ No (if not set, /api/token endpoint disabled) |

**Key Changes:**
- ⚠️ **No fallback**: BFA_SECRET_KEY does NOT fallback to GITLAB_TOKEN anymore
- ⚠️ **Separate concerns**: GITLAB_TOKEN and BFA_SECRET_KEY are completely separate
- ⚠️ **Error logging**: If BFA_SECRET_KEY is not set, errors are logged and JWT token generation is disabled

**Configuration:**
```bash
# .env file
GITLAB_TOKEN=glpat-xxxxxxxxxxxxxxxxxxxx       # For GitLab API access (REQUIRED)
BFA_SERVER=http://bfa-host:8000               # API server to get BFA_SECRET_KEY (optional)
BFA_SECRET_KEY=your_strong_random_secret      # For JWT signing (optional)

# If BFA_SECRET_KEY is not set:
# - JWT token generation via /api/token endpoint will be disabled
# - Errors will be logged on startup
# - API calls to /api/token will return 503 Service Unavailable
```

**Obtaining BFA_SECRET_KEY:**

**Option 1: Get from BFA_SERVER (if you have one)**
```bash
# Set your BFA server host
BFA_HOST="bfa-server.example.com"

# Make API call to BFA_SERVER to obtain token
curl -X POST http://${BFA_HOST}:8000/api/token

# Response format:
# {
#   "token": "<TOKEN>"
# }

# Extract token and set in .env
TOKEN=$(curl -s -X POST http://${BFA_HOST}:8000/api/token | jq -r '.token')
echo "BFA_SECRET_KEY=${TOKEN}" >> .env
```

**Option 2: Generate manually**
```bash
# Generate a random secure token
python -c "import secrets; print(secrets.token_urlsafe(32))"

# Or add directly to .env
echo "BFA_SECRET_KEY=$(python -c 'import secrets; print(secrets.token_urlsafe(32))')" >> .env
```

**Startup Behavior:**

With BFA_SECRET_KEY set:
```
DEBUG | BFA Server: http://bfa-host:8000
DEBUG | BFA Secret Key: secret-xxxx...xxxx
DEBUG | BFA JWT token manager initialized
```

Without BFA_SECRET_KEY:
```
DEBUG | BFA Server: Not Set
DEBUG | BFA Secret Key: Not Set
ERROR | BFA_SECRET_KEY is not set - JWT token generation disabled
ERROR | BFA_SERVER is also not set - cannot obtain BFA_SECRET_KEY from server
```

**Security Best Practice:**
- ✅ Use different secrets for different purposes (GITLAB_TOKEN ≠ BFA_SECRET_KEY)
- ✅ Never use GITLAB_TOKEN for JWT signing
- ✅ Generate strong random secrets: `python -c "import secrets; print(secrets.token_urlsafe(32))"`
- ✅ Never commit secrets to version control
- ✅ Rotate secrets periodically
- ✅ Use BFA_SERVER to centrally manage BFA_SECRET_KEY distribution

## Usage

### Start the Server

```bash
# Method 1: Using the main script (recommended)
python src/webhook_listener.py

# Method 2: Using uvicorn directly (more control)
uvicorn src.webhook_listener:app --host 0.0.0.0 --port 8000

# Method 3: With auto-reload for development
uvicorn src.webhook_listener:app --reload --host 0.0.0.0 --port 8000
```

### Verify Server is Running

```bash
# Check health endpoint
curl http://localhost:8000/health

# Expected response:
# {"status":"healthy","service":"gitlab-log-extractor","version":"1.0.0"}
```

### Access API Documentation

FastAPI automatically generates interactive API documentation:

```bash
# Swagger UI (interactive)
http://localhost:8000/docs

# ReDoc (alternative documentation)
http://localhost:8000/redoc
```

### Monitor Logs

```bash
# Watch application logs (aligned columns for easy reading)
tail -f logs/application.log

# Watch access logs
tail -f logs/access.log

# Watch performance logs
tail -f logs/performance.log

# Watch extracted logs directory
watch -n 5 'ls -lah logs/'

# Filter logs by request ID (trace a single pipeline)
grep "4729a324" logs/application.log

# Filter logs by project name
grep "my-project" logs/application.log
```

**Example Log Output (Aligned Columns):**
```
2025-10-31 06:15:13.670 | INFO     | src.webhook_listener           | 4729a324 | Request ID 4729a324 tracking pipeline 1061175 from project 'my-app' (ID: 123)
2025-10-31 06:15:13.670 | INFO     | src.pipeline_extractor         | 4729a324 | Extracted info for pipeline 1061175 from project 'my-app' (type: main, status: success)
2025-10-31 06:15:13.700 | INFO     | src.webhook_listener           | 4729a324 | Starting pipeline log extraction for 'my-app'
```

### View Storage Statistics

```bash
curl http://localhost:8000/stats
```

## Monitoring & Tracking

The system automatically tracks **every webhook request** and processing status. See [OPERATIONS.md](OPERATIONS.md) (Part 2: Monitoring & Tracking) for complete documentation.

### Quick Start

```bash
# View monitoring dashboard
python scripts/monitor_dashboard.py

# Show recent 100 requests
python scripts/monitor_dashboard.py --recent 100

# Export to CSV
python scripts/monitor_dashboard.py --export pipeline_data.csv
```

### What is Tracked

- ✓ Total requests received
- ✓ Processing status (queued, processing, completed, failed, skipped)
- ✓ Success/failure rates
- ✓ Processing times
- ✓ Job counts per pipeline
- ✓ Error messages
- ✓ Pipeline types

### Monitoring API Endpoints

```bash
# Get summary statistics
curl http://localhost:8000/monitor/summary?hours=24

# Get recent requests
curl http://localhost:8000/monitor/recent?limit=50

# Get specific pipeline details
curl http://localhost:8000/monitor/pipeline/12345

# Download CSV export
curl -O http://localhost:8000/monitor/export/csv?hours=24
```

### Database Location

All monitoring data is stored in: `logs/monitoring.db`

You can query it directly with SQL or use the provided CLI dashboard.

**For complete debugging, monitoring documentation, and examples, see [OPERATIONS.md](OPERATIONS.md)**

## API Documentation

### Webhook Events

#### POST /webhook/gitlab

Receives GitLab pipeline webhook events.

**Headers**:
- `X-Gitlab-Event`: Event type (must be "Pipeline Hook")
- `X-Gitlab-Token`: Webhook secret token
- `Content-Type`: application/json

**Request Body**: GitLab pipeline webhook payload

**Responses**:
- `200 OK`: Successfully processed or queued
- `400 Bad Request`: Invalid JSON payload
- `401 Unauthorized`: Invalid secret token
- `500 Internal Server Error`: Processing error

**Example Response**:
```json
{
  "status": "success",
  "message": "Pipeline logs queued for extraction",
  "pipeline_id": 12345,
  "project_id": 123
}
```

#### GET /health

Health check endpoint.

**Response**:
```json
{
  "status": "healthy",
  "service": "gitlab-log-extractor",
  "version": "1.0.0"
}
```

#### GET /stats

Get storage statistics.

**Response**:
```json
{
  "total_projects": 5,
  "total_pipelines": 23,
  "total_jobs": 156,
  "total_size_bytes": 45678901,
  "total_size_mb": 43.56
}
```

## Testing

### Test Suite Overview

The project includes comprehensive unit tests covering core functionality:

| Test Module | Tests | Coverage | Focus Area |
|-------------|-------|----------|------------|
| `test_api_poster.py` | 20 | 88% | API posting, timeouts, errors, retry logic |
| `test_error_handler.py` | 12 | 84% | Retry with backoff, circuit breaker |
| `test_pipeline_extractor.py` | 8 | 86% | Pipeline data extraction, filtering |
| `test_storage_manager.py` | 10 | 78% | File storage, metadata management |
| **Total** | **50** | **30%** | **Overall coverage** |

### Run All Tests

```bash
# Run all tests
pytest tests/

# Run with coverage report
pytest --cov=src tests/ --cov-report=term-missing

# Run specific test file
pytest tests/test_api_poster.py -v

# Run tests for API posting only
pytest tests/test_api_poster.py

# Run with coverage for specific module
pytest tests/test_api_poster.py --cov=src/api_poster.py
```

### API Poster Test Coverage

The `test_api_poster.py` module includes comprehensive tests for:

**Success Scenarios:**
- ✓ Successful API POST with authentication
- ✓ POST without authentication token
- ✓ Large payload handling
- ✓ Slow/late responses (within timeout)

**Error Scenarios:**
- ✓ 400 Bad Request errors
- ✓ 500 Internal Server errors
- ✓ 503 Service Unavailable errors
- ✓ Connection errors
- ✓ Timeout errors

**Retry Logic:**
- ✓ Retry with exponential backoff
- ✓ Retry exhaustion handling

**Data & Logging:**
- ✓ Payload formatting and structure
- ✓ Request/response logging
- ✓ Long response truncation

### Manual Testing

```bash
# Test webhook endpoint with curl
curl -X POST http://localhost:8000/webhook/gitlab \
  -H "Content-Type: application/json" \
  -H "X-Gitlab-Event: Pipeline Hook" \
  -H "X-Gitlab-Token: your_secret" \
  -d '{"object_kind":"pipeline","object_attributes":{"id":123,"status":"success"}}'
```

## CI/CD Pipeline

The project includes comprehensive GitLab CI/CD configuration for automated testing and code quality checks.

### Pipeline Stages

The CI/CD pipeline runs on every push and consists of three stages:

#### 1. Lint Stage (Code Quality)

**Flake8** - PEP 8 compliance and code style:
```bash
flake8 src/ tests/ --max-line-length=120
```

**Pylint** - Comprehensive linting (advisory):
```bash
pylint src/ --max-line-length=120
```

#### 2. Test Stage

**Pytest** - Unit tests execution:
```bash
pytest tests/ --ignore=tests/test_manage_container.py -v
```

#### 3. Coverage Stage

**Coverage Report** - Code coverage analysis:
```bash
pytest tests/ --cov=src --cov-report=html --cov-report=xml
```

- Coverage threshold tracking
- HTML coverage report artifacts
- Cobertura XML for GitLab integration
- Coverage badge support

### Local CI Testing

Run the same checks locally before pushing:

```bash
# Install dev dependencies
pip install -r requirements.txt

# Run linters
flake8 src/ tests/
pylint src/

# Run tests with coverage
pytest tests/ --cov=src --cov-report=html --cov-report=term-missing

# View HTML coverage report
open coverage_html/index.html
```

### Configuration Files

| File | Purpose |
|------|---------|
| `.gitlab-ci.yml` | CI/CD pipeline configuration |
| `.flake8` | Flake8 linter settings |
| `.pylintrc` | Pylint configuration |
| `pyproject.toml` | pytest and coverage settings |

### CI/CD Artifacts

The pipeline generates the following artifacts:

- **Coverage Reports**: HTML and XML formats (30 days retention)
- **Test Results**: JUnit XML for GitLab test reporting
- **Badges**: Coverage percentage for README

### Pipeline Behavior

- **Lint Stage**: Must pass (except pylint which is advisory)
- **Test Stage**: Must pass (all tests must succeed)
- **Coverage Stage**: Must pass, reports coverage percentage

## Troubleshooting

### Server Won't Start

**Problem**: Port already in use

**Solution**:
```bash
# Check what's using the port
lsof -i :8000

# Kill the process or change WEBHOOK_PORT in .env
```

### Webhook Returns 401

**Problem**: Secret token mismatch

**Solution**:
- Verify `WEBHOOK_SECRET` in `.env` matches GitLab webhook secret
- Check for extra spaces or newlines

### Logs Not Being Saved

**Problem**: Permission denied

**Solution**:
```bash
# Check directory permissions
ls -la logs/

# Create directory with proper permissions
mkdir -p logs
chmod 755 logs
```

### API Calls Failing

**Problem**: Invalid GitLab token

**Solution**:
- Verify token has `api` scope
- Check token hasn't expired
- Ensure `GITLAB_URL` is correct

## Development

### Adding New Features

1. Create new module in `src/`
2. Add tests in `tests/`
3. Update module documentation in README
4. Update architecture diagrams if needed

## Contributing

1. Fork the repository
2. Create feature branch
3. Commit changes
4. Push to branch
5. Open Pull Request

---