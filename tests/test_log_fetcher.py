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
            error_context_lines_after=10
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
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.raise_for_status.side_effect = requests.HTTPError("500 Server Error")
        mock_get.return_value = mock_response

        with self.assertRaises(requests.HTTPError):
            self.fetcher.fetch_job_log(123, 456)

    @patch('requests.Session.get')
    def test_fetch_job_log_request_exception(self, mock_get):
        """Test job log fetch with connection error."""
        mock_get.side_effect = requests.ConnectionError("Connection failed")

        with self.assertRaises(requests.RequestException):
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
        mock_get.side_effect = requests.ConnectionError("Connection failed")

        with self.assertRaises(requests.RequestException):
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
        # First page
        mock_response1 = Mock()
        mock_response1.status_code = 200
        mock_response1.json.return_value = [
            {"id": 456, "name": "build", "status": "success"}
        ]
        mock_response1.links = {'next': {'url': 'https://gitlab.example.com/api/v4/projects/123/pipelines/789/jobs?page=2'}}

        # Second page
        mock_response2 = Mock()
        mock_response2.status_code = 200
        mock_response2.json.return_value = [
            {"id": 457, "name": "test", "status": "success"}
        ]
        mock_response2.links = {}

        mock_get.side_effect = [mock_response1, mock_response2]

        result = self.fetcher.fetch_pipeline_jobs(123, 789)

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["name"], "build")
        self.assertEqual(result[1]["name"], "test")

    @patch('requests.Session.get')
    def test_fetch_pipeline_jobs_request_exception(self, mock_get):
        """Test pipeline jobs fetch with connection error."""
        mock_get.side_effect = requests.ConnectionError("Connection failed")

        with self.assertRaises(requests.RequestException):
            self.fetcher.fetch_pipeline_jobs(123, 789)


class TestGitLabAPIError(unittest.TestCase):
    """Test cases for GitLabAPIError exception."""

    def test_exception_message(self):
        """Test GitLabAPIError can be raised with a message."""
        with self.assertRaises(GitLabAPIError) as context:
            raise GitLabAPIError("Test error message")

        self.assertEqual(str(context.exception), "Test error message")


if __name__ == '__main__':
    unittest.main()
