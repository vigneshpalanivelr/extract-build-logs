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
        """Test loading config applies defaults for missing values."""
        mock_exists.return_value = True
        mock_dotenv.return_value = {
            'GITLAB_URL': 'https://gitlab.com',
            'GITLAB_TOKEN': 'glpat-test123',
        }

        result = manage_container.load_config(Path('.env'))

        self.assertEqual(result['WEBHOOK_PORT'], '8000')
        self.assertEqual(result['LOG_LEVEL'], 'INFO')
        self.assertEqual(result['LOG_OUTPUT_DIR'], './logs')


class TestValidateConfig(unittest.TestCase):
    """Test cases for validate_config function."""

    @patch('pathlib.Path.exists')
    def test_validate_valid_config(self, mock_exists):
        """Test validation of a fully valid configuration."""
        mock_exists.return_value = False  # Pretend .env doesn't exist to skip permission check
        config = {
            'GITLAB_URL': 'https://gitlab.com',
            'GITLAB_TOKEN': 'glpat-test123',
            'WEBHOOK_PORT': '8000',
            'WEBHOOK_SECRET': 'secret',
            'LOG_LEVEL': 'INFO',
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
        }

        errors, warnings = manage_container.validate_config(config)

        self.assertEqual(len(errors), 1)
        self.assertIn('GITLAB_URL', errors[0])

    def test_validate_missing_gitlab_token(self):
        """Test validation catches missing GITLAB_TOKEN."""
        config = {
            'GITLAB_URL': 'https://gitlab.com',
        }

        errors, warnings = manage_container.validate_config(config)

        self.assertEqual(len(errors), 1)
        self.assertIn('GITLAB_TOKEN', errors[0])

    def test_validate_invalid_port(self):
        """Test validation warns about invalid port."""
        config = {
            'GITLAB_URL': 'https://gitlab.com',
            'GITLAB_TOKEN': 'glpat-test123',
            'WEBHOOK_PORT': 'not-a-number',
        }

        errors, warnings = manage_container.validate_config(config)

        self.assertEqual(len(errors), 0)
        self.assertTrue(any('WEBHOOK_PORT' in w for w in warnings))


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

    @patch('manage_container.console')
    def test_build_image_success(self, mock_console):
        """Test successful image build."""
        mock_client = MagicMock()
        mock_client.images.build.return_value = (MagicMock(), [])

        result = manage_container.build_image(mock_client)

        self.assertTrue(result)
        mock_client.images.build.assert_called_once()

    @patch('manage_container.console')
    def test_build_image_failure(self, mock_console):
        """Test image build failure."""
        from docker.errors import APIError
        mock_client = MagicMock()
        mock_client.images.build.side_effect = APIError("Build failed")

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
        config = {'WEBHOOK_PORT': '8000'}

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
        """Test starting new container."""
        mock_exists.return_value = False
        mock_client = MagicMock()
        config = {'WEBHOOK_PORT': '8000'}

        # Mock Path instance
        mock_path_instance = MagicMock()
        mock_path_instance.exists.return_value = False
        mock_path.return_value = mock_path_instance

        result = manage_container.start_container(mock_client, config, skip_confirm=True)

        self.assertTrue(result)
        mock_client.containers.run.assert_called_once()


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
        config = {'WEBHOOK_PORT': '8000'}

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

    @patch('manage_container.stop_container')
    @patch('manage_container.console')
    @patch('manage_container.container_exists')
    def test_remove_container_with_force(self, mock_exists, mock_console, mock_stop):
        """Test removing container with force flag."""
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


if __name__ == '__main__':
    unittest.main()
