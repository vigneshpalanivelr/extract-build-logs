# API POST Implementation Design

## Overview
Instead of dumping logs to files, the system will POST pipeline logs to an API endpoint and log the request/response details.

## Configuration (Environment Variables)

Add to `.env`:

```bash
# API Posting Configuration
API_POST_ENABLED=true                    # Enable/disable API posting (default: false)
API_POST_URL=https://api.example.com/logs  # API endpoint URL
API_POST_AUTH_TOKEN=your_token_here      # Bearer token for authentication
API_POST_TIMEOUT=30                      # Request timeout in seconds (default: 30)
API_POST_RETRY_ENABLED=true              # Use retry logic for failed requests (default: true)
API_POST_SAVE_TO_FILE=false              # Also save to file as fallback/backup (default: false)
```

## Modes

1. **API Only**: `API_POST_ENABLED=true` + `API_POST_SAVE_TO_FILE=false`
2. **Dual Mode** (API + File fallback): `API_POST_ENABLED=true` + `API_POST_SAVE_TO_FILE=true`
3. **File Only** (current behavior): `API_POST_ENABLED=false`

## API Request Format

**One POST request per pipeline** with all jobs batched together:

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
    },
    {
      "job_id": 457,
      "job_name": "test:unit",
      "log_content": "Full test logs here...",
      "status": "success",
      "stage": "test",
      "created_at": "2024-01-01T00:01:10Z",
      "started_at": "2024-01-01T00:01:15Z",
      "finished_at": "2024-01-01T00:02:00Z",
      "duration": 45.3,
      "ref": "main"
    }
  ]
}
```

**Authentication**: Bearer token in Authorization header
```
Authorization: Bearer <API_POST_AUTH_TOKEN>
```

**Content-Type**: `application/json`

## Logging (NOT Database)

Log API requests/responses to a dedicated log file: `logs/api-requests.log`

### Log Entry Format:
```
[2024-01-01 00:02:05] PIPELINE_ID=12345 PROJECT_ID=123 URL=https://api.example.com/logs STATUS=200 DURATION=1250ms RESPONSE={"success": true, "message": "Logs received"}
[2024-01-01 00:03:10] PIPELINE_ID=12346 PROJECT_ID=123 URL=https://api.example.com/logs STATUS=500 DURATION=2100ms ERROR=Internal Server Error RESPONSE={"error": "Database connection failed"}
```

### Log Fields:
- Timestamp
- Pipeline ID
- Project ID
- Request URL
- HTTP Status Code
- Response Body (first 1000 characters)
- Duration (milliseconds)
- Error messages (if any)

## Implementation Changes

### Files to Modify:

1. **`src/config_loader.py`**
   - Add new environment variables to `Config` dataclass
   - Load and validate API configuration

2. **`src/storage_manager.py`** or Create **`src/api_poster.py`** (new)
   - Create `ApiPoster` class to handle API POST requests
   - Method: `post_pipeline_logs(pipeline_info, all_logs)`
   - Handle authentication, retries, timeouts
   - Log request/response details

3. **`src/webhook_listener.py`**
   - Modify `process_pipeline_event()` function
   - After fetching all logs, check if `API_POST_ENABLED`
   - If enabled, POST to API instead of/in addition to file storage
   - Handle errors and fallback logic

4. **`.env.example`**
   - Add API configuration examples with comments

5. **`README.md`** / **`OPERATIONS.md`**
   - Document new API posting feature
   - Configuration examples
   - Troubleshooting guide

## Behavior

- **Batch Processing**: All jobs for a pipeline are sent in ONE API call
- **Retry Logic**: Use existing retry mechanism for failed API calls
- **Fallback**: If `API_POST_SAVE_TO_FILE=true`, save to file if API fails
- **Continue on Error**: If API POST fails, log error and continue (don't crash)
- **Filtering**: Respect existing filtering config (pipeline status, job status, etc.)

## Error Handling

1. API request fails → Log error to `api-requests.log`
2. If `API_POST_SAVE_TO_FILE=true` → Save to file as fallback
3. If retry enabled → Retry with exponential backoff
4. Continue processing (don't block other pipelines)

## Receiving Service

The receiving API service is responsible for:
- Storing logs in its own database
- Processing/analyzing logs
- Returning success/error responses

Our service only:
- POSTs the data
- Logs the request/response
- Handles retries/fallback

---

## Questions/Decisions Pending:

- ✅ One API call per pipeline (batched jobs)
- ✅ Log to file, not database
- ✅ Configurable via environment variables
- ❓ Additional request headers needed?
- ❓ Specific response format expected?
- ❓ Any request payload size limits?
- ❓ Should we compress large payloads (gzip)?

---

**Status**: Design approved, waiting for final confirmation before implementation.

**Date**: 2025-11-04
