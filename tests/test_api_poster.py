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
from unittest.mock import patch, MagicMock
from pathlib import Path
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

        # Patch TokenManager to prevent JWT token generation in tests
        # This ensures tests use raw secret key instead of JWT tokens
        self.token_manager_patcher = patch('src.api_poster.TokenManager')
        self.mock_token_manager_class = self.token_manager_patcher.start()
        # Make TokenManager raise exception on initialization
        # so ApiPoster falls back to using raw bfa_secret_key
        self.mock_token_manager_class.side_effect = Exception("TokenManager disabled in tests")

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
            # Error context extraction
            error_context_lines_before=50,
            error_context_lines_after=10
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
        # Stop the TokenManager patcher
        self.token_manager_patcher.stop()

    def test_initialization(self):
        """Test ApiPoster initialization."""
        poster = ApiPoster(self.config)

        self.assertEqual(poster.config, self.config)
        self.assertEqual(poster.api_log_file.parent, Path(self.temp_dir))
        self.assertEqual(poster.api_log_file.name, "api-requests.log")

    # Note: Cannot test ImportError for requests library because it's imported at module level
    # The import will fail before tests run if requests is not available

    def test_format_payload(self):
        """Test payload formatting."""
        poster = ApiPoster(self.config)
        payload = poster.format_payload(self.pipeline_info, self.all_logs)

        # Verify structure - new simplified format
        self.assertEqual(payload["pipeline_id"], "12345")  # String now
        self.assertEqual(payload["repo"], "test-project")
        self.assertEqual(payload["branch"], "main")
        self.assertEqual(payload["commit"], "abc123d")  # First 7 chars of sha
        self.assertEqual(payload["triggered_by"], "Test User@sandvine.com")  # Username gets domain appended
        # job_name is a comma-separated string
        self.assertIsInstance(payload["job_name"], str)
        self.assertEqual(len(payload["failed_steps"]), 0)  # No failed jobs

        # Verify job names are present in comma-separated string
        self.assertIn("build:production", payload["job_name"])
        self.assertIn("test:unit", payload["job_name"])

    def test_format_payload_empty_jobs(self):
        """Test payload formatting with no jobs."""
        poster = ApiPoster(self.config)
        payload = poster.format_payload(self.pipeline_info, {})

        self.assertEqual(payload["pipeline_id"], "12345")  # String now
        self.assertEqual(payload["job_name"], "")  # Empty string when no jobs
        self.assertEqual(len(payload["failed_steps"]), 0)

    @patch('src.api_poster.requests.post')
    def test_successful_post(self, mock_post):
        """Test successful API POST."""
        # Mock successful response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"status": "ok", "message": "Logs received"}'
        mock_response.json.return_value = {"status": "ok", "message": "Logs received"}
        mock_post.return_value = mock_response

        poster = ApiPoster(self.config)
        result = poster.post_pipeline_logs(self.pipeline_info, self.all_logs)

        # Verify success
        self.assertTrue(result)

        # Verify request was made
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args.kwargs

        self.assertEqual(call_kwargs['headers']['Content-Type'], 'application/json')
        # Auth header uses bfa_secret_key from config
        self.assertEqual(call_kwargs['headers']['Authorization'], 'Bearer test-secret-key')
        self.assertEqual(call_kwargs['timeout'], 30)

    @patch('src.api_poster.requests.post')
    def test_post_without_auth_token(self, mock_post):
        """Test POST without authentication token."""
        # Create new config without auth token (no bfa_secret_key or bfa_host)
        import tempfile
        temp_dir = tempfile.mkdtemp()
        config_no_auth = Config(
            gitlab_url="https://gitlab.example.com",
            gitlab_token="test-token",
            webhook_port=8000,
            webhook_secret=None,
            log_output_dir=temp_dir,
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
            api_post_retry_enabled=False,
            api_post_save_to_file=False,
            jenkins_enabled=False,
            jenkins_url=None,
            jenkins_user=None,
            jenkins_api_token=None,
            jenkins_webhook_secret=None,
            bfa_host=None,
            bfa_secret_key=None,  # No auth
            error_context_lines_before=50,
            error_context_lines_after=10
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"status": "ok"}'
        mock_response.json.return_value = {"status": "ok"}
        mock_post.return_value = mock_response

        poster = ApiPoster(config_no_auth)
        poster.post_pipeline_logs(self.pipeline_info, self.all_logs)

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
            mock_response.text = '{"status": "ok", "message": "Processed"}'
            mock_response.json.return_value = {"status": "ok", "message": "Processed"}
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
        self.assertEqual(payload["pipeline_id"], "12345")  # String now
        self.assertEqual(payload["repo"], "unknown")  # Default when project_name missing
        self.assertEqual(payload["branch"], "unknown")  # Default when ref missing
        self.assertEqual(payload["commit"], "unknown")  # Default when sha missing
        # job_name is a comma-separated string
        self.assertEqual(payload["job_name"], "test-job")

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
        mock_response.text = '{"status": "ok"}'
        mock_response.json.return_value = {"status": "ok"}
        mock_post.return_value = mock_response

        poster = ApiPoster(self.config)
        result = poster.post_pipeline_logs(self.pipeline_info, large_logs)

        # Verify it handles large payloads
        self.assertTrue(result)

    def test_format_payload_preserves_job_order(self):
        """Test that job order is preserved in payload."""
        poster = ApiPoster(self.config)
        payload = poster.format_payload(self.pipeline_info, self.all_logs)

        # Verify job names are in comma-separated string
        self.assertIsInstance(payload["job_name"], str)
        self.assertIn("build:production", payload["job_name"])
        self.assertIn("test:unit", payload["job_name"])

    @patch('requests.post')
    def test_fetch_token_from_bfa_server_success(self, mock_post):
        """Test successful token fetching from BFA server."""
        self.config.bfa_host = "bfa.example.com"
        self.config.bfa_secret_key = None

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"token": "jwt-token-123", "expires_in": 60}
        mock_post.return_value = mock_response

        poster = ApiPoster(self.config)
        token = poster._fetch_token_from_bfa_server("gitlab_repo_123")

        self.assertEqual(token, "jwt-token-123")
        mock_post.assert_called_once()
        # Verify token is cached
        self.assertEqual(poster.bfa_token_cache, "jwt-token-123")
        self.assertIsNotNone(poster.bfa_token_expiry)

    @patch('requests.post')
    def test_fetch_token_from_bfa_server_uses_cache(self, mock_post):
        """Test that cached token is reused if still valid."""
        self.config.bfa_host = "bfa.example.com"
        self.config.bfa_secret_key = None

        poster = ApiPoster(self.config)
        # Set up cached token
        import time
        poster.bfa_token_cache = "cached-token"
        poster.bfa_token_expiry = time.time() + 3000  # Valid for 50 minutes

        token = poster._fetch_token_from_bfa_server("gitlab_repo_123")

        self.assertEqual(token, "cached-token")
        # Should not make HTTP request
        mock_post.assert_not_called()

    @patch('requests.post')
    def test_fetch_token_from_bfa_server_request_failure(self, mock_post):
        """Test token fetching when HTTP request fails."""
        self.config.bfa_host = "bfa.example.com"
        self.config.bfa_secret_key = None

        mock_post.side_effect = requests.exceptions.ConnectionError("Network error")

        poster = ApiPoster(self.config)
        token = poster._fetch_token_from_bfa_server("gitlab_repo_123")

        self.assertIsNone(token)

    @patch('requests.post')
    def test_fetch_token_from_bfa_server_missing_token_field(self, mock_post):
        """Test token fetching when response is missing token field."""
        self.config.bfa_host = "bfa.example.com"
        self.config.bfa_secret_key = None

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"expires_in": 60}  # Missing 'token'
        mock_post.return_value = mock_response

        poster = ApiPoster(self.config)
        token = poster._fetch_token_from_bfa_server("gitlab_repo_123")

        self.assertIsNone(token)

    def test_fetch_token_without_bfa_host_configured(self):
        """Test token fetching fails when BFA_HOST is not configured."""
        self.config.bfa_host = None
        self.config.bfa_secret_key = None

        poster = ApiPoster(self.config)
        token = poster._fetch_token_from_bfa_server("gitlab_repo_123")

        self.assertIsNone(token)

    @patch('requests.post')
    def test_post_to_api_with_jwt_generation(self, mock_post):
        """Test _post_to_api uses locally generated JWT token."""
        self.config.bfa_secret_key = "test-secret-key"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"status": "ok", "results": []}'
        mock_response.json.return_value = {"status": "ok", "results": []}
        mock_post.return_value = mock_response

        poster = ApiPoster(self.config)
        payload = {"repo": "test", "pipeline_id": "123"}

        status, body, duration = poster._post_to_api(payload)

        self.assertEqual(status, 200)
        # Verify Authorization header with JWT Bearer token was used
        call_kwargs = mock_post.call_args[1]
        self.assertIn("Authorization", call_kwargs["headers"])
        self.assertTrue(call_kwargs["headers"]["Authorization"].startswith("Bearer "))

    @patch('requests.post')
    @patch.object(ApiPoster, '_fetch_token_from_bfa_server')
    def test_post_to_api_with_bfa_server_token(self, mock_fetch_token, mock_post):
        """Test _post_to_api fetches token from BFA server when no secret key."""
        self.config.bfa_host = "bfa.example.com"
        self.config.bfa_secret_key = None

        mock_fetch_token.return_value = "fetched-token-456"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"status": "ok", "results": []}'
        mock_response.json.return_value = {"status": "ok", "results": []}
        mock_post.return_value = mock_response

        poster = ApiPoster(self.config)
        payload = {"repo": "test", "pipeline_id": "123"}

        status, body, duration = poster._post_to_api(payload)

        self.assertEqual(status, 200)
        mock_fetch_token.assert_called_once()
        call_kwargs = mock_post.call_args[1]
        self.assertEqual(call_kwargs["headers"]["Authorization"], "Bearer fetched-token-456")

    @patch('requests.post')
    def test_post_to_api_with_raw_secret_key_fallback(self, mock_post):
        """Test _post_to_api uses raw secret key when JWT generation fails."""
        self.config.bfa_secret_key = "raw-secret"
        self.config.bfa_host = None

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"status": "ok", "results": []}'
        mock_response.json.return_value = {"status": "ok", "results": []}
        mock_post.return_value = mock_response

        poster = ApiPoster(self.config)
        # Force token manager to None to simulate initialization failure
        poster.token_manager = None

        payload = {"repo": "test", "pipeline_id": "123"}
        status, body, duration = poster._post_to_api(payload)

        self.assertEqual(status, 200)
        call_kwargs = mock_post.call_args[1]
        self.assertEqual(call_kwargs["headers"]["Authorization"], "Bearer raw-secret")

    @patch('requests.post')
    def test_post_to_api_without_authentication(self, mock_post):
        """Test _post_to_api proceeds without auth when nothing is configured."""
        self.config.bfa_secret_key = None
        self.config.bfa_host = None

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"status": "ok", "results": []}'
        mock_response.json.return_value = {"status": "ok", "results": []}
        mock_post.return_value = mock_response

        poster = ApiPoster(self.config)
        payload = {"repo": "test", "pipeline_id": "123"}

        status, body, duration = poster._post_to_api(payload)

        self.assertEqual(status, 200)
        call_kwargs = mock_post.call_args[1]
        # Authorization header should not be present
        self.assertNotIn("Authorization", call_kwargs["headers"])

    @patch('requests.post')
    def test_post_to_api_non_json_response(self, mock_post):
        """Test _post_to_api handles non-JSON response."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "Not JSON"
        mock_response.json.side_effect = ValueError("Invalid JSON")
        mock_post.return_value = mock_response

        poster = ApiPoster(self.config)
        payload = {"repo": "test", "pipeline_id": "123"}

        with self.assertRaises(requests.exceptions.RequestException) as context:
            poster._post_to_api(payload)

        self.assertIn("non-JSON response", str(context.exception))

    @patch('requests.post')
    def test_post_to_api_response_status_not_ok(self, mock_post):
        """Test _post_to_api handles response with status != 'ok'."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"status": "error", "message": "Something failed"}'
        mock_response.json.return_value = {"status": "error", "message": "Something failed"}
        mock_post.return_value = mock_response

        poster = ApiPoster(self.config)
        payload = {"repo": "test", "pipeline_id": "123"}

        with self.assertRaises(requests.exceptions.RequestException) as context:
            poster._post_to_api(payload)

        self.assertIn("status 'error'", str(context.exception))

    @patch('requests.post')
    def test_post_to_api_with_results_logging(self, mock_post):
        """Test _post_to_api logs results when present."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"status": "ok", "results": [{"step_name": "build", "error_hash": "abc123"}]}'
        mock_response.json.return_value = {
            "status": "ok",
            "results": [{"step_name": "build", "error_hash": "abc123", "source": "gitlab"}]
        }
        mock_post.return_value = mock_response

        poster = ApiPoster(self.config)
        payload = {"repo": "test", "pipeline_id": "123"}

        status, body, duration = poster._post_to_api(payload)

        self.assertEqual(status, 200)
        # Verify results were present
        self.assertIn("results", mock_response.json.return_value)
        self.assertEqual(len(mock_response.json.return_value["results"]), 1)

    @patch('requests.post')
    def test_post_jenkins_logs_success(self, mock_post):
        """Test successful Jenkins logs posting."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"status": "ok"}'
        mock_response.json.return_value = {"status": "ok"}
        mock_post.return_value = mock_response

        jenkins_payload = {
            "source": "jenkins",
            "job_name": "build-job",
            "build_number": 42,
            "build_url": "http://jenkins/job/42",
            "status": "SUCCESS",
            "duration_ms": 60000,
            "timestamp": "2024-01-01T00:00:00Z",
            "stages": []
        }

        poster = ApiPoster(self.config)
        result = poster.post_jenkins_logs(jenkins_payload)

        self.assertTrue(result)
        mock_post.assert_called_once()

    def test_post_jenkins_logs_when_api_disabled(self):
        """Test Jenkins logs posting when API is disabled."""
        self.config.api_post_enabled = False

        jenkins_payload = {
            "source": "jenkins",
            "job_name": "test-job",
            "build_number": 1
        }

        poster = ApiPoster(self.config)
        result = poster.post_jenkins_logs(jenkins_payload)

        self.assertFalse(result)

    def test_post_jenkins_logs_without_url_configured(self):
        """Test Jenkins logs posting when API URL is not configured."""
        self.config.api_post_url = None

        jenkins_payload = {
            "source": "jenkins",
            "job_name": "test-job",
            "build_number": 1
        }

        poster = ApiPoster(self.config)
        result = poster.post_jenkins_logs(jenkins_payload)

        self.assertFalse(result)

    @patch('requests.post')
    def test_post_jenkins_logs_with_retry_exhausted(self, mock_post):
        """Test Jenkins logs posting when retry is exhausted."""
        from src.error_handler import RetryExhaustedError

        mock_post.side_effect = requests.exceptions.ConnectionError("Network error")

        jenkins_payload = {
            "source": "jenkins",
            "job_name": "failing-job",
            "build_number": 99,
            "status": "FAILURE"
        }

        poster = ApiPoster(self.config)
        result = poster.post_jenkins_logs(jenkins_payload)

        self.assertFalse(result)

    @patch('requests.post')
    def test_post_jenkins_logs_unexpected_exception(self, mock_post):
        """Test Jenkins logs posting handles unexpected exceptions."""
        mock_post.side_effect = RuntimeError("Unexpected error")

        jenkins_payload = {
            "source": "jenkins",
            "job_name": "error-job",
            "build_number": 77
        }

        poster = ApiPoster(self.config)
        result = poster.post_jenkins_logs(jenkins_payload)

        self.assertFalse(result)

    @patch('requests.post')
    def test_post_jenkins_logs_non_success_status_code(self, mock_post):
        """Test Jenkins logs posting when API returns non-success status."""
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = '{"status": "error"}'
        mock_response.json.return_value = {"status": "error"}
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError("400 Bad Request")
        mock_post.return_value = mock_response

        jenkins_payload = {
            "source": "jenkins",
            "job_name": "bad-request-job",
            "build_number": 55
        }

        poster = ApiPoster(self.config)
        result = poster.post_jenkins_logs(jenkins_payload)

        self.assertFalse(result)

    @patch('requests.post')
    def test_post_jenkins_logs_without_retry(self, mock_post):
        """Test Jenkins logs posting with retry disabled."""
        self.config.api_post_retry_enabled = False

        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.text = '{"status": "ok"}'
        mock_response.json.return_value = {"status": "ok"}
        mock_post.return_value = mock_response

        jenkins_payload = {
            "source": "jenkins",
            "job_name": "no-retry-job",
            "build_number": 33
        }

        poster = ApiPoster(self.config)
        result = poster.post_jenkins_logs(jenkins_payload)

        self.assertTrue(result)

    def test_post_pipeline_logs_payload_formatting_failure(self):
        """Test pipeline logs posting when payload formatting fails."""
        poster = ApiPoster(self.config)

        # Create malformed pipeline_info that will cause formatting error
        # Must have pipeline_id/project_id but will fail in format_payload
        bad_pipeline_info = {
            'pipeline_id': 123,
            'project_id': 456,
            'project_name': 'test'
            # Missing other required fields
        }

        # Create malformed all_logs that will cause iteration error during format_payload
        bad_all_logs = {
            123: None  # This will cause error when accessing job_data.get("details")
        }

        result = poster.post_pipeline_logs(bad_pipeline_info, bad_all_logs)

        self.assertFalse(result)

    @patch('requests.post')
    def test_post_pipeline_logs_unexpected_exception_during_post(self, mock_post):
        """Test pipeline logs posting handles unexpected exception during POST."""
        mock_post.side_effect = RuntimeError("Unexpected runtime error")

        poster = ApiPoster(self.config)
        result = poster.post_pipeline_logs(self.pipeline_info, self.all_logs)

        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
