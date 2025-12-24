"""
Centralized Logging Configuration Module

This module provides comprehensive logging configuration for the GitLab Pipeline
Log Extraction System with the following features:

- Pipe-delimited plain text format
- Multiple log files (application, access, performance)
- Request ID correlation across all logs
- Sensitive data masking (tokens, secrets)
- Log rotation with size limits
- DEBUG level logging
- Console and file output
- API endpoints for log querying

Format:
timestamp | level | logger | request_id | message | context

Example:
2024-01-01 10:15:30.123 | INFO | webhook_listener | a1b2c3d4 | Webhook received | pipeline_id=12345 project_id=100

Note: All logs including errors are kept in application.log to maintain context and traceability.

We don't need below handlers
- access_logger
src.logging_config.py
# Mention the script that are invoking this script
- script1
- script2
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
    - GitLab tokens (glpat-*, gldt-*)
    - Generic tokens in URLs
    - Webhook secrets
    - Authorization headers
    """

    # Patterns for sensitive data
    PATTERNS = [
        (re.compile(r'(glpat-)[a-zA-Z0-9_-]{20,}'), r'\1****'),  # GitLab personal access token
        (re.compile(r'(gldt-)[a-zA-Z0-9_-]{20,}'), r'\1****'),   # GitLab deploy token
        (re.compile(r'(token[=:]\s*)[^\s&]+', re.IGNORECASE), r'\1****'),  # Generic tokens
        (re.compile(r'(secret[=:]\s*)[^\s&]+', re.IGNORECASE), r'\1****'),  # Secrets
        (re.compile(r'(Authorization:\s*)[^\s]+', re.IGNORECASE), r'\1****'),  # Auth headers
        (re.compile(r'(PRIVATE-TOKEN:\s*)[^\s]+', re.IGNORECASE), r'\1****'),  # GitLab token header
    ]

    def filter(self, record: logging.LogRecord) -> bool:
        """Mask sensitive data in log message"""
        # Don't filter the msg template - it contains format specifiers like %s
        # Only filter the args that will be substituted into the template

        # Mask in args
        if hasattr(record, 'args') and record.args:
            if isinstance(record.args, dict):
                record.args = self._mask_dict(record.args)
            elif isinstance(record.args, tuple):
                record.args = tuple(self._mask_value(arg) for arg in record.args)

        return True

    def _mask_dict(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Mask sensitive values in dictionary"""
        masked = {}
        sensitive_keys = ['token', 'secret', 'password', 'auth']
        for key, value in data.items():
            if isinstance(key, str) and any(s in key.lower() for s in sensitive_keys):
                masked[key] = self._mask_token(str(value))
            elif isinstance(value, dict):
                masked[key] = self._mask_dict(value)
            else:
                masked[key] = self._mask_value(value)
        return masked

    def _mask_value(self, value: Any) -> Any:
        """Mask value if it looks like a token"""
        if isinstance(value, str) and len(value) > 20:
            for pattern, replacement in self.PATTERNS:
                if pattern.search(value):
                    return pattern.sub(replacement, value)
        return value

    @staticmethod
    def _mask_token(token: str) -> str:
        """Mask token showing only first and last 4 characters"""
        if not token or len(token) < 12:
            return "****"
        return f"{token[:4]}...{token[-4:]}"


class RequestIdFilter(logging.Filter):
    """
    Filter to add request ID to log records from context.

    Request ID is stored in contextvars and automatically added to all logs
    within the same async context.
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
    2024-01-01 10:15:30.123 | INFO     | src.webhook_listener       | a1b2c3d4 | Webhook received | pipeline_id=12345
    """

    # Column widths for alignment
    LEVEL_WIDTH = 8
    LOGGER_WIDTH = 30
    REQUEST_ID_WIDTH = 8

    def format(self, record: logging.LogRecord) -> str:
        """Format log record with pipe delimiters and aligned columns"""
        # Get timestamp with milliseconds (fixed width: 23 chars)
        timestamp = datetime.fromtimestamp(record.created).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]

        # Get basic fields with padding
        level = record.levelname.ljust(self.LEVEL_WIDTH)

        # Truncate or pad logger name
        logger = record.name  # pylint: disable=redefined-outer-name
        if len(logger) > self.LOGGER_WIDTH:
            logger = logger[:self.LOGGER_WIDTH - 3] + '...'
        else:
            logger = logger.ljust(self.LOGGER_WIDTH)

        # Pad request ID
        request_id = getattr(record, 'request_id', 'N/A')
        request_id = request_id.ljust(self.REQUEST_ID_WIDTH)

        # Format the main message
        message = record.getMessage()

        # Extract context from extra fields
        context_parts = []

        # Standard extra fields we want to include
        extra_fields = ['pipeline_id', 'project_id', 'project_name', 'job_id', 'event_type', 'source_ip',
                        'duration_ms', 'status_code', 'operation', 'path', 'error_type']

        for field in extra_fields:
            if hasattr(record, field):
                value = getattr(record, field)
                if value is not None:
                    context_parts.append(f"{field}={value}")

        # Add context string
        context = ' '.join(context_parts) if context_parts else ''

        # Build final log line
        if context:
            log_line = f"{timestamp} | {level} | {logger} | {request_id} | {message} | {context}"
        else:
            log_line = f"{timestamp} | {level} | {logger} | {request_id} | {message}"

        # Add exception info if present
        if record.exc_info and not record.exc_text:
            record.exc_text = self.formatException(record.exc_info)

        if record.exc_text:
            log_line = log_line + '\n' + record.exc_text

        if record.stack_info:
            log_line = log_line + '\n' + self.formatStack(record.stack_info)

        return log_line


class LoggingConfig:
    """
    Centralized logging configuration manager.

    Sets up:
    - Multiple log files (application, access, performance)
    - Console output
    - Log rotation
    - Request ID tracking
    - Sensitive data masking
    """

    def __init__(self, log_dir: str = './logs', log_level: str = 'INFO'):
        """
        Initialize logging configuration.

        Args:
            log_dir: Directory for log files
            log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        """
        self.log_dir = Path(log_dir)
        self.log_level = getattr(logging, log_level.upper(), logging.DEBUG)

        # Ensure log directory exists
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # Configure logging
        self._setup_logging()

    def _setup_logging(self):
        """Configure all logging handlers and formatters"""
        # Create formatter
        formatter = PipeDelimitedFormatter()

        # Get root logger
        root_logger = logging.getLogger()
        root_logger.setLevel(self.log_level)

        # Remove existing handlers
        root_logger.handlers.clear()

        # 1. Console Handler (stdout) - Respects LOG_LEVEL from config
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(self.log_level)
        console_handler.setFormatter(formatter)
        console_handler.addFilter(RequestIdFilter())
        console_handler.addFilter(SensitiveDataFilter())
        root_logger.addHandler(console_handler)

        # 2. Application Log File - Respects configured log level
        app_handler = logging.handlers.RotatingFileHandler(
            filename=self.log_dir / 'application.log',
            maxBytes=100 * 1024 * 1024,  # 100MB
            backupCount=10,
            encoding='utf-8'
        )
        app_handler.setLevel(self.log_level)  # Use configured level, not hardcoded DEBUG
        app_handler.setFormatter(formatter)
        app_handler.addFilter(RequestIdFilter())
        app_handler.addFilter(SensitiveDataFilter())
        root_logger.addHandler(app_handler)

        # 3. Access Log File - for webhook access logging
        access_handler = logging.handlers.RotatingFileHandler(
            filename=self.log_dir / 'access.log',
            maxBytes=50 * 1024 * 1024,  # 50MB
            backupCount=20,
            encoding='utf-8'
        )
        access_handler.setLevel(logging.INFO)
        access_handler.setFormatter(formatter)
        access_handler.addFilter(RequestIdFilter())
        access_handler.addFilter(SensitiveDataFilter())

        # Access logger is separate
        access_logger = logging.getLogger('access')  # pylint: disable=redefined-outer-name
        access_logger.setLevel(logging.INFO)
        access_logger.addHandler(access_handler)
        access_logger.propagate = False  # Don't propagate to root

        # 4. Performance Log File - for performance metrics
        perf_handler = logging.handlers.RotatingFileHandler(
            filename=self.log_dir / 'performance.log',
            maxBytes=50 * 1024 * 1024,  # 50MB
            backupCount=10,
            encoding='utf-8'
        )
        perf_handler.setLevel(logging.INFO)
        perf_handler.setFormatter(formatter)
        perf_handler.addFilter(RequestIdFilter())

        # Performance logger is separate
        perf_logger = logging.getLogger('performance')  # pylint: disable=redefined-outer-name
        perf_logger.setLevel(logging.INFO)
        perf_logger.addHandler(perf_handler)
        perf_logger.propagate = False  # Don't propagate to root

    @staticmethod
    def get_logger(name: str) -> logging.Logger:
        """
        Get logger for a module.

        Args:
            name: Logger name (typically __name__)

        Returns:
            Configured logger instance
        """
        return logging.getLogger(name)

    @staticmethod
    def get_access_logger() -> logging.Logger:
        """Get the access logger for webhook requests"""
        return logging.getLogger('access')

    @staticmethod
    def get_performance_logger() -> logging.Logger:
        """Get the performance logger for metrics"""
        return logging.getLogger('performance')

    @staticmethod
    def set_request_id(request_id: str):
        """
        Set request ID in context for current async task.

        Args:
            request_id: Unique request identifier
        """
        request_id_var.set(request_id)

    @staticmethod
    def clear_request_id():
        """Clear request ID from context"""
        request_id_var.set(None)

    @staticmethod
    def get_request_id() -> Optional[str]:
        """Get current request ID from context"""
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
    global _logging_config  # pylint: disable=global-statement
    # Allow re-initialization to support updating log level from configuration
    # This fixes the issue where DEBUG logging was not working even after setting
    # LOG_LEVEL=DEBUG in .env, because the singleton was locked to the initial INFO level
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
        # Auto-initialize with defaults if not yet configured
        setup_logging()
    return logging.getLogger(name)


def get_access_logger() -> logging.Logger:
    """Get the access logger (convenience function)"""
    if _logging_config is None:
        setup_logging()
    return LoggingConfig.get_access_logger()


def get_performance_logger() -> logging.Logger:
    """Get the performance logger (convenience function)"""
    if _logging_config is None:
        setup_logging()
    return LoggingConfig.get_performance_logger()


def set_request_id(request_id: str):
    """Set request ID for current context (convenience function)"""
    LoggingConfig.set_request_id(request_id)


def clear_request_id():
    """Clear request ID from context (convenience function)"""
    LoggingConfig.clear_request_id()


def get_request_id() -> Optional[str]:
    """Get current request ID (convenience function)"""
    return LoggingConfig.get_request_id()


def mask_token(token: str) -> str:
    """
    Mask a token for logging (convenience function).

    Args:
        token: Token to mask

    Returns:
        Masked token (e.g., "glpat-abcd...xyz9")
    """
    return SensitiveDataFilter._mask_token(token)


# Example usage and testing
if __name__ == "__main__":
    # Test the logging configuration
    setup_logging(log_level='DEBUG')

    logger = get_logger(__name__)  # pylint: disable=redefined-outer-name
    access_logger = get_access_logger()  # pylint: disable=redefined-outer-name
    perf_logger = get_performance_logger()  # pylint: disable=redefined-outer-name

    # Test basic logging
    set_request_id('test123')

    logger.debug("This is a debug message")
    logger.info("This is an info message", extra={'pipeline_id': 12345, 'project_id': 100})
    logger.warning("This is a warning message")
    logger.error("This is an error message", extra={'error_type': 'TestError'})

    # Test token masking
    logger.info("Using token: glpat-1234567890abcdefghijklmnop", extra={'operation': 'api_call'})

    # Test access logging
    access_logger.info("Webhook received", extra={
        'pipeline_id': 12345,
        'project_id': 100,
        'source_ip': '192.168.1.100',
        'event_type': 'Pipeline Hook'
    })

    # Test performance logging
    perf_logger.info("Request completed", extra={'pipeline_id': 12345, 'duration_ms': 1234})

    # Test exception logging
    try:
        raise ValueError("Test exception")
    except ValueError:
        logger.exception("An error occurred")

    clear_request_id()

    print("\nLogging test complete! Check ./logs/ directory for log files:")
    print("  - application.log (all logs including errors)")
    print("  - access.log (access logs)")
    print("  - performance.log (performance metrics)")
