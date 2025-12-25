"""
Unit tests for config_loader.py

Comprehensive test coverage for configuration loading and validation including:
- Required environment variables
- Default values for optional settings
- URL trimming and validation
- Port number validation
- Log level validation
- List parsing for filters and projects
- Boolean parsing (multiple formats)
- API POST configuration
- Jenkins configuration
- BFA JWT configuration
- Error context settings
"""

import unittest
import os
from pathlib import Path
import sys

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config_loader import ConfigLoader


class TestConfigLoader(unittest.TestCase):
    """Test cases for ConfigLoader class."""

    def setUp(self):
        """Set up test fixtures - save and clear environment variables."""
        self.original_env = os.environ.copy()
        # Clear all relevant environment variables
        for key in list(os.environ.keys()):
            if key.startswith(('GITLAB_', 'WEBHOOK_', 'LOG_', 'API_POST_',
                               'JENKINS_', 'BFA_', 'RETRY_', 'ERROR_')):
                del os.environ[key]

    def tearDown(self):
        """Clean up test fixtures - restore environment variables."""
        os.environ.clear()
        os.environ.update(self.original_env)

    def test_load_with_minimum_required_config(self):
        """Test loading with only required environment variables."""
        os.environ['GITLAB_URL'] = 'https://gitlab.com'
        os.environ['GITLAB_TOKEN'] = 'glpat-1234567890'

        config = ConfigLoader.load()

        self.assertEqual(config.gitlab_url, 'https://gitlab.com')
        self.assertEqual(config.gitlab_token, 'glpat-1234567890')
        self.assertEqual(config.webhook_port, 8000)  # Default
        self.assertEqual(config.log_output_dir, './logs/pipeline-logs')  # Default
        self.assertEqual(config.retry_attempts, 3)  # Default
        self.assertEqual(config.retry_delay, 2)  # Default
        self.assertEqual(config.log_level, 'INFO')  # Default

    def test_load_missing_gitlab_url(self):
        """Test that missing GITLAB_URL raises ValueError."""
        os.environ['GITLAB_TOKEN'] = 'glpat-1234567890'

        with self.assertRaises(ValueError) as context:
            ConfigLoader.load()

        self.assertIn('GITLAB_URL', str(context.exception))

    def test_load_missing_gitlab_token(self):
        """Test that missing GITLAB_TOKEN raises ValueError."""
        os.environ['GITLAB_URL'] = 'https://gitlab.com'

        with self.assertRaises(ValueError) as context:
            ConfigLoader.load()

        self.assertIn('GITLAB_TOKEN', str(context.exception))

    def test_gitlab_url_trailing_slash_removal(self):
        """Test that trailing slash is removed from GitLab URL."""
        os.environ['GITLAB_URL'] = 'https://gitlab.com/'
        os.environ['GITLAB_TOKEN'] = 'glpat-1234567890'

        config = ConfigLoader.load()

        self.assertEqual(config.gitlab_url, 'https://gitlab.com')

    def test_webhook_port_custom_value(self):
        """Test loading custom webhook port."""
        os.environ['GITLAB_URL'] = 'https://gitlab.com'
        os.environ['GITLAB_TOKEN'] = 'glpat-1234567890'
        os.environ['WEBHOOK_PORT'] = '9000'

        config = ConfigLoader.load()

        self.assertEqual(config.webhook_port, 9000)

    def test_webhook_port_invalid_too_low(self):
        """Test that port number below 1 raises ValueError."""
        os.environ['GITLAB_URL'] = 'https://gitlab.com'
        os.environ['GITLAB_TOKEN'] = 'glpat-1234567890'
        os.environ['WEBHOOK_PORT'] = '0'

        with self.assertRaises(ValueError) as context:
            ConfigLoader.load()

        self.assertIn('WEBHOOK_PORT', str(context.exception))
        self.assertIn('between 1 and 65535', str(context.exception))

    def test_webhook_port_invalid_too_high(self):
        """Test that port number above 65535 raises ValueError."""
        os.environ['GITLAB_URL'] = 'https://gitlab.com'
        os.environ['GITLAB_TOKEN'] = 'glpat-1234567890'
        os.environ['WEBHOOK_PORT'] = '65536'

        with self.assertRaises(ValueError) as context:
            ConfigLoader.load()

        self.assertIn('WEBHOOK_PORT', str(context.exception))

    def test_log_level_valid_values(self):
        """Test valid log level values."""
        os.environ['GITLAB_URL'] = 'https://gitlab.com'
        os.environ['GITLAB_TOKEN'] = 'glpat-1234567890'

        for level in ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']:
            os.environ['LOG_LEVEL'] = level
            config = ConfigLoader.load()
            self.assertEqual(config.log_level, level)

    def test_log_level_case_insensitive(self):
        """Test that log level is converted to uppercase."""
        os.environ['GITLAB_URL'] = 'https://gitlab.com'
        os.environ['GITLAB_TOKEN'] = 'glpat-1234567890'
        os.environ['LOG_LEVEL'] = 'debug'

        config = ConfigLoader.load()

        self.assertEqual(config.log_level, 'DEBUG')

    def test_log_level_invalid(self):
        """Test that invalid log level raises ValueError."""
        os.environ['GITLAB_URL'] = 'https://gitlab.com'
        os.environ['GITLAB_TOKEN'] = 'glpat-1234567890'
        os.environ['LOG_LEVEL'] = 'INVALID'

        with self.assertRaises(ValueError) as context:
            ConfigLoader.load()

        self.assertIn('LOG_LEVEL', str(context.exception))

    def test_log_save_pipeline_status_parsing(self):
        """Test parsing of pipeline status filter."""
        os.environ['GITLAB_URL'] = 'https://gitlab.com'
        os.environ['GITLAB_TOKEN'] = 'glpat-1234567890'
        os.environ['LOG_SAVE_PIPELINE_STATUS'] = 'failed,canceled,skipped'

        config = ConfigLoader.load()

        self.assertEqual(config.log_save_pipeline_status, ['failed', 'canceled', 'skipped'])

    def test_log_save_pipeline_status_default(self):
        """Test default value for pipeline status filter."""
        os.environ['GITLAB_URL'] = 'https://gitlab.com'
        os.environ['GITLAB_TOKEN'] = 'glpat-1234567890'

        config = ConfigLoader.load()

        self.assertEqual(config.log_save_pipeline_status, ['all'])

    def test_log_save_projects_parsing(self):
        """Test parsing of project ID whitelist."""
        os.environ['GITLAB_URL'] = 'https://gitlab.com'
        os.environ['GITLAB_TOKEN'] = 'glpat-1234567890'
        os.environ['LOG_SAVE_PROJECTS'] = '123,456,789'

        config = ConfigLoader.load()

        self.assertEqual(config.log_save_projects, ['123', '456', '789'])

    def test_log_exclude_projects_parsing(self):
        """Test parsing of project ID blacklist."""
        os.environ['GITLAB_URL'] = 'https://gitlab.com'
        os.environ['GITLAB_TOKEN'] = 'glpat-1234567890'
        os.environ['LOG_EXCLUDE_PROJECTS'] = '999,888'

        config = ConfigLoader.load()

        self.assertEqual(config.log_exclude_projects, ['999', '888'])

    def test_log_save_metadata_always_boolean_parsing(self):
        """Test boolean parsing for log_save_metadata_always."""
        os.environ['GITLAB_URL'] = 'https://gitlab.com'
        os.environ['GITLAB_TOKEN'] = 'glpat-1234567890'

        # Test truthy values
        for value in ['true', '1', 'yes', 'on', 'TRUE', 'Yes', 'ON']:
            os.environ['LOG_SAVE_METADATA_ALWAYS'] = value
            config = ConfigLoader.load()
            self.assertTrue(config.log_save_metadata_always, f"Failed for value: {value}")

        # Test falsy values
        for value in ['false', '0', 'no', 'off', 'FALSE', 'No']:
            os.environ['LOG_SAVE_METADATA_ALWAYS'] = value
            config = ConfigLoader.load()
            self.assertFalse(config.log_save_metadata_always, f"Failed for value: {value}")

    def test_api_post_enabled_default(self):
        """Test API POST is disabled by default."""
        os.environ['GITLAB_URL'] = 'https://gitlab.com'
        os.environ['GITLAB_TOKEN'] = 'glpat-1234567890'

        config = ConfigLoader.load()

        self.assertFalse(config.api_post_enabled)

    def test_api_post_enabled_with_bfa_host(self):
        """Test API POST configuration with BFA_HOST."""
        os.environ['GITLAB_URL'] = 'https://gitlab.com'
        os.environ['GITLAB_TOKEN'] = 'glpat-1234567890'
        os.environ['API_POST_ENABLED'] = 'true'
        os.environ['BFA_HOST'] = 'bfa-server.example.com'

        config = ConfigLoader.load()

        self.assertTrue(config.api_post_enabled)
        self.assertEqual(config.bfa_host, 'bfa-server.example.com')
        self.assertEqual(config.api_post_url, 'http://bfa-server.example.com:8000/api/analyze')

    def test_api_post_enabled_without_bfa_host_raises_error(self):
        """Test that API_POST_ENABLED without BFA_HOST raises ValueError."""
        os.environ['GITLAB_URL'] = 'https://gitlab.com'
        os.environ['GITLAB_TOKEN'] = 'glpat-1234567890'
        os.environ['API_POST_ENABLED'] = 'true'

        with self.assertRaises(ValueError) as context:
            ConfigLoader.load()

        self.assertIn('BFA_HOST', str(context.exception))

    def test_api_post_timeout_validation(self):
        """Test API POST timeout validation."""
        os.environ['GITLAB_URL'] = 'https://gitlab.com'
        os.environ['GITLAB_TOKEN'] = 'glpat-1234567890'
        os.environ['API_POST_ENABLED'] = 'true'
        os.environ['BFA_HOST'] = 'bfa-server.example.com'

        # Test invalid timeout (too low)
        os.environ['API_POST_TIMEOUT'] = '0'
        with self.assertRaises(ValueError) as context:
            ConfigLoader.load()
        self.assertIn('API_POST_TIMEOUT', str(context.exception))

        # Test invalid timeout (too high)
        os.environ['API_POST_TIMEOUT'] = '301'
        with self.assertRaises(ValueError) as context:
            ConfigLoader.load()
        self.assertIn('API_POST_TIMEOUT', str(context.exception))

        # Test valid timeout
        os.environ['API_POST_TIMEOUT'] = '60'
        config = ConfigLoader.load()
        self.assertEqual(config.api_post_timeout, 60)

    def test_jenkins_disabled_by_default(self):
        """Test Jenkins is disabled by default."""
        os.environ['GITLAB_URL'] = 'https://gitlab.com'
        os.environ['GITLAB_TOKEN'] = 'glpat-1234567890'

        config = ConfigLoader.load()

        self.assertFalse(config.jenkins_enabled)

    def test_jenkins_enabled_with_full_config(self):
        """Test Jenkins configuration with all required settings."""
        os.environ['GITLAB_URL'] = 'https://gitlab.com'
        os.environ['GITLAB_TOKEN'] = 'glpat-1234567890'
        os.environ['JENKINS_ENABLED'] = 'true'
        os.environ['JENKINS_URL'] = 'https://jenkins.example.com/'
        os.environ['JENKINS_USER'] = 'jenkins-user'
        os.environ['JENKINS_API_TOKEN'] = 'jenkins-token-123'

        config = ConfigLoader.load()

        self.assertTrue(config.jenkins_enabled)
        self.assertEqual(config.jenkins_url, 'https://jenkins.example.com')  # Trailing slash removed
        self.assertEqual(config.jenkins_user, 'jenkins-user')
        self.assertEqual(config.jenkins_api_token, 'jenkins-token-123')

    def test_jenkins_enabled_missing_url(self):
        """Test that JENKINS_ENABLED without JENKINS_URL raises ValueError."""
        os.environ['GITLAB_URL'] = 'https://gitlab.com'
        os.environ['GITLAB_TOKEN'] = 'glpat-1234567890'
        os.environ['JENKINS_ENABLED'] = 'true'

        with self.assertRaises(ValueError) as context:
            ConfigLoader.load()

        self.assertIn('JENKINS_URL', str(context.exception))

    def test_jenkins_url_invalid_protocol(self):
        """Test that invalid Jenkins URL protocol raises ValueError."""
        os.environ['GITLAB_URL'] = 'https://gitlab.com'
        os.environ['GITLAB_TOKEN'] = 'glpat-1234567890'
        os.environ['JENKINS_ENABLED'] = 'true'
        os.environ['JENKINS_URL'] = 'ftp://jenkins.example.com'
        os.environ['JENKINS_USER'] = 'user'
        os.environ['JENKINS_API_TOKEN'] = 'token'

        with self.assertRaises(ValueError) as context:
            ConfigLoader.load()

        self.assertIn('JENKINS_URL', str(context.exception))
        self.assertIn('http://', str(context.exception))

    def test_jenkins_enabled_missing_user(self):
        """Test that JENKINS_ENABLED without JENKINS_USER raises ValueError."""
        os.environ['GITLAB_URL'] = 'https://gitlab.com'
        os.environ['GITLAB_TOKEN'] = 'glpat-1234567890'
        os.environ['JENKINS_ENABLED'] = 'true'
        os.environ['JENKINS_URL'] = 'https://jenkins.example.com'

        with self.assertRaises(ValueError) as context:
            ConfigLoader.load()

        self.assertIn('JENKINS_USER', str(context.exception))

    def test_jenkins_enabled_missing_api_token(self):
        """Test that JENKINS_ENABLED without JENKINS_API_TOKEN raises ValueError."""
        os.environ['GITLAB_URL'] = 'https://gitlab.com'
        os.environ['GITLAB_TOKEN'] = 'glpat-1234567890'
        os.environ['JENKINS_ENABLED'] = 'true'
        os.environ['JENKINS_URL'] = 'https://jenkins.example.com'
        os.environ['JENKINS_USER'] = 'jenkins-user'

        with self.assertRaises(ValueError) as context:
            ConfigLoader.load()

        self.assertIn('JENKINS_API_TOKEN', str(context.exception))

    def test_error_context_lines_custom_values(self):
        """Test custom error context line settings."""
        os.environ['GITLAB_URL'] = 'https://gitlab.com'
        os.environ['GITLAB_TOKEN'] = 'glpat-1234567890'
        os.environ['ERROR_CONTEXT_LINES_BEFORE'] = '100'
        os.environ['ERROR_CONTEXT_LINES_AFTER'] = '20'

        config = ConfigLoader.load()

        self.assertEqual(config.error_context_lines_before, 100)
        self.assertEqual(config.error_context_lines_after, 20)

    def test_error_context_lines_defaults(self):
        """Test default error context line settings."""
        os.environ['GITLAB_URL'] = 'https://gitlab.com'
        os.environ['GITLAB_TOKEN'] = 'glpat-1234567890'

        config = ConfigLoader.load()

        self.assertEqual(config.error_context_lines_before, 50)
        self.assertEqual(config.error_context_lines_after, 10)

    def test_validate_valid_config(self):
        """Test validation of a valid configuration."""
        os.environ['GITLAB_URL'] = 'https://gitlab.com'
        os.environ['GITLAB_TOKEN'] = 'glpat-1234567890'

        config = ConfigLoader.load()
        result = ConfigLoader.validate(config)

        self.assertTrue(result)

    def test_validate_invalid_gitlab_url_protocol(self):
        """Test validation fails for invalid GitLab URL protocol."""
        os.environ['GITLAB_URL'] = 'ftp://gitlab.com'
        os.environ['GITLAB_TOKEN'] = 'glpat-1234567890'

        config = ConfigLoader.load()

        with self.assertRaises(ValueError) as context:
            ConfigLoader.validate(config)

        self.assertIn('GITLAB_URL', str(context.exception))
        self.assertIn('http://', str(context.exception))

    def test_validate_short_gitlab_token(self):
        """Test validation fails for too short GitLab token."""
        os.environ['GITLAB_URL'] = 'https://gitlab.com'
        os.environ['GITLAB_TOKEN'] = 'short'

        config = ConfigLoader.load()

        with self.assertRaises(ValueError) as context:
            ConfigLoader.validate(config)

        self.assertIn('GITLAB_TOKEN', str(context.exception))
        self.assertIn('too short', str(context.exception))

    def test_retry_settings(self):
        """Test retry attempt and delay settings."""
        os.environ['GITLAB_URL'] = 'https://gitlab.com'
        os.environ['GITLAB_TOKEN'] = 'glpat-1234567890'
        os.environ['RETRY_ATTEMPTS'] = '5'
        os.environ['RETRY_DELAY'] = '10'

        config = ConfigLoader.load()

        self.assertEqual(config.retry_attempts, 5)
        self.assertEqual(config.retry_delay, 10)

    def test_webhook_secret_optional(self):
        """Test that webhook secret is optional."""
        os.environ['GITLAB_URL'] = 'https://gitlab.com'
        os.environ['GITLAB_TOKEN'] = 'glpat-1234567890'

        config = ConfigLoader.load()

        self.assertIsNone(config.webhook_secret)

        # Test with secret
        os.environ['WEBHOOK_SECRET'] = 'my-secret-123'
        config = ConfigLoader.load()

        self.assertEqual(config.webhook_secret, 'my-secret-123')

    def test_bfa_secret_key_optional(self):
        """Test that BFA secret key is optional when API posting is disabled."""
        os.environ['GITLAB_URL'] = 'https://gitlab.com'
        os.environ['GITLAB_TOKEN'] = 'glpat-1234567890'

        config = ConfigLoader.load()

        self.assertIsNone(config.bfa_secret_key)

    def test_api_post_url_none_when_bfa_host_not_set(self):
        """Test that API POST URL is None when BFA_HOST is not set."""
        os.environ['GITLAB_URL'] = 'https://gitlab.com'
        os.environ['GITLAB_TOKEN'] = 'glpat-1234567890'

        config = ConfigLoader.load()

        self.assertIsNone(config.api_post_url)

    def test_list_parsing_with_spaces(self):
        """Test that list parsing handles spaces correctly."""
        os.environ['GITLAB_URL'] = 'https://gitlab.com'
        os.environ['GITLAB_TOKEN'] = 'glpat-1234567890'
        os.environ['LOG_SAVE_PIPELINE_STATUS'] = 'failed , canceled , skipped'

        config = ConfigLoader.load()

        # Spaces should be stripped
        self.assertEqual(config.log_save_pipeline_status, ['failed', 'canceled', 'skipped'])

    def test_list_parsing_empty_string(self):
        """Test that empty string results in empty list."""
        os.environ['GITLAB_URL'] = 'https://gitlab.com'
        os.environ['GITLAB_TOKEN'] = 'glpat-1234567890'
        os.environ['LOG_SAVE_PROJECTS'] = ''

        config = ConfigLoader.load()

        self.assertEqual(config.log_save_projects, [])

    def test_api_post_retry_enabled_default(self):
        """Test API POST retry is enabled by default."""
        os.environ['GITLAB_URL'] = 'https://gitlab.com'
        os.environ['GITLAB_TOKEN'] = 'glpat-1234567890'

        config = ConfigLoader.load()

        self.assertTrue(config.api_post_retry_enabled)

    def test_api_post_save_to_file_default(self):
        """Test API POST save to file is disabled by default."""
        os.environ['GITLAB_URL'] = 'https://gitlab.com'
        os.environ['GITLAB_TOKEN'] = 'glpat-1234567890'

        config = ConfigLoader.load()

        self.assertFalse(config.api_post_save_to_file)


if __name__ == '__main__':
    unittest.main()
