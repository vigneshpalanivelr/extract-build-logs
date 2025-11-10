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
# BFA Server Configuration (Required for API Posting)
# ============================================================================

# BFA Host - hostname or IP (without http:// prefix)
# API endpoint will be auto-constructed as: http://BFA_HOST:8000/api/analyze
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

### Validation Rules

| Variable | Required | Default | Validation |
|----------|----------|---------|------------|
| `BFA_HOST` | Yes (if API enabled) | - | Hostname or IP address |
| `BFA_SECRET_KEY` | Yes (if API enabled) | - | Any string (used as Bearer token) |
| `API_POST_ENABLED` | No | `false` | Must be `true` or `false` |
| `API_POST_TIMEOUT` | No | `30` | Integer between 1-300 |
| `API_POST_RETRY_ENABLED` | No | `true` | Must be `true` or `false` |
| `API_POST_SAVE_TO_FILE` | No | `false` | Must be `true` or `false` |

### API Endpoint

The API endpoint is **automatically constructed** from `BFA_HOST`:

```
http://{BFA_HOST}:8000/api/analyze
```

**Examples:**
- `BFA_HOST=bfa-server.example.com` → `http://bfa-server.example.com:8000/api/analyze`
- `BFA_HOST=192.168.1.100` → `http://192.168.1.100:8000/api/analyze`

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

### Simplified Format (v2.0)

The system sends a **lightweight payload** focused on failed jobs and error extraction:

```json
{
  "repo": "api-backend",
  "branch": "feature/user-auth",
  "commit": "abc123d",
  "job_name": ["build:docker", "test:unit", "test:integration", "deploy:staging"],
  "pipeline_id": "12345",
  "triggered_by": "john.doe",
  "failed_steps": [
    {
      "step_name": "build:docker",
      "error_lines": [
        "npm ERR! code ERESOLVE",
        "npm ERR! ERESOLVE unable to resolve dependency tree",
        "npm ERR! Could not resolve dependency:",
        "npm ERR! peer react@\"^17.0.0\" from react-dom@17.0.2",
        "ERROR: npm install failed",
        "ERROR: Build failed with exit code 1"
      ]
    },
    {
      "step_name": "test:integration",
      "error_lines": [
        "AssertionError: expected 401 but got 500",
        "TypeError: Cannot read property 'id' of undefined",
        "2 tests failed, 3 passed",
        "ERROR: Test suite failed"
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

### Payload Size Comparison

| Pipeline Type | Old Format | New Format | Reduction |
|--------------|------------|------------|-----------|
| Small (3 jobs, 10KB logs) | ~30 KB | ~1 KB | **97%** |
| Medium (10 jobs, 100KB logs) | ~1 MB | ~3 KB | **99.7%** |
| Large (50 jobs, 500KB logs) | ~25 MB | ~15 KB | **99.9%** |

**Benefits:**
- ✓ 97-99% smaller payloads
- ✓ Faster network transfer
- ✓ Lower API endpoint processing cost
- ✓ Easier to store and query
- ✓ Focused on actionable error data

---

## Authentication

### Bearer Token Authentication

The system uses **HTTP Bearer token** authentication with `BFA_SECRET_KEY`:

```http
POST /api/analyze HTTP/1.1
Host: bfa-server.example.com:8000
Authorization: Bearer your_bfa_secret_key
Content-Type: application/json

{payload}
```

### Configuration

```bash
# In .env file:
BFA_SECRET_KEY=your_bfa_secret_key

# Token is automatically added to Authorization header as Bearer token
```

### Security

- ✓ Token is **masked in logs** (`Bearer *****`)
- ✓ Token is **never** written to log files
- ✓ Same secret key used for JWT token signing
- ✓ Transmitted over HTTP (HTTPS recommended for production)
- ✓ No token validation on client side (API validates)

### Required Authentication

**Note:** `BFA_SECRET_KEY` is **required** when `API_POST_ENABLED=true`.

```bash
# Both required for API posting:
BFA_HOST=bfa-server.example.com
BFA_SECRET_KEY=your_secret_key

# System will validate on startup and fail if missing
```

---

## API Request and Response Details

### HTTP Request Format

**Endpoint:** `POST http://{BFA_HOST}:8000/api/analyze`

**Headers:**
```http
POST /api/analyze HTTP/1.1
Host: {BFA_HOST}:8000
Content-Type: application/json
Authorization: Bearer {BFA_SECRET_KEY}
User-Agent: GitLab-Pipeline-Log-Extractor/2.0
```

**Request Body:**
```json
{
  "repo": "api-backend",
  "branch": "feature/user-auth",
  "commit": "abc123d",
  "job_name": ["build:docker", "test:unit"],
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
    }
  ]
}
```

### Success Response (HTTP 200)

**Status Code:** `200 OK`

**Response Format:**
```json
{
  "status": "ok",
  "results": [
    {
      "error_hash": "60b7634d92fcd9eda5c3d3755fda94a6fb6d50c00b707f6a129a08a0ab787c3b",
      "source": "slack_posted",
      "step_name": "unit-test",
      "error_text": "semi colon missing",
      "fix": "## Fix: Semi colon missing\n\n**Root Cause:** Missing semicolon in JavaScript code.\n\n**Steps:**\n1. Add semicolon at the end of the statement\n2. Enable ESLint to catch these errors\n\n**Code Fix:**\n\n```javascript\n// Before (causes error)\nconst value = obj.property\n\n// After (fixed)\nconst value = obj.property;\n```\n\n**Quick Debug:**\n- Check line number in error message\n- Enable linting in your editor\n- Use Prettier for auto-formatting\n\n[debug] prompt tokens=52, output tokens=212, total tokens=264"
    },
    {
      "error_hash": "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0u1v2w3x4y5z6",
      "source": "slack_posted",
      "step_name": "integration-test",
      "error_text": "Cannot read properties of undefined",
      "fix": "## Fix: Cannot read properties of undefined\n\n**Root Cause:** Trying to access a property on an undefined/null object.\n\n**Steps:**\n1. Add null/undefined checks before property access\n2. Use optional chaining or defensive programming\n\n**Code Fix:**\n\n```javascript\n// Before (causes error)\nconst value = obj.property.nestedProperty;\n\n// After (safe approaches)\n// Option 1: Optional chaining\nconst value = obj?.property?.nestedProperty;\n\n// Option 2: Null check\nconst value = obj && obj.property && obj.property.nestedProperty;\n\n// Option 3: Default values\nconst value = obj?.property?.nestedProperty || 'defaultValue';\n```\n\n**Quick Debug:**\n- Add `console.log(obj)` before the failing line to identify which object is undefined\n- Check if async data has loaded before accessing properties\n- Ensure API responses/imports are properly handled\n\n[debug] prompt tokens=52, output tokens=212, total tokens=264"
    }
  ]
}
```

**Response Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | Always `"ok"` for successful analysis |
| `results` | array | Array of error analysis results |
| `results[].error_hash` | string | Unique hash identifier for the error |
| `results[].source` | string | Source of the fix (e.g., "slack_posted") |
| `results[].step_name` | string | Name of the failed step |
| `results[].error_text` | string | Brief description of the error |
| `results[].fix` | string | Markdown-formatted fix instructions with code examples |

**Processing Success Response:**
- Status 200 indicates successful error analysis
- Parse `results` array to extract error fixes
- Each result contains actionable fix information
- `fix` field contains detailed Markdown documentation
- **Action:** Send email to pipeline user with all error fixes

### Failure Response (HTTP != 200)

**Status Codes:**
- `400 Bad Request` - Invalid payload format
- `401 Unauthorized` - Invalid or missing BFA_SECRET_KEY
- `500 Internal Server Error` - Server error
- `503 Service Unavailable` - Server temporarily unavailable
- `504 Gateway Timeout` - Request timeout

**Response Format:**
```json
{
  "error": "Invalid payload format",
  "message": "Missing required field: pipeline_id",
  "code": "INVALID_PAYLOAD"
}
```

**Error Response Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `error` | string | Error type/summary |
| `message` | string | Detailed error message |
| `code` | string | Machine-readable error code |

**Processing Failure Response:**
- Status != 200 indicates failure
- Log error details for debugging
- **Action:** Send alert email to DevOps team
- Include error message and status code
- May trigger retry logic if enabled

### Response Handling Flow

```
API Response Received
       │
       ├─→ [Status 200]
       │      │
       │      ├─→ Parse results array
       │      ├─→ Extract error fixes
       │      ├─→ Send email to PIPELINE USER
       │      │   ├─ Subject: "Build Failures Fixed: [repo/branch]"
       │      │   ├─ Body: All error analysis + fixes
       │      │   └─ Format: HTML email with code blocks
       │      └─→ Log success
       │
       └─→ [Status != 200]
              │
              ├─→ Log error details
              ├─→ Send alert to DEVOPS TEAM
              │   ├─ Subject: "BFA API Failure: [pipeline_id]"
              │   ├─ Body: Error message + status code
              │   └─ Include: Pipeline details
              └─→ Trigger retry (if enabled)
```

### Example cURL Request

```bash
curl -X POST http://bfa-server.example.com:8000/api/analyze \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your_bfa_secret_key" \
  -d '{
    "repo": "api-backend",
    "branch": "main",
    "commit": "abc123",
    "job_name": ["build", "test"],
    "pipeline_id": "12345",
    "triggered_by": "john.doe",
    "failed_steps": [
      {
        "step_name": "test",
        "error_lines": ["Error: Test failed", "AssertionError: expected true"]
      }
    ]
  }'
```

**Expected Output (Success):**
```json
{
  "status": "ok",
  "results": [...]
}
```

**Expected Output (Failure):**
```json
{
  "error": "Unauthorized",
  "message": "Invalid Bearer token",
  "code": "AUTH_FAILED"
}
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
# BFA_HOST=bfa-server.example.com
# BFA_SECRET_KEY=your_secret_key

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

@app.post('/pipeline-logs')
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
    uvicorn.run(app, host='0.0.0.0', port=5000)
```

**Node.js Express:**
```javascript
const express = require('express');
const app = express();

app.use(express.json({ limit: '10mb' }));  // Smaller limit due to simplified format

app.post('/pipeline-logs', (req, res) => {
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
BFA_HOST=httpbin.org
BFA_SECRET_KEY=test_token

# Restart:
sudo systemctl restart gitlab-log-extractor
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

@app.post('/logs')
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
    return {"status": "success"}

if __name__ == '__main__':
    uvicorn.run(app, host='0.0.0.0', port=5000, log_level='info')
```

```bash
# Install FastAPI and uvicorn:
pip install fastapi uvicorn

# Run test server:
python test_api_server.py

# In another terminal, configure:
BFA_HOST=localhost
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
   sudo systemctl restart gitlab-log-extractor
   ```

---

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
- [ ] Set `BFA_HOST` to your BFA server hostname
- [ ] Set `BFA_SECRET_KEY` for authentication
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

## Appendix: Design History & Implementation Notes

### Original Design (v1.0)

The API posting feature was originally designed to send complete pipeline logs with full job output to external APIs. Below is the historical design documentation preserved for reference.

#### Design Overview

**Goal:** POST pipeline logs to an API endpoint instead of/in addition to saving to files.

**Approach:** Batch all jobs for a pipeline into ONE API call with complete log content.

#### Original Payload Format (v1.0 - Legacy)

```json
{
  "pipeline_id": 12345,
  "project_id": 123,
  "project_name": "my-app",
  "status": "success",
  "ref": "main",
  "sha": "abc123def456...",
  "source": "push",
  "pipeline_type": "main",
  "created_at": "2024-01-01T00:00:00Z",
  "finished_at": "2024-01-01T00:02:00Z",
  "duration": 120.5,
  "user": {
    "name": "John Doe",
    "email": "john@example.com"
  },
  "stages": ["build", "test", "deploy"],
  "jobs": [
    {
      "job_id": 456,
      "job_name": "build:production",
      "log_content": "Full build logs here...",
      "status": "success",
      "stage": "build",
      "created_at": "2024-01-01T00:00:00Z",
      "started_at": "2024-01-01T00:00:05Z",
      "finished_at": "2024-01-01T00:01:05Z",
      "duration": 60.2,
      "ref": "main"
    }
  ]
}
```

**Issues with v1.0:**
- Large payload sizes (1-25 MB for typical pipelines)
- Network transfer overhead
- Included full logs with success messages mixed with errors
- Included all jobs (successful and failed)

#### Evolution to v2.0

**Motivation:** Reduce payload size by 97-99% and focus on actionable error data.

**Changes in v2.0:**
1. **Simplified structure** - Removed timestamps, durations, stages metadata
2. **Error extraction** - Parse logs to extract only error lines
3. **Failed jobs only** - Include only failed steps in `failed_steps` array
4. **Short identifiers** - 7-char commit SHA, repo name without org
5. **Error cleaning** - Remove timestamps, ANSI codes, duplicates from error lines

**Result:** Typical payload reduced from 30KB-25MB to 1-15KB (97-99% reduction)

#### Implementation Details

**Files Modified:**
- `src/config_loader.py` - API configuration fields
- `src/api_poster.py` - API posting logic with v2.0 format
- `src/webhook_listener.py` - Integration with pipeline processing
- `.env.example` - Configuration examples
- Documentation (this file)

**Implemented:** 2025-11-04
**Updated to v2.0:** 2025-11-07

#### Design Decisions

**Q: One API call per pipeline vs. one per job?**
A: One per pipeline (batched) to reduce API calls and provide complete context.

**Q: Log to file or database?**
A: Log to `logs/api-requests.log` file for simplicity and separation of concerns.

**Q: Compress large payloads?**
A: Not needed with v2.0 format (payloads now <15KB). Can add if required later.

**Q: Retry logic?**
A: Yes, exponential backoff with configurable retries (default: 3 attempts, 2/4/8s delays).

**Q: Fallback on failure?**
A: Controlled by `API_POST_SAVE_TO_FILE` setting. If true, saves to files on API failure.

#### Behavior Characteristics

- **Batch Processing:** All jobs sent in single API request
- **Retry Logic:** Uses existing error handler with exponential backoff
- **Fallback:** Optional file storage if API fails
- **Continue on Error:** Logs error and continues (doesn't crash)
- **Filtering:** Respects LOG_SAVE_PIPELINE_STATUS and other filters
- **Error Handling:** Graceful degradation if API unavailable

#### Future Enhancements (Potential)

- Payload compression (gzip) for very large error outputs
- Webhook-style confirmation/acknowledgment from receiving API
- Batch multiple pipelines in single API call (configurable)
- Custom payload transformations via plugins
- Metrics/monitoring dashboard for API posting success rates

---

*Last Updated: 2025-11-07*
