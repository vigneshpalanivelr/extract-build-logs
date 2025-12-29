"""
Monitoring Module

This module provides comprehensive tracking and monitoring of pipeline webhook requests,
processing status, and statistics. It maintains a database of all requests and provides
export capabilities for analysis.

Data Flow:
    Webhook Request → track_request() → SQLite DB → Export/Query → Reports

Features:
    - Track all incoming webhook requests
    - Monitor pipeline processing status
    - Calculate success/failure rates
    - Export to CSV for analysis
    - Query historical data
    - Real-time statistics

Invoked by: webhook_listener
Invokes: None
"""

import csv
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from pathlib import Path
from enum import Enum
import json
import sqlite3

logger = logging.getLogger(__name__)


class RequestStatus(Enum):
    """Status of pipeline processing request."""
    RECEIVED = "received"           # Webhook received
    QUEUED = "queued"               # Queued for processing
    PROCESSING = "processing"       # Currently processing
    COMPLETED = "completed"         # Successfully completed
    FAILED = "failed"               # Failed with error
    SKIPPED = "skipped"             # Skipped (not ready)
    IGNORED = "ignored"             # Ignored (wrong event type)


class PipelineMonitor:
    """
    Monitor and track all pipeline webhook requests and processing.

    This class maintains a SQLite database of all webhook requests
    and provides methods for querying, exporting, and analyzing the data.

    Supports context manager protocol for proper resource cleanup:
        with PipelineMonitor() as monitor:
            monitor.track_request(...)

    Attributes:
        db_path (Path): Path to SQLite database file
        conn: Database connection (sqlite3)
    """

    def __init__(self, db_path: str = "./logs/monitoring.db"):
        """
        Initialize the pipeline monitor with SQLite database.

        Args:
            db_path (str): Path to SQLite database file (default: ./logs/monitoring.db)
        """
        self.db_path = Path(db_path)
        self.conn = None

        # Ensure directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._init_sqlite()
        logger.debug("4. SQLite database initialized with WAL mode: %s", self.db_path)

    def _init_sqlite(self):
        """
        Initialize SQLite database with required tables.

        Uses WAL mode and optimized PRAGMA settings to prevent database corruption
        when container stops abruptly.
        """
        try:
            # Connect with extended timeout and isolation level for better reliability
            self.conn = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,
                timeout=30.0,
                isolation_level=None  # Autocommit mode to prevent corruption on crash
            )
            self.conn.row_factory = sqlite3.Row

            # Configure SQLite for durability and concurrency
            self.conn.execute('PRAGMA journal_mode=WAL')  # Write-Ahead Logging for better concurrency
            self.conn.execute('PRAGMA synchronous=NORMAL')  # Balance between safety and speed
            self.conn.execute('PRAGMA wal_autocheckpoint=1000')  # Checkpoint every 1000 pages
            self.conn.execute('PRAGMA busy_timeout=30000')  # 30 second busy timeout

            # Create requests table (SQLite syntax)
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS requests (
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
                )
            """)

            # Create indexes for faster queries
            self.conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_pipeline_id
                ON requests(pipeline_id)
            """)

            self.conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_timestamp
                ON requests(timestamp)
            """)

            self.conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_status
                ON requests(status)
            """)

            self.conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_event_type
                ON requests(event_type)
            """)

        except sqlite3.Error as e:
            logger.error("Failed to initialize SQLite database: %s", e, exc_info=True)
            raise

    def _execute(self, query: str, params: tuple = None):
        """
        Execute a SQLite query with proper error handling.

        Args:
            query (str): SQL query with ? placeholders
            params (tuple): Query parameters

        Returns:
            cursor: Database cursor with results
        """
        try:
            return self.conn.execute(query, params or ())
        except sqlite3.Error as e:
            logger.error("SQLite query failed: %s - Query: %s", e, query, exc_info=True)
            raise

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - ensure connection is closed."""
        self.close()
        return False  # Don't suppress exceptions

    def track_request(
        self,
        pipeline_info: Optional[Dict[str, Any]] = None,
        status: RequestStatus = RequestStatus.RECEIVED,
        event_type: Optional[str] = None,
        client_ip: Optional[str] = None,
        error_message: Optional[str] = None
    ) -> int:
        """
        Track a webhook request.

        Args:
            pipeline_info (Optional[Dict]): Extracted pipeline information
            status (RequestStatus): Current status of the request
            event_type (Optional[str]): GitLab event type
            client_ip (Optional[str]): Client IP address
            error_message (Optional[str]): Error message if failed

        Returns:
            int: Request ID in database

        Example:
            monitor.track_request(
                pipeline_info=pipeline_info,
                status=RequestStatus.QUEUED,
                client_ip="192.168.1.100"
            )
        """
        timestamp = datetime.utcnow().isoformat()

        # Extract data from pipeline_info if available
        project_id = None
        pipeline_id = None
        pipeline_type = None
        ref = None
        sha = None
        source = None
        job_count = None

        if pipeline_info:
            project_id = pipeline_info.get('project_id')
            pipeline_id = pipeline_info.get('pipeline_id')
            pipeline_type = pipeline_info.get('pipeline_type')
            ref = pipeline_info.get('ref')
            sha = pipeline_info.get('sha')
            source = pipeline_info.get('source')
            job_count = len(pipeline_info.get('builds', []))

        # Prepare metadata
        metadata = json.dumps(pipeline_info) if pipeline_info else None

        cursor = self._execute("""
            INSERT INTO requests (
                timestamp, project_id, pipeline_id, pipeline_type,
                status, ref, sha, source, event_type, client_ip,
                job_count, error_message, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            timestamp, project_id, pipeline_id, pipeline_type,
            status.value, ref, sha, source, event_type, client_ip,
            job_count, error_message, metadata
        ))

        # Get inserted ID from SQLite
        request_id = cursor.lastrowid  # pylint: disable=redefined-outer-name

        logger.info(
            "Tracked request #%s: pipeline=%s, status=%s",
            request_id, pipeline_id, status.value
        )

        return request_id

    def update_request(  # pylint: disable=redefined-outer-name
        self,
        request_id: int,
        status: RequestStatus,
        processing_time: Optional[float] = None,
        success_count: Optional[int] = None,
        error_count: Optional[int] = None,
        error_message: Optional[str] = None
    ):
        """
        Update an existing request with processing results.

        Args:
            request_id (int): Request ID to update
            status (RequestStatus): New status
            processing_time (Optional[float]): Processing time in seconds
            success_count (Optional[int]): Number of successfully processed jobs
            error_count (Optional[int]): Number of failed jobs
            error_message (Optional[str]): Error message if failed
        """
        self._execute("""
            UPDATE requests
            SET status = ?, processing_time = ?, success_count = ?,
                error_count = ?, error_message = ?
            WHERE id = ?
        """, (
            status.value, processing_time, success_count,
            error_count, error_message, request_id
        ))

        logger.debug("Updated request #%s to status: %s", request_id, status.value)

    def get_summary(self, hours: int = 24) -> Dict[str, Any]:
        """
        Get summary statistics for the specified time period.

        Args:
            hours (int): Number of hours to include (default: 24)

        Returns:
            Dict[str, Any]: Summary statistics

        Example Result:
            {
                "total_requests": 150,
                "by_status": {
                    "completed": 120,
                    "failed": 10,
                    "skipped": 15,
                    "processing": 5
                },
                "by_type": {
                    "main": 100,
                    "child": 30,
                    "merge_request": 20
                },
                "success_rate": 92.3,
                "avg_processing_time": 12.5,
                "total_jobs_processed": 450
            }
        """
        cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()

        # Total requests
        total = self.conn.execute("""
            SELECT COUNT(*) as count FROM requests
            WHERE timestamp > ?
        """, (cutoff,)).fetchone()['count']

        # By status
        by_status = {}
        status_rows = self.conn.execute("""
            SELECT status, COUNT(*) as count
            FROM requests
            WHERE timestamp > ?
            GROUP BY status
        """, (cutoff,)).fetchall()
        for row in status_rows:
            by_status[row['status']] = row['count']

        # By pipeline type
        by_type = {}
        type_rows = self.conn.execute("""
            SELECT pipeline_type, COUNT(*) as count
            FROM requests
            WHERE timestamp > ? AND pipeline_type IS NOT NULL
            GROUP BY pipeline_type
        """, (cutoff,)).fetchall()
        for row in type_rows:
            by_type[row['pipeline_type']] = row['count']

        # Success rate
        completed = by_status.get('completed', 0)
        failed = by_status.get('failed', 0)
        total_processed = completed + failed
        success_rate = (completed / total_processed * 100) if total_processed > 0 else 0

        # Average processing time
        avg_time = self.conn.execute("""
            SELECT AVG(processing_time) as avg_time
            FROM requests
            WHERE timestamp > ? AND processing_time IS NOT NULL
        """, (cutoff,)).fetchone()['avg_time'] or 0

        # Total jobs processed
        total_jobs = self.conn.execute("""
            SELECT SUM(success_count + IFNULL(error_count, 0)) as total
            FROM requests
            WHERE timestamp > ?
        """, (cutoff,)).fetchone()['total'] or 0

        return {
            "time_period_hours": hours,
            "total_requests": total,
            "by_status": by_status,
            "by_type": by_type,
            "success_rate": round(success_rate, 2),
            "avg_processing_time_seconds": round(avg_time, 2),
            "total_jobs_processed": total_jobs,
            "generated_at": datetime.utcnow().isoformat()
        }

    def get_recent_requests(self, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Get most recent requests.

        Args:
            limit (int): Maximum number of requests to return (default: 50)

        Returns:
            List[Dict]: List of recent requests
        """
        rows = self.conn.execute("""
            SELECT * FROM requests
            ORDER BY timestamp DESC
            LIMIT ?
        """, (limit,)).fetchall()

        return [dict(row) for row in rows]

    def get_pipeline_requests(self, pipeline_id: int) -> List[Dict[str, Any]]:
        """
        Get all requests for a specific pipeline.

        Args:
            pipeline_id (int): Pipeline ID

        Returns:
            List[Dict]: List of requests for the pipeline
        """
        rows = self.conn.execute("""
            SELECT * FROM requests
            WHERE pipeline_id = ?
            ORDER BY timestamp DESC
        """, (pipeline_id,)).fetchall()

        return [dict(row) for row in rows]

    def export_to_csv(self, filepath: str, hours: Optional[int] = None):
        """
        Export requests to CSV file.

        Args:
            filepath (str): Output CSV file path
            hours (Optional[int]): Only export requests from last N hours (None = all)

        Example:
            monitor.export_to_csv("pipeline_requests.csv", hours=24)
        """
        if hours:
            cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
            rows = self.conn.execute("""
                SELECT * FROM requests
                WHERE timestamp > ?
                ORDER BY timestamp DESC
            """, (cutoff,)).fetchall()
        else:
            rows = self.conn.execute("""
                SELECT * FROM requests
                ORDER BY timestamp DESC
            """).fetchall()

        if not rows:
            logger.warning("No data to export")
            return

        # Write to CSV
        with open(filepath, 'w', newline='', encoding='utf-8') as csvfile:
            # Get column names from first row
            fieldnames = rows[0].keys()
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

            writer.writeheader()
            for row in rows:
                writer.writerow(dict(row))

        logger.info("Exported %s requests to %s", len(rows), filepath)

    def get_status_timeline(self, hours: int = 24, _interval_minutes: int = 60) -> List[Dict[str, Any]]:
        """
        Get timeline of request statuses over time.

        Args:
            hours (int): Number of hours to include
            interval_minutes (int): Interval for grouping (default: 60 minutes)

        Returns:
            List[Dict]: Timeline data points
        """
        cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()

        rows = self.conn.execute("""
            SELECT
                strftime('%Y-%m-%d %H:00:00', timestamp) as time_bucket,
                status,
                COUNT(*) as count
            FROM requests
            WHERE timestamp > ?
            GROUP BY time_bucket, status
            ORDER BY time_bucket
        """, (cutoff,)).fetchall()

        return [dict(row) for row in rows]

    def cleanup_old_records(self, days: int = 30):
        """
        Remove old records from database.

        Args:
            days (int): Remove records older than N days (default: 30)
        """
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()

        result = self.conn.execute("""
            DELETE FROM requests
            WHERE timestamp < ?
        """, (cutoff,))

        deleted = result.rowcount

        logger.info("Cleaned up %s records older than %s days", deleted, days)
        return deleted

    def close(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()
            logger.debug("Database connection closed")


if __name__ == "__main__":
    # Example usage
    logging.basicConfig(level=logging.INFO)

    monitor = PipelineMonitor()

    # Track a sample request
    request_id = monitor.track_request(
        pipeline_info={
            'pipeline_id': 12345,
            'project_id': 123,
            'pipeline_type': 'main',
            'status': 'success',
            'ref': 'main',
            'builds': [{'id': 1}, {'id': 2}]
        },
        status=RequestStatus.QUEUED,
        client_ip="192.168.1.100"
    )

    # Update request
    monitor.update_request(
        request_id=request_id,
        status=RequestStatus.COMPLETED,
        processing_time=12.5,
        success_count=2,
        error_count=0
    )

    # Get summary
    summary = monitor.get_summary(hours=24)
    print("\nSummary (last 24 hours):")
    print(json.dumps(summary, indent=2))

    # Export to CSV
    monitor.export_to_csv("requests.csv")
    print("\nExported to requests.csv")

    monitor.close()
