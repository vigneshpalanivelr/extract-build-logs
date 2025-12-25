"""
Unit tests for webhook_listener module.
"""

import unittest
from unittest.mock import patch, Mock
from typing import Dict, Any

from src.config_loader import Config


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

        # Manual jobs should be skipped
        self.assertFalse(result)

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

        # Skipped jobs should be skipped
        self.assertFalse(result)


if __name__ == '__main__':
    unittest.main()
