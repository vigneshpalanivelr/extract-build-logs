"""
Configuration Loader Module

This module handles loading and validating configuration from environment variables.
It provides a centralized configuration management system for the GitLab pipeline
log extraction application.

Data Flow:
    Environment Variables → ConfigLoader.load() → Configuration Object → Other Modules

Invoked by: webhook_listener, log_fetcher, jenkins_log_fetcher, api_poster
Invokes: None
"""

import os
from typing import Optional, List
from dataclasses import dataclass


@dataclass
class Config:  # pylint: disable=too-many-instance-attributes
    """
    Configuration data class holding all application settings.

    @dataclass: Python decorator that auto-generates __init__(), __repr__(), and __eq__() methods
                from class attributes, eliminating boilerplate code for data classes.

    Attributes:
        gitlab_url                  -> (str)           -> GitLab instance URL
        gitlab_token                -> (str)           -> GitLab API token
        webhook_port                -> (int)           -> Webhook listener port
        webhook_secret              -> (Optional[str]) -> Webhook validation secret
        log_output_dir              -> (str)           -> Log storage directory
        retry_attempts              -> (int)           -> API retry attempts
        retry_delay                 -> (int)           -> Retry delay (seconds)
        log_level                   -> (str)           -> Logging level
        log_save_pipeline_status    -> (List[str])     -> Pipeline statuses to save
        log_save_projects           -> (List[str])     -> Project IDs whitelist
        log_exclude_projects        -> (List[str])     -> Project IDs blacklist
        log_save_job_status         -> (List[str])     -> Job statuses to save
        log_save_metadata_always    -> (bool)          -> Save metadata always
        api_post_enabled            -> (bool)          -> Enable API posting
        api_post_url                -> (Optional[str]) -> API endpoint URL
        api_post_timeout            -> (int)           -> API timeout (seconds)
        api_post_retry_enabled      -> (bool)          -> Enable API retry
        api_post_save_to_file       -> (bool)          -> Save to file when posting
        jenkins_enabled             -> (bool)          -> Enable Jenkins support
        jenkins_url                 -> (Optional[str]) -> Jenkins instance URL
        jenkins_user                -> (Optional[str]) -> Jenkins username
        jenkins_api_token           -> (Optional[str]) -> Jenkins API token
        jenkins_webhook_secret      -> (Optional[str]) -> Jenkins webhook secret
        bfa_host                    -> (Optional[str]) -> BFA server hostname
        bfa_secret_key              -> (Optional[str]) -> BFA JWT secret key
        error_context_lines_before  -> (int)           -> Error context lines before
        error_context_lines_after   -> (int)           -> Error context lines after
    """
    gitlab_url: str
    gitlab_token: str
    webhook_port: int
    webhook_secret: Optional[str]
    log_output_dir: str
    retry_attempts: int
    retry_delay: int
    log_level: str
    log_save_pipeline_status: List[str]
    log_save_projects: List[str]
    log_exclude_projects: List[str]
    log_save_job_status: List[str]
    log_save_metadata_always: bool
    api_post_enabled: bool
    api_post_url: Optional[str]  # Auto-constructed from BFA_HOST
    api_post_timeout: int
    api_post_retry_enabled: bool
    api_post_save_to_file: bool
    jenkins_enabled: bool
    jenkins_url: Optional[str]
    jenkins_user: Optional[str]
    jenkins_api_token: Optional[str]
    jenkins_webhook_secret: Optional[str]
    bfa_host: Optional[str]
    bfa_secret_key: Optional[str]
    error_context_lines_before: int
    error_context_lines_after: int


class ConfigLoader:
    """
    Configuration loader and validator.
    This class is responsible for loading configuration from environment variables,
    validating required settings, and providing default values where appropriate.

    Usage:
        config = ConfigLoader.load()
        print(config.gitlab_url)
    """

    @staticmethod
    def load() -> Config:  # pylint: disable=too-many-branches
        """
        Load configuration from environment variables.

        Returns:
            Config: Configuration object with all settings

        Raises:
            ValueError: If required environment variables are missing

        Environment Variables:
            Required:
                - GITLAB_URL: GitLab instance URL
                - GITLAB_TOKEN: GitLab API access token

            Optional:
                - WEBHOOK_PORT: Port for webhook server (default: 8000)
                - WEBHOOK_SECRET: Secret for webhook validation
                - LOG_OUTPUT_DIR: Directory for log storage (default: ./logs)
                - RETRY_ATTEMPTS: Number of retry attempts (default: 3)
                - RETRY_DELAY: Delay between retries in seconds (default: 2)
                - LOG_LEVEL: Logging level (default: INFO)
        """
        # Required settings
        gitlab_url = os.getenv('GITLAB_URL')
        gitlab_token = os.getenv('GITLAB_TOKEN')

        if not gitlab_url:
            raise ValueError("GITLAB_URL environment variable is required")
        if not gitlab_token:
            raise ValueError("GITLAB_TOKEN environment variable is required")

        # Remove trailing slash from GitLab URL if present
        gitlab_url = gitlab_url.rstrip('/')

        # Optional settings with defaults
        webhook_port = int(os.getenv('WEBHOOK_PORT', '8000'))
        webhook_secret = os.getenv('WEBHOOK_SECRET')
        log_output_dir = os.getenv('LOG_OUTPUT_DIR', './logs/pipeline-logs')
        retry_attempts = int(os.getenv('RETRY_ATTEMPTS', '3'))
        retry_delay = int(os.getenv('RETRY_DELAY', '2'))
        log_level = os.getenv('LOG_LEVEL', 'INFO').upper()

        # Log filtering settings
        log_save_pipeline_status_str = os.getenv('LOG_SAVE_PIPELINE_STATUS', 'all')
        log_save_pipeline_status = [s.strip().lower() for s in log_save_pipeline_status_str.split(',') if s.strip()]

        log_save_projects_str = os.getenv('LOG_SAVE_PROJECTS', '')
        log_save_projects = [s.strip() for s in log_save_projects_str.split(',') if s.strip()]

        log_exclude_projects_str = os.getenv('LOG_EXCLUDE_PROJECTS', '')
        log_exclude_projects = [s.strip() for s in log_exclude_projects_str.split(',') if s.strip()]

        log_save_job_status_str = os.getenv('LOG_SAVE_JOB_STATUS', 'all')
        log_save_job_status = [s.strip().lower() for s in log_save_job_status_str.split(',') if s.strip()]

        log_save_metadata_always_str = os.getenv('LOG_SAVE_METADATA_ALWAYS', 'true').lower()
        log_save_metadata_always = log_save_metadata_always_str in ['true', '1', 'yes', 'on']

        # API POST configuration
        api_post_enabled_str = os.getenv('API_POST_ENABLED', 'false').lower()
        api_post_enabled = api_post_enabled_str in ['true', '1', 'yes', 'on']

        api_post_timeout = int(os.getenv('API_POST_TIMEOUT', '30'))

        api_post_retry_enabled_str = os.getenv('API_POST_RETRY_ENABLED', 'true').lower()
        api_post_retry_enabled = api_post_retry_enabled_str in ['true', '1', 'yes', 'on']

        api_post_save_to_file_str = os.getenv('API_POST_SAVE_TO_FILE', 'false').lower()
        api_post_save_to_file = api_post_save_to_file_str in ['true', '1', 'yes', 'on']

        # Jenkins configuration
        jenkins_enabled_str = os.getenv('JENKINS_ENABLED', 'false').lower()
        jenkins_enabled = jenkins_enabled_str in ['true', '1', 'yes', 'on']

        jenkins_url = os.getenv('JENKINS_URL')
        if jenkins_url:
            jenkins_url = jenkins_url.rstrip('/')

        jenkins_user = os.getenv('JENKINS_USER')
        jenkins_api_token = os.getenv('JENKINS_API_TOKEN')
        jenkins_webhook_secret = os.getenv('JENKINS_WEBHOOK_SECRET')

        # BFA JWT configuration
        # BFA_HOST: Hostname/IP of BFA server (used to construct http://BFA_HOST:8000/api/analyze)
        # BFA_SECRET_KEY: Required for JWT token generation (no fallback to GITLAB_TOKEN)
        bfa_host = os.getenv('BFA_HOST')
        bfa_secret_key = os.getenv('BFA_SECRET_KEY')

        # Auto-construct API POST URL from BFA_HOST
        api_post_url = f"http://{bfa_host}:8000/api/analyze" if bfa_host else None

        # Error context extraction settings
        error_context_lines_before = int(os.getenv('ERROR_CONTEXT_LINES_BEFORE', '50'))
        error_context_lines_after = int(os.getenv('ERROR_CONTEXT_LINES_AFTER', '10'))

        # Validate port number
        if not 1 <= webhook_port <= 65535:
            raise ValueError(f"Invalid WEBHOOK_PORT: {webhook_port}. Must be between 1 and 65535")

        # Validate log level
        valid_levels = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
        if log_level not in valid_levels:
            raise ValueError(f"Invalid LOG_LEVEL: {log_level}. Must be one of {valid_levels}")

        # Validate API POST configuration
        if api_post_enabled:
            if not bfa_host:
                raise ValueError("BFA_HOST is required when API_POST_ENABLED is true")
            if api_post_timeout < 1 or api_post_timeout > 300:
                raise ValueError(f"Invalid API_POST_TIMEOUT: {api_post_timeout}. Must be between 1 and 300 seconds")

        # Validate Jenkins configuration
        # Note: When JENKINS_ENABLED=true, credentials can come from either:
        #   1. .env file (jenkins_url, jenkins_user, jenkins_api_token) - for single instance
        #   2. jenkins_instances.json file - for multiple instances
        # If jenkins_instances.json exists, .env credentials are optional (checked at runtime)
        if jenkins_enabled:
            # Check if jenkins_instances.json exists
            jenkins_instances_file = "jenkins_instances.json"
            has_instances_file = os.path.isfile(jenkins_instances_file)

            # If no jenkins_instances.json, require .env credentials
            if not has_instances_file:
                if not jenkins_url:
                    raise ValueError(
                        "JENKINS_URL is required when JENKINS_ENABLED is true. "
                        "Either set JENKINS_URL in .env or create jenkins_instances.json for multi-instance support."
                    )
                if not jenkins_user:
                    raise ValueError(
                        "JENKINS_USER is required when JENKINS_ENABLED is true. "
                        "Either set JENKINS_USER in .env or create jenkins_instances.json for multi-instance support."
                    )
                if not jenkins_api_token:
                    raise ValueError(
                        "JENKINS_API_TOKEN is required when JENKINS_ENABLED is true. "
                        "Either set JENKINS_API_TOKEN in .env or create jenkins_instances.json for multi-instance support."
                    )

            # Validate jenkins_url format if provided (optional with jenkins_instances.json)
            if jenkins_url and not jenkins_url.startswith(('http://', 'https://')):
                raise ValueError(f"Invalid JENKINS_URL: {jenkins_url}. Must start with http:// or https://")

        return Config(
            gitlab_url=gitlab_url,
            gitlab_token=gitlab_token,
            webhook_port=webhook_port,
            webhook_secret=webhook_secret,
            log_output_dir=log_output_dir,
            retry_attempts=retry_attempts,
            retry_delay=retry_delay,
            log_level=log_level,
            log_save_pipeline_status=log_save_pipeline_status,
            log_save_projects=log_save_projects,
            log_exclude_projects=log_exclude_projects,
            log_save_job_status=log_save_job_status,
            log_save_metadata_always=log_save_metadata_always,
            api_post_enabled=api_post_enabled,
            api_post_url=api_post_url,
            api_post_timeout=api_post_timeout,
            api_post_retry_enabled=api_post_retry_enabled,
            api_post_save_to_file=api_post_save_to_file,
            jenkins_enabled=jenkins_enabled,
            jenkins_url=jenkins_url,
            jenkins_user=jenkins_user,
            jenkins_api_token=jenkins_api_token,
            jenkins_webhook_secret=jenkins_webhook_secret,
            bfa_host=bfa_host,
            bfa_secret_key=bfa_secret_key,
            error_context_lines_before=error_context_lines_before,
            error_context_lines_after=error_context_lines_after
        )

    @staticmethod
    def validate(config: Config) -> bool:  # pylint: disable=redefined-outer-name
        """
        Validate configuration settings.

        Args:
            config (Config): Configuration object to validate

        Returns:
            bool: True if configuration is valid

        Raises:
            ValueError: If configuration is invalid
        """
        if not config.gitlab_url.startswith(('http://', 'https://')):
            raise ValueError(f"Invalid GITLAB_URL: {config.gitlab_url}. Must start with http:// or https://")

        if len(config.gitlab_token) < 10:
            raise ValueError("GITLAB_TOKEN appears to be invalid (too short)")

        return True


if __name__ == "__main__":
    # Example usage and testing
    try:
        config = ConfigLoader.load()
        print("Configuration loaded successfully!")
        print(f"GitLab URL: {config.gitlab_url}")
        print(f"Webhook Port: {config.webhook_port}")
        print(f"Log Output Directory: {config.log_output_dir}")
    except ValueError as e:
        print(f"Configuration error: {e}")
