"""
Tests for Pipeline Extractor Module
"""

import unittest
from src.pipeline_extractor import PipelineExtractor, PipelineType


class TestPipelineExtractor(unittest.TestCase):
    """Test cases for PipelineExtractor class."""

    def setUp(self):
        """Set up test fixtures."""
        self.extractor = PipelineExtractor()

    def test_extract_main_pipeline(self):
        """Test extraction of main pipeline information."""
        payload = {
            "object_kind": "pipeline",
            "object_attributes": {
                "id": 12345,
                "ref": "main",
                "sha": "abc123",
                "status": "success",
                "source": "push",
                "duration": 225,
                "created_at": "2023-01-01T00:00:00Z",
                "finished_at": "2023-01-01T00:03:45Z",
                "stages": ["build", "test", "deploy"]
            },
            "project": {
                "id": 123,
                "name": "test-project",
                "path_with_namespace": "group/test-project"
            },
            "user": {
                "name": "John Doe",
                "username": "jdoe"
            },
            "builds": [
                {"id": 1, "name": "build", "stage": "build", "status": "success"},
                {"id": 2, "name": "test", "stage": "test", "status": "success"}
            ]
        }

        result = self.extractor.extract_pipeline_info(payload)

        self.assertEqual(result['pipeline_id'], 12345)
        self.assertEqual(result['project_id'], 123)
        self.assertEqual(result['pipeline_type'], PipelineType.MAIN.value)
        self.assertEqual(result['status'], "success")
        self.assertEqual(result['ref'], "main")
        self.assertEqual(len(result['builds']), 2)

    def test_extract_child_pipeline(self):
        """Test extraction of child pipeline information."""
        payload = {
            "object_kind": "pipeline",
            "object_attributes": {
                "id": 67890,
                "ref": "main",
                "sha": "def456",
                "status": "failed",
                "source": "parent_pipeline",
                "duration": 120
            },
            "project": {
                "id": 123,
                "name": "test-project"
            },
            "builds": []
        }

        result = self.extractor.extract_pipeline_info(payload)

        self.assertEqual(result['pipeline_type'], PipelineType.CHILD.value)
        self.assertEqual(result['status'], "failed")

    def test_extract_merge_request_pipeline(self):
        """Test extraction of merge request pipeline."""
        payload = {
            "object_kind": "pipeline",
            "object_attributes": {
                "id": 11111,
                "ref": "feature-branch",
                "sha": "ghi789",
                "status": "running",
                "source": "merge_request_event"
            },
            "project": {
                "id": 456,
                "name": "another-project"
            },
            "merge_request": {
                "id": 42,
                "title": "Add new feature"
            },
            "builds": []
        }

        result = self.extractor.extract_pipeline_info(payload)

        self.assertEqual(result['pipeline_type'], PipelineType.MERGE_REQUEST.value)

    def test_should_process_completed_pipeline(self):
        """Test that completed pipelines should be processed."""
        pipeline_info = {
            "pipeline_id": 123,
            "status": "success"
        }

        self.assertTrue(self.extractor.should_process_pipeline(pipeline_info))

    def test_should_not_process_running_pipeline(self):
        """Test that running pipelines should not be processed."""
        pipeline_info = {
            "pipeline_id": 123,
            "status": "running"
        }

        self.assertFalse(self.extractor.should_process_pipeline(pipeline_info))

    def test_filter_jobs_success_only(self):
        """Test filtering to include only successful jobs."""
        pipeline_info = {
            "builds": [
                {"id": 1, "name": "build", "status": "success"},
                {"id": 2, "name": "test", "status": "failed"},
                {"id": 3, "name": "deploy", "status": "success"}
            ]
        }

        filtered = self.extractor.filter_jobs_to_fetch(
            pipeline_info,
            include_success=True,
            include_failed=False
        )

        self.assertEqual(len(filtered), 2)
        self.assertEqual(filtered[0]['id'], 1)
        self.assertEqual(filtered[1]['id'], 3)

    def test_filter_jobs_failed_only(self):
        """Test filtering to include only failed jobs."""
        pipeline_info = {
            "builds": [
                {"id": 1, "name": "build", "status": "success"},
                {"id": 2, "name": "test", "status": "failed"},
                {"id": 3, "name": "deploy", "status": "success"}
            ]
        }

        filtered = self.extractor.filter_jobs_to_fetch(
            pipeline_info,
            include_success=False,
            include_failed=True
        )

        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]['id'], 2)

    def test_get_pipeline_summary(self):
        """Test pipeline summary generation."""
        pipeline_info = {
            "pipeline_id": 12345,
            "ref": "main",
            "status": "success",
            "duration": 225,
            "pipeline_type": "main",
            "builds": [
                {"id": 1, "status": "success"},
                {"id": 2, "status": "success"},
                {"id": 3, "status": "failed"}
            ]
        }

        summary = self.extractor.get_pipeline_summary(pipeline_info)

        self.assertIn("Pipeline #12345", summary)
        self.assertIn("main", summary)
        self.assertIn("success", summary)
        self.assertIn("3m 45s", summary)


if __name__ == '__main__':
    unittest.main()
