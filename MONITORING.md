# Pipeline Monitoring & Tracking Guide

Complete guide for monitoring and tracking GitLab pipeline webhook requests, processing status, and performance metrics.

## Table of Contents

- [Overview](#overview)
- [What is Tracked](#what-is-tracked)
- [Monitoring Dashboard](#monitoring-dashboard)
- [API Endpoints](#api-endpoints)
- [Viewing Statistics](#viewing-statistics)
- [Exporting Data](#exporting-data)
- [Database Location](#database-location)
- [Querying the Database](#querying-the-database)
- [Examples](#examples)

---

## Overview

The system automatically tracks **every webhook request** received and maintains a complete history of:

- ✅ How many pipeline requests received
- ✅ Processing status (queued, processing, completed, failed, skipped)
- ✅ Success/failure rates
- ✅ Processing times
- ✅ Job counts
- ✅ Error messages
- ✅ Client IP addresses
- ✅ Pipeline types (main, child, merge request)

All data is stored in a **SQLite database** at `logs/monitoring.db` and can be accessed via:
1. **API Endpoints** - REST API for programmatic access
2. **CLI Dashboard** - Command-line dashboard for viewing statistics
3. **CSV Export** - Export data to CSV for analysis in Excel/etc
4. **Direct SQL** - Query the database directly

---

## What is Tracked

### Automatic Tracking

Every webhook request is tracked with the following information:

| Field | Description | Example |
|-------|-------------|---------|
| `id` | Unique request ID | 1, 2, 3... |
| `timestamp` | When request was received | 2024-01-01T12:00:00Z |
| `project_id` | GitLab project ID | 123 |
| `pipeline_id` | GitLab pipeline ID | 789 |
| `pipeline_type` | Type of pipeline | main, child, merge_request |
| `status` | Processing status | queued, processing, completed, failed |
| `ref` | Git branch/tag | main, develop, v1.0.0 |
| `sha` | Git commit SHA | abc123... |
| `source` | Pipeline trigger source | push, web, schedule |
| `event_type` | GitLab event type | Pipeline Hook |
| `client_ip` | Client IP address | 192.168.1.100 |
| `processing_time` | Time to process (seconds) | 12.5 |
| `job_count` | Number of jobs in pipeline | 5 |
| `success_count` | Jobs successfully processed | 4 |
| `error_count` | Jobs that failed | 1 |
| `error_message` | Error message if failed | Connection timeout |
| `metadata` | Full pipeline info (JSON) | {...} |

### Request Status Flow

```
RECEIVED → IGNORED    (Wrong event type)
         → SKIPPED    (Pipeline not ready)
         → QUEUED → PROCESSING → COMPLETED  (Success)
                               → FAILED     (Error)
```

---

## Monitoring Dashboard

### CLI Dashboard Tool

A command-line dashboard is available for viewing statistics:

```bash
# Show 24-hour summary (default)
python monitor_dashboard.py

# Show 48-hour summary
python monitor_dashboard.py --hours 48

# Show recent 100 requests
python monitor_dashboard.py --recent 100

# Show details for specific pipeline
python monitor_dashboard.py --pipeline 12345

# Export data to CSV
python monitor_dashboard.py --export pipeline_data.csv

# Export last 24 hours to CSV
python monitor_dashboard.py --export data.csv --hours 24
```

### Dashboard Output Example

```
======================================================================
  PIPELINE MONITORING DASHBOARD - Last 24 Hours
======================================================================

Generated: 2024-01-01T12:00:00Z

📊 OVERALL STATISTICS
   Total Requests:      150
   Success Rate:        92.3%
   Avg Processing Time: 12.5s
   Total Jobs Processed: 450

📈 REQUESTS BY STATUS
╔═══════════╦═══════╗
║ Status    ║ Count ║
╠═══════════╬═══════╣
║ Completed ║   120 ║
║ Failed    ║    10 ║
║ Skipped   ║    15 ║
║ Processing║     5 ║
╚═══════════╩═══════╝

🔀 REQUESTS BY PIPELINE TYPE
╔════════════════╦═══════╗
║ Type           ║ Count ║
╠════════════════╬═══════╣
║ Main           ║   100 ║
║ Child          ║    30 ║
║ Merge_Request  ║    20 ║
╚════════════════╩═══════╝

======================================================================
```

---

## API Endpoints

### 1. Monitoring Summary

Get overall statistics for a time period.

**Endpoint:** `GET /monitor/summary?hours=24`

**Parameters:**
- `hours` (optional): Number of hours to include (default: 24)

**Example:**
```bash
curl http://localhost:8000/monitor/summary?hours=48
```

**Response:**
```json
{
  "time_period_hours": 48,
  "total_requests": 250,
  "by_status": {
    "completed": 200,
    "failed": 15,
    "skipped": 25,
    "processing": 10
  },
  "by_type": {
    "main": 180,
    "child": 50,
    "merge_request": 20
  },
  "success_rate": 93.0,
  "avg_processing_time_seconds": 14.2,
  "total_jobs_processed": 750,
  "generated_at": "2024-01-01T12:00:00Z"
}
```

### 2. Recent Requests

Get most recent pipeline requests.

**Endpoint:** `GET /monitor/recent?limit=50`

**Parameters:**
- `limit` (optional): Maximum number of requests (default: 50)

**Example:**
```bash
curl http://localhost:8000/monitor/recent?limit=100
```

**Response:**
```json
{
  "requests": [
    {
      "id": 150,
      "timestamp": "2024-01-01T12:00:00Z",
      "project_id": 123,
      "pipeline_id": 789,
      "pipeline_type": "main",
      "status": "completed",
      "processing_time": 12.5,
      "job_count": 5,
      "success_count": 5,
      "error_count": 0
    },
    ...
  ],
  "count": 100
}
```

### 3. Pipeline Details

Get all requests for a specific pipeline.

**Endpoint:** `GET /monitor/pipeline/{pipeline_id}`

**Example:**
```bash
curl http://localhost:8000/monitor/pipeline/12345
```

**Response:**
```json
{
  "pipeline_id": 12345,
  "requests": [
    {
      "id": 42,
      "timestamp": "2024-01-01T12:00:00Z",
      "status": "completed",
      "processing_time": 15.3,
      "success_count": 8,
      "error_count": 0
    }
  ],
  "count": 1
}
```

### 4. Export to CSV

Download monitoring data as CSV file.

**Endpoint:** `GET /monitor/export/csv?hours=24`

**Parameters:**
- `hours` (optional): Only export last N hours (omit for all data)

**Example:**
```bash
# Download last 24 hours
curl -O http://localhost:8000/monitor/export/csv?hours=24

# Download all data
curl -O http://localhost:8000/monitor/export/csv
```

---

## Viewing Statistics

### Method 1: CLI Dashboard (Recommended)

```bash
# Quick summary
python monitor_dashboard.py

# Detailed recent requests
python monitor_dashboard.py --recent 50
```

### Method 2: API Calls

```bash
# Get summary
curl http://localhost:8000/monitor/summary | jq

# Get recent requests
curl http://localhost:8000/monitor/recent?limit=10 | jq

# Format nicely with jq
curl http://localhost:8000/monitor/summary | jq '
{
  total: .total_requests,
  success_rate: .success_rate,
  by_status: .by_status
}'
```

### Method 3: Interactive API Docs

Visit http://localhost:8000/docs and explore the monitoring endpoints interactively.

### Method 4: Direct Database Query

```bash
# Connect to database
sqlite3 logs/monitoring.db

# Run queries
SELECT COUNT(*) FROM requests;
SELECT status, COUNT(*) FROM requests GROUP BY status;
SELECT AVG(processing_time) FROM requests WHERE status='completed';
```

---

## Exporting Data

### CSV Export via CLI

```bash
# Export all data
python monitor_dashboard.py --export all_pipelines.csv

# Export last 24 hours
python monitor_dashboard.py --export today.csv --hours 24

# Export last week
python monitor_dashboard.py --export week.csv --hours 168
```

### CSV Export via API

```bash
# Download CSV file
curl -o pipelines.csv http://localhost:8000/monitor/export/csv?hours=24

# The file will be named with timestamp
# Example: pipeline_monitoring_20240101_120000.csv
```

### CSV Fields

The exported CSV contains all tracked fields:

```csv
id,timestamp,project_id,pipeline_id,pipeline_type,status,ref,sha,source,event_type,client_ip,processing_time,job_count,success_count,error_count,error_message,metadata
1,2024-01-01T12:00:00Z,123,789,main,completed,main,abc123,push,Pipeline Hook,192.168.1.100,12.5,5,5,0,,{...}
```

### Analyze in Excel/Google Sheets

1. Export CSV: `python monitor_dashboard.py --export data.csv`
2. Open in Excel/Google Sheets
3. Create pivot tables, charts, and analysis

---

## Database Location

### Default Location

```
logs/monitoring.db
```

### Custom Location

Set via environment variable or during initialization.

### Database Schema

```sql
CREATE TABLE requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    project_id INTEGER,
    pipeline_id INTEGER,
    pipeline_type TEXT,
    status TEXT NOT NULL,
    ref TEXT,
    sha TEXT,
    source TEXT,
    event_type TEXT,
    client_ip TEXT,
    processing_time REAL,
    job_count INTEGER,
    success_count INTEGER,
    error_count INTEGER,
    error_message TEXT,
    metadata TEXT
);
```

---

## Querying the Database

### Using SQLite Command Line

```bash
# Open database
sqlite3 logs/monitoring.db

# Common queries
.mode column
.headers on

-- Total requests
SELECT COUNT(*) as total_requests FROM requests;

-- Requests by status
SELECT status, COUNT(*) as count
FROM requests
GROUP BY status
ORDER BY count DESC;

-- Average processing time
SELECT AVG(processing_time) as avg_time
FROM requests
WHERE status = 'completed';

-- Failed pipelines
SELECT pipeline_id, error_message, timestamp
FROM requests
WHERE status = 'failed'
ORDER BY timestamp DESC
LIMIT 10;

-- Success rate per day
SELECT
    DATE(timestamp) as date,
    COUNT(*) as total,
    SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) as completed,
    ROUND(100.0 * SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) / COUNT(*), 2) as success_rate
FROM requests
WHERE status IN ('completed', 'failed')
GROUP BY DATE(timestamp)
ORDER BY date DESC;
```

### Using Python

```python
from src.monitoring import PipelineMonitor

monitor = PipelineMonitor()

# Get summary
summary = monitor.get_summary(hours=24)
print(summary)

# Get recent requests
recent = monitor.get_recent_requests(limit=10)
for req in recent:
    print(f"Pipeline {req['pipeline_id']}: {req['status']}")

# Get specific pipeline
pipeline_requests = monitor.get_pipeline_requests(12345)
print(f"Found {len(pipeline_requests)} requests for pipeline 12345")

monitor.close()
```

---

## Examples

### Example 1: Check Today's Activity

```bash
# View dashboard
python monitor_dashboard.py --hours 24

# Export to CSV
python monitor_dashboard.py --export today.csv --hours 24

# Check via API
curl http://localhost:8000/monitor/summary?hours=24 | jq
```

### Example 2: Troubleshoot Failed Pipeline

```bash
# Find pipeline in recent requests
python monitor_dashboard.py --recent 100 | grep failed

# Get details for specific pipeline
python monitor_dashboard.py --pipeline 12345

# Or via API
curl http://localhost:8000/monitor/pipeline/12345 | jq
```

### Example 3: Track Performance Over Time

```bash
# Export last week
python monitor_dashboard.py --export week.csv --hours 168

# Open in Excel and create charts for:
# - Requests per day
# - Success rate trend
# - Average processing time
# - Jobs processed per day
```

### Example 4: Monitor Active Processing

```bash
# Check current processing
sqlite3 logs/monitoring.db "
SELECT pipeline_id, status, timestamp
FROM requests
WHERE status = 'processing'
ORDER BY timestamp DESC;
"
```

### Example 5: Generate Weekly Report

```bash
# Get summary for last 7 days
curl http://localhost:8000/monitor/summary?hours=168 | jq '
{
  period: "Last 7 days",
  total_requests: .total_requests,
  success_rate: "\(.success_rate)%",
  total_jobs: .total_jobs_processed,
  avg_time: "\(.avg_processing_time_seconds)s",
  breakdown: .by_status
}' | tee weekly_report.json

# Export detailed data
python monitor_dashboard.py --export weekly_data.csv --hours 168
```

---

## Real-Time Monitoring

### Watch Mode (Linux/Mac)

```bash
# Refresh dashboard every 30 seconds
watch -n 30 python monitor_dashboard.py

# Monitor processing requests
watch -n 5 'curl -s http://localhost:8000/monitor/summary | jq .by_status'
```

### Tail Logs + Monitor

```bash
# Terminal 1: Watch logs
tail -f webhook_server.log | grep "pipeline"

# Terminal 2: Dashboard
python monitor_dashboard.py
```

---

## Cleanup Old Data

The monitoring database grows over time. Clean up old records:

```python
from src.monitoring import PipelineMonitor

monitor = PipelineMonitor()

# Remove records older than 30 days
deleted = monitor.cleanup_old_records(days=30)
print(f"Deleted {deleted} old records")

monitor.close()
```

Or via SQL:

```bash
sqlite3 logs/monitoring.db "
DELETE FROM requests
WHERE timestamp < datetime('now', '-30 days');
VACUUM;
"
```

---

## Integration with Monitoring Tools

### Prometheus/Grafana

Expose metrics endpoint (can be added):

```python
# Example: Add /metrics endpoint
@app.get('/metrics')
async def metrics():
    summary = monitor.get_summary(hours=1)
    return {
        "pipeline_requests_total": summary['total_requests'],
        "pipeline_success_rate": summary['success_rate'],
        "pipeline_processing_time_avg": summary['avg_processing_time_seconds']
    }
```

### Logs Integration

All monitoring events are also logged to `webhook_server.log`:

```
INFO - Tracked request #42: pipeline=789, status=queued
INFO - Updated request #42 to status: processing
INFO - Updated request #42 to status: completed
```

### Alerting

Monitor for failures:

```bash
# Check for high failure rate
python -c "
from src.monitoring import PipelineMonitor
m = PipelineMonitor()
s = m.get_summary(hours=1)
if s['success_rate'] < 90:
    print(f'ALERT: Success rate is {s[\"success_rate\"]}%')
m.close()
"
```

---

## FAQ

**Q: Where is monitoring data stored?**
A: In `logs/monitoring.db` (SQLite database)

**Q: Can I query the database while the server is running?**
A: Yes, SQLite supports concurrent reads.

**Q: How long is data kept?**
A: Forever, unless you manually clean it up. Run `monitor.cleanup_old_records(days=30)` periodically.

**Q: Can I export data for a specific project?**
A: Yes, via SQL:
```sql
SELECT * FROM requests WHERE project_id = 123;
```

**Q: Does monitoring affect performance?**
A: Minimal impact. Database writes are non-blocking and very fast.

**Q: Can I disable monitoring?**
A: Currently monitoring is always enabled. You can ignore the data if not needed.

**Q: How to backup monitoring data?**
A: Simply copy the `logs/monitoring.db` file.

---

## Troubleshooting

### Database Locked Error

If you get "database is locked" errors:
```bash
# Close any open connections
# Check for locks
lsof logs/monitoring.db

# Kill processes if needed
kill <PID>
```

### Dashboard Shows No Data

Check if database exists:
```bash
ls -la logs/monitoring.db

# If not, server hasn't processed any requests yet
# Make sure server is running and receiving webhooks
```

### Missing Requests

Verify server is logging:
```bash
tail -f webhook_server.log | grep "Tracked request"

# Should see entries like:
# INFO - Tracked request #42: pipeline=789, status=queued
```

---

## Summary

The monitoring system provides complete visibility into:

✅ **All webhook requests** - Every request is tracked
✅ **Processing status** - Real-time status updates
✅ **Performance metrics** - Processing times, success rates
✅ **Multiple access methods** - CLI, API, CSV, SQL
✅ **Historical analysis** - Query any time period
✅ **Export capabilities** - CSV export for external analysis

**Quick Start:**
```bash
# View dashboard
python monitor_dashboard.py

# Export today's data
python monitor_dashboard.py --export today.csv --hours 24
```

For more details, see the main [README.md](README.md) and [DEBUG.md](DEBUG.md).
