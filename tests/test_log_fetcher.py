"""
Unit tests for log_fetcher module.
"""

import unittest
from unittest.mock import Mock, patch
import requests

from src.log_fetcher import LogFetcher, GitLabAPIError
from src.config_loader import Config


class TestLogFetcher(unittest.TestCase):
    """Test cases for LogFetcher class."""

    def setUp(self):
        """Set up test fixtures."""
        self.config = Config(
            gitlab_url="https://gitlab.example.com",
            gitlab_token="test-token-123",
            webhook_port=8000,
            webhook_secret=None,
            log_output_dir="/tmp/test",
            retry_attempts=3,
            retry_delay=1,
            log_level="INFO",
            log_save_pipeline_status=["all"],
            log_save_projects=[],
            log_exclude_projects=[],
            log_save_job_status=["all"],
            log_save_metadata_always=True,
            api_post_enabled=False,
            api_post_url=None,
            api_post_timeout=30,
            api_post_retry_enabled=True,
            api_post_save_to_file=False,
            jenkins_enabled=False,
            jenkins_url=None,
            jenkins_user=None,
            jenkins_api_token=None,
            jenkins_webhook_secret=None,
            bfa_host=None,
            bfa_secret_key=None,
            error_context_lines_before=50,
            error_context_lines_after=10,
            error_adaptive_context_enabled=True,
            error_adaptive_thresholds=[(50, 50, 10), (100, 10, 5), (150, 5, 2)],
            max_log_lines=100000,
            tail_log_lines=5000,
            stream_chunk_size=8192
        )

        self.fetcher = LogFetcher(self.config)

    def test_initialization(self):
        """Test LogFetcher initialization."""
        self.assertEqual(self.fetcher.base_url, "https://gitlab.example.com/api/v4")
        self.assertEqual(self.fetcher.session.headers['PRIVATE-TOKEN'], 'test-token-123')
        self.assertEqual(self.fetcher.session.headers['Content-Type'], 'application/json')

    @patch('requests.Session.get')
    def test_fetch_job_log_success(self, mock_get):
        """Test successful job log fetch."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "Build log output\nLine 2\nLine 3"
        mock_get.return_value = mock_response

        result = self.fetcher.fetch_job_log(123, 456)

        self.assertEqual(result, "Build log output\nLine 2\nLine 3")
        mock_get.assert_called_once_with(
            "https://gitlab.example.com/api/v4/projects/123/jobs/456/trace",
            timeout=30
        )

    @patch('requests.Session.get')
    def test_fetch_job_log_not_found(self, mock_get):
        """Test job log fetch when log not found (404)."""
        mock_response = Mock()
        mock_response.status_code = 404
        mock_get.return_value = mock_response

        result = self.fetcher.fetch_job_log(123, 456)

        self.assertEqual(result, "[Log not available for job 456]")

    @patch('requests.Session.get')
    def test_fetch_job_log_unauthorized(self, mock_get):
        """Test job log fetch with authentication failure (401)."""
        mock_response = Mock()
        mock_response.status_code = 401
        mock_get.return_value = mock_response

        with self.assertRaises(GitLabAPIError) as context:
            self.fetcher.fetch_job_log(123, 456)

        self.assertIn("Authentication failed", str(context.exception))

    @patch('requests.Session.get')
    def test_fetch_job_log_forbidden(self, mock_get):
        """Test job log fetch with access forbidden (403)."""
        mock_response = Mock()
        mock_response.status_code = 403
        mock_get.return_value = mock_response

        with self.assertRaises(GitLabAPIError) as context:
            self.fetcher.fetch_job_log(123, 456)

        self.assertIn("Access forbidden", str(context.exception))

    @patch('requests.Session.get')
    def test_fetch_job_log_server_error(self, mock_get):
        """Test job log fetch with server error (500)."""
        from src.error_handler import RetryExhaustedError

        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.raise_for_status.side_effect = requests.HTTPError("500 Server Error")
        mock_get.return_value = mock_response

        # The decorator retries and then raises RetryExhaustedError
        with self.assertRaises(RetryExhaustedError):
            self.fetcher.fetch_job_log(123, 456)

    @patch('requests.Session.get')
    def test_fetch_job_log_request_exception(self, mock_get):
        """Test job log fetch with connection error."""
        from src.error_handler import RetryExhaustedError

        mock_get.side_effect = requests.ConnectionError("Connection failed")

        # The decorator retries and then raises RetryExhaustedError
        with self.assertRaises(RetryExhaustedError):
            self.fetcher.fetch_job_log(123, 456)

    @patch('requests.Session.get')
    def test_fetch_job_details_success(self, mock_get):
        """Test successful job details fetch."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": 456,
            "name": "build",
            "stage": "build",
            "status": "success",
            "duration": 240.5
        }
        mock_get.return_value = mock_response

        result = self.fetcher.fetch_job_details(123, 456)

        self.assertEqual(result["id"], 456)
        self.assertEqual(result["name"], "build")
        self.assertEqual(result["status"], "success")
        mock_get.assert_called_once_with(
            "https://gitlab.example.com/api/v4/projects/123/jobs/456",
            timeout=30
        )

    @patch('requests.Session.get')
    def test_fetch_job_details_request_exception(self, mock_get):
        """Test job details fetch with connection error."""
        from src.error_handler import RetryExhaustedError

        mock_get.side_effect = requests.ConnectionError("Connection failed")

        # The decorator retries and then raises RetryExhaustedError
        with self.assertRaises(RetryExhaustedError):
            self.fetcher.fetch_job_details(123, 456)

    @patch('requests.Session.get')
    def test_fetch_pipeline_jobs_success(self, mock_get):
        """Test successful pipeline jobs fetch."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {"id": 456, "name": "build", "status": "success"},
            {"id": 457, "name": "test", "status": "success"}
        ]
        mock_response.links = {}
        mock_get.return_value = mock_response

        result = self.fetcher.fetch_pipeline_jobs(123, 789)

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["name"], "build")
        self.assertEqual(result[1]["name"], "test")

    @patch('requests.Session.get')
    def test_fetch_pipeline_jobs_with_pagination(self, mock_get):
        """Test pipeline jobs fetch with pagination."""
        # First page - return full page (100 jobs) to trigger pagination
        first_page_jobs = [{"id": i, "name": f"job-{i}", "status": "success"} for i in range(100)]
        mock_response1 = Mock()
        mock_response1.status_code = 200
        mock_response1.json.return_value = first_page_jobs

        # Second page - return fewer jobs to end pagination
        mock_response2 = Mock()
        mock_response2.status_code = 200
        mock_response2.json.return_value = [
            {"id": 456, "name": "build", "status": "success"},
            {"id": 457, "name": "test", "status": "success"}
        ]

        mock_get.side_effect = [mock_response1, mock_response2]

        result = self.fetcher.fetch_pipeline_jobs(123, 789)

        # Should have 100 + 2 = 102 jobs total
        self.assertEqual(len(result), 102)
        self.assertEqual(result[100]["name"], "build")
        self.assertEqual(result[101]["name"], "test")

    @patch('requests.Session.get')
    def test_fetch_pipeline_jobs_request_exception(self, mock_get):
        """Test pipeline jobs fetch with connection error."""
        from src.error_handler import RetryExhaustedError

        mock_get.side_effect = requests.ConnectionError("Connection failed")

        # The decorator retries and then raises RetryExhaustedError
        with self.assertRaises(RetryExhaustedError):
            self.fetcher.fetch_pipeline_jobs(123, 789)

    @patch('requests.Session.get')
    def test_fetch_pipeline_jobs_empty_response(self, mock_get):
        """Test pipeline jobs fetch when API returns empty list."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = []  # Empty list
        mock_get.return_value = mock_response

        result = self.fetcher.fetch_pipeline_jobs(123, 789)

        # Should return empty list and break immediately (line 203)
        self.assertEqual(len(result), 0)
        self.assertEqual(result, [])

    @patch('requests.Session.get')
    def test_fetch_all_logs_for_pipeline(self, mock_get):
        """Test fetching all logs for a pipeline."""
        # Mock fetch_pipeline_jobs response (first call)
        mock_jobs_response = Mock()
        mock_jobs_response.status_code = 200
        mock_jobs_response.json.return_value = [
            {"id": 1, "name": "build", "status": "success"},
            {"id": 2, "name": "test", "status": "success"}
        ]

        # Mock fetch_job_log responses (subsequent calls)
        mock_log1_response = Mock()
        mock_log1_response.status_code = 200
        mock_log1_response.text = "Build log content"

        mock_log2_response = Mock()
        mock_log2_response.status_code = 200
        mock_log2_response.text = "Test log content"

        mock_get.side_effect = [mock_jobs_response, mock_log1_response, mock_log2_response]

        result = self.fetcher.fetch_all_logs_for_pipeline(123, 789)

        # Should have 2 jobs with logs
        self.assertEqual(len(result), 2)
        self.assertIn(1, result)
        self.assertIn(2, result)
        self.assertEqual(result[1]['details']['name'], "build")
        self.assertEqual(result[1]['log'], "Build log content")
        self.assertEqual(result[2]['details']['name'], "test")
        self.assertEqual(result[2]['log'], "Test log content")

    @patch('requests.Session.get')
    def test_fetch_all_logs_for_pipeline_with_job_error(self, mock_get):
        """Test fetch_all_logs_for_pipeline when one job log fetch fails."""
        # Mock fetch_pipeline_jobs
        mock_jobs_response = Mock()
        mock_jobs_response.status_code = 200
        mock_jobs_response.json.return_value = [
            {"id": 1, "name": "build", "status": "success"},
            {"id": 2, "name": "test", "status": "failed"}
        ]

        # Mock log responses - second one fails
        mock_log1_response = Mock()
        mock_log1_response.status_code = 200
        mock_log1_response.text = "Build log content"

        mock_get.side_effect = [
            mock_jobs_response,
            mock_log1_response,
            requests.ConnectionError("Network error")
        ]

        result = self.fetcher.fetch_all_logs_for_pipeline(123, 789)

        # Should have 2 jobs, second with error message (line 262)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[1]['log'], "Build log content")
        self.assertIn("[Error fetching log:", result[2]['log'])

    @patch('requests.Session.get')
    def test_fetch_pipeline_details(self, mock_get):
        """Test fetching pipeline details."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": 789,
            "status": "success",
            "ref": "main",
            "sha": "abc123",
            "user": {"username": "testuser"}
        }
        mock_get.return_value = mock_response

        result = self.fetcher.fetch_pipeline_details(123, 789)

        # Verify pipeline details
        self.assertEqual(result['id'], 789)
        self.assertEqual(result['status'], "success")
        self.assertEqual(result['ref'], "main")
        mock_get.assert_called_once()

    @patch('requests.Session.get')
    def test_fetch_pipeline_details_request_error(self, mock_get):
        """Test fetch_pipeline_details with HTTP error."""
        from src.error_handler import RetryExhaustedError

        mock_get.side_effect = requests.HTTPError("404 Not Found")

        # The decorator retries and then raises RetryExhaustedError
        with self.assertRaises(RetryExhaustedError):
            self.fetcher.fetch_pipeline_details(123, 789)

    def test_close(self):
        """Test closing the fetcher session."""
        # Create a real session to test closing
        import requests
        self.fetcher.session = requests.Session()

        # Close should not raise an error
        self.fetcher.close()

        # Session should be closed (we can't directly check but method should execute)
        # This covers lines 308-309

    @patch('requests.Session.get')
    @patch('requests.Session.head')
    def test_fetch_job_log_tail_with_range_support(self, mock_head, mock_get):
        """Test fetch_job_log_tail with Range header support (206 response)."""
        # Mock HEAD response with Content-Length
        mock_head_response = Mock()
        mock_head_response.status_code = 200
        mock_head_response.headers = {'Content-Length': '10000'}
        mock_head.return_value = mock_head_response

        # Mock GET with Range header returning 206 Partial Content
        mock_range_response = Mock()
        mock_range_response.status_code = 206
        mock_range_response.text = "Line 1\nLine 2\nLine 3\nLine 4\nLine 5"
        mock_get.return_value = mock_range_response

        result = self.fetcher.fetch_job_log_tail(123, 456, 5)

        self.assertEqual(result, "Line 1\nLine 2\nLine 3\nLine 4\nLine 5")
        mock_head.assert_called_once()
        mock_get.assert_called_once()
        # Verify Range header was used
        call_kwargs = mock_get.call_args[1]
        self.assertIn('headers', call_kwargs)
        self.assertIn('Range', call_kwargs['headers'])

    @patch('requests.Session.get')
    @patch('requests.Session.head')
    def test_fetch_job_log_tail_without_range_support(self, mock_head, mock_get):
        """Test fetch_job_log_tail fallback when Range not supported (200 instead of 206)."""
        # Mock HEAD response
        mock_head_response = Mock()
        mock_head_response.status_code = 200
        mock_head_response.headers = {'Content-Length': '10000'}
        mock_head.return_value = mock_head_response

        # Mock Range request returning 200 (not 206), then mock full fetch
        mock_range_response = Mock()
        mock_range_response.status_code = 200  # Server doesn't support Range

        mock_full_log_response = Mock()
        mock_full_log_response.status_code = 200
        mock_full_log_response.text = "Line 1\nLine 2\nLine 3\nLine 4\nLine 5\nLine 6\nLine 7\nLine 8"

        mock_get.side_effect = [mock_range_response, mock_full_log_response]

        result = self.fetcher.fetch_job_log_tail(123, 456, 3)

        # Should fallback to full fetch and trim to last 3 lines
        self.assertEqual(result, "Line 6\nLine 7\nLine 8")

    @patch('requests.Session.get')
    @patch('requests.Session.head')
    def test_fetch_job_log_tail_head_request_fails(self, mock_head, mock_get):
        """Test fetch_job_log_tail when HEAD request fails."""
        # Mock HEAD request failure
        mock_head.side_effect = requests.RequestException("Connection error")

        # Mock full log fetch (fallback)
        mock_full_log_response = Mock()
        mock_full_log_response.status_code = 200
        mock_full_log_response.text = "Line 1\nLine 2\nLine 3\nLine 4\nLine 5"
        mock_get.return_value = mock_full_log_response

        result = self.fetcher.fetch_job_log_tail(123, 456, 3)

        # Should fallback to full fetch and trim
        self.assertEqual(result, "Line 3\nLine 4\nLine 5")

    @patch('requests.Session.get')
    @patch('requests.Session.head')
    def test_fetch_job_log_tail_no_content_length(self, mock_head, mock_get):
        """Test fetch_job_log_tail when HEAD response has no Content-Length."""
        # Mock HEAD response without Content-Length
        mock_head_response = Mock()
        mock_head_response.status_code = 200
        mock_head_response.headers = {}  # No Content-Length
        mock_head.return_value = mock_head_response

        # Mock full log fetch (fallback)
        mock_full_log_response = Mock()
        mock_full_log_response.status_code = 200
        mock_full_log_response.text = "Line 1\nLine 2\nLine 3"
        mock_get.return_value = mock_full_log_response

        result = self.fetcher.fetch_job_log_tail(123, 456, 2)

        # Should fallback to full fetch and trim
        self.assertEqual(result, "Line 2\nLine 3")

    @patch('requests.Session.get')
    @patch('requests.Session.head')
    def test_fetch_job_log_tail_log_not_available(self, mock_head, mock_get):
        """Test fetch_job_log_tail when log is not available (404)."""
        # Mock HEAD fails
        mock_head.side_effect = requests.RequestException("Error")

        # Mock full fetch returning log not available
        mock_full_log_response = Mock()
        mock_full_log_response.status_code = 404
        mock_get.return_value = mock_full_log_response

        result = self.fetcher.fetch_job_log_tail(123, 456, 5)

        # Should return log not available message
        self.assertEqual(result, "[Log not available for job 456]")

    @patch('requests.Session.get')
    @patch('requests.Session.head')
    def test_fetch_job_log_tail_shorter_than_requested(self, mock_head, mock_get):
        """Test fetch_job_log_tail when log has fewer lines than requested."""
        # Mock HEAD fails
        mock_head.side_effect = requests.RequestException("Error")

        # Mock full fetch with short log
        mock_full_log_response = Mock()
        mock_full_log_response.status_code = 200
        mock_full_log_response.text = "Line 1\nLine 2"
        mock_get.return_value = mock_full_log_response

        result = self.fetcher.fetch_job_log_tail(123, 456, 100)

        # Should return full log since it's shorter than requested
        self.assertEqual(result, "Line 1\nLine 2")

    @patch('requests.Session.get')
    @patch('requests.Session.head')
    def test_fetch_job_log_tail_head_404(self, mock_head, mock_get):
        """Test fetch_job_log_tail when HEAD returns 404."""
        # Mock HEAD returning non-200 status
        mock_head_response = Mock()
        mock_head_response.status_code = 404
        mock_head.return_value = mock_head_response

        # Mock full fetch
        mock_full_log_response = Mock()
        mock_full_log_response.status_code = 200
        mock_full_log_response.text = "Line 1\nLine 2\nLine 3"
        mock_get.return_value = mock_full_log_response

        result = self.fetcher.fetch_job_log_tail(123, 456, 2)

        # Should fallback to full fetch
        self.assertEqual(result, "Line 2\nLine 3")


class TestGitLabAPIError(unittest.TestCase):
    """Test cases for GitLabAPIError exception."""

    def test_exception_message(self):
        """Test GitLabAPIError can be raised with a message."""
        with self.assertRaises(GitLabAPIError) as context:
            raise GitLabAPIError("Test error message")

        self.assertEqual(str(context.exception), "Test error message")


if __name__ == '__main__':
    unittest.main()
