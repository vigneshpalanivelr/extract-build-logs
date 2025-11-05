# GitLab Webhook Setup Guide

This guide explains how to configure GitLab webhooks to send pipeline events to your log extraction server.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Setup Steps](#setup-steps)
  - [1. Navigate to Webhook Settings](#1-navigate-to-webhook-settings)
  - [2. Configure Webhook URL](#2-configure-webhook-url)
  - [3. Set Secret Token](#3-set-secret-token-recommended)
  - [4. Select Trigger Events](#4-select-trigger-events)
  - [5. Configure SSL Verification](#5-configure-ssl-verification)
  - [6. Test the Webhook](#6-test-the-webhook)
  - [7. Verify Event Reception](#7-verify-event-reception)
- [Webhook Payload Example](#webhook-payload-example)
- [Troubleshooting](#troubleshooting)
  - [Webhook Returns 401 Unauthorized](#webhook-returns-401-unauthorized)
  - [Webhook Returns 500 Internal Server Error](#webhook-returns-500-internal-server-error)
  - [No Logs Are Saved](#no-logs-are-saved)
  - [Connection Refused](#connection-refused)
- [Security Best Practices](#security-best-practices)
- [Testing with curl](#testing-with-curl)
- [Next Steps](#next-steps)

---

## Prerequisites

- Access to GitLab project settings (Maintainer or Owner role)
- Running webhook server (see main README for setup)
- Server accessible from GitLab (public IP or ngrok tunnel for local development)

## Setup Steps

### 1. Navigate to Webhook Settings

1. Go to your GitLab project
2. Navigate to **Settings → Webhooks**

### 2. Configure Webhook URL

Enter your server URL in the format:
```
http://your-server-ip:8000/webhook
```

**Examples:**
- Production: `https://logs.company.com/webhook`
- Local (with ngrok): `https://abc123.ngrok.io/webhook`
- Local network: `http://192.168.1.100:8000/webhook`

### 3. Set Secret Token (Recommended)

1. Generate a secure random token:
   ```bash
   openssl rand -hex 32
   ```

2. Enter the token in GitLab's "Secret token" field

3. Add the same token to your `.env` file:
   ```bash
   WEBHOOK_SECRET=your_generated_token_here
   ```

### 4. Select Trigger Events

**Enable only Pipeline events:**
- ✓ **Pipeline events** (REQUIRED)

Disable all other events unless you plan to handle them.

### 5. Configure SSL Verification

- **Production**: Enable SSL verification (recommended)
- **Development**: Disable if using self-signed certificates

### 6. Test the Webhook

1. Click **"Add webhook"** to save

2. Scroll down to find your webhook in the list

3. Click **"Test" → "Pipeline events"**

4. Check your server logs for the test event:
   ```bash
   tail -f webhook_server.log
   ```

5. Expected response: `200 OK` with JSON response

### 7. Verify Event Reception

Trigger a real pipeline and verify logs are extracted:

1. Push a commit or manually run a pipeline

2. Check server logs:
   ```bash
   tail -f webhook_server.log
   ```

3. Verify logs were saved:
   ```bash
   ls -lah logs/
   ```

## Webhook Payload Example

GitLab sends POST requests with this structure:

```json
{
  "object_kind": "pipeline",
  "object_attributes": {
    "id": 12345,
    "ref": "main",
    "sha": "abc123...",
    "status": "success",
    "source": "push",
    "duration": 225
  },
  "project": {
    "id": 123,
    "name": "my-project"
  },
  "builds": [
    {
      "id": 456,
      "name": "build",
      "stage": "build",
      "status": "success"
    }
  ]
}
```

## Troubleshooting

### Webhook Returns 401 Unauthorized

**Problem**: Secret token mismatch

**Solution**:
- Verify `WEBHOOK_SECRET` in `.env` matches GitLab webhook secret
- Check for extra spaces or newlines in token

### Webhook Returns 500 Internal Server Error

**Problem**: Server configuration issue

**Solution**:
- Check server logs: `tail -f webhook_server.log`
- Verify `GITLAB_TOKEN` has correct permissions
- Ensure `GITLAB_URL` is correct

### No Logs Are Saved

**Problem**: Pipeline processing issue

**Solution**:
1. Check if pipeline is completed (`status: success` or `failed`)
2. Verify logs directory permissions
3. Check server logs for errors

### Connection Refused

**Problem**: Server not accessible

**Solution**:
- Verify server is running: `curl http://localhost:8000/health`
- Check firewall rules
- For local development, use ngrok:
  ```bash
  ngrok http 8000
  ```

## Security Best Practices

1. **Always use HTTPS in production**
   - Use reverse proxy (nginx, Apache) with SSL certificate
   - Use Let's Encrypt for free SSL certificates

2. **Configure webhook secret token**
   - Use strong random tokens (32+ characters)
   - Rotate tokens periodically

3. **Restrict network access**
   - Use firewall rules to allow only GitLab IP ranges
   - GitLab.com IP ranges: https://docs.gitlab.com/ee/user/gitlab_com/

4. **Monitor webhook activity**
   - Review logs regularly
   - Set up alerts for failed requests

5. **Limit webhook scope**
   - Only enable Pipeline events
   - Consider separate webhooks for different purposes

## Testing with curl

You can test the webhook endpoint manually:

```bash
curl -X POST http://localhost:8000/webhook/gitlab \
  -H "Content-Type: application/json" \
  -H "X-Gitlab-Event: Pipeline Hook" \
  -H "X-Gitlab-Token: your_secret_token" \
  -d @test_payload.json
```

## Next Steps

After webhook setup:
1. Monitor initial pipeline runs
2. Verify log extraction works correctly
3. Adjust configuration as needed
4. Set up log analysis tools
