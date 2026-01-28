# DIY Conceptual Guide - Build Log Extractor

## Logs Extractor

### What It Is
The Logs Extractor is an automated system that captures and processes build logs from CI/CD pipelines (GitLab and Jenkins). Think of it as a listener that waits for build completion notifications and immediately fetches the logs for analysis.

### How It Works
When a pipeline finishes (success or failure), the CI/CD system sends a webhook notification to our extractor service. The extractor then:
1. Receives the notification
2. Identifies which jobs/stages ran
3. Fetches the complete logs from those jobs
4. Scans for error patterns using specific keywords
5. Extracts errors with surrounding context (lines before and after)
6. Optionally posts the processed data to an external API for analysis
7. Stores logs locally or remotely based on configuration

### Why It's Useful
- **Automated**: No manual log retrieval needed
- **Intelligent**: Only captures relevant error sections, not entire multi-gigabyte logs
- **Contextual**: Provides surrounding lines to understand what led to the error
- **Filtered**: Can save only failed builds to reduce storage
- **Integrated**: Works seamlessly with existing GitLab/Jenkins setups without code changes

---

## Host and Service Details

### Architecture Overview
The system runs as a web service (FastAPI application) that exposes HTTP endpoints. It listens on a specific port (default 8000) and responds to webhook POST requests from GitLab or Jenkins.

### Key Components
- **Webhook Listener**: The main service that receives notifications
- **API Endpoints**: RESTful endpoints for webhooks, health checks, and monitoring
- **Storage Layer**: File system or API-based storage for logs
- **Monitoring Database**: SQLite database tracking all requests and processing status
- **Log Retention**: Automatic cleanup of old logs based on configured retention period

### Service Boundaries
The service needs:
- **Inbound**: Network access for GitLab/Jenkins to reach webhook endpoints
- **Outbound**: Network access to GitLab/Jenkins APIs for log fetching
- **Optional Outbound**: Access to external BFA API if posting is enabled
- **Storage**: Persistent volume for logs and monitoring database

---

## Project Structure

### Core Application (`src/`)
This directory contains the main application logic split into specialized modules:

**Listener & Routing**
- The webhook listener is the entry point - it's a FastAPI web server that handles incoming HTTP requests from GitLab and Jenkins

**Event Parsing**
- Pipeline extractor parses GitLab webhook payloads to understand what happened (which pipeline, which jobs, what status)
- Jenkins extractor does the same for Jenkins build notifications

**Log Retrieval**
- Separate fetchers for GitLab and Jenkins APIs handle the actual log downloading
- They implement retry logic, authentication, and handle API rate limits
- Jenkins fetcher uses a hybrid approach: tries fetching last N lines first (fast), then full log if needed (for huge builds)

**Intelligence Layer**
- Error extractor scans logs for specific patterns (like "error", "failed", "exception")
- It's not just keyword matching - it extracts context lines before and after errors
- Configurable ignore patterns filter out false positives (like "0 errors" success messages)

**Storage & Output**
- Storage manager handles file system operations - creating directories, saving logs, updating metadata
- API poster handles external integration - formats data, generates JWT tokens, posts to BFA API

**Infrastructure**
- Configuration loader centralizes all environment variable handling
- Error handler implements exponential backoff retry logic
- Monitoring tracks all webhook requests in SQLite for operational visibility
- Token manager handles JWT generation and validation

### Tests (`tests/`)
Comprehensive test coverage including:
- Unit tests for each module
- Integration tests for webhook flows
- Mock servers for API testing
- Test fixtures for common scenarios

### Scripts (`scripts/`)
Operational utilities:
- Log cleanup automation (removes logs older than retention period)
- Database management (backup, query, maintenance)
- Monitoring dashboard (real-time statistics)

### Configuration Files
- `.env`: All runtime configuration (tokens, URLs, filters)
- `jenkins_instances.json`: Multi-instance Jenkins credentials
- `.env.example`: Template with documentation

### Generated Logs Structure
**GitLab**: `logs/{project}_{id}/pipeline_{id}/job_logs/{job_name}.log`
- Organized by project and pipeline for easy navigation
- Each job gets its own log file
- Metadata JSON contains pipeline info, job statuses, timestamps

**Jenkins**: `logs/jenkins-builds/{job-name}/{build-number}/console.log`
- Organized by job name and build number
- Console log contains full build output
- Metadata JSON contains build parameters, stage results, user info

---

## Create and Activate the Environment

### Docker Approach (Recommended)
Docker containerization provides:
- **Isolation**: The application runs in its own container with all dependencies
- **Consistency**: Same environment on any machine (dev, staging, production)
- **Easy Deployment**: Single command to start/stop/restart
- **Rollback**: Easy to revert to previous versions
- **Resource Control**: CPU and memory limits can be set

The Docker image is built once and contains:
- Base Python 3.8 runtime
- All Python dependencies (FastAPI, requests, etc.)
- Application code
- Entry point script that starts the FastAPI server

The container mounts a host directory (`./logs`) so logs persist even if container is removed.

### Python Virtual Environment Approach
A Python virtual environment provides:
- **Dependency Isolation**: Packages don't conflict with system Python
- **Reproducibility**: requirements.txt ensures same package versions
- **Development Flexibility**: Easier to test code changes without rebuilding

This approach runs the Python process directly on the host machine, useful for:
- Local development and debugging
- Environments where Docker isn't available
- When you need to modify code frequently

---

## Docker Operations Explained

### Build
Building creates a Docker image - a snapshot of the file system with all code and dependencies. The build process:
1. Starts from a base Python image
2. Installs system packages (curl for health checks)
3. Copies requirements.txt and installs Python packages
4. Copies application code
5. Sets up entry point and health check
6. Tags the image with a name

Once built, this image can be started multiple times to create containers.

### Start
Starting creates and runs a container from the image. The container:
- Gets its own network namespace (can bind to port 8000)
- Mounts host directory for log storage
- Reads environment variables from .env file
- Starts the FastAPI server
- Runs in detached mode (background process)

### Restart
Restarting stops and starts the container, useful when:
- Configuration changed in .env (need to reload environment variables)
- Application code updated (after rebuilding image)
- Clearing any memory issues or hung processes
- The restart is graceful - FastAPI shuts down properly

### Stop
Stopping sends a SIGTERM signal to the container, allowing:
- Graceful shutdown (finish processing current requests)
- Clean up resources (close database connections, finish file writes)
- The container is stopped but not removed, so it retains state

### Remove
Removing deletes the container (and optionally the image and logs):
- Container removal: Frees up system resources, removes container metadata
- Image removal: Reclaims disk space from image layers
- Log removal: Cleans up all stored logs (use carefully!)

### Status
Status checking provides operational visibility:
- Container running state (up/down)
- Resource usage (CPU, memory)
- Log output (application logs, errors)
- Configuration verification (what settings are active)

---

## Container Configuration

### Configuration Philosophy
The application uses environment variables for configuration because:
- **12-Factor App**: Standard practice for cloud-native applications
- **Separation**: Config separate from code (no hardcoded values)
- **Security**: Secrets not committed to version control
- **Flexibility**: Different configs for dev/staging/production

### Required Settings
Minimum to get started:
- **GitLab URL**: Tells the system where to find GitLab API
- **GitLab Token**: Authentication for API access (read pipeline data, fetch logs)
- **Webhook Port**: What port the service listens on
- **Log Directory**: Where to store fetched logs

### GitLab Integration Config
- **Token Scopes**: Needs `api` scope to read pipelines and fetch logs
- **Webhook Secret**: Validates that requests actually come from GitLab, not attackers
- Without secret, anyone who knows your webhook URL could spam fake requests

### Jenkins Integration Config
**Single Instance Mode**: Simple setup when you have one Jenkins server
- URL, username, and API token stored in .env
- All webhooks from Jenkins use these credentials

**Multi-Instance Mode**: For organizations with multiple Jenkins servers
- Credentials stored in separate JSON file
- Each instance can have different auth
- Webhook payload must include `jenkins_url` field
- System automatically matches webhook to correct credentials

### API Posting Config
When enabled, logs are posted to external API instead of (or in addition to) file storage:
- **BFA_HOST**: Where to send the data
- **BFA_SECRET_KEY**: JWT secret for authentication
- **Dual Mode**: Can save to both API and files, or just API
- **Retry Logic**: Failed posts are retried with exponential backoff

### Log Filtering Config
Reduces storage and noise by filtering what gets saved:

**Pipeline Status Filter**: Only save specific pipeline outcomes
- `failed`: Only failed pipelines (most common for debugging)
- `all`: Everything (useful for compliance/auditing)
- `failed,canceled`: Multiple statuses

**Job Status Filter**: Within a pipeline, only save specific job logs
- Independent of pipeline filter
- Can save all jobs from failed pipelines, or only failed jobs

**Project Filters**: Control which projects are logged
- Whitelist: Only specified project IDs
- Blacklist: All except specified project IDs
- Useful to exclude test projects or focus on critical services

**Metadata Always**: Even if logs aren't saved, metadata is recorded
- Tracks all pipeline executions for monitoring
- Minimal storage overhead
- Full visibility into pipeline health

### Error Detection Config
Controls how errors are extracted from logs:

**Context Lines**:
- Lines before error (default 50): Shows what led up to the failure
- Lines after error (default 10): Shows immediate consequences
- Larger context = better understanding but bigger payloads to API

**Ignore Patterns**:
- Filters false positives (lines that contain error keywords but aren't errors)
- Examples: "error: tag" (Docker command), "0 errors" (success message)
- Case-insensitive matching

**Memory Limits**:
- MAX_LOG_LINES: Safety limit to prevent processing 10-million-line logs
- TAIL_LOG_LINES: Hybrid strategy - try tail first (fast), fallback to full fetch
- STREAM_CHUNK_SIZE: Memory vs speed tradeoff when downloading logs

---

## Integration Flows

### Jenkins Integration Flow

**Step 1: Build Completes**
A Jenkins pipeline finishes execution (success or failure). The Jenkinsfile has a `post` section that always runs.

**Step 2: Webhook Notification**
The Jenkinsfile uses HTTP Request plugin to POST to our webhook endpoint. The payload includes:
- Job name and build number (identifies the build)
- Build URL (for linking back)
- Jenkins URL (for multi-instance routing)
- Build status (SUCCESS, FAILURE, ABORTED)

**Step 3: Webhook Reception**
Our service receives the POST request and:
- Validates the X-Jenkins-Token header (security check)
- Returns 200 OK immediately (Jenkins doesn't wait for log processing)
- Queues background task for log fetching

**Step 4: Metadata Fetch**
Background task calls Jenkins Blue Ocean API to get:
- Pipeline structure (stages and steps)
- Stage statuses (which stages failed)
- Build parameters (what inputs were used)
- Committer information (who triggered the build)

**Step 5: Log Retrieval**
System fetches console log from Jenkins using hybrid strategy:
- First tries: "Get last 5000 lines" (fast API call)
- If errors found in tail: Use tail only
- If no errors in tail: Fetch full log (errors might be earlier)

**Step 6: Error Extraction**
Log error extractor scans the text for error patterns:
- Matches keywords like "exception", "failed", "build failed"
- Skips lines matching ignore patterns
- Extracts matching lines with surrounding context

**Step 7: User Determination**
System identifies who to notify:
- Uses Jenkins build metadata (user who triggered)
- Falls back to GitLab API if Jenkins doesn't have email
- Determines from commit author if available

**Step 8: Output**
Processed data is:
- Posted to BFA API (if enabled) with JWT authentication
- Saved to local files (if enabled)
- Logged to monitoring database for tracking

### GitLab Integration Flow

**Step 1: Pipeline Event**
GitLab fires a "Pipeline Hook" webhook when a pipeline changes state (running → failed, running → success, etc.).

**Step 2: Webhook Delivery**
GitLab POSTs to our endpoint with:
- X-Gitlab-Event header (identifies event type)
- X-Gitlab-Token header (webhook secret for validation)
- JSON payload with complete pipeline information

**Step 3: Validation & Parsing**
Our service:
- Validates secret token matches .env configuration
- Checks event type is "Pipeline Hook"
- Returns 200 OK immediately (GitLab doesn't retry on success)
- Parses payload to extract project, pipeline, and job information

**Step 4: Filter Check**
Before fetching logs, system checks filters:
- Is pipeline status one we care about? (e.g., only "failed")
- Is this project in our whitelist/blacklist?
- Are there any jobs that match job status filter?
- If all checks pass, proceed; otherwise skip log fetching

**Step 5: Job Log Fetching**
For each job in the pipeline:
- Call GitLab API: GET /api/v4/projects/{id}/jobs/{job_id}/trace
- Use PRIVATE-TOKEN header for authentication
- Implement retry with exponential backoff on failures
- Handle rate limits and transient errors

**Step 6: Error Extraction**
Same pattern matching as Jenkins:
- Scan for error keywords
- Filter out ignore patterns
- Extract with context lines

**Step 7: Storage Organization**
Save to organized directory structure:
- `logs/{project}_{id}/pipeline_{id}/`
- Separate file per job: `job_logs/{job_name}.log`
- Metadata JSON with pipeline summary

**Step 8: Optional API Posting**
If API posting enabled:
- Format data for BFA API
- Look up GitLab user email via API
- Generate JWT token
- POST with retry logic

---

## Jenkins Webhook Configuration

### Why Webhooks?
Webhooks are event-driven - Jenkins "pushes" notifications to us instead of us "polling" Jenkins. This is:
- **Efficient**: No wasted API calls checking for new builds
- **Real-time**: We know immediately when build completes
- **Scalable**: Works for hundreds of jobs without performance impact

### API Token Purpose
Jenkins API token is used for two purposes:
1. **Webhook Validation**: We verify token matches (optional security)
2. **Log Fetching**: We authenticate API calls to fetch build logs

The token provides read-only access to build data without needing full username/password.

### Jenkinsfile Integration
The `post { always { ... } }` block ensures:
- Webhook fires regardless of build outcome
- Notification happens after build truly completes
- Error in notification doesn't fail the build
- Timeout prevents indefinite hang

### Multi-Instance Routing
When multiple Jenkins instances exist:
- Webhook payload must include `jenkins_url` field
- Our system matches that URL to credentials in `jenkins_instances.json`
- This allows each Jenkins to have different authentication
- Enables centralized log collection from distributed Jenkins

---

## GitLab Webhook Configuration

### Access Token Scopes
The `api` scope provides:
- **Read Projects**: Get project metadata
- **Read Pipelines**: Access pipeline and job information
- **Read Logs**: Fetch job trace logs
- **Read Users**: Look up user emails for notifications

Without `api` scope, log fetching will fail with 403 Forbidden errors.

### Webhook Secret Purpose
The secret token prevents:
- **Spoofing**: Attackers can't send fake pipeline notifications
- **Replay Attacks**: Old webhooks can't be replayed
- **Unauthorized Access**: Only GitLab with correct secret can trigger processing

Best practice: Use a long random string (32+ characters).

### Pipeline Events Only
We only need "Pipeline events" trigger because:
- Covers all pipeline state changes (started, success, failed, canceled)
- Includes all jobs in the payload (no separate requests needed)
- Other events (push, merge request) aren't relevant for log extraction

### SSL Verification
Enable SSL verification in production to prevent:
- Man-in-the-middle attacks
- Webhook interception
- Credential theft

Only disable for local development/testing with self-signed certificates.

---

## Debugging and Validation

### Understanding Logs

**Container Logs**
These show the application's stdout/stderr output:
- Startup messages (configuration loaded, server started)
- Webhook receipts (incoming requests logged with request ID)
- API calls (fetching logs from GitLab/Jenkins)
- Errors (exceptions, failed API calls, validation errors)
- Processing results (X jobs fetched, Y errors found)

Useful for diagnosing:
- Why webhooks aren't being received
- Why log fetching is failing
- Configuration issues
- Runtime errors

**Application Logs vs Stored Logs**
- Application logs: What the extractor service itself is doing
- Stored logs: The actual build/pipeline logs it fetched
- Don't confuse them - application logs tell you if the system is working

**Log Levels**
- DEBUG: Every detail (API requests, parsing steps, filter checks)
- INFO: Normal operations (webhook received, logs saved)
- WARNING: Potential issues (API retry, filter excluded pipeline)
- ERROR: Failures (API timeout, invalid token, processing error)

Set DEBUG temporarily when troubleshooting, INFO for production.

### Monitoring Database

The SQLite database (`monitoring.db`) tracks:
- Every webhook request received (source, timestamp, status)
- Processing outcomes (success, error, filtered)
- Timing information (how long processing took)
- Error details (what went wrong)

This provides:
- **Historical View**: What happened over time
- **Success Rate**: How many webhooks succeeded vs failed
- **Error Patterns**: Common failure modes
- **Performance Metrics**: Processing times, API call durations

Query it to answer questions like:
- "How many pipelines failed last week?"
- "Why did processing fail for build #123?"
- "What's our webhook success rate?"

### Endpoint Purposes

**Health Check (`/health`)**
Simplest endpoint - just confirms service is running and responding. Use for:
- Docker/Kubernetes health probes
- Monitoring systems (Datadog, Prometheus)
- Quick manual check that service is up

**Stats (`/stats`)**
Shows what's stored on disk:
- How many projects/pipelines we're tracking
- Total storage used
- Growth over time

Useful for capacity planning and cleanup decisions.

**Monitor Summary (`/monitor/summary`)**
Shows operational metrics:
- Request counts by source (GitLab vs Jenkins)
- Success/failure rates
- Recent errors
- Time-based filtering (last hour, last day, last week)

Use to understand system health and identify issues.

**Interactive Docs (`/docs`, `/redoc`)**
Auto-generated API documentation:
- Shows all available endpoints
- Explains request/response formats
- Provides "Try it out" functionality
- Documents required headers and parameters

Useful for understanding the API without reading code.

### Testing Webhooks

**Why Test?**
Before connecting real GitLab/Jenkins, verify:
- Service is reachable from webhook source
- Authentication is configured correctly
- Payload format is understood
- Processing logic works as expected

**Test with Curl**
Simulate webhook by sending HTTP POST with:
- Correct headers (token, content-type)
- Valid JSON payload
- Expected fields populated

If curl test succeeds, real webhook should work.

**Validation Checklist**
Systematically verify:
1. Container/process is running
2. Health endpoint responds
3. Configuration loaded correctly
4. Recent activity visible in monitoring
5. No errors in application logs
6. External services (GitLab/Jenkins) are reachable
7. Storage directory is writable

Work through checklist top to bottom when troubleshooting.

---

## Common Troubleshooting Scenarios

### Webhook Returns 401
**What it means**: Authentication failed - token mismatch.

**Why it happens**:
- Secret in GitLab/Jenkins doesn't match .env
- Secret has special characters not properly escaped
- Environment variable not loaded (typo in .env)

**How to fix**:
- Verify exact token match (copy-paste, watch for extra spaces)
- Check container restarted after .env change
- Test with curl using same token

### No Logs Saved
**What it means**: Webhooks received but logs not written to disk.

**Why it happens**:
- Pipeline status filter excluding all pipelines (e.g., filter=failed but build succeeded)
- Job status filter too restrictive
- Storage directory not writable
- API posting enabled but file saving disabled

**How to fix**:
- Check monitoring database to confirm webhooks processed
- Review filter settings in .env
- Temporarily set filters to "all" to confirm logs appear
- Check file permissions on logs directory

### API Posting Fails
**What it means**: Logs fetched successfully but POST to BFA API fails.

**Why it happens**:
- BFA_HOST not reachable (network/firewall)
- BFA_SECRET_KEY invalid or expired
- API endpoint changed or unavailable
- Timeout too short for large payloads

**How to fix**:
- Test connectivity: curl http://BFA_HOST:8000/health
- Verify secret key with API provider
- Check BFA API logs for received requests
- Increase API_POST_TIMEOUT for large logs

### Memory Issues
**What it means**: Container crashes or becomes unresponsive processing large logs.

**Why it happens**:
- Million+ line logs loaded entirely into memory
- MAX_LOG_LINES set too high
- Multiple large builds processing simultaneously

**How to fix**:
- Reduce MAX_LOG_LINES (try 50000 or 100000)
- Reduce TAIL_LOG_LINES (try 2000-3000)
- Increase container memory limit
- Process fewer builds concurrently

### Jenkins Multi-Instance Not Working
**What it means**: Webhook received but logs not fetched from correct Jenkins.

**Why it happens**:
- `jenkins_url` not included in webhook payload
- URL in webhook doesn't exactly match jenkins_instances.json
- Credentials wrong for that specific instance

**How to fix**:
- Add `jenkins_url: "${env.JENKINS_URL}"` to Jenkinsfile payload
- Check URL matching (trailing slash, http vs https)
- Test credentials manually: curl -u user:token JENKINS_URL/api/json
- Check application logs for credential matching errors

---

This guide focuses on *understanding* the system rather than just running commands. Each section explains the "what" and "why" to help you make informed decisions about configuration and troubleshooting.
