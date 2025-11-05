# Jenkins Integration Guide

This guide explains how to integrate Jenkins with the log extraction system to automatically post pipeline logs (including parallel stages) to your API.

## Table of Contents
- [Overview](#overview)
- [Prerequisites](#prerequisites)
- [Configuration](#configuration)
- [Jenkinsfile Setup](#jenkinsfile-setup)
- [API Payload Format](#api-payload-format)
- [Testing](#testing)
- [Troubleshooting](#troubleshooting)

---

## Overview

The Jenkins integration allows you to:
- Automatically extract build logs from Jenkins when builds complete (especially failures)
- Parse console logs to identify stages and parallel execution blocks
- Post structured log data to your API endpoint
- Handle Blue Ocean API data for better stage information

### Flow Diagram

```
Jenkins Pipeline Completes (FAILURE)
    ↓
Jenkinsfile post{} block sends webhook via curl
    ↓
Log Extractor receives webhook at /webhook/jenkins
    ↓
Fetches console log via Jenkins REST API
    ↓
Fetches Blue Ocean stage data (if available)
    ↓
Parses parallel blocks from console log
    ↓
Posts structured data to your API
```

---

## Prerequisites

1. **Jenkins Access**:
   - Jenkins URL (e.g., `https://jenkins.example.com`)
   - Jenkins user with API access
   - Jenkins API token

2. **API Endpoint**:
   - API endpoint URL configured in `.env`
   - API authentication token (if required)

3. **Network Access**:
   - Jenkins can reach the log extractor service
   - Log extractor can reach Jenkins API
   - Log extractor can reach your API endpoint

---

## Configuration

### Step 1: Generate Jenkins API Token

1. Log into Jenkins
2. Go to your user profile → **Configure**
3. Under **API Token**, click **Add new Token**
4. Give it a name (e.g., "Log Extractor")
5. Copy the generated token

### Step 2: Configure Environment Variables

Edit your `.env` file:

```bash
# Enable Jenkins integration
JENKINS_ENABLED=true

# Jenkins connection details
JENKINS_URL=https://jenkins.example.com
JENKINS_USER=your_username
JENKINS_API_TOKEN=your_api_token_here

# Optional: Webhook secret for authentication
JENKINS_WEBHOOK_SECRET=your_secret_token

# Enable API posting
API_POST_ENABLED=true
API_POST_URL=https://your-api.example.com/logs
API_POST_AUTH_TOKEN=your_api_bearer_token
```

### Step 3: Restart the Service

```bash
./manage_container.py restart
```

---

## Jenkinsfile Setup

### Option A: Post on Failures Only (Recommended)

Add this to your Jenkinsfile `post{}` block to send webhook **only when build fails**:

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
                        echo "Running unit tests..."
                        sh './test_unit.sh'
                    }
                }
                stage('Integration Tests') {
                    steps {
                        echo "Running integration tests..."
                        sh './test_integration.sh'
                    }
                }
                stage('UI Tests') {
                    steps {
                        echo "Running UI tests..."
                        sh './test_ui.sh'
                    }
                }
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
        failure {
            script {
                echo "Build failed! Sending logs to extractor..."

                // Send webhook to log extractor
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

### Option B: Post on All Build Completions

To send logs for all builds (success, failure, etc.):

```groovy
post {
    always {
        script {
            echo "Build completed. Sending logs to extractor..."

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
```

### Configuration Notes:

1. **Replace `http://your-log-extractor:8000`** with your actual service URL
2. **Replace `your_secret_token`** with the value from `JENKINS_WEBHOOK_SECRET` in `.env`
3. **The `|| true`** at the end prevents build failure if webhook fails
4. **Use `failure {}` block** to only send failed builds (recommended for production)

---

## API Payload Format

The log extractor will send the following JSON structure to your API:

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
          "duration_ms": 15000,
          "log_content": "... unit test logs here ..."
        },
        {
          "block_name": "Integration Tests",
          "status": "FAILURE",
          "duration_ms": 25000,
          "log_content": "... integration test logs with failure details ..."
        },
        {
          "block_name": "UI Tests",
          "status": "SUCCESS",
          "duration_ms": 30000,
          "log_content": "... UI test logs here ..."
        }
      ]
    },
    {
      "stage_name": "Deploy",
      "stage_id": "3",
      "status": "SKIPPED",
      "duration_ms": 0,
      "is_parallel": false,
      "log_content": ""
    }
  ]
}
```

### Key Fields:

- **`source`**: Always "jenkins" to distinguish from GitLab
- **`is_parallel`**: `true` if stage has parallel blocks
- **`parallel_blocks`**: Array of parallel execution blocks with individual logs
- **`log_content`**: Full console log for non-parallel stages
- **`status`**: BUILD result (SUCCESS, FAILURE, UNSTABLE, ABORTED, etc.)

---

## Testing

### Step 1: Test Webhook Endpoint

```bash
# Test that the endpoint is accessible
curl http://your-log-extractor:8000/health

# Expected response:
# {"status":"healthy","service":"gitlab-log-extractor","version":"1.0.0"}
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
# {
#   "status": "success",
#   "message": "Jenkins build logs queued for extraction",
#   "job_name": "test-pipeline",
#   "build_number": 1,
#   "request_id": "a1b2c3d4"
# }
```

### Step 3: Trigger Jenkins Build

1. Run a Jenkins pipeline that has the webhook configured
2. Let it fail (or complete)
3. Check the logs:

```bash
# View container logs
./manage_container.py logs

# Or check API request logs
tail -f logs/api-requests.log
```

### Step 4: Verify API Received Data

Check your API endpoint to confirm it received the payload with:
- Job name and build number
- All stages
- Parallel blocks (if any)
- Full console logs

---

## Troubleshooting

### Issue: "Jenkins integration is not enabled"

**Problem**: Webhook returns 503 error

**Solution**:
```bash
# Check .env configuration
grep JENKINS_ENABLED .env

# Should be:
JENKINS_ENABLED=true

# Restart service
./manage_container.py restart
```

### Issue: "Authentication failed"

**Problem**: Webhook returns 401 error

**Solution**:
- Check that `X-Jenkins-Token` header matches `JENKINS_WEBHOOK_SECRET` in `.env`
- Or remove `JENKINS_WEBHOOK_SECRET` from `.env` to disable authentication

### Issue: "Failed to fetch console log"

**Problem**: Can't retrieve logs from Jenkins

**Solution**:
```bash
# Test Jenkins API access manually
curl -u username:api_token \
    https://jenkins.example.com/job/my-pipeline/123/consoleText

# Check:
# 1. JENKINS_URL is correct (no trailing slash)
# 2. JENKINS_USER is correct
# 3. JENKINS_API_TOKEN is valid
# 4. Network connectivity from container to Jenkins
```

### Issue: "Parallel blocks not detected"

**Problem**: All stages show `is_parallel: false`

**Solution**:
- Jenkins must be using **Scripted Pipeline** or **Declarative Pipeline** with `parallel` keyword
- Console log must contain `[Pipeline] parallel` markers
- If using Blue Ocean, check that the plugin is installed:
  - Jenkins → Manage Plugins → Installed → search for "Blue Ocean"

### Issue: "API POST failed"

**Problem**: Logs extracted but not posted to API

**Solution**:
```bash
# Check API configuration
grep API_POST .env

# Test API endpoint manually
curl -X POST https://your-api.example.com/logs \
    -H 'Content-Type: application/json' \
    -H 'Authorization: Bearer your_token' \
    -d '{"test": "data"}'

# Check logs for error details
grep "API" logs/api-requests.log
```

### Viewing Detailed Logs

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

## Architecture Details

### Log Parsing Strategy

1. **With Blue Ocean API** (preferred):
   - Fetch `/wfapi/describe` for stage structure
   - Match console log segments to stages
   - Extract parallel blocks with accurate timing

2. **Without Blue Ocean API** (fallback):
   - Parse console log for `[Pipeline]` markers
   - Detect `parallel` blocks
   - Extract logs between markers
   - Timing data may be approximate

### Retry Logic

- Uses same retry configuration as GitLab API (`RETRY_ATTEMPTS`, `RETRY_DELAY`)
- Retries on network errors, timeouts, and 5xx responses
- Does not retry on 4xx errors (client errors)

### Security

- **Webhook Secret**: Optional but recommended
- **API Token**: Stored securely in `.env` (not in Jenkinsfile)
- **HTTPS**: Always use HTTPS in production
- **Network Isolation**: Run service in private network if possible

---

## Advanced Examples

### Multi-Branch Pipeline

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
        failure {
            script {
                // Include branch name in job_name
                def jobName = "${env.JOB_NAME}/${env.BRANCH_NAME}"

                sh """
                    curl -X POST http://your-log-extractor:8000/webhook/jenkins \\
                        -H 'Content-Type: application/json' \\
                        -d '{
                            "job_name": "${jobName}",
                            "build_number": ${env.BUILD_NUMBER},
                            "build_url": "${env.BUILD_URL}",
                            "status": "${currentBuild.result}"
                        }' || true
                """
            }
        }
    }
}
```

### Conditional Logging

```groovy
post {
    always {
        script {
            // Only send logs for master branch failures
            if (env.BRANCH_NAME == 'master' && currentBuild.result != 'SUCCESS') {
                sh """
                    curl -X POST http://your-log-extractor:8000/webhook/jenkins \\
                        -H 'Content-Type: application/json' \\
                        -d '{
                            "job_name": "${env.JOB_NAME}",
                            "build_number": ${env.BUILD_NUMBER},
                            "build_url": "${env.BUILD_URL}",
                            "status": "${currentBuild.result}"
                        }' || true
                """
            }
        }
    }
}
```

---

## Next Steps

1. **Monitor**: Check `logs/api-requests.log` for API calls
2. **Tune**: Adjust retry settings based on your API's reliability
3. **Scale**: Run multiple instances behind a load balancer if needed
4. **Alert**: Set up monitoring for webhook failures

For more information:
- See `README.md` for general setup
- See `API_POST_DESIGN.md` for API posting architecture
- See `.env.example` for all configuration options
