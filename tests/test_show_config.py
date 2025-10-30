"""
Unit tests for show_config.py

Tests configuration loading, validation, masking, and user interaction.
"""

import unittest
from unittest.mock import patch, mock_open, MagicMock
from pathlib import Path
import sys
import io

# Add parent directory to path to import show_config
sys.path.insert(0, str(Path(__file__).parent.parent))

import show_config


class TestMaskValue(unittest.TestCase):
    """Test cases for mask_value function."""

    def test_mask_long_value(self):
        """Test masking a long value shows first 8 chars."""
        result = show_config.mask_value("glpat-1234567890abcdefgh", 8)
        self.assertEqual(result, "glpat-12****")

    def test_mask_short_value(self):
        """Test masking a short value returns asterisks."""
        result = show_config.mask_value("short", 8)
        self.assertEqual(result, "****")

    def test_mask_empty_value(self):
        """Test masking empty value returns 'Not Set'."""
        result = show_config.mask_value("", 8)
        self.assertEqual(result, "Not Set")

    def test_mask_none_value(self):
        """Test masking None returns 'Not Set'."""
        result = show_config.mask_value(None, 8)
        self.assertEqual(result, "Not Set")

    def test_mask_custom_show_chars(self):
        """Test masking with custom number of visible characters."""
        result = show_config.mask_value("glpat-1234567890", 4)
        self.assertEqual(result, "glpa****")

    def test_mask_exact_length(self):
        """Test masking value exactly equal to show_chars."""
        result = show_config.mask_value("12345678", 8)
        self.assertEqual(result, "****")


class TestLoadConfig(unittest.TestCase):
    """Test cases for load_config function."""

    def test_load_config_file_not_found(self):
        """Test loading non-existent config file returns None."""
        result = show_config.load_config(Path('/nonexistent/.env'))
        self.assertIsNone(result)

    @patch('show_config.dotenv_values')
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

        result = show_config.load_config(Path('.env'))

        self.assertIsNotNone(result)
        self.assertEqual(result['GITLAB_URL'], 'https://gitlab.com')
        self.assertEqual(result['GITLAB_TOKEN'], 'glpat-test123')
        self.assertEqual(result['WEBHOOK_PORT'], '9000')
        self.assertEqual(result['LOG_LEVEL'], 'DEBUG')

    @patch('show_config.dotenv_values')
    @patch('pathlib.Path.exists')
    def test_load_config_with_defaults(self, mock_exists, mock_dotenv):
        """Test loading config applies defaults for missing values."""
        mock_exists.return_value = True
        mock_dotenv.return_value = {
            'GITLAB_URL': 'https://gitlab.com',
            'GITLAB_TOKEN': 'glpat-test123',
        }

        result = show_config.load_config(Path('.env'))

        self.assertEqual(result['WEBHOOK_PORT'], '8000')  # Default
        self.assertEqual(result['LOG_LEVEL'], 'INFO')  # Default
        self.assertEqual(result['LOG_OUTPUT_DIR'], './logs')  # Default
        self.assertEqual(result['RETRY_ATTEMPTS'], '3')  # Default
        self.assertEqual(result['RETRY_DELAY'], '2')  # Default
        self.assertEqual(result['WEBHOOK_SECRET'], '')  # Default

    @patch('show_config.dotenv_values')
    @patch('pathlib.Path.exists')
    def test_load_config_with_empty_values(self, mock_exists, mock_dotenv):
        """Test loading config replaces empty values with defaults."""
        mock_exists.return_value = True
        mock_dotenv.return_value = {
            'GITLAB_URL': 'https://gitlab.com',
            'GITLAB_TOKEN': 'glpat-test123',
            'WEBHOOK_PORT': '',  # Empty
            'LOG_LEVEL': '',  # Empty
        }

        result = show_config.load_config(Path('.env'))

        self.assertEqual(result['WEBHOOK_PORT'], '8000')  # Default applied
        self.assertEqual(result['LOG_LEVEL'], 'INFO')  # Default applied


class TestValidateConfig(unittest.TestCase):
    """Test cases for validate_config function."""

    def test_validate_valid_config(self):
        """Test validation of a fully valid configuration."""
        config = {
            'GITLAB_URL': 'https://gitlab.com',
            'GITLAB_TOKEN': 'glpat-test123',
            'WEBHOOK_PORT': '8000',
            'WEBHOOK_SECRET': 'secret',
            'LOG_LEVEL': 'INFO',
            'RETRY_ATTEMPTS': '3',
            'RETRY_DELAY': '2',
        }

        errors, warnings = show_config.validate_config(config)

        self.assertEqual(len(errors), 0)
        self.assertEqual(len(warnings), 0)

    def test_validate_missing_gitlab_url(self):
        """Test validation catches missing GITLAB_URL."""
        config = {
            'GITLAB_TOKEN': 'glpat-test123',
            'WEBHOOK_PORT': '8000',
            'LOG_LEVEL': 'INFO',
        }

        errors, warnings = show_config.validate_config(config)

        self.assertEqual(len(errors), 1)
        self.assertIn('GITLAB_URL', errors[0])

    def test_validate_missing_gitlab_token(self):
        """Test validation catches missing GITLAB_TOKEN."""
        config = {
            'GITLAB_URL': 'https://gitlab.com',
            'WEBHOOK_PORT': '8000',
            'LOG_LEVEL': 'INFO',
        }

        errors, warnings = show_config.validate_config(config)

        self.assertEqual(len(errors), 1)
        self.assertIn('GITLAB_TOKEN', errors[0])

    def test_validate_missing_webhook_secret_warning(self):
        """Test validation warns about missing WEBHOOK_SECRET."""
        config = {
            'GITLAB_URL': 'https://gitlab.com',
            'GITLAB_TOKEN': 'glpat-test123',
            'WEBHOOK_SECRET': '',
            'WEBHOOK_PORT': '8000',
            'LOG_LEVEL': 'INFO',
        }

        errors, warnings = show_config.validate_config(config)

        self.assertEqual(len(errors), 0)
        self.assertEqual(len(warnings), 1)
        self.assertIn('WEBHOOK_SECRET', warnings[0])

    def test_validate_invalid_log_level(self):
        """Test validation warns about invalid LOG_LEVEL."""
        config = {
            'GITLAB_URL': 'https://gitlab.com',
            'GITLAB_TOKEN': 'glpat-test123',
            'WEBHOOK_SECRET': 'secret',
            'WEBHOOK_PORT': '8000',
            'LOG_LEVEL': 'INVALID',
            'RETRY_ATTEMPTS': '3',
            'RETRY_DELAY': '2',
        }

        errors, warnings = show_config.validate_config(config)

        self.assertEqual(len(errors), 0)
        self.assertGreaterEqual(len(warnings), 1)
        self.assertTrue(any('LOG_LEVEL' in w for w in warnings))

    def test_validate_invalid_port_number(self):
        """Test validation warns about invalid port number."""
        config = {
            'GITLAB_URL': 'https://gitlab.com',
            'GITLAB_TOKEN': 'glpat-test123',
            'WEBHOOK_SECRET': 'secret',
            'WEBHOOK_PORT': 'not-a-number',
            'LOG_LEVEL': 'INFO',
        }

        errors, warnings = show_config.validate_config(config)

        self.assertEqual(len(errors), 0)
        self.assertTrue(any('WEBHOOK_PORT' in w for w in warnings))

    def test_validate_port_out_of_range(self):
        """Test validation warns about port out of valid range."""
        config = {
            'GITLAB_URL': 'https://gitlab.com',
            'GITLAB_TOKEN': 'glpat-test123',
            'WEBHOOK_SECRET': 'secret',
            'WEBHOOK_PORT': '70000',  # > 65535
            'LOG_LEVEL': 'INFO',
        }

        errors, warnings = show_config.validate_config(config)

        self.assertEqual(len(errors), 0)
        self.assertTrue(any('WEBHOOK_PORT' in w and 'range' in w for w in warnings))

    def test_validate_negative_retry_attempts(self):
        """Test validation warns about negative retry attempts."""
        config = {
            'GITLAB_URL': 'https://gitlab.com',
            'GITLAB_TOKEN': 'glpat-test123',
            'WEBHOOK_SECRET': 'secret',
            'WEBHOOK_PORT': '8000',
            'LOG_LEVEL': 'INFO',
            'RETRY_ATTEMPTS': '-1',
        }

        errors, warnings = show_config.validate_config(config)

        self.assertEqual(len(errors), 0)
        self.assertTrue(any('RETRY_ATTEMPTS' in w for w in warnings))

    def test_validate_invalid_retry_delay(self):
        """Test validation warns about invalid retry delay."""
        config = {
            'GITLAB_URL': 'https://gitlab.com',
            'GITLAB_TOKEN': 'glpat-test123',
            'WEBHOOK_SECRET': 'secret',
            'WEBHOOK_PORT': '8000',
            'LOG_LEVEL': 'INFO',
            'RETRY_DELAY': 'not-a-number',
        }

        errors, warnings = show_config.validate_config(config)

        self.assertEqual(len(errors), 0)
        self.assertTrue(any('RETRY_DELAY' in w for w in warnings))

    def test_validate_all_log_levels(self):
        """Test validation accepts all valid log levels."""
        valid_levels = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']

        for level in valid_levels:
            config = {
                'GITLAB_URL': 'https://gitlab.com',
                'GITLAB_TOKEN': 'glpat-test123',
                'WEBHOOK_SECRET': 'secret',
                'WEBHOOK_PORT': '8000',
                'LOG_LEVEL': level,
                'RETRY_ATTEMPTS': '3',
                'RETRY_DELAY': '2',
            }

            errors, warnings = show_config.validate_config(config)

            self.assertEqual(len(errors), 0, f"Level {level} should not produce errors")
            self.assertEqual(len(warnings), 0, f"Level {level} should not produce warnings")


class TestConfirmAction(unittest.TestCase):
    """Test cases for confirm_action function."""

    @patch('builtins.input', return_value='y')
    def test_confirm_action_yes(self, mock_input):
        """Test confirmation returns True for 'y' input."""
        result = show_config.confirm_action()
        self.assertTrue(result)

    @patch('builtins.input', return_value='yes')
    def test_confirm_action_yes_full(self, mock_input):
        """Test confirmation returns True for 'yes' input."""
        result = show_config.confirm_action()
        self.assertTrue(result)

    @patch('builtins.input', return_value='n')
    def test_confirm_action_no(self, mock_input):
        """Test confirmation returns False for 'n' input."""
        result = show_config.confirm_action()
        self.assertFalse(result)

    @patch('builtins.input', return_value='no')
    def test_confirm_action_no_full(self, mock_input):
        """Test confirmation returns False for 'no' input."""
        result = show_config.confirm_action()
        self.assertFalse(result)

    @patch('builtins.input', return_value='')
    def test_confirm_action_empty(self, mock_input):
        """Test confirmation returns False for empty input (default No)."""
        result = show_config.confirm_action()
        self.assertFalse(result)

    @patch('builtins.input', side_effect=['invalid', 'y'])
    def test_confirm_action_retry_on_invalid(self, mock_input):
        """Test confirmation retries on invalid input."""
        result = show_config.confirm_action()
        self.assertTrue(result)
        self.assertEqual(mock_input.call_count, 2)

    @patch('builtins.input', side_effect=KeyboardInterrupt())
    def test_confirm_action_keyboard_interrupt(self, mock_input):
        """Test confirmation handles KeyboardInterrupt gracefully."""
        result = show_config.confirm_action()
        self.assertFalse(result)


class TestShowConfigTable(unittest.TestCase):
    """Test cases for show_config_table function."""

    @patch('sys.stdout', new_callable=io.StringIO)
    def test_show_config_table_output(self, mock_stdout):
        """Test that show_config_table produces output."""
        config = {
            'GITLAB_URL': 'https://gitlab.com',
            'GITLAB_TOKEN': 'glpat-test123',
            'WEBHOOK_PORT': '8000',
            'WEBHOOK_SECRET': 'secret',
            'LOG_LEVEL': 'INFO',
            'LOG_OUTPUT_DIR': './logs',
            'RETRY_ATTEMPTS': '3',
            'RETRY_DELAY': '2',
        }

        show_config.show_config_table(config)

        output = mock_stdout.getvalue()

        # Check key elements are in output
        self.assertIn('Configuration Review', output)
        self.assertIn('https://gitlab.com', output)
        self.assertIn('glpat-te****', output)  # Masked token
        self.assertIn('8000', output)
        self.assertIn('INFO', output)

    @patch('sys.stdout', new_callable=io.StringIO)
    def test_show_config_table_masks_secrets(self, mock_stdout):
        """Test that show_config_table masks sensitive data."""
        config = {
            'GITLAB_URL': 'https://gitlab.com',
            'GITLAB_TOKEN': 'glpat-verysecrettoken123',
            'WEBHOOK_PORT': '8000',
            'WEBHOOK_SECRET': 'mysecret',
            'LOG_LEVEL': 'INFO',
            'LOG_OUTPUT_DIR': './logs',
            'RETRY_ATTEMPTS': '3',
            'RETRY_DELAY': '2',
        }

        show_config.show_config_table(config)

        output = mock_stdout.getvalue()

        # Full token should NOT be in output
        self.assertNotIn('glpat-verysecrettoken123', output)
        # Masked version should be in output
        self.assertIn('glpat-ve****', output)

        # Full secret should NOT be in output
        self.assertNotIn('mysecret', output)


class TestShowValidationResults(unittest.TestCase):
    """Test cases for show_validation_results function."""

    @patch('sys.stdout', new_callable=io.StringIO)
    def test_show_validation_results_with_errors(self, mock_stdout):
        """Test displaying validation results with errors."""
        errors = ['GITLAB_URL is not set', 'GITLAB_TOKEN is not set']
        warnings = []

        show_config.show_validation_results(errors, warnings)

        output = mock_stdout.getvalue()

        self.assertIn('ERRORS', output)
        self.assertIn('GITLAB_URL is not set', output)
        self.assertIn('GITLAB_TOKEN is not set', output)

    @patch('sys.stdout', new_callable=io.StringIO)
    def test_show_validation_results_with_warnings(self, mock_stdout):
        """Test displaying validation results with warnings."""
        errors = []
        warnings = ['WEBHOOK_SECRET is not set']

        show_config.show_validation_results(errors, warnings)

        output = mock_stdout.getvalue()

        self.assertIn('WARNINGS', output)
        self.assertIn('WEBHOOK_SECRET is not set', output)

    @patch('sys.stdout', new_callable=io.StringIO)
    def test_show_validation_results_empty(self, mock_stdout):
        """Test displaying validation results with no errors or warnings."""
        errors = []
        warnings = []

        show_config.show_validation_results(errors, warnings)

        output = mock_stdout.getvalue()

        # Should produce no output
        self.assertEqual(output, '')


class TestParseArgs(unittest.TestCase):
    """Test cases for parse_args function."""

    @patch('sys.argv', ['show_config.py'])
    def test_parse_args_defaults(self):
        """Test argument parsing with default values."""
        args = show_config.parse_args()

        self.assertFalse(args.yes)
        self.assertFalse(args.quiet)
        self.assertFalse(args.validate_only)
        self.assertEqual(args.env_file, Path('.env'))
        self.assertEqual(args.container_name, 'gitlab-pipeline-extractor')
        self.assertEqual(args.image_name, 'gitlab-pipeline-extractor')

    @patch('sys.argv', ['show_config.py', '--yes'])
    def test_parse_args_yes_flag(self):
        """Test parsing --yes flag."""
        args = show_config.parse_args()

        self.assertTrue(args.yes)

    @patch('sys.argv', ['show_config.py', '-y'])
    def test_parse_args_yes_flag_short(self):
        """Test parsing -y flag."""
        args = show_config.parse_args()

        self.assertTrue(args.yes)

    @patch('sys.argv', ['show_config.py', '--quiet'])
    def test_parse_args_quiet_flag(self):
        """Test parsing --quiet flag."""
        args = show_config.parse_args()

        self.assertTrue(args.quiet)

    @patch('sys.argv', ['show_config.py', '-q'])
    def test_parse_args_quiet_flag_short(self):
        """Test parsing -q flag."""
        args = show_config.parse_args()

        self.assertTrue(args.quiet)

    @patch('sys.argv', ['show_config.py', '--validate-only'])
    def test_parse_args_validate_only(self):
        """Test parsing --validate-only flag."""
        args = show_config.parse_args()

        self.assertTrue(args.validate_only)

    @patch('sys.argv', ['show_config.py', '--env-file', '.env.prod'])
    def test_parse_args_custom_env_file(self):
        """Test parsing custom env file path."""
        args = show_config.parse_args()

        self.assertEqual(args.env_file, Path('.env.prod'))

    @patch('sys.argv', ['show_config.py', '--container-name', 'my-container'])
    def test_parse_args_custom_container_name(self):
        """Test parsing custom container name."""
        args = show_config.parse_args()

        self.assertEqual(args.container_name, 'my-container')

    @patch('sys.argv', ['show_config.py', '--image-name', 'my-image'])
    def test_parse_args_custom_image_name(self):
        """Test parsing custom image name."""
        args = show_config.parse_args()

        self.assertEqual(args.image_name, 'my-image')

    @patch('sys.argv', ['show_config.py', '-y', '-q', '--validate-only'])
    def test_parse_args_multiple_flags(self):
        """Test parsing multiple flags together."""
        args = show_config.parse_args()

        self.assertTrue(args.yes)
        self.assertTrue(args.quiet)
        self.assertTrue(args.validate_only)


class TestMainFunction(unittest.TestCase):
    """Test cases for main function."""

    @patch('show_config.parse_args')
    @patch('show_config.load_config')
    def test_main_file_not_found(self, mock_load, mock_parse):
        """Test main returns EXIT_FILE_NOT_FOUND when .env missing."""
        mock_parse.return_value = MagicMock(
            env_file=Path('.env'),
            quiet=False,
            yes=False,
            validate_only=False,
            container_name='test',
            image_name='test'
        )
        mock_load.return_value = None

        exit_code = show_config.main()

        self.assertEqual(exit_code, show_config.EXIT_FILE_NOT_FOUND)

    @patch('show_config.parse_args')
    @patch('show_config.load_config')
    @patch('show_config.validate_config')
    @patch('show_config.show_config_table')
    @patch('show_config.show_validation_results')
    def test_main_validation_errors(self, mock_show_val, mock_show_table,
                                   mock_validate, mock_load, mock_parse):
        """Test main returns EXIT_ERROR when validation fails."""
        mock_parse.return_value = MagicMock(
            env_file=Path('.env'),
            quiet=False,
            yes=False,
            validate_only=False,
            container_name='test',
            image_name='test'
        )
        mock_load.return_value = {'GITLAB_URL': 'test'}
        mock_validate.return_value = (['Error1'], [])  # Has errors

        exit_code = show_config.main()

        self.assertEqual(exit_code, show_config.EXIT_ERROR)

    @patch('show_config.parse_args')
    @patch('show_config.load_config')
    @patch('show_config.validate_config')
    @patch('show_config.show_config_table')
    @patch('show_config.show_validation_results')
    def test_main_validate_only_success(self, mock_show_val, mock_show_table,
                                       mock_validate, mock_load, mock_parse):
        """Test main returns EXIT_SUCCESS in validate-only mode."""
        mock_parse.return_value = MagicMock(
            env_file=Path('.env'),
            quiet=False,
            yes=False,
            validate_only=True,
            container_name='test',
            image_name='test'
        )
        mock_load.return_value = {'GITLAB_URL': 'test', 'GITLAB_TOKEN': 'test'}
        mock_validate.return_value = ([], [])  # No errors

        exit_code = show_config.main()

        self.assertEqual(exit_code, show_config.EXIT_SUCCESS)

    @patch('show_config.parse_args')
    @patch('show_config.load_config')
    @patch('show_config.validate_config')
    @patch('show_config.show_config_table')
    @patch('show_config.show_validation_results')
    def test_main_auto_confirm(self, mock_show_val, mock_show_table,
                               mock_validate, mock_load, mock_parse):
        """Test main returns EXIT_SUCCESS with --yes flag."""
        mock_parse.return_value = MagicMock(
            env_file=Path('.env'),
            quiet=False,
            yes=True,
            validate_only=False,
            container_name='test',
            image_name='test'
        )
        mock_load.return_value = {'GITLAB_URL': 'test', 'GITLAB_TOKEN': 'test'}
        mock_validate.return_value = ([], [])

        exit_code = show_config.main()

        self.assertEqual(exit_code, show_config.EXIT_SUCCESS)

    @patch('show_config.parse_args')
    @patch('show_config.load_config')
    @patch('show_config.validate_config')
    @patch('show_config.show_config_table')
    @patch('show_config.show_validation_results')
    @patch('show_config.confirm_action')
    def test_main_user_confirms(self, mock_confirm, mock_show_val, mock_show_table,
                                mock_validate, mock_load, mock_parse):
        """Test main returns EXIT_SUCCESS when user confirms."""
        mock_parse.return_value = MagicMock(
            env_file=Path('.env'),
            quiet=False,
            yes=False,
            validate_only=False,
            container_name='test',
            image_name='test'
        )
        mock_load.return_value = {'GITLAB_URL': 'test', 'GITLAB_TOKEN': 'test'}
        mock_validate.return_value = ([], [])
        mock_confirm.return_value = True

        exit_code = show_config.main()

        self.assertEqual(exit_code, show_config.EXIT_SUCCESS)

    @patch('show_config.parse_args')
    @patch('show_config.load_config')
    @patch('show_config.validate_config')
    @patch('show_config.show_config_table')
    @patch('show_config.show_validation_results')
    @patch('show_config.confirm_action')
    def test_main_user_cancels(self, mock_confirm, mock_show_val, mock_show_table,
                               mock_validate, mock_load, mock_parse):
        """Test main returns EXIT_CANCELLED when user declines."""
        mock_parse.return_value = MagicMock(
            env_file=Path('.env'),
            quiet=False,
            yes=False,
            validate_only=False,
            container_name='test',
            image_name='test'
        )
        mock_load.return_value = {'GITLAB_URL': 'test', 'GITLAB_TOKEN': 'test'}
        mock_validate.return_value = ([], [])
        mock_confirm.return_value = False

        exit_code = show_config.main()

        self.assertEqual(exit_code, show_config.EXIT_CANCELLED)


if __name__ == '__main__':
    unittest.main()
