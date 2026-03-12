"""
Centralized Logging Configuration for Build Failure Analyzer

Adapted from the log-extractor's logging module, tailored for BFA service.

Features:
- Pipe-delimited plain text format
- Application log file with rotation
- Request ID correlation across all logs
- Sensitive data masking (tokens, secrets, API keys, Slack tokens)
- Console and file output

Format:
timestamp | level | logger | request_id | message | context

Example:
2026-01-16 10:15:30.123 | INFO   | analyzer                  | a1b2c3d4 | Build error analyzed | build_id=12345 project=my-app

Invoked by: analyzer_service, slack_reviewer, resolver_agent, etc.
Invokes: None
"""

import logging
import logging.handlers
import re
import sys
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

# Context variable for request ID (thread-safe for async)
request_id_var: ContextVar[Optional[str]] = ContextVar('request_id', default=None)


class SensitiveDataFilter(logging.Filter):
    """
    Filter to mask sensitive data in log messages.

    Masks:
    - Slack bot tokens (xoxb-*, xoxp-*, xapp-*)
    - OpenWebUI API keys
    - JWT tokens
    - Generic tokens/secrets in URLs and headers
    - Authorization headers
    - Redis connection strings with passwords
    """

    PATTERNS = [
        re.compile(r'(xoxb-)([a-zA-Z0-9_-]{20,})'),           # Slack bot token
        re.compile(r'(xoxp-)([a-zA-Z0-9_-]{20,})'),           # Slack user token
        re.compile(r'(xapp-)([a-zA-Z0-9_-]{20,})'),           # Slack app token
        re.compile(r'(Bearer\s+)([A-Za-z0-9._-]{20,})', re.IGNORECASE),  # JWT/Bearer
        re.compile(r'(token[=:]\s*)([^\s&]+)', re.IGNORECASE),  # Generic tokens
        re.compile(r'(secret[=:]\s*)([^\s&]+)', re.IGNORECASE),  # Secrets
        re.compile(r'(password[=:]\s*)([^\s&]+)', re.IGNORECASE),  # Passwords
        re.compile(r'(api[_-]?key[=:]\s*)([^\s&]+)', re.IGNORECASE),  # API keys
        re.compile(r'(Authorization:\s+(?:Bearer\s+)?)([^\s]+)', re.IGNORECASE),  # Auth headers
        re.compile(r'(PRIVATE-TOKEN:\s*)([^\s]+)', re.IGNORECASE),  # GitLab token header
        re.compile(r'(redis://[^:]*:)([^@]+)(@)', re.IGNORECASE),  # Redis password in URL
    ]

    def filter(self, record: logging.LogRecord) -> bool:
        """Mask sensitive data in log message args"""
        if hasattr(record, 'args') and record.args:
            if isinstance(record.args, dict):
                record.args = self._mask_dict(record.args)
            elif isinstance(record.args, tuple):
                record.args = tuple(self._mask_value(arg) for arg in record.args)

        return True

    def _mask_dict(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Mask sensitive values in dictionary"""
        masked = {}
        sensitive_keys = ['token', 'secret', 'password', 'auth', 'api_key', 'apikey',
                          'signing_secret', 'bot_token']
        for key, value in data.items():
            if isinstance(key, str) and any(s in key.lower() for s in sensitive_keys):
                masked[key] = self._mask_token(str(value))
            elif isinstance(value, dict):
                masked[key] = self._mask_dict(value)
            else:
                masked[key] = self._mask_value(value)
        return masked

    def _mask_value(self, value: Any) -> Any:
        """Mask value if it matches a sensitive pattern"""
        if isinstance(value, str) and len(value) > 20:
            for pattern in self.PATTERNS:
                match = pattern.search(value)
                if match:
                    prefix = match.group(1)
                    token_value = match.group(2)
                    masked_token = self._mask_token(token_value)
                    return pattern.sub(rf'{prefix}{masked_token}', value)
        return value

    @staticmethod
    def _mask_token(token: str) -> str:
        """Mask token showing only first and last 4 characters"""
        if not token or len(token) < 12:
            return "****"
        return f"{token[:4]}...[MASKED]{token[-4:]}"


class RequestIdFilter(logging.Filter):
    """
    Filter to add request ID to log records from context.

    Request ID is stored in contextvars and automatically added to all logs
    within the same async context. Useful for tracing a single build analysis
    request across analyzer, resolver, vector DB, and Slack operations.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """Add request ID from context to log record"""
        record.request_id = request_id_var.get() or 'N/A'
        return True


class PipeDelimitedFormatter(logging.Formatter):
    """
    Custom formatter for pipe-delimited log format with aligned columns.

    Format: timestamp | level | logger | request_id | message | context

    Example:
    2026-01-16 10:15:30.123 | INFO   | resolver_agent            | a1b2c3d4 | Fix found in vector DB | build_id=999
    """

    LEVEL_WIDTH = 6
    LOGGER_WIDTH = 25
    REQUEST_ID_WIDTH = 8

    def format(self, record: logging.LogRecord) -> str:
        """Format log record with pipe delimiters and aligned columns"""
        timestamp = datetime.fromtimestamp(record.created).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]

        level = record.levelname.ljust(self.LEVEL_WIDTH)

        logger_name = record.name
        if len(logger_name) > self.LOGGER_WIDTH:
            logger_name = logger_name[:self.LOGGER_WIDTH - 3] + '...'
        else:
            logger_name = logger_name.ljust(self.LOGGER_WIDTH)

        request_id = getattr(record, 'request_id', 'N/A')
        request_id = request_id.ljust(self.REQUEST_ID_WIDTH)

        message = record.getMessage()

        # Extract context from extra fields relevant to BFA
        context_parts = []
        extra_fields = [
            'build_id', 'project_name', 'error_hash', 'fix_id',
            'slack_channel', 'slack_user', 'action', 'similarity_score',
            'confidence', 'source', 'duration_ms', 'status_code',
            'operation', 'endpoint', 'vector_count', 'error_type'
        ]

        for field in extra_fields:
            if hasattr(record, field):
                value = getattr(record, field)
                if value is not None:
                    context_parts.append(f"{field}={value}")

        context = ' '.join(context_parts) if context_parts else ''

        if context:
            log_line = f"{timestamp} | {level} | {logger_name} | {request_id} | {message} | {context}"
        else:
            log_line = f"{timestamp} | {level} | {logger_name} | {request_id} | {message}"

        if record.exc_info and not record.exc_text:
            record.exc_text = self.formatException(record.exc_info)

        if record.exc_text:
            log_line = log_line + '\n' + record.exc_text

        if record.stack_info:
            log_line = log_line + '\n' + self.formatStack(record.stack_info)

        return log_line


class LoggingConfig:
    """
    Centralized logging configuration manager for BFA service.

    Sets up:
    - Application log file with rotation (50MB, 5 backups)
    - Console output (stdout)
    - Request ID tracking for cross-module correlation
    - Sensitive data masking (Slack tokens, API keys, JWT)
    """

    def __init__(self, log_dir: str = './logs', log_level: str = 'INFO'):
        """
        Initialize logging configuration.

        Args:
            log_dir: Directory for log files
            log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        """
        self.log_dir = Path(log_dir)
        self.log_level = getattr(logging, log_level.upper(), logging.INFO)

        self.log_dir.mkdir(parents=True, exist_ok=True)

        self._setup_logging()

    def _setup_logging(self):
        """Configure all logging handlers and formatters"""
        formatter = PipeDelimitedFormatter()

        root_logger = logging.getLogger()
        root_logger.setLevel(self.log_level)

        root_logger.handlers.clear()

        # Console Handler (stdout)
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(self.log_level)
        console_handler.setFormatter(formatter)
        console_handler.addFilter(RequestIdFilter())
        console_handler.addFilter(SensitiveDataFilter())
        root_logger.addHandler(console_handler)

        # Application Log File with rotation
        app_handler = logging.handlers.RotatingFileHandler(
            filename=self.log_dir / 'bfa-service.log',
            maxBytes=50 * 1024 * 1024,  # 50MB
            backupCount=5,
            encoding='utf-8'
        )
        app_handler.setLevel(self.log_level)
        app_handler.setFormatter(formatter)
        app_handler.addFilter(RequestIdFilter())
        app_handler.addFilter(SensitiveDataFilter())
        root_logger.addHandler(app_handler)

    @staticmethod
    def get_logger(name: str) -> logging.Logger:
        """Get logger for a module."""
        return logging.getLogger(name)

    @staticmethod
    def set_request_id(request_id: str):
        """Set request ID in context for current async task."""
        request_id_var.set(request_id)

    @staticmethod
    def clear_request_id():
        """Clear request ID from context."""
        request_id_var.set(None)

    @staticmethod
    def get_request_id() -> Optional[str]:
        """Get current request ID from context."""
        return request_id_var.get()


# Singleton instance
_logging_config: Optional[LoggingConfig] = None


def setup_logging(log_dir: str = './logs', log_level: str = 'INFO') -> LoggingConfig:
    """
    Initialize logging configuration (call once at startup).

    Args:
        log_dir: Directory for log files
        log_level: Logging level

    Returns:
        LoggingConfig instance
    """
    global _logging_config
    _logging_config = LoggingConfig(log_dir=log_dir, log_level=log_level)
    return _logging_config


def get_logger(name: str) -> logging.Logger:
    """
    Get logger for a module (convenience function).

    Args:
        name: Logger name (typically __name__)

    Returns:
        Configured logger instance
    """
    if _logging_config is None:
        setup_logging()
    return logging.getLogger(name)


def set_request_id(request_id: str):
    """Set request ID for current context."""
    LoggingConfig.set_request_id(request_id)


def clear_request_id():
    """Clear request ID from context."""
    LoggingConfig.clear_request_id()


def get_request_id() -> Optional[str]:
    """Get current request ID."""
    return LoggingConfig.get_request_id()


def mask_token(token: str) -> str:
    """
    Mask a token for safe logging.

    Args:
        token: Token to mask

    Returns:
        Masked token (e.g., "xoxb...[MASKED]xyz9")
    """
    return SensitiveDataFilter._mask_token(token)


if __name__ == "__main__":
    setup_logging(log_level='DEBUG')

    logger = get_logger(__name__)

    set_request_id('test123')

    logger.debug("Debug message test")
    logger.info("Build error analyzed", extra={'build_id': 12345, 'project_name': 'my-app'})
    logger.warning("Low similarity score", extra={'similarity_score': 0.65, 'fix_id': 'fix-abc'})
    logger.error("LLM call failed", extra={'error_type': 'TimeoutError', 'duration_ms': 30000})

    logger.info("Slack token: xoxb-1234567890abcdefghijklmnop", extra={'operation': 'slack_post'})

    try:
        raise ValueError("Test exception for logging")
    except ValueError:
        logger.exception("An error occurred during analysis")

    clear_request_id()

    print("\nLogging test complete! Check ./logs/ directory for bfa-service.log")
