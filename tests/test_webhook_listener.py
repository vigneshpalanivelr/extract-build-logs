"""
Unit tests for webhook_listener module.
"""

import unittest
from unittest.mock import patch, Mock


class TestWebhookListener(unittest.TestCase):
    """Test cases for webhook_listener helper functions."""

    def setUp(self):
        """Set up test fixtures."""
        self.config_patcher = patch('src.webhook_listener.config')
        self.mock_config = self.config_patcher.start()

        # Set up default config values
        self.mock_config.webhook_secret = None
        self.mock_config.log_save_pipeline_status = ['all']
        self.mock_config.log_save_projects = []
        self.mock_config.log_exclude_projects = []
        self.mock_config.log_save_job_status = ['all']

        # Import after patching config
        from src.webhook_listener import validate_webhook_secret, should_save_pipeline_logs, should_save_job_log
        self.validate_webhook_secret = validate_webhook_secret
        self.should_save_pipeline_logs = should_save_pipeline_logs
        self.should_save_job_log = should_save_job_log

    def tearDown(self):
        """Clean up test fixtures."""
        self.config_patcher.stop()

    def test_validate_webhook_secret_no_secret_configured(self):
        """Test webhook validation when no secret is configured."""
        self.mock_config.webhook_secret = None

        result = self.validate_webhook_secret(b"test payload", "any-token")

        self.assertTrue(result)

    def test_validate_webhook_secret_valid_signature(self):
        """Test webhook validation with valid signature."""
        self.mock_config.webhook_secret = "test-secret-123"

        result = self.validate_webhook_secret(b"test payload", "test-secret-123")

        self.assertTrue(result)

    def test_validate_webhook_secret_invalid_signature(self):
        """Test webhook validation with invalid signature."""
        self.mock_config.webhook_secret = "test-secret-123"

        result = self.validate_webhook_secret(b"test payload", "wrong-secret")

        self.assertFalse(result)

    def test_validate_webhook_secret_missing_signature(self):
        """Test webhook validation when signature is missing."""
        self.mock_config.webhook_secret = "test-secret-123"

        result = self.validate_webhook_secret(b"test payload", None)

        self.assertFalse(result)

    def test_should_save_pipeline_logs_all_status(self):
        """Test pipeline log saving when status filter is 'all'."""
        self.mock_config.log_save_pipeline_status = ['all']
        self.mock_config.log_save_projects = []
        self.mock_config.log_exclude_projects = []

        pipeline_info = {
            'pipeline_id': 12345,
            'project_id': 123,
            'project_name': 'test/project',
            'status': 'success'
        }

        result = self.should_save_pipeline_logs(pipeline_info)

        self.assertTrue(result)

    def test_should_save_pipeline_logs_status_filter_match(self):
        """Test pipeline log saving when status matches filter."""
        self.mock_config.log_save_pipeline_status = ['failed', 'canceled']
        self.mock_config.log_save_projects = []
        self.mock_config.log_exclude_projects = []

        pipeline_info = {
            'pipeline_id': 12345,
            'project_id': 123,
            'project_name': 'test/project',
            'status': 'failed'
        }

        result = self.should_save_pipeline_logs(pipeline_info)

        self.assertTrue(result)

    def test_should_save_pipeline_logs_status_filter_no_match(self):
        """Test pipeline log saving when status doesn't match filter."""
        self.mock_config.log_save_pipeline_status = ['failed', 'canceled']
        self.mock_config.log_save_projects = []
        self.mock_config.log_exclude_projects = []

        pipeline_info = {
            'pipeline_id': 12345,
            'project_id': 123,
            'project_name': 'test/project',
            'status': 'success'
        }

        result = self.should_save_pipeline_logs(pipeline_info)

        self.assertFalse(result)

    def test_should_save_pipeline_logs_whitelist_match(self):
        """Test pipeline log saving when project is in whitelist."""
        self.mock_config.log_save_pipeline_status = ['all']
        self.mock_config.log_save_projects = ['123', '456']
        self.mock_config.log_exclude_projects = []

        pipeline_info = {
            'pipeline_id': 12345,
            'project_id': 123,
            'project_name': 'test/project',
            'status': 'success'
        }

        result = self.should_save_pipeline_logs(pipeline_info)

        self.assertTrue(result)

    def test_should_save_pipeline_logs_whitelist_no_match(self):
        """Test pipeline log saving when project is not in whitelist."""
        self.mock_config.log_save_pipeline_status = ['all']
        self.mock_config.log_save_projects = ['456', '789']
        self.mock_config.log_exclude_projects = []

        pipeline_info = {
            'pipeline_id': 12345,
            'project_id': 123,
            'project_name': 'test/project',
            'status': 'success'
        }

        result = self.should_save_pipeline_logs(pipeline_info)

        self.assertFalse(result)

    def test_should_save_pipeline_logs_blacklist_match(self):
        """Test pipeline log saving when project is in blacklist."""
        self.mock_config.log_save_pipeline_status = ['all']
        self.mock_config.log_save_projects = []
        self.mock_config.log_exclude_projects = ['123', '456']

        pipeline_info = {
            'pipeline_id': 12345,
            'project_id': 123,
            'project_name': 'test/project',
            'status': 'success'
        }

        result = self.should_save_pipeline_logs(pipeline_info)

        self.assertFalse(result)

    def test_should_save_pipeline_logs_blacklist_no_match(self):
        """Test pipeline log saving when project is not in blacklist."""
        self.mock_config.log_save_pipeline_status = ['all']
        self.mock_config.log_save_projects = []
        self.mock_config.log_exclude_projects = ['456', '789']

        pipeline_info = {
            'pipeline_id': 12345,
            'project_id': 123,
            'project_name': 'test/project',
            'status': 'success'
        }

        result = self.should_save_pipeline_logs(pipeline_info)

        self.assertTrue(result)

    def test_should_save_pipeline_logs_whitelist_overrides_blacklist(self):
        """Test that whitelist takes precedence over blacklist."""
        self.mock_config.log_save_pipeline_status = ['all']
        self.mock_config.log_save_projects = ['123']
        self.mock_config.log_exclude_projects = ['123']

        pipeline_info = {
            'pipeline_id': 12345,
            'project_id': 123,
            'project_name': 'test/project',
            'status': 'success'
        }

        result = self.should_save_pipeline_logs(pipeline_info)

        # Whitelist should win - blacklist is ignored when whitelist exists
        self.assertTrue(result)

    def test_should_save_job_log_all_status(self):
        """Test job log saving when status filter is 'all'."""
        self.mock_config.log_save_job_status = ['all']

        job_details = {
            'id': 456,
            'name': 'build',
            'status': 'success'
        }
        pipeline_info = {
            'pipeline_id': 12345,
            'project_id': 123
        }

        result = self.should_save_job_log(job_details, pipeline_info)

        self.assertTrue(result)

    def test_should_save_job_log_status_filter_match(self):
        """Test job log saving when status matches filter."""
        self.mock_config.log_save_job_status = ['failed', 'canceled']

        job_details = {
            'id': 456,
            'name': 'build',
            'status': 'failed'
        }
        pipeline_info = {
            'pipeline_id': 12345,
            'project_id': 123
        }

        result = self.should_save_job_log(job_details, pipeline_info)

        self.assertTrue(result)

    def test_should_save_job_log_status_filter_no_match(self):
        """Test job log saving when status doesn't match filter."""
        self.mock_config.log_save_job_status = ['failed', 'canceled']

        job_details = {
            'id': 456,
            'name': 'build',
            'status': 'success'
        }
        pipeline_info = {
            'pipeline_id': 12345,
            'project_id': 123
        }

        result = self.should_save_job_log(job_details, pipeline_info)

        self.assertFalse(result)

    def test_should_save_job_log_manual_job(self):
        """Test job log saving for manual jobs."""
        self.mock_config.log_save_job_status = ['all']

        job_details = {
            'id': 456,
            'name': 'deploy:manual',
            'status': 'manual'
        }
        pipeline_info = {
            'pipeline_id': 12345,
            'project_id': 123
        }

        result = self.should_save_job_log(job_details, pipeline_info)

        # With 'all' filter, manual jobs are saved
        self.assertTrue(result)

    def test_should_save_job_log_skipped_job(self):
        """Test job log saving for skipped jobs."""
        self.mock_config.log_save_job_status = ['all']

        job_details = {
            'id': 456,
            'name': 'deploy',
            'status': 'skipped'
        }
        pipeline_info = {
            'pipeline_id': 12345,
            'project_id': 123
        }

        result = self.should_save_job_log(job_details, pipeline_info)

        # With 'all' filter, skipped jobs are saved
        self.assertTrue(result)


class TestWebhookEndpoints(unittest.TestCase):
    """Test cases for FastAPI webhook endpoints."""

    def setUp(self):
        """Set up test fixtures."""
        # Import FastAPI TestClient and app
        from fastapi.testclient import TestClient
        from src.webhook_listener import app

        self.client = TestClient(app)

    def test_health_endpoint(self):
        """Test /health endpoint."""
        response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "healthy")
        self.assertEqual(data["service"], "gitlab-log-extractor")
        self.assertEqual(data["version"], "1.0.0")

    @patch('src.webhook_listener.token_manager')
    def test_api_token_endpoint_success(self, mock_token_manager):
        """Test /api/token endpoint with successful token generation."""
        # Mock token manager
        mock_tm = Mock()
        mock_tm.generate_token.return_value = "test-jwt-token-123"

        # Need to set the global token_manager
        from src import webhook_listener
        webhook_listener.token_manager = mock_tm

        response = self.client.post("/api/token", json={
            "subject": "gitlab_repo_123",
            "expires_in": 60
        })

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["token"], "test-jwt-token-123")
        self.assertEqual(data["subject"], "gitlab_repo_123")
        self.assertEqual(data["expires_in"], 60)

    def test_api_token_endpoint_no_token_manager(self):
        """Test /api/token endpoint when token_manager is not configured."""
        from src import webhook_listener
        webhook_listener.token_manager = None

        response = self.client.post("/api/token", json={
            "subject": "gitlab_repo_123"
        })

        # HTTPException with 503 gets caught and re-raised as 500
        self.assertEqual(response.status_code, 500)
        self.assertIn("Token generation failed", response.json()["detail"])

    def test_api_token_endpoint_missing_subject(self):
        """Test /api/token endpoint with missing subject."""
        response = self.client.post("/api/token", json={
            "expires_in": 60
        })

        # HTTPException with 400 gets caught and re-raised as 500
        self.assertEqual(response.status_code, 500)

    def test_api_token_endpoint_invalid_expires_in(self):
        """Test /api/token endpoint with invalid expires_in."""
        from src import webhook_listener
        mock_tm = Mock()
        webhook_listener.token_manager = mock_tm

        response = self.client.post("/api/token", json={
            "subject": "gitlab_repo_123",
            "expires_in": 9999  # Too large
        })

        # HTTPException with 400 gets caught and re-raised as 500
        self.assertEqual(response.status_code, 500)

    @patch('src.webhook_listener.monitor')
    @patch('src.webhook_listener.config')
    def test_webhook_gitlab_invalid_event_type(self, mock_config, mock_monitor):
        """Test /webhook/gitlab with non-pipeline event."""
        mock_config.webhook_secret = None

        # Mock monitor to avoid None error
        mock_monitor.track_request.return_value = 1

        response = self.client.post(
            "/webhook/gitlab",
            json={"test": "data"},
            headers={"X-Gitlab-Event": "Push Hook"}
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ignored")

    @patch('src.webhook_listener.config')
    def test_webhook_gitlab_auth_failure(self, mock_config):
        """Test /webhook/gitlab with authentication failure."""
        mock_config.webhook_secret = "secret-123"

        response = self.client.post(
            "/webhook/gitlab",
            json={"test": "data"},
            headers={
                "X-Gitlab-Event": "Pipeline Hook",
                "X-Gitlab-Token": "wrong-token"
            }
        )

        self.assertEqual(response.status_code, 401)

    @patch('src.webhook_listener.config')
    def test_webhook_jenkins_disabled(self, mock_config):
        """Test /webhook/jenkins when Jenkins integration is disabled."""
        mock_config.jenkins_enabled = False

        response = self.client.post(
            "/webhook/jenkins",
            json={"job_name": "test", "build_number": 1}
        )

        self.assertEqual(response.status_code, 503)
        self.assertIn("not enabled", response.json()["detail"]["message"])

    @patch('src.webhook_listener.storage_manager')
    def test_stats_endpoint(self, mock_storage):
        """Test /stats endpoint."""
        mock_storage.get_storage_stats.return_value = {
            "total_projects": 5,
            "total_pipelines": 20,
            "total_jobs": 100,
            "total_size_mb": 50.5
        }

        response = self.client.get("/stats")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["total_projects"], 5)
        self.assertEqual(data["total_pipelines"], 20)

    @patch('src.webhook_listener.monitor')
    def test_monitor_summary_endpoint(self, mock_monitor):
        """Test /monitor/summary endpoint."""
        mock_monitor.get_summary.return_value = {
            "time_period_hours": 24,
            "total_requests": 150,
            "success_rate": 95.5
        }

        response = self.client.get("/monitor/summary?hours=24")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["total_requests"], 150)

    @patch('src.webhook_listener.monitor')
    def test_monitor_recent_endpoint(self, mock_monitor):
        """Test /monitor/recent endpoint."""
        mock_monitor.get_recent_requests.return_value = [
            {"id": 1, "pipeline_id": 123},
            {"id": 2, "pipeline_id": 456}
        ]

        response = self.client.get("/monitor/recent?limit=50")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["requests"]), 2)
        self.assertEqual(data["count"], 2)

    @patch('src.webhook_listener.monitor')
    def test_monitor_pipeline_endpoint(self, mock_monitor):
        """Test /monitor/pipeline/{pipeline_id} endpoint."""
        mock_monitor.get_pipeline_requests.return_value = [
            {"id": 1, "status": "completed"}
        ]

        response = self.client.get("/monitor/pipeline/12345")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["pipeline_id"], 12345)
        self.assertEqual(len(data["requests"]), 1)

    @patch('src.webhook_listener.monitor')
    def test_monitor_export_csv_endpoint(self, mock_monitor):
        """Test /monitor/export/csv endpoint."""
        import tempfile
        import os

        # Create a temporary CSV file
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.csv') as f:
            f.write("id,pipeline_id,status\n")
            f.write("1,123,completed\n")
            temp_path = f.name

        # Mock export_to_csv to use our temp file
        def mock_export(path, hours=None):
            with open(temp_path, 'r') as src:
                with open(path, 'w') as dst:
                    dst.write(src.read())

        mock_monitor.export_to_csv.side_effect = mock_export

        try:
            response = self.client.get("/monitor/export/csv?hours=24")

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["content-type"], "text/csv; charset=utf-8")
        finally:
            # Clean up
            if os.path.exists(temp_path):
                os.remove(temp_path)


class TestWebhookEdgeCases(unittest.TestCase):
    """Test edge cases and error paths for webhook_listener."""

    def setUp(self):
        """Set up test fixtures."""
        from fastapi.testclient import TestClient
        from src.webhook_listener import app
        self.client = TestClient(app)

    @patch('src.webhook_listener.monitor')
    @patch('src.webhook_listener.config')
    def test_webhook_gitlab_general_exception(self, mock_config, mock_monitor):
        """Test GitLab webhook with general exception (covers lines 685-700)."""
        mock_config.webhook_secret = None

        # Make monitor.track_request raise a non-HTTPException error
        # This happens at line 539 when tracking ignored requests
        mock_monitor.track_request.side_effect = RuntimeError("Database connection lost")

        # Send a non-pipeline event to trigger the ignored request tracking
        response = self.client.post(
            "/webhook/gitlab",
            json={"object_kind": "push"},
            headers={"X-Gitlab-Event": "Push Hook"}  # Non-pipeline event
        )

        # Should get 500 with "Processing failed" message
        self.assertEqual(response.status_code, 500)
        response_data = response.json()
        self.assertIn("Processing failed", response_data["detail"]["message"])

    @patch('src.webhook_listener.token_manager')
    @patch('src.webhook_listener.monitor')
    @patch('src.webhook_listener.config')
    def test_api_token_endpoint_value_error(self, mock_config, mock_monitor, mock_token_mgr):
        """Test /api/token endpoint with ValueError (covers lines 454-455)."""
        mock_config.webhook_secret = None
        mock_token_mgr.generate_token.side_effect = ValueError("Invalid subject format")

        response = self.client.post(
            "/api/token",
            json={"subject": "invalid_format", "expires_in": 60}
        )

        self.assertEqual(response.status_code, 400)


class TestProcessJenkinsEdgeCases(unittest.TestCase):
    """Test edge cases for Jenkins processing."""

    @patch('src.webhook_listener.time')
    @patch('src.webhook_listener.clear_request_id')
    @patch('src.webhook_listener.set_request_id')
    @patch('src.webhook_listener.api_poster')
    @patch('src.webhook_listener.jenkins_log_fetcher')
    @patch('src.webhook_listener.storage_manager')
    @patch('src.webhook_listener.monitor')
    @patch('src.webhook_listener.config')
    def test_process_jenkins_build_api_post_fails(self, mock_config, mock_monitor,
                                                  mock_storage, mock_log_fetcher, mock_api_poster,
                                                  mock_set_req, mock_clear_req, mock_time):
        """Test Jenkins build processing when API post fails (covers lines 941-946)."""
        from src.webhook_listener import process_jenkins_build

        mock_config.api_post_enabled = True
        mock_config.log_save_metadata_always = False
        mock_time.time.return_value = 1000.0

        mock_log_fetcher.fetch_console_log.return_value = "Console log"
        mock_log_fetcher.extract_stages.return_value = [
            {'name': 'Build', 'status': 'SUCCESS'}
        ]

        # API post returns False (failure)
        mock_api_poster.post_jenkins_logs.return_value = False

        build_info = {
            'job_name': 'test-job',
            'build_number': 42,
            'status': 'SUCCESS',
            'url': 'https://jenkins.example.com/job/test-job/42/'
        }

        process_jenkins_build(build_info, db_request_id=1, req_id='test-123')

        # Should complete despite API failure
        mock_monitor.update_request.assert_called()

    @patch('src.webhook_listener.time')
    @patch('src.webhook_listener.clear_request_id')
    @patch('src.webhook_listener.set_request_id')
    @patch('src.webhook_listener.api_poster')
    @patch('src.webhook_listener.jenkins_log_fetcher')
    @patch('src.webhook_listener.monitor')
    @patch('src.webhook_listener.config')
    def test_process_jenkins_build_api_post_exception(self, mock_config, mock_monitor,
                                                      mock_log_fetcher, mock_api_poster,
                                                      mock_set_req, mock_clear_req, mock_time):
        """Test Jenkins build when API post raises exception (covers line 946)."""
        from src.webhook_listener import process_jenkins_build

        mock_config.api_post_enabled = True
        mock_time.time.return_value = 1000.0

        mock_log_fetcher.fetch_console_log.return_value = "Console log"
        mock_log_fetcher.extract_stages.return_value = [
            {'name': 'Build', 'status': 'SUCCESS'}
        ]

        # API post raises exception
        mock_api_poster.post_jenkins_logs.side_effect = RuntimeError("API error")

        build_info = {
            'job_name': 'test-job',
            'build_number': 42,
            'status': 'SUCCESS',
            'url': 'https://jenkins.example.com/job/test-job/42/'
        }

        process_jenkins_build(build_info, db_request_id=1, req_id='test-123')

        # Should complete despite exception
        mock_monitor.update_request.assert_called()

    @patch('src.webhook_listener.time')
    @patch('src.webhook_listener.clear_request_id')
    @patch('src.webhook_listener.set_request_id')
    @patch('src.webhook_listener.jenkins_log_fetcher')
    @patch('src.webhook_listener.monitor')
    @patch('src.webhook_listener.config')
    def test_process_jenkins_build_general_exception(self, mock_config, mock_monitor,
                                                     mock_log_fetcher, mock_set_req,
                                                     mock_clear_req, mock_time):
        """Test Jenkins build processing with general exception (covers lines 965-973)."""
        from src.monitoring import RequestStatus
        from src.webhook_listener import process_jenkins_build

        mock_config.api_post_enabled = False
        mock_time.time.return_value = 1000.0

        # Log fetcher raises exception (now using hybrid method)
        mock_log_fetcher.fetch_console_log_hybrid.side_effect = RuntimeError("Fetch failed")

        build_info = {
            'job_name': 'test-job',
            'build_number': 42,
            'status': 'SUCCESS',
            'url': 'https://jenkins.example.com/job/test-job/42/'
        }

        process_jenkins_build(build_info, db_request_id=1, req_id='test-123')

        # Should mark as failed
        calls = mock_monitor.update_request.call_args_list
        final_call = calls[-1]
        self.assertEqual(final_call[1]['status'], RequestStatus.FAILED)


class TestProcessPipelineEdgeCases(unittest.TestCase):
    """Test edge cases for pipeline processing."""

    @patch('src.webhook_listener.time')
    @patch('src.webhook_listener.clear_request_id')
    @patch('src.webhook_listener.set_request_id')
    @patch('src.webhook_listener.api_poster')
    @patch('src.webhook_listener.log_fetcher')
    @patch('src.webhook_listener.should_save_pipeline_logs')
    @patch('src.webhook_listener.monitor')
    @patch('src.webhook_listener.config')
    def test_process_pipeline_api_post_unexpected_exception(self, mock_config, mock_monitor,
                                                            mock_should_save, mock_log_fetcher,
                                                            mock_api_poster, mock_set_req,
                                                            mock_clear_req, mock_time):
        """Test pipeline processing with unexpected API exception (covers lines 1166-1168)."""
        from src.webhook_listener import process_pipeline_event
        from tests.test_webhook_background_tasks import create_complete_pipeline_info

        mock_config.api_post_enabled = True
        mock_config.log_save_metadata_always = False
        mock_time.time.return_value = 1000.0

        mock_should_save.return_value = True

        mock_log_fetcher.fetch_pipeline_jobs.return_value = [
            {'id': 1, 'name': 'build', 'status': 'success'}
        ]
        mock_log_fetcher.fetch_job_log.return_value = 'Build log'

        # API poster raises unexpected exception
        mock_api_poster.post_pipeline_logs.side_effect = RuntimeError("Unexpected error")

        pipeline_info = create_complete_pipeline_info()

        process_pipeline_event(pipeline_info, db_request_id=1, req_id='test-123')

        # Should complete and save to files as fallback
        mock_monitor.update_request.assert_called()

    @patch('src.webhook_listener.time')
    @patch('src.webhook_listener.clear_request_id')
    @patch('src.webhook_listener.set_request_id')
    @patch('src.webhook_listener.api_poster')
    @patch('src.webhook_listener.log_fetcher')
    @patch('src.webhook_listener.should_save_pipeline_logs')
    @patch('src.webhook_listener.pipeline_extractor')
    @patch('src.webhook_listener.monitor')
    @patch('src.webhook_listener.config')
    def test_process_pipeline_with_skipped_jobs(self, mock_config, mock_monitor,
                                                mock_extractor, mock_should_save,
                                                mock_log_fetcher, mock_api_poster,
                                                mock_set_req, mock_clear_req, mock_time):
        """Test pipeline processing with skipped jobs (covers lines 1265-1270)."""
        from src.webhook_listener import process_pipeline_event
        from tests.test_webhook_background_tasks import create_complete_pipeline_info

        mock_config.api_post_enabled = False
        mock_config.log_save_metadata_always = False
        mock_time.time.return_value = 1000.0

        mock_should_save.return_value = False  # Skip jobs due to filtering

        # Create pipeline info with multiple jobs
        pipeline_info = create_complete_pipeline_info()
        pipeline_info['jobs'] = [
            {'id': 1, 'name': 'build', 'status': 'success', 'stage': 'build'},
            {'id': 2, 'name': 'test', 'status': 'failed', 'stage': 'test'},
            {'id': 3, 'name': 'deploy', 'status': 'skipped', 'stage': 'deploy'}
        ]

        mock_extractor.get_pipeline_summary.return_value = "Pipeline summary"

        process_pipeline_event(pipeline_info, db_request_id=1, req_id='test-123')

        # Should log skipped jobs
        mock_monitor.update_request.assert_called()

    @patch('src.webhook_listener.time')
    @patch('src.webhook_listener.clear_request_id')
    @patch('src.webhook_listener.set_request_id')
    @patch('src.webhook_listener.log_fetcher')
    @patch('src.webhook_listener.should_save_pipeline_logs')
    @patch('src.webhook_listener.monitor')
    @patch('src.webhook_listener.config')
    def test_process_pipeline_retry_exhausted(self, mock_config, mock_monitor,
                                              mock_should_save, mock_log_fetcher,
                                              mock_set_req, mock_clear_req, mock_time):
        """Test pipeline processing with RetryExhaustedError (covers lines 1302-1321)."""
        from src.webhook_listener import process_pipeline_event
        from src.error_handler import RetryExhaustedError
        from src.monitoring import RequestStatus
        from tests.test_webhook_background_tasks import create_complete_pipeline_info

        mock_config.api_post_enabled = False
        mock_config.log_save_metadata_always = False
        mock_time.time.return_value = 1000.0

        mock_should_save.return_value = True

        # Make log fetcher raise RetryExhaustedError
        last_exc = RuntimeError("Connection failed")
        mock_log_fetcher.fetch_pipeline_jobs.side_effect = RetryExhaustedError(attempts=3, last_exception=last_exc)

        pipeline_info = create_complete_pipeline_info()

        process_pipeline_event(pipeline_info, db_request_id=1, req_id='test-123')

        # Should update monitoring with FAILED status
        calls = mock_monitor.update_request.call_args_list
        final_call = calls[-1]
        self.assertEqual(final_call[1]['status'], RequestStatus.FAILED)
        self.assertIn("attempts", final_call[1]['error_message'].lower())


class TestJenkinsWebhookEdgeCases(unittest.TestCase):
    """Test edge cases for Jenkins webhook endpoint."""

    @patch('src.webhook_listener.jenkins_log_fetcher')
    @patch('src.webhook_listener.jenkins_extractor')
    @patch('src.webhook_listener.monitor')
    @patch('src.webhook_listener.config')
    def test_jenkins_webhook_empty_payload(self, mock_config, mock_monitor,
                                           mock_jenkins_extractor, mock_jenkins_log_fetcher):
        """Test Jenkins webhook with empty payload (covers line 779)."""
        from fastapi.testclient import TestClient
        from src.webhook_listener import app
        from unittest.mock import MagicMock

        client = TestClient(app)
        mock_config.webhook_secret = None
        mock_config.jenkins_enabled = True
        mock_config.jenkins_webhook_secret = None  # Disable authentication

        # Mock Jenkins components to be available
        mock_jenkins_extractor.return_value = MagicMock()
        mock_jenkins_log_fetcher.return_value = MagicMock()

        # Send empty JSON object
        response = client.post(
            "/webhook/jenkins",
            json={},
            headers={"Content-Type": "application/json"}
        )

        # Should return 400 for empty payload
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json()["detail"]["status"])


if __name__ == "__main__":
    unittest.main()
