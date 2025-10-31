"""
Configuration Loader Module

This module handles loading and validating configuration from environment variables.
It provides a centralized configuration management system for the GitLab pipeline
log extraction application.

Data Flow:
    Environment Variables → ConfigLoader.load() → Configuration Object → Other Modules

Module Dependencies:
    - os: For reading environment variables
    - typing: For type hints
"""

import os
from typing import Optional, List
from dataclasses import dataclass


@dataclass
class Config:
    """
    Configuration data class holding all application settings.

    Attributes:
        gitlab_url (str): GitLab instance URL (e.g., https://gitlab.com)
        gitlab_token (str): Private token for GitLab API authentication
        webhook_port (int): Port for webhook listener server
        webhook_secret (Optional[str]): Secret token for webhook validation
        log_output_dir (str): Directory where logs will be stored
        retry_attempts (int): Number of retry attempts for failed API calls
        retry_delay (int): Delay in seconds between retry attempts
        log_level (str): Logging level (DEBUG, INFO, WARNING, ERROR)
        log_save_pipeline_status (List[str]): Which pipeline statuses to save logs for
        log_save_projects (List[str]): Whitelist of project IDs to save logs for (empty = all)
        log_exclude_projects (List[str]): Blacklist of project IDs to exclude from logging
        log_save_job_status (List[str]): Which job statuses to save logs for
        log_save_metadata_always (bool): Whether to save metadata even if logs are filtered out
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
    def load() -> Config:
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
        log_output_dir = os.getenv('LOG_OUTPUT_DIR', './logs')
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

        # Validate port number
        if not 1 <= webhook_port <= 65535:
            raise ValueError(f"Invalid WEBHOOK_PORT: {webhook_port}. Must be between 1 and 65535")

        # Validate log level
        valid_levels = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
        if log_level not in valid_levels:
            raise ValueError(f"Invalid LOG_LEVEL: {log_level}. Must be one of {valid_levels}")

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
            log_save_metadata_always=log_save_metadata_always
        )

    @staticmethod
    def validate(config: Config) -> bool:
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
