"""
Comprehensive tests for webhook_listener to achieve 100% coverage.
"""

import unittest
from unittest.mock import patch, Mock, MagicMock, call
import asyncio


def create_complete_pipeline_info(overrides=None):
    """Helper to create complete pipeline_info with all required fields."""
    base = {
        'pipeline_id': 123,
        'project_id': 456,
        'project_name': 'test/repo',
        'status': 'success',
        'ref': 'main',
        'sha': 'abc123',
        'source': 'push',
        'pipeline_type': 'main',
        'created_at': '2024-01-01T00:00:00Z',
        'finished_at': '2024-01-01T00:05:00Z',
        'duration': 300,
        'user': {'username': 'testuser'},
        'builds': []
    }
    if overrides:
        base.update(overrides)
    return base


class TestWebhookGitlabComprehensive(unittest.TestCase):
    """Comprehensive tests for GitLab webhook processing."""

    def setUp(self):
        """Set up test fixtures."""
        from fastapi.testclient import TestClient
        from src.webhook_listener import app
        self.client = TestClient(app)

    @patch('src.webhook_listener.monitor')
    @patch('src.webhook_listener.storage_manager')
    @patch('src.webhook_listener.pipeline_extractor')
    @patch('src.webhook_listener.config')
    def test_webhook_gitlab_complete_flow_with_metadata(self, mock_config, mock_extractor, mock_storage, mock_monitor):
        """Test complete GitLab webhook flow including metadata saving."""
        mock_config.webhook_secret = None
        mock_config.log_save_metadata_always = True

        # Complete pipeline info using helper
        pipeline_info = create_complete_pipeline_info()
        mock_extractor.extract_pipeline_info.return_value = pipeline_info
        mock_extractor.should_process_pipeline.return_value = True

        # Mock monitor
        from src.monitoring import RequestStatus
        mock_monitor.track_request.return_value = 1

        response = self.client.post(
            "/webhook/gitlab",
            json={"object_kind": "pipeline", "project": {"id": 456}},
            headers={"X-Gitlab-Event": "Pipeline Hook"}
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "success")

        # Note: metadata saving happens in background task which we don't wait for in endpoint tests
        # The background task is tested separately in TestBackgroundTasks

    @patch('src.webhook_listener.monitor')
    @patch('src.webhook_listener.pipeline_extractor')
    @patch('src.webhook_listener.config')
    def test_webhook_gitlab_empty_json(self, mock_config, mock_extractor, mock_monitor):
        """Test GitLab webhook with empty JSON payload."""
        mock_config.webhook_secret = None

        # Mock monitor to avoid None error
        from src.monitoring import RequestStatus
        mock_monitor.track_request.return_value = 1

        # Send empty JSON {}
        response = self.client.post(
            "/webhook/gitlab",
            json={},
            headers={"X-Gitlab-Event": "Pipeline Hook"}
        )

        # Empty JSON is rejected with 400
        self.assertEqual(response.status_code, 400)

    @patch('src.webhook_listener.monitor')
    @patch('src.webhook_listener.config')
    def test_webhook_gitlab_json_decode_error(self, mock_config, mock_monitor):
        """Test GitLab webhook with malformed JSON."""
        mock_config.webhook_secret = None

        response = self.client.post(
            "/webhook/gitlab",
            data="{invalid json",
            headers={
                "X-Gitlab-Event": "Pipeline Hook",
                "Content-Type": "application/json"
            }
        )

        self.assertEqual(response.status_code, 400)


class TestWebhookJenkinsComprehensive(unittest.TestCase):
    """Comprehensive tests for Jenkins webhook processing."""

    def setUp(self):
        """Set up test fixtures."""
        from fastapi.testclient import TestClient
        from src.webhook_listener import app
        self.client = TestClient(app)

    @patch('src.webhook_listener.api_poster')
    @patch('src.webhook_listener.storage_manager')
    @patch('src.webhook_listener.monitor')
    @patch('src.webhook_listener.jenkins_log_fetcher')
    @patch('src.webhook_listener.jenkins_extractor')
    @patch('src.webhook_listener.config')
    def test_webhook_jenkins_complete_flow_with_api_post(self, mock_config, mock_extractor,
                                                         mock_fetcher, mock_monitor, mock_storage, mock_api_poster):
        """Test complete Jenkins webhook flow with API posting."""
        mock_config.jenkins_enabled = True
        mock_config.jenkins_webhook_secret = None
        mock_config.api_post_enabled = True

        # Mock build info
        build_info = {
            'job_name': 'test-job',
            'build_number': 42,
            'status': 'SUCCESS',
            'build_url': 'http://jenkins/job/test-job/42'
        }
        mock_extractor.extract_webhook_data.return_value = build_info

        # Mock Jenkins fetcher
        mock_fetcher.fetch_build_info.return_value = {
            'duration': 120000,
            'timestamp': 1704067200000,
            'result': 'SUCCESS'
        }
        mock_fetcher.fetch_console_log.return_value = "Build log"
        mock_fetcher.fetch_stages.return_value = []

        # Mock extractor parsing
        mock_extractor.parse_console_log.return_value = []

        # Mock API poster
        mock_api_poster.post_jenkins_logs.return_value = True

        # Mock monitor
        from src.monitoring import RequestStatus
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

    @patch('src.webhook_listener.storage_manager')
    @patch('src.webhook_listener.monitor')
    @patch('src.webhook_listener.jenkins_log_fetcher')
    @patch('src.webhook_listener.jenkins_extractor')
    @patch('src.webhook_listener.config')
    def test_webhook_jenkins_metadata_fetch_error(self, mock_config, mock_extractor,
                                                   mock_fetcher, mock_monitor, mock_storage):
        """Test Jenkins webhook when metadata fetch fails."""
        mock_config.jenkins_enabled = True
        mock_config.jenkins_webhook_secret = None
        mock_config.api_post_enabled = False

        build_info = {
            'job_name': 'test-job',
            'build_number': 42,
            'status': 'FAILURE'
        }
        mock_extractor.extract_webhook_data.return_value = build_info

        # Metadata fetch fails
        mock_fetcher.fetch_build_info.side_effect = Exception("Metadata error")
        mock_fetcher.fetch_console_log.return_value = "Build log"
        mock_fetcher.fetch_stages.return_value = None

        mock_extractor.parse_console_log.return_value = []

        # Mock monitor
        from src.monitoring import RequestStatus
        mock_monitor.track_request.return_value = 1

        response = self.client.post(
            "/webhook/jenkins",
            json={
                "job_name": "test-job",
                "build_number": 42,
                "status": "FAILURE"
            }
        )

        # Should still succeed despite metadata error
        self.assertEqual(response.status_code, 200)

    @patch('src.webhook_listener.jenkins_log_fetcher')
    @patch('src.webhook_listener.jenkins_extractor')
    @patch('src.webhook_listener.config')
    def test_webhook_jenkins_console_log_error(self, mock_config, mock_extractor, mock_fetcher):
        """Test Jenkins webhook when console log fetch fails."""
        mock_config.jenkins_enabled = True
        mock_config.jenkins_webhook_secret = None

        build_info = {
            'job_name': 'test-job',
            'build_number': 42,
            'status': 'FAILURE'
        }
        mock_extractor.extract_webhook_data.return_value = build_info

        # Console log fetch fails
        mock_fetcher.fetch_build_info.return_value = {}
        mock_fetcher.fetch_console_log.side_effect = Exception("Console log error")

        response = self.client.post(
            "/webhook/jenkins",
            json={
                "job_name": "test-job",
                "build_number": 42,
                "status": "FAILURE"
            }
        )

        # Should handle error gracefully
        self.assertEqual(response.status_code, 500)


class TestBackgroundTasks(unittest.TestCase):
    """Test background task functions."""

    @patch('src.webhook_listener.time')
    @patch('src.webhook_listener.clear_request_id')
    @patch('src.webhook_listener.set_request_id')
    @patch('src.webhook_listener.api_poster')
    @patch('src.webhook_listener.storage_manager')
    @patch('src.webhook_listener.log_fetcher')
    @patch('src.webhook_listener.should_save_job_log')
    @patch('src.webhook_listener.should_save_pipeline_logs')
    @patch('src.webhook_listener.monitor')
    @patch('src.webhook_listener.config')
    def test_process_pipeline_event_success(self, mock_config, mock_monitor, mock_should_save_pipeline,
                                           mock_should_save_job, mock_log_fetcher, mock_storage,
                                           mock_api_poster, mock_set_req, mock_clear_req, mock_time):
        """Test process_pipeline_event background task success path."""
        from src.webhook_listener import process_pipeline_event
        from src.monitoring import RequestStatus

        # Mock config
        mock_config.log_save_metadata_always = True
        mock_config.api_post_enabled = True
        mock_config.api_post_save_to_file = False

        # Mock time
        mock_time.time.return_value = 1000.0

        # Mock filters
        mock_should_save_pipeline.return_value = True
        mock_should_save_job.return_value = True

        # Mock log fetcher
        mock_log_fetcher.fetch_pipeline_jobs.return_value = [
            {'id': 1, 'name': 'build', 'status': 'success'},
            {'id': 2, 'name': 'test', 'status': 'success'}
        ]
        mock_log_fetcher.fetch_job_log.side_effect = ['Build log', 'Test log']

        # Mock API posting
        mock_api_poster.post_pipeline_logs.return_value = True

        pipeline_info = create_complete_pipeline_info()

        # Execute
        process_pipeline_event(pipeline_info, db_request_id=1, req_id='test-123')

        # Verify
        mock_storage.save_pipeline_metadata.assert_called_once()
        self.assertEqual(mock_log_fetcher.fetch_job_log.call_count, 2)
        mock_api_poster.post_pipeline_logs.assert_called_once()
        mock_monitor.update_request.assert_called()

    @patch('src.webhook_listener.time')
    @patch('src.webhook_listener.clear_request_id')
    @patch('src.webhook_listener.set_request_id')
    @patch('src.webhook_listener.storage_manager')
    @patch('src.webhook_listener.log_fetcher')
    @patch('src.webhook_listener.should_save_job_log')
    @patch('src.webhook_listener.should_save_pipeline_logs')
    @patch('src.webhook_listener.monitor')
    @patch('src.webhook_listener.config')
    def test_process_pipeline_event_api_disabled(self, mock_config, mock_monitor, mock_should_save_pipeline,
                                                 mock_should_save_job, mock_log_fetcher, mock_storage,
                                                 mock_set_req, mock_clear_req, mock_time):
        """Test process_pipeline_event with API disabled (save to files)."""
        from src.webhook_listener import process_pipeline_event

        mock_config.log_save_metadata_always = True
        mock_config.api_post_enabled = False
        mock_time.time.return_value = 1000.0

        mock_should_save_pipeline.return_value = True
        mock_should_save_job.return_value = True

        mock_log_fetcher.fetch_pipeline_jobs.return_value = [
            {'id': 1, 'name': 'build', 'status': 'success'}
        ]
        mock_log_fetcher.fetch_job_log.return_value = 'Build log'

        pipeline_info = create_complete_pipeline_info()

        process_pipeline_event(pipeline_info, db_request_id=1, req_id='test-123')

        # Verify logs were saved to files
        mock_storage.save_log.assert_called()

    @patch('src.webhook_listener.time')
    @patch('src.webhook_listener.clear_request_id')
    @patch('src.webhook_listener.set_request_id')
    @patch('src.webhook_listener.log_fetcher')
    @patch('src.webhook_listener.should_save_pipeline_logs')
    @patch('src.webhook_listener.monitor')
    @patch('src.webhook_listener.config')
    def test_process_pipeline_event_retry_exhausted(self, mock_config, mock_monitor,
                                                     mock_should_save_pipeline, mock_log_fetcher,
                                                     mock_set_req, mock_clear_req, mock_time):
        """Test process_pipeline_event when retry is exhausted."""
        from src.webhook_listener import process_pipeline_event
        from src.error_handler import RetryExhaustedError
        from src.monitoring import RequestStatus

        mock_config.log_save_metadata_always = False
        mock_time.time.return_value = 1000.0

        mock_should_save_pipeline.return_value = True

        # Simulate retry exhausted
        test_exception = Exception("Network error")
        mock_log_fetcher.fetch_pipeline_jobs.side_effect = RetryExhaustedError(3, test_exception)

        pipeline_info = create_complete_pipeline_info()

        process_pipeline_event(pipeline_info, db_request_id=1, req_id='test-123')

        # Verify request was marked as failed
        calls = mock_monitor.update_request.call_args_list
        final_call = calls[-1]
        self.assertEqual(final_call[1]['status'], RequestStatus.FAILED)


class TestStartupShutdown(unittest.TestCase):
    """Test startup and shutdown event handlers."""

    @patch('src.webhook_listener.monitor')
    def test_startup_event(self, mock_monitor):
        """Test startup event handler."""
        import asyncio
        from src.webhook_listener import startup_event

        # Execute async startup event
        asyncio.run(startup_event())

        # Verify monitor was called
        mock_monitor.startup.assert_called_once()

    @patch('src.webhook_listener.monitor')
    def test_shutdown_event(self, mock_monitor):
        """Test shutdown event handler."""
        import asyncio
        from src.webhook_listener import shutdown_event

        # Execute async shutdown event
        asyncio.run(shutdown_event())

        # Verify monitor cleanup was called
        mock_monitor.cleanup.assert_called_once()


class TestProcessPipelineEventAdvanced(unittest.TestCase):
    """Advanced test cases for process_pipeline_event."""

    @patch('src.webhook_listener.time')
    @patch('src.webhook_listener.clear_request_id')
    @patch('src.webhook_listener.set_request_id')
    @patch('src.webhook_listener.api_poster')
    @patch('src.webhook_listener.storage_manager')
    @patch('src.webhook_listener.log_fetcher')
    @patch('src.webhook_listener.should_save_job_log')
    @patch('src.webhook_listener.should_save_pipeline_logs')
    @patch('src.webhook_listener.monitor')
    @patch('src.webhook_listener.config')
    def test_process_pipeline_event_api_failure_fallback_to_files(self, mock_config, mock_monitor,
                                                                   mock_should_save_pipeline, mock_should_save_job,
                                                                   mock_log_fetcher, mock_storage, mock_api_poster,
                                                                   mock_set_req, mock_clear_req, mock_time):
        """Test process_pipeline_event falls back to files when API posting fails."""
        from src.webhook_listener import process_pipeline_event

        mock_config.log_save_metadata_always = True
        mock_config.api_post_enabled = True
        mock_config.api_post_save_to_file = False
        mock_time.time.return_value = 1000.0

        mock_should_save_pipeline.return_value = True
        mock_should_save_job.return_value = True

        mock_log_fetcher.fetch_pipeline_jobs.return_value = [
            {'id': 1, 'name': 'build', 'status': 'success'}
        ]
        mock_log_fetcher.fetch_job_log.return_value = 'Build log'

        # API posting fails
        mock_api_poster.post_pipeline_logs.return_value = False

        pipeline_info = create_complete_pipeline_info()

        process_pipeline_event(pipeline_info, db_request_id=1, req_id='test-123')

        # Verify fallback to file storage occurred
        mock_storage.save_log.assert_called()

    @patch('src.webhook_listener.time')
    @patch('src.webhook_listener.clear_request_id')
    @patch('src.webhook_listener.set_request_id')
    @patch('src.webhook_listener.api_poster')
    @patch('src.webhook_listener.storage_manager')
    @patch('src.webhook_listener.log_fetcher')
    @patch('src.webhook_listener.should_save_job_log')
    @patch('src.webhook_listener.should_save_pipeline_logs')
    @patch('src.webhook_listener.monitor')
    @patch('src.webhook_listener.config')
    def test_process_pipeline_event_dual_mode(self, mock_config, mock_monitor, mock_should_save_pipeline,
                                               mock_should_save_job, mock_log_fetcher, mock_storage,
                                               mock_api_poster, mock_set_req, mock_clear_req, mock_time):
        """Test process_pipeline_event in dual mode (API + file storage)."""
        from src.webhook_listener import process_pipeline_event

        mock_config.log_save_metadata_always = True
        mock_config.api_post_enabled = True
        mock_config.api_post_save_to_file = True  # Dual mode
        mock_time.time.return_value = 1000.0

        mock_should_save_pipeline.return_value = True
        mock_should_save_job.return_value = True

        mock_log_fetcher.fetch_pipeline_jobs.return_value = [
            {'id': 1, 'name': 'build', 'status': 'success'}
        ]
        mock_log_fetcher.fetch_job_log.return_value = 'Build log'

        mock_api_poster.post_pipeline_logs.return_value = True

        pipeline_info = create_complete_pipeline_info()

        process_pipeline_event(pipeline_info, db_request_id=1, req_id='test-123')

        # Verify both API posting AND file storage occurred
        mock_api_poster.post_pipeline_logs.assert_called()
        mock_storage.save_log.assert_called()

    @patch('src.webhook_listener.time')
    @patch('src.webhook_listener.clear_request_id')
    @patch('src.webhook_listener.set_request_id')
    @patch('src.webhook_listener.storage_manager')
    @patch('src.webhook_listener.log_fetcher')
    @patch('src.webhook_listener.should_save_job_log')
    @patch('src.webhook_listener.should_save_pipeline_logs')
    @patch('src.webhook_listener.monitor')
    @patch('src.webhook_listener.config')
    def test_process_pipeline_event_with_job_filtering(self, mock_config, mock_monitor,
                                                        mock_should_save_pipeline, mock_should_save_job,
                                                        mock_log_fetcher, mock_storage,
                                                        mock_set_req, mock_clear_req, mock_time):
        """Test process_pipeline_event with job status filtering."""
        from src.webhook_listener import process_pipeline_event

        mock_config.log_save_metadata_always = True
        mock_config.api_post_enabled = False
        mock_time.time.return_value = 1000.0

        mock_should_save_pipeline.return_value = True

        # Filter: only save failed jobs
        def job_filter(job, _pipeline_info):
            return job['status'] == 'failed'
        mock_should_save_job.side_effect = job_filter

        mock_log_fetcher.fetch_pipeline_jobs.return_value = [
            {'id': 1, 'name': 'build', 'status': 'success'},
            {'id': 2, 'name': 'test', 'status': 'failed'},
            {'id': 3, 'name': 'deploy', 'status': 'success'}
        ]
        mock_log_fetcher.fetch_job_log.return_value = 'Test log'

        pipeline_info = create_complete_pipeline_info({'status': 'failed'})

        process_pipeline_event(pipeline_info, db_request_id=1, req_id='test-123')

        # Verify only 1 job log was fetched (the failed one)
        self.assertEqual(mock_log_fetcher.fetch_job_log.call_count, 1)
        mock_log_fetcher.fetch_job_log.assert_called_with(456, 2)

    @patch('src.webhook_listener.time')
    @patch('src.webhook_listener.clear_request_id')
    @patch('src.webhook_listener.set_request_id')
    @patch('src.webhook_listener.storage_manager')
    @patch('src.webhook_listener.should_save_pipeline_logs')
    @patch('src.webhook_listener.monitor')
    @patch('src.webhook_listener.config')
    def test_process_pipeline_event_filtered_out(self, mock_config, mock_monitor,
                                                  mock_should_save_pipeline, mock_storage,
                                                  mock_set_req, mock_clear_req, mock_time):
        """Test process_pipeline_event when pipeline is filtered out."""
        from src.webhook_listener import process_pipeline_event

        mock_config.log_save_metadata_always = True
        mock_time.time.return_value = 1000.0

        # Pipeline is filtered out
        mock_should_save_pipeline.return_value = False

        pipeline_info = create_complete_pipeline_info({'status': 'running'})

        process_pipeline_event(pipeline_info, db_request_id=1, req_id='test-123')

        # Metadata should still be saved
        mock_storage.save_pipeline_metadata.assert_called_once()

    @patch('src.webhook_listener.time')
    @patch('src.webhook_listener.clear_request_id')
    @patch('src.webhook_listener.set_request_id')
    @patch('src.webhook_listener.storage_manager')
    @patch('src.webhook_listener.should_save_pipeline_logs')
    @patch('src.webhook_listener.monitor')
    @patch('src.webhook_listener.config')
    def test_process_pipeline_event_filtered_no_metadata(self, mock_config, mock_monitor,
                                                         mock_should_save_pipeline, mock_storage,
                                                         mock_set_req, mock_clear_req, mock_time):
        """Test process_pipeline_event doesn't save metadata when disabled and filtered."""
        from src.webhook_listener import process_pipeline_event

        mock_config.log_save_metadata_always = False
        mock_time.time.return_value = 1000.0

        mock_should_save_pipeline.return_value = False

        pipeline_info = create_complete_pipeline_info({'status': 'running'})

        process_pipeline_event(pipeline_info, db_request_id=1, req_id='test-123')

        # Metadata should NOT be saved
        mock_storage.save_pipeline_metadata.assert_not_called()

    @patch('src.webhook_listener.time')
    @patch('src.webhook_listener.clear_request_id')
    @patch('src.webhook_listener.set_request_id')
    @patch('src.webhook_listener.storage_manager')
    @patch('src.webhook_listener.log_fetcher')
    @patch('src.webhook_listener.should_save_job_log')
    @patch('src.webhook_listener.should_save_pipeline_logs')
    @patch('src.webhook_listener.monitor')
    @patch('src.webhook_listener.config')
    def test_process_pipeline_event_job_log_fetch_error(self, mock_config, mock_monitor,
                                                         mock_should_save_pipeline, mock_should_save_job,
                                                         mock_log_fetcher, mock_storage,
                                                         mock_set_req, mock_clear_req, mock_time):
        """Test process_pipeline_event when individual job log fetch fails."""
        from src.webhook_listener import process_pipeline_event

        mock_config.log_save_metadata_always = True
        mock_config.api_post_enabled = False
        mock_time.time.return_value = 1000.0

        mock_should_save_pipeline.return_value = True
        mock_should_save_job.return_value = True

        mock_log_fetcher.fetch_pipeline_jobs.return_value = [
            {'id': 1, 'name': 'build', 'status': 'success'},
            {'id': 2, 'name': 'test', 'status': 'failed'}
        ]

        # First succeeds, second fails
        mock_log_fetcher.fetch_job_log.side_effect = [
            'Build log',
            Exception('Network error')
        ]

        pipeline_info = create_complete_pipeline_info({'status': 'failed'})

        process_pipeline_event(pipeline_info, db_request_id=1, req_id='test-123')

        # Verify both saves were attempted (error message for failed one)
        self.assertEqual(mock_storage.save_log.call_count, 2)

    @patch('src.webhook_listener.time')
    @patch('src.webhook_listener.clear_request_id')
    @patch('src.webhook_listener.set_request_id')
    @patch('src.webhook_listener.storage_manager')
    @patch('src.webhook_listener.log_fetcher')
    @patch('src.webhook_listener.should_save_job_log')
    @patch('src.webhook_listener.should_save_pipeline_logs')
    @patch('src.webhook_listener.monitor')
    @patch('src.webhook_listener.config')
    def test_process_pipeline_event_storage_error(self, mock_config, mock_monitor,
                                                   mock_should_save_pipeline, mock_should_save_job,
                                                   mock_log_fetcher, mock_storage,
                                                   mock_set_req, mock_clear_req, mock_time):
        """Test process_pipeline_event when file storage fails."""
        from src.webhook_listener import process_pipeline_event

        mock_config.log_save_metadata_always = True
        mock_config.api_post_enabled = False
        mock_time.time.return_value = 1000.0

        mock_should_save_pipeline.return_value = True
        mock_should_save_job.return_value = True

        mock_log_fetcher.fetch_pipeline_jobs.return_value = [
            {'id': 1, 'name': 'build', 'status': 'success'}
        ]
        mock_log_fetcher.fetch_job_log.return_value = 'Build log'

        # Storage fails
        mock_storage.save_log.side_effect = Exception('Disk full')

        pipeline_info = create_complete_pipeline_info()

        process_pipeline_event(pipeline_info, db_request_id=1, req_id='test-123')

        # Verify error was handled
        calls = mock_monitor.update_request.call_args_list
        # Check that error_count was incremented
        self.assertTrue(any('error_count' in str(call) for call in calls))

    @patch('src.webhook_listener.time')
    @patch('src.webhook_listener.clear_request_id')
    @patch('src.webhook_listener.set_request_id')
    @patch('src.webhook_listener.log_fetcher')
    @patch('src.webhook_listener.should_save_pipeline_logs')
    @patch('src.webhook_listener.monitor')
    @patch('src.webhook_listener.config')
    def test_process_pipeline_event_unexpected_exception(self, mock_config, mock_monitor,
                                                         mock_should_save_pipeline, mock_log_fetcher,
                                                         mock_set_req, mock_clear_req, mock_time):
        """Test process_pipeline_event handles unexpected exceptions."""
        from src.webhook_listener import process_pipeline_event
        from src.monitoring import RequestStatus

        mock_config.log_save_metadata_always = False
        mock_time.time.return_value = 1000.0

        mock_should_save_pipeline.return_value = True

        # Unexpected error
        mock_log_fetcher.fetch_pipeline_jobs.side_effect = RuntimeError("Unexpected error")

        pipeline_info = create_complete_pipeline_info()

        process_pipeline_event(pipeline_info, db_request_id=1, req_id='test-123')

        # Verify request was marked as failed
        calls = mock_monitor.update_request.call_args_list
        final_call = calls[-1]
        self.assertEqual(final_call[1]['status'], RequestStatus.FAILED)


if __name__ == "__main__":
    unittest.main()
