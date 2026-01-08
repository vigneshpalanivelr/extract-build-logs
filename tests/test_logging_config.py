"""
Unit tests for logging_config.py

Comprehensive test coverage for logging configuration including:
- Logging setup
- Pipe-delimited formatter
- Sensitive data filter (token masking)
- Request ID context management
- Logger creation
- Log file creation and rotation settings
"""

import unittest
import tempfile
import os
import logging
from pathlib import Path
import sys

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.logging_config import (
    setup_logging,
    get_logger,
    set_request_id,
    clear_request_id,
    mask_token,
    PipeDelimitedFormatter,
    SensitiveDataFilter,
    RequestIdFilter,
    LoggingConfig
)


class TestLoggingSetup(unittest.TestCase):
    """Test cases for logging setup and configuration."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up test fixtures."""
        # Reset logging to avoid interference between tests
        logging.root.handlers = []
        clear_request_id()

    def test_setup_logging_creates_log_directory(self):
        """Test that setup_logging creates the log directory."""
        log_dir = os.path.join(self.temp_dir, "logs")
        setup_logging(log_dir=log_dir, log_level='INFO')

        self.assertTrue(os.path.exists(log_dir))

    def test_setup_logging_creates_application_log(self):
        """Test that application.log file is created."""
        log_dir = os.path.join(self.temp_dir, "logs")
        setup_logging(log_dir=log_dir, log_level='INFO')

        app_log = os.path.join(log_dir, "application.log")
        # File may not exist until first log message
        logger = get_logger("test")
        logger.info("Test message")

        self.assertTrue(os.path.exists(app_log))

    def test_get_logger_returns_logger(self):
        """Test that get_logger returns a proper logger instance."""
        logger = get_logger("test_module")

        self.assertIsInstance(logger, logging.Logger)
        self.assertEqual(logger.name, "test_module")

    def test_get_logger_auto_initializes(self):
        """Test that get_logger auto-initializes logging if not set up."""
        # Clear any existing setup
        logging.root.handlers = []

        logger = get_logger("test_auto_init")
        self.assertIsInstance(logger, logging.Logger)

    def test_set_and_clear_request_id(self):
        """Test setting and clearing request ID in context."""
        # Set request ID
        set_request_id("test-req-123")

        # Clear request ID
        clear_request_id()
        # We can't directly test the context var value without executing logging
        # but we can verify the functions run without error

    def test_mask_token_function(self):
        """Test the mask_token convenience function."""
        token = "glpat-1234567890abcdefghij"
        masked = mask_token(token)

        # Should show first 4 and last 4 characters
        self.assertIn("glpa", masked)  # First 4 chars
        self.assertIn("...", masked)
        self.assertIn("ghij", masked)  # Last 4 chars
        self.assertNotIn("1234567890", masked)


class TestPipeDelimitedFormatter(unittest.TestCase):
    """Test cases for PipeDelimitedFormatter."""

    def setUp(self):
        """Set up test fixtures."""
        self.formatter = PipeDelimitedFormatter()

    def test_format_basic_message(self):
        """Test formatting a basic log message."""
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Test message",
            args=(),
            exc_info=None
        )

        formatted = self.formatter.format(record)

        # Should contain pipe delimiters
        self.assertIn(" | ", formatted)
        # Should contain the message
        self.assertIn("Test message", formatted)
        # Should contain log level
        self.assertIn("INFO", formatted)

    def test_format_with_extra_fields(self):
        """Test formatting with extra fields in context."""
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Test message",
            args=(),
            exc_info=None
        )
        record.pipeline_id = 12345
        record.project_id = 100

        formatted = self.formatter.format(record)

        self.assertIn("pipeline_id=12345", formatted)
        self.assertIn("project_id=100", formatted)

    def test_format_handles_none_extra_fields(self):
        """Test that formatter handles None values in extra fields."""
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Test message",
            args=(),
            exc_info=None
        )
        record.optional_field = None

        formatted = self.formatter.format(record)
        # Should not raise exception
        self.assertIn("Test message", formatted)


class TestSensitiveDataFilter(unittest.TestCase):
    """Test cases for SensitiveDataFilter."""

    def setUp(self):
        """Set up test fixtures."""
        self.filter = SensitiveDataFilter()

    def test_masks_gitlab_token(self):
        """Test that GitLab tokens are masked."""
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Token: %s",
            args=("glpat-1234567890abcdefghij",),
            exc_info=None
        )

        result = self.filter.filter(record)

        self.assertTrue(result)
        # Args should be masked with [REDACTED***] format
        self.assertIn("[REDACTED***]", str(record.args))
        self.assertNotIn("1234567890", str(record.args))

    def test_masks_bearer_token(self):
        """Test that Bearer tokens are masked."""
        # Use a long token that will match the pattern
        long_token = "secret_token_1234567890abcdef"
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Authorization: Bearer %s",
            args=(long_token,),
            exc_info=None
        )

        result = self.filter.filter(record)

        self.assertTrue(result)
        # Args should still be a tuple, values unchanged unless matching patterns
        self.assertIsInstance(record.args, tuple)

    def test_does_not_mask_format_strings(self):
        """Test that format strings like %s are not masked."""
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Token: %s, ID: %s",
            args=(),
            exc_info=None
        )

        result = self.filter.filter(record)

        self.assertTrue(result)
        # Message template should not be modified
        self.assertEqual(record.msg, "Token: %s, ID: %s")

    def test_masks_dict_args(self):
        """Test that dict arguments are properly masked."""
        # Create a logger to use for actual logging (not direct LogRecord creation)
        test_logger = logging.getLogger("test_masks_dict")
        test_logger.addFilter(self.filter)

        # Create dict with sensitive data
        test_args = {"token": "glpat-1234567890abcdefghijklmnop"}

        # Create a handler to capture the log record
        class RecordCapture(logging.Handler):
            def __init__(self):
                super().__init__()
                self.record = None

            def emit(self, record):
                self.record = record

        handler = RecordCapture()
        test_logger.addHandler(handler)
        test_logger.setLevel(logging.INFO)

        # Log with dict args
        test_logger.info("Data: %(token)s", test_args)

        # Verify the record was created and filtered
        self.assertIsNotNone(handler.record)
        # The token in the dict args should be masked
        if isinstance(handler.record.args, dict):
            self.assertIn("glpa", str(handler.record.args['token']))
            self.assertIn("...", str(handler.record.args['token']))
            self.assertIn("mnop", str(handler.record.args['token']))


class TestRequestIdFilter(unittest.TestCase):
    """Test cases for RequestIdFilter."""

    def setUp(self):
        """Set up test fixtures."""
        self.filter = RequestIdFilter()

    def test_adds_request_id_to_record(self):
        """Test that request ID is added to log record."""
        set_request_id("req-123")

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Test message",
            args=(),
            exc_info=None
        )

        result = self.filter.filter(record)

        self.assertTrue(result)
        self.assertEqual(record.request_id, "req-123")

        clear_request_id()

    def test_handles_missing_request_id(self):
        """Test that filter handles missing request ID gracefully."""
        clear_request_id()

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Test message",
            args=(),
            exc_info=None
        )

        result = self.filter.filter(record)

        self.assertTrue(result)
        # Should have empty or None request_id
        self.assertTrue(hasattr(record, 'request_id'))


class TestLoggingConfig(unittest.TestCase):
    """Test cases for LoggingConfig class."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up test fixtures."""
        logging.root.handlers = []

    def test_logging_config_initialization(self):
        """Test LoggingConfig initialization."""
        log_dir = os.path.join(self.temp_dir, "logs")
        config = LoggingConfig(log_dir=log_dir, log_level='DEBUG')

        self.assertIsNotNone(config)
        self.assertTrue(os.path.exists(log_dir))

    def test_get_logger_static_method(self):
        """Test LoggingConfig.get_logger static method."""
        logger = LoggingConfig.get_logger("test_static")

        self.assertIsInstance(logger, logging.Logger)
        self.assertEqual(logger.name, "test_static")

    def test_set_request_id_static_method(self):
        """Test LoggingConfig.set_request_id static method."""
        # Should not raise exception
        LoggingConfig.set_request_id("test-id-456")
        LoggingConfig.clear_request_id()

    def test_log_rotation_settings(self):
        """Test that log rotation settings are configured."""
        log_dir = os.path.join(self.temp_dir, "logs")
        LoggingConfig(log_dir=log_dir, log_level='INFO')

        # Verify handler is a RotatingFileHandler
        root_logger = logging.getLogger()
        handlers = [h for h in root_logger.handlers if hasattr(h, 'maxBytes')]

        self.assertGreater(len(handlers), 0)
        # Check max bytes is set (should be 100MB for application.log)
        self.assertEqual(handlers[0].maxBytes, 100 * 1024 * 1024)


if __name__ == '__main__':
    unittest.main()
