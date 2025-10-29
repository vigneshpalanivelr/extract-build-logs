# Extensive Logging Implementation Plan

## Executive Summary

This document outlines a comprehensive logging strategy for the GitLab Pipeline Log Extraction System. The plan focuses on extensive, structured logging that provides visibility into all operations while maintaining performance and security.

**Current State:** Basic logging with 87 log statements (41 info, 25 error, 13 debug, 8 warning)

**Goal:** Comprehensive, structured logging with request tracing, performance metrics, and external integration support

---

## Table of Contents

- [Current State Analysis](#current-state-analysis)
- [Logging Objectives](#logging-objectives)
- [What to Log](#what-to-log)
- [Log Levels Strategy](#log-levels-strategy)
- [Log Format](#log-format)
- [Log Destinations](#log-destinations)
- [Security Considerations](#security-considerations)
- [Performance Considerations](#performance-considerations)
- [Log Rotation and Retention](#log-rotation-and-retention)
- [Docker-Specific Logging](#docker-specific-logging)
- [Request Tracing](#request-tracing)
- [Monitoring Integration](#monitoring-integration)
- [Configuration Options](#configuration-options)
- [Implementation Phases](#implementation-phases)
- [Testing Plan](#testing-plan)
- [Examples](#examples)

---

## Current State Analysis

### What We Have Now:

**File:** `src/webhook_listener.py`
```python
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('webhook_server.log')
    ]
)
```

**Distribution:**
- 41 info logs (47%)
- 25 error logs (29%)
- 13 debug logs (15%)
- 8 warning logs (9%)

**Issues:**
- ❌ No structured logging (JSON)
- ❌ No request correlation IDs
- ❌ No performance metrics logging
- ❌ Sensitive data not masked (GitLab tokens)
- ❌ No log rotation configured
- ❌ Fixed log file path (not container-friendly)
- ❌ No differentiation between access logs and application logs
- ❌ Multiple `logging.basicConfig()` calls across modules
- ❌ No external logging integration (ELK, Splunk, etc.)

**What Works:**
- ✅ Basic console + file logging
- ✅ Reasonable log level distribution
- ✅ Module-specific loggers (`__name__`)
- ✅ Configurable log level from environment

---

## Logging Objectives

### Primary Goals:

1. **Visibility**: See what the application is doing at any time
2. **Debuggability**: Quickly identify and diagnose issues
3. **Traceability**: Track requests from webhook to completion
4. **Performance**: Monitor operation timings and bottlenecks
5. **Security**: Log security events, mask sensitive data
6. **Compliance**: Audit trail for all operations
7. **Integration**: Support external log aggregation systems

### Success Metrics:

- Can trace any webhook request through entire pipeline
- Can identify performance bottlenecks from logs
- Can detect security issues from log patterns
- Logs don't impact performance (< 5% overhead)
- Easy to search and filter logs
- Sensitive data never appears in logs

---

## What to Log

### 1. Webhook Events (HIGH PRIORITY)

**When:**
- Webhook received
- Webhook validated
- Webhook rejected

**What:**
```
- Request ID (correlation ID)
- Timestamp
- Source IP
- Event type (Pipeline Hook, etc.)
- Project ID
- Pipeline ID
- Validation result
- Processing time
```

**Log Level:**
- INFO: Successful webhook
- WARNING: Validation warnings
- ERROR: Rejected webhooks

### 2. Pipeline Processing (HIGH PRIORITY)

**When:**
- Processing started
- Pipeline info extracted
- Job enumeration
- Processing completed/failed

**What:**
```
- Request ID
- Pipeline ID
- Project ID
- Pipeline type (main/child/MR)
- Number of jobs
- Processing stages
- Duration at each stage
- Final status
```

**Log Level:**
- INFO: Normal processing
- DEBUG: Detailed extraction info
- ERROR: Processing failures

### 3. GitLab API Calls (CRITICAL)

**When:**
- Before API call
- After API call
- On retry
- On failure

**What:**
```
- Request ID
- API endpoint (URL path only, no tokens)
- HTTP method
- Response status code
- Response time (ms)
- Retry attempt number
- Rate limit headers
- Error details
```

**Log Level:**
- DEBUG: All API calls
- WARNING: Rate limit approaching, retries
- ERROR: API failures

### 4. Storage Operations (MEDIUM PRIORITY)

**When:**
- Creating directories
- Writing log files
- Writing metadata
- File operations fail

**What:**
```
- Request ID
- Operation type (create_dir, write_file, etc.)
- File path (relative)
- File size
- Duration
- Success/failure
```

**Log Level:**
- DEBUG: All operations
- INFO: Summary (X files written)
- ERROR: Failures

### 5. Error Handling & Retries (HIGH PRIORITY)

**When:**
- Error caught
- Retry triggered
- Circuit breaker state change
- Retry exhausted

**What:**
```
- Request ID
- Error type/class
- Error message
- Stack trace (DEBUG level only)
- Retry attempt number
- Backoff duration
- Circuit breaker state
```

**Log Level:**
- WARNING: First retry
- ERROR: Retries exhausted
- CRITICAL: Circuit breaker open

### 6. Performance Metrics (MEDIUM PRIORITY)

**When:**
- Request starts
- Request completes
- Each processing stage

**What:**
```
- Request ID
- Stage name
- Duration (ms)
- Memory usage
- Queue depth
- Active requests
```

**Log Level:**
- INFO: Request summary
- DEBUG: Stage timings

### 7. Security Events (HIGH PRIORITY)

**When:**
- Authentication attempts
- Webhook validation failures
- Unusual activity detected
- Configuration changes

**What:**
```
- Event type
- Source IP
- User/token identifier (hashed)
- Success/failure
- Reason
```

**Log Level:**
- INFO: Successful auth
- WARNING: Failed attempts
- CRITICAL: Attack patterns detected

### 8. Application Lifecycle (LOW PRIORITY)

**When:**
- Application starts
- Configuration loaded
- Components initialized
- Shutdown initiated
- Graceful shutdown complete

**What:**
```
- Event type
- Configuration summary (no secrets)
- Component status
- Version information
```

**Log Level:**
- INFO: All lifecycle events

---

## Log Levels Strategy

### DEBUG
**When:** Development, troubleshooting
**Volume:** High (10x normal)
**Contents:**
- Detailed function entry/exit
- Variable values
- Full API requests/responses
- Stack traces
- Processing details

**Examples:**
```
DEBUG - Entering process_pipeline_event()
DEBUG - Extracted pipeline info: type=main, jobs=5
DEBUG - API request: GET /api/v4/projects/100/pipelines/12345
DEBUG - API response: 200 OK, body_size=2048 bytes
```

### INFO
**When:** Production normal operations
**Volume:** Medium
**Contents:**
- Request received/completed
- Successful operations
- Status changes
- Performance summaries

**Examples:**
```
INFO - Webhook received: request_id=abc123, pipeline_id=12345
INFO - Processing completed: request_id=abc123, duration=2.3s, jobs=5
INFO - Application started: version=1.0.0, port=8000
```

### WARNING
**When:** Recoverable issues
**Volume:** Low
**Contents:**
- Retries triggered
- Rate limiting
- Configuration issues (using defaults)
- Validation warnings
- Performance degradation

**Examples:**
```
WARNING - API call failed, retrying: attempt=1/3, error=ConnectionTimeout
WARNING - Rate limit approaching: remaining=50/300
WARNING - Using default value: RETRY_DELAY not set, using 2s
```

### ERROR
**When:** Operation failures
**Volume:** Very Low (hopefully!)
**Contents:**
- Failed operations
- Unhandled errors
- Data validation failures
- Resource unavailable

**Examples:**
```
ERROR - Failed to fetch logs: request_id=abc123, job_id=1001, error=404 Not Found
ERROR - Storage write failed: path=/app/logs/project_100, error=Permission denied
ERROR - Webhook validation failed: missing X-Gitlab-Event header
```

### CRITICAL
**When:** System failures
**Volume:** Extremely Rare
**Contents:**
- Application crash
- Database corruption
- Circuit breaker open
- Unrecoverable errors

**Examples:**
```
CRITICAL - Database connection lost, cannot track requests
CRITICAL - Circuit breaker opened: GitLab API failures exceeding threshold
CRITICAL - Fatal configuration error: GITLAB_TOKEN not set
```

---

## Log Format

### Option 1: Structured JSON (RECOMMENDED)

**Format:**
```json
{
  "timestamp": "2024-01-01T10:15:30.123Z",
  "level": "INFO",
  "logger": "webhook_listener",
  "request_id": "abc123def456",
  "message": "Webhook received",
  "context": {
    "pipeline_id": 12345,
    "project_id": 100,
    "event_type": "Pipeline Hook",
    "source_ip": "192.168.1.100"
  },
  "performance": {
    "duration_ms": 25
  }
}
```

**Advantages:**
- ✅ Easy to parse and query
- ✅ Structured data for analytics
- ✅ Great for log aggregation (ELK, Splunk)
- ✅ Consistent format
- ✅ Machine-readable

**Disadvantages:**
- ❌ Less human-readable
- ❌ Larger file size

**Use Case:** Production, log aggregation, automated analysis

### Option 2: Enhanced Plain Text

**Format:**
```
2024-01-01 10:15:30.123 [INFO] [webhook_listener] [request_id=abc123] Webhook received pipeline_id=12345 project_id=100 event_type="Pipeline Hook" source_ip=192.168.1.100 duration_ms=25
```

**Advantages:**
- ✅ Human-readable
- ✅ Greppable
- ✅ Smaller file size
- ✅ Good for console output

**Disadvantages:**
- ❌ Harder to parse programmatically
- ❌ Inconsistent structure

**Use Case:** Development, console logs, simple deployments

### Hybrid Approach (RECOMMENDED)

**Console:** Plain text (human-readable)
**File:** JSON (structured, queryable)
**External:** JSON (ELK, Splunk, etc.)

---

## Log Destinations

### 1. Console (stdout/stderr)

**Purpose:** Real-time monitoring, Docker logs
**Format:** Plain text
**Level:** INFO and above
**Volume:** Medium

**Configuration:**
```python
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_formatter = logging.Formatter(
    '%(asctime)s [%(levelname)s] [%(name)s] %(message)s'
)
console_handler.setFormatter(console_formatter)
```

### 2. Application Log File

**Purpose:** Application events and errors
**Format:** JSON
**Level:** DEBUG (configurable)
**Volume:** High
**Location:** `/app/logs/application.log` (in container)

**Configuration:**
```python
file_handler = RotatingFileHandler(
    '/app/logs/application.log',
    maxBytes=100*1024*1024,  # 100MB
    backupCount=10
)
```

### 3. Access Log File

**Purpose:** All webhook requests
**Format:** JSON
**Level:** INFO
**Volume:** Medium (one per webhook)
**Location:** `/app/logs/access.log`

**Example Entry:**
```json
{
  "timestamp": "2024-01-01T10:15:30.123Z",
  "request_id": "abc123",
  "method": "POST",
  "path": "/webhook",
  "status": 200,
  "duration_ms": 125,
  "source_ip": "192.168.1.100",
  "pipeline_id": 12345,
  "project_id": 100
}
```

### 4. Error Log File

**Purpose:** Errors and critical issues only
**Format:** JSON with stack traces
**Level:** ERROR and above
**Volume:** Low
**Location:** `/app/logs/errors.log`

### 5. Performance Log File

**Purpose:** Performance metrics and timings
**Format:** JSON
**Level:** INFO
**Volume:** Medium
**Location:** `/app/logs/performance.log`

**Example Entry:**
```json
{
  "timestamp": "2024-01-01T10:15:30.123Z",
  "request_id": "abc123",
  "operation": "fetch_logs",
  "duration_ms": 1234,
  "jobs_processed": 5,
  "api_calls": 6,
  "bytes_written": 524288
}
```

### 6. External Systems (Optional)

**Options:**
- **ELK Stack** (Elasticsearch, Logstash, Kibana)
- **Splunk**
- **Datadog**
- **CloudWatch** (AWS)
- **Stackdriver** (GCP)
- **Syslog server**

**Integration:** Via logging handlers or log shipping (Filebeat, Fluentd)

---

## Security Considerations

### 1. Sensitive Data Masking

**MUST MASK:**
- ✅ GitLab tokens (`GITLAB_TOKEN`)
- ✅ Webhook secrets (`WEBHOOK_SECRET`)
- ✅ API authentication headers
- ✅ Full URLs with tokens
- ✅ User passwords (if any)

**Example:**
```python
def mask_token(token: str) -> str:
    """Mask token, showing only first/last 4 chars"""
    if not token or len(token) < 12:
        return "***MASKED***"
    return f"{token[:4]}...{token[-4:]}"

# Before
logger.info(f"Using token: {config.gitlab_token}")

# After
logger.info(f"Using token: {mask_token(config.gitlab_token)}")
# Output: "Using token: glpat...x9z2"
```

### 2. IP Address Logging

**Options:**
- Log full IP (privacy concern)
- Log masked IP (192.168.xxx.xxx)
- Log hashed IP
- Don't log IP

**Recommendation:** Log full IP but implement retention policy (30 days)

### 3. User Data

**Guideline:**
- Log user IDs (not personal info)
- Hash email addresses if needed
- Never log passwords
- Comply with GDPR if applicable

### 4. Log File Permissions

**Requirements:**
- Application logs: 640 (owner read/write, group read)
- Log directory: 750 (owner rwx, group rx)
- Owner: appuser (UID 1000)
- Group: appuser (GID 1000)

---

## Performance Considerations

### 1. Logging Overhead

**Target:** < 5% performance impact

**Strategies:**
- Use lazy formatting: `logger.debug("Value: %s", value)` not `logger.debug(f"Value: {value}")`
- Async logging handlers for file I/O
- Batch writes where possible
- Rate limiting for high-frequency logs

### 2. Log Volume Management

**Expected Volume (100-200 webhooks/day):**
- Access logs: ~20KB/day
- Application logs: ~500KB/day (INFO level)
- Debug logs: ~5MB/day (DEBUG level)
- Total: ~525KB/day normal, ~5MB/day debug

**Annual:** ~190MB (normal), ~1.8GB (debug)

**Recommendation:** Safe to keep DEBUG on with proper rotation

### 3. Asynchronous Logging

**Implementation:**
```python
from logging.handlers import QueueHandler, QueueListener
import queue

# Create queue for async logging
log_queue = queue.Queue(-1)  # No size limit
queue_handler = QueueHandler(log_queue)

# Background listener handles actual I/O
listener = QueueListener(
    log_queue,
    console_handler,
    file_handler,
    respect_handler_level=True
)
listener.start()
```

**Benefits:**
- Non-blocking log writes
- Better performance
- No impact on request latency

### 4. Conditional Verbose Logging

**Pattern:**
```python
if logger.isEnabledFor(logging.DEBUG):
    # Expensive operation only if DEBUG is enabled
    detailed_info = expensive_debug_function()
    logger.debug("Details: %s", detailed_info)
```

---

## Log Rotation and Retention

### 1. Rotation Strategy

**Application Logs:**
- Max size: 100MB per file
- Keep: 10 files
- Total: 1GB max
- Rotation: When file reaches 100MB

**Access Logs:**
- Max size: 50MB per file
- Keep: 20 files
- Total: 1GB max
- Rotation: When file reaches 50MB

**Error Logs:**
- Max size: 50MB per file
- Keep: 10 files
- Total: 500MB max
- Rotation: When file reaches 50MB

**Implementation:**
```python
from logging.handlers import RotatingFileHandler

handler = RotatingFileHandler(
    filename='/app/logs/application.log',
    maxBytes=100 * 1024 * 1024,  # 100MB
    backupCount=10,
    encoding='utf-8'
)
```

### 2. Time-Based Rotation (Alternative)

**For production with high volume:**
```python
from logging.handlers import TimedRotatingFileHandler

handler = TimedRotatingFileHandler(
    filename='/app/logs/application.log',
    when='midnight',  # Rotate daily
    interval=1,
    backupCount=30,  # Keep 30 days
    encoding='utf-8'
)
```

### 3. Compression (Optional)

**Using logrotate (Linux):**
```
/app/logs/*.log {
    daily
    rotate 30
    compress
    delaycompress
    notifempty
    create 640 appuser appuser
    sharedscripts
    postrotate
        # Signal application to reopen log files
        kill -USR1 $(cat /var/run/app.pid)
    endscript
}
```

### 4. Retention Policy

**Recommendation:**
- Active logs: In container (30 days)
- Archives: Backed up to external storage (1 year)
- Compliance logs: As required by policy
- Debug logs: 7 days only

---

## Docker-Specific Logging

### 1. Container Logs (stdout/stderr)

**Docker captures all stdout/stderr**

**View logs:**
```bash
# Real-time
docker logs -f gitlab-pipeline-extractor

# Last 100 lines
docker logs --tail 100 gitlab-pipeline-extractor

# Since timestamp
docker logs --since 2024-01-01T10:00:00 gitlab-pipeline-extractor

# With timestamps
docker logs -t gitlab-pipeline-extractor
```

### 2. Docker Logging Drivers

**Current:** Default JSON file driver

**Options:**

**a) JSON File (Default):**
```yaml
# docker-compose.yml
logging:
  driver: "json-file"
  options:
    max-size: "10m"
    max-file: "3"
```

**b) Syslog:**
```yaml
logging:
  driver: "syslog"
  options:
    syslog-address: "tcp://192.168.1.100:514"
    tag: "gitlab-pipeline-extractor"
```

**c) Fluentd:**
```yaml
logging:
  driver: "fluentd"
  options:
    fluentd-address: "localhost:24224"
    tag: "docker.{{.Name}}"
```

**d) Journald (systemd):**
```yaml
logging:
  driver: "journald"
  options:
    tag: "gitlab-pipeline-extractor"
```

### 3. Volume-Mounted Logs

**Current Setup:**
```bash
-v ./logs:/app/logs
```

**Benefits:**
- ✅ Logs persist outside container
- ✅ Easy to access from host
- ✅ Can be backed up independently
- ✅ No container size bloat

**Structure:**
```
./logs/
├── application.log
├── application.log.1
├── application.log.2
├── access.log
├── errors.log
├── performance.log
├── monitoring.db
└── project_*/
    └── pipeline_*/
```

### 4. ELK Stack Integration

**Architecture:**
```
Container → stdout → Docker JSON → Filebeat → Logstash → Elasticsearch → Kibana
                                                                              ↓
Container → /app/logs/*.log ────────────────────────────────────> Filebeat ─┘
```

**Filebeat Configuration:**
```yaml
filebeat.inputs:
  - type: container
    paths:
      - /var/lib/docker/containers/*/*.log

  - type: log
    paths:
      - /path/to/logs/*.log
    json.keys_under_root: true
    json.add_error_key: true

output.logstash:
  hosts: ["logstash:5044"]
```

---

## Request Tracing

### 1. Correlation IDs

**Purpose:** Track a single webhook request through the entire pipeline

**Implementation:**
```python
import uuid

def generate_request_id():
    return str(uuid.uuid4())[:8]

# In webhook handler
request_id = generate_request_id()
logger.info("Webhook received", extra={"request_id": request_id})
```

**Pass through all functions:**
```python
def process_pipeline_event(pipeline_info, request_id):
    logger.info("Processing pipeline", extra={"request_id": request_id})
    logs = fetch_logs(project_id, pipeline_id, request_id)
    store_logs(logs, request_id)
```

### 2. Context Propagation

**Using contextvars (Python 3.7+):**
```python
from contextvars import ContextVar

request_id_var = ContextVar('request_id', default=None)

class RequestIdFilter(logging.Filter):
    def filter(self, record):
        record.request_id = request_id_var.get() or 'N/A'
        return True

# Set in webhook handler
request_id_var.set(generate_request_id())

# Automatically included in all logs
logger.info("Any message")  # Will include request_id
```

### 3. Distributed Tracing (Advanced)

**Using OpenTelemetry:**
```python
from opentelemetry import trace
from opentelemetry.instrumentation.logging import LoggingInstrumentor

tracer = trace.get_tracer(__name__)

@tracer.start_as_current_span("process_pipeline")
def process_pipeline_event(pipeline_info):
    # Span automatically added to logs
    logger.info("Processing pipeline")
```

---

## Monitoring Integration

### 1. Metrics from Logs

**Extract metrics:**
- Request rate (webhooks/minute)
- Error rate (errors/minute)
- Average response time
- API call latency
- Success/failure ratio

### 2. Alerting Triggers

**Alert on:**
- Error rate > 5%
- Response time > 10s
- API failures > 3 consecutive
- Circuit breaker opens
- Disk space < 10%

### 3. Prometheus Integration (Optional)

**Export metrics:**
```python
from prometheus_client import Counter, Histogram

webhook_requests = Counter('webhook_requests_total', 'Total webhook requests')
request_duration = Histogram('request_duration_seconds', 'Request duration')

@request_duration.time()
def process_webhook():
    webhook_requests.inc()
    # ... process ...
```

---

## Configuration Options

### Environment Variables

```bash
# Logging Configuration
LOG_LEVEL=INFO              # DEBUG, INFO, WARNING, ERROR, CRITICAL
LOG_FORMAT=json             # json, text, hybrid
LOG_DIR=/app/logs           # Log directory
LOG_MAX_SIZE=100            # Max log file size (MB)
LOG_BACKUP_COUNT=10         # Number of backup files
LOG_ROTATION=size           # size, time
LOG_COMPRESSION=true        # Compress rotated logs

# Specific Log Files
LOG_ACCESS_ENABLED=true     # Enable access logging
LOG_PERFORMANCE_ENABLED=true # Enable performance logging
LOG_ERRORS_ONLY=false       # Error log file only

# External Logging
LOG_SYSLOG_ENABLED=false    # Enable syslog
LOG_SYSLOG_ADDRESS=localhost:514
LOG_ELK_ENABLED=false       # Enable ELK integration
LOG_ELK_HOST=localhost:9200

# Security
LOG_MASK_TOKENS=true        # Mask sensitive tokens
LOG_MASK_IPS=false          # Mask IP addresses

# Performance
LOG_ASYNC=true              # Use async logging
LOG_BUFFER_SIZE=1000        # Async buffer size
```

### Configuration File (Alternative)

**logging_config.yaml:**
```yaml
version: 1
disable_existing_loggers: false

formatters:
  json:
    class: pythonjsonlogger.jsonlogger.JsonFormatter
    format: "%(timestamp)s %(level)s %(name)s %(message)s"

  text:
    format: "%(asctime)s [%(levelname)s] [%(name)s] [%(request_id)s] %(message)s"

handlers:
  console:
    class: logging.StreamHandler
    level: INFO
    formatter: text
    stream: ext://sys.stdout

  file:
    class: logging.handlers.RotatingFileHandler
    level: DEBUG
    formatter: json
    filename: /app/logs/application.log
    maxBytes: 104857600  # 100MB
    backupCount: 10

  access:
    class: logging.handlers.RotatingFileHandler
    level: INFO
    formatter: json
    filename: /app/logs/access.log
    maxBytes: 52428800  # 50MB
    backupCount: 20

root:
  level: DEBUG
  handlers: [console, file]

loggers:
  webhook_listener:
    level: INFO
    handlers: [access]
    propagate: false
```

---

## Implementation Phases

### Phase 1: Foundation (Week 1)

**Tasks:**
1. Create centralized logging configuration module
2. Implement structured JSON logging
3. Add request ID generation and propagation
4. Set up log rotation
5. Add sensitive data masking

**Files:**
- `src/logging_config.py` (new)
- Update all modules to use centralized config

**Deliverables:**
- Working structured logging
- Request IDs in all logs
- Log rotation active

### Phase 2: Enhanced Logging (Week 2)

**Tasks:**
1. Add separate access log
2. Add performance logging
3. Add error-only log file
4. Implement async logging
5. Add more context to logs

**Deliverables:**
- Multiple log files operational
- Performance overhead < 5%
- Rich contextual information

### Phase 3: Integration (Week 3)

**Tasks:**
1. Add ELK stack support (optional)
2. Add Prometheus metrics (optional)
3. Create log analysis dashboard
4. Set up alerting rules
5. Documentation

**Deliverables:**
- External integration working
- Dashboard functional
- Alerting configured

### Phase 4: Testing & Optimization (Week 4)

**Tasks:**
1. Load testing with extensive logging
2. Performance optimization
3. Log volume analysis
4. Documentation updates
5. Team training

**Deliverables:**
- Performance validated
- Documentation complete
- Team trained

---

## Testing Plan

### 1. Functional Testing

**Test Cases:**
- ✅ Logs written to correct files
- ✅ Log rotation works
- ✅ Request IDs unique and propagated
- ✅ Sensitive data masked
- ✅ All log levels work
- ✅ JSON format valid

### 2. Performance Testing

**Test:**
- Send 1000 webhooks
- Measure: Response time, CPU, memory, disk I/O
- Compare: Logging ON vs OFF
- Target: < 5% overhead

### 3. Volume Testing

**Test:**
- Run for 24 hours
- Generate 200 webhooks
- Measure: Log file sizes, disk usage
- Verify: Rotation working

### 4. Security Testing

**Test:**
- Search logs for tokens
- Search logs for passwords
- Verify masking working
- Check file permissions

---

## Examples

### Example 1: Webhook Received (JSON)

```json
{
  "timestamp": "2024-01-01T10:15:30.123456Z",
  "level": "INFO",
  "logger": "webhook_listener",
  "request_id": "a1b2c3d4",
  "message": "Webhook received",
  "event": "webhook_received",
  "context": {
    "pipeline_id": 12345,
    "project_id": 100,
    "project_name": "my-project",
    "pipeline_type": "main",
    "pipeline_status": "success",
    "event_type": "Pipeline Hook",
    "source_ip": "192.168.1.100",
    "gitlab_event": "Pipeline Hook"
  },
  "performance": {
    "validation_duration_ms": 5
  }
}
```

### Example 2: API Call (JSON)

```json
{
  "timestamp": "2024-01-01T10:15:31.234567Z",
  "level": "DEBUG",
  "logger": "log_fetcher",
  "request_id": "a1b2c3d4",
  "message": "GitLab API call",
  "event": "api_call",
  "context": {
    "method": "GET",
    "path": "/api/v4/projects/100/jobs/1001/trace",
    "project_id": 100,
    "job_id": 1001
  },
  "performance": {
    "duration_ms": 234,
    "response_size_bytes": 15234,
    "status_code": 200
  }
}
```

### Example 3: Error with Retry (JSON)

```json
{
  "timestamp": "2024-01-01T10:15:32.345678Z",
  "level": "WARNING",
  "logger": "error_handler",
  "request_id": "a1b2c3d4",
  "message": "API call failed, retrying",
  "event": "retry_triggered",
  "context": {
    "operation": "fetch_job_log",
    "job_id": 1001,
    "attempt": 1,
    "max_attempts": 3,
    "backoff_delay_seconds": 2
  },
  "error": {
    "type": "ConnectionTimeout",
    "message": "Connection timed out after 30 seconds"
  }
}
```

### Example 4: Performance Summary (JSON)

```json
{
  "timestamp": "2024-01-01T10:15:35.567890Z",
  "level": "INFO",
  "logger": "webhook_listener",
  "request_id": "a1b2c3d4",
  "message": "Request completed",
  "event": "request_completed",
  "context": {
    "pipeline_id": 12345,
    "project_id": 100,
    "status": "success"
  },
  "performance": {
    "total_duration_ms": 5234,
    "stages": {
      "validation_ms": 5,
      "extraction_ms": 12,
      "api_calls_ms": 4200,
      "storage_ms": 1017
    },
    "api_calls": {
      "count": 6,
      "total_duration_ms": 4200,
      "avg_duration_ms": 700
    },
    "storage": {
      "jobs_saved": 5,
      "bytes_written": 524288,
      "files_created": 6
    }
  }
}
```

### Example 5: Security Event (JSON)

```json
{
  "timestamp": "2024-01-01T10:15:30.123456Z",
  "level": "WARNING",
  "logger": "webhook_listener",
  "request_id": "a1b2c3d4",
  "message": "Webhook validation failed",
  "event": "security_validation_failed",
  "context": {
    "source_ip": "203.0.113.45",
    "reason": "Invalid webhook secret",
    "event_type": "Pipeline Hook"
  },
  "security": {
    "threat_level": "low",
    "action": "rejected",
    "client_blocked": false
  }
}
```

---

## Implementation Cost Estimate

### Development Time:
- Phase 1 (Foundation): 2-3 days
- Phase 2 (Enhanced): 2-3 days
- Phase 3 (Integration): 2-3 days (optional)
- Phase 4 (Testing): 1-2 days
- **Total: 7-11 days**

### Performance Impact:
- CPU: +3-5%
- Memory: +50-100MB (for buffers)
- Disk I/O: +5-10% (with async logging)
- Network: Negligible (unless external logging)

### Storage Requirements:
- Normal operations: ~200MB/month
- Debug enabled: ~2GB/month
- Log retention (30 days): ~6GB max

---

## Recommendations

### Must Have (Phase 1):
1. ✅ Structured JSON logging to files
2. ✅ Request ID correlation
3. ✅ Sensitive data masking
4. ✅ Log rotation
5. ✅ Separate access logs

### Should Have (Phase 2):
1. ✅ Async logging for performance
2. ✅ Performance metrics logging
3. ✅ Enhanced error context
4. ✅ Configurable log levels per module

### Nice to Have (Phase 3):
1. ⚠️ ELK stack integration
2. ⚠️ Prometheus metrics
3. ⚠️ Distributed tracing
4. ⚠️ Real-time alerting

### For Your Use Case (100-200 webhooks/day):
- Start with Phase 1 + Phase 2
- Skip Phase 3 unless you plan to scale significantly
- Enable DEBUG logging by default (volume is manageable)
- Use file-based logging (no need for ELK yet)
- Implement request tracing (very valuable for debugging)

---

## Questions for Discussion

Before implementation, please consider:

1. **Log Format Preference:**
   - JSON (structured, queryable)
   - Plain text (human-readable)
   - Hybrid (JSON files, text console)?

2. **External Integration:**
   - Need ELK stack integration now?
   - Any existing log aggregation system?
   - Syslog server available?

3. **Retention Requirements:**
   - How long to keep logs?
   - Compliance requirements?
   - Backup strategy?

4. **Alerting:**
   - Need real-time alerting?
   - Who gets alerted?
   - Alert channels (email, Slack, PagerDuty)?

5. **Performance:**
   - What's acceptable overhead? (<5%?)
   - Async logging preferred?
   - Debug mode in production?

6. **Security:**
   - GDPR compliance needed?
   - Any specific sensitive data?
   - Audit log requirements?

---

## Next Steps

Once you review this plan, I can implement:

1. **Quick Win:** Phase 1 (Foundation) - 2-3 days
2. **Full Featured:** Phase 1 + Phase 2 - 4-6 days
3. **Enterprise:** All phases - 7-11 days

Your feedback on preferences will help tailor the implementation!
