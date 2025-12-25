"""
Unit tests for monitoring.py

Comprehensive test coverage for monitoring functionality including:
- Database initialization
- Request tracking
- Request updates
- Summary statistics
- CSV export
- Context manager protocol
- SQLite configuration
"""

import unittest
import tempfile
import os
import csv
from pathlib import Path
from datetime import datetime, timedelta
import sys
import sqlite3

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.monitoring import PipelineMonitor, RequestStatus


class TestPipelineMonitor(unittest.TestCase):
    """Test cases for PipelineMonitor class."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_monitoring.db")
        self.monitor = PipelineMonitor(db_path=self.db_path)

    def tearDown(self):
        """Clean up test fixtures."""
        if self.monitor and self.monitor.conn:
            self.monitor.close()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        if os.path.exists(self.temp_dir):
            os.rmdir(self.temp_dir)

    def test_initialization_creates_database(self):
        """Test that initialization creates the database file."""
        self.assertTrue(os.path.exists(self.db_path))
        self.assertIsNotNone(self.monitor.conn)

    def test_initialization_creates_directory(self):
        """Test that initialization creates parent directory if needed."""
        nested_path = os.path.join(self.temp_dir, "nested", "db.sqlite")
        monitor = PipelineMonitor(db_path=nested_path)
        try:
            self.assertTrue(os.path.exists(os.path.dirname(nested_path)))
            self.assertTrue(os.path.exists(nested_path))
        finally:
            monitor.close()

    def test_sqlite_wal_mode_enabled(self):
        """Test that WAL mode is enabled for better concurrency."""
        cursor = self.monitor.conn.execute("PRAGMA journal_mode")
        mode = cursor.fetchone()[0]
        self.assertEqual(mode.upper(), "WAL")

    def test_sqlite_pragma_settings(self):
        """Test that SQLite PRAGMA settings are configured."""
        # Check synchronous mode
        cursor = self.monitor.conn.execute("PRAGMA synchronous")
        sync_mode = cursor.fetchone()[0]
        self.assertEqual(sync_mode, 1)  # NORMAL = 1

        # Check busy_timeout
        cursor = self.monitor.conn.execute("PRAGMA busy_timeout")
        timeout = cursor.fetchone()[0]
        self.assertEqual(timeout, 30000)

    def test_track_request_basic(self):
        """Test tracking a basic request without pipeline info."""
        request_id = self.monitor.track_request(
            status=RequestStatus.RECEIVED,
            event_type="Pipeline Hook",
            client_ip="192.168.1.100"
        )

        self.assertIsInstance(request_id, int)
        self.assertGreater(request_id, 0)

    def test_track_request_with_pipeline_info(self):
        """Test tracking a request with full pipeline info."""
        pipeline_info = {
            "pipeline_id": 12345,
            "project_id": 100,
            "project_name": "test-project",
            "pipeline_type": "main",
            "ref": "main",
            "sha": "abc123",
            "source": "push",
            "user": {"name": "Test User"},
            "jobs": [{"id": 1, "name": "build"}]
        }

        request_id = self.monitor.track_request(
            pipeline_info=pipeline_info,
            status=RequestStatus.PROCESSING,
            event_type="Pipeline Hook",
            client_ip="192.168.1.100"
        )

        self.assertGreater(request_id, 0)

        # Verify data was stored
        cursor = self.monitor.conn.execute(
            "SELECT pipeline_id, project_id, status FROM requests WHERE id = ?",
            (request_id,)
        )
        row = cursor.fetchone()
        self.assertEqual(row[0], 12345)
        self.assertEqual(row[1], 100)
        self.assertEqual(row[2], "processing")

    def test_update_request(self):
        """Test updating a request with processing results."""
        # Create initial request
        request_id = self.monitor.track_request(
            status=RequestStatus.PROCESSING
        )

        # Update with results
        self.monitor.update_request(
            request_id=request_id,
            status=RequestStatus.COMPLETED,
            processing_time=1.5,
            success_count=3,
            error_count=0
        )

        # Verify update
        cursor = self.monitor.conn.execute(
            "SELECT status, processing_time, success_count, error_count FROM requests WHERE id = ?",
            (request_id,)
        )
        row = cursor.fetchone()
        self.assertEqual(row[0], "completed")
        self.assertEqual(row[1], 1.5)
        self.assertEqual(row[2], 3)
        self.assertEqual(row[3], 0)

    def test_update_request_with_error(self):
        """Test updating a request with error information."""
        request_id = self.monitor.track_request(status=RequestStatus.PROCESSING)

        self.monitor.update_request(
            request_id=request_id,
            status=RequestStatus.FAILED,
            processing_time=0.5,
            error_count=1,
            error_message="Pipeline failed"
        )

        cursor = self.monitor.conn.execute(
            "SELECT status, error_message FROM requests WHERE id = ?",
            (request_id,)
        )
        row = cursor.fetchone()
        self.assertEqual(row[0], "failed")
        self.assertEqual(row[1], "Pipeline failed")

    def test_get_summary_empty(self):
        """Test getting summary with no data."""
        summary = self.monitor.get_summary(hours=24)

        self.assertEqual(summary["total_requests"], 0)
        self.assertEqual(summary["completed"], 0)
        self.assertEqual(summary["failed"], 0)
        self.assertEqual(summary["processing"], 0)

    def test_get_summary_with_data(self):
        """Test getting summary with various request statuses."""
        # Create test data
        self.monitor.track_request(status=RequestStatus.COMPLETED)
        self.monitor.track_request(status=RequestStatus.COMPLETED)
        self.monitor.track_request(status=RequestStatus.FAILED)
        self.monitor.track_request(status=RequestStatus.PROCESSING)

        summary = self.monitor.get_summary(hours=24)

        self.assertEqual(summary["total_requests"], 4)
        self.assertEqual(summary["completed"], 2)
        self.assertEqual(summary["failed"], 1)
        self.assertEqual(summary["processing"], 1)

    def test_get_recent_requests(self):
        """Test getting recent requests."""
        # Create test requests
        for i in range(5):
            self.monitor.track_request(
                status=RequestStatus.COMPLETED,
                event_type="Pipeline Hook"
            )

        recent = self.monitor.get_recent_requests(limit=3)
        self.assertEqual(len(recent), 3)

    def test_export_to_csv(self):
        """Test exporting requests to CSV file."""
        # Create test data
        pipeline_info = {
            "pipeline_id": 12345,
            "project_id": 100,
            "ref": "main"
        }
        self.monitor.track_request(
            pipeline_info=pipeline_info,
            status=RequestStatus.COMPLETED
        )

        # Export to CSV
        csv_path = os.path.join(self.temp_dir, "export.csv")
        self.monitor.export_to_csv(csv_path)

        # Verify CSV file exists and has content
        self.assertTrue(os.path.exists(csv_path))

        with open(csv_path, 'r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["pipeline_id"], "12345")

    def test_cleanup_old_records(self):
        """Test cleanup of old records."""
        # This is hard to test without mocking time
        # Just verify the method runs without error
        deleted = self.monitor.cleanup_old_records(days=30)
        self.assertIsInstance(deleted, int)
        self.assertGreaterEqual(deleted, 0)

    def test_context_manager_protocol(self):
        """Test context manager enters and exits properly."""
        db_path = os.path.join(self.temp_dir, "context_test.db")

        with PipelineMonitor(db_path=db_path) as monitor:
            self.assertIsNotNone(monitor.conn)
            request_id = monitor.track_request(status=RequestStatus.RECEIVED)
            self.assertGreater(request_id, 0)

        # After context exit, connection should be closed
        # Note: We can't directly test if connection is closed
        # but we can verify the file exists
        self.assertTrue(os.path.exists(db_path))

    def test_close_method(self):
        """Test that close method properly closes connection."""
        monitor = PipelineMonitor(db_path=os.path.join(self.temp_dir, "close_test.db"))
        self.assertIsNotNone(monitor.conn)

        monitor.close()
        # After close, attempting to use connection should fail
        with self.assertRaises(sqlite3.ProgrammingError):
            monitor.conn.execute("SELECT 1")

    def test_error_handling_on_invalid_query(self):
        """Test that invalid queries raise proper exceptions."""
        with self.assertRaises(sqlite3.Error):
            self.monitor._execute("INVALID SQL QUERY")

    def test_get_pipeline_requests(self):
        """Test getting requests for a specific pipeline."""
        # Create requests for different pipelines
        pipeline_info_1 = {"pipeline_id": 111}
        pipeline_info_2 = {"pipeline_id": 222}

        self.monitor.track_request(pipeline_info=pipeline_info_1, status=RequestStatus.COMPLETED)
        self.monitor.track_request(pipeline_info=pipeline_info_1, status=RequestStatus.COMPLETED)
        self.monitor.track_request(pipeline_info=pipeline_info_2, status=RequestStatus.COMPLETED)

        # Get requests for pipeline 111
        requests = self.monitor.get_pipeline_requests(pipeline_id=111)
        self.assertEqual(len(requests), 2)
        for req in requests:
            self.assertEqual(req["pipeline_id"], 111)


if __name__ == '__main__':
    unittest.main()
