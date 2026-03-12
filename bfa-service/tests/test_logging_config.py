import logging
import pytest
from unittest.mock import patch, MagicMock

import logging_config
from logging_config import (
    SensitiveDataFilter,
    RequestIdFilter,
    PipeDelimitedFormatter,
    LoggingConfig,
    setup_logging,
    get_logger,
    set_request_id,
    clear_request_id,
    get_request_id,
    mask_token,
    request_id_var,
)


# ─── SensitiveDataFilter ───────────────────────────────────────────────


class TestSensitiveDataFilter:
    def setup_method(self):
        self.f = SensitiveDataFilter()

    def test_filter_returns_true(self):
        record = logging.LogRecord(
            "test", logging.INFO, "", 0, "hello", None, None)
        assert self.f.filter(record) is True

    def test_mask_slack_bot_token_in_tuple_args(self):
        msg = "Token is xoxb-1234567890abcdefghijklmnopqrst"
        record = logging.LogRecord(
            "test", logging.INFO, "", 0, "msg %s", (msg,), None)
        self.f.filter(record)
        assert "xoxb" not in record.args[0] or "[MASKED]" in record.args[0]

    def test_mask_slack_user_token(self):
        msg = "Token is xoxp-1234567890abcdefghijklmnopqrst"
        record = logging.LogRecord(
            "test", logging.INFO, "", 0, "msg %s", (msg,), None)
        self.f.filter(record)
        assert "[MASKED]" in record.args[0]

    def test_mask_slack_app_token(self):
        msg = "Token is xapp-1234567890abcdefghijklmnopqrst"
        record = logging.LogRecord(
            "test", logging.INFO, "", 0, "msg %s", (msg,), None)
        self.f.filter(record)
        assert "[MASKED]" in record.args[0]

    def test_mask_bearer_token(self):
        msg = "Authorization: Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.payload.sig"
        record = logging.LogRecord(
            "test", logging.INFO, "", 0, "msg %s", (msg,), None)
        self.f.filter(record)
        assert "[MASKED]" in record.args[0]

    def test_mask_generic_token(self):
        msg = "token=abc123def456ghi789jkl012mnopqrst"
        record = logging.LogRecord(
            "test", logging.INFO, "", 0, "msg %s", (msg,), None)
        self.f.filter(record)
        assert "[MASKED]" in record.args[0]

    def test_mask_password_in_string(self):
        msg = "password=supersecretpassword1234567890"
        record = logging.LogRecord(
            "test", logging.INFO, "", 0, "msg %s", (msg,), None)
        self.f.filter(record)
        assert "[MASKED]" in record.args[0]

    def test_mask_api_key(self):
        msg = "api_key=fake_test_key_1234567890abcdefghij"
        record = logging.LogRecord(
            "test", logging.INFO, "", 0, "msg %s", (msg,), None)
        self.f.filter(record)
        assert "[MASKED]" in record.args[0]

    def test_mask_authorization_header(self):
        msg = "Authorization: Bearer abcdefghijklmnopqrstuvwxyz1234"
        record = logging.LogRecord(
            "test", logging.INFO, "", 0, "msg %s", (msg,), None)
        self.f.filter(record)
        assert "[MASKED]" in record.args[0]

    def test_mask_private_token_header(self):
        msg = "PRIVATE-TOKEN: glpat-1234567890abcdefghijkl"
        record = logging.LogRecord(
            "test", logging.INFO, "", 0, "msg %s", (msg,), None)
        self.f.filter(record)
        assert "[MASKED]" in record.args[0]

    def test_mask_redis_password_in_url(self):
        msg = "redis://user:mysecretpassword123@redis-host:6379/0"
        record = logging.LogRecord(
            "test", logging.INFO, "", 0, "msg %s", (msg,), None)
        self.f.filter(record)
        assert "mysecretpassword123" not in record.args[0]

    def test_mask_dict_args_with_sensitive_keys(self):
        args = {"token": "secret123", "normal": "value"}
        record = logging.LogRecord(
            "test", logging.INFO, "", 0, "msg %(token)s %(normal)s", args, None)
        self.f.filter(record)
        assert record.args["token"] == "****"
        assert record.args["normal"] == "value"

    def test_mask_dict_nested(self):
        args = {"outer": {"password": "secretval"}}
        record = logging.LogRecord(
            "test", logging.INFO, "", 0, "msg", args, None)
        self.f.filter(record)
        assert record.args["outer"]["password"] == "****"

    def test_no_mask_short_string(self):
        msg = "short"
        record = logging.LogRecord(
            "test", logging.INFO, "", 0, "msg %s", (msg,), None)
        self.f.filter(record)
        assert record.args[0] == "short"

    def test_no_mask_non_sensitive_long_string(self):
        msg = "This is a long string with no sensitive data at all here."
        record = logging.LogRecord(
            "test", logging.INFO, "", 0, "msg %s", (msg,), None)
        self.f.filter(record)
        assert record.args[0] == msg

    def test_no_args(self):
        record = logging.LogRecord(
            "test", logging.INFO, "", 0, "no args msg", None, None)
        result = self.f.filter(record)
        assert result is True

    def test_mask_dict_with_bot_token_key(self):
        args = {"bot_token": "xoxb-realtoken12345678"}
        record = logging.LogRecord(
            "test", logging.INFO, "", 0, "msg", args, None)
        self.f.filter(record)
        assert "xoxb-realtoken12345678" not in str(record.args["bot_token"])

    def test_mask_dict_with_signing_secret_key(self):
        args = {"signing_secret": "secretvalue123"}
        record = logging.LogRecord(
            "test", logging.INFO, "", 0, "msg", args, None)
        self.f.filter(record)
        assert record.args["signing_secret"] == "****"

    def test_mask_dict_with_apikey_key(self):
        args = {"apikey": "myapikey12345"}
        record = logging.LogRecord(
            "test", logging.INFO, "", 0, "msg", args, None)
        self.f.filter(record)
        assert record.args["apikey"] == "****"


# ─── SensitiveDataFilter._mask_token ───────────────────────────────────


class TestMaskToken:
    def test_mask_long_token(self):
        result = SensitiveDataFilter._mask_token("abcdefghijklmnopqrst")
        assert result == "abcd...[MASKED]qrst"

    def test_mask_short_token(self):
        result = SensitiveDataFilter._mask_token("short")
        assert result == "****"

    def test_mask_empty_token(self):
        result = SensitiveDataFilter._mask_token("")
        assert result == "****"

    def test_mask_none_token(self):
        result = SensitiveDataFilter._mask_token(None)
        assert result == "****"

    def test_mask_exactly_12_chars(self):
        result = SensitiveDataFilter._mask_token("123456789012")
        assert result == "1234...[MASKED]9012"

    def test_mask_11_chars(self):
        result = SensitiveDataFilter._mask_token("12345678901")
        assert result == "****"


# ─── RequestIdFilter ────────────────────────────────────────────────────


class TestRequestIdFilter:
    def setup_method(self):
        self.f = RequestIdFilter()
        clear_request_id()

    def teardown_method(self):
        clear_request_id()

    def test_adds_default_request_id(self):
        record = logging.LogRecord(
            "test", logging.INFO, "", 0, "msg", None, None)
        self.f.filter(record)
        assert record.request_id == "N/A"

    def test_adds_set_request_id(self):
        set_request_id("req-123")
        record = logging.LogRecord(
            "test", logging.INFO, "", 0, "msg", None, None)
        self.f.filter(record)
        assert record.request_id == "req-123"

    def test_filter_returns_true(self):
        record = logging.LogRecord(
            "test", logging.INFO, "", 0, "msg", None, None)
        assert self.f.filter(record) is True


# ─── PipeDelimitedFormatter ─────────────────────────────────────────────


class TestPipeDelimitedFormatter:
    def setup_method(self):
        self.fmt = PipeDelimitedFormatter()

    def test_basic_format(self):
        record = logging.LogRecord(
            "test_logger", logging.INFO, "", 0, "Test message", None, None)
        record.request_id = "N/A"
        output = self.fmt.format(record)
        assert " | INFO" in output
        assert " | test_logger" in output
        assert " | N/A" in output
        assert " | Test message" in output

    def test_format_with_context_fields(self):
        record = logging.LogRecord(
            "analyzer", logging.WARNING, "", 0, "Low similarity", None, None)
        record.request_id = "abc123"
        record.build_id = 999
        record.similarity_score = 0.65
        output = self.fmt.format(record)
        assert "build_id=999" in output
        assert "similarity_score=0.65" in output

    def test_format_truncates_long_logger_name(self):
        long_name = "a" * 30
        record = logging.LogRecord(
            long_name, logging.DEBUG, "", 0, "msg", None, None)
        record.request_id = "N/A"
        output = self.fmt.format(record)
        assert "..." in output

    def test_format_pads_short_logger_name(self):
        record = logging.LogRecord(
            "short", logging.INFO, "", 0, "msg", None, None)
        record.request_id = "N/A"
        output = self.fmt.format(record)
        # Logger name is padded to LOGGER_WIDTH
        parts = output.split(" | ")
        assert len(parts) >= 4

    def test_format_with_exception(self):
        try:
            raise ValueError("test error")
        except ValueError:
            import sys
            exc_info = sys.exc_info()
        record = logging.LogRecord(
            "test", logging.ERROR, "", 0, "Error occurred", None, exc_info)
        record.request_id = "N/A"
        output = self.fmt.format(record)
        assert "ValueError: test error" in output

    def test_format_no_context_fields(self):
        record = logging.LogRecord(
            "test", logging.INFO, "", 0, "Simple message", None, None)
        record.request_id = "req1"
        output = self.fmt.format(record)
        # Should not have trailing context separator
        parts = output.split(" | ")
        assert len(parts) == 4  # timestamp, level, logger, request_id+msg

    def test_format_all_context_fields(self):
        record = logging.LogRecord(
            "test", logging.INFO, "", 0, "msg", None, None)
        record.request_id = "N/A"
        record.build_id = 1
        record.project_name = "myproj"
        record.error_hash = "abc"
        record.fix_id = "fix-1"
        record.slack_channel = "#alerts"
        record.slack_user = "user1"
        record.action = "approve"
        record.similarity_score = 0.9
        record.confidence = "high"
        record.source = "vectordb"
        record.duration_ms = 100
        record.status_code = 200
        record.operation = "lookup"
        record.endpoint = "/api/analyze"
        record.vector_count = 42
        record.error_type = "TimeoutError"
        output = self.fmt.format(record)
        assert "build_id=1" in output
        assert "project_name=myproj" in output
        assert "error_type=TimeoutError" in output

    def test_format_with_none_context_value(self):
        record = logging.LogRecord(
            "test", logging.INFO, "", 0, "msg", None, None)
        record.request_id = "N/A"
        record.build_id = None
        output = self.fmt.format(record)
        assert "build_id" not in output


# ─── LoggingConfig ──────────────────────────────────────────────────────


class TestLoggingConfig:
    def test_init_creates_log_dir(self, tmp_path):
        log_dir = tmp_path / "test_logs"
        config = LoggingConfig(log_dir=str(log_dir), log_level='DEBUG')
        assert log_dir.exists()

    def test_init_sets_log_level(self, tmp_path):
        config = LoggingConfig(log_dir=str(tmp_path), log_level='WARNING')
        assert config.log_level == logging.WARNING

    def test_init_default_log_level(self, tmp_path):
        config = LoggingConfig(log_dir=str(tmp_path), log_level='INFO')
        assert config.log_level == logging.INFO

    def test_init_invalid_log_level_defaults_to_info(self, tmp_path):
        config = LoggingConfig(log_dir=str(tmp_path), log_level='NONEXISTENT')
        assert config.log_level == logging.INFO

    def test_setup_adds_two_handlers(self, tmp_path):
        config = LoggingConfig(log_dir=str(tmp_path), log_level='INFO')
        root = logging.getLogger()
        assert len(root.handlers) >= 2

    def test_log_file_created(self, tmp_path):
        config = LoggingConfig(log_dir=str(tmp_path), log_level='INFO')
        logger = logging.getLogger("test_file_creation")
        logger.info("test message")
        log_file = tmp_path / "bfa-service.log"
        assert log_file.exists()

    def test_get_logger_returns_logger(self, tmp_path):
        config = LoggingConfig(log_dir=str(tmp_path))
        logger = config.get_logger("test_module")
        assert isinstance(logger, logging.Logger)
        assert logger.name == "test_module"

    def test_set_and_get_request_id(self):
        LoggingConfig.set_request_id("req-xyz")
        assert LoggingConfig.get_request_id() == "req-xyz"
        LoggingConfig.clear_request_id()

    def test_clear_request_id(self):
        LoggingConfig.set_request_id("req-abc")
        LoggingConfig.clear_request_id()
        assert LoggingConfig.get_request_id() is None


# ─── Module-level convenience functions ─────────────────────────────────


class TestConvenienceFunctions:
    def setup_method(self):
        clear_request_id()

    def teardown_method(self):
        clear_request_id()

    def test_setup_logging_returns_config(self, tmp_path):
        config = setup_logging(
            log_dir=str(tmp_path), log_level='DEBUG')
        assert isinstance(config, LoggingConfig)

    def test_get_logger_auto_initializes(self, tmp_path):
        # Reset singleton
        logging_config._logging_config = None
        with patch.object(logging_config, 'setup_logging',
                          wraps=logging_config.setup_logging) as mock_setup:
            logger = get_logger("auto_init_test")
            assert isinstance(logger, logging.Logger)

    def test_get_logger_returns_named_logger(self, tmp_path):
        setup_logging(log_dir=str(tmp_path))
        logger = get_logger("my_module")
        assert logger.name == "my_module"

    def test_set_and_get_request_id_convenience(self):
        set_request_id("conv-123")
        assert get_request_id() == "conv-123"

    def test_clear_request_id_convenience(self):
        set_request_id("conv-456")
        clear_request_id()
        assert get_request_id() is None

    def test_mask_token_convenience(self):
        result = mask_token("abcdefghijklmnopqrstuvwxyz")
        assert result == "abcd...[MASKED]wxyz"

    def test_mask_token_short(self):
        result = mask_token("short")
        assert result == "****"

    def test_setup_logging_reinitializes(self, tmp_path):
        config1 = setup_logging(log_dir=str(tmp_path), log_level='INFO')
        config2 = setup_logging(log_dir=str(tmp_path), log_level='DEBUG')
        assert config2.log_level == logging.DEBUG


# ─── Integration: full pipeline ─────────────────────────────────────────


class TestLoggingIntegration:
    def test_full_pipeline_logs_with_masking_and_request_id(self, tmp_path):
        config = setup_logging(log_dir=str(tmp_path), log_level='DEBUG')
        logger = get_logger("integration_test")

        set_request_id("int-test-001")
        logger.info("Processing build error",
                     extra={'build_id': 42, 'project_name': 'test-proj'})
        clear_request_id()

        log_file = tmp_path / "bfa-service.log"
        content = log_file.read_text()
        assert "int-test-001" in content
        assert "Processing build error" in content
        assert "build_id=42" in content

    def test_sensitive_data_masked_in_file(self, tmp_path):
        config = setup_logging(log_dir=str(tmp_path), log_level='DEBUG')
        logger = get_logger("mask_test")

        set_request_id("mask-001")
        logger.info("Using token: %s",
                     "xoxb-1234567890abcdefghijklmnopqrst")
        clear_request_id()

        log_file = tmp_path / "bfa-service.log"
        content = log_file.read_text()
        assert "xoxb-1234567890abcdefghijklmnopqrst" not in content
        assert "[MASKED]" in content

    def test_exception_logging(self, tmp_path):
        config = setup_logging(log_dir=str(tmp_path), log_level='DEBUG')
        logger = get_logger("exc_test")

        try:
            raise RuntimeError("test exception for logging")
        except RuntimeError:
            logger.exception("Caught error")

        log_file = tmp_path / "bfa-service.log"
        content = log_file.read_text()
        assert "RuntimeError: test exception for logging" in content
