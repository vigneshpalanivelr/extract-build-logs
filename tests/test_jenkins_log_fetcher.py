"""
Unit tests for jenkins_log_fetcher module.
"""

import unittest
from unittest.mock import Mock, patch
import requests

from src.jenkins_log_fetcher import JenkinsLogFetcher
from src.config_loader import Config
from src.error_handler import RetryExhaustedError


class TestJenkinsLogFetcher(unittest.TestCase):
    """Test cases for JenkinsLogFetcher class."""

    def setUp(self):
        """Set up test fixtures."""
        self.config = Config(
            gitlab_url="https://gitlab.example.com",
            gitlab_token="test-token",
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
            jenkins_enabled=True,
            jenkins_url="https://jenkins.example.com",
            jenkins_user="test_user",
            jenkins_api_token="test_api_token",
            jenkins_webhook_secret=None,
            bfa_host=None,
            bfa_secret_key=None,
            error_context_lines_before=50,
            error_context_lines_after=10,
            max_log_lines=100000,
            tail_log_lines=5000,
            stream_chunk_size=8192
        )

        self.fetcher = JenkinsLogFetcher(self.config)

    def test_initialization_with_jenkins_enabled(self):
        """Test initialization when Jenkins is enabled."""
        self.assertEqual(self.fetcher.jenkins_url, "https://jenkins.example.com")
        self.assertIsNotNone(self.fetcher.auth)
        self.assertIsNotNone(self.fetcher.error_handler)

    def test_initialization_without_jenkins_enabled(self):
        """Test initialization fails when Jenkins is disabled."""
        config = Config(
            gitlab_url="https://gitlab.example.com",
            gitlab_token="test-token",
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
        max_log_lines=100000,
        tail_log_lines=5000,
        stream_chunk_size=8192
        )

        with self.assertRaises(ValueError) as context:
            JenkinsLogFetcher(config)

        self.assertIn("Jenkins is not enabled", str(context.exception))

    def test_initialization_with_explicit_credentials(self):
        """Test initialization with explicit Jenkins credentials."""
        fetcher = JenkinsLogFetcher(
            jenkins_url="https://jenkins.example.com",
            jenkins_user="test_user",
            jenkins_api_token="test_token",
            retry_attempts=3,
            retry_delay=2
        )

        self.assertEqual(fetcher.jenkins_url, "https://jenkins.example.com")
        self.assertEqual(fetcher.auth.username, "test_user")
        self.assertEqual(fetcher.auth.password, "test_token")
        self.assertIsNotNone(fetcher.error_handler)

    def test_initialization_with_explicit_credentials_trailing_slash(self):
        """Test initialization with explicit credentials removes trailing slash."""
        fetcher = JenkinsLogFetcher(
            jenkins_url="https://jenkins.example.com/",
            jenkins_user="test_user",
            jenkins_api_token="test_token"
        )

        # Trailing slash should be removed
        self.assertEqual(fetcher.jenkins_url, "https://jenkins.example.com")

    def test_initialization_without_config_or_credentials(self):
        """Test initialization fails when neither config nor credentials provided."""
        with self.assertRaises(ValueError) as context:
            JenkinsLogFetcher()

        self.assertIn("Must provide either config or explicit Jenkins credentials", str(context.exception))

    def test_initialization_with_partial_credentials(self):
        """Test initialization fails with incomplete explicit credentials."""
        # Missing jenkins_api_token
        with self.assertRaises(ValueError) as context:
            JenkinsLogFetcher(
                jenkins_url="https://jenkins.example.com",
                jenkins_user="test_user"
            )

        self.assertIn("Must provide either config or explicit Jenkins credentials", str(context.exception))

    @patch('src.jenkins_log_fetcher.JenkinsLogFetcher._make_request')
    def test_fetch_build_info_success(self, mock_make_request):
        """Test successful build info fetch."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "result": "SUCCESS",
            "duration": 120000,
            "timestamp": 1704067200000
        }

        # Mock the error_handler.retry_with_backoff to return the response
        with patch.object(self.fetcher.error_handler, 'retry_with_backoff', return_value=mock_response):
            result = self.fetcher.fetch_build_info("test-job", 123)

        self.assertEqual(result["result"], "SUCCESS")
        self.assertEqual(result["duration"], 120000)

    @patch('src.jenkins_log_fetcher.JenkinsLogFetcher._make_request')
    def test_fetch_build_info_retry_exhausted(self, mock_make_request):
        """Test build info fetch when retries are exhausted."""
        # Mock the error_handler.retry_with_backoff to raise RetryExhaustedError
        test_exception = Exception("Max retries exceeded")
        with patch.object(self.fetcher.error_handler, 'retry_with_backoff',
                          side_effect=RetryExhaustedError(3, test_exception)):
            with self.assertRaises(RetryExhaustedError):
                self.fetcher.fetch_build_info("test-job", 123)

    @patch('src.jenkins_log_fetcher.JenkinsLogFetcher._make_request')
    def test_fetch_console_log_success(self, mock_make_request):
        """Test successful console log fetch."""
        mock_response = Mock()
        mock_response.text = "Console log output\nLine 2\nLine 3"

        with patch.object(self.fetcher.error_handler, 'retry_with_backoff', return_value=mock_response):
            result = self.fetcher.fetch_console_log("test-job", 123)

        self.assertEqual(result, "Console log output\nLine 2\nLine 3")

    @patch('src.jenkins_log_fetcher.JenkinsLogFetcher._make_request')
    def test_fetch_console_log_retry_exhausted(self, mock_make_request):
        """Test console log fetch when retries are exhausted."""
        test_exception = Exception("Max retries exceeded")
        with patch.object(self.fetcher.error_handler, 'retry_with_backoff',
                          side_effect=RetryExhaustedError(3, test_exception)):
            with self.assertRaises(RetryExhaustedError):
                self.fetcher.fetch_console_log("test-job", 123)

    @patch('src.jenkins_log_fetcher.JenkinsLogFetcher._make_request')
    def test_fetch_stages_success(self, mock_make_request):
        """Test successful stages fetch."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "stages": [
                {"id": "1", "name": "Build", "status": "SUCCESS"},
                {"id": "2", "name": "Test", "status": "SUCCESS"}
            ]
        }
        mock_make_request.return_value = mock_response

        result = self.fetcher.fetch_stages("test-job", 123)

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["name"], "Build")
        self.assertEqual(result[1]["name"], "Test")

    @patch('src.jenkins_log_fetcher.JenkinsLogFetcher._make_request')
    def test_fetch_stages_not_found(self, mock_make_request):
        """Test stages fetch when Blue Ocean API returns 404."""
        mock_response = Mock()
        mock_response.status_code = 404
        mock_make_request.return_value = mock_response

        result = self.fetcher.fetch_stages("test-job", 123)

        self.assertIsNone(result)

    @patch('src.jenkins_log_fetcher.JenkinsLogFetcher._make_request')
    def test_fetch_stages_request_exception(self, mock_make_request):
        """Test stages fetch when request fails."""
        mock_make_request.side_effect = requests.exceptions.RequestException("Connection error")

        result = self.fetcher.fetch_stages("test-job", 123)

        self.assertIsNone(result)

    @patch('src.jenkins_log_fetcher.JenkinsLogFetcher._make_request')
    def test_fetch_stage_log_success(self, mock_make_request):
        """Test successful stage log fetch."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "Stage log output"
        # Mock .json() to raise ValueError so it falls back to plain text
        mock_response.json.side_effect = ValueError("Not JSON")
        mock_make_request.return_value = mock_response

        result = self.fetcher.fetch_stage_log("test-job", 123, "stage-1")

        self.assertEqual(result, "Stage log output")

    @patch('src.jenkins_log_fetcher.JenkinsLogFetcher._make_request')
    def test_fetch_stage_log_not_found(self, mock_make_request):
        """Test stage log fetch when stage log returns 404."""
        mock_response = Mock()
        mock_response.status_code = 404
        mock_make_request.return_value = mock_response

        result = self.fetcher.fetch_stage_log("test-job", 123, "stage-1")

        self.assertIsNone(result)

    @patch('src.jenkins_log_fetcher.JenkinsLogFetcher._make_request')
    def test_fetch_stage_log_request_exception(self, mock_make_request):
        """Test stage log fetch when request fails."""
        mock_make_request.side_effect = requests.exceptions.RequestException("Connection error")

        result = self.fetcher.fetch_stage_log("test-job", 123, "stage-1")

        self.assertIsNone(result)

    @patch('requests.request')
    def test_make_request_success(self, mock_request):
        """Test _make_request with successful response."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_request.return_value = mock_response

        result = self.fetcher._make_request('GET', 'https://jenkins.example.com/api/json')

        self.assertEqual(result.status_code, 200)
        mock_request.assert_called_once()

    @patch('requests.request')
    def test_make_request_with_custom_timeout(self, mock_request):
        """Test _make_request with custom timeout."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_request.return_value = mock_response

        self.fetcher._make_request('GET', 'https://jenkins.example.com/api/json', timeout=60)

        # Verify timeout was passed correctly
        call_kwargs = mock_request.call_args[1]
        self.assertEqual(call_kwargs['timeout'], 60)

    @patch('requests.request')
    def test_make_request_raises_http_error(self, mock_request):
        """Test _make_request when HTTP error occurs."""
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError("500 Server Error")
        mock_request.return_value = mock_response

        with self.assertRaises(requests.exceptions.HTTPError):
            result = self.fetcher._make_request('GET', 'https://jenkins.example.com/api/json')
            result.raise_for_status()

    @patch('requests.head')
    @patch('requests.get')
    def test_fetch_console_log_tail_success(self, mock_get, mock_head):
        """Test fetch_console_log_tail with successful response."""
        # Mock HEAD request to get content length
        mock_head_response = Mock()
        mock_head_response.headers = {'Content-Length': '100000'}
        mock_head.return_value = mock_head_response

        # Mock GET request for tail
        mock_get_response = Mock()
        mock_get_response.text = "Line 1\nLine 2\nError occurred\n"
        mock_get_response.raise_for_status = Mock()
        mock_get.return_value = mock_get_response

        result = self.fetcher.fetch_console_log_tail("test-job", 123)

        self.assertIsInstance(result, str)
        self.assertIn("Error occurred", result)
        mock_head.assert_called_once()
        mock_get.assert_called_once()

    @patch('requests.head')
    def test_fetch_console_log_tail_empty_log(self, mock_head):
        """Test fetch_console_log_tail when log is empty."""
        mock_head_response = Mock()
        mock_head_response.headers = {'Content-Length': '0'}
        mock_head.return_value = mock_head_response

        result = self.fetcher.fetch_console_log_tail("test-job", 123)

        self.assertEqual(result, "")

    @patch('requests.head')
    def test_fetch_console_log_tail_failure(self, mock_head):
        """Test fetch_console_log_tail when request fails."""
        mock_head.side_effect = requests.exceptions.RequestException("Connection error")

        with self.assertRaises(requests.exceptions.RequestException):
            self.fetcher.fetch_console_log_tail("test-job", 123)

    @patch('requests.get')
    def test_fetch_console_log_streaming_success(self, mock_get):
        """Test fetch_console_log_streaming with successful response."""
        # Mock streaming response
        mock_response = Mock()
        mock_response.iter_lines.return_value = iter([
            "Line 1",
            "Line 2",
            "Error: Something failed",
            "Line 4"
        ])
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        result = self.fetcher.fetch_console_log_streaming("test-job", 123, max_lines=10)

        self.assertIsInstance(result, dict)
        self.assertIn('log_content', result)
        self.assertIn('truncated', result)
        self.assertIn('total_lines', result)
        self.assertEqual(result['total_lines'], 4)
        self.assertFalse(result['truncated'])
        self.assertIn("Error: Something failed", result['log_content'])

    @patch('requests.get')
    def test_fetch_console_log_streaming_truncated(self, mock_get):
        """Test fetch_console_log_streaming with truncation at max_lines."""
        # Mock streaming response with many lines
        mock_response = Mock()
        lines = [f"Line {i}" for i in range(1000)]
        mock_response.iter_lines.return_value = iter(lines)
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        result = self.fetcher.fetch_console_log_streaming("test-job", 123, max_lines=100)

        self.assertTrue(result['truncated'])
        self.assertEqual(result['total_lines'], 100)

    @patch('requests.get')
    def test_fetch_console_log_streaming_failure(self, mock_get):
        """Test fetch_console_log_streaming when request fails."""
        mock_get.side_effect = requests.exceptions.RequestException("Connection error")

        with self.assertRaises(requests.exceptions.RequestException):
            self.fetcher.fetch_console_log_streaming("test-job", 123)

    @patch('src.jenkins_log_fetcher.JenkinsLogFetcher.fetch_console_log_tail')
    @patch('src.log_error_extractor.LogErrorExtractor._find_error_lines')
    def test_fetch_console_log_hybrid_tail_with_errors(self, mock_find_errors, mock_tail):
        """Test fetch_console_log_hybrid when tail has errors."""
        mock_tail.return_value = "Line 1\nError: Failed\nLine 3"
        mock_find_errors.return_value = True  # Errors found in tail

        result = self.fetcher.fetch_console_log_hybrid("test-job", 123)

        self.assertEqual(result['method'], 'tail')
        self.assertIn('log_content', result)
        self.assertFalse(result['truncated'])
        mock_tail.assert_called_once()

    @patch('src.jenkins_log_fetcher.JenkinsLogFetcher.fetch_console_log_tail')
    @patch('src.jenkins_log_fetcher.JenkinsLogFetcher.fetch_console_log_streaming')
    @patch('src.log_error_extractor.LogErrorExtractor._find_error_lines')
    def test_fetch_console_log_hybrid_fallback_to_streaming(self, mock_find_errors, mock_streaming, mock_tail):
        """Test fetch_console_log_hybrid falls back to streaming when no errors in tail."""
        mock_tail.return_value = "Line 1\nLine 2\nLine 3"
        mock_find_errors.return_value = False  # No errors in tail
        mock_streaming.return_value = {
            'log_content': "Full log content",
            'truncated': False,
            'total_lines': 100
        }

        result = self.fetcher.fetch_console_log_hybrid("test-job", 123)

        self.assertEqual(result['method'], 'streaming')
        self.assertIn('log_content', result)
        mock_tail.assert_called_once()
        mock_streaming.assert_called_once()

    @patch('src.jenkins_log_fetcher.JenkinsLogFetcher.fetch_console_log_tail')
    @patch('src.jenkins_log_fetcher.JenkinsLogFetcher.fetch_console_log_streaming')
    def test_fetch_console_log_hybrid_tail_exception(self, mock_streaming, mock_tail):
        """Test fetch_console_log_hybrid when tail fetch fails."""
        mock_tail.side_effect = Exception("Tail fetch failed")
        mock_streaming.return_value = {
            'log_content': "Full log content",
            'truncated': False,
            'total_lines': 100
        }

        result = self.fetcher.fetch_console_log_hybrid("test-job", 123)

        self.assertEqual(result['method'], 'streaming')
        mock_streaming.assert_called_once()

    @patch('src.jenkins_log_fetcher.JenkinsLogFetcher._make_request')
    def test_fetch_stage_log_with_text_content(self, mock_make_request):
        """Test fetch_stage_log when it returns plain text (not JSON)."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("Not JSON")  # Not JSON
        mock_response.text = "Stage log content here"
        mock_make_request.return_value = mock_response

        result = self.fetcher.fetch_stage_log("test-job", 123, "stage-1")

        self.assertEqual(result, "Stage log content here")

    @patch('src.jenkins_log_fetcher.JenkinsLogFetcher._make_request')
    def test_fetch_stage_log_json_with_text_field(self, mock_make_request):
        """Test fetch_stage_log when JSON has 'text' field."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'text': 'Stage log from JSON text field', 'length': 30}
        mock_make_request.return_value = mock_response

        result = self.fetcher.fetch_stage_log("test-job", 123, "stage-1")

        self.assertEqual(result, "Stage log from JSON text field")

    @patch('src.jenkins_log_fetcher.JenkinsLogFetcher._make_request')
    def test_fetch_stage_log_json_without_useful_data(self, mock_make_request):
        """Test fetch_stage_log when JSON has no useful log data."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'nodeId': 'xyz', 'nodeStatus': 'SUCCESS'}  # No text or length
        mock_make_request.return_value = mock_response

        result = self.fetcher.fetch_stage_log("test-job", 123, "stage-1")

        self.assertIsNone(result)


if __name__ == '__main__':
    unittest.main()
