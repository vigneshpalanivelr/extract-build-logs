"""
Tests for Storage Manager Module
"""

import unittest
import tempfile
import shutil
import json
from pathlib import Path
from src.storage_manager import StorageManager


class TestStorageManager(unittest.TestCase):
    """Test cases for StorageManager class."""

    def setUp(self):
        """Set up test fixtures with temporary directory."""
        self.test_dir = tempfile.mkdtemp()
        self.manager = StorageManager(self.test_dir)

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_initialization(self):
        """Test storage manager initialization."""
        self.assertTrue(Path(self.test_dir).exists())

    def test_sanitize_filename(self):
        """Test filename sanitization."""
        test_cases = [
            ("build:production", "build_production"),
            ("test/unit", "test_unit"),
            ("deploy-staging", "deploy-staging"),
            ("build  test", "build_test")
        ]

        for input_name, expected in test_cases:
            result = self.manager._sanitize_filename(input_name)
            self.assertEqual(result, expected)

    def test_get_pipeline_directory(self):
        """Test pipeline directory creation."""
        pipeline_dir = self.manager.get_pipeline_directory(123, 789)

        self.assertTrue(pipeline_dir.exists())
        self.assertIn("project_123", str(pipeline_dir))
        self.assertIn("pipeline_789", str(pipeline_dir))

    def test_save_log(self):
        """Test saving a job log."""
        log_path = self.manager.save_log(
            project_id=123,
            pipeline_id=789,
            job_id=456,
            job_name="build",
            log_content="Test log content",
            job_details={"status": "success"}
        )

        self.assertTrue(log_path.exists())

        # Read and verify content
        with open(log_path, 'r') as f:
            content = f.read()
        self.assertEqual(content, "Test log content")

    def test_save_pipeline_metadata(self):
        """Test saving pipeline metadata."""
        self.manager.save_pipeline_metadata(
            project_id=123,
            pipeline_id=789,
            pipeline_data={
                "status": "success",
                "ref": "main",
                "duration": 120
            }
        )

        pipeline_dir = self.manager.get_pipeline_directory(123, 789)
        metadata_path = pipeline_dir / "metadata.json"

        self.assertTrue(metadata_path.exists())

        # Read and verify metadata
        with open(metadata_path, 'r') as f:
            metadata = json.load(f)

        self.assertEqual(metadata['status'], "success")
        self.assertEqual(metadata['ref'], "main")
        self.assertEqual(metadata['duration'], 120)
        self.assertIn('last_updated', metadata)

    def test_get_pipeline_metadata(self):
        """Test retrieving pipeline metadata."""
        # First save some metadata
        self.manager.save_pipeline_metadata(
            project_id=123,
            pipeline_id=789,
            pipeline_data={"status": "success"}
        )

        # Then retrieve it
        metadata = self.manager.get_pipeline_metadata(123, 789)

        self.assertIsNotNone(metadata)
        self.assertEqual(metadata['status'], "success")

    def test_get_nonexistent_metadata(self):
        """Test retrieving metadata that doesn't exist."""
        metadata = self.manager.get_pipeline_metadata(999, 999)
        self.assertIsNone(metadata)

    def test_list_stored_pipelines(self):
        """Test listing stored pipelines."""
        # Create some test pipelines
        self.manager.save_pipeline_metadata(123, 789, {"status": "success"})
        self.manager.save_pipeline_metadata(123, 790, {"status": "failed"})
        self.manager.save_pipeline_metadata(456, 791, {"status": "success"})

        # List all pipelines
        all_pipelines = self.manager.list_stored_pipelines()
        self.assertEqual(len(all_pipelines), 3)

        # List pipelines for specific project
        project_pipelines = self.manager.list_stored_pipelines(project_id=123)
        self.assertEqual(len(project_pipelines), 2)

    def test_storage_stats(self):
        """Test getting storage statistics."""
        # Create some test data
        self.manager.save_log(
            project_id=123,
            pipeline_id=789,
            job_id=456,
            job_name="build",
            log_content="A" * 1000,  # 1000 bytes
            job_details={"status": "success"}
        )

        stats = self.manager.get_storage_stats()

        self.assertEqual(stats['total_projects'], 1)
        self.assertEqual(stats['total_pipelines'], 1)
        self.assertEqual(stats['total_jobs'], 1)
        self.assertGreater(stats['total_size_bytes'], 0)

    def test_multiple_jobs_same_pipeline(self):
        """Test saving multiple jobs for the same pipeline."""
        # Save multiple jobs
        for i in range(3):
            self.manager.save_log(
                project_id=123,
                pipeline_id=789,
                job_id=100 + i,
                job_name=f"job_{i}",
                log_content=f"Log content {i}",
                job_details={"status": "success"}
            )

        # Verify all jobs are saved
        metadata = self.manager.get_pipeline_metadata(123, 789)
        self.assertEqual(len(metadata['jobs']), 3)


if __name__ == '__main__':
    unittest.main()
