# DIY Setup Guide - Build Log Extractor

## Logs Extractor

**What it does:**
Automatically captures and processes build logs from GitLab and Jenkins pipelines when builds complete. Extracts error sections with context and optionally posts to an external API for analysis.

**Key Features:**
- Webhook-based automation (no polling)
- Error pattern detection with configurable context
- Supports both GitLab and Jenkins
- Dual storage: API posting and/or local files
- Memory-efficient handling of large logs (million+ lines)
- Parallel stage support for Jenkins pipelines

---

## Host and Service Details

**Default Configuration:**

| Component | Details |
|-----------|---------|
| **Service Port** | 8000 (configurable via `WEBHOOK_PORT`) |
| **Host Directory** | `./logs` (mapped to container's `/app/logs`) |
| **Health Check** | `http://localhost:8000/health` |
| **API Docs** | `http://localhost:8000/docs` (Swagger UI) |
| **Log Retention** | 90 days (configurable via `LOG_RETENTION_DAYS`) |

**Service Endpoints:**
- GitLab Webhook: `POST /webhook/gitlab`
- Jenkins Webhook: `POST /webhook/jenkins`
- Health Check: `GET /health`
- Stats: `GET /stats`
- Monitoring: `GET /monitor/summary`

---

## Project Structure

```
extract-build-logs/
├── src/                          # Core application code
│   ├── webhook_listener.py       # FastAPI webhook server
│   ├── pipeline_extractor.py     # GitLab event parser
│   ├── jenkins_extractor.py      # Jenkins event parser
│   ├── log_fetcher.py            # GitLab API client
│   ├── jenkins_log_fetcher.py    # Jenkins API client
│   ├── log_error_extractor.py    # Error pattern detection
│   ├── storage_manager.py        # File storage handler
│   ├── api_poster.py             # External API integration
│   ├── monitoring.py             # SQLite tracking database
│   ├── config_loader.py          # Configuration management
│   ├── error_handler.py          # Retry logic & circuit breaker
│   └── token_manager.py          # JWT authentication
│
├── tests/                        # Unit and integration tests
├── scripts/                      # Utility scripts
│   ├── cleanup_old_logs.sh       # Log retention cleanup
│   ├── manage_database.sh        # Database operations
│   └── monitor_dashboard.py      # Monitoring dashboard
│
├── logs/                         # Generated log storage
│   ├── {project}_{id}/           # GitLab logs
│   │   └── pipeline_{id}/
│   │       ├── job_logs/
│   │       └── metadata.json
│   └── jenkins-builds/           # Jenkins logs
│       └── {job-name}/{build}/
│           ├── console.log
│           └── metadata.json
│
├── Dockerfile                    # Container definition
├── log-extractor-entrypoint.sh   # Container startup script
├── manage_container.py           # Docker management CLI
├── .env                          # Configuration (from .env.example)
├── jenkins_instances.json        # Multi-Jenkins config (optional)
└── README.md                     # Quick start guide
```

---

## Create and Activate the Environment

### Option 1: Docker (Recommended)

**Prerequisites:**
- Docker installed
- Docker Compose (optional)

**Setup Steps:**

```bash
# 1. Clone repository
git clone <repository-url>
cd extract-build-logs

# 2. Create configuration
cp .env.example .env
vi .env  # Edit GITLAB_URL, GITLAB_TOKEN, etc.

# 3. Build Docker image
./manage_container.py build

# 4. Start container
./manage_container.py start

# 5. Verify running
./manage_container.py status
curl http://localhost:8000/health
```

### Option 2: Python Virtual Environment

**Prerequisites:**
- Python 3.8+
- pip

**Setup Steps:**

```bash
# 1. Clone repository
git clone <repository-url>
cd extract-build-logs

# 2. Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Create configuration
cp .env.example .env
vi .env  # Edit configuration

# 5. Run server
python src/webhook_listener.py

# 6. Verify (in another terminal)
curl http://localhost:8000/health
```

---

## Docker (Build | Start | Restart | Stop | Remove | Status)

The `manage_container.py` script provides easy Docker management:

### Build
```bash
# Build Docker image from Dockerfile
./manage_container.py build

# Force rebuild without cache
./manage_container.py build --no-cache
```

### Start
```bash
# Start container in detached mode
./manage_container.py start

# Start and show logs
./manage_container.py start --logs
```

### Restart
```bash
# Restart running container (preserves data)
./manage_container.py restart
```

### Stop
```bash
# Stop container gracefully
./manage_container.py stop
```

### Remove
```bash
# Remove stopped container
./manage_container.py remove

# Remove container and image
./manage_container.py remove --image

# Remove everything (container, image, logs)
./manage_container.py remove --all
```

### Status
```bash
# Check container status
./manage_container.py status

# View container logs
./manage_container.py logs

# Follow logs in real-time
./manage_container.py logs --follow

# View configuration
./manage_container.py config
```

---

## Container Configuration

**Environment Variables (.env file):**

### Minimum Required:
```bash
GITLAB_URL=https://gitlab.com
GITLAB_TOKEN=glpat-xxxxxxxxxxxx
WEBHOOK_PORT=8000
LOG_OUTPUT_DIR=./logs
```

### GitLab Integration:
```bash
GITLAB_URL=https://gitlab.com
GITLAB_TOKEN=glpat-xxxxxxxxxxxx
WEBHOOK_SECRET=my-secret-token-123
```

### Jenkins Integration (Single Instance):
```bash
JENKINS_ENABLED=true
JENKINS_URL=https://jenkins.example.com
JENKINS_USER=jenkins_username
JENKINS_API_TOKEN=1234567890abcdef
JENKINS_WEBHOOK_SECRET=jenkins-secret
```

### Jenkins Integration (Multiple Instances):
Create `jenkins_instances.json`:
```json
{
  "instances": [
    {
      "jenkins_url": "https://jenkins1.example.com",
      "username": "user1",
      "api_token": "token1",
      "webhook_secret": "secret1"
    },
    {
      "jenkins_url": "https://jenkins2.example.com",
      "username": "user2",
      "api_token": "token2"
    }
  ]
}
```

### API Posting Configuration:
```bash
API_POST_ENABLED=true
BFA_HOST=bfa-server.example.com
BFA_SECRET_KEY=your-bfa-jwt-secret
API_POST_TIMEOUT=180
API_POST_SAVE_TO_FILE=false  # API only, no file storage
```

### Log Filtering:
```bash
# Only save failed pipeline logs
LOG_SAVE_PIPELINE_STATUS=failed

# Only save failed job logs
LOG_SAVE_JOB_STATUS=failed

# Save metadata for all pipelines
LOG_SAVE_METADATA_ALWAYS=true

# Filter specific projects (comma-separated IDs)
LOG_SAVE_PROJECTS=123,456,789

# Exclude specific projects
LOG_EXCLUDE_PROJECTS=999,888
```

### Error Detection Configuration:
```bash
# Context lines before/after errors
ERROR_CONTEXT_LINES_BEFORE=50
ERROR_CONTEXT_LINES_AFTER=10

# Ignore false positive patterns
ERROR_IGNORE_PATTERNS=error: tag,0 errors,warning treated as error

# Memory limits for large logs
MAX_LOG_LINES=100000
TAIL_LOG_LINES=5000
STREAM_CHUNK_SIZE=8192
```

---

## Integration

### Jenkins Integration Flow

```mermaid
sequenceDiagram
    participant J as Jenkins Pipeline
    participant JF as Jenkinsfile
    participant WH as Webhook Server
    participant JLF as Jenkins Log Fetcher
    participant LEE as Error Extractor
    participant API as BFA API

    J->>JF: Build Completes
    JF->>WH: POST /webhook/jenkins
    Note over JF,WH: Headers: X-Jenkins-Token<br/>Body: job_name, build_number, jenkins_url
    WH->>WH: Validate Token
    WH-->>JF: 200 OK (Acknowledged)

    WH->>JLF: Fetch Build Metadata
    JLF->>J: Blue Ocean API Call
    J-->>JLF: Build Info + Stage Data

    JLF->>J: Fetch Console Log
    J-->>JLF: Full Build Log

    JLF->>LEE: Extract Errors
    LEE-->>JLF: Error Sections + Context

    WH->>API: POST /api/analyze
    Note over WH,API: JWT Bearer Token<br/>Structured Log Data
```

**Required Jenkinsfile Code:**
```groovy
post {
    always {
        script {
            def webhookUrl = "http://your-server:8000/webhook/jenkins"
            def webhookToken = "your-jenkins-webhook-secret"
            def payload = [
                job_name: env.JOB_NAME,
                build_number: env.BUILD_NUMBER,
                build_url: env.BUILD_URL,
                jenkins_url: "https://jenkins.example.com",  // Required for multi-instance
                status: currentBuild.result
            ]

            httpRequest(
                httpMode: 'POST',
                url: webhookUrl,
                customHeaders: [[name: 'X-Jenkins-Token', value: webhookToken]],
                contentType: 'APPLICATION_JSON',
                requestBody: groovy.json.JsonOutput.toJson(payload),
                validResponseCodes: '200'
            )
        }
    }
}
```

---

## Jenkins Webhook Configuration

### Step 1: Generate API Token
1. Go to Jenkins → Your User → Configure
2. Scroll to "API Token" section
3. Click "Add new Token"
4. Copy the generated token

### Step 2: Configure Environment
In `.env` file:
```bash
JENKINS_ENABLED=true
JENKINS_URL=https://jenkins.example.com
JENKINS_USER=your_username
JENKINS_API_TOKEN=<token-from-step-1>
JENKINS_WEBHOOK_SECRET=my-jenkins-secret-123
```

### Step 3: Add to Jenkinsfile
Add this post-build action to your pipeline:

```groovy
pipeline {
    agent any

    stages {
        stage('Build') {
            steps {
                echo 'Building...'
            }
        }
    }

    post {
        always {
            script {
                def webhookUrl = "http://log-extractor-host:8000/webhook/jenkins"
                def webhookToken = "my-jenkins-secret-123"  // Match .env JENKINS_WEBHOOK_SECRET

                def payload = [
                    job_name: env.JOB_NAME,
                    build_number: env.BUILD_NUMBER.toInteger(),
                    build_url: env.BUILD_URL,
                    jenkins_url: "${env.JENKINS_URL}",
                    status: currentBuild.result ?: 'SUCCESS',
                    timestamp: new Date().format("yyyy-MM-dd'T'HH:mm:ss'Z'")
                ]

                try {
                    httpRequest(
                        httpMode: 'POST',
                        url: webhookUrl,
                        customHeaders: [[name: 'X-Jenkins-Token', value: webhookToken]],
                        contentType: 'APPLICATION_JSON',
                        requestBody: groovy.json.JsonOutput.toJson(payload),
                        validResponseCodes: '200',
                        timeout: 30
                    )
                    echo "Webhook sent successfully"
                } catch (Exception e) {
                    echo "Webhook failed: ${e.message}"
                }
            }
        }
    }
}
```

### Step 4: Test
```bash
# Trigger a build and check logs
./manage_container.py logs --follow

# Check if webhook received
curl http://localhost:8000/monitor/summary?hours=1
```

---

## Gitlab Integration

### GitLab Integration Flow

```mermaid
sequenceDiagram
    participant GL as GitLab
    participant WH as Webhook Server
    participant PE as Pipeline Extractor
    participant LF as Log Fetcher
    participant SM as Storage Manager
    participant API as BFA API

    GL->>WH: POST /webhook/gitlab
    Note over GL,WH: Event: Pipeline Hook<br/>Token: X-Gitlab-Token
    WH->>WH: Validate Secret Token
    WH->>PE: Extract Pipeline Info
    PE-->>WH: Pipeline Metadata
    WH-->>GL: 200 OK (Acknowledged)

    Note over WH: Background Processing

    WH->>LF: Fetch Job Logs
    loop For Each Job
        LF->>GL: GET /api/v4/projects/{id}/jobs/{job}/trace
        GL-->>LF: Job Log Content
    end

    WH->>SM: Save Logs + Metadata
    SM-->>WH: Storage Complete

    opt If API Posting Enabled
        WH->>API: POST /api/analyze
        API-->>WH: Analysis Response
    end
```

**GitLab Webhook Payload Example:**
```json
{
  "object_kind": "pipeline",
  "object_attributes": {
    "id": 12345,
    "status": "failed",
    "ref": "main",
    "source": "push"
  },
  "project": {
    "id": 456,
    "name": "my-project",
    "web_url": "https://gitlab.com/group/my-project"
  },
  "builds": [
    {
      "id": 67890,
      "name": "test",
      "stage": "test",
      "status": "failed"
    }
  ]
}
```

---

## Gitlab Webhook Configuration

### Step 1: Generate GitLab Access Token
1. Go to GitLab → Profile → Access Tokens
2. Name: "Log Extractor"
3. Select scopes: `api` (required), `read_api`, `read_repository`
4. Create token and copy it

### Step 2: Configure Service
In `.env` file:
```bash
GITLAB_URL=https://gitlab.com
GITLAB_TOKEN=glpat-xxxxxxxxxxxxxxxxxxxxx  # Token from Step 1
WEBHOOK_SECRET=my-secret-token-123
LOG_SAVE_PIPELINE_STATUS=failed  # Optional: only save failed pipelines
```

### Step 3: Configure GitLab Webhook
1. Go to GitLab → Your Project → Settings → Webhooks
2. Fill in webhook details:
   - **URL**: `http://your-server:8000/webhook/gitlab`
   - **Secret Token**: `my-secret-token-123` (must match .env)
   - **Trigger**: Check "Pipeline events" only
   - **SSL verification**: Enable if using HTTPS
3. Click "Add webhook"

### Step 4: Test Webhook
1. In GitLab webhook settings, click "Test" → "Pipeline events"
2. Check webhook server logs:
   ```bash
   ./manage_container.py logs --follow
   ```
3. Verify webhook received:
   ```bash
   curl http://localhost:8000/monitor/summary?hours=1
   ```

### Common Issues:
- **401 Unauthorized**: Secret token mismatch between GitLab and .env
- **Connection Refused**: Webhook server not accessible (check firewall/network)
- **500 Error**: Check server logs for configuration issues

---

## Debugging and Validation

### Getting Logs

**Container Logs:**
```bash
# View recent logs
./manage_container.py logs

# Follow logs in real-time
./manage_container.py logs --follow

# Last 100 lines
./manage_container.py logs --tail 100

# Direct docker command
docker logs bfa-gitlab-pipeline-extractor
docker logs -f bfa-gitlab-pipeline-extractor  # Follow mode
```

**Application Logs:**
```bash
# Set debug level in .env
LOG_LEVEL=DEBUG

# Restart to apply
./manage_container.py restart

# Check logs for detailed output
./manage_container.py logs --follow
```

**Stored Build Logs:**
```bash
# GitLab logs location
ls -lh logs/{project}_{id}/pipeline_{id}/job_logs/

# Jenkins logs location
ls -lh logs/jenkins-builds/{job-name}/{build-number}/

# View a specific job log
cat logs/my-project_123/pipeline_456/job_logs/test.log

# View metadata
cat logs/my-project_123/pipeline_456/metadata.json | jq .
```

**Monitoring Database:**
```bash
# View recent webhook requests
./scripts/manage_database.sh query "
  SELECT * FROM webhook_requests
  ORDER BY timestamp DESC
  LIMIT 10;
"

# Count requests by status
./scripts/manage_database.sh query "
  SELECT status, COUNT(*) as count
  FROM webhook_requests
  GROUP BY status;
"

# View recent errors
./scripts/manage_database.sh query "
  SELECT * FROM webhook_requests
  WHERE status != 'success'
  ORDER BY timestamp DESC;
"
```

### Endpoints

**Health Check:**
```bash
curl http://localhost:8000/health

# Response:
{
  "status": "healthy",
  "service": "gitlab-log-extractor",
  "version": "1.0.0"
}
```

**Storage Statistics:**
```bash
curl http://localhost:8000/stats

# Response:
{
  "total_projects": 5,
  "total_pipelines": 23,
  "total_jobs": 156,
  "total_size_bytes": 45678901,
  "total_size_mb": 43.56
}
```

**Monitoring Summary:**
```bash
# Last 24 hours
curl http://localhost:8000/monitor/summary

# Last hour
curl http://localhost:8000/monitor/summary?hours=1

# Specific date range
curl "http://localhost:8000/monitor/summary?start_date=2024-01-01&end_date=2024-01-31"

# Response includes:
{
  "total_requests": 150,
  "successful": 145,
  "failed": 5,
  "by_source": {
    "gitlab": 100,
    "jenkins": 50
  },
  "by_status": {
    "success": 145,
    "error": 5
  }
}
```

**Interactive API Documentation:**
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

**Test Webhooks:**

GitLab Test:
```bash
curl -X POST http://localhost:8000/webhook/gitlab \
  -H "Content-Type: application/json" \
  -H "X-Gitlab-Event: Pipeline Hook" \
  -H "X-Gitlab-Token: my-secret-token-123" \
  -d '{
    "object_kind": "pipeline",
    "object_attributes": {
      "id": 12345,
      "status": "failed"
    },
    "project": {
      "id": 456,
      "name": "test-project"
    }
  }'
```

Jenkins Test:
```bash
curl -X POST http://localhost:8000/webhook/jenkins \
  -H "Content-Type: application/json" \
  -H "X-Jenkins-Token: jenkins-secret" \
  -d '{
    "job_name": "test-job",
    "build_number": 42,
    "build_url": "https://jenkins.example.com/job/test-job/42/",
    "jenkins_url": "https://jenkins.example.com"
  }'
```

**Validation Commands:**

```bash
# 1. Check container is running
./manage_container.py status

# 2. Verify health endpoint
curl http://localhost:8000/health

# 3. Check recent activity
curl http://localhost:8000/monitor/summary?hours=1

# 4. Verify configuration
./manage_container.py config

# 5. Check logs for errors
./manage_container.py logs --tail 50 | grep -i error

# 6. Test GitLab connection
curl -H "PRIVATE-TOKEN: ${GITLAB_TOKEN}" ${GITLAB_URL}/api/v4/projects

# 7. Verify log storage
ls -lh logs/

# 8. Check database
./scripts/manage_database.sh query "SELECT COUNT(*) FROM webhook_requests;"
```

---

## Quick Troubleshooting

| Issue | Solution |
|-------|----------|
| **Container won't start** | Check `.env` file exists and has valid values |
| **Webhook returns 401** | Verify secret token matches between GitLab/Jenkins and `.env` |
| **No logs saved** | Check `LOG_SAVE_PIPELINE_STATUS` filter settings |
| **API posting fails** | Verify `BFA_HOST` is reachable and `BFA_SECRET_KEY` is valid |
| **Memory issues** | Reduce `MAX_LOG_LINES` or `TAIL_LOG_LINES` in `.env` |
| **Jenkins multi-instance not working** | Ensure `jenkins_url` is included in webhook payload |

---

## Useful Commands Reference

```bash
# Full lifecycle
./manage_container.py build
./manage_container.py start
./manage_container.py logs --follow
./manage_container.py restart
./manage_container.py stop
./manage_container.py remove

# Monitoring
curl http://localhost:8000/health
curl http://localhost:8000/stats
curl http://localhost:8000/monitor/summary

# Cleanup old logs (90 days)
./scripts/cleanup_old_logs.sh

# Database backup
./scripts/manage_database.sh backup

# View configuration
./manage_container.py config
```

---

For complete documentation, see [DOCUMENTATION.md](DOCUMENTATION.md)
