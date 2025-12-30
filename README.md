# GitLab & Jenkins Pipeline Log Extraction System

A production-ready webhook server that automatically extracts and stores pipeline logs from GitLab and Jenkins with comprehensive error handling, retry logic, and structured metadata. Supports parallel execution blocks and API posting.

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
  - [System Architecture Diagram](#system-architecture-diagram)
  - [Data Flow Diagram](#data-flow-diagram)
- [Quick Setup](#quick-setup)
  - [Prerequisites](#prerequisites)
  - [Docker Deployment (Recommended)](#docker-deployment-recommended)
  - [Manual Installation](#manual-installation)
- [Configuration](#configuration)
- [Complete Documentation](#complete-documentation)

## Overview

This system provides a complete solution for:
- **GitLab Integration**: Receiving webhook events for pipeline completion
- **Jenkins Integration**: Extracting build logs with parallel stage support
- Automatically extracting logs from all pipeline jobs/stages
- **API Posting**: Send structured logs to external API endpoints
- Storing logs with structured metadata for easy retrieval
- Handling failures with exponential backoff retry logic
- Supporting multiple pipeline types (main, child, merge request)
- **Parallel Execution**: Parse and extract parallel stage logs (Jenkins)

**Key Benefits:**
- Production-ready with Docker containerization
- Comprehensive monitoring and tracking
- Advanced logging with request ID correlation
- Flexible log filtering (by status, project, job)
- Dual-mode storage (API + files or either)
- Automatic retry and error handling

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

## Quick Setup

### Prerequisites

- **Python 3.8+** or **Docker** (Docker recommended for production)
- GitLab instance (GitLab.com or self-hosted)
- GitLab Personal Access Token with `api` scope
- Network connectivity to GitLab API

### Docker Deployment (Recommended)

**1. Create configuration file:**
```bash
cp .env.example .env
nano .env  # Edit GITLAB_URL and GITLAB_TOKEN
```

**2. Build and start container:**
```bash
./manage_container.py build
./manage_container.py start
```

**3. Verify it's running:**
```bash
./manage_container.py status
curl http://localhost:8000/health
```

Your webhook is now available at: `http://your-server:8000/webhook/gitlab`

**Complete Docker guide:** [DOCUMENTATION.md - Docker Operations](DOCUMENTATION.md#23-docker-operations)

### Manual Installation

**1. Clone and setup:**
```bash
git clone <repository-url>
cd extract-build-logs
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

**2. Configure environment:**
```bash
cp .env.example .env
nano .env  # Edit with your settings
```

**3. Start the server:**
```bash
python src/webhook_listener.py
```

**4. Verify:**
```bash
curl http://localhost:8000/health
```

## Configuration

**Minimum required configuration (.env file):**

```bash
# Required
GITLAB_URL=https://gitlab.com
GITLAB_TOKEN=your_gitlab_token_here

# Optional (with defaults)
WEBHOOK_PORT=8000
WEBHOOK_SECRET=your_webhook_secret
LOG_OUTPUT_DIR=./logs
LOG_LEVEL=INFO
```

**Common configurations:**

**1. Save only failed pipeline logs:**
```bash
LOG_SAVE_PIPELINE_STATUS=failed,canceled
LOG_SAVE_METADATA_ALWAYS=true
```

**2. Enable API posting:**
```bash
BFA_HOST=bfa-server.example.com
BFA_SECRET_KEY=your_bfa_secret_key
API_POST_ENABLED=true
API_POST_SAVE_TO_FILE=false  # API only, no file storage
```

**3. Jenkins integration:**
```bash
JENKINS_ENABLED=true
JENKINS_URL=https://jenkins.example.com
JENKINS_USER=your_username
JENKINS_API_TOKEN=your_jenkins_token
```

## Complete Documentation

For detailed documentation on all features, configuration options, operations, and troubleshooting:

**[→ Read Complete Documentation (DOCUMENTATION.md)](DOCUMENTATION.md)**

### Documentation Sections

- **[Features & Capabilities](DOCUMENTATION.md#features)** - Complete feature list with examples
- **[Module Documentation](DOCUMENTATION.md#module-documentation)** - Detailed module architecture and connections
- **[Installation & Setup](DOCUMENTATION.md#21-initial-setup)** - Complete installation guide
- **[Docker Operations](DOCUMENTATION.md#23-docker-operations)** - Full Docker deployment guide
- **[Configuration Guide](DOCUMENTATION.md#configuration)** - All configuration options explained
- **[GitLab Webhook Setup](DOCUMENTATION.md#31-webhook-configuration)** - Step-by-step webhook configuration
- **[Jenkins Integration](DOCUMENTATION.md#4-jenkins-integration)** - Complete Jenkins setup guide
- **[API Posting](DOCUMENTATION.md#5-api-posting)** - API integration documentation
- **[Monitoring & Operations](DOCUMENTATION.md#6-operations--monitoring)** - Monitoring, logging, and tracking
- **[Testing](DOCUMENTATION.md#61-testing)** - Test suite and CI/CD
- **[Troubleshooting](DOCUMENTATION.md#64-common-issues--solutions)** - Common issues and solutions
- **[Database Maintenance](DOCUMENTATION.md#7-database-maintenance)** - Backup and maintenance procedures

---

**Quick Links:**
- [Health Check](http://localhost:8000/health) - Server health status
- [API Docs (Swagger)](http://localhost:8000/docs) - Interactive API documentation
- [Monitoring Dashboard](http://localhost:8000/monitor/summary) - Statistics and metrics

**Support:**
- Report issues: Create an issue in the repository
- Documentation: [DOCUMENTATION.md](DOCUMENTATION.md)
- Configuration help: See [Configuration Guide](DOCUMENTATION.md#configuration)
