#!/home/build-failure-analyzer/build-failure-analyzer/.venv/bin/python3

"""
Centralized Configuration Loader for Build Failure Analyzer

Loads all environment variables from .env, validates required settings,
and provides typed access to configuration values. Exits with clear
error messages if critical variables are missing.

Adapted from the log-extractor's ConfigLoader pattern.

Usage:
    from config_loader import config  # auto-loads on first import
    print(config.slack_bot_token)
    print(config.redis_url)
"""

import os
import sys
from dataclasses import dataclass, field
from typing import List, Optional
from dotenv import load_dotenv


@dataclass
class Config:
    """All BFA service configuration in one place."""

    # --- Required: Slack ---
    slack_bot_token: str = ""
    slack_channel: str = ""
    slack_signing_secret: str = ""

    # --- Required: LLM ---
    openwebui_base_url: str = ""
    openwebui_api_key: str = ""
    openwebui_model: str = ""
    openwebui_timeout: int = 60
    openwebui_retries: int = 2
    openwebui_backoff: float = 0.5

    # --- Required: JWT ---
    jwt_public_key_path: str = ""
    jwt_audience: str = ""

    # --- Redis ---
    redis_url: str = ""
    redis_host: str = ""
    redis_port: int = 6379
    redis_db: int = 0

    # --- Vector DB (ChromaDB) ---
    chroma_db_path: str = ""
    chroma_collection: str = ""
    ollama_http_url: str = ""
    ollama_cli_path: str = ""
    ollama_embed_model: str = ""
    ollama_timeout: int = 30
    similarity_threshold: float = 0.78
    max_error_lines: int = 80
    max_error_chars: int = 4000
    length_penalty_alpha: float = 0.15
    vector_top_k: int = 5

    # --- Domain RAG ---
    domain_context_path: str = ""
    domain_context_collection: str = ""
    domain_rag_threshold: float = 0.55
    domain_rag_top_k: int = 5
    global_context_path: str = ""
    global_context_max_chars: int = 6000

    # --- Resolver ---
    redis_ttl_ai: int = 86400
    ai_fix_ttl: int = 86400
    llm_generated_confidence: float = 0.6

    # --- Slack Messages ---
    slack_max_block_len: int = 2500
    error_summary_max_chars: int = 300

    # --- Error Notification ---
    alert_slack_emails: List[str] = field(default_factory=list)
    alert_email_to: List[str] = field(default_factory=list)
    smtp_server: str = ""
    smtp_port: int = 25
    smtp_from: str = ""
    smtp_timeout: int = 10
    traceback_max_chars: int = 3500

    # --- Flask (Slack Reviewer) ---
    flask_host: str = ""
    flask_port: int = 5001
    flask_debug: bool = False

    # --- Analyzer Service ---
    bfa_host: str = ""
    bfa_port: int = 8000

    # --- Logging ---
    bfa_log_dir: str = ""
    bfa_log_level: str = ""

    # --- JWT Issuer (scripts) ---
    jwt_private_key_path: str = ""
    jwt_issuer: str = ""
    jwt_iss: str = ""
    jwt_expiry_minutes: int = 60
    jwt_ttl_seconds: int = 60


def _parse_csv_list(value: str) -> List[str]:
    """Parse comma-separated string into a list of stripped non-empty values."""
    return [v.strip() for v in value.split(",") if v.strip()] if value else []


def _get_env(name: str) -> str:
    """Get environment variable value (empty string if not set)."""
    return os.getenv(name, "")


def _get_env_int(name: str, default: int) -> int:
    """Get environment variable as int with fallback default."""
    val = os.getenv(name, "")
    if not val:
        return default
    try:
        return int(val)
    except ValueError:
        return default


def _get_env_float(name: str, default: float) -> float:
    """Get environment variable as float with fallback default."""
    val = os.getenv(name, "")
    if not val:
        return default
    try:
        return float(val)
    except ValueError:
        return default


def _get_env_bool(name: str, default: bool) -> bool:
    """Get environment variable as bool."""
    val = os.getenv(name, "")
    if not val:
        return default
    return val.lower() in ("true", "1", "yes", "on")


def load_config() -> Config:
    """
    Load configuration from .env file.

    Reads all environment variables and populates a Config dataclass.
    Does NOT validate — call validate_config() after loading.
    """
    load_dotenv()

    return Config(
        # Slack
        slack_bot_token=_get_env("SLACK_BOT_TOKEN"),
        slack_channel=_get_env("SLACK_CHANNEL"),
        slack_signing_secret=_get_env("SLACK_SIGNING_SECRET"),

        # LLM
        openwebui_base_url=_get_env("OPENWEBUI_BASE_URL"),
        openwebui_api_key=_get_env("OPENWEBUI_API_KEY"),
        openwebui_model=_get_env("OPENWEBUI_MODEL"),
        openwebui_timeout=_get_env_int("OPENWEBUI_TIMEOUT", 60),
        openwebui_retries=_get_env_int("OPENWEBUI_RETRIES", 2),
        openwebui_backoff=_get_env_float("OPENWEBUI_BACKOFF", 0.5),

        # JWT
        jwt_public_key_path=_get_env("JWT_PUBLIC_KEY_PATH"),
        jwt_audience=_get_env("JWT_AUDIENCE"),

        # Redis
        redis_url=_get_env("REDIS_URL"),
        redis_host=_get_env("REDIS_HOST"),
        redis_port=_get_env_int("REDIS_PORT", 6379),
        redis_db=_get_env_int("REDIS_DB", 0),

        # Vector DB
        chroma_db_path=_get_env("CHROMA_DB_PATH"),
        chroma_collection=_get_env("CHROMA_COLLECTION"),
        ollama_http_url=_get_env("OLLAMA_HTTP_URL"),
        ollama_cli_path=_get_env("OLLAMA_CLI_PATH"),
        ollama_embed_model=_get_env("OLLAMA_EMBED_MODEL"),
        ollama_timeout=_get_env_int("OLLAMA_TIMEOUT", 30),
        similarity_threshold=_get_env_float("SIMILARITY_THRESHOLD", 0.78),
        max_error_lines=_get_env_int("MAX_ERROR_LINES", 80),
        max_error_chars=_get_env_int("MAX_ERROR_CHARS", 4000),
        length_penalty_alpha=_get_env_float("LENGTH_PENALTY_ALPHA", 0.15),
        vector_top_k=_get_env_int("VECTOR_TOP_K", 5),

        # Domain RAG
        domain_context_path=_get_env("DOMAIN_CONTEXT_PATH"),
        domain_context_collection=_get_env("DOMAIN_CONTEXT_COLLECTION"),
        domain_rag_threshold=_get_env_float("DOMAIN_RAG_THRESHOLD", 0.55),
        domain_rag_top_k=_get_env_int("DOMAIN_RAG_TOP_K", 5),
        global_context_path=_get_env("GLOBAL_CONTEXT_PATH"),
        global_context_max_chars=_get_env_int("GLOBAL_CONTEXT_MAX_CHARS", 6000),

        # Resolver
        redis_ttl_ai=_get_env_int("REDIS_TTL_AI", 86400),
        ai_fix_ttl=_get_env_int("AI_FIX_TTL", 86400),
        llm_generated_confidence=_get_env_float("LLM_GENERATED_CONFIDENCE", 0.6),

        # Slack Messages
        slack_max_block_len=_get_env_int("SLACK_MAX_BLOCK_LEN", 2500),
        error_summary_max_chars=_get_env_int("ERROR_SUMMARY_MAX_CHARS", 300),

        # Error Notification
        alert_slack_emails=_parse_csv_list(_get_env("ALERT_SLACK_EMAILS")),
        alert_email_to=_parse_csv_list(_get_env("ALERT_EMAIL_TO")),
        smtp_server=_get_env("SMTP_SERVER"),
        smtp_port=_get_env_int("SMTP_PORT", 25),
        smtp_from=_get_env("SMTP_FROM"),
        smtp_timeout=_get_env_int("SMTP_TIMEOUT", 10),
        traceback_max_chars=_get_env_int("TRACEBACK_MAX_CHARS", 3500),

        # Flask
        flask_host=_get_env("FLASK_HOST"),
        flask_port=_get_env_int("FLASK_PORT", 5001),
        flask_debug=_get_env_bool("FLASK_DEBUG", False),

        # Analyzer
        bfa_host=_get_env("BFA_HOST"),
        bfa_port=_get_env_int("BFA_PORT", 8000),

        # Logging
        bfa_log_dir=_get_env("BFA_LOG_DIR") or "./logs",
        bfa_log_level=_get_env("BFA_LOG_LEVEL") or "INFO",

        # JWT Issuer (scripts)
        jwt_private_key_path=_get_env("JWT_PRIVATE_KEY_PATH"),
        jwt_issuer=_get_env("JWT_ISSUER"),
        jwt_iss=_get_env("JWT_ISS"),
        jwt_expiry_minutes=_get_env_int("JWT_EXPIRY_MINUTES", 60),
        jwt_ttl_seconds=_get_env_int("JWT_TTL_SECONDS", 60),
    )


def validate_config(cfg: Config, mode: str = "analyzer") -> List[str]:
    """
    Validate configuration and return list of errors.

    Args:
        cfg: Config instance to validate
        mode: One of "analyzer", "reviewer", "script"
              Controls which variables are required.

    Returns:
        List of error messages (empty if valid)
    """
    errors = []

    # --- Always required ---
    if not cfg.slack_bot_token:
        errors.append("SLACK_BOT_TOKEN is required")

    if mode == "analyzer":
        # Required for analyzer service
        if not cfg.slack_channel:
            errors.append("SLACK_CHANNEL is required")
        if not cfg.openwebui_api_key:
            errors.append("OPENWEBUI_API_KEY is required")
        if not cfg.openwebui_base_url:
            errors.append("OPENWEBUI_BASE_URL is required")
        if not cfg.jwt_public_key_path:
            errors.append("JWT_PUBLIC_KEY_PATH is required")
        if cfg.jwt_public_key_path and not os.path.isfile(cfg.jwt_public_key_path):
            errors.append(
                f"JWT_PUBLIC_KEY_PATH file not found: {cfg.jwt_public_key_path}"
            )
        if not cfg.redis_url and not cfg.redis_host:
            errors.append(
                "Either REDIS_URL or REDIS_HOST is required"
            )
        if not cfg.chroma_db_path:
            errors.append("CHROMA_DB_PATH is required")
        if not cfg.ollama_http_url:
            errors.append("OLLAMA_HTTP_URL is required")
        if not cfg.ollama_embed_model:
            errors.append("OLLAMA_EMBED_MODEL is required")

        # Validate numeric ranges
        if not 0.0 <= cfg.similarity_threshold <= 1.0:
            errors.append(
                f"SIMILARITY_THRESHOLD must be between 0.0 and 1.0, got {cfg.similarity_threshold}"
            )
        if not 1 <= cfg.bfa_port <= 65535:
            errors.append(
                f"BFA_PORT must be between 1 and 65535, got {cfg.bfa_port}"
            )

        # Validate log level
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if cfg.bfa_log_level.upper() not in valid_levels:
            errors.append(
                f"BFA_LOG_LEVEL must be one of {valid_levels}, got {cfg.bfa_log_level}"
            )

    elif mode == "reviewer":
        # Required for slack reviewer (Flask)
        if not cfg.chroma_db_path:
            errors.append("CHROMA_DB_PATH is required")
        if not cfg.redis_host and not cfg.redis_url:
            errors.append("Either REDIS_URL or REDIS_HOST is required")
        if not 1 <= cfg.flask_port <= 65535:
            errors.append(
                f"FLASK_PORT must be between 1 and 65535, got {cfg.flask_port}"
            )

    elif mode == "script":
        pass  # Scripts have minimal requirements

    return errors


def init_config(mode: str = "analyzer") -> Config:
    """
    Load and validate configuration. Exit on failure.

    This is the main entry point. Call once at startup.

    Args:
        mode: "analyzer", "reviewer", or "script"

    Returns:
        Validated Config instance
    """
    cfg = load_config()
    errors = validate_config(cfg, mode=mode)

    if errors:
        print("=" * 70, file=sys.stderr)
        print("CONFIGURATION ERROR — Cannot start BFA service", file=sys.stderr)
        print("=" * 70, file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        print("=" * 70, file=sys.stderr)
        print(
            "\nPlease check your .env file. See .env.example for reference.",
            file=sys.stderr,
        )
        sys.exit(1)

    return cfg


# Module-level singleton: auto-loads on import
# Use mode="script" for minimal validation (safe for all contexts)
config: Config = load_config()
