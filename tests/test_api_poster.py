"""
Unit tests for api_poster.py

Comprehensive test coverage for API posting functionality including:
- Payload formatting
- Successful API requests
- Failed API requests (4xx, 5xx errors)
- Timeout handling
- Retry logic
- Authentication
- Request/response logging
- Edge cases
"""

import unittest
from unittest.mock import patch, MagicMock, mock_open, call
from pathlib import Path
import json
import sys
import tempfile
import requests

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.api_poster import ApiPoster
from src.config_loader import Config


class TestApiPoster(unittest.TestCase):
    """Test cases for ApiPoster class."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()

        self.config = Config(
            gitlab_url="https://gitlab.example.com",
            gitlab_token="test-token",
            webhook_port=8000,
            webhook_secret=None,
            log_output_dir=self.temp_dir,
            retry_attempts=3,
            retry_delay=1,
            log_level="INFO",
            log_save_pipeline_status=["all"],
            log_save_projects=[],
            log_exclude_projects=[],
            log_save_job_status=["all"],
            log_save_metadata_always=True,
            api_post_enabled=True,
            api_post_url="https://api.example.com/logs",
            api_post_timeout=30,
            api_post_retry_enabled=True,
            api_post_save_to_file=False,
            # Jenkins configuration
            jenkins_enabled=False,
            jenkins_url=None,
            jenkins_user=None,
            jenkins_api_token=None,
            jenkins_webhook_secret=None,
            # BFA JWT authentication
            bfa_host=None,
            bfa_secret_key="test-secret-key",
            # Email notifications
            email_notifications_enabled=False,
            smtp_host="localhost",
            smtp_port=25,
            smtp_from_email=None,
            devops_email=None
        )

        self.pipeline_info = {
            "pipeline_id": 12345,
            "project_id": 123,
            "project_name": "test-project",
            "status": "success",
            "ref": "main",
            "sha": "abc123def456",
            "source": "push",
            "pipeline_type": "main",
            "created_at": "2024-01-01T00:00:00Z",
            "finished_at": "2024-01-01T00:02:00Z",
            "duration": 120.5,
            "user": {"name": "Test User", "email": "test@example.com"},
            "stages": ["build", "test", "deploy"]
        }

        self.all_logs = {
            456: {
                "details": {
                    "name": "build:production",
                    "status": "success",
                    "stage": "build",
                    "created_at": "2024-01-01T00:00:00Z",
                    "started_at": "2024-01-01T00:00:05Z",
                    "finished_at": "2024-01-01T00:01:05Z",
                    "duration": 60.2,
                    "ref": "main"
                },
                "log": "Build started...\nBuild completed successfully."
            },
            457: {
                "details": {
                    "name": "test:unit",
                    "status": "success",
                    "stage": "test",
                    "created_at": "2024-01-01T00:01:10Z",
                    "started_at": "2024-01-01T00:01:15Z",
                    "finished_at": "2024-01-01T00:02:00Z",
                    "duration": 45.3,
                    "ref": "main"
                },
                "log": "Running tests...\nAll tests passed."
            }
        }

    def tearDown(self):
        """Clean up test fixtures."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_initialization(self):
        """Test ApiPoster initialization."""
        poster = ApiPoster(self.config)

        self.assertEqual(poster.config, self.config)
        self.assertEqual(poster.api_log_file.parent, Path(self.temp_dir))
        self.assertEqual(poster.api_log_file.name, "api-requests.log")

    def test_initialization_without_requests(self):
        """Test initialization fails without requests library."""
        with patch('src.api_poster.requests', None):
            with self.assertRaises(ImportError) as context:
                ApiPoster(self.config)
            self.assertIn("requests library is required", str(context.exception))

    def test_format_payload(self):
        """Test payload formatting."""
        poster = ApiPoster(self.config)
        payload = poster.format_payload(self.pipeline_info, self.all_logs)

        # Verify structure
        self.assertEqual(payload["pipeline_id"], 12345)
        self.assertEqual(payload["project_id"], 123)
        self.assertEqual(payload["project_name"], "test-project")
        self.assertEqual(payload["status"], "success")
        self.assertEqual(len(payload["jobs"]), 2)

        # Verify first job
        job1 = payload["jobs"][0]
        self.assertEqual(job1["job_id"], 456)
        self.assertEqual(job1["job_name"], "build:production")
        self.assertIn("Build started", job1["log_content"])

        # Verify second job
        job2 = payload["jobs"][1]
        self.assertEqual(job2["job_id"], 457)
        self.assertEqual(job2["job_name"], "test:unit")

    def test_format_payload_empty_jobs(self):
        """Test payload formatting with no jobs."""
        poster = ApiPoster(self.config)
        payload = poster.format_payload(self.pipeline_info, {})

        self.assertEqual(payload["pipeline_id"], 12345)
        self.assertEqual(len(payload["jobs"]), 0)

    @patch('src.api_poster.requests.post')
    def test_successful_post(self, mock_post):
        """Test successful API POST."""
        # Mock successful response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"success": true, "message": "Logs received"}'
        mock_post.return_value = mock_response

        poster = ApiPoster(self.config)
        result = poster.post_pipeline_logs(self.pipeline_info, self.all_logs)

        # Verify success
        self.assertTrue(result)

        # Verify request was made
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args.kwargs

        self.assertEqual(call_kwargs['headers']['Content-Type'], 'application/json')
        self.assertEqual(call_kwargs['headers']['Authorization'], 'Bearer test-api-token')
        self.assertEqual(call_kwargs['timeout'], 30)

    @patch('src.api_poster.requests.post')
    def test_post_without_auth_token(self, mock_post):
        """Test POST without authentication token."""
        # Config without auth token
        config_no_auth = self.config
        config_no_auth.api_post_auth_token = None

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"success": true}'
        mock_post.return_value = mock_response

        poster = ApiPoster(config_no_auth)
        result = poster.post_pipeline_logs(self.pipeline_info, self.all_logs)

        # Verify auth header not present
        call_kwargs = mock_post.call_args.kwargs
        self.assertNotIn('Authorization', call_kwargs['headers'])

    @patch('src.api_poster.requests.post')
    def test_post_with_400_error(self, mock_post):
        """Test API POST with 400 Bad Request error."""
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = '{"error": "Invalid payload"}'
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError("400 Bad Request")
        mock_post.return_value = mock_response

        # Disable retry for this test
        self.config.api_post_retry_enabled = False

        poster = ApiPoster(self.config)
        result = poster.post_pipeline_logs(self.pipeline_info, self.all_logs)

        # Verify failure
        self.assertFalse(result)

    @patch('src.api_poster.requests.post')
    def test_post_with_500_error(self, mock_post):
        """Test API POST with 500 Internal Server Error."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = '{"error": "Internal server error"}'
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError("500 Internal Server Error")
        mock_post.return_value = mock_response

        # Disable retry for this test
        self.config.api_post_retry_enabled = False

        poster = ApiPoster(self.config)
        result = poster.post_pipeline_logs(self.pipeline_info, self.all_logs)

        # Verify failure
        self.assertFalse(result)

    @patch('src.api_poster.requests.post')
    def test_post_with_503_error(self, mock_post):
        """Test API POST with 503 Service Unavailable."""
        mock_response = MagicMock()
        mock_response.status_code = 503
        mock_response.text = '{"error": "Service temporarily unavailable"}'
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError("503 Service Unavailable")
        mock_post.return_value = mock_response

        # Disable retry for this test
        self.config.api_post_retry_enabled = False

        poster = ApiPoster(self.config)
        result = poster.post_pipeline_logs(self.pipeline_info, self.all_logs)

        # Verify failure
        self.assertFalse(result)

    @patch('src.api_poster.requests.post')
    def test_post_timeout(self, mock_post):
        """Test API POST with timeout."""
        mock_post.side_effect = requests.exceptions.Timeout("Request timed out after 30 seconds")

        # Disable retry for this test
        self.config.api_post_retry_enabled = False

        poster = ApiPoster(self.config)
        result = poster.post_pipeline_logs(self.pipeline_info, self.all_logs)

        # Verify failure
        self.assertFalse(result)

    @patch('src.api_poster.requests.post')
    def test_post_connection_error(self, mock_post):
        """Test API POST with connection error."""
        mock_post.side_effect = requests.exceptions.ConnectionError("Failed to establish connection")

        # Disable retry for this test
        self.config.api_post_retry_enabled = False

        poster = ApiPoster(self.config)
        result = poster.post_pipeline_logs(self.pipeline_info, self.all_logs)

        # Verify failure
        self.assertFalse(result)

    @patch('src.api_poster.requests.post')
    @patch('src.api_poster.ErrorHandler')
    def test_post_with_retry_enabled(self, mock_error_handler_class, mock_post):
        """Test API POST with retry enabled."""
        # Mock successful response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"success": true}'

        # Mock ErrorHandler instance and its retry_with_backoff method
        mock_error_handler = MagicMock()
        mock_error_handler.retry_with_backoff.return_value = (200, '{"success": true}', 1000)
        mock_error_handler_class.return_value = mock_error_handler

        poster = ApiPoster(self.config)
        result = poster.post_pipeline_logs(self.pipeline_info, self.all_logs)

        # Verify ErrorHandler was instantiated
        mock_error_handler_class.assert_called_once()
        # Verify retry_with_backoff was used
        mock_error_handler.retry_with_backoff.assert_called_once()
        self.assertTrue(result)

    @patch('src.api_poster.requests.post')
    @patch('src.api_poster.ErrorHandler')
    def test_post_with_retry_exhausted(self, mock_error_handler_class, mock_post):
        """Test API POST when retries are exhausted."""
        from src.error_handler import RetryExhaustedError

        # Mock to always fail
        last_exception = requests.exceptions.HTTPError("500 Internal Server Error")
        mock_post.side_effect = last_exception

        # Mock ErrorHandler to raise RetryExhaustedError
        mock_error_handler = MagicMock()
        mock_error_handler.retry_with_backoff.side_effect = RetryExhaustedError(
            "Max retries exceeded",
            last_exception
        )
        mock_error_handler_class.return_value = mock_error_handler

        poster = ApiPoster(self.config)
        result = poster.post_pipeline_logs(self.pipeline_info, self.all_logs)

        # Verify failure
        self.assertFalse(result)

    @patch('src.api_poster.requests.post')
    def test_post_with_late_response(self, mock_post):
        """Test API POST with slow/late response (but not timeout)."""
        import time

        # Simulate slow response (2 seconds delay)
        def slow_response(*args, **kwargs):
            time.sleep(0.1)  # Small delay for test
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.text = '{"success": true, "message": "Processed"}'
            return mock_response

        mock_post.side_effect = slow_response

        poster = ApiPoster(self.config)
        result = poster.post_pipeline_logs(self.pipeline_info, self.all_logs)

        # Should still succeed (within timeout)
        self.assertTrue(result)

    def test_log_api_request_success(self):
        """Test API request logging for successful request."""
        poster = ApiPoster(self.config)

        poster._log_api_request(
            pipeline_id=12345,
            project_id=123,
            status_code=200,
            response_body='{"success": true}',
            duration_ms=1250,
            error=None
        )

        # Verify log file exists and contains expected data
        self.assertTrue(poster.api_log_file.exists())
        log_content = poster.api_log_file.read_text()

        self.assertIn("PIPELINE_ID=12345", log_content)
        self.assertIn("PROJECT_ID=123", log_content)
        self.assertIn("STATUS=200", log_content)
        self.assertIn("DURATION=1250ms", log_content)
        self.assertIn('{"success": true}', log_content)

    def test_log_api_request_error(self):
        """Test API request logging for failed request."""
        poster = ApiPoster(self.config)

        poster._log_api_request(
            pipeline_id=12345,
            project_id=123,
            status_code=500,
            response_body='{"error": "Internal server error"}',
            duration_ms=2100,
            error="HTTPError: 500 Internal Server Error"
        )

        # Verify log file contains error information
        log_content = poster.api_log_file.read_text()

        self.assertIn("STATUS=500", log_content)
        self.assertIn("ERROR=HTTPError: 500 Internal Server Error", log_content)
        self.assertIn("DURATION=2100ms", log_content)

    def test_log_api_request_truncates_long_response(self):
        """Test that long responses are truncated in logs."""
        poster = ApiPoster(self.config)

        # Create a response longer than 1000 characters
        long_response = "x" * 2000

        poster._log_api_request(
            pipeline_id=12345,
            project_id=123,
            status_code=200,
            response_body=long_response,
            duration_ms=1000,
            error=None
        )

        log_content = poster.api_log_file.read_text()

        # Verify response is truncated to 1000 chars
        # The log line will have the truncated response
        self.assertLess(log_content.count('x'), 1100)  # Allow some margin

    def test_format_payload_with_missing_fields(self):
        """Test payload formatting when optional fields are missing."""
        # Pipeline info with minimal fields
        minimal_pipeline_info = {
            "pipeline_id": 12345,
            "project_id": 123,
            "status": "success"
        }

        # Job with minimal fields
        minimal_logs = {
            789: {
                "details": {
                    "name": "test-job"
                },
                "log": "Test log content"
            }
        }

        poster = ApiPoster(self.config)
        payload = poster.format_payload(minimal_pipeline_info, minimal_logs)

        # Verify required fields are present
        self.assertEqual(payload["pipeline_id"], 12345)
        self.assertEqual(payload["project_id"], 123)

        # Verify optional fields are None or default
        self.assertIsNone(payload.get("ref"))
        self.assertIsNone(payload.get("sha"))

    @patch('src.api_poster.requests.post')
    def test_post_with_large_payload(self, mock_post):
        """Test API POST with large log payload."""
        # Create large logs
        large_logs = {}
        for i in range(50):
            large_logs[i] = {
                "details": {
                    "name": f"job-{i}",
                    "status": "success",
                    "stage": "test"
                },
                "log": "x" * 10000  # 10KB per job
            }

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"success": true}'
        mock_post.return_value = mock_response

        poster = ApiPoster(self.config)
        result = poster.post_pipeline_logs(self.pipeline_info, large_logs)

        # Verify it handles large payloads
        self.assertTrue(result)

    def test_format_payload_preserves_job_order(self):
        """Test that job order is preserved in payload."""
        poster = ApiPoster(self.config)
        payload = poster.format_payload(self.pipeline_info, self.all_logs)

        # Verify jobs are in order (456, 457)
        self.assertEqual(payload["jobs"][0]["job_id"], 456)
        self.assertEqual(payload["jobs"][1]["job_id"], 457)


if __name__ == "__main__":
    unittest.main()
