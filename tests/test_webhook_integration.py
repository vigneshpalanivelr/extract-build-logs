"""
Integration tests for webhook_listener endpoints and background tasks.
"""

import unittest
from unittest.mock import patch, Mock, MagicMock
import json

class TestWebhookGitlabIntegration(unittest.TestCase):
    """Integration tests for GitLab webhook endpoint."""

    def setUp(self):
        """Set up test fixtures."""
        from fastapi.testclient import TestClient
        from src.webhook_listener import app
        self.client = TestClient(app)

    @patch('src.webhook_listener.pipeline_extractor')
    @patch('src.webhook_listener.monitor')
    @patch('src.webhook_listener.config')
    def test_webhook_gitlab_pipeline_not_ready(self, mock_config, mock_monitor, mock_extractor):
        """Test GitLab webhook when pipeline is not ready for processing."""
        mock_config.webhook_secret = None

        # Mock pipeline extractor
        mock_extractor.extract_pipeline_info.return_value = {
            'pipeline_id': 123,
            'project_id': 456,
            'project_name': 'test/repo',
            'status': 'running'
        }
        mock_extractor.should_process_pipeline.return_value = False

        # Mock monitor
        mock_monitor.track_request.return_value = 1

        response = self.client.post(
            "/webhook/gitlab",
            json={"object_kind": "pipeline", "project": {"id": 456}},
            headers={"X-Gitlab-Event": "Pipeline Hook"}
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "skipped")
        self.assertEqual(data["pipeline_id"], 123)

    @patch('src.webhook_listener.pipeline_extractor')
    @patch('src.webhook_listener.monitor')
    @patch('src.webhook_listener.config')
    @patch('src.webhook_listener.BackgroundTasks')
    def test_webhook_gitlab_pipeline_queued(self, mock_bg, mock_config, mock_monitor, mock_extractor):
        """Test GitLab webhook queues pipeline for processing."""
        mock_config.webhook_secret = None

        # Mock pipeline extractor
        mock_extractor.extract_pipeline_info.return_value = {
            'pipeline_id': 123,
            'project_id': 456,
            'project_name': 'test/repo',
            'status': 'success',
            'builds': []
        }
        mock_extractor.should_process_pipeline.return_value = True

        # Mock monitor
        mock_monitor.track_request.return_value = 1

        response = self.client.post(
            "/webhook/gitlab",
            json={"object_kind": "pipeline", "project": {"id": 456}},
            headers={"X-Gitlab-Event": "Pipeline Hook"}
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["pipeline_id"], 123)

    @patch('src.webhook_listener.config')
    def test_webhook_gitlab_invalid_json(self, mock_config):
        """Test GitLab webhook with invalid JSON."""
        mock_config.webhook_secret = None

        response = self.client.post(
            "/webhook/gitlab",
            data="not json",
            headers={
                "X-Gitlab-Event": "Pipeline Hook",
                "Content-Type": "application/json"
            }
        )

        self.assertEqual(response.status_code, 400)

    @patch('src.webhook_listener.pipeline_extractor')
    @patch('src.webhook_listener.config')
    def test_webhook_gitlab_extraction_error(self, mock_config, mock_extractor):
        """Test GitLab webhook when pipeline extraction fails."""
        mock_config.webhook_secret = None
        mock_extractor.extract_pipeline_info.side_effect = Exception("Extraction failed")

        response = self.client.post(
            "/webhook/gitlab",
            json={"object_kind": "pipeline"},
            headers={"X-Gitlab-Event": "Pipeline Hook"}
        )

        self.assertEqual(response.status_code, 500)


class TestWebhookJenkinsIntegration(unittest.TestCase):
    """Integration tests for Jenkins webhook endpoint."""

    def setUp(self):
        """Set up test fixtures."""
        from fastapi.testclient import TestClient
        from src.webhook_listener import app
        self.client = TestClient(app)

    @patch('src.webhook_listener.jenkins_extractor')
    @patch('src.webhook_listener.jenkins_log_fetcher')
    @patch('src.webhook_listener.monitor')
    @patch('src.webhook_listener.config')
    def test_webhook_jenkins_success(self, mock_config, mock_monitor, mock_fetcher, mock_extractor):
        """Test Jenkins webhook successful processing."""
        mock_config.jenkins_enabled = True
        mock_config.jenkins_webhook_secret = None

        # Mock extractor
        mock_extractor.extract_webhook_data.return_value = {
            'job_name': 'test-job',
            'build_number': 42,
            'status': 'SUCCESS'
        }

        # Mock monitor
        mock_monitor.track_request.return_value = 1

        response = self.client.post(
            "/webhook/jenkins",
            json={
                "job_name": "test-job",
                "build_number": 42,
                "status": "SUCCESS"
            }
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["job_name"], "test-job")
        self.assertEqual(data["build_number"], 42)

    @patch('src.webhook_listener.config')
    def test_webhook_jenkins_auth_required(self, mock_config):
        """Test Jenkins webhook with authentication required but not provided."""
        mock_config.jenkins_enabled = True
        mock_config.jenkins_webhook_secret = "secret-123"

        response = self.client.post(
            "/webhook/jenkins",
            json={"job_name": "test"}
        )

        self.assertEqual(response.status_code, 401)

    @patch('src.webhook_listener.config')
    def test_webhook_jenkins_auth_invalid(self, mock_config):
        """Test Jenkins webhook with invalid authentication."""
        mock_config.jenkins_enabled = True
        mock_config.jenkins_webhook_secret = "secret-123"

        response = self.client.post(
            "/webhook/jenkins",
            json={"job_name": "test"},
            headers={"X-Jenkins-Token": "wrong-secret"}
        )

        self.assertEqual(response.status_code, 401)

    @patch('src.webhook_listener.jenkins_extractor')
    @patch('src.webhook_listener.jenkins_log_fetcher')
    @patch('src.webhook_listener.config')
    def test_webhook_jenkins_extraction_error(self, mock_config, mock_fetcher, mock_extractor):
        """Test Jenkins webhook when extraction fails."""
        mock_config.jenkins_enabled = True
        mock_config.jenkins_webhook_secret = None
        mock_extractor.extract_webhook_data.side_effect = ValueError("Invalid payload")

        response = self.client.post(
            "/webhook/jenkins",
            json={"bad": "data"}
        )

        self.assertEqual(response.status_code, 400)

    @patch('src.webhook_listener.config')
    def test_webhook_jenkins_invalid_json(self, mock_config):
        """Test Jenkins webhook with invalid JSON."""
        mock_config.jenkins_enabled = True
        mock_config.jenkins_webhook_secret = None

        response = self.client.post(
            "/webhook/jenkins",
            data="not json",
            headers={"Content-Type": "application/json"}
        )

        self.assertEqual(response.status_code, 400)


class TestMiddleware(unittest.TestCase):
    """Test cases for HTTP middleware."""

    def setUp(self):
        """Set up test fixtures."""
        from fastapi.testclient import TestClient
        from src.webhook_listener import app
        self.client = TestClient(app)

    def test_middleware_logs_request(self):
        """Test that middleware logs HTTP requests."""
        # Make a request - middleware should log it
        response = self.client.get("/health")

        # Should complete successfully
        self.assertEqual(response.status_code, 200)
        # Middleware logging happens automatically, difficult to assert
        # but this covers the code path


class TestErrorHandling(unittest.TestCase):
    """Test error handling in endpoints."""

    def setUp(self):
        """Set up test fixtures."""
        from fastapi.testclient import TestClient
        from src.webhook_listener import app
        self.client = TestClient(app)

    @patch('src.webhook_listener.storage_manager')
    def test_stats_endpoint_error(self, mock_storage):
        """Test /stats endpoint when storage_manager raises error."""
        mock_storage.get_storage_stats.side_effect = Exception("Database error")

        response = self.client.get("/stats")

        self.assertEqual(response.status_code, 500)

    @patch('src.webhook_listener.monitor')
    def test_monitor_summary_error(self, mock_monitor):
        """Test /monitor/summary endpoint error handling."""
        mock_monitor.get_summary.side_effect = Exception("Monitor error")

        response = self.client.get("/monitor/summary")

        self.assertEqual(response.status_code, 500)

    @patch('src.webhook_listener.monitor')
    def test_monitor_recent_error(self, mock_monitor):
        """Test /monitor/recent endpoint error handling."""
        mock_monitor.get_recent_requests.side_effect = Exception("Monitor error")

        response = self.client.get("/monitor/recent")

        self.assertEqual(response.status_code, 500)

    @patch('src.webhook_listener.monitor')
    def test_monitor_pipeline_error(self, mock_monitor):
        """Test /monitor/pipeline endpoint error handling."""
        mock_monitor.get_pipeline_requests.side_effect = Exception("Monitor error")

        response = self.client.get("/monitor/pipeline/123")

        self.assertEqual(response.status_code, 500)

    @patch('src.webhook_listener.monitor')
    def test_monitor_export_csv_error(self, mock_monitor):
        """Test /monitor/export/csv endpoint error handling."""
        mock_monitor.export_to_csv.side_effect = Exception("Export error")

        response = self.client.get("/monitor/export/csv")

        self.assertEqual(response.status_code, 500)


if __name__ == "__main__":
    unittest.main()
