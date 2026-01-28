# GitLab & Jenkins Pipeline Log Extraction System - Complete Documentation

> **Comprehensive guide for setup, configuration, operations, and maintenance**

**Last Updated:** 2026-01-14
**Version:** 3.1

---

## System Deployment Flow

### High-Level Deployment Diagram

```mermaid
%%{init: {'theme':'base', 'themeVariables': { 'primaryColor':'#a8d5ba','secondaryColor':'#b3d9ff','tertiaryColor':'#ffd699','primaryBorderColor':'#6b9e78','secondaryBorderColor':'#6ba8e6','tertiaryBorderColor':'#e6a84d'}}}%%
flowchart TD
    subgraph Sources["CI/CD Sources"]
        JK[Jenkins Server<br/>Build Failures]
        GL[GitLab Server<br/>Pipeline Events]
    end

    subgraph Endpoints["Webhook Endpoints :8000"]
        JE["/webhook/jenkins<br/>Jenkins Endpoint"]
        GE["/webhook/gitlab<br/>GitLab Endpoint"]
    end

    subgraph Listener["Log Extractor Listener"]
        WH[Webhook Validator<br/>Secret Token Check]
        BG[Background Task Queue<br/>Non-blocking]
    end

    subgraph Processing["Stage Processing"]
        META[Get Build/Pipeline Metadata<br/>All Stages Info]
        FILTER[Find Failed Stages<br/>Status Filtering]
        EXTRACT[Extract Error Logs<br/>Context + Errors]
    end

    subgraph APIPost["API Integration"]
        USER[Determine Triggered User<br/>Jenkins/GitLab API]
        TOKEN[Generate JWT Token<br/>BFA Authentication]
        POST[Call External API<br/>POST Logs + Metadata]
    end

    subgraph Storage["Optional Storage"]
        SAVE[Save to File System<br/>logs/ directory]
    end

    JK -->|Build Failed<br/>POST webhook| JE
    GL -->|Pipeline Complete<br/>POST webhook| GE
    JE --> WH
    GE --> WH
    WH -->|Validated| BG
    BG --> META
    META -->|All Stages| FILTER
    FILTER -->|Failed Stages| EXTRACT
    EXTRACT -->|Logs Ready| USER
    USER -->|User Identified| TOKEN
    TOKEN -->|JWT Ready| POST
    POST -->|Optional<br/>Dual Mode| SAVE

    style JK fill:#ffe4b3,stroke:#e6c56b,stroke-width:2px
    style GL fill:#e8f4ea,stroke:#9db5a0,stroke-width:2px
    style JE fill:#ffd699,stroke:#e6a84d,stroke-width:3px
    style GE fill:#a8d5ba,stroke:#6b9e78,stroke-width:3px
    style WH fill:#b3d9ff,stroke:#6ba8e6,stroke-width:2px
    style BG fill:#c1e1c1,stroke:#7eb07e,stroke-width:2px
    style META fill:#d9b3ff,stroke:#a86be6,stroke-width:2px
    style FILTER fill:#ffb3d9,stroke:#e66ba8,stroke-width:2px
    style EXTRACT fill:#ffd699,stroke:#e6a84d,stroke-width:2px
    style USER fill:#b3f0ff,stroke:#6baee6,stroke-width:2px
    style TOKEN fill:#ffe4b3,stroke:#e6c56b,stroke-width:2px
    style POST fill:#a8d5ba,stroke:#6b9e78,stroke-width:3px
    style SAVE fill:#d9b3ff,stroke:#a86be6,stroke-width:2px
```

**Key Flow Steps:**

1. **Webhook Trigger**: Jenkins (on build failure) or GitLab (on pipeline event) sends POST request to respective endpoint
2. **Listener Processing**: Validates webhook secret and queues background processing task
3. **Stage Collection**: Fetches complete build/pipeline metadata with all stages information
4. **Failed Stage Identification**: Filters stages based on status (failed, canceled, etc.)
5. **Log Extraction**: Extracts error context and relevant log sections from failed stages
6. **User Determination**: Identifies who triggered the build using Jenkins metadata or GitLab API
7. **Authentication**: Generates JWT token for external API authentication
8. **API Posting**: Sends processed logs and metadata to external BFA API endpoint
9. **Optional Storage**: Saves logs to file system if dual mode is enabled

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
- [3.4 Jenkins Log File Storage](#34-jenkins-log-file-storage)
- [3.5 API Posting Setup](#35-api-posting-setup)
- [3.6 Log Filtering Configuration](#36-log-filtering-configuration)
- [3.7 Configuration Examples & Scenarios](#37-configuration-examples--scenarios)

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

**[7. Debugging and Validation](#7-debugging-and-validation)**
- [7.1 Container Debugging](#71-container-debugging)
- [7.2 Inside Container Debugging](#72-inside-container-debugging)
- [7.3 Log File Analysis](#73-log-file-analysis)
- [7.4 GitLab-Specific Debugging](#74-gitlab-specific-debugging)
- [7.5 Jenkins-Specific Debugging](#75-jenkins-specific-debugging)
- [7.6 Monitoring Dashboard Debugging](#76-monitoring-dashboard-debugging)
- [7.7 Configuration Validation](#77-configuration-validation)
- [7.8 Common Issues and Solutions](#78-common-issues-and-solutions)
- [7.9 Performance Debugging](#79-performance-debugging)

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

### System Architecture Diagram

```mermaid
graph TB
    subgraph "CI/CD Sources"
        GL[GitLab Server<br/>Pipeline Events]
        JK1[Jenkins Instance 1<br/>Build Events]
        JK2[Jenkins Instance 2<br/>Build Events]
        JK3[Jenkins Instance N<br/>Multi-Instance]
    end

    subgraph "Webhook Server (Port 8000)"
        WH[Webhook Listener<br/>FastAPI Server]
        VAL[Webhook Validator<br/>Secret Token Check]
        PARSE[Pipeline Extractor<br/>GitLab Parser]
        JPARSE[Jenkins Extractor<br/>Build Parser]
    end

    subgraph "Processing Layer"
        GLFETCH[GitLab Log Fetcher<br/>Pipeline API]
        JKFETCH[Jenkins Log Fetcher<br/>Blue Ocean API]
        GLAPI[GitLab API Client<br/>User Lookup]
        ERREXT[Error Extractor<br/>Pattern Matching]
        RETRY[Error Handler<br/>Retry Logic]
    end

    subgraph "API Integration Layer"
        APIPOSTER[API Poster<br/>External API]
        TOKENMGR[Token Manager<br/>JWT Generation]
        USERDET[User Determination<br/>Jenkins/GitLab]
    end

    subgraph "Storage Layer"
        STORE[Storage Manager<br/>File System]
        GLMETA[GitLab Metadata<br/>metadata.json]
        JKMETA[Jenkins Metadata<br/>metadata.json]
        LOGS[Log Files<br/>stage_*.log]
    end

    subgraph "Monitoring & Config"
        CONFIG[Config Loader<br/>Environment + JSON]
        MONITOR[Monitor DB<br/>SQLite Tracking]
    end

    GL -->|POST /webhook/gitlab| WH
    JK1 -->|POST /webhook/jenkins| WH
    JK2 -->|POST /webhook/jenkins| WH
    JK3 -->|POST /webhook/jenkins| WH

    WH --> VAL
    VAL -->|GitLab Event| PARSE
    VAL -->|Jenkins Event| JPARSE

    PARSE -->|Pipeline Info| GLFETCH
    JPARSE -->|Build Info| JKFETCH

    GLFETCH -->|API Call| GL
    JKFETCH -->|Blue Ocean API| JK1
    JKFETCH -->|Blue Ocean API| JK2
    JKFETCH -->|Blue Ocean API| JK3

    GLFETCH -.->|On Error| RETRY
    JKFETCH -.->|On Error| RETRY
    RETRY -.->|Retry| GLFETCH
    RETRY -.->|Retry| JKFETCH

    GLFETCH --> ERREXT
    JKFETCH --> ERREXT
    ERREXT --> USERDET

    USERDET -->|GitLab User Lookup| GLAPI
    GLAPI -->|API Call| GL
    USERDET --> APIPOSTER

    APIPOSTER --> TOKENMGR
    APIPOSTER -->|POST Logs| APIPOSTER
    APIPOSTER -.->|Dual Mode| STORE

    ERREXT -.->|File Mode| STORE
    STORE --> GLMETA
    STORE --> JKMETA
    STORE --> LOGS

    WH --> MONITOR
    APIPOSTER --> MONITOR

    CONFIG -.->|Configuration| WH
    CONFIG -.->|jenkins_instances.json| JKFETCH
    CONFIG -.->|.env| APIPOSTER

    style WH fill:#a8d5ba,stroke:#6b9e78,stroke-width:3px
    style VAL fill:#c1e1c1,stroke:#7eb07e
    style PARSE fill:#b3d9ff,stroke:#6ba8e6
    style JPARSE fill:#ffd699,stroke:#e6a84d
    style GLFETCH fill:#b3d9ff,stroke:#6ba8e6
    style JKFETCH fill:#ffd699,stroke:#e6a84d
    style GLAPI fill:#b3f0ff,stroke:#6baee6
    style ERREXT fill:#ffb3d9,stroke:#e66ba8
    style RETRY fill:#ffb3b3,stroke:#e66b6b
    style APIPOSTER fill:#a8d5ba,stroke:#6b9e78,stroke-width:2px
    style TOKENMGR fill:#ffe4b3,stroke:#e6c56b
    style USERDET fill:#b3f0ff,stroke:#6baee6
    style STORE fill:#d9b3ff,stroke:#a86be6
    style GLMETA fill:#e6ccff,stroke:#b380e6
    style JKMETA fill:#ffe4cc,stroke:#e6b380
    style LOGS fill:#f0d9ff,stroke:#c699e6
    style CONFIG fill:#c5ccd4,stroke:#8b95a1
    style MONITOR fill:#d4f4dd,stroke:#9bcca8
    style GL fill:#e8f4ea,stroke:#9db5a0
    style JK1 fill:#fff4e6,stroke:#e6c599
    style JK2 fill:#fff4e6,stroke:#e6c599
    style JK3 fill:#fff4e6,stroke:#e6c599
```

The system consists of several key components working together:

### Core Components

1. **Webhook Listener** (`webhook_listener.py`)
   - FastAPI async web server
   - Dual endpoints: `/webhook/gitlab` and `/webhook/jenkins`
   - Validates webhook secrets for both sources
   - Queues background processing tasks

2. **Pipeline Extractor** (`pipeline_extractor.py`)
   - Parses GitLab webhook payloads
   - Identifies pipeline types (main/child/MR)
   - Filters jobs based on configuration

3. **Jenkins Extractor** (`jenkins_extractor.py`)
   - Parses Jenkins webhook payloads
   - Fetches build metadata via Blue Ocean API
   - Extracts stage information and parameters
   - Supports multi-instance configurations

4. **GitLab Log Fetcher** (`log_fetcher.py`)
   - Communicates with GitLab API
   - Fetches pipeline and job logs
   - Handles authentication with private tokens

5. **Jenkins Log Fetcher** (`jenkins_log_fetcher.py`)
   - Communicates with Jenkins API and Blue Ocean
   - Memory-efficient log streaming (tail + streaming hybrid)
   - Handles million+ line logs without OOM crashes
   - Multi-instance support with credential management

6. **Log Error Extractor** (`log_error_extractor.py`)
   - Pattern-based error detection
   - Extracts error context from logs
   - Supports Jenkins and GitLab log formats

7. **Storage Manager** (`storage_manager.py`)
   - Creates directory structures for both GitLab and Jenkins
   - GitLab: `logs/{project}_{id}/pipeline_{id}/`
   - Jenkins: `logs/jenkins-builds/{job-name}/{build-number}/`
   - Saves log files and metadata.json

8. **API Poster** (`api_poster.py`)
   - Posts logs to external BFA API endpoint
   - User determination: Jenkins metadata + GitLab API lookups
   - JWT token generation for authentication
   - Dual mode: API-only or API + file storage
   - Retry logic with exponential backoff

9. **Monitoring** (`monitoring.py`)
   - SQLite database for tracking
   - Records all webhook requests (GitLab and Jenkins)
   - Provides statistics and reporting

10. **Error Handler** (`error_handler.py`)
    - Implements retry logic with exponential backoff
    - Circuit breaker pattern
    - Comprehensive error tracking

## 1.3 Module Documentation

### Module Connection Diagram

```mermaid
graph TB
    subgraph "Core Modules"
        WL[webhook_listener.py<br/>Main Server<br/>FastAPI]
        PE[pipeline_extractor.py<br/>GitLab Parser]
        JE[jenkins_extractor.py<br/>Jenkins Parser]
        GLF[log_fetcher.py<br/>GitLab API Client]
        JLF[jenkins_log_fetcher.py<br/>Jenkins API Client]
        LEE[log_error_extractor.py<br/>Error Pattern Matcher]
        SM[storage_manager.py<br/>File Storage]
        AP[api_poster.py<br/>API Integration]
        MON[monitoring.py<br/>Tracking DB]
    end

    subgraph "Helper Modules"
        CL[config_loader.py<br/>Configuration]
        EH[error_handler.py<br/>Retry Logic]
        TM[token_manager.py<br/>JWT Auth]
        LC[logging_config.py<br/>Logging Setup]
    end

    subgraph "Configuration Files"
        ENV[.env<br/>Environment]
        JINS[jenkins_instances.json<br/>Multi-Instance Config]
    end

    WL -->|extract_pipeline_info| PE
    WL -->|extract_jenkins_info| JE
    WL -->|fetch_gitlab_logs| GLF
    WL -->|fetch_jenkins_logs| JLF
    WL -->|extract_errors| LEE
    WL -->|save_logs| SM
    WL -->|post_to_api| AP
    WL -->|record_request| MON

    JE -->|fetch_build_metadata| JLF
    JLF -->|extract_errors| LEE

    AP -->|gitlab_user_lookup| GLF
    AP -->|determine_user| JE
    AP -->|generate_token| TM
    AP -->|with_retry| EH

    GLF -->|with_retry| EH
    JLF -->|with_retry| EH

    WL -->|load_config| CL
    GLF -->|load_config| CL
    JLF -->|load_config| CL
    SM -->|load_config| CL
    AP -->|load_config| CL
    WL -->|setup_logging| LC

    CL -->|read| ENV
    JLF -->|read| JINS

    style WL fill:#a8d5ba,stroke:#6b9e78,stroke-width:3px
    style PE fill:#b3d9ff,stroke:#6ba8e6
    style JE fill:#ffd699,stroke:#e6a84d
    style GLF fill:#b3d9ff,stroke:#6ba8e6
    style JLF fill:#ffd699,stroke:#e6a84d
    style LEE fill:#ffb3d9,stroke:#e66ba8
    style SM fill:#d9b3ff,stroke:#a86be6
    style AP fill:#a8d5ba,stroke:#6b9e78,stroke-width:2px
    style MON fill:#b3f0ff,stroke:#6baee6
    style CL fill:#c5ccd4,stroke:#8b95a1
    style EH fill:#ffb3b3,stroke:#e66b6b
    style TM fill:#ffe4b3,stroke:#e6c56b
    style LC fill:#d4bcb0,stroke:#a18578
    style ENV fill:#e8e8e8,stroke:#a0a0a0
    style JINS fill:#ffe8d6,stroke:#e6b380
```

### Core Application Files

| File | Purpose | Key Classes/Functions | Key Responsibilities |
|------|---------|----------------------|---------------------|
| `webhook_listener.py` | Main server | `init_app()`, `process_pipeline_event()`, `process_jenkins_build()` | FastAPI server, dual webhook endpoints (/webhook/gitlab, /webhook/jenkins), background task processing, job filtering |
| `pipeline_extractor.py` | GitLab parsing | `PipelineExtractor`, `PipelineType` | Parse GitLab webhook payloads, identify pipeline types (merge_request, branch, tag, scheduled), filter jobs by status |
| `jenkins_extractor.py` | Jenkins parsing | `JenkinsExtractor` | Parse Jenkins webhook payloads, fetch Blue Ocean metadata, extract failed stages and steps |
| `log_fetcher.py` | GitLab API client | `LogFetcher`, `GitLabAPIError` | Fetch GitLab job logs via API, handle authentication, retry on failures |
| `jenkins_log_fetcher.py` | Jenkins API client | `JenkinsLogFetcher` | Memory-efficient log streaming, hybrid fetch (tail-first), multi-instance support |
| `jenkins_instance_manager.py` | Jenkins multi-instance | `JenkinsInstance`, `JenkinsInstanceManager` | Load jenkins_instances.json, match URLs to credentials, validate configuration |
| `log_error_extractor.py` | Error extraction | `LogErrorExtractor`, `extract_error_sections()` | Pattern matching (ERROR_PATTERNS), ignore patterns, context extraction (lines before/after), line cleaning |
| `storage_manager.py` | File storage | `StorageManager` | Create directory structure for GitLab/Jenkins, save logs and metadata JSON files |
| `api_poster.py` | API integration | `ApiPoster` | Determine triggered user, JWT authentication, POST logs to BFA API, dual mode (API + file) |
| `monitoring.py` | Tracking | `PipelineMonitor`, `RequestStatus` | SQLite database for webhook statistics, request tracking, CSV export |
| `error_handler.py` | Error handling | `ErrorHandler`, `CircuitBreaker`, `retry_on_failure()` | Retry logic with exponential backoff, circuit breaker pattern, error tracking |
| `config_loader.py` | Configuration | `Config`, `ConfigLoader` | Load .env file, load jenkins_instances.json, validate all settings |
| `logging_config.py` | Logging | `LoggingConfig`, `SensitiveDataFilter`, `PipeDelimitedFormatter` | Configure loggers, pipe-delimited format, mask sensitive data (tokens), request ID tracking |
| `token_manager.py` | Authentication | `TokenManager` | JWT token generation and caching for BFA API authentication |

## 1.4 Project Structure

```
extract-build-logs/
│
├── src/                          # Main application code
│   ├── webhook_listener.py      # FastAPI server and main entry point
│   ├── pipeline_extractor.py    # GitLab pipeline event parsing
│   ├── jenkins_extractor.py     # Jenkins build event parsing
│   ├── log_fetcher.py            # GitLab API client for logs
│   ├── jenkins_log_fetcher.py   # Jenkins API client for logs
│   ├── log_error_extractor.py   # Error extraction from logs
│   ├── storage_manager.py        # File system storage
│   ├── api_poster.py             # API posting functionality
│   ├── monitoring.py             # SQLite tracking database
│   ├── config_loader.py          # Configuration management
│   ├── error_handler.py          # Retry logic and error handling
│   ├── logging_config.py         # Logging configuration
│   ├── token_manager.py          # JWT token management
│   └── jenkins_instance_manager.py  # Jenkins multi-instance support
│
├── tests/                        # Comprehensive test suite
│   ├── test_webhook_listener.py
│   ├── test_webhook_background_tasks.py
│   ├── test_webhook_initialization.py
│   ├── test_webhook_integration.py
│   ├── test_pipeline_extractor.py
│   ├── test_jenkins_extractor.py
│   ├── test_jenkins_log_fetcher.py
│   ├── test_log_fetcher.py
│   ├── test_log_error_extractor.py
│   ├── test_storage_manager.py
│   ├── test_api_poster.py
│   ├── test_monitoring.py
│   ├── test_config_loader.py
│   ├── test_error_handler.py
│   ├── test_logging_config.py
│   ├── test_token_manager.py
│   └── test_manage_container.py
│
├── scripts/                      # Utility scripts and services
│   ├── manage_database.sh        # Database management CLI
│   ├── monitor_dashboard.py      # Monitoring dashboard
│   ├── gitlab-log-extractor.service  # Systemd service file
│   └── crontab.example           # Example cron jobs
│
├── logs/                         # Output directory (created automatically)
│   ├── {project-name}_{id}/      # GitLab: Organized by project
│   │   └── pipeline_{id}/        # Then by pipeline
│   │       ├── metadata.json     # Pipeline metadata
│   │       └── job_{id}_{name}.log  # Job logs
│   ├── jenkins-builds/           # Jenkins: Organized by job
│   │   └── {job-name}/           # Job name from Jenkins
│   │       └── {build-number}/   # Build number
│   │           ├── metadata.json # Build metadata
│   │           ├── console.log   # Full console output
│   │           └── stage_*.log   # Failed stage logs
│   ├── application.log           # Application logs
│   ├── api-requests.log          # API request logs
│   └── monitoring.db             # SQLite tracking database
│
├── .env                          # Environment configuration (create from .env.example)
├── .env.example                  # Configuration template with documentation
├── .gitlab-ci.yml                # GitLab CI/CD pipeline configuration
├── .dockerignore                 # Docker build ignore list
├── .flake8                       # Flake8 linter configuration
├── .pylintrc                     # Pylint linter configuration
├── .gitignore                    # Git ignore list
├── pyproject.toml                # Python project config (pytest, coverage)
├── jenkins_instances.json        # Jenkins multi-instance configuration
├── jenkins_instances.json.example # Jenkins config template
├── requirements.txt              # Python dependencies (main application)
├── requirements-manage-py36.txt  # Python 3.6 compatible dependencies
├── Dockerfile                    # Docker image definition
├── log-extractor-entrypoint.sh   # Container entrypoint script
├── manage_container.py           # Container management tool
├── remove_emojis.py              # Utility to remove emojis from files
├── README.md                     # Quick start guide
├── DOCUMENTATION.md              # This file (complete documentation)
├── PYTHON36_COMPATIBILITY.md     # Python 3.6 compatibility guide
└── PLAN_JENKINS_USER_EXTRACTION.md  # Jenkins user extraction planning doc
```

## 1.5 Data Flow & Processing

### GitLab Data Flow Sequence Diagram

```mermaid
%%{init: {'theme':'base', 'themeVariables': { 'primaryColor':'#a8d5ba','secondaryColor':'#b3d9ff','tertiaryColor':'#ffd699','primaryBorderColor':'#6b9e78','secondaryBorderColor':'#6ba8e6','tertiaryBorderColor':'#e6a84d'}}}%%
sequenceDiagram
    participant GL as GitLab
    participant WH as Webhook Listener
    participant EX as Pipeline Extractor
    participant FE as Log Fetcher
    participant ST as Storage Manager
    participant AP as API Poster
    participant MO as Monitor DB
    participant FS as File System

    GL->>WH: POST /webhook/gitlab<br/>(Pipeline Event)

    rect rgba(168, 213, 186, 0.2)
        Note over WH: Authentication & Validation
        WH->>WH: Validate Secret Token
        alt Invalid Token
            WH-->>GL: 401 Unauthorized
        end
        WH->>WH: Generate Request ID
    end

    rect rgba(179, 217, 255, 0.2)
        Note over WH,EX: Event Parsing & Filtering
        WH->>EX: extract_pipeline_info(event)
        EX->>EX: Parse pipeline metadata<br/>(ID, project, status, jobs)
        EX->>EX: Identify pipeline type<br/>(main/child/MR)

        alt Check Pipeline Status Filter
            EX->>EX: Status in LOG_SAVE_PIPELINE_STATUS?
            Note over EX: e.g., only "failed,canceled"
            alt Status Matches Filter
                EX->>EX: Proceed with extraction
            else Status Doesn't Match
                EX-->>WH: Skip (status filtered)
                WH->>MO: record_request(skipped)
                WH-->>GL: 200 OK (Filtered)
                Note over WH: Exit - No logs fetched
            end
        end

        EX->>EX: Filter jobs by status<br/>(LOG_SAVE_JOB_STATUS)
        EX-->>WH: Pipeline metadata + filtered jobs
    end

    WH->>WH: Queue background task
    WH->>MO: record_request(processing)
    WH-->>GL: 200 OK (Acknowledged)

    rect rgba(255, 214, 153, 0.2)
        Note over WH,FE: Background Log Fetching
        WH->>FE: fetch_logs(pipeline_id, jobs)

        loop For Each Filtered Job
            FE->>GL: GET /api/v4/projects/{id}/jobs/{job_id}/trace
            alt Success
                GL-->>FE: Job log content
            else API Error (4xx/5xx)
                FE->>FE: Exponential backoff retry<br/>(2s, 4s, 8s...)
                alt Max Retries Exceeded
                    FE->>MO: Log fetch failure
                    Note over FE: Continue with next job
                else Retry Success
                    GL-->>FE: Job log content
                end
            end
        end
        FE-->>WH: All job logs + metadata
    end

    rect rgba(217, 179, 255, 0.2)
        Note over WH,AP: Storage & API Posting Decision
        alt API_POST_ENABLED = true
            WH->>AP: post_to_api(logs, metadata)
            AP->>AP: generate_token() [JWT]
            AP->>AP: Build request payload

            loop Retry with backoff
                AP->>AP: POST to BFA API
                alt API Success
                    Note over AP: API returned 200 OK
                    AP->>MO: record_api_success()
                else API Failure
                    Note over AP: Retry or fallback
                end
            end

            alt API_POST_SAVE_TO_FILE = true
                Note over AP,ST: Dual mode: API + Files
                AP->>ST: save_logs(logs, metadata)
            else API_POST_SAVE_TO_FILE = false
                Note over AP: API only, skip file storage
            end
        else API_POST_ENABLED = false
            Note over WH,ST: File storage only
            WH->>ST: save_logs(logs, metadata)
        end
    end

    rect rgba(179, 240, 255, 0.2)
        Note over ST,FS: File System Storage
        ST->>FS: Create directory structure<br/>(project/pipeline/)
        ST->>FS: Save job logs (.log files)
        ST->>FS: Save/update metadata.json
        FS-->>ST: Confirmation
        ST-->>WH: Storage complete
    end

    WH->>MO: update_request(completed)<br/>Record duration & status
    MO-->>WH: Success

    Note over WH: Processing complete<br/>Request ID logged
```

### Jenkins Data Flow Sequence Diagram

```mermaid
%%{init: {'theme':'base', 'themeVariables': { 'primaryColor':'#ffd699','secondaryColor':'#b3d9ff','tertiaryColor':'#ffb3d9','primaryBorderColor':'#e6a84d','secondaryBorderColor':'#6ba8e6','tertiaryBorderColor':'#e66ba8'}}}%%
sequenceDiagram
    participant JK as Jenkins
    participant WH as Webhook Listener
    participant JE as Jenkins Extractor
    participant JF as Jenkins Log Fetcher
    participant GL as GitLab API
    participant EE as Error Extractor
    participant AP as API Poster
    participant TM as Token Manager
    participant MO as Monitor DB
    participant ST as Storage Manager

    JK->>WH: POST /webhook/jenkins<br/>(Build Event)

    rect rgba(255, 214, 153, 0.2)
        Note over WH: Authentication & Validation
        WH->>WH: Validate X-Jenkins-Token
        alt Invalid Token
            WH-->>JK: 401 Unauthorized
        end
        WH->>WH: Generate Request ID
    end

    WH->>WH: Queue background task
    WH->>MO: record_request(processing)
    WH-->>JK: 200 OK (Acknowledged)

    rect rgba(179, 217, 255, 0.2)
        Note over WH,JE: Build Metadata Extraction
        WH->>JE: extract_jenkins_info(webhook_data)
        JE->>JF: fetch_build_info(job_name, build_number)
        JF->>JK: GET /job/{name}/{number}/api/json
        JK-->>JF: Build metadata + parameters

        Note over JF: Extract jenkins_url from build metadata
        JF->>JF: Load jenkins_instances.json<br/>Find credentials by jenkins_url

        JF->>JK: GET /job/{name}/{number}/wfapi/describe<br/>(Blue Ocean API)
        JK-->>JF: All stages metadata<br/>(names, statuses, durations)
        JF-->>JE: Build info + stages
        JE-->>WH: Jenkins payload
    end

    rect rgba(255, 179, 217, 0.2)
        Note over WH,EE: Log Fetching & Error Extraction
        loop For Each Failed Stage
            WH->>JF: fetch_console_log(job, build)

            alt Large Log (>1M lines)
                JF->>JF: Use hybrid strategy:<br/>Tail (last 5000 lines) first
                JF->>JK: GET with Range header<br/>(last N bytes)
                JK-->>JF: Tail content

                alt Errors found in tail
                    Note over JF: Use tail content (fast path)
                else No errors in tail
                    JF->>JF: Fall back to streaming
                    JF->>JK: GET with iter_lines()<br/>(max 100K lines)
                    JK-->>JF: Streamed content
                end
            else Normal Log
                JF->>JK: GET /job/{name}/{number}/consoleText
                JK-->>JF: Full console log
            end

            JF-->>WH: Console log
            WH->>EE: extract_errors(console_log, stage_name)
            EE->>EE: Pattern matching for errors<br/>(ERROR, FAILED, Exception, etc.)
            EE-->>WH: Error context + summary
        end
    end

    rect rgba(179, 240, 255, 0.2)
        Note over WH,AP: User Determination
        WH->>AP: determine_triggered_by(parameters, metadata)
        AP->>AP: Extract Jenkins userId<br/>from build metadata

        alt userId == "jenkins"
            Note over AP,GL: GitLab webhook trigger
            AP->>AP: Extract GitLab parameters:<br/>namespace, repo, MR/commit/branch
            AP->>GL: GET /api/v4/projects/{namespace}/{repo}
            GL-->>AP: Project ID

            alt Has gitlabMergeRequestIid
                AP->>GL: GET /projects/{id}/merge_requests/{iid}
                GL-->>AP: MR author username
            else Has gitlabMergeRequestLastCommit
                AP->>GL: GET /projects/{id}/repository/commits/{sha}
                GL-->>AP: Commit author username
            else Has gitlabSourceBranch
                AP->>GL: GET /projects/{id}/repository/branches/{branch}
                GL-->>AP: Latest commit author
            end

            AP->>AP: Format: {gitlab_user}@internal.com
        else userId != "jenkins"
            Note over AP: Manual Jenkins trigger
            AP->>AP: Format: {jenkins_user}@internal.com
        end

        AP-->>WH: Triggered by user determined
    end

    rect rgba(168, 213, 186, 0.2)
        Note over WH,AP: API Posting with Authentication
        WH->>AP: post_jenkins_logs(payload, metadata)
        AP->>AP: Build payload with:<br/>- pipeline_id: {build_url}<br/>- triggered_by: {user}@internal.com<br/>- stages with errors

        AP->>TM: generate_token(BFA_SECRET_KEY)
        TM-->>AP: JWT token

        AP->>AP: POST to BFA API<br/>(with retry logic)

        alt API Success
            Note over AP: Logs posted successfully
            AP->>MO: record_api_success()
        else API Failure
            Note over AP: Retry with backoff
            AP->>MO: record_api_failure()
        end

        alt API_POST_SAVE_TO_FILE = true
            Note over AP,ST: Dual mode enabled
            AP->>ST: save_jenkins_logs(logs, metadata)
            ST->>ST: Create directory:<br/>logs/jenkins-builds/{job}/{build}/
            ST->>ST: Save console.log, stage_*.log,<br/>metadata.json
        end
    end

    WH->>MO: update_request(completed)
    Note over WH: Jenkins build processing complete
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
vi .env  # Add your GITLAB_URL and GITLAB_TOKEN
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
- GitLab instance (GitLab.com)
- GitLab Personal Access Token with `api` scope

### Installation Steps

**1. Clone Repository**
```bash
git clone <repository-url>
cd extract-build-logs
```

**2. Create Virtual Environment**
```bash
python3 -m venv venv
source venv/bin/activate
```

**3. Install Dependencies**
```bash
pip install -r requirements.txt
```

**4. Configure Environment**
```bash
cp .env.example .env
vi .env  # Edit with your settings
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
2. **Configure Log Filtering** (optional) → See [Section 3.6](#36-log-filtering-configuration)
3. **Enable API Posting** (optional) → See [Section 3.5](#35-api-posting-setup)
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

#### Docker Configuration
```bash
DOCKER_IMAGE_NAME=bfa-gitlab-pipeline-extractor   # Docker image name
DOCKER_CONTAINER_NAME=bfa-gitlab-pipeline-extractor  # Docker container name
DOCKER_LOGS_DIR=./logs               # Host directory for volume mount
```

#### Server Configuration
```bash
WEBHOOK_PORT=8000                    # Server port (default: 8000)
WEBHOOK_SECRET=your_webhook_secret   # Webhook validation secret
LOG_OUTPUT_DIR=./logs                # Log storage directory
LOG_LEVEL=INFO                       # Logging level (DEBUG, INFO, WARNING, ERROR)
RETRY_ATTEMPTS=3                     # API retry attempts
RETRY_DELAY=60                       # Retry delay in seconds (default: 60)
LOG_RETENTION_DAYS=90                # Days to retain logs before cleanup
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
JENKINS_FILTER_HANDLED_FAILURES=true          # Filter out handled failures (try-catch)
```

#### Log Error Extraction
```bash
# Context lines around errors
ERROR_CONTEXT_LINES_BEFORE=50        # Lines before each error (default: 50)
ERROR_CONTEXT_LINES_AFTER=10         # Lines after each error (default: 10)

# Ignore patterns (comma-separated, case-insensitive)
# Lines matching these won't be considered errors even if they match ERROR_PATTERNS
ERROR_IGNORE_PATTERNS=               # e.g., "error: tag,0 errors"

# Log processing limits
MAX_LOG_LINES=100000                 # Max lines to process per log (default: 100000)
TAIL_LOG_LINES=5000                  # Tail lines for hybrid fetch (default: 5000)
STREAM_CHUNK_SIZE=8192               # Bytes per chunk when streaming (default: 8192)
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

```mermaid
sequenceDiagram
    participant G as GitLab
    participant W as Webhook Server
    participant API as GitLab API
    participant S as Storage/BFA

    G->>W: Pipeline Event Webhook
    W->>API: Fetch Job Logs
    API-->>W: Return Logs
    W->>W: Extract Error Sections
    W->>S: Post/Store Extracted Errors
```

### Setup Steps

**1. Navigate to Webhook Settings**
- Go to your GitLab project
- Settings → Webhooks

**2. Add Webhook URL**
```
http://your-server:8000/webhook/gitlab
```

**3. Select Trigger Events**
- Enable **Pipeline events** only
- Disable all other events

**4. Configure Options**
- Disable SSL verification (if not using HTTPS)

**5. Add Webhook**
- Click "Add webhook"

**6. Test the Webhook**
- Click "Test" → "Pipeline events"
- Check server logs for confirmation

**Example: Successful Webhook Test**
```
2025-12-30 10:30:15.123 | INFO  | src.webhook_listener    | c4d5e6f7 | Webhook received | event=Pipeline Hook
2025-12-30 10:30:15.124 | INFO  | src.pipeline_extractor  | c4d5e6f7 | Extracted info for pipeline 123456 | project=test-project type=main
2025-12-30 10:30:15.125 | INFO  | src.webhook_listener    | c4d5e6f7 | Pipeline queued for processing | pipeline_id=123456
```

<details>
<summary><b>Webhook Payload Example</b></summary>

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

</details>

<details>
<summary><b>Troubleshooting</b></summary>

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

</details>

## 3.3 Jenkins Integration

### Overview

Jenkins integration allows extracting build logs including parallel execution blocks.

```mermaid
sequenceDiagram
    participant J as Jenkins
    participant W as Webhook Server
    participant API as Jenkins API
    participant S as Storage/BFA

    J->>W: POST /webhook/jenkins (build info)
    W->>API: Fetch Console Log
    API-->>W: Return Build Logs
    W->>W: Extract Error Sections
    W->>S: Post/Store Extracted Errors
```

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
                def webhookUrl = "http://your-server:8000/webhook/jenkins"
                def curlCommand = """curl -X POST ${webhookUrl} \\
                    -H "Content-Type: application/json" \\
                    -H "X-Jenkins-Token: ${JENKINS_WEBHOOK_SECRET}" \\
                    -d '{"job_name":"${env.JOB_NAME}","build_number":${env.BUILD_NUMBER},"build_url":"${env.BUILD_URL}","jenkins_url":"${env.JENKINS_URL}"}'"""

                try {
                    // Webhook server will fetch logs via Jenkins API
                    sh curlCommand
                    echo "✓ Webhook sent successfully"
                } catch (Exception e) {
                    echo "✗ ERROR: Failed to send webhook"
                    echo "Error: ${e.message}"
                    echo "Command attempted:"
                    echo curlCommand
                }
            }
        }
    }
}
```

**Note:** The `jenkins_url` field is required when using multiple Jenkins instances. The system will automatically use the appropriate credentials based on this URL.

### Example: Jenkins Logs with Parallel Stages

```
2025-12-30 10:35:15.456 | INFO  | src.webhook_listener    | d5e6f7g8 | Jenkins webhook received | job=my-pipeline build=42
2025-12-30 10:35:16.123 | INFO  | src.jenkins_extractor   | d5e6f7g8 | Extracted Jenkins build info | stages=5 parallel_blocks=2
2025-12-30 10:35:16.234 | INFO  | src.jenkins_log_fetcher | d5e6f7g8 | Fetching logs for parallel stage: test-unit
2025-12-30 10:35:16.345 | INFO  | src.jenkins_log_fetcher | d5e6f7g8 | Fetching logs for parallel stage: test-integration
2025-12-30 10:35:17.456 | INFO  | src.storage_manager     | d5e6f7g8 | Saved Jenkins logs | job=my-pipeline build=42 files=5
```

### Recent Jenkins Enhancements (January 2026)

#### Memory-Efficient Large Log Handling

Jenkins builds can produce massive console logs (1M+ lines). The system now handles these efficiently without memory overflow:

**Hybrid Fetching Strategy:**
1. **Tail Method** (fast, 99% of cases):
   - Fetches only last N lines using HTTP Range headers
   - Memory usage: ~2MB regardless of log size
   - Latency: ~200ms
   - Works when errors are at the end (typical for failed builds)

2. **Streaming Method** (fallback):
   - Line-by-line streaming with safety limits
   - Memory usage: ~10MB constant (doesn't grow with log size)
   - Processes up to `MAX_LOG_LINES` (default: 100,000)
   - Prevents OOM crashes on multi-million line logs

**Configuration:**
```bash
# Optional - has sensible defaults
MAX_LOG_LINES=100000        # Maximum lines to process (safety limit)
TAIL_LOG_LINES=5000         # How many tail lines to try first
STREAM_CHUNK_SIZE=8192      # Streaming chunk size in bytes
```

**Example Logs:**
```
2026-01-10 12:35:02.880 | INFO  | src.jenkins_log_fetcher | 329aa9a3 | Streaming console log for job ci_build #8355 (max 100000 lines)
2026-01-10 12:35:02.920 | INFO  | src.jenkins_log_fetcher | 329aa9a3 | Streamed console log for job ci_build #8355: 72478 lines, 6059383 bytes (truncated=False)
2026-01-10 12:35:02.921 | INFO  | src.webhook_listener    | 329aa9a3 | Fetched console log using 'streaming' method: 72478 lines, truncated=False
```

#### Performance Optimizations

**Problem Eliminated:**
- Previous implementation made 7+ failing API calls per build (one per stage)
- Complex marker extraction that never found stage boundaries
- Multi-layer fallback chains adding latency

**Solution:**
1. **Single Blue Ocean API call** for all stage metadata (names, statuses)
2. **Direct error extraction** from full console log for each failed stage
3. **Simplified processing**: 68% code reduction (112 → 36 lines)

## 3.4 Jenkins Log File Storage

### Overview

Jenkins build logs are automatically saved to a structured directory hierarchy when Jenkins webhooks are processed. The system organizes logs by job name and build number, creating a consistent structure similar to GitLab pipeline logs.

### Directory Structure

**Base Structure:**
```
logs/
├── jenkins-builds/
│   ├── {job-name}/
│   │   └── {build-number}/
│   │       ├── metadata.json
│   │       ├── console.log
│   │       ├── stage_{stage-name}.log
│   │       └── stage_{stage-name}.log
│   └── another-job/
│       └── 123/
│           ├── metadata.json
│           └── console.log
├── application.log
├── api-requests.log
└── monitoring.db
```

**Example: Complete Jenkins Build with Multiple Stages**
```
logs/
├── jenkins-builds/
│   ├── ci_build/
│   │   ├── 8320/
│   │   │   ├── metadata.json
│   │   │   ├── console.log
│   │   │   ├── stage_checkout.log
│   │   │   ├── stage_build.log
│   │   │   ├── stage_test-unit.log
│   │   │   ├── stage_test-integration.log
│   │   │   └── stage_deploy.log
│   │   └── 8321/
│   │       ├── metadata.json
│   │       ├── console.log
│   │       └── stage_build.log
│   ├── pre-merge-build/
│   │   └── 456/
│   │       ├── metadata.json
│   │       ├── console.log
│   │       ├── stage_pre-merge-test.log
│   │       └── stage_code-review.log
│   └── nightly-tests/
│       └── 789/
│           ├── metadata.json
│           └── console.log
├── application.log
├── api-requests.log
└── monitoring.db
```

### File Naming Conventions

#### Directory Names
- **Job directory**: Exact job name from Jenkins (e.g., `ci_build`, `pre-merge-build`)
- **Build directory**: Build number as string (e.g., `8320`, `456`)

#### Log Files
- **`metadata.json`**: Complete build metadata including parameters, trigger info, and stage details
- **`console.log`**: Full console output from the Jenkins build
- **`stage_{stage-name}.log`**: Individual stage logs with extracted error context
  - Stage names are sanitized (lowercase, spaces/special chars replaced with hyphens)
  - Examples: `stage_build.log`, `stage_test-unit.log`, `stage_code-review.log`

### Metadata File Format

The `metadata.json` file contains comprehensive information about the Jenkins build:

```json
{
  "source": "jenkins",
  "job_name": "ci_build",
  "build_number": 8320,
  "build_url": "https://jenkins.example.com/job/ci_build/8320/",
  "jenkins_url": "https://jenkins.example.com",
  "triggered_by": "john.doe@internal.com",
  "timestamp": "2026-01-13T10:30:45.123Z",
  "status": "FAILED",
  "duration_ms": 245000,
  "parameters": {
    "gitlabSourceNamespace": "sandvine-platform",
    "gitlabSourceRepoName": "ci_build",
    "gitlabSourceBranch": "feature/new-feature",
    "gitlabMergeRequestIid": "123",
    "gitlabMergeRequestLastCommit": "abc123def456"
  },
  "stages": [
    {
      "name": "checkout",
      "status": "SUCCESS",
      "duration_ms": 5000
    },
    {
      "name": "build",
      "status": "SUCCESS",
      "duration_ms": 120000
    },
    {
      "name": "test-unit",
      "status": "FAILED",
      "duration_ms": 45000,
      "error_summary": "AssertionError: Expected 42 but got 41"
    },
    {
      "name": "test-integration",
      "status": "ABORTED",
      "duration_ms": 0
    }
  ],
  "repo": "ci_build",
  "branch": "feature/new-feature",
  "commit": "abc123def456"
}
```

### Comparison with GitLab Structure

Both Jenkins and GitLab logs follow similar organizational principles:

| Aspect | GitLab | Jenkins |
|--------|--------|---------|
| **Base path** | `logs/{project}_{id}/pipeline_{id}/` | `logs/jenkins-builds/{job-name}/{build-number}/` |
| **Metadata** | `metadata.json` | `metadata.json` |
| **Main log** | N/A (job-specific only) | `console.log` (full build output) |
| **Stage logs** | `job_{id}_{name}.log` | `stage_{name}.log` |
| **Identifier** | Pipeline URL | Build URL |
| **Trigger user** | `username@sandvine.com` | `username@internal.com` |

### Storage Behavior

**Automatic Creation:**
- Directories are created automatically when webhooks are processed
- No manual setup required
- Failed builds still save logs for debugging

**File Persistence:**
- Logs are retained indefinitely (no automatic cleanup)
- Implement custom retention policies using cron jobs if needed
- Example: `find logs/jenkins-builds -mtime +90 -delete` (remove builds older than 90 days)

**Disk Space Considerations:**
- Console logs can be large (1MB-100MB+ per build)
- Stage logs are typically smaller (errors + context only)
- Monitor disk usage: `du -sh logs/jenkins-builds/`

### Multi-Instance Support

When using multiple Jenkins instances, logs are still organized by job name:

```
logs/
├── jenkins-builds/
│   ├── ci_build/                    # Could be from jenkins1.example.com
│   │   └── 8320/
│   │       ├── metadata.json        # Contains jenkins_url field
│   │       └── console.log
│   └── ci_build/                    # Or from jenkins2.example.com
│       └── 8320/
│           ├── metadata.json        # Different jenkins_url
│           └── console.log
```

**Note:** If the same job name and build number exist on different Jenkins instances, the logs will be organized by job name. Check the `jenkins_url` field in `metadata.json` to identify the source instance.

### Troubleshooting

**Logs not being saved:**
1. Check `JENKINS_ENABLED=true` in `.env`
2. Verify webhook is reaching the server (check `application.log`)
3. Ensure write permissions on `logs/` directory
4. Check `JENKINS_SAVE_TO_FILE=true` (if API posting is enabled)

**Missing stage logs:**
- Stage logs are only created for failed stages by default
- Check `metadata.json` to see which stages failed
- Successful stages only appear in `console.log`

**Large console.log files:**
- Files over 100MB indicate verbose build output
- Consider Jenkins-side log filtering
- System automatically handles large logs with streaming (won't crash)

## 3.5 API Posting Setup

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

## 3.6 Log Filtering Configuration

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

## 3.7 Configuration Examples & Scenarios

<details>
<summary><b>Scenario 1: Production - Failed Logs Only</b></summary>

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

</details>

<details>
<summary><b>Scenario 2: Development - Specific Projects Only</b></summary>

**Goal:** Track only development projects.

```bash
# GitLab Configuration
GITLAB_URL=https://gitlab.com
GITLAB_TOKEN=glpat-xxxxxxxxxxxxxxxxxxxx

# Project Filtering
LOG_SAVE_PROJECTS=123,456,789  # Dev project IDs

# All other projects ignored
```

</details>

<details>
<summary><b>Scenario 3: CI/CD Monitoring - All Pipelines, Failed Jobs</b></summary>

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

</details>

<details>
<summary><b>Scenario 4: API Posting with File Fallback</b></summary>

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

</details>

<details>
<summary><b>Scenario 5: Dual Mode - Maximum Reliability</b></summary>

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

</details>

<details>
<summary><b>Scenario 6: Multi-Platform - GitLab + Jenkins</b></summary>

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

**Note:** When using multiple Jenkins instances, create a `jenkins_instances.json` file to configure credentials for each instance. See [Jenkins Multi-Instance Support](#jenkins-multi-instance-support) for details.

</details>

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
sudo vi /etc/systemd/system/gitlab-log-extractor.service
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

<details>
<summary><h2>5.3 Database Maintenance</h2></summary>

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

</details>

<details>
<summary><h2>5.4 Troubleshooting & Common Issues</h2></summary>



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

</details>

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

---

# 7. Debugging and Validation

This section provides comprehensive debugging techniques for troubleshooting the Log Extractor system, covering container operations, log analysis, and both GitLab and Jenkins integrations.

## 7.1 Container Debugging

### Check Container Status

```bash
# Quick status check
bfapython manage_container.py status

# Detailed Docker status
docker ps -a | grep bfa-gitlab-pipeline-extractor

# Check container health
docker inspect bfa-gitlab-pipeline-extractor --format='{{.State.Status}}'

# View container resource usage
docker stats bfa-gitlab-pipeline-extractor --no-stream
```

### Container Logs

```bash
# Follow live logs
bfapython manage_container.py logs

# View logs without following
bfapython manage_container.py logs --no-follow

# View last N lines
docker logs --tail 100 bfa-gitlab-pipeline-extractor

# View logs with timestamps
docker logs --timestamps bfa-gitlab-pipeline-extractor

# View logs since specific time
docker logs --since "2024-01-01T10:00:00" bfa-gitlab-pipeline-extractor

# Filter container logs for errors
docker logs bfa-gitlab-pipeline-extractor 2>&1 | grep -i error
```

### Container Restart and Recovery

```bash
# Graceful restart
bfapython manage_container.py restart

# Force stop and start
bfapython manage_container.py stop
bfapython manage_container.py start --yes

# Remove and rebuild (nuclear option)
bfapython manage_container.py remove --force
bfapython manage_container.py build
bfapython manage_container.py start --yes
```

### Container Network Debugging

```bash
# Check container port bindings
docker port bfa-gitlab-pipeline-extractor

# Test webhook endpoint from host
curl -X POST http://localhost:8000/webhook/gitlab \
  -H "Content-Type: application/json" \
  -d '{"test": "payload"}'

# Test health endpoint
curl http://localhost:8000/health

# Check container network settings
docker inspect bfa-gitlab-pipeline-extractor --format='{{.NetworkSettings.Ports}}'
```

## 7.2 Inside Container Debugging

### Access Container Shell

```bash
# Enter running container
docker exec -it bfa-gitlab-pipeline-extractor /bin/bash

# Run command in container
docker exec bfa-gitlab-pipeline-extractor ls -la /app/logs

# Check Python environment
docker exec bfa-gitlab-pipeline-extractor python --version
docker exec bfa-gitlab-pipeline-extractor pip list
```

### Check Configuration Inside Container

```bash
# View loaded environment variables
docker exec bfa-gitlab-pipeline-extractor env | grep -E "GITLAB|JENKINS|BFA|LOG|API"

# Verify .env file is mounted
docker exec bfa-gitlab-pipeline-extractor cat /app/.env

# Check jenkins_instances.json (if using multi-instance)
docker exec bfa-gitlab-pipeline-extractor cat /app/jenkins_instances.json 2>/dev/null || echo "Not configured"
```

### Test API Connectivity from Container

```bash
# Test GitLab API connectivity
docker exec bfa-gitlab-pipeline-extractor curl -s -o /dev/null -w "%{http_code}" \
  -H "PRIVATE-TOKEN: $GITLAB_TOKEN" \
  "$GITLAB_URL/api/v4/projects"

# Test Jenkins API connectivity
docker exec bfa-gitlab-pipeline-extractor curl -s -o /dev/null -w "%{http_code}" \
  -u "$JENKINS_USER:$JENKINS_API_TOKEN" \
  "$JENKINS_URL/api/json"

# Test BFA API connectivity
docker exec bfa-gitlab-pipeline-extractor curl -s -o /dev/null -w "%{http_code}" \
  "http://$BFA_HOST:8000/health"
```

### Check Disk Usage Inside Container

```bash
# Check logs directory size
docker exec bfa-gitlab-pipeline-extractor du -sh /app/logs/

# List log files by size
docker exec bfa-gitlab-pipeline-extractor find /app/logs -type f -name "*.log" -exec ls -lh {} \; | sort -k5 -h

# Check available disk space
docker exec bfa-gitlab-pipeline-extractor df -h /app/logs
```

## 7.3 Log File Analysis

### Application Log Locations

| Log File | Description | Location |
|----------|-------------|----------|
| `application.log` | Main application logs | `logs/application.log` |
| `api-requests.log` | API request/response logs | `logs/api-requests.log` |
| `monitoring.db` | SQLite tracking database | `logs/monitoring.db` |

### Log Format Understanding

The application uses pipe-delimited format:
```
TIMESTAMP | LEVEL | MODULE | REQUEST_ID | MESSAGE | key=value pairs
```

Example:
```
2024-01-15 10:30:45.123 | INFO  | src.webhook_listener | a1b2c3d4 | Webhook received | event=Pipeline Hook
```

### Filtering Application Logs

```bash
# View all ERROR level logs
grep "| ERROR |" logs/application.log

# View WARNING and above
grep -E "\| (WARNING|ERROR|CRITICAL) \|" logs/application.log

# Filter by specific module
grep "src.jenkins_log_fetcher" logs/application.log

# Filter by request ID
grep "a1b2c3d4" logs/application.log

# View logs from specific time range
awk '/2024-01-15 10:30/,/2024-01-15 10:45/' logs/application.log

# Count errors by module
grep "| ERROR |" logs/application.log | awk -F'|' '{print $3}' | sort | uniq -c | sort -rn
```

### Finding Specific Pipeline Logs

```bash
# Find all logs for a specific pipeline ID
grep "pipeline_id=12345" logs/application.log

# Find all logs for a specific project
grep "project=my-project" logs/application.log
# Or by project ID
grep "project_id=789" logs/application.log

# Find all failed pipeline processing
grep "status=error" logs/application.log | grep "pipeline"

# List all pipeline directories
ls -la logs/ | grep -E "^d.*_[0-9]+$"

# Find specific pipeline log files
find logs/ -type d -name "pipeline_12345" -exec ls -la {} \;
```

### Finding Jenkins Build Logs

```bash
# Find all Jenkins build logs
ls -la logs/jenkins-builds/

# Find specific job logs
find logs/jenkins-builds/ -type d -name "my-job-name"

# Find all failed stage logs
find logs/jenkins-builds/ -name "stage_*.log"

# View Jenkins build metadata
find logs/jenkins-builds/ -name "metadata.json" -exec cat {} \; | jq .
```

### API Request Log Analysis

```bash
# View all API requests
cat logs/api-requests.log

# Filter by response status code
grep "response_status=200" logs/api-requests.log
grep "response_status=5" logs/api-requests.log  # 5xx errors

# Filter by endpoint
grep "/webhook/gitlab" logs/api-requests.log
grep "/webhook/jenkins" logs/api-requests.log

# Check API post failures
grep "API post failed" logs/application.log
```

## 7.4 GitLab-Specific Debugging

### Validate GitLab Webhook Configuration

```bash
# Test GitLab token permissions
curl -s -H "PRIVATE-TOKEN: $GITLAB_TOKEN" \
  "$GITLAB_URL/api/v4/user" | jq '.username'

# List accessible projects
curl -s -H "PRIVATE-TOKEN: $GITLAB_TOKEN" \
  "$GITLAB_URL/api/v4/projects?membership=true&per_page=5" | jq '.[].name'

# Test fetching a specific pipeline
curl -s -H "PRIVATE-TOKEN: $GITLAB_TOKEN" \
  "$GITLAB_URL/api/v4/projects/123/pipelines/456" | jq .
```

### Test GitLab Webhook Endpoint

```bash
# Send test webhook (GitLab format)
bfapython manage_container.py test

# Manual test with curl
curl -X POST http://localhost:8000/webhook/gitlab \
  -H "Content-Type: application/json" \
  -H "X-Gitlab-Event: Pipeline Hook" \
  -d '{
    "object_kind": "pipeline",
    "object_attributes": {"id": 12345, "status": "failed"},
    "project": {"id": 100, "name": "test-project"},
    "builds": []
  }'
```

### Debug GitLab Pipeline Processing

```bash
# Find all GitLab webhook events in logs
grep "X-Gitlab-Event" logs/application.log

# Track a specific pipeline through the system
PIPELINE_ID=12345
grep "$PIPELINE_ID" logs/application.log | head -50

# Check for job filtering
grep "Filtering jobs" logs/application.log

# Check for log fetch errors
grep "Failed to fetch log for job" logs/application.log
```

## 7.5 Jenkins-Specific Debugging

### Validate Jenkins Configuration

```bash
# Test Jenkins API connectivity
curl -s -u "$JENKINS_USER:$JENKINS_API_TOKEN" \
  "$JENKINS_URL/api/json" | jq '.mode'

# List Jenkins jobs
curl -s -u "$JENKINS_USER:$JENKINS_API_TOKEN" \
  "$JENKINS_URL/api/json?tree=jobs[name]" | jq '.jobs[].name'

# Test Blue Ocean API (if available)
curl -s -u "$JENKINS_USER:$JENKINS_API_TOKEN" \
  "$JENKINS_URL/blue/rest/organizations/jenkins/pipelines/" | jq '.[].name'
```

### Test Jenkins Webhook Endpoint

```bash
# Send test webhook (Jenkins format)
bfapython manage_container.py test --jenkins

# Send with specific Jenkins URL (multi-instance)
bfapython manage_container.py test --jenkins --jenkins-url https://jenkins.example.com

# Manual test with curl
curl -X POST http://localhost:8000/webhook/jenkins \
  -H "Content-Type: application/json" \
  -d '{
    "jenkins_url": "https://jenkins.example.com",
    "job_name": "my-pipeline",
    "build_number": 42,
    "build_status": "FAILURE"
  }'
```

### Debug Jenkins Build Processing

```bash
# Find all Jenkins webhook events
grep "Jenkins webhook received" logs/application.log

# Track a specific build
JOB_NAME="my-pipeline"
BUILD_NUM=42
grep "$JOB_NAME" logs/application.log | grep "$BUILD_NUM"

# Check for Blue Ocean API errors
grep "Blue Ocean" logs/application.log | grep -i error

# Check console log fetch
grep "Fetching console log" logs/application.log

# Check stage extraction
grep "Extracting failed stages" logs/application.log
```

### Jenkins Multi-Instance Debugging

```bash
# Check jenkins_instances.json loading
grep "Loading Jenkins instances" logs/application.log

# Check instance matching
grep "Matched Jenkins instance" logs/application.log

# Verify instance configuration
cat jenkins_instances.json | jq '.instances[].jenkins_url'
```

## 7.6 Monitoring Dashboard Debugging

### Check Monitoring Database

```bash
# View dashboard summary
bfapython scripts/monitor_dashboard.py

# View recent requests
bfapython scripts/monitor_dashboard.py --recent 50

# View specific pipeline history
bfapython scripts/monitor_dashboard.py --pipeline 12345

# Export data for analysis
bfapython scripts/monitor_dashboard.py --export debug_export.csv

# Query database directly
sqlite3 logs/monitoring.db "SELECT * FROM webhook_requests ORDER BY timestamp DESC LIMIT 10;"

# Get error statistics
sqlite3 logs/monitoring.db "SELECT status, COUNT(*) FROM webhook_requests GROUP BY status;"

# Find slow requests
sqlite3 logs/monitoring.db "SELECT * FROM webhook_requests WHERE processing_time > 30 ORDER BY processing_time DESC LIMIT 10;"
```

### Monitor Real-Time Activity

```bash
# Watch for new webhook requests (follow application log)
tail -f logs/application.log | grep "Webhook received"

# Monitor processing status
watch -n 5 'sqlite3 logs/monitoring.db "SELECT status, COUNT(*) as cnt FROM webhook_requests WHERE timestamp > datetime(\"now\", \"-1 hour\") GROUP BY status;"'

# Count requests per minute
sqlite3 logs/monitoring.db "SELECT strftime('%Y-%m-%d %H:%M', timestamp) as minute, COUNT(*) FROM webhook_requests GROUP BY minute ORDER BY minute DESC LIMIT 20;"
```

## 7.7 Configuration Validation

### Validate Full Configuration

```bash
# Display and validate configuration
bfapython manage_container.py config

# Quiet validation (exit code only)
bfapython manage_container.py config --validate-only
echo "Exit code: $?"

# Check specific environment file
bfapython manage_container.py config --env-file .env.production
```

### Common Configuration Issues

| Issue | Symptom | Solution |
|-------|---------|----------|
| Invalid GITLAB_URL | "Invalid URL format" error | Ensure URL starts with http:// or https:// |
| Short GITLAB_TOKEN | "Token too short" error | Generate new token with minimum 10 characters |
| Invalid WEBHOOK_PORT | Port binding error | Use port between 1-65535 |
| Missing BFA_HOST | API posting fails | Set BFA_HOST when API_POST_ENABLED=true |
| Jenkins auth failure | 401 errors in logs | Verify JENKINS_USER and JENKINS_API_TOKEN |

### Test Configuration Without Starting

```bash
# Python validation script
python3 -c "
from src.config_loader import ConfigLoader
try:
    config = ConfigLoader.load()
    print('Configuration valid!')
    print(f'GitLab URL: {config.gitlab_url}')
    print(f'Jenkins enabled: {config.jenkins_enabled}')
    print(f'API posting enabled: {config.api_post_enabled}')
except Exception as e:
    print(f'Configuration error: {e}')
"
```

## 7.8 Common Issues and Solutions

### GitLab Issues

| Issue | Possible Cause | Debug Steps |
|-------|---------------|-------------|
| No logs being saved | Pipeline status filtering | Check `LOG_SAVE_PIPELINE_STATUS` setting |
| Missing jobs | Job status filtering | Check `LOG_SAVE_JOB_STATUS` setting |
| 401 Unauthorized | Invalid GitLab token | Verify token with `curl` test above |
| Webhook not received | Network/firewall issue | Check container port binding and firewall |
| Slow processing | Large logs | Check `MAX_LOG_LINES` and `TAIL_LOG_LINES` |

### Jenkins Issues

| Issue | Possible Cause | Debug Steps |
|-------|---------------|-------------|
| No logs being saved | JENKINS_ENABLED=false | Set JENKINS_ENABLED=true in .env |
| 401 Unauthorized | Invalid credentials | Verify JENKINS_USER and JENKINS_API_TOKEN |
| Multi-instance not working | Missing jenkins_url in payload | Check Jenkinsfile sends jenkins_url |
| Blue Ocean API errors | Plugin not installed | Install Blue Ocean plugin or use console parsing |
| Handled failures appearing | Filter disabled | Set JENKINS_FILTER_HANDLED_FAILURES=true |

### API Posting Issues

| Issue | Possible Cause | Debug Steps |
|-------|---------------|-------------|
| API post timeout | Slow API server | Increase API_POST_TIMEOUT |
| Connection refused | Wrong BFA_HOST | Verify BFA_HOST is reachable |
| 401 Unauthorized | Invalid BFA_SECRET_KEY | Check JWT token generation |
| Fallback to file | API failures | Check logs for specific error messages |

## 7.9 Performance Debugging

### Identify Slow Operations

```bash
# Find slow pipeline processing
grep "processing_time" logs/application.log | awk -F'processing_time=' '{print $2}' | sort -n | tail -20

# Check memory usage trend
docker stats bfa-gitlab-pipeline-extractor --no-stream --format "{{.MemUsage}}"

# Find large log files being processed
grep "Log size" logs/application.log | sort -t'=' -k2 -n | tail -20
```

### Log Rotation and Cleanup

```bash
# Check log file sizes
du -sh logs/*.log logs/*.db

# Manual log rotation (if needed)
mv logs/application.log logs/application.log.$(date +%Y%m%d)
docker exec bfa-gitlab-pipeline-extractor kill -USR1 1  # Signal log rotation

# Clean old pipeline logs (older than 30 days)
find logs/ -type d -name "pipeline_*" -mtime +30 -exec rm -rf {} \;
```

---

# Appendix A: Comprehensive Jenkins Integration Guide

## A.1 Jenkins Overview & Architecture

The Jenkins integration provides:
- Automatic build log extraction from Jenkins
- Console log parsing to identify stages and parallel execution
- Blue Ocean API support for better stage information
- Structured log data posting to your API endpoint

## A.2 Detailed Jenkins Configuration

### Step 1: Generate Jenkins API Token

**In Jenkins Web UI:**
1. Log into Jenkins
2. Click your username (top right) → **Configure**
3. Scroll to **API Token** section
4. Click **Add new Token**
5. Give it a name (e.g., "log-extractor")
6. Click **Generate**
7. **Important:** Copy the token immediately (it won't be shown again)

**Example Token:** `11a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5`

### Step 2: Configure Environment Variables

Add to your `.env` file:
```bash
# ============================================================================
# JENKINS INTEGRATION
# ============================================================================

# Enable Jenkins integration
JENKINS_ENABLED=true

# Jenkins connection details
JENKINS_URL=https://jenkins.example.com
JENKINS_USER=your_username
JENKINS_API_TOKEN=11a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5

# Optional: Webhook secret for validation
JENKINS_WEBHOOK_SECRET=your_secret_token_here

# API Posting (required for Jenkins integration)
API_POST_ENABLED=true
BFA_HOST=bfa-server.example.com
BFA_SECRET_KEY=your_bfa_secret_key
```

### Step 3: Test Jenkins Connectivity

```bash
# Test if you can reach Jenkins API
curl -u "your_username:your_api_token" \
    "https://jenkins.example.com/api/json"

# Expected: JSON response with Jenkins version info
```

### Step 4: Restart Log Extractor

```bash
./manage_container.py restart

# Check logs to verify Jenkins is enabled
./manage_container.py logs | grep "Jenkins"

# Expected output:
# 2025-12-30 10:15:00.138 | INFO | src.webhook_listener | N/A | 7. Jenkins integration: ENABLED
```

## A.3 Jenkinsfile Integration Examples

### Example 1: Basic Integration (All Builds)

```groovy
pipeline {
    agent any

    stages {
        stage('Build') {
            steps {
                echo "Building application..."
                sh './build.sh'
            }
        }

        stage('Test') {
            steps {
                echo "Running tests..."
                sh './test.sh'
            }
        }

        stage('Deploy') {
            steps {
                echo "Deploying..."
                sh './deploy.sh'
            }
        }
    }

    post {
        always {
            script {
                // Send webhook for ALL builds (success or failure)
                def webhookUrl = "http://your-log-extractor:8000/webhook/jenkins"
                def webhookSecret = "your_secret_token"

                def curlCommand = """curl -X POST ${webhookUrl} \\
                    -H 'Content-Type: application/json' \\
                    -H 'X-Jenkins-Token: ${webhookSecret}' \\
                    -d '{
                        "job_name": "${env.JOB_NAME}",
                        "build_number": ${env.BUILD_NUMBER},
                        "build_url": "${env.BUILD_URL}",
                        "status": "${currentBuild.result}",
                        "duration_ms": ${currentBuild.duration},
                        "timestamp": "${new Date().format('yyyy-MM-dd HH:mm:ss')}",
                        "jenkins_url": "${env.JENKINS_URL}"
                    }'"""

                try {
                    sh curlCommand
                    echo "✓ Webhook sent successfully"
                } catch (Exception e) {
                    echo "✗ ERROR: Failed to send webhook"
                    echo "Error: ${e.message}"
                    echo "Command attempted:"
                    echo curlCommand
                }
            }
        }
    }
}
```

### Example 2: Failed Builds Only (Recommended)

```groovy
pipeline {
    agent any

    stages {
        stage('Build') {
            steps {
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
                stage('E2E Tests') {
                    steps {
                        sh './test_e2e.sh'
                    }
                }
            }
        }

        stage('Deploy') {
            steps {
                sh './deploy.sh'
            }
        }
    }

    post {
        failure {
            script {
                // Only send webhook on FAILURES
                def webhookUrl = "http://your-log-extractor:8000/webhook/jenkins"
                def webhookSecret = "your_secret_token"

                def curlCommand = """curl -X POST ${webhookUrl} \\
                    -H 'Content-Type: application/json' \\
                    -H 'X-Jenkins-Token: ${webhookSecret}' \\
                    -d '{
                        "job_name": "${env.JOB_NAME}",
                        "build_number": ${env.BUILD_NUMBER},
                        "build_url": "${env.BUILD_URL}",
                        "status": "FAILURE",
                        "jenkins_url": "${env.JENKINS_URL}"
                    }'"""

                try {
                    sh curlCommand
                    echo "✓ Webhook sent successfully"
                } catch (Exception e) {
                    echo "✗ ERROR: Failed to send webhook"
                    echo "Error: ${e.message}"
                    echo "Command attempted:"
                    echo curlCommand
                }
            }
        }
    }
}
```

### Example 3: With Error Handling

```groovy
pipeline {
    agent any

    stages {
        stage('Build') {
            steps {
                sh './build.sh'
            }
        }
    }

    post {
        always {
            script {
                def webhookUrl = "http://your-log-extractor:8000/webhook/jenkins"
                def webhookSecret = "your_secret_token"

                def payload = """
                {
                    "job_name": "${env.JOB_NAME}",
                    "build_number": ${env.BUILD_NUMBER},
                    "build_url": "${env.BUILD_URL}",
                    "status": "${currentBuild.result}",
                    "jenkins_url": "${env.JENKINS_URL}"
                }
                """

                // Construct the curl command
                def curlCommand = """curl -X POST ${webhookUrl} \\
                    -H 'Content-Type: application/json' \\
                    -H 'X-Jenkins-Token: ${webhookSecret}' \\
                    -d '${payload}' \\
                    -w '%{http_code}' \\
                    -o /dev/null \\
                    -s"""

                try {
                    def response = sh(
                        script: curlCommand,
                        returnStdout: true
                    ).trim()

                    if (response == "200") {
                        echo "✓ Successfully sent webhook to log extractor"
                    } else {
                        echo "✗ WARNING: Webhook failed with HTTP ${response}"
                        echo "Command executed:"
                        echo curlCommand
                        echo "This does not affect your build status"
                    }
                } catch (Exception e) {
                    echo "✗ ERROR: Failed to send webhook to log extractor"
                    echo "Error: ${e.message}"
                    echo "Command attempted:"
                    echo curlCommand
                    echo "This does not affect your build status"
                }
            }
        }
    }
}
```

## A.4 Jenkins API Integration Details

### Webhook Payload Format

The webhook payload sent to the log extractor:
```json
{
  "source": "jenkins",
  "job_name": "my-app-pipeline",
  "build_number": 123,
  "build_url": "https://jenkins.example.com/job/my-app-pipeline/123/",
  "status": "FAILURE",
  "duration_ms": 45000,
  "timestamp": "2025-12-30T10:30:00Z",
  "jenkins_url": "https://jenkins.example.com"
}
```

### Console Log Parsing

The log extractor fetches and parses the console log to extract:

1. **Stages**: Individual pipeline stages
2. **Parallel Blocks**: Parallel execution within stages
3. **Timestamps**: Stage start/end times
4. **Status**: Success/failure of each stage

**Example Console Log:**
```
Started by user Admin
[Pipeline] Start of Pipeline
[Pipeline] stage
[Pipeline] { (Build)
[Pipeline] echo
Building application...
[Pipeline] sh
+ ./build.sh
Build successful
[Pipeline] }
[Pipeline] // stage
[Pipeline] stage
[Pipeline] { (Test)
[Pipeline] parallel
[Pipeline] { (Branch: Unit Tests)
[Pipeline] { (Branch: Integration Tests)
[Pipeline] echo
Running unit tests...
[Pipeline] echo
Running integration tests...
[Pipeline] }
[Pipeline] // parallel
[Pipeline] }
[Pipeline] // stage
```

**Parsed Output:**
```json
{
  "stages": [
    {
      "stage_name": "Build",
      "status": "SUCCESS",
      "duration_ms": 5000,
      "is_parallel": false,
      "log_content": "Building application...\nBuild successful"
    },
    {
      "stage_name": "Test",
      "status": "SUCCESS",
      "duration_ms": 15000,
      "is_parallel": true,
      "parallel_blocks": [
        {
          "block_name": "Unit Tests",
          "status": "SUCCESS",
          "log_content": "Running unit tests..."
        },
        {
          "block_name": "Integration Tests",
          "status": "SUCCESS",
          "log_content": "Running integration tests..."
        }
      ]
    }
  ]
}
```

## A.5 Jenkins Testing & Verification

### Step 1: Test Webhook Endpoint

```bash
# Verify log extractor is running
curl http://your-log-extractor:8000/health

# Expected response:
{
  "status": "healthy",
  "service": "gitlab-log-extractor",
  "version": "1.0.0"
}
```

### Step 2: Manual Webhook Test

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
{
  "status": "success",
  "message": "Jenkins build logs queued for extraction",
  "job_name": "test-pipeline",
  "build_number": 1,
  "request_id": "a1b2c3d4"
}
```

### Step 3: Verify in Application Logs

```bash
# Check application logs
tail -f logs/application.log | grep jenkins

# Expected output:
2025-12-30 10:35:15.456 | INFO | src.webhook_listener | d5e6f7g8 | Jenkins webhook received | job=test-pipeline build=1
2025-12-30 10:35:16.123 | INFO | src.jenkins_extractor | d5e6f7g8 | Fetching console log from Jenkins
2025-12-30 10:35:17.234 | INFO | src.jenkins_extractor | d5e6f7g8 | Parsed 3 stages from console log
2025-12-30 10:35:18.345 | INFO | src.api_poster | d5e6f7g8 | Posting Jenkins logs to API
2025-12-30 10:35:19.456 | INFO | src.api_poster | d5e6f7g8 | Successfully posted Jenkins build logs
```

### Step 4: Trigger Real Jenkins Build

1. Create a test pipeline in Jenkins with the webhook configured
2. Trigger a build (let it fail for testing)
3. Check the log extractor logs:

```bash
./manage_container.py logs | grep "Jenkins"

# You should see:
# - Webhook received
# - Console log fetched
# - Stages parsed
# - Data posted to API
```

## A.6 Jenkins Troubleshooting

### Issue 1: Jenkins API Authentication Fails

**Error:**
```
ERROR: Failed to fetch Jenkins console log: 401 Unauthorized
```

**Solutions:**

1. **Verify API Token:**
```bash
# Test your Jenkins credentials
curl -u "username:api_token" \
    "https://jenkins.example.com/api/json"

# Should return Jenkins info, not 401
```

2. **Check Token Hasn't Expired:**
- Go to Jenkins → Your Profile → Configure → API Token
- Check if token is listed
- If not, generate a new one

3. **Verify Username:**
```bash
# Must be your Jenkins username, not email
JENKINS_USER=johndoe  # NOT john@example.com
```

### Issue 2: Webhook Not Triggering

**Symptoms:**
- Jenkins build completes
- No logs in log extractor

**Debug Steps:**

1. **Check Jenkinsfile:**
```groovy
post {
    always {
        script {
            // Add echo for debugging
            echo "Sending webhook to log extractor..."

            def curlCommand = """curl -v -X POST http://your-log-extractor:8000/webhook/jenkins \\
                -H 'Content-Type: application/json' \\
                -H 'X-Jenkins-Token: your_secret' \\
                -d '{
                    "job_name": "${env.JOB_NAME}",
                    "build_number": ${env.BUILD_NUMBER},
                    "build_url": "${env.BUILD_URL}",
                    "status": "${currentBuild.result}"
                }'"""

            try {
                sh curlCommand
                echo "✓ Webhook sent successfully!"
            } catch (Exception e) {
                echo "✗ ERROR: Failed to send webhook"
                echo "Error: ${e.message}"
                echo "Command attempted:"
                echo curlCommand
            }
        }
    }
}
```

2. **Check Jenkins Console Output:**
- Open the build in Jenkins
- Go to Console Output
- Look for the webhook curl command output
- Check for errors

3. **Network Connectivity:**
```bash
# From Jenkins server, test connectivity
curl -I http://your-log-extractor:8000/health

# Should return 200 OK
```

### Issue 3: Console Log Parsing Fails

**Error:**
```
WARN: Failed to parse parallel blocks from console log
```

**Causes:**
- Non-standard Jenkins output
- Custom logging that interferes with parsing
- Very large console logs (>10MB)

**Solutions:**

1. **Check Console Log Size:**
```bash
# In Jenkins, check the console output size
# If > 10MB, consider reducing verbosity
```

2. **Simplify Logging:**
```groovy
// Reduce noise in console output
pipeline {
    options {
        // Limit console output
        timestamps()
        ansiColor('xterm')
    }
}
```

3. **Enable Debug Logging:**
```bash
# In .env
LOG_LEVEL=DEBUG

# Restart and check detailed parsing logs
```

### Issue 4: Parallel Blocks Not Detected

**Symptoms:**
- Parallel stages run in Jenkins
- But appear as single stage in extracted logs

**Solution:**

Ensure you're using declarative pipeline parallel syntax:
```groovy
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
```

NOT scripted pipeline:
```groovy
// This won't be parsed correctly
stage('Test') {
    steps {
        script {
            parallel (
                unitTest: { sh './test_unit.sh' },
                integrationTest: { sh './test_integration.sh' }
            )
        }
    }
}
```

## A.7 Jenkins Advanced Topics

### Blue Ocean API Integration

If Blue Ocean plugin is installed, the log extractor can use Blue Ocean API for better stage information:

**Benefits:**
- More accurate stage timing
- Better parallel block detection
- Stage duration in milliseconds
- Status per stage

**Blue Ocean API Endpoint:**
```
GET /blue/rest/organizations/jenkins/pipelines/{job_name}/runs/{build_number}/nodes/
```

**Example Response:**
```json
[
  {
    "id": "3",
    "displayName": "Build",
    "state": "FINISHED",
    "result": "SUCCESS",
    "durationInMillis": 5234,
    "startTime": "2025-12-30T10:00:00.000+0000"
  },
  {
    "id": "7",
    "displayName": "Test",
    "state": "FINISHED",
    "result": "SUCCESS",
    "durationInMillis": 15678,
    "startTime": "2025-12-30T10:00:05.234+0000"
  }
]
```

### Multi-Branch Pipeline Support

The log extractor supports multi-branch pipelines:

**Branch Information Included:**
```json
{
  "job_name": "my-app/feature-branch",
  "branch_name": "feature-branch",
  "build_number": 123
}
```

**Example Jenkinsfile for Multi-Branch:**
```groovy
pipeline {
    agent any

    stages {
        stage('Build') {
            steps {
                echo "Building branch: ${env.BRANCH_NAME}"
                sh './build.sh'
            }
        }
    }

    post {
        failure {
            script {
                def curlCommand = """curl -X POST http://your-log-extractor:8000/webhook/jenkins \\
                    -H 'Content-Type: application/json' \\
                    -d '{
                        "job_name": "${env.JOB_NAME}",
                        "branch_name": "${env.BRANCH_NAME}",
                        "build_number": ${env.BUILD_NUMBER},
                        "build_url": "${env.BUILD_URL}",
                        "status": "FAILURE"
                    }'"""

                try {
                    sh curlCommand
                    echo "✓ Webhook sent successfully"
                } catch (Exception e) {
                    echo "✗ ERROR: Failed to send webhook"
                    echo "Error: ${e.message}"
                    echo "Command attempted:"
                    echo curlCommand
                }
            }
        }
    }
}
```

### Pipeline Parameters

Include pipeline parameters in the webhook:

```groovy
pipeline {
    parameters {
        string(name: 'DEPLOY_ENV', defaultValue: 'staging', description: 'Deployment environment')
        booleanParam(name: 'RUN_TESTS', defaultValue: true, description: 'Run tests')
    }

    stages {
        stage('Deploy') {
            steps {
                echo "Deploying to ${params.DEPLOY_ENV}"
            }
        }
    }

    post {
        always {
            script {
                def curlCommand = """curl -X POST http://your-log-extractor:8000/webhook/jenkins \\
                    -H 'Content-Type: application/json' \\
                    -d '{
                        "job_name": "${env.JOB_NAME}",
                        "build_number": ${env.BUILD_NUMBER},
                        "build_url": "${env.BUILD_URL}",
                        "status": "${currentBuild.result}",
                        "parameters": {
                            "DEPLOY_ENV": "${params.DEPLOY_ENV}",
                            "RUN_TESTS": ${params.RUN_TESTS}
                        }
                    }'"""

                try {
                    sh curlCommand
                    echo "✓ Webhook sent successfully"
                } catch (Exception e) {
                    echo "✗ ERROR: Failed to send webhook"
                    echo "Error: ${e.message}"
                    echo "Command attempted:"
                    echo curlCommand
                }
            }
        }
    }
}
```

---
