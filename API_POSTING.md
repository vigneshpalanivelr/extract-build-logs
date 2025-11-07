# API Posting Documentation

Complete guide for sending pipeline logs to external API endpoints.

---

## Table of Contents

1. [Overview](#overview)
2. [Configuration](#configuration)
3. [Payload Format](#payload-format)
4. [Authentication](#authentication)
5. [Operating Modes](#operating-modes)
6. [Retry Logic](#retry-logic)
7. [API Request Logging](#api-request-logging)
8. [Debugging](#debugging)
9. [API Endpoint Requirements](#api-endpoint-requirements)
10. [Testing](#testing)
11. [Troubleshooting](#troubleshooting)

---

## Overview

The API posting feature allows you to **send pipeline logs to an external API** instead of (or in addition to) saving them to files.

**Use Cases:**
- Centralized log aggregation
- Real-time log analysis
- Integration with monitoring systems
- Custom log processing pipelines
- Compliance and audit logging

**Key Features:**
- ✓ HTTP POST with JSON payload
- ✓ Bearer token authentication
- ✓ Automatic retry with exponential backoff
- ✓ Fallback to file storage on failure
- ✓ Dual mode (API + file simultaneously)
- ✓ Detailed request/response logging
- ✓ Configurable timeouts

---

## Configuration

### Environment Variables

Add these to your `.env` file:

```bash
# ============================================================================
# API Posting Configuration
# ============================================================================

# Enable/disable API posting
API_POST_ENABLED=true

# API endpoint URL (required if enabled)
API_POST_URL=https://your-api.example.com/pipeline-logs

# Authentication token (optional but recommended)
API_POST_AUTH_TOKEN=your_bearer_token_here

# Request timeout in seconds (default: 30, range: 1-300)
API_POST_TIMEOUT=30

# Enable retry on failure (default: true)
API_POST_RETRY_ENABLED=true

# Save to file even if API succeeds (dual mode, default: false)
API_POST_SAVE_TO_FILE=false
```

### Validation Rules

| Variable | Required | Default | Validation |
|----------|----------|---------|------------|
| `API_POST_ENABLED` | No | `false` | Must be `true` or `false` |
| `API_POST_URL` | Yes (if enabled) | - | Must be valid HTTP/HTTPS URL |
| `API_POST_AUTH_TOKEN` | No | - | Any string |
| `API_POST_TIMEOUT` | No | `30` | Integer between 1-300 |
| `API_POST_RETRY_ENABLED` | No | `true` | Must be `true` or `false` |
| `API_POST_SAVE_TO_FILE` | No | `false` | Must be `true` or `false` |

### Configuration Validation

The system validates configuration on startup:

```bash
# Check logs for validation messages:
grep "API posting" logs/application.log

# Expected output:
# INFO | API posting enabled: https://your-api.example.com/pipeline-logs
# INFO | API posting disabled - logs will be saved to files only
```

---

## Payload Format

### Current Format (v1.0)

The system sends a **complete pipeline snapshot** with all job logs:

```json
{
  "pipeline": {
    "id": 12345,
    "project_id": 123,
    "project_name": "my-app",
    "status": "failed",
    "ref": "main",
    "sha": "abc123def456",
    "source": "push",
    "pipeline_type": "main",
    "created_at": "2024-01-01T10:00:00Z",
    "finished_at": "2024-01-01T10:05:00Z",
    "duration": 300.5,
    "user": {
      "name": "John Doe",
      "username": "jdoe",
      "email": "jdoe@example.com"
    },
    "stages": ["build", "test", "deploy"]
  },
  "jobs": [
    {
      "id": 456,
      "name": "build",
      "stage": "build",
      "status": "success",
      "created_at": "2024-01-01T10:00:05Z",
      "started_at": "2024-01-01T10:00:10Z",
      "finished_at": "2024-01-01T10:01:10Z",
      "duration": 60.2,
      "ref": "main",
      "log": "$ npm install\nadded 234 packages...\n$ npm run build\nBuild successful!\n"
    },
    {
      "id": 457,
      "name": "test",
      "stage": "test",
      "status": "failed",
      "created_at": "2024-01-01T10:01:15Z",
      "started_at": "2024-01-01T10:01:20Z",
      "finished_at": "2024-01-01T10:02:05Z",
      "duration": 45.8,
      "ref": "main",
      "log": "$ npm test\nRunning tests...\n  ✓ Test 1\n  ✗ Test 2 - FAILED\nError: Expected 5 but got 3\n"
    }
  ]
}
```

### Field Descriptions

**Pipeline Object:**
| Field | Type | Description |
|-------|------|-------------|
| `id` | integer | GitLab pipeline ID |
| `project_id` | integer | GitLab project ID |
| `project_name` | string | Human-readable project name |
| `status` | string | Pipeline status: `success`, `failed`, `canceled`, etc. |
| `ref` | string | Git branch or tag name |
| `sha` | string | Git commit SHA (full 40 characters) |
| `source` | string | Trigger source: `push`, `web`, `schedule`, `api`, `trigger`, `parent_pipeline` |
| `pipeline_type` | string | Type: `main`, `child`, `merge_request`, `unknown` |
| `created_at` | string | ISO 8601 timestamp |
| `finished_at` | string | ISO 8601 timestamp |
| `duration` | float | Pipeline duration in seconds |
| `user` | object | User who triggered the pipeline |
| `stages` | array | List of pipeline stages |

**Job Object:**
| Field | Type | Description |
|-------|------|-------------|
| `id` | integer | GitLab job ID |
| `name` | string | Job name |
| `stage` | string | Stage name |
| `status` | string | Job status: `success`, `failed`, `canceled`, `skipped` |
| `created_at` | string | ISO 8601 timestamp |
| `started_at` | string | ISO 8601 timestamp |
| `finished_at` | string | ISO 8601 timestamp |
| `duration` | float | Job duration in seconds |
| `ref` | string | Git branch/tag |
| `log` | string | **Complete job log output** |

### Payload Size

**Typical sizes:**
- Small pipeline (3 jobs, 10KB logs each): ~30 KB
- Medium pipeline (10 jobs, 100KB logs each): ~1 MB
- Large pipeline (50 jobs, 500KB logs each): ~25 MB

**Note:** Very large payloads (>10MB) may need compression support (future enhancement).

---

## Authentication

### Bearer Token Authentication

The system uses **HTTP Bearer token** authentication:

```http
POST /your-endpoint HTTP/1.1
Host: your-api.example.com
Authorization: Bearer your_token_here
Content-Type: application/json

{payload}
```

### Configuration

```bash
# In .env file:
API_POST_AUTH_TOKEN=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...

# Token is automatically added to Authorization header
```

### Security

- ✓ Token is **masked in logs** (`Bearer *****`)
- ✓ Token is **never** written to log files
- ✓ Transmitted over **HTTPS** (recommended)
- ✓ No token validation on client side (API validates)

### No Authentication

If your API doesn't require authentication:

```bash
# Leave empty or don't set:
API_POST_AUTH_TOKEN=

# System will send requests without Authorization header
```

---

## Operating Modes

### Mode 1: API Only (Default)

**Configuration:**
```bash
API_POST_ENABLED=true
API_POST_SAVE_TO_FILE=false
```

**Behavior:**
1. Try to POST to API
2. If **successful** → Done ✓
3. If **failed** → Fall back to file storage

**Use when:**
- API is primary log destination
- Files are backup only
- Want to save storage space

---

### Mode 2: Dual Mode (API + File)

**Configuration:**
```bash
API_POST_ENABLED=true
API_POST_SAVE_TO_FILE=true
```

**Behavior:**
1. POST to API (always)
2. Save to file (always, regardless of API result)

**Use when:**
- Need both API and local files
- Want file backup even if API succeeds
- Compliance requires local retention

---

### Mode 3: File Only (Traditional)

**Configuration:**
```bash
API_POST_ENABLED=false
```

**Behavior:**
1. Save to files only
2. No API calls made

**Use when:**
- Not ready to use API posting
- Testing/development
- No API endpoint available

---

## Retry Logic

### Exponential Backoff

Failed API requests are **automatically retried** with exponential backoff:

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

Attempt 4: Final retry POST
  ↓ (succeeds or gives up)
```

### Retry Configuration

```bash
# Enable/disable retry (default: true)
API_POST_RETRY_ENABLED=true

# Retry is controlled by global settings:
RETRY_ATTEMPTS=3    # Number of retries (default: 3)
RETRY_DELAY=2       # Base delay in seconds (default: 2)
```

### What Triggers Retry

**Retriable errors:**
- Network connection errors
- Timeout errors
- HTTP 500-599 (server errors)
- HTTP 429 (rate limiting)

**Non-retriable errors (stop immediately):**
- HTTP 400-499 (client errors, except 429)
  - 400 Bad Request
  - 401 Unauthorized
  - 403 Forbidden
  - 404 Not Found
- Invalid URL
- Invalid JSON payload

### Retry Logging

```bash
# Check retry attempts in logs:
grep "Retry attempt" logs/api-requests.log

# Example output:
# Retry attempt 1/3 for pipeline 12345 after 2.0s
# Retry attempt 2/3 for pipeline 12345 after 4.0s
# API POST failed after 3 retries, falling back to file storage
```

---

## API Request Logging

### Dedicated Log File

All API requests/responses are logged to:

```bash
logs/api-requests.log
```

### Log Format

```
[2024-01-01 10:05:00] PIPELINE_ID=12345 STATUS=success DURATION=234ms
REQUEST: POST https://your-api.example.com/pipeline-logs
  Headers: Authorization: Bearer *****, Content-Type: application/json
  Payload Size: 1234 bytes (5 jobs)
RESPONSE: 200 OK
  Headers: Content-Type: application/json
  Body: {"status": "received", "pipeline_id": 12345}

[2024-01-01 10:10:00] PIPELINE_ID=12346 STATUS=failed DURATION=30002ms
REQUEST: POST https://your-api.example.com/pipeline-logs
  Headers: Authorization: Bearer *****, Content-Type: application/json
  Payload Size: 5678 bytes (8 jobs)
RESPONSE: 500 Internal Server Error
  Headers: Content-Type: application/json
  Body: {"error": "Database connection failed"}
ACTION: Retry attempt 1/3 after 2.0s
```

### Log Rotation

- **Size limit:** 50 MB per file
- **Backups:** 10 rotated files
- **Total storage:** ~550 MB
- **Auto-rotation:** When size limit reached

### Viewing Logs

```bash
# Tail live API requests:
tail -f logs/api-requests.log

# Search for specific pipeline:
grep "PIPELINE_ID=12345" logs/api-requests.log

# Find failed requests:
grep "STATUS=failed" logs/api-requests.log

# Check response codes:
grep "RESPONSE:" logs/api-requests.log
```

---

## Debugging

### Step 1: Check Configuration

```bash
# Verify environment variables are set:
grep "^API_POST" .env

# Expected output:
# API_POST_ENABLED=true
# API_POST_URL=https://your-api.example.com/endpoint
# API_POST_AUTH_TOKEN=your_token

# Check if configuration loaded correctly:
grep "API posting" logs/application.log

# Expected output:
# INFO | API posting enabled: https://your-api.example.com/endpoint
```

### Step 2: Test API Endpoint Manually

```bash
# Test with curl:
curl -X POST https://your-api.example.com/endpoint \
  -H "Authorization: Bearer your_token" \
  -H "Content-Type: application/json" \
  -d '{
    "pipeline": {
      "id": 99999,
      "project_name": "test",
      "status": "success"
    },
    "jobs": []
  }'

# Expected response:
# {"status": "success", "message": "Logs received"}
```

### Step 3: Send Test Webhook

```bash
# Use built-in test command:
./manage_container.py test

# This triggers a test pipeline event
# Check if API POST was attempted:
tail -20 logs/api-requests.log
```

### Step 4: Check API Request Log

```bash
# View last 50 lines:
tail -50 logs/api-requests.log

# Look for:
# - REQUEST line (should show your API URL)
# - RESPONSE line (should show 200 OK)
# - Any error messages
```

### Step 5: Check Application Log

```bash
# Search for API-related errors:
grep -i "api post" logs/application.log

# Search for specific pipeline:
grep "pipeline_id=12345" logs/application.log
```

### Step 6: Verify Network Connectivity

```bash
# Test if API is reachable:
curl -I https://your-api.example.com/endpoint

# Expected:
# HTTP/1.1 200 OK (or 405 Method Not Allowed for GET)

# Check DNS resolution:
nslookup your-api.example.com

# Check connectivity:
ping your-api.example.com
```

### Step 7: Check Container Logs

```bash
# If using Docker:
docker logs bfa-gitlab-pipeline-extractor | grep -i "api"

# Or:
./manage_container.py logs | grep -i "api"
```

### Common Debug Commands

```bash
# 1. Is API posting enabled?
grep "API_POST_ENABLED" .env

# 2. What's the API URL?
grep "API_POST_URL" .env

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

---

## API Endpoint Requirements

### Your API Must Handle

**HTTP Method:** `POST`

**Headers:**
- `Content-Type: application/json`
- `Authorization: Bearer <token>` (if token configured)

**Request Body:** JSON payload (see [Payload Format](#payload-format))

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

**Python Flask:**
```python
from flask import Flask, request, jsonify

app = Flask(__name__)

@app.route('/pipeline-logs', methods=['POST'])
def receive_logs():
    # Verify authentication
    auth_header = request.headers.get('Authorization')
    if auth_header != 'Bearer your_secret_token':
        return jsonify({"error": "Unauthorized"}), 401

    # Parse payload
    data = request.get_json()
    pipeline_id = data['pipeline']['id']
    project_name = data['pipeline']['project_name']
    jobs = data['jobs']

    # Process logs (your logic here)
    print(f"Received pipeline {pipeline_id} from {project_name} with {len(jobs)} jobs")

    # Store in database, forward to analytics, etc.
    # ...

    # Return success
    return jsonify({
        "status": "success",
        "message": f"Received {len(jobs)} job logs",
        "pipeline_id": pipeline_id
    }), 200

if __name__ == '__main__':
    app.run(port=5000)
```

**Node.js Express:**
```javascript
const express = require('express');
const app = express();

app.use(express.json({ limit: '50mb' }));

app.post('/pipeline-logs', (req, res) => {
    // Verify authentication
    const authHeader = req.headers.authorization;
    if (authHeader !== 'Bearer your_secret_token') {
        return res.status(401).json({ error: 'Unauthorized' });
    }

    // Parse payload
    const { pipeline, jobs } = req.body;
    console.log(`Received pipeline ${pipeline.id} with ${jobs.length} jobs`);

    // Process logs (your logic here)
    // ...

    // Return success
    res.json({
        status: 'success',
        message: `Received ${jobs.length} job logs`,
        pipeline_id: pipeline.id
    });
});

app.listen(5000, () => {
    console.log('API listening on port 5000');
});
```

---

## Testing

### Step 1: Set Up Test API

**Option A: Use httpbin.org (Public Test Service)**
```bash
# In .env:
API_POST_ENABLED=true
API_POST_URL=https://httpbin.org/post
API_POST_AUTH_TOKEN=test_token

# Restart:
sudo systemctl restart gitlab-log-extractor
```

**Option B: Run Local Test Server**
```python
# test_api_server.py
from flask import Flask, request, jsonify
import json

app = Flask(__name__)

@app.route('/logs', methods=['POST'])
def receive():
    print("="*80)
    print("Received API POST:")
    print(f"Headers: {dict(request.headers)}")
    print(f"Body size: {len(request.data)} bytes")
    data = request.get_json()
    print(f"Pipeline ID: {data['pipeline']['id']}")
    print(f"Jobs: {len(data['jobs'])}")
    print("="*80)
    return jsonify({"status": "success"}), 200

if __name__ == '__main__':
    app.run(port=5000, debug=True)
```

```bash
# Run test server:
python test_api_server.py

# In another terminal, configure:
API_POST_URL=http://localhost:5000/logs
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

---

## Troubleshooting

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

2. **Check URL is set:**
   ```bash
   grep "API_POST_URL" .env
   # Should have valid URL
   ```

3. **Check startup logs:**
   ```bash
   grep "API posting" logs/application.log
   # Should say "enabled" not "disabled"
   ```

4. **Restart service:**
   ```bash
   sudo systemctl restart gitlab-log-extractor
   ```

---

### Issue: Getting 401 Unauthorized

**Symptoms:**
- `RESPONSE: 401 Unauthorized` in api-requests.log

**Solutions:**

1. **Check token is set:**
   ```bash
   grep "API_POST_AUTH_TOKEN" .env
   ```

2. **Verify token is correct:**
   - Compare with your API's expected token

3. **Test manually:**
   ```bash
   curl -X POST https://your-api.com/endpoint \
     -H "Authorization: Bearer your_token" \
     -d '{"test": true}'
   ```

---

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

---

### Issue: Connection Refused

**Symptoms:**
- `Connection refused` error
- `Failed to establish connection`

**Solutions:**

1. **Check API is running:**
   ```bash
   curl -I https://your-api.com/endpoint
   ```

2. **Check firewall:**
   - Is port open?
   - Can container reach external network?

3. **Check URL:**
   - Correct protocol (http vs https)?
   - Correct domain/IP?
   - Correct port?

---

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

3. **Future enhancement:** Payload compression

---

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

## Summary

**Quick Start Checklist:**

- [ ] Set `API_POST_ENABLED=true` in .env
- [ ] Set `API_POST_URL` to your API endpoint
- [ ] Set `API_POST_AUTH_TOKEN` (if required)
- [ ] Restart service
- [ ] Send test webhook
- [ ] Check `logs/api-requests.log`
- [ ] Verify API received payload

**Key Files:**
- **Configuration:** `.env`
- **API Logs:** `logs/api-requests.log`
- **Application Logs:** `logs/application.log`
- **Code:** `src/api_poster.py`

**Need Help?**
- Check [Debugging](#debugging) section
- Review [Troubleshooting](#troubleshooting) section
- Check application logs for errors
- Verify API endpoint is working

---

*Last Updated: 2024*
