"""
Tests for webhook_listener initialization functions to achieve 100% coverage.
"""

import unittest
from unittest.mock import patch, MagicMock, call
import sys
from pathlib import Path
import tempfile

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestInitApp(unittest.TestCase):
    """Test cases for init_app function."""

    @patch('src.webhook_listener.TokenManager')
    @patch('src.webhook_listener.JenkinsLogFetcher')
    @patch('src.webhook_listener.JenkinsExtractor')
    @patch('src.webhook_listener.ApiPoster')
    @patch('src.webhook_listener.PipelineMonitor')
    @patch('src.webhook_listener.StorageManager')
    @patch('src.webhook_listener.LogFetcher')
    @patch('src.webhook_listener.PipelineExtractor')
    @patch('src.webhook_listener.setup_logging')
    @patch('src.webhook_listener.ConfigLoader')
    def test_init_app_with_bfa_secret_key(self, mock_config_loader, mock_setup_logging,
                                          mock_pipeline_extractor, mock_log_fetcher,
                                          mock_storage_manager, mock_monitor,
                                          mock_api_poster, mock_jenkins_extractor,
                                          mock_jenkins_log_fetcher, mock_token_manager):
        """Test init_app with BFA_SECRET_KEY configured (covers lines 132-231)."""
        from src.webhook_listener import init_app

        # Create temp directory for testing
        temp_dir = tempfile.mkdtemp()

        # Mock config
        mock_config = MagicMock()
        mock_config.log_output_dir = temp_dir
        mock_config.log_level = "INFO"
        mock_config.gitlab_url = "https://gitlab.example.com"
        mock_config.webhook_port = 8000
        mock_config.retry_attempts = 3
        mock_config.gitlab_token = "test-token"
        mock_config.bfa_host = None
        mock_config.bfa_secret_key = "secret123"
        mock_config.api_post_enabled = True
        mock_config.api_post_url = "https://api.example.com"
        mock_config.api_post_timeout = 30
        mock_config.api_post_retry_enabled = True
        mock_config.api_post_save_to_file = False
        mock_config.jenkins_enabled = False

        mock_config_loader.load.return_value = mock_config

        # Call init_app
        init_app()

        # Verify all components were initialized
        mock_config_loader.load.assert_called_once()
        mock_config_loader.validate.assert_called_once_with(mock_config)
        mock_setup_logging.assert_called_once_with(log_dir=temp_dir, log_level="INFO")
        mock_pipeline_extractor.assert_called_once()
        mock_log_fetcher.assert_called_once_with(mock_config)
        mock_storage_manager.assert_called_once_with(temp_dir)
        mock_monitor.assert_called_once_with(f"{temp_dir}/monitoring.db")
        mock_token_manager.assert_called_once_with(secret_key="secret123")
        mock_api_poster.assert_called_once_with(mock_config)

    @patch('src.webhook_listener.JenkinsLogFetcher')
    @patch('src.webhook_listener.JenkinsExtractor')
    @patch('src.webhook_listener.ApiPoster')
    @patch('src.webhook_listener.PipelineMonitor')
    @patch('src.webhook_listener.StorageManager')
    @patch('src.webhook_listener.LogFetcher')
    @patch('src.webhook_listener.PipelineExtractor')
    @patch('src.webhook_listener.setup_logging')
    @patch('src.webhook_listener.ConfigLoader')
    def test_init_app_with_bfa_host_only(self, mock_config_loader, mock_setup_logging,
                                         mock_pipeline_extractor, mock_log_fetcher,
                                         mock_storage_manager, mock_monitor,
                                         mock_api_poster, mock_jenkins_extractor,
                                         mock_jenkins_log_fetcher):
        """Test init_app with only BFA_HOST configured (covers lines 191-194)."""
        from src.webhook_listener import init_app

        temp_dir = tempfile.mkdtemp()
        mock_config = MagicMock()
        mock_config.log_output_dir = temp_dir
        mock_config.log_level = "INFO"
        mock_config.gitlab_url = "https://gitlab.example.com"
        mock_config.webhook_port = 8000
        mock_config.retry_attempts = 3
        mock_config.gitlab_token = "test-token"
        mock_config.bfa_host = "https://bfa.example.com"
        mock_config.bfa_secret_key = None
        mock_config.api_post_enabled = False
        mock_config.jenkins_enabled = False

        mock_config_loader.load.return_value = mock_config

        init_app()

        # Verify components were initialized
        mock_config_loader.load.assert_called_once()
        # API poster should not be initialized when disabled
        mock_api_poster.assert_not_called()

    @patch('src.webhook_listener.JenkinsLogFetcher')
    @patch('src.webhook_listener.JenkinsExtractor')
    @patch('src.webhook_listener.PipelineMonitor')
    @patch('src.webhook_listener.StorageManager')
    @patch('src.webhook_listener.LogFetcher')
    @patch('src.webhook_listener.PipelineExtractor')
    @patch('src.webhook_listener.setup_logging')
    @patch('src.webhook_listener.ConfigLoader')
    def test_init_app_no_bfa_config(self, mock_config_loader, mock_setup_logging,
                                    mock_pipeline_extractor, mock_log_fetcher,
                                    mock_storage_manager, mock_monitor,
                                    mock_jenkins_extractor, mock_jenkins_log_fetcher):
        """Test init_app with no BFA configuration (covers lines 195-198)."""
        from src.webhook_listener import init_app

        temp_dir = tempfile.mkdtemp()
        mock_config = MagicMock()
        mock_config.log_output_dir = temp_dir
        mock_config.log_level = "DEBUG"
        mock_config.gitlab_url = "https://gitlab.example.com"
        mock_config.webhook_port = 8000
        mock_config.retry_attempts = 3
        mock_config.gitlab_token = "test-token"
        mock_config.bfa_host = None
        mock_config.bfa_secret_key = None
        mock_config.api_post_enabled = False
        mock_config.jenkins_enabled = False

        mock_config_loader.load.return_value = mock_config

        init_app()

        # Verify components were initialized
        mock_pipeline_extractor.assert_called_once()

    @patch('src.webhook_listener.JenkinsLogFetcher')
    @patch('src.webhook_listener.JenkinsExtractor')
    @patch('src.webhook_listener.PipelineMonitor')
    @patch('src.webhook_listener.StorageManager')
    @patch('src.webhook_listener.LogFetcher')
    @patch('src.webhook_listener.PipelineExtractor')
    @patch('src.webhook_listener.setup_logging')
    @patch('src.webhook_listener.ConfigLoader')
    def test_init_app_with_jenkins_enabled(self, mock_config_loader, mock_setup_logging,
                                           mock_pipeline_extractor, mock_log_fetcher,
                                           mock_storage_manager, mock_monitor,
                                           mock_jenkins_extractor, mock_jenkins_log_fetcher):
        """Test init_app with Jenkins enabled (covers lines 214-220)."""
        from src.webhook_listener import init_app

        temp_dir = tempfile.mkdtemp()
        mock_config = MagicMock()
        mock_config.log_output_dir = temp_dir
        mock_config.log_level = "INFO"
        mock_config.gitlab_url = "https://gitlab.example.com"
        mock_config.webhook_port = 8000
        mock_config.retry_attempts = 3
        mock_config.gitlab_token = "test-token"
        mock_config.bfa_host = None
        mock_config.bfa_secret_key = None
        mock_config.api_post_enabled = False
        mock_config.jenkins_enabled = True
        mock_config.jenkins_url = "https://jenkins.example.com"
        mock_config.jenkins_user = "testuser"

        mock_config_loader.load.return_value = mock_config

        init_app()

        # Verify Jenkins components were initialized
        mock_jenkins_extractor.assert_called_once()
        mock_jenkins_log_fetcher.assert_called_once_with(mock_config)

    @patch('src.webhook_listener.sys.exit')
    @patch('src.webhook_listener.ConfigLoader')
    def test_init_app_config_load_failure(self, mock_config_loader, mock_exit):
        """Test init_app when config loading fails (covers lines 229-231)."""
        from src.webhook_listener import init_app

        # Make config loading fail
        mock_config_loader.load.side_effect = Exception("Config load failed")

        init_app()

        # Should call sys.exit(1)
        mock_exit.assert_called_once_with(1)


class TestMainFunction(unittest.TestCase):
    """Test cases for main function."""

    @patch('src.webhook_listener.uvicorn.run')
    @patch('src.webhook_listener.init_app')
    @patch('src.webhook_listener.config')
    def test_main_normal_execution(self, mock_config, mock_init_app, mock_uvicorn_run):
        """Test main function normal execution (covers lines 1491-1509)."""
        from src.webhook_listener import main

        mock_config.webhook_port = 8000
        mock_config.log_level = "INFO"

        main()

        # Verify init_app was called
        mock_init_app.assert_called_once()

        # Verify uvicorn.run was called
        mock_uvicorn_run.assert_called_once()
        call_args = mock_uvicorn_run.call_args
        self.assertEqual(call_args[1]['host'], '0.0.0.0')
        self.assertEqual(call_args[1]['port'], 8000)
        self.assertEqual(call_args[1]['log_level'], 'info')
        self.assertEqual(call_args[1]['access_log'], False)

    @patch('src.webhook_listener.uvicorn.run')
    @patch('src.webhook_listener.init_app')
    @patch('src.webhook_listener.config')
    def test_main_keyboard_interrupt(self, mock_config, mock_init_app, mock_uvicorn_run):
        """Test main function with KeyboardInterrupt (covers lines 1510-1511)."""
        from src.webhook_listener import main

        mock_config.webhook_port = 8000
        mock_config.log_level = "INFO"
        mock_uvicorn_run.side_effect = KeyboardInterrupt()

        # Should not raise, just handle gracefully
        main()

        mock_init_app.assert_called_once()

    @patch('src.webhook_listener.uvicorn.run')
    @patch('src.webhook_listener.init_app')
    @patch('src.webhook_listener.config')
    def test_main_unexpected_exception(self, mock_config, mock_init_app, mock_uvicorn_run):
        """Test main function with unexpected exception (covers lines 1512-1513)."""
        from src.webhook_listener import main

        mock_config.webhook_port = 8000
        mock_config.log_level = "INFO"
        mock_uvicorn_run.side_effect = RuntimeError("Unexpected error")

        # Should not raise, just log error
        main()

        mock_init_app.assert_called_once()


if __name__ == "__main__":
    unittest.main()
