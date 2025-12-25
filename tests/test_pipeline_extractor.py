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

    def test_extract_pipeline_with_minimal_data(self):
        """Test extraction with minimal required data."""
        payload = {
            "object_kind": "pipeline",
            "object_attributes": {
                "id": 99999,
                "status": "pending"
            },
            "project": {
                "id": 888
            }
        }

        result = self.extractor.extract_pipeline_info(payload)

        self.assertEqual(result['pipeline_id'], 99999)
        self.assertEqual(result['project_id'], 888)
        self.assertEqual(result['status'], "pending")
        self.assertEqual(len(result['builds']), 0)

    def test_extract_pipeline_with_variables(self):
        """Test extraction of pipeline variables."""
        payload = {
            "object_kind": "pipeline",
            "object_attributes": {
                "id": 11111,
                "status": "success",
                "variables": [
                    {"key": "ENV", "value": "production"},
                    {"key": "VERSION", "value": "1.0.0"}
                ]
            },
            "project": {"id": 123}
        }

        result = self.extractor.extract_pipeline_info(payload)

        self.assertEqual(len(result['variables']), 2)
        self.assertEqual(result['variables'][0]['key'], "ENV")

    def test_extract_pipeline_with_commit_info(self):
        """Test extraction of commit information."""
        payload = {
            "object_kind": "pipeline",
            "object_attributes": {
                "id": 22222,
                "status": "success"
            },
            "project": {"id": 456},
            "commit": {
                "id": "abc123",
                "message": "Fix bug",
                "author": {
                    "name": "Jane Doe",
                    "email": "jane@example.com"
                }
            }
        }

        result = self.extractor.extract_pipeline_info(payload)

        self.assertEqual(result['commit']['id'], "abc123")
        self.assertEqual(result['commit']['message'], "Fix bug")
        self.assertEqual(result['commit']['author']['name'], "Jane Doe")

    def test_should_process_failed_pipeline(self):
        """Test that failed pipelines should be processed."""
        pipeline_info = {
            "pipeline_id": 456,
            "status": "failed"
        }

        self.assertTrue(self.extractor.should_process_pipeline(pipeline_info))

    def test_should_process_canceled_pipeline(self):
        """Test that canceled pipelines should be processed."""
        pipeline_info = {
            "pipeline_id": 789,
            "status": "canceled"
        }

        self.assertTrue(self.extractor.should_process_pipeline(pipeline_info))

    def test_should_not_process_pending_pipeline(self):
        """Test that pending pipelines should not be processed."""
        pipeline_info = {
            "pipeline_id": 111,
            "status": "pending"
        }

        self.assertFalse(self.extractor.should_process_pipeline(pipeline_info))

    def test_filter_jobs_all(self):
        """Test filtering to include all jobs."""
        pipeline_info = {
            "builds": [
                {"id": 1, "name": "build", "status": "success"},
                {"id": 2, "name": "test", "status": "failed"},
                {"id": 3, "name": "deploy", "status": "skipped"}
            ]
        }

        filtered = self.extractor.filter_jobs_to_fetch(
            pipeline_info,
            include_success=True,
            include_failed=True
        )

        self.assertEqual(len(filtered), 2)  # Skipped jobs are excluded

    def test_filter_jobs_empty_builds(self):
        """Test filtering with empty builds list."""
        pipeline_info = {"builds": []}

        filtered = self.extractor.filter_jobs_to_fetch(
            pipeline_info,
            include_success=True,
            include_failed=True
        )

        self.assertEqual(len(filtered), 0)

    def test_filter_jobs_no_matches(self):
        """Test filtering when no jobs match criteria."""
        pipeline_info = {
            "builds": [
                {"id": 1, "name": "build", "status": "success"},
                {"id": 2, "name": "test", "status": "success"}
            ]
        }

        filtered = self.extractor.filter_jobs_to_fetch(
            pipeline_info,
            include_success=False,
            include_failed=True
        )

        self.assertEqual(len(filtered), 0)

    def test_pipeline_summary_with_no_duration(self):
        """Test summary generation when duration is None."""
        pipeline_info = {
            "pipeline_id": 33333,
            "ref": "develop",
            "status": "running",
            "duration": None,
            "pipeline_type": "main",
            "builds": []
        }

        summary = self.extractor.get_pipeline_summary(pipeline_info)

        self.assertIn("Pipeline #33333", summary)
        self.assertIn("running", summary)

    def test_extract_scheduled_pipeline(self):
        """Test extraction of scheduled pipeline."""
        payload = {
            "object_kind": "pipeline",
            "object_attributes": {
                "id": 44444,
                "ref": "main",
                "sha": "xyz789",
                "status": "success",
                "source": "schedule"
            },
            "project": {
                "id": 789,
                "name": "scheduled-project"
            },
            "builds": []
        }

        result = self.extractor.extract_pipeline_info(payload)

        self.assertEqual(result['pipeline_id'], 44444)
        self.assertEqual(result['source'], "schedule")

    def test_extract_web_triggered_pipeline(self):
        """Test extraction of web-triggered pipeline."""
        payload = {
            "object_kind": "pipeline",
            "object_attributes": {
                "id": 55555,
                "ref": "main",
                "status": "success",
                "source": "web"
            },
            "project": {"id": 111},
            "builds": []
        }

        result = self.extractor.extract_pipeline_info(payload)

        self.assertEqual(result['source'], "web")

    def test_extract_pipeline_with_stages(self):
        """Test extraction of pipeline stages."""
        payload = {
            "object_kind": "pipeline",
            "object_attributes": {
                "id": 66666,
                "status": "success",
                "stages": ["build", "test", "deploy", "cleanup"]
            },
            "project": {"id": 222},
            "builds": []
        }

        result = self.extractor.extract_pipeline_info(payload)

        self.assertEqual(len(result['stages']), 4)
        self.assertIn("deploy", result['stages'])

    def test_extract_pipeline_with_pipeline_url(self):
        """Test extraction of pipeline URL."""
        payload = {
            "object_kind": "pipeline",
            "object_attributes": {
                "id": 77777,
                "status": "success",
                "url": "https://gitlab.example.com/group/project/-/pipelines/77777"
            },
            "project": {"id": 333},
            "builds": []
        }

        result = self.extractor.extract_pipeline_info(payload)

        self.assertEqual(result['pipeline_url'], "https://gitlab.example.com/group/project/-/pipelines/77777")


if __name__ == '__main__':
    unittest.main()
