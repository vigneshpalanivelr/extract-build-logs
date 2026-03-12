"""
Tests for config_loader.py — centralized configuration loading and validation.
"""

import os
import sys
import pytest
from unittest.mock import patch, MagicMock

# Ensure src/ is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


# ----------------------------------------------------------------
# Helper: import config_loader fresh (avoid module-level singleton)
# ----------------------------------------------------------------
def _import_config_loader():
    """Import config_loader module fresh, bypassing cached singleton."""
    import importlib
    # Remove cached module if present
    if "config_loader" in sys.modules:
        del sys.modules["config_loader"]
    return importlib.import_module("config_loader")


# ----------------------------------------------------------------
# Tests for _parse_csv_list
# ----------------------------------------------------------------
class TestParseCsvList:
    def test_empty_string(self):
        mod = _import_config_loader()
        assert mod._parse_csv_list("") == []

    def test_single_value(self):
        mod = _import_config_loader()
        assert mod._parse_csv_list("alice@example.com") == ["alice@example.com"]

    def test_multiple_values(self):
        mod = _import_config_loader()
        result = mod._parse_csv_list("a@test.com, b@test.com, c@test.com")
        assert result == ["a@test.com", "b@test.com", "c@test.com"]

    def test_strips_whitespace(self):
        mod = _import_config_loader()
        result = mod._parse_csv_list("  foo ,  bar  ,  baz  ")
        assert result == ["foo", "bar", "baz"]

    def test_filters_empty_entries(self):
        mod = _import_config_loader()
        result = mod._parse_csv_list("a,,b, ,c")
        assert result == ["a", "b", "c"]


# ----------------------------------------------------------------
# Tests for _get_env helpers
# ----------------------------------------------------------------
class TestGetEnvHelpers:
    def test_get_env_returns_value(self):
        mod = _import_config_loader()
        with patch.dict(os.environ, {"TEST_VAR_XYZ": "hello"}):
            assert mod._get_env("TEST_VAR_XYZ") == "hello"

    def test_get_env_returns_empty_when_missing(self):
        mod = _import_config_loader()
        os.environ.pop("TEST_VAR_MISSING_ABC", None)
        assert mod._get_env("TEST_VAR_MISSING_ABC") == ""

    def test_get_env_int_valid(self):
        mod = _import_config_loader()
        with patch.dict(os.environ, {"TEST_INT": "42"}):
            assert mod._get_env_int("TEST_INT", 0) == 42

    def test_get_env_int_empty_returns_default(self):
        mod = _import_config_loader()
        os.environ.pop("TEST_INT_EMPTY", None)
        assert mod._get_env_int("TEST_INT_EMPTY", 99) == 99

    def test_get_env_int_invalid_returns_default(self):
        mod = _import_config_loader()
        with patch.dict(os.environ, {"TEST_INT_BAD": "notanumber"}):
            assert mod._get_env_int("TEST_INT_BAD", 7) == 7

    def test_get_env_float_valid(self):
        mod = _import_config_loader()
        with patch.dict(os.environ, {"TEST_FLOAT": "0.75"}):
            assert mod._get_env_float("TEST_FLOAT", 0.0) == 0.75

    def test_get_env_float_empty_returns_default(self):
        mod = _import_config_loader()
        os.environ.pop("TEST_FLOAT_EMPTY", None)
        assert mod._get_env_float("TEST_FLOAT_EMPTY", 3.14) == 3.14

    def test_get_env_float_invalid_returns_default(self):
        mod = _import_config_loader()
        with patch.dict(os.environ, {"TEST_FLOAT_BAD": "abc"}):
            assert mod._get_env_float("TEST_FLOAT_BAD", 1.5) == 1.5

    def test_get_env_bool_true_values(self):
        mod = _import_config_loader()
        for val in ("true", "True", "TRUE", "1", "yes", "on"):
            with patch.dict(os.environ, {"TEST_BOOL": val}):
                assert mod._get_env_bool("TEST_BOOL", False) is True

    def test_get_env_bool_false_values(self):
        mod = _import_config_loader()
        for val in ("false", "False", "0", "no", "off", "anything"):
            with patch.dict(os.environ, {"TEST_BOOL": val}):
                assert mod._get_env_bool("TEST_BOOL", True) is False

    def test_get_env_bool_empty_returns_default(self):
        mod = _import_config_loader()
        os.environ.pop("TEST_BOOL_EMPTY", None)
        assert mod._get_env_bool("TEST_BOOL_EMPTY", True) is True
        assert mod._get_env_bool("TEST_BOOL_EMPTY", False) is False


# ----------------------------------------------------------------
# Tests for load_config
# ----------------------------------------------------------------
class TestLoadConfig:
    @patch("config_loader.load_dotenv")
    def test_loads_with_defaults(self, mock_dotenv):
        mod = _import_config_loader()
        # Clear env vars so all get defaults
        env_override = {}
        with patch.dict(os.environ, env_override, clear=False):
            cfg = mod.load_config()
        assert cfg.redis_port == 6379
        assert cfg.redis_db == 0
        assert cfg.ollama_timeout == 30
        assert cfg.similarity_threshold == 0.78
        assert cfg.max_error_lines == 80
        assert cfg.max_error_chars == 4000
        assert cfg.length_penalty_alpha == 0.15
        assert cfg.vector_top_k == 5
        assert cfg.domain_rag_threshold == 0.55
        assert cfg.domain_rag_top_k == 5
        assert cfg.global_context_max_chars == 6000
        assert cfg.redis_ttl_ai == 86400
        assert cfg.ai_fix_ttl == 86400
        assert cfg.llm_generated_confidence == 0.6
        assert cfg.slack_max_block_len == 2500
        assert cfg.error_summary_max_chars == 300
        assert cfg.smtp_port == 25
        assert cfg.smtp_timeout == 10
        assert cfg.traceback_max_chars == 3500
        assert cfg.flask_port == 5001
        assert cfg.flask_debug is False
        assert cfg.bfa_port == 8000
        assert cfg.bfa_log_level == "INFO"
        assert cfg.bfa_log_dir == "./logs"
        assert cfg.jwt_expiry_minutes == 60
        assert cfg.jwt_ttl_seconds == 60
        assert cfg.openwebui_timeout == 60
        assert cfg.openwebui_retries == 2
        assert cfg.openwebui_backoff == 0.5

    @patch("config_loader.load_dotenv")
    def test_loads_env_vars(self, mock_dotenv):
        mod = _import_config_loader()
        env = {
            "SLACK_BOT_TOKEN": "xoxb-test-token",
            "SLACK_CHANNEL": "#test-channel",
            "REDIS_PORT": "6380",
            "BFA_PORT": "9000",
            "FLASK_DEBUG": "true",
            "SIMILARITY_THRESHOLD": "0.85",
            "ALERT_SLACK_EMAILS": "a@test.com, b@test.com",
        }
        with patch.dict(os.environ, env, clear=False):
            cfg = mod.load_config()
        assert cfg.slack_bot_token == "xoxb-test-token"
        assert cfg.slack_channel == "#test-channel"
        assert cfg.redis_port == 6380
        assert cfg.bfa_port == 9000
        assert cfg.flask_debug is True
        assert cfg.similarity_threshold == 0.85
        assert cfg.alert_slack_emails == ["a@test.com", "b@test.com"]

    @patch("config_loader.load_dotenv")
    def test_csv_list_fields(self, mock_dotenv):
        mod = _import_config_loader()
        env = {
            "ALERT_SLACK_EMAILS": "user1@slack.com,user2@slack.com",
            "ALERT_EMAIL_TO": "ops@company.com",
        }
        with patch.dict(os.environ, env, clear=False):
            cfg = mod.load_config()
        assert cfg.alert_slack_emails == ["user1@slack.com", "user2@slack.com"]
        assert cfg.alert_email_to == ["ops@company.com"]


# ----------------------------------------------------------------
# Tests for validate_config
# ----------------------------------------------------------------
class TestValidateConfig:
    def _make_valid_analyzer_config(self, tmp_path):
        """Create a Config with all required analyzer fields set."""
        mod = _import_config_loader()
        # Create a fake public key file
        pubkey = tmp_path / "public.pem"
        pubkey.write_text("fake-public-key")
        return mod.Config(
            slack_bot_token="xoxb-test",
            slack_channel="#builds",
            openwebui_api_key="test-key",
            openwebui_base_url="http://localhost:8080",
            jwt_public_key_path=str(pubkey),
            redis_url="redis://localhost:6379/0",
            chroma_db_path="/var/lib/chroma",
            ollama_http_url="http://localhost:11434",
            ollama_embed_model="granite-embedding",
            bfa_port=8000,
            bfa_log_level="INFO",
            similarity_threshold=0.78,
        )

    def test_analyzer_mode_valid(self, tmp_path):
        mod = _import_config_loader()
        cfg = self._make_valid_analyzer_config(tmp_path)
        errors = mod.validate_config(cfg, mode="analyzer")
        assert errors == []

    def test_analyzer_mode_missing_slack_token(self, tmp_path):
        mod = _import_config_loader()
        cfg = self._make_valid_analyzer_config(tmp_path)
        cfg.slack_bot_token = ""
        errors = mod.validate_config(cfg, mode="analyzer")
        assert any("SLACK_BOT_TOKEN" in e for e in errors)

    def test_analyzer_mode_missing_slack_channel(self, tmp_path):
        mod = _import_config_loader()
        cfg = self._make_valid_analyzer_config(tmp_path)
        cfg.slack_channel = ""
        errors = mod.validate_config(cfg, mode="analyzer")
        assert any("SLACK_CHANNEL" in e for e in errors)

    def test_analyzer_mode_missing_openwebui_api_key(self, tmp_path):
        mod = _import_config_loader()
        cfg = self._make_valid_analyzer_config(tmp_path)
        cfg.openwebui_api_key = ""
        errors = mod.validate_config(cfg, mode="analyzer")
        assert any("OPENWEBUI_API_KEY" in e for e in errors)

    def test_analyzer_mode_missing_openwebui_base_url(self, tmp_path):
        mod = _import_config_loader()
        cfg = self._make_valid_analyzer_config(tmp_path)
        cfg.openwebui_base_url = ""
        errors = mod.validate_config(cfg, mode="analyzer")
        assert any("OPENWEBUI_BASE_URL" in e for e in errors)

    def test_analyzer_mode_missing_jwt_public_key_path(self, tmp_path):
        mod = _import_config_loader()
        cfg = self._make_valid_analyzer_config(tmp_path)
        cfg.jwt_public_key_path = ""
        errors = mod.validate_config(cfg, mode="analyzer")
        assert any("JWT_PUBLIC_KEY_PATH" in e for e in errors)

    def test_analyzer_mode_jwt_file_not_found(self, tmp_path):
        mod = _import_config_loader()
        cfg = self._make_valid_analyzer_config(tmp_path)
        cfg.jwt_public_key_path = "/nonexistent/path/public.pem"
        errors = mod.validate_config(cfg, mode="analyzer")
        assert any("file not found" in e for e in errors)

    def test_analyzer_mode_missing_redis(self, tmp_path):
        mod = _import_config_loader()
        cfg = self._make_valid_analyzer_config(tmp_path)
        cfg.redis_url = ""
        cfg.redis_host = ""
        errors = mod.validate_config(cfg, mode="analyzer")
        assert any("REDIS" in e for e in errors)

    def test_analyzer_mode_redis_host_alone_is_valid(self, tmp_path):
        mod = _import_config_loader()
        cfg = self._make_valid_analyzer_config(tmp_path)
        cfg.redis_url = ""
        cfg.redis_host = "localhost"
        errors = mod.validate_config(cfg, mode="analyzer")
        assert not any("REDIS" in e for e in errors)

    def test_analyzer_mode_missing_chroma(self, tmp_path):
        mod = _import_config_loader()
        cfg = self._make_valid_analyzer_config(tmp_path)
        cfg.chroma_db_path = ""
        errors = mod.validate_config(cfg, mode="analyzer")
        assert any("CHROMA_DB_PATH" in e for e in errors)

    def test_analyzer_mode_missing_ollama_url(self, tmp_path):
        mod = _import_config_loader()
        cfg = self._make_valid_analyzer_config(tmp_path)
        cfg.ollama_http_url = ""
        errors = mod.validate_config(cfg, mode="analyzer")
        assert any("OLLAMA_HTTP_URL" in e for e in errors)

    def test_analyzer_mode_missing_ollama_model(self, tmp_path):
        mod = _import_config_loader()
        cfg = self._make_valid_analyzer_config(tmp_path)
        cfg.ollama_embed_model = ""
        errors = mod.validate_config(cfg, mode="analyzer")
        assert any("OLLAMA_EMBED_MODEL" in e for e in errors)

    def test_analyzer_mode_bad_similarity_threshold(self, tmp_path):
        mod = _import_config_loader()
        cfg = self._make_valid_analyzer_config(tmp_path)
        cfg.similarity_threshold = 1.5
        errors = mod.validate_config(cfg, mode="analyzer")
        assert any("SIMILARITY_THRESHOLD" in e for e in errors)

    def test_analyzer_mode_negative_similarity_threshold(self, tmp_path):
        mod = _import_config_loader()
        cfg = self._make_valid_analyzer_config(tmp_path)
        cfg.similarity_threshold = -0.1
        errors = mod.validate_config(cfg, mode="analyzer")
        assert any("SIMILARITY_THRESHOLD" in e for e in errors)

    def test_analyzer_mode_bad_port(self, tmp_path):
        mod = _import_config_loader()
        cfg = self._make_valid_analyzer_config(tmp_path)
        cfg.bfa_port = 0
        errors = mod.validate_config(cfg, mode="analyzer")
        assert any("BFA_PORT" in e for e in errors)

    def test_analyzer_mode_port_too_high(self, tmp_path):
        mod = _import_config_loader()
        cfg = self._make_valid_analyzer_config(tmp_path)
        cfg.bfa_port = 70000
        errors = mod.validate_config(cfg, mode="analyzer")
        assert any("BFA_PORT" in e for e in errors)

    def test_analyzer_mode_bad_log_level(self, tmp_path):
        mod = _import_config_loader()
        cfg = self._make_valid_analyzer_config(tmp_path)
        cfg.bfa_log_level = "VERBOSE"
        errors = mod.validate_config(cfg, mode="analyzer")
        assert any("BFA_LOG_LEVEL" in e for e in errors)

    def test_analyzer_mode_valid_log_levels(self, tmp_path):
        mod = _import_config_loader()
        for level in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
            cfg = self._make_valid_analyzer_config(tmp_path)
            cfg.bfa_log_level = level
            errors = mod.validate_config(cfg, mode="analyzer")
            assert not any("BFA_LOG_LEVEL" in e for e in errors)

    def test_analyzer_mode_multiple_errors(self, tmp_path):
        mod = _import_config_loader()
        cfg = mod.Config()  # All defaults = empty
        errors = mod.validate_config(cfg, mode="analyzer")
        assert len(errors) >= 3  # At least slack_bot_token, channel, openwebui, etc.

    def test_reviewer_mode_valid(self, tmp_path):
        mod = _import_config_loader()
        cfg = mod.Config(
            slack_bot_token="xoxb-test",
            chroma_db_path="/var/lib/chroma",
            redis_host="localhost",
            flask_port=5001,
        )
        errors = mod.validate_config(cfg, mode="reviewer")
        assert errors == []

    def test_reviewer_mode_missing_chroma(self):
        mod = _import_config_loader()
        cfg = mod.Config(
            slack_bot_token="xoxb-test",
            redis_host="localhost",
            flask_port=5001,
        )
        errors = mod.validate_config(cfg, mode="reviewer")
        assert any("CHROMA_DB_PATH" in e for e in errors)

    def test_reviewer_mode_missing_redis(self):
        mod = _import_config_loader()
        cfg = mod.Config(
            slack_bot_token="xoxb-test",
            chroma_db_path="/var/lib/chroma",
            flask_port=5001,
        )
        errors = mod.validate_config(cfg, mode="reviewer")
        assert any("REDIS" in e for e in errors)

    def test_reviewer_mode_bad_port(self):
        mod = _import_config_loader()
        cfg = mod.Config(
            slack_bot_token="xoxb-test",
            chroma_db_path="/var/lib/chroma",
            redis_host="localhost",
            flask_port=0,
        )
        errors = mod.validate_config(cfg, mode="reviewer")
        assert any("FLASK_PORT" in e for e in errors)

    def test_script_mode_minimal(self):
        mod = _import_config_loader()
        cfg = mod.Config(slack_bot_token="xoxb-test")
        errors = mod.validate_config(cfg, mode="script")
        assert errors == []

    def test_script_mode_missing_token(self):
        mod = _import_config_loader()
        cfg = mod.Config()
        errors = mod.validate_config(cfg, mode="script")
        assert any("SLACK_BOT_TOKEN" in e for e in errors)


# ----------------------------------------------------------------
# Tests for init_config
# ----------------------------------------------------------------
class TestInitConfig:
    @patch("config_loader.load_dotenv")
    def test_exits_on_validation_failure(self, mock_dotenv):
        mod = _import_config_loader()
        # No env vars set = missing required fields
        with pytest.raises(SystemExit) as exc_info:
            mod.init_config(mode="analyzer")
        assert exc_info.value.code == 1

    @patch("config_loader.load_dotenv")
    def test_returns_config_on_success(self, mock_dotenv, tmp_path):
        mod = _import_config_loader()
        pubkey = tmp_path / "public.pem"
        pubkey.write_text("fake-key")
        env = {
            "SLACK_BOT_TOKEN": "xoxb-test",
            "SLACK_CHANNEL": "#builds",
            "OPENWEBUI_API_KEY": "test-key",
            "OPENWEBUI_BASE_URL": "http://localhost:8080",
            "JWT_PUBLIC_KEY_PATH": str(pubkey),
            "REDIS_URL": "redis://localhost:6379/0",
            "CHROMA_DB_PATH": "/var/lib/chroma",
            "OLLAMA_HTTP_URL": "http://localhost:11434",
            "OLLAMA_EMBED_MODEL": "granite-embedding",
        }
        with patch.dict(os.environ, env, clear=False):
            cfg = mod.init_config(mode="analyzer")
        assert cfg.slack_bot_token == "xoxb-test"
        assert cfg.bfa_port == 8000

    @patch("config_loader.load_dotenv")
    def test_script_mode_accepts_minimal(self, mock_dotenv):
        mod = _import_config_loader()
        env = {"SLACK_BOT_TOKEN": "xoxb-test"}
        with patch.dict(os.environ, env, clear=False):
            cfg = mod.init_config(mode="script")
        assert cfg.slack_bot_token == "xoxb-test"

    @patch("config_loader.load_dotenv")
    def test_stderr_output_on_failure(self, mock_dotenv, capsys):
        mod = _import_config_loader()
        with pytest.raises(SystemExit):
            mod.init_config(mode="analyzer")
        captured = capsys.readouterr()
        assert "CONFIGURATION ERROR" in captured.err
        assert "Cannot start BFA service" in captured.err
        assert ".env" in captured.err


# ----------------------------------------------------------------
# Tests for Config dataclass
# ----------------------------------------------------------------
class TestConfigDataclass:
    def test_default_values(self):
        mod = _import_config_loader()
        cfg = mod.Config()
        assert cfg.slack_bot_token == ""
        assert cfg.redis_port == 6379
        assert cfg.flask_debug is False
        assert cfg.alert_slack_emails == []
        assert cfg.alert_email_to == []

    def test_fields_are_mutable(self):
        mod = _import_config_loader()
        cfg = mod.Config()
        cfg.slack_bot_token = "changed"
        assert cfg.slack_bot_token == "changed"

    def test_list_fields_independent(self):
        """Ensure list default_factory creates independent instances."""
        mod = _import_config_loader()
        cfg1 = mod.Config()
        cfg2 = mod.Config()
        cfg1.alert_slack_emails.append("test@test.com")
        assert cfg2.alert_slack_emails == []
