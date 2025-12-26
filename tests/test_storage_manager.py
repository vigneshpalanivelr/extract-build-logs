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

    def test_save_log_with_empty_content(self):
        """Test saving a log with empty content."""
        log_path = self.manager.save_log(
            project_id=123,
            pipeline_id=789,
            job_id=456,
            job_name="empty_job",
            log_content="",
            job_details={"status": "success"}
        )

        self.assertTrue(log_path.exists())
        with open(log_path, 'r') as f:
            content = f.read()
        self.assertEqual(content, "")

    def test_save_log_with_special_characters(self):
        """Test saving a log with special characters in job name."""
        log_path = self.manager.save_log(
            project_id=123,
            pipeline_id=789,
            job_id=456,
            job_name="build:production/test",
            log_content="Test content",
            job_details={"status": "success"}
        )

        self.assertTrue(log_path.exists())
        # Verify filename is sanitized
        self.assertIn("build_production_test", str(log_path))

    def test_save_log_with_unicode_content(self):
        """Test saving a log with Unicode characters."""
        unicode_content = "Test log with Unicode: 你好 🚀 Ñoño"
        log_path = self.manager.save_log(
            project_id=123,
            pipeline_id=789,
            job_id=456,
            job_name="unicode_test",
            log_content=unicode_content,
            job_details={"status": "success"}
        )

        self.assertTrue(log_path.exists())
        with open(log_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertEqual(content, unicode_content)

    def test_get_pipeline_directory_with_project_name(self):
        """Test pipeline directory creation with project name."""
        pipeline_dir = self.manager.get_pipeline_directory(
            project_id=123,
            pipeline_id=789,
            project_name="my-awesome-project"
        )

        self.assertTrue(pipeline_dir.exists())
        self.assertIn("my-awesome-project", str(pipeline_dir))

    def test_sanitize_filename_edge_cases(self):
        """Test filename sanitization with edge cases."""
        test_cases = [
            ("", ""),  # Empty string returns empty
            ("   ", ""),  # Only spaces returns empty
            ("valid-name", "valid-name"),
            ("UPPERCASE", "UPPERCASE"),
            ("under_score", "under_score"),
            ("dots.dots.dots", "dots.dots.dots"),
            ("multiple   spaces", "multiple_spaces"),
            ("slash/backslash\\", "slash_backslash")  # Trailing underscore is stripped
        ]

        for input_name, expected in test_cases:
            result = self.manager._sanitize_filename(input_name)
            self.assertEqual(result, expected, f"Failed for input: {input_name}")

    def test_save_pipeline_metadata_updates_existing(self):
        """Test that saving metadata updates existing metadata."""
        # Save initial metadata
        self.manager.save_pipeline_metadata(
            project_id=123,
            pipeline_id=789,
            pipeline_data={"status": "running", "ref": "main"}
        )

        # Update metadata
        self.manager.save_pipeline_metadata(
            project_id=123,
            pipeline_id=789,
            pipeline_data={"status": "success", "ref": "main", "duration": 100}
        )

        # Verify updated metadata
        metadata = self.manager.get_pipeline_metadata(123, 789)
        self.assertEqual(metadata['status'], "success")
        self.assertEqual(metadata['duration'], 100)

    def test_list_stored_pipelines_empty(self):
        """Test listing pipelines when none exist."""
        pipelines = self.manager.list_stored_pipelines()
        self.assertEqual(len(pipelines), 0)

    def test_list_stored_pipelines_specific_project_not_found(self):
        """Test listing pipelines for non-existent project."""
        self.manager.save_pipeline_metadata(123, 789, {"status": "success"})

        pipelines = self.manager.list_stored_pipelines(project_id=999)
        self.assertEqual(len(pipelines), 0)

    def test_get_storage_stats_empty(self):
        """Test getting storage stats when no data exists."""
        stats = self.manager.get_storage_stats()

        self.assertEqual(stats['total_projects'], 0)
        self.assertEqual(stats['total_pipelines'], 0)
        self.assertEqual(stats['total_jobs'], 0)
        self.assertEqual(stats['total_size_bytes'], 0)

    def test_save_log_creates_nested_directories(self):
        """Test that save_log creates all necessary directories."""
        # Use fresh manager with non-existent base directory
        new_base = Path(self.test_dir) / "nested" / "deep" / "logs"
        manager = StorageManager(str(new_base))

        log_path = manager.save_log(
            project_id=123,
            pipeline_id=789,
            job_id=456,
            job_name="test",
            log_content="content",
            job_details={"status": "success"}
        )

        self.assertTrue(log_path.exists())
        self.assertTrue(log_path.parent.exists())

    def test_update_job_metadata(self):
        """Test updating job metadata after saving log."""
        # Save initial log
        self.manager.save_log(
            project_id=123,
            pipeline_id=789,
            job_id=456,
            job_name="build",
            log_content="Initial content",
            job_details={"status": "running", "stage": "build"}
        )

        # Save again with updated details (simulating job completion)
        self.manager.save_log(
            project_id=123,
            pipeline_id=789,
            job_id=456,
            job_name="build",
            log_content="Updated content",
            job_details={"status": "success", "stage": "build", "duration": 120}
        )

        # Verify metadata is updated
        metadata = self.manager.get_pipeline_metadata(123, 789)
        # Jobs are stored as dict with job_id as string key
        job_meta = metadata['jobs']['456']
        self.assertEqual(job_meta['status'], "success")
        self.assertEqual(job_meta['duration'], 120)

    def test_storage_stats_multiple_projects(self):
        """Test storage stats with multiple projects and pipelines."""
        # Create data for multiple projects
        for project_id in [100, 200, 300]:
            for pipeline_id in [1, 2]:
                self.manager.save_log(
                    project_id=project_id,
                    pipeline_id=pipeline_id,
                    job_id=1,
                    job_name="test",
                    log_content="x" * 100,
                    job_details={"status": "success"}
                )

        stats = self.manager.get_storage_stats()

        self.assertEqual(stats['total_projects'], 3)
        self.assertEqual(stats['total_pipelines'], 6)
        self.assertEqual(stats['total_jobs'], 6)
        self.assertGreater(stats['total_size_bytes'], 0)

    def test_list_stored_pipelines_contains_correct_data(self):
        """Test that listed pipelines contain correct project and pipeline IDs."""
        self.manager.save_pipeline_metadata(123, 789, {"status": "success"})
        self.manager.save_pipeline_metadata(456, 999, {"status": "failed"})

        pipelines = self.manager.list_stored_pipelines()

        self.assertEqual(len(pipelines), 2)
        # Verify pipelines have correct structure
        for pipeline in pipelines:
            self.assertIn('project_id', pipeline)
            self.assertIn('pipeline_id', pipeline)

    def test_save_log_with_large_content(self):
        """Test saving a log with large content."""
        large_content = "A" * 1000000  # 1MB of data
        log_path = self.manager.save_log(
            project_id=123,
            pipeline_id=789,
            job_id=456,
            job_name="large_job",
            log_content=large_content,
            job_details={"status": "success"}
        )

        self.assertTrue(log_path.exists())
        # Verify file size
        self.assertGreater(log_path.stat().st_size, 900000)

    @patch('builtins.open', side_effect=IOError("Permission denied"))
    def test_save_log_io_error(self, mock_open):
        """Test save_log handles IOError correctly."""
        with self.assertRaises(IOError):
            self.manager.save_log(
                project_id=123,
                pipeline_id=789,
                job_id=456,
                job_name="test",
                log_content="test log",
                job_details={"status": "success"}
            )

    @patch('builtins.open', side_effect=IOError("Disk full"))
    def test_save_pipeline_metadata_io_error(self, mock_open):
        """Test save_pipeline_metadata handles IOError correctly."""
        with self.assertRaises(IOError):
            self.manager.save_pipeline_metadata(
                project_id=123,
                pipeline_id=789,
                pipeline_data={"status": "success"}
            )

    def test_get_pipeline_metadata_file_not_exists(self):
        """Test get_pipeline_metadata when file doesn't exist."""
        result = self.manager.get_pipeline_metadata(999, 999)
        self.assertIsNone(result)

    def test_get_pipeline_metadata_json_decode_error(self):
        """Test get_pipeline_metadata handles invalid JSON."""
        # Create metadata file with invalid JSON
        pipeline_dir = self.manager.get_pipeline_directory(123, 789)
        pipeline_dir.mkdir(parents=True, exist_ok=True)
        metadata_path = pipeline_dir / "metadata.json"

        # Write invalid JSON
        with open(metadata_path, 'w') as f:
            f.write("{invalid json content")

        result = self.manager.get_pipeline_metadata(123, 789)
        self.assertIsNone(result)

    @patch('pathlib.Path.mkdir', side_effect=OSError("Permission denied"))
    def test_get_pipeline_directory_os_error(self, mock_mkdir):
        """Test directory creation handles OSError."""
        with self.assertRaises(OSError):
            self.manager.get_pipeline_directory(123, 789)


if __name__ == '__main__':
    unittest.main()
