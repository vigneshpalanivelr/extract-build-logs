"""
Unit tests for manage_container.py

Comprehensive test coverage for the container management script including:
- Configuration loading and validation
- Docker operations
- CLI commands
- Error handling
- User interaction
"""

import unittest
from unittest.mock import patch, MagicMock, mock_open
from pathlib import Path
import sys
import argparse

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import manage_container


class TestMaskValue(unittest.TestCase):
    """Test cases for mask_value function."""

    def test_mask_long_value(self):
        """Test masking a long value shows first 8 chars."""
        result = manage_container.mask_value("glpat-1234567890abcdefgh", 8)
        self.assertEqual(result, "glpat-12****")

    def test_mask_short_value(self):
        """Test masking a short value returns asterisks."""
        result = manage_container.mask_value("short", 8)
        self.assertEqual(result, "****")

    def test_mask_empty_value(self):
        """Test masking empty value returns 'Not Set'."""
        result = manage_container.mask_value("", 8)
        self.assertIn("Not Set", result)

    def test_mask_none_value(self):
        """Test masking None returns 'Not Set'."""
        result = manage_container.mask_value(None, 8)
        self.assertIn("Not Set", result)

    def test_mask_custom_show_chars(self):
        """Test masking with custom number of visible characters."""
        result = manage_container.mask_value("glpat-1234567890", 4)
        self.assertEqual(result, "glpa****")


class TestLoadConfig(unittest.TestCase):
    """Test cases for load_config function."""

    def test_load_config_file_not_found(self):
        """Test loading non-existent config file returns None."""
        result = manage_container.load_config(Path('/nonexistent/.env'))
        self.assertIsNone(result)

    @patch('manage_container.dotenv_values')
    @patch('pathlib.Path.exists')
    def test_load_config_with_all_values(self, mock_exists, mock_dotenv):
        """Test loading config with all values set."""
        mock_exists.return_value = True
        mock_dotenv.return_value = {
            'GITLAB_URL': 'https://gitlab.com',
            'GITLAB_TOKEN': 'glpat-test123',
            'WEBHOOK_PORT': '9000',
            'WEBHOOK_SECRET': 'secret123',
            'LOG_LEVEL': 'DEBUG',
            'LOG_OUTPUT_DIR': './my-logs',
            'RETRY_ATTEMPTS': '5',
            'RETRY_DELAY': '3',
        }

        result = manage_container.load_config(Path('.env'))

        self.assertIsNotNone(result)
        self.assertEqual(result['GITLAB_URL'], 'https://gitlab.com')
        self.assertEqual(result['GITLAB_TOKEN'], 'glpat-test123')
        self.assertEqual(result['WEBHOOK_PORT'], '9000')

    @patch('manage_container.dotenv_values')
    @patch('pathlib.Path.exists')
    def test_load_config_with_defaults(self, mock_exists, mock_dotenv):
        """Test loading config without defaults returns only provided values."""
        mock_exists.return_value = True
        mock_dotenv.return_value = {
            'GITLAB_URL': 'https://gitlab.com',
            'GITLAB_TOKEN': 'glpat-test123',
        }

        result = manage_container.load_config(Path('.env'))

        # Defaults are no longer applied - config only contains what's in .env
        self.assertNotIn('WEBHOOK_PORT', result)
        self.assertNotIn('LOG_LEVEL', result)
        self.assertNotIn('LOG_OUTPUT_DIR', result)


class TestValidateConfig(unittest.TestCase):
    """Test cases for validate_config function."""

    @patch('pathlib.Path.exists')
    def test_validate_valid_config(self, mock_exists):
        """Test validation of a fully valid configuration."""
        mock_exists.return_value = False  # Pretend .env doesn't exist to skip permission check
        config = {
            'GITLAB_URL': 'https://gitlab.com',
            'GITLAB_TOKEN': 'glpat-test123',
            'DOCKER_IMAGE_NAME': 'bfa-gitlab-pipeline-extractor',
            'DOCKER_CONTAINER_NAME': 'bfa-gitlab-pipeline-extractor',
            'DOCKER_LOGS_DIR': './logs',
            'WEBHOOK_PORT': '8000',
            'WEBHOOK_SECRET': 'secret',
            'LOG_LEVEL': 'INFO',
            'LOG_OUTPUT_DIR': './logs',
            'RETRY_ATTEMPTS': '3',
            'RETRY_DELAY': '2',
        }

        errors, warnings = manage_container.validate_config(config)

        self.assertEqual(len(errors), 0)
        self.assertEqual(len(warnings), 0)

    def test_validate_missing_gitlab_url(self):
        """Test validation catches missing GITLAB_URL."""
        config = {
            'GITLAB_TOKEN': 'glpat-test123',
            'DOCKER_IMAGE_NAME': 'bfa-gitlab-pipeline-extractor',
            'DOCKER_CONTAINER_NAME': 'bfa-gitlab-pipeline-extractor',
            'DOCKER_LOGS_DIR': './logs',
            'WEBHOOK_PORT': '8000',
            'LOG_LEVEL': 'INFO',
            'LOG_OUTPUT_DIR': './logs',
            'RETRY_ATTEMPTS': '3',
            'RETRY_DELAY': '2',
        }

        errors, warnings = manage_container.validate_config(config)

        self.assertGreaterEqual(len(errors), 1)
        self.assertTrue(any('GITLAB_URL' in e for e in errors))

    def test_validate_missing_gitlab_token(self):
        """Test validation catches missing GITLAB_TOKEN."""
        config = {
            'GITLAB_URL': 'https://gitlab.com',
            'DOCKER_IMAGE_NAME': 'bfa-gitlab-pipeline-extractor',
            'DOCKER_CONTAINER_NAME': 'bfa-gitlab-pipeline-extractor',
            'DOCKER_LOGS_DIR': './logs',
            'WEBHOOK_PORT': '8000',
            'LOG_LEVEL': 'INFO',
            'LOG_OUTPUT_DIR': './logs',
            'RETRY_ATTEMPTS': '3',
            'RETRY_DELAY': '2',
        }

        errors, warnings = manage_container.validate_config(config)

        self.assertGreaterEqual(len(errors), 1)
        self.assertTrue(any('GITLAB_TOKEN' in e for e in errors))

    def test_validate_invalid_port(self):
        """Test validation errors on invalid port."""
        config = {
            'GITLAB_URL': 'https://gitlab.com',
            'GITLAB_TOKEN': 'glpat-test123',
            'DOCKER_IMAGE_NAME': 'bfa-gitlab-pipeline-extractor',
            'DOCKER_CONTAINER_NAME': 'bfa-gitlab-pipeline-extractor',
            'DOCKER_LOGS_DIR': './logs',
            'WEBHOOK_PORT': 'not-a-number',
            'LOG_LEVEL': 'INFO',
            'LOG_OUTPUT_DIR': './logs',
            'RETRY_ATTEMPTS': '3',
            'RETRY_DELAY': '2',
        }

        errors, warnings = manage_container.validate_config(config)

        self.assertGreaterEqual(len(errors), 1)
        self.assertTrue(any('WEBHOOK_PORT' in e for e in errors))


class TestConfirmAction(unittest.TestCase):
    """Test cases for confirm_action function."""

    def test_confirm_action_auto_yes(self):
        """Test auto-confirmation with yes flag."""
        result = manage_container.confirm_action("Test?", auto_yes=True)
        self.assertTrue(result)

    @patch('builtins.input', return_value='y')
    def test_confirm_action_user_yes(self, mock_input):
        """Test user confirms with 'y'."""
        result = manage_container.confirm_action("Test?", auto_yes=False)
        self.assertTrue(result)

    @patch('builtins.input', return_value='n')
    def test_confirm_action_user_no(self, mock_input):
        """Test user declines with 'n'."""
        result = manage_container.confirm_action("Test?", auto_yes=False)
        self.assertFalse(result)

    @patch('builtins.input', side_effect=KeyboardInterrupt())
    def test_confirm_action_keyboard_interrupt(self, mock_input):
        """Test graceful handling of keyboard interrupt."""
        result = manage_container.confirm_action("Test?", auto_yes=False)
        self.assertFalse(result)


class TestGetDockerClient(unittest.TestCase):
    """Test cases for get_docker_client function."""

    @patch('manage_container.docker.from_env')
    def test_get_docker_client_success(self, mock_docker):
        """Test successful Docker client creation."""
        mock_client = MagicMock()
        mock_docker.return_value = mock_client

        result = manage_container.get_docker_client()

        self.assertIsNotNone(result)
        mock_client.ping.assert_called_once()

    @patch('manage_container.docker.from_env')
    def test_get_docker_client_failure(self, mock_docker):
        """Test Docker client creation failure."""
        from docker.errors import DockerException
        mock_docker.side_effect = DockerException("Docker not running")

        result = manage_container.get_docker_client()

        self.assertIsNone(result)


class TestGetPortFromConfig(unittest.TestCase):
    """Test cases for get_port_from_config function."""

    @patch('manage_container.load_config')
    def test_get_port_from_config_success(self, mock_load):
        """Test getting port from config."""
        mock_load.return_value = {'WEBHOOK_PORT': '9000'}

        result = manage_container.get_port_from_config()

        self.assertEqual(result, 9000)

    @patch('manage_container.load_config')
    def test_get_port_from_config_default(self, mock_load):
        """Test getting default port when config missing."""
        mock_load.return_value = None

        result = manage_container.get_port_from_config()

        self.assertEqual(result, 8000)


class TestBuildImage(unittest.TestCase):
    """Test cases for build_image function."""

    @patch('manage_container.load_config')
    @patch('manage_container.subprocess.run')
    @patch('manage_container.Progress')
    @patch('manage_container.os.environ.get')
    @patch('manage_container.os.path.abspath')
    @patch('manage_container.console')
    def test_build_image_success(self, mock_console, mock_abspath, mock_env_get, mock_progress, mock_subprocess, mock_load_config):
        """Test successful image build using subprocess (SDK has user namespace issue)."""
        # Mock load_config to return config with Docker settings
        mock_load_config.return_value = {
            'DOCKER_IMAGE_NAME': 'bfa-gitlab-pipeline-extractor',
            'DOCKER_CONTAINER_NAME': 'bfa-gitlab-pipeline-extractor',
            'DOCKER_LOGS_DIR': './logs'
        }

        # Mock os.path.abspath to return current directory
        mock_abspath.return_value = '/current/dir'

        # Mock environment variables for USER_UID and USER_GID
        def env_get_side_effect(key, default=None):
            if key == 'USER_UID':
                return '12345'
            elif key == 'USER_GID':
                return '54321'
            return default

        mock_env_get.side_effect = env_get_side_effect

        # Mock Progress context manager
        mock_progress_instance = MagicMock()
        mock_progress.return_value.__enter__.return_value = mock_progress_instance
        mock_progress_instance.add_task.return_value = 0

        # Mock subprocess.run to return success
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""
        mock_subprocess.return_value = mock_result

        mock_client = MagicMock()

        result = manage_container.build_image(mock_client)

        self.assertTrue(result)
        mock_subprocess.assert_called_once()

        # Verify subprocess was called with correct command
        call_args = mock_subprocess.call_args
        cmd = call_args[0][0]
        self.assertIn('docker', cmd)
        self.assertIn('build', cmd)
        self.assertIn('--build-arg', cmd)
        self.assertIn('USER_UID=12345', cmd)
        self.assertIn('USER_GID=54321', cmd)
        self.assertIn('-t', cmd)
        self.assertIn('bfa-gitlab-pipeline-extractor:latest', cmd)
        self.assertIn('--rm', cmd)
        self.assertIn('.', cmd)

        # Verify Python 3.6 compatible parameters are used
        import subprocess
        self.assertEqual(call_args[1]['stdout'], subprocess.PIPE)
        self.assertEqual(call_args[1]['stderr'], subprocess.PIPE)
        self.assertTrue(call_args[1]['universal_newlines'])
        self.assertEqual(call_args[1]['cwd'], '/current/dir')

    @patch('manage_container.subprocess.run')
    @patch('manage_container.Progress')
    @patch('manage_container.os.path.abspath')
    @patch('manage_container.console')
    def test_build_image_failure(self, mock_console, mock_abspath, mock_progress, mock_subprocess):
        """Test image build failure using subprocess."""
        # Mock os.path.abspath
        mock_abspath.return_value = '/current/dir'

        # Mock Progress context manager
        mock_progress_instance = MagicMock()
        mock_progress.return_value.__enter__.return_value = mock_progress_instance
        mock_progress_instance.add_task.return_value = 0

        # Mock subprocess.run to return failure
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "Build error"
        mock_result.stdout = ""
        mock_subprocess.return_value = mock_result

        mock_client = MagicMock()

        result = manage_container.build_image(mock_client)

        self.assertFalse(result)


class TestContainerExists(unittest.TestCase):
    """Test cases for container_exists function."""

    def test_container_exists_true(self):
        """Test container exists."""
        mock_client = MagicMock()
        mock_client.containers.get.return_value = MagicMock()

        result = manage_container.container_exists(mock_client)

        self.assertTrue(result)

    def test_container_exists_false(self):
        """Test container does not exist."""
        from docker.errors import NotFound
        mock_client = MagicMock()
        mock_client.containers.get.side_effect = NotFound("Container not found")

        result = manage_container.container_exists(mock_client)

        self.assertFalse(result)


class TestContainerRunning(unittest.TestCase):
    """Test cases for container_running function."""

    def test_container_running_true(self):
        """Test container is running."""
        mock_client = MagicMock()
        mock_container = MagicMock()
        mock_container.status = 'running'
        mock_client.containers.get.return_value = mock_container

        result = manage_container.container_running(mock_client)

        self.assertTrue(result)

    def test_container_running_false(self):
        """Test container is not running."""
        mock_client = MagicMock()
        mock_container = MagicMock()
        mock_container.status = 'exited'
        mock_client.containers.get.return_value = mock_container

        result = manage_container.container_running(mock_client)

        self.assertFalse(result)


class TestStartContainer(unittest.TestCase):
    """Test cases for start_container function."""

    @patch('manage_container.Path')
    @patch('manage_container.console')
    @patch('manage_container.container_exists')
    @patch('manage_container.container_running')
    def test_start_container_already_running(self, mock_running, mock_exists, mock_console, mock_path):
        """Test start when container already running."""
        mock_exists.return_value = True
        mock_running.return_value = True
        mock_client = MagicMock()
        config = {'WEBHOOK_PORT': '8000', 'DOCKER_IMAGE_NAME': 'bfa-gitlab-pipeline-extractor', 'DOCKER_CONTAINER_NAME': 'bfa-gitlab-pipeline-extractor', 'DOCKER_LOGS_DIR': './logs'}

        # Mock Path instance
        mock_path_instance = MagicMock()
        mock_path_instance.exists.return_value = True
        mock_path.return_value = mock_path_instance

        result = manage_container.start_container(mock_client, config, skip_confirm=True)

        self.assertTrue(result)

    @patch('manage_container.Path')
    @patch('manage_container.console')
    @patch('manage_container.container_exists')
    @patch('manage_container.container_running')
    @patch('manage_container.show_endpoints')
    def test_start_container_new(self, mock_endpoints, mock_running, mock_exists, mock_console, mock_path):
        """Test starting new container with host network and user namespace."""
        mock_exists.return_value = False
        mock_client = MagicMock()
        config = {'WEBHOOK_PORT': '8000', 'DOCKER_IMAGE_NAME': 'bfa-gitlab-pipeline-extractor', 'DOCKER_CONTAINER_NAME': 'bfa-gitlab-pipeline-extractor', 'DOCKER_LOGS_DIR': './logs'}

        # Mock Path instance
        mock_path_instance = MagicMock()
        mock_path_instance.exists.return_value = False
        mock_path.return_value = mock_path_instance

        result = manage_container.start_container(mock_client, config, skip_confirm=True)

        self.assertTrue(result)
        mock_client.containers.run.assert_called_once()

        # Verify container was started with correct parameters
        call_args = mock_client.containers.run.call_args
        self.assertEqual(call_args[0][0], 'bfa-gitlab-pipeline-extractor:latest')  # Image with :latest tag
        self.assertEqual(call_args[1]['name'], 'bfa-gitlab-pipeline-extractor')
        self.assertTrue(call_args[1]['detach'])
        self.assertEqual(call_args[1]['network_mode'], 'host')  # Host networking
        self.assertEqual(call_args[1]['userns_mode'], 'host')  # Host user namespace
        self.assertIn('volumes', call_args[1])
        self.assertIn('restart_policy', call_args[1])


class TestStopContainer(unittest.TestCase):
    """Test cases for stop_container function."""

    @patch('manage_container.console')
    @patch('manage_container.container_running')
    def test_stop_container_success(self, mock_running, mock_console):
        """Test successful container stop."""
        mock_running.return_value = True
        mock_client = MagicMock()
        mock_container = MagicMock()
        mock_client.containers.get.return_value = mock_container

        result = manage_container.stop_container(mock_client)

        self.assertTrue(result)
        mock_container.stop.assert_called_once()

    @patch('manage_container.console')
    @patch('manage_container.container_running')
    def test_stop_container_not_running(self, mock_running, mock_console):
        """Test stop when container not running."""
        mock_running.return_value = False
        mock_client = MagicMock()

        result = manage_container.stop_container(mock_client)

        self.assertTrue(result)


class TestRestartContainer(unittest.TestCase):
    """Test cases for restart_container function."""

    @patch('manage_container.container_running')
    @patch('manage_container.container_exists')
    @patch('manage_container.start_container')
    @patch('manage_container.stop_container')
    @patch('manage_container.console')
    def test_restart_container_success(self, mock_console, mock_stop, mock_start, mock_exists, mock_running):
        """Test successful container restart."""
        mock_exists.return_value = True
        mock_running.return_value = True
        mock_stop.return_value = True
        mock_start.return_value = True
        mock_client = MagicMock()
        config = {'WEBHOOK_PORT': '8000', 'DOCKER_IMAGE_NAME': 'bfa-gitlab-pipeline-extractor', 'DOCKER_CONTAINER_NAME': 'bfa-gitlab-pipeline-extractor', 'DOCKER_LOGS_DIR': './logs'}

        result = manage_container.restart_container(mock_client, config)

        self.assertTrue(result)
        mock_stop.assert_called_once()
        mock_start.assert_called_once()


class TestShowLogs(unittest.TestCase):
    """Test cases for show_logs function."""

    @patch('manage_container.console')
    @patch('manage_container.container_exists')
    def test_show_logs_container_not_exists(self, mock_exists, mock_console):
        """Test show logs when container doesn't exist."""
        mock_exists.return_value = False
        mock_client = MagicMock()

        result = manage_container.show_logs(mock_client, follow=False)

        self.assertFalse(result)

    @patch('manage_container.console')
    @patch('manage_container.container_exists')
    def test_show_logs_no_follow(self, mock_exists, mock_console):
        """Test showing logs without following."""
        mock_exists.return_value = True
        mock_client = MagicMock()
        mock_container = MagicMock()
        mock_container.logs.return_value = b"test logs"
        mock_client.containers.get.return_value = mock_container

        result = manage_container.show_logs(mock_client, follow=False)

        self.assertTrue(result)
        mock_container.logs.assert_called_once()


class TestShowStatus(unittest.TestCase):
    """Test cases for show_status function."""

    @patch('manage_container.console')
    @patch('manage_container.container_exists')
    def test_show_status_not_exists(self, mock_exists, mock_console):
        """Test status when container doesn't exist."""
        mock_exists.return_value = False
        mock_client = MagicMock()

        result = manage_container.show_status(mock_client)

        self.assertTrue(result)

    @patch('manage_container.console')
    @patch('manage_container.container_exists')
    def test_show_status_running(self, mock_exists, mock_console):
        """Test status when container is running."""
        mock_exists.return_value = True
        mock_client = MagicMock()
        mock_container = MagicMock()
        mock_container.name = 'gitlab-log-extractor'
        mock_container.status = 'running'
        mock_container.short_id = 'abc123'
        mock_container.attrs = {
            'Created': '2024-01-01T00:00:00Z',
            'NetworkSettings': {'Ports': {}},
            'State': {}
        }
        mock_container.stats.return_value = {
            'cpu_stats': {'cpu_usage': {'total_usage': 1000}, 'system_cpu_usage': 2000, 'online_cpus': 1},
            'precpu_stats': {'cpu_usage': {'total_usage': 500}, 'system_cpu_usage': 1000},
            'memory_stats': {'usage': 1024 * 1024 * 100, 'limit': 1024 * 1024 * 1000}
        }
        mock_client.containers.get.return_value = mock_container

        result = manage_container.show_status(mock_client)

        self.assertTrue(result)

    @patch('manage_container.console')
    @patch('manage_container.container_exists')
    def test_show_status_with_uptime_microseconds(self, mock_exists, mock_console):
        """Test status with StartedAt timestamp containing microseconds (Python 3.6 datetime parsing)."""
        mock_exists.return_value = True
        mock_client = MagicMock()
        mock_container = MagicMock()
        mock_container.name = 'gitlab-log-extractor'
        mock_container.status = 'running'
        mock_container.short_id = 'abc123'
        mock_container.attrs = {
            'Created': '2024-01-01T00:00:00Z',
            'NetworkSettings': {'Ports': {}},
            'State': {
                'StartedAt': '2024-01-01T10:00:00.123456Z'  # ISO format with microseconds
            }
        }
        mock_container.stats.return_value = {
            'cpu_stats': {'cpu_usage': {'total_usage': 1000}, 'system_cpu_usage': 2000, 'online_cpus': 1},
            'precpu_stats': {'cpu_usage': {'total_usage': 500}, 'system_cpu_usage': 1000},
            'memory_stats': {'usage': 1024 * 1024 * 100, 'limit': 1024 * 1024 * 1000}
        }
        mock_container.logs.return_value = b"test log output"
        mock_client.containers.get.return_value = mock_container

        result = manage_container.show_status(mock_client)

        self.assertTrue(result)

    @patch('manage_container.console')
    @patch('manage_container.container_exists')
    def test_show_status_with_uptime_no_microseconds(self, mock_exists, mock_console):
        """Test status with StartedAt timestamp without microseconds (Python 3.6 datetime parsing)."""
        mock_exists.return_value = True
        mock_client = MagicMock()
        mock_container = MagicMock()
        mock_container.name = 'gitlab-log-extractor'
        mock_container.status = 'running'
        mock_container.short_id = 'abc123'
        mock_container.attrs = {
            'Created': '2024-01-01T00:00:00Z',
            'NetworkSettings': {'Ports': {}},
            'State': {
                'StartedAt': '2024-01-01T10:00:00+00:00'  # ISO format without microseconds
            }
        }
        mock_container.stats.return_value = {
            'cpu_stats': {'cpu_usage': {'total_usage': 1000}, 'system_cpu_usage': 2000, 'online_cpus': 1},
            'precpu_stats': {'cpu_usage': {'total_usage': 500}, 'system_cpu_usage': 1000},
            'memory_stats': {'usage': 1024 * 1024 * 100, 'limit': 1024 * 1024 * 1000}
        }
        mock_container.logs.return_value = b"test log output"
        mock_client.containers.get.return_value = mock_container

        result = manage_container.show_status(mock_client)

        self.assertTrue(result)

    @patch('manage_container.console')
    @patch('manage_container.container_exists')
    def test_show_status_with_malformed_timestamp(self, mock_exists, mock_console):
        """Test status handles malformed timestamp gracefully (Python 3.6 datetime parsing)."""
        mock_exists.return_value = True
        mock_client = MagicMock()
        mock_container = MagicMock()
        mock_container.name = 'gitlab-log-extractor'
        mock_container.status = 'running'
        mock_container.short_id = 'abc123'
        mock_container.attrs = {
            'Created': '2024-01-01T00:00:00Z',
            'NetworkSettings': {'Ports': {}},
            'State': {
                'StartedAt': 'invalid-timestamp'  # Malformed timestamp - should fallback
            }
        }
        mock_container.stats.return_value = {
            'cpu_stats': {'cpu_usage': {'total_usage': 1000}, 'system_cpu_usage': 2000, 'online_cpus': 1},
            'precpu_stats': {'cpu_usage': {'total_usage': 500}, 'system_cpu_usage': 1000},
            'memory_stats': {'usage': 1024 * 1024 * 100, 'limit': 1024 * 1024 * 1000}
        }
        mock_container.logs.return_value = b"test log output"
        mock_client.containers.get.return_value = mock_container

        # Should not raise exception, fallback to current time
        result = manage_container.show_status(mock_client)

        self.assertTrue(result)


@unittest.skip("open_shell function removed during script condensing")
class TestOpenShell(unittest.TestCase):
    """Test cases for open_shell function."""

    @patch('manage_container.console')
    @patch('manage_container.container_running')
    def test_open_shell_success(self, mock_running, mock_console):
        """Test successful shell opening."""
        mock_running.return_value = True

        # Function removed during condensing
        pass

    @patch('manage_container.console')
    @patch('manage_container.container_running')
    def test_open_shell_not_running(self, mock_running, mock_console):
        """Test shell when container not running."""
        # Function removed during condensing
        pass


class TestRemoveContainer(unittest.TestCase):
    """Test cases for remove_container function."""

    @patch('manage_container.load_config')
    @patch('manage_container.stop_container')
    @patch('manage_container.console')
    @patch('manage_container.container_exists')
    def test_remove_container_with_force(self, mock_exists, mock_console, mock_stop, mock_load_config):
        """Test removing container with force flag."""
        mock_load_config.return_value = {
            'DOCKER_IMAGE_NAME': 'bfa-gitlab-pipeline-extractor',
            'DOCKER_LOGS_DIR': './logs'
        }
        mock_exists.return_value = True
        mock_client = MagicMock()
        mock_container = MagicMock()
        mock_client.containers.get.return_value = mock_container

        result = manage_container.remove_container(mock_client, force=True)

        self.assertTrue(result)
        mock_container.remove.assert_called_once()


@unittest.skip("cleanup function removed during script condensing")
class TestCleanup(unittest.TestCase):
    """Test cases for cleanup function."""

    @patch('manage_container.console')
    def test_cleanup_with_force(self, mock_console):
        """Test cleanup with force flag."""
        # Function removed during condensing
        pass


class TestShowMonitor(unittest.TestCase):
    """Test cases for show_monitor function."""

    @patch('manage_container.console')
    @patch('manage_container.container_running')
    def test_show_monitor_not_running(self, mock_running, mock_console):
        """Test monitor when container not running."""
        mock_running.return_value = False
        mock_client = MagicMock()

        result = manage_container.show_monitor(mock_client, [])

        self.assertFalse(result)

    @patch('manage_container.console')
    @patch('manage_container.container_running')
    def test_show_monitor_success(self, mock_running, mock_console):
        """Test successful monitor display."""
        mock_running.return_value = True
        mock_client = MagicMock()
        mock_container = MagicMock()
        mock_result = MagicMock()
        mock_result.output = [b"test output"]
        mock_container.exec_run.return_value = mock_result
        mock_client.containers.get.return_value = mock_container

        result = manage_container.show_monitor(mock_client, ['--hours', '24'])

        self.assertTrue(result)


class TestExportMonitoringData(unittest.TestCase):
    """Test cases for export_monitoring_data function."""

    @patch('manage_container.requests.get')
    @patch('manage_container.get_port_from_config')
    @patch('manage_container.console')
    def test_export_monitoring_data_success(self, mock_console, mock_port, mock_get):
        """Test successful data export."""
        mock_port.return_value = 8000
        mock_response = MagicMock()
        mock_response.text = "csv,data"
        mock_get.return_value = mock_response

        with patch('builtins.open', mock_open()):
            result = manage_container.export_monitoring_data("test.csv")

        self.assertTrue(result)
        mock_get.assert_called_once()


class TestTestWebhook(unittest.TestCase):
    """Test cases for test_webhook function."""

    @patch('manage_container.requests.post')
    @patch('manage_container.get_port_from_config')
    @patch('manage_container.console')
    def test_test_webhook_success(self, mock_console, mock_port, mock_post):
        """Test successful webhook test."""
        mock_port.return_value = 8000
        mock_response = MagicMock()
        mock_response.json.return_value = {"status": "success"}
        mock_post.return_value = mock_response

        result = manage_container.test_webhook()

        self.assertTrue(result)
        mock_post.assert_called_once()


class TestCLICommands(unittest.TestCase):
    """Test cases for CLI command functions."""

    @patch('manage_container.load_config')
    @patch('manage_container.validate_config')
    @patch('manage_container.show_config_table')
    @patch('manage_container.show_validation_results')
    def test_cmd_config_success(self, mock_show_val, mock_show_table, mock_validate, mock_load):
        """Test config command with valid configuration."""
        mock_load.return_value = {'GITLAB_URL': 'test', 'GITLAB_TOKEN': 'test'}
        mock_validate.return_value = ([], [])

        args = argparse.Namespace(env_file='.env', quiet=False, validate_only=True)

        with self.assertRaises(SystemExit) as cm:
            manage_container.cmd_config(args)

        self.assertEqual(cm.exception.code, manage_container.EXIT_SUCCESS)

    @patch('manage_container.get_docker_client')
    @patch('manage_container.build_image')
    def test_cmd_build_success(self, mock_build, mock_client):
        """Test build command success."""
        mock_client.return_value = MagicMock()
        mock_build.return_value = True

        args = argparse.Namespace()

        with self.assertRaises(SystemExit) as cm:
            manage_container.cmd_build(args)

        self.assertEqual(cm.exception.code, manage_container.EXIT_SUCCESS)

    @patch('pathlib.Path.exists')
    def test_cmd_start_no_env_file(self, mock_exists):
        """Test start command without .env file."""
        mock_exists.return_value = False

        args = argparse.Namespace(yes=False)

        with self.assertRaises(SystemExit) as cm:
            manage_container.cmd_start(args)

        self.assertEqual(cm.exception.code, manage_container.EXIT_CONFIG_ERROR)


class TestMain(unittest.TestCase):
    """Test cases for main function."""

    @patch('sys.argv', ['manage_container.py', '--version'])
    def test_main_version(self):
        """Test --version flag."""
        with self.assertRaises(SystemExit) as cm:
            manage_container.main()

        self.assertEqual(cm.exception.code, 0)

    @patch('sys.argv', ['manage_container.py', 'build'])
    @patch('manage_container.cmd_build')
    def test_main_build_command(self, mock_cmd):
        """Test main calls build command."""
        manage_container.main()
        mock_cmd.assert_called_once()


class TestSimpleFallbackClasses(unittest.TestCase):
    """Test cases for simple fallback classes when rich is not available."""

    def test_simple_console_print(self):
        """Test SimpleConsole strips rich markup."""
        console = manage_container.SimpleConsole()
        # This should not raise an exception
        import io
        import sys
        captured_output = io.StringIO()
        sys.stdout = captured_output
        console.print("[bold]Test[/bold] [red]message[/red]")
        sys.stdout = sys.__stdout__
        output = captured_output.getvalue()
        # Rich markup should be stripped
        self.assertIn("Test message", output)
        self.assertNotIn("[bold]", output)
        self.assertNotIn("[red]", output)

    def test_simple_table_creation(self):
        """Test SimpleTable creates basic table output."""
        table = manage_container.SimpleTable(title="Test Table")
        table.add_column("Column1")
        table.add_column("Column2")
        table.add_row("Value1", "Value2")
        table.add_row("Value3", "Value4")

        output = str(table)
        self.assertIn("Test Table", output)
        self.assertIn("Column1", output)
        self.assertIn("Column2", output)
        self.assertIn("Value1", output)
        self.assertIn("Value2", output)

    def test_simple_table_with_console_print(self):
        """Test SimpleConsole can print SimpleTable objects."""
        console = manage_container.SimpleConsole()
        table = manage_container.SimpleTable(title="Test")
        table.add_column("Col1")
        table.add_row("Val1")

        import io
        import sys
        captured_output = io.StringIO()
        sys.stdout = captured_output
        console.print(table)
        sys.stdout = sys.__stdout__
        output = captured_output.getvalue()

        self.assertIn("Test", output)
        self.assertIn("Col1", output)
        self.assertIn("Val1", output)

    def test_simple_progress_context(self):
        """Test SimpleProgress works as context manager."""
        with manage_container.SimpleProgress() as progress:
            task = progress.add_task("Test task")
            self.assertIsNotNone(task)
            progress.update(task, completed=True)
        # Should not raise any exceptions

    def test_simple_prompt_with_choices(self):
        """Test SimplePrompt validates choices."""
        import io
        import sys

        # Mock user input
        sys.stdin = io.StringIO("1\n")
        result = manage_container.SimplePrompt.ask("Choose", choices=["1", "2"], default="2")
        sys.stdin = sys.__stdin__

        self.assertEqual(result, "1")

    def test_simple_prompt_default(self):
        """Test SimplePrompt returns default on empty input."""
        import io
        import sys

        # Mock empty input
        sys.stdin = io.StringIO("\n")
        result = manage_container.SimplePrompt.ask("Choose", choices=["1", "2"], default="2")
        sys.stdin = sys.__stdin__

        self.assertEqual(result, "2")


class TestFormatBytes(unittest.TestCase):
    """Test cases for format_bytes function."""

    def test_format_bytes_zero(self):
        """Test formatting zero bytes."""
        result = manage_container.format_bytes(0)
        self.assertEqual(result, "0.0 B")

    def test_format_bytes_kb(self):
        """Test formatting kilobytes."""
        result = manage_container.format_bytes(1500)
        self.assertEqual(result, "1.5 KB")

    def test_format_bytes_mb(self):
        """Test formatting megabytes."""
        result = manage_container.format_bytes(1500000)
        self.assertEqual(result, "1.4 MB")

    def test_format_bytes_gb(self):
        """Test formatting gigabytes."""
        result = manage_container.format_bytes(1500000000)
        self.assertEqual(result, "1.4 GB")

    def test_format_bytes_tb(self):
        """Test formatting terabytes."""
        result = manage_container.format_bytes(1500000000000)
        self.assertEqual(result, "1.4 TB")


class TestGetDirectorySize(unittest.TestCase):
    """Test cases for get_directory_size function."""

    @patch('manage_container.Path')
    def test_get_directory_size_not_exists(self, mock_path):
        """Test directory size when path doesn't exist."""
        mock_path_instance = MagicMock()
        mock_path_instance.exists.return_value = False
        mock_path.return_value = mock_path_instance

        result = manage_container.get_directory_size(mock_path_instance)
        self.assertEqual(result, "N/A (not created)")

    @patch('manage_container.format_bytes')
    @patch('manage_container.Path')
    def test_get_directory_size_exists(self, mock_path, mock_format):
        """Test directory size calculation."""
        mock_path_instance = MagicMock()
        mock_path_instance.exists.return_value = True

        # Mock files with sizes
        mock_file1 = MagicMock()
        mock_file1.is_file.return_value = True
        mock_file1.stat.return_value.st_size = 1000

        mock_file2 = MagicMock()
        mock_file2.is_file.return_value = True
        mock_file2.stat.return_value.st_size = 2000

        mock_path_instance.rglob.return_value = [mock_file1, mock_file2]
        mock_format.return_value = "3.0 KB"

        result = manage_container.get_directory_size(mock_path_instance)
        mock_format.assert_called_once_with(3000)
        self.assertEqual(result, "3.0 KB")


class TestGetDiskSpace(unittest.TestCase):
    """Test cases for get_disk_space function."""

    @patch('shutil.disk_usage')
    def test_get_disk_space_success(self, mock_disk_usage):
        """Test getting disk space."""
        mock_disk_usage.return_value = MagicMock(total=10000000000, used=4000000000, free=6000000000)

        available, total, percent_used = manage_container.get_disk_space(Path("/test/path"))
        self.assertIn("GB", available)
        self.assertIn("GB", total)
        self.assertAlmostEqual(percent_used, 40.0, places=1)


class TestGetHostIP(unittest.TestCase):
    """Test cases for get_host_ip function."""

    @patch('manage_container.socket.socket')
    def test_get_host_ip_success(self, mock_socket):
        """Test getting host IP address."""
        mock_sock = MagicMock()
        mock_sock.getsockname.return_value = ('192.168.1.100', 0)
        mock_socket.return_value.__enter__.return_value = mock_sock

        result = manage_container.get_host_ip()
        self.assertEqual(result, '192.168.1.100')

    @patch('manage_container.socket.socket')
    def test_get_host_ip_failure(self, mock_socket):
        """Test getting host IP when socket fails."""
        mock_socket.return_value.__enter__.side_effect = Exception("Socket error")

        result = manage_container.get_host_ip()
        self.assertEqual(result, '127.0.0.1')


class TestCheckFilePermissions(unittest.TestCase):
    """Test cases for check_file_permissions function."""

    @patch('manage_container.Path')
    def test_check_file_permissions_not_exists(self, mock_path):
        """Test file permissions when file doesn't exist."""
        mock_path_instance = MagicMock()
        mock_path_instance.stat.side_effect = Exception("File not found")

        perms, is_secure = manage_container.check_file_permissions(mock_path_instance)
        self.assertEqual(perms, "Unknown")
        self.assertFalse(is_secure)

    @patch('manage_container.Path')
    def test_check_file_permissions_secure(self, mock_path):
        """Test file permissions when secure."""
        mock_path_instance = MagicMock()
        mock_stat = MagicMock()
        mock_stat.st_mode = 0o100600  # 600 permissions
        mock_path_instance.stat.return_value = mock_stat

        perms, is_secure = manage_container.check_file_permissions(mock_path_instance)
        self.assertEqual(perms, "600")
        self.assertTrue(is_secure)

    @patch('manage_container.Path')
    def test_check_file_permissions_insecure(self, mock_path):
        """Test file permissions when insecure."""
        mock_path_instance = MagicMock()
        mock_stat = MagicMock()
        mock_stat.st_mode = 0o100755  # 755 permissions
        mock_path_instance.stat.return_value = mock_stat

        perms, is_secure = manage_container.check_file_permissions(mock_path_instance)
        self.assertEqual(perms, "755")
        self.assertFalse(is_secure)


class TestValidationFunctions(unittest.TestCase):
    """Test cases for validation functions."""

    def test_validate_required_fields_missing_gitlab_url(self):
        """Test validation with missing GitLab URL."""
        config = {'GITLAB_TOKEN': 'test'}
        errors, warnings = manage_container.validate_required_fields(config)
        self.assertIn("GITLAB_URL is not set (required)", errors)

    def test_validate_required_fields_missing_token(self):
        """Test validation with missing GitLab token."""
        config = {'GITLAB_URL': 'https://gitlab.com'}
        errors, warnings = manage_container.validate_required_fields(config)
        self.assertIn("GITLAB_TOKEN is not set (required)", errors)

    def test_validate_required_fields_valid(self):
        """Test validation with valid required fields."""
        config = {'GITLAB_URL': 'https://gitlab.com', 'GITLAB_TOKEN': 'test', 'WEBHOOK_SECRET': 'secret'}
        errors, warnings = manage_container.validate_required_fields(config)
        self.assertEqual(len(errors), 0)

    def test_validate_logging_config_invalid_level(self):
        """Test validation with invalid log level."""
        config = {
            'LOG_LEVEL': 'INVALID',
            'LOG_OUTPUT_DIR': './logs',
            'WEBHOOK_PORT': '8000',
            'RETRY_ATTEMPTS': '3',
            'RETRY_DELAY': '2'
        }
        errors, warnings = manage_container.validate_logging_config(config)
        self.assertTrue(len(errors) > 0)
        self.assertTrue(any('LOG_LEVEL' in str(e) and 'invalid' in str(e).lower() for e in errors))

    def test_validate_api_config_enabled_missing_url(self):
        """Test API validation when enabled but BFA_HOST missing."""
        config = {'API_POST_ENABLED': 'true'}
        errors, warnings = manage_container.validate_api_config(config)
        self.assertIn("API_POST_ENABLED is true but BFA_HOST is not set", errors)

    @patch('manage_container.Path')
    def test_validate_jenkins_config_multi_instance(self, mock_path):
        """Test Jenkins validation with jenkins_instances.json."""
        mock_path_instance = MagicMock()
        mock_path_instance.exists.return_value = True
        mock_path.return_value = mock_path_instance

        config = {'JENKINS_ENABLED': 'true'}
        errors, warnings = manage_container.validate_jenkins_config(config)
        # Should not have errors about missing JENKINS_URL, etc. when using multi-instance
        self.assertFalse(any('JENKINS_URL' in str(e) for e in errors))

    def test_validate_log_filters_invalid_status(self):
        """Test log filter validation with invalid status."""
        config = {'LOG_SAVE_PIPELINE_STATUS': 'invalid_status'}
        errors, warnings = manage_container.validate_log_filters(config)
        self.assertTrue(len(warnings) > 0 or len(errors) > 0)

    @patch('shutil.disk_usage')
    def test_validate_system_resources_low_space(self, mock_disk):
        """Test system validation with low disk space."""
        mock_disk.return_value = MagicMock(total=10000000000, free=500000000)  # < 1GB free
        config = {'LOG_OUTPUT_DIR': './logs'}
        errors, warnings = manage_container.validate_system_resources(config)
        self.assertTrue(any('disk space' in str(w).lower() for w in warnings))


class TestShowFunctions(unittest.TestCase):
    """Test cases for show_* functions."""

    @patch('manage_container.console')
    def test_show_endpoints(self, mock_console):
        """Test showing endpoints."""
        manage_container.show_endpoints(8000)
        # Should print endpoints table
        self.assertTrue(mock_console.print.called)

    @patch('manage_container.console')
    def test_show_endpoints_with_host(self, mock_console):
        """Test showing endpoints with custom host."""
        manage_container.show_endpoints(8000, host='192.168.1.100')
        self.assertTrue(mock_console.print.called)

    @patch('manage_container.console')
    def test_show_validation_results_no_issues(self, mock_console):
        """Test showing validation results with no issues."""
        manage_container.show_validation_results([], [])
        # Should not print any errors or warnings sections
        calls = [str(call) for call in mock_console.print.call_args_list]
        self.assertFalse(any('ERRORS' in str(c) for c in calls))

    @patch('manage_container.console')
    def test_show_validation_results_with_errors(self, mock_console):
        """Test showing validation results with errors."""
        manage_container.show_validation_results(['Error 1', 'Error 2'], [])
        calls = [str(call) for call in mock_console.print.call_args_list]
        self.assertTrue(any('ERRORS' in str(c) for c in calls))

    @patch('manage_container.console')
    def test_show_validation_results_with_warnings(self, mock_console):
        """Test showing validation results with warnings."""
        manage_container.show_validation_results([], ['Warning 1'])
        calls = [str(call) for call in mock_console.print.call_args_list]
        self.assertTrue(any('WARNINGS' in str(c) for c in calls))


class TestTestWebhookWithHostIP(unittest.TestCase):
    """Test cases for test_webhook function with host IP."""

    @patch('manage_container.requests.post')
    @patch('manage_container.get_host_ip')
    @patch('manage_container.get_port_from_config')
    @patch('manage_container.console')
    def test_webhook_success(self, mock_console, mock_port, mock_host, mock_post):
        """Test webhook test with success response."""
        mock_port.return_value = 8000
        mock_host.return_value = 'localhost'
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "success"}
        mock_post.return_value = mock_response

        result = manage_container.test_webhook()
        self.assertTrue(result)

    @patch('manage_container.requests.post')
    @patch('manage_container.get_host_ip')
    @patch('manage_container.get_port_from_config')
    @patch('manage_container.console')
    def test_webhook_failure(self, mock_console, mock_port, mock_host, mock_post):
        """Test webhook test with failure response."""
        mock_port.return_value = 8000
        mock_host.return_value = 'localhost'
        mock_post.side_effect = Exception("Connection error")

        result = manage_container.test_webhook()
        self.assertFalse(result)

    @patch('manage_container.requests.post')
    @patch('manage_container.get_host_ip')
    @patch('manage_container.get_port_from_config')
    @patch('manage_container.console')
    def test_webhook_connection_error(self, mock_console, mock_port, mock_host, mock_post):
        """Test webhook test with connection error."""
        mock_port.return_value = 8000
        mock_host.return_value = 'localhost'
        mock_post.side_effect = Exception("Connection refused")

        result = manage_container.test_webhook()
        self.assertFalse(result)


class TestExportMonitoringDataWithHostIP(unittest.TestCase):
    """Test cases for export_monitoring_data function with host IP."""

    @patch('manage_container.requests.get')
    @patch('manage_container.get_host_ip')
    @patch('manage_container.get_port_from_config')
    @patch('manage_container.console')
    def test_export_failure(self, mock_console, mock_port, mock_host, mock_get):
        """Test export when request fails."""
        mock_port.return_value = 8000
        mock_host.return_value = 'localhost'
        mock_get.side_effect = Exception("Connection error")

        result = manage_container.export_monitoring_data('test.csv')
        self.assertFalse(result)

    @patch('builtins.open', new_callable=MagicMock)
    @patch('manage_container.requests.get')
    @patch('manage_container.get_host_ip')
    @patch('manage_container.get_port_from_config')
    @patch('manage_container.console')
    def test_export_success(self, mock_console, mock_port, mock_host, mock_get, mock_open):
        """Test successful export."""
        mock_port.return_value = 8000
        mock_host.return_value = 'localhost'
        mock_response = MagicMock()
        mock_response.text = "csv,data,here"
        mock_get.return_value = mock_response

        result = manage_container.export_monitoring_data('test.csv')
        self.assertTrue(result)


class TestCreateConfigTable(unittest.TestCase):
    """Test cases for create_config_table function."""

    def test_create_config_table_rich_available(self):
        """Test creating config table when rich is available."""
        table = manage_container.create_config_table("Test Title")
        self.assertIsNotNone(table)

    def test_create_config_table_adds_columns(self):
        """Test that config table has required columns."""
        table = manage_container.create_config_table("Test Title")
        # Should be able to add rows to the table
        table.add_row("Setting", "Value")


class TestShowConfigTable(unittest.TestCase):
    """Test cases for show_config_table function."""

    @patch('manage_container.console')
    def test_show_config_table_quiet_mode(self, mock_console):
        """Test show_config_table in quiet mode."""
        config = {'GITLAB_URL': 'https://gitlab.com', 'GITLAB_TOKEN': 'token'}
        manage_container.show_config_table(config, quiet=True)
        # In quiet mode, should not print anything
        mock_console.print.assert_not_called()

    @patch('manage_container.console')
    @patch('manage_container.create_config_table')
    def test_show_config_table_basic(self, mock_create_table, mock_console):
        """Test show_config_table with basic config."""
        config = {
            'GITLAB_URL': 'https://gitlab.com',
            'GITLAB_TOKEN': 'test_token',
            'WEBHOOK_PORT': '8000',
            'LOG_LEVEL': 'INFO',
            'LOG_OUTPUT_DIR': './logs'
        }
        mock_table = MagicMock()
        mock_create_table.return_value = mock_table

        manage_container.show_config_table(config, quiet=False)

        # Should create tables and print them
        self.assertTrue(mock_create_table.called)
        self.assertTrue(mock_console.print.called)

    @patch('manage_container.console')
    @patch('manage_container.create_config_table')
    def test_show_config_table_with_api_enabled(self, mock_create_table, mock_console):
        """Test show_config_table with API posting enabled."""
        config = {
            'GITLAB_URL': 'https://gitlab.com',
            'GITLAB_TOKEN': 'token',
            'API_POST_ENABLED': 'true',
            'BFA_HOST': 'localhost',
            'BFA_SECRET_KEY': 'secret'
        }
        mock_table = MagicMock()
        mock_create_table.return_value = mock_table

        manage_container.show_config_table(config, quiet=False)

        # Should show API configuration section
        self.assertTrue(mock_create_table.called)

    @patch('manage_container.console')
    @patch('manage_container.create_config_table')
    def test_show_config_table_with_jenkins_enabled(self, mock_create_table, mock_console):
        """Test show_config_table with Jenkins integration enabled."""
        config = {
            'GITLAB_URL': 'https://gitlab.com',
            'GITLAB_TOKEN': 'token',
            'JENKINS_ENABLED': 'true',
            'JENKINS_URL': 'http://jenkins.local',
            'JENKINS_USER': 'admin',
            'JENKINS_API_TOKEN': 'jenkins_token'
        }
        mock_table = MagicMock()
        mock_create_table.return_value = mock_table

        manage_container.show_config_table(config, quiet=False)

        # Should show Jenkins configuration section
        self.assertTrue(mock_create_table.called)


class TestBuildImageEdgeCases(unittest.TestCase):
    """Test edge cases for build_image function."""

    @patch('manage_container.subprocess.run')
    @patch('manage_container.Progress')
    @patch('manage_container.os.environ.get')
    @patch('manage_container.os.path.abspath')
    @patch('manage_container.console')
    def test_build_image_os_error(self, mock_console, mock_abspath, mock_env_get, mock_progress, mock_subprocess):
        """Test build image with OSError."""
        mock_abspath.return_value = '/current/dir'
        mock_env_get.side_effect = lambda k, d=None: d

        mock_progress_instance = MagicMock()
        mock_progress.return_value.__enter__.return_value = mock_progress_instance

        mock_subprocess.side_effect = OSError("Docker command not found")

        result = manage_container.build_image(MagicMock())
        self.assertFalse(result)


class TestStartContainerEdgeCases(unittest.TestCase):
    """Test edge cases for start_container function."""

    @patch('manage_container.container_exists')
    @patch('manage_container.container_running')
    @patch('manage_container.console')
    def test_start_container_exists_but_not_running(self, mock_console, mock_running, mock_exists):
        """Test starting container that exists but is not running."""
        mock_exists.return_value = True
        mock_running.return_value = False

        mock_client = MagicMock()
        mock_container = MagicMock()
        mock_client.containers.get.return_value = mock_container

        config = {
            'GITLAB_URL': 'https://gitlab.com',
            'GITLAB_TOKEN': 'token',
            'DOCKER_IMAGE_NAME': 'bfa-gitlab-pipeline-extractor',
            'DOCKER_CONTAINER_NAME': 'bfa-gitlab-pipeline-extractor',
            'DOCKER_LOGS_DIR': './logs',
            'WEBHOOK_PORT': '8000'
        }
        result = manage_container.start_container(mock_client, config, skip_confirm=True)

        # Should start the existing container
        mock_container.start.assert_called_once()
        self.assertTrue(result)


class TestShowLogsEdgeCases(unittest.TestCase):
    """Test edge cases for show_logs function."""

    @patch('manage_container.console')
    @patch('manage_container.container_exists')
    def test_show_logs_container_not_exists(self, mock_exists, mock_console):
        """Test showing logs when container doesn't exist."""
        mock_exists.return_value = False
        mock_client = MagicMock()

        result = manage_container.show_logs(mock_client, follow=False)
        self.assertFalse(result)

    @patch('manage_container.console')
    def test_show_logs_keyboard_interrupt_outer(self, mock_console):
        """Test show_logs with keyboard interrupt in outer catch."""
        mock_client = MagicMock()
        mock_client.containers.get.side_effect = KeyboardInterrupt()

        # Should catch KeyboardInterrupt gracefully
        result = manage_container.show_logs(mock_client, follow=True)
        self.assertTrue(result)


class TestRemoveContainerEdgeCases(unittest.TestCase):
    """Test edge cases for remove_container function."""

    @patch('manage_container.load_config')
    @patch('manage_container.container_exists')
    @patch('manage_container.console')
    def test_remove_container_force_running(self, mock_console, mock_exists, mock_load_config):
        """Test removing running container with force."""
        mock_load_config.return_value = {
            'DOCKER_IMAGE_NAME': 'bfa-gitlab-pipeline-extractor',
            'DOCKER_LOGS_DIR': './logs'
        }
        mock_exists.return_value = True
        mock_client = MagicMock()
        mock_container = MagicMock()
        mock_container.status = 'running'
        mock_client.containers.get.return_value = mock_container

        result = manage_container.remove_container(mock_client, force=True, force_remove=True)

        # Should remove with force without stopping first
        mock_container.remove.assert_called_once_with(force=True)
        self.assertTrue(result)

    @patch('manage_container.load_config')
    @patch('manage_container.Prompt')
    @patch('manage_container.container_exists')
    @patch('manage_container.console')
    def test_remove_container_stop_fails(self, mock_console, mock_exists, mock_prompt, mock_load_config):
        """Test removing container when stop fails."""
        mock_load_config.return_value = {
            'DOCKER_IMAGE_NAME': 'bfa-gitlab-pipeline-extractor',
            'DOCKER_LOGS_DIR': './logs'
        }
        mock_exists.return_value = True
        mock_prompt.ask.return_value = "1"  # Choose force remove option
        mock_client = MagicMock()
        mock_container = MagicMock()
        mock_container.status = 'running'
        mock_container.stop.side_effect = Exception("Stop failed")
        mock_client.containers.get.return_value = mock_container

        result = manage_container.remove_container(mock_client, force=False, force_remove=False)

        # Should prompt user and then remove with force
        self.assertTrue(mock_prompt.ask.called)
        self.assertTrue(result)


class TestCmdFunctionsExtended(unittest.TestCase):
    """Extended test cases for CLI command functions."""

    @patch('sys.exit', side_effect=SystemExit)
    @patch('manage_container.get_docker_client')
    @patch('manage_container.build_image')
    @patch('manage_container.console')
    def test_cmd_build_with_docker_client_failure(self, mock_console, mock_build, mock_client, mock_exit):
        """Test cmd_build when docker client fails."""
        mock_client.return_value = None
        args = MagicMock()

        with self.assertRaises(SystemExit):
            manage_container.cmd_build(args)
        mock_build.assert_not_called()
        mock_exit.assert_called_once_with(3)

    @patch('sys.exit')
    @patch('manage_container.get_docker_client')
    @patch('manage_container.load_config')
    @patch('manage_container.start_container')
    @patch('manage_container.console')
    def test_cmd_start_with_config(self, mock_console, mock_start, mock_config, mock_client, mock_exit):
        """Test cmd_start with valid config."""
        args = MagicMock()
        args.env_file = '.env'
        args.yes = True
        mock_client.return_value = MagicMock()
        mock_config.return_value = {
            'GITLAB_URL': 'https://gitlab.com',
            'GITLAB_TOKEN': 'token',
            'DOCKER_IMAGE_NAME': 'bfa-gitlab-pipeline-extractor',
            'DOCKER_CONTAINER_NAME': 'bfa-gitlab-pipeline-extractor',
            'DOCKER_LOGS_DIR': './logs',
            'WEBHOOK_PORT': '8000',
            'LOG_LEVEL': 'INFO',
            'LOG_OUTPUT_DIR': './logs',
            'RETRY_ATTEMPTS': '3',
            'RETRY_DELAY': '2'
        }
        mock_start.return_value = True

        manage_container.cmd_start(args)
        mock_start.assert_called_once()
        # Should call sys.exit with 0 eventually
        self.assertTrue(mock_exit.called)

    @patch('sys.exit')
    @patch('manage_container.get_docker_client')
    @patch('manage_container.stop_container')
    @patch('manage_container.console')
    def test_cmd_stop_success(self, mock_console, mock_stop, mock_client, mock_exit):
        """Test cmd_stop successful execution."""
        args = MagicMock()
        mock_client.return_value = MagicMock()
        mock_stop.return_value = True

        manage_container.cmd_stop(args)
        mock_stop.assert_called_once()
        mock_exit.assert_called_once_with(0)

    @patch('sys.exit', side_effect=SystemExit)
    @patch('manage_container.get_docker_client')
    @patch('manage_container.stop_container')
    @patch('manage_container.console')
    def test_cmd_stop_no_client(self, mock_console, mock_stop, mock_client, mock_exit):
        """Test cmd_stop when docker client fails."""
        args = MagicMock()
        mock_client.return_value = None

        with self.assertRaises(SystemExit):
            manage_container.cmd_stop(args)
        mock_stop.assert_not_called()
        mock_exit.assert_called_once_with(3)

    @patch('sys.exit')
    @patch('manage_container.get_docker_client')
    @patch('manage_container.load_config')
    @patch('manage_container.restart_container')
    @patch('manage_container.console')
    def test_cmd_restart_success(self, mock_console, mock_restart, mock_config, mock_client, mock_exit):
        """Test cmd_restart successful execution."""
        args = MagicMock()
        args.env_file = '.env'
        mock_client.return_value = MagicMock()
        mock_config.return_value = {'GITLAB_URL': 'https://gitlab.com'}
        mock_restart.return_value = True

        manage_container.cmd_restart(args)
        mock_restart.assert_called_once()
        mock_exit.assert_called_once_with(0)

    @patch('sys.exit', side_effect=SystemExit)
    @patch('manage_container.get_docker_client')
    @patch('manage_container.show_logs')
    @patch('manage_container.console')
    def test_cmd_logs_follow(self, mock_console, mock_logs, mock_client, mock_exit):
        """Test cmd_logs with follow option."""
        args = MagicMock()
        args.follow = True
        mock_client.return_value = MagicMock()
        mock_logs.return_value = True

        with self.assertRaises(SystemExit):
            manage_container.cmd_logs(args)
        # Check that show_logs was called with correct args
        call_args = mock_logs.call_args
        self.assertEqual(call_args[0][1], True)  # follow=True
        # Should call sys.exit
        self.assertTrue(mock_exit.called)

    @patch('sys.exit')
    @patch('manage_container.get_docker_client')
    @patch('manage_container.show_status')
    @patch('manage_container.console')
    def test_cmd_status_success(self, mock_console, mock_status, mock_client, mock_exit):
        """Test cmd_status successful execution."""
        args = MagicMock()
        mock_client.return_value = MagicMock()
        mock_status.return_value = True

        manage_container.cmd_status(args)
        mock_status.assert_called_once()
        mock_exit.assert_called_once_with(0)

    @patch('sys.exit')
    @patch('manage_container.get_docker_client')
    @patch('manage_container.remove_container')
    @patch('manage_container.console')
    def test_cmd_remove_with_force(self, mock_console, mock_remove, mock_client, mock_exit):
        """Test cmd_remove with force option."""
        args = MagicMock()
        args.force = True
        mock_client.return_value = MagicMock()
        mock_remove.return_value = True

        manage_container.cmd_remove(args)
        mock_remove.assert_called_once()
        mock_exit.assert_called_once_with(0)

    @patch('sys.exit')
    @patch('manage_container.get_docker_client')
    @patch('manage_container.show_monitor')
    @patch('manage_container.console')
    def test_cmd_monitor_success(self, mock_console, mock_monitor, mock_client, mock_exit):
        """Test cmd_monitor successful execution."""
        args = MagicMock()
        args.args = []
        mock_client.return_value = MagicMock()
        mock_monitor.return_value = True

        manage_container.cmd_monitor(args)
        mock_monitor.assert_called_once()
        mock_exit.assert_called_once_with(0)

    @patch('sys.exit')
    @patch('manage_container.export_monitoring_data')
    @patch('manage_container.console')
    def test_cmd_export_with_filename(self, mock_console, mock_export, mock_exit):
        """Test cmd_export with custom filename."""
        args = MagicMock()
        args.filename = 'custom.csv'
        mock_export.return_value = True

        manage_container.cmd_export(args)
        mock_export.assert_called_once_with('custom.csv')
        mock_exit.assert_called_once_with(0)

    @patch('sys.exit')
    @patch('manage_container.test_webhook')
    @patch('manage_container.console')
    def test_cmd_test_success(self, mock_console, mock_test, mock_exit):
        """Test cmd_test successful execution."""
        args = MagicMock()
        mock_test.return_value = True

        manage_container.cmd_test(args)
        mock_test.assert_called_once()
        mock_exit.assert_called_once_with(0)


class TestMainFunction(unittest.TestCase):
    """Test cases for main function."""

    @patch('sys.argv', ['manage_container.py', 'config', '--env-file', '.env'])
    @patch('manage_container.cmd_config')
    def test_main_config_command_routing(self, mock_cmd_config):
        """Test main routes to config command."""
        manage_container.main()
        mock_cmd_config.assert_called_once()

    @patch('sys.argv', ['manage_container.py', 'build'])
    @patch('manage_container.cmd_build')
    def test_main_build_command_routing(self, mock_cmd_build):
        """Test main routes to build command."""
        manage_container.main()
        mock_cmd_build.assert_called_once()

    @patch('sys.argv', ['manage_container.py', 'start'])
    @patch('manage_container.cmd_start')
    def test_main_start_command_routing(self, mock_cmd_start):
        """Test main routes to start command."""
        manage_container.main()
        mock_cmd_start.assert_called_once()


class TestShowStatusExtended(unittest.TestCase):
    """Extended test cases for show_status function."""

    @patch('manage_container.console')
    def test_show_status_exited_container(self, mock_console):
        """Test showing status of exited container."""
        mock_client = MagicMock()
        mock_container = MagicMock()
        mock_container.status = 'exited'
        mock_container.attrs = {
            'State': {
                'Status': 'exited',
                'ExitCode': 0,
                'StartedAt': '2024-01-01T10:00:00.000000000Z',
                'FinishedAt': '2024-01-01T10:05:00.000000000Z'
            },
            'Config': {
                'Image': 'test:latest'
            }
        }
        mock_client.containers.get.return_value = mock_container

        result = manage_container.show_status(mock_client)
        self.assertTrue(result)

    @patch('manage_container.console')
    def test_show_status_created_container(self, mock_console):
        """Test showing status of created but not started container."""
        mock_client = MagicMock()
        mock_container = MagicMock()
        mock_container.status = 'created'
        mock_container.attrs = {
            'State': {
                'Status': 'created',
                'StartedAt': '0001-01-01T00:00:00Z'
            },
            'Config': {
                'Image': 'test:latest'
            }
        }
        mock_client.containers.get.return_value = mock_container

        result = manage_container.show_status(mock_client)
        self.assertTrue(result)


class TestBuildImageExtended(unittest.TestCase):
    """Extended test cases for build_image function."""

    @patch('manage_container.subprocess.run')
    @patch('manage_container.Progress')
    @patch('manage_container.os.environ.get')
    @patch('manage_container.os.path.abspath')
    @patch('manage_container.console')
    def test_build_image_with_output(self, mock_console, mock_abspath, mock_env_get, mock_progress, mock_subprocess):
        """Test build image with subprocess output."""
        mock_abspath.return_value = '/current/dir'
        mock_env_get.side_effect = lambda k, d=None: d

        mock_progress_instance = MagicMock()
        mock_progress.return_value.__enter__.return_value = mock_progress_instance

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = "Build output"
        mock_result.stderr = "Build errors"
        mock_subprocess.return_value = mock_result

        result = manage_container.build_image(MagicMock())
        self.assertFalse(result)


class TestValidationFunctionsEdgeCases(unittest.TestCase):
    """Test edge cases for validation functions."""

    def test_validate_logging_config_invalid_port(self):
        """Test logging validation with invalid port."""
        config = {
            'WEBHOOK_PORT': 'abc',
            'LOG_LEVEL': 'INFO',
            'LOG_OUTPUT_DIR': './logs',
            'RETRY_ATTEMPTS': '3',
            'RETRY_DELAY': '2'
        }
        errors, warnings = manage_container.validate_logging_config(config)
        self.assertTrue(any('not a valid number' in str(e) for e in errors))

    def test_validate_logging_config_port_out_of_range(self):
        """Test logging validation with port out of range."""
        config = {
            'WEBHOOK_PORT': '70000',
            'LOG_LEVEL': 'INFO',
            'LOG_OUTPUT_DIR': './logs',
            'RETRY_ATTEMPTS': '3',
            'RETRY_DELAY': '2'
        }
        errors, warnings = manage_container.validate_logging_config(config)
        self.assertTrue(any('out of valid range' in str(e) for e in errors))

    def test_validate_logging_config_negative_retry(self):
        """Test logging validation with negative retry attempts."""
        config = {
            'RETRY_ATTEMPTS': '-1',
            'LOG_LEVEL': 'INFO',
            'LOG_OUTPUT_DIR': './logs',
            'WEBHOOK_PORT': '8000',
            'RETRY_DELAY': '2'
        }
        errors, warnings = manage_container.validate_logging_config(config)
        self.assertTrue(any('cannot be negative' in str(e) for e in errors))

    def test_validate_logging_config_invalid_retry_delay(self):
        """Test logging validation with invalid retry delay."""
        config = {
            'RETRY_DELAY': 'abc',
            'LOG_LEVEL': 'INFO',
            'LOG_OUTPUT_DIR': './logs',
            'WEBHOOK_PORT': '8000',
            'RETRY_ATTEMPTS': '3'
        }
        errors, warnings = manage_container.validate_logging_config(config)
        self.assertTrue(any('not a valid number' in str(e) for e in errors))

    def test_validate_api_config_low_timeout(self):
        """Test API validation with low timeout."""
        config = {'API_POST_ENABLED': 'true', 'BFA_HOST': 'localhost', 'API_POST_TIMEOUT': '0'}
        errors, warnings = manage_container.validate_api_config(config)
        self.assertTrue(any('at least 1 second' in str(w) for w in warnings))

    def test_validate_api_config_high_timeout(self):
        """Test API validation with very high timeout."""
        config = {'API_POST_ENABLED': 'true', 'BFA_HOST': 'localhost', 'API_POST_TIMEOUT': '400'}
        errors, warnings = manage_container.validate_api_config(config)
        self.assertTrue(any('>300s' in str(w) for w in warnings))

    def test_validate_api_config_invalid_timeout(self):
        """Test API validation with invalid timeout."""
        config = {'API_POST_ENABLED': 'true', 'BFA_HOST': 'localhost', 'API_POST_TIMEOUT': 'abc'}
        errors, warnings = manage_container.validate_api_config(config)
        self.assertTrue(any('not a valid number' in str(w) for w in warnings))

    @patch('manage_container.Path')
    def test_validate_jenkins_config_single_instance_missing_url(self, mock_path):
        """Test Jenkins validation with single instance missing URL."""
        mock_path_instance = MagicMock()
        mock_path_instance.exists.return_value = False
        mock_path.return_value = mock_path_instance

        config = {'JENKINS_ENABLED': 'true'}
        errors, warnings = manage_container.validate_jenkins_config(config)
        self.assertTrue(any('JENKINS_URL' in str(e) for e in errors))

    @patch('manage_container.Path')
    def test_validate_jenkins_config_single_instance_missing_user(self, mock_path):
        """Test Jenkins validation with single instance missing user."""
        mock_path_instance = MagicMock()
        mock_path_instance.exists.return_value = False
        mock_path.return_value = mock_path_instance

        config = {'JENKINS_ENABLED': 'true', 'JENKINS_URL': 'http://jenkins'}
        errors, warnings = manage_container.validate_jenkins_config(config)
        self.assertTrue(any('JENKINS_USER' in str(e) for e in errors))

    def test_validate_log_filters_invalid_pipeline_status(self):
        """Test log filter validation with invalid pipeline status."""
        config = {'LOG_SAVE_PIPELINE_STATUS': 'invalid'}
        errors, warnings = manage_container.validate_log_filters(config)
        self.assertTrue(any('LOG_SAVE_PIPELINE_STATUS' in str(w) and 'invalid' in str(w) for w in warnings))

    def test_validate_log_filters_invalid_job_status(self):
        """Test log filter validation with invalid job status."""
        config = {'LOG_SAVE_JOB_STATUS': 'invalid'}
        errors, warnings = manage_container.validate_log_filters(config)
        self.assertTrue(any('LOG_SAVE_JOB_STATUS' in str(w) and 'invalid' in str(w) for w in warnings))

    @patch('manage_container.os.access')
    @patch('manage_container.Path')
    def test_validate_system_resources_log_dir_not_writable(self, mock_path, mock_access):
        """Test system validation with non-writable log directory."""
        mock_path_instance = MagicMock()
        mock_path_instance.exists.return_value = True
        mock_path.return_value = mock_path_instance
        mock_access.return_value = False

        config = {'LOG_OUTPUT_DIR': '/test/logs'}
        errors, warnings = manage_container.validate_system_resources(config)
        self.assertTrue(any('not writable' in str(e) for e in errors))

    @patch('manage_container.Path')
    def test_validate_system_resources_env_file_insecure(self, mock_path):
        """Test system validation with insecure .env file permissions."""
        # Mock the .env file
        mock_env_file = MagicMock()
        mock_env_file.exists.return_value = True
        mock_stat = MagicMock()
        mock_stat.st_mode = 0o100644  # 644 permissions (insecure)
        mock_env_file.stat.return_value = mock_stat

        # Mock Path() call for .env file
        def path_side_effect(arg):
            if arg == manage_container.ENV_FILE:
                return mock_env_file
            return MagicMock(exists=MagicMock(return_value=False))

        mock_path.side_effect = path_side_effect

        config = {}
        errors, warnings = manage_container.validate_system_resources(config)
        self.assertTrue(any('insecure permissions' in str(w) for w in warnings))


class TestCmdFunctionsErrorPaths(unittest.TestCase):
    """Test error paths for cmd functions."""

    @patch('sys.exit', side_effect=SystemExit)
    @patch('manage_container.console')
    @patch('manage_container.load_config')
    def test_cmd_config_no_file(self, mock_config, mock_console, mock_exit):
        """Test cmd_config when .env file doesn't exist."""
        args = MagicMock()
        args.env_file = '.env'
        args.quiet = False
        mock_config.return_value = None

        with self.assertRaises(SystemExit):
            manage_container.cmd_config(args)

    @patch('sys.exit', side_effect=SystemExit)
    @patch('manage_container.validate_config')
    @patch('manage_container.load_config')
    @patch('manage_container.console')
    def test_cmd_config_with_errors(self, mock_console, mock_config, mock_validate, mock_exit):
        """Test cmd_config with validation errors."""
        args = MagicMock()
        args.env_file = '.env'
        args.quiet = False
        mock_config.return_value = {'GITLAB_URL': 'https://gitlab.com'}
        mock_validate.return_value = (['Error 1'], [])

        with self.assertRaises(SystemExit):
            manage_container.cmd_config(args)
        # Should exit with error
        mock_exit.assert_called()

    @patch('sys.exit', side_effect=SystemExit)
    @patch('manage_container.get_docker_client')
    @patch('manage_container.load_config')
    @patch('manage_container.console')
    def test_cmd_start_no_env_file(self, mock_console, mock_config, mock_client, mock_exit):
        """Test cmd_start when .env file doesn't exist."""
        args = MagicMock()
        args.env_file = '.env'
        mock_config.return_value = None

        with self.assertRaises(SystemExit):
            manage_container.cmd_start(args)

    @patch('sys.exit', side_effect=SystemExit)
    @patch('manage_container.get_docker_client')
    @patch('manage_container.load_config')
    @patch('manage_container.console')
    def test_cmd_restart_no_env_file(self, mock_console, mock_config, mock_client, mock_exit):
        """Test cmd_restart when .env file doesn't exist."""
        args = MagicMock()
        args.env_file = '.env'
        mock_config.return_value = None

        with self.assertRaises(SystemExit):
            manage_container.cmd_restart(args)


class TestHelperFunctionEdgeCases(unittest.TestCase):
    """Test edge cases for helper functions."""

    def test_get_directory_size_error(self):
        """Test get_directory_size with error."""
        mock_path_instance = MagicMock()
        mock_path_instance.exists.return_value = True
        mock_path_instance.rglob.side_effect = Exception("Permission denied")

        result = manage_container.get_directory_size(mock_path_instance)
        self.assertEqual(result, "Unknown")

    def test_get_disk_space_error(self):
        """Test get_disk_space with error."""
        # Pass a path that will cause shutil to fail
        result = manage_container.get_disk_space(Path("/nonexistent/path"))
        # Should return default values on error
        self.assertEqual(result[0], "Unknown")
        self.assertEqual(result[1], "Unknown")
        self.assertEqual(result[2], 0.0)


class TestConfirmActionEdgeCases(unittest.TestCase):
    """Test edge cases for confirm_action function."""

    @patch('manage_container.Prompt')
    def test_confirm_action_eoferror(self, mock_prompt):
        """Test confirm_action with EOFError."""
        mock_prompt.ask.side_effect = EOFError()

        result = manage_container.confirm_action("Test?")
        self.assertFalse(result)


if __name__ == '__main__':
    unittest.main()
