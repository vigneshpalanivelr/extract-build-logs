"""
Jenkins Log Fetcher Module

This module handles fetching logs and build information from Jenkins via REST API.
It retrieves console logs, stage information (Blue Ocean API), and build metadata.

Data Flow:
    Jenkins Build → REST API → fetch_console_log() / fetch_stages() → Log Data

Module Dependencies:
    - requests: For HTTP requests to Jenkins API
    - logging: For operation logging
    - config_loader: For Jenkins configuration
    - error_handler: For retry logic
"""

import logging
import requests
from typing import Dict, Any, Optional, List
from requests.auth import HTTPBasicAuth

from .config_loader import Config
from .error_handler import ErrorHandler, RetryExhaustedError

# Configure module logger
logger = logging.getLogger(__name__)


class JenkinsLogFetcher:
    """
    Fetches logs and build information from Jenkins via REST API.

    This class handles all interactions with the Jenkins REST API including:
    - Fetching console logs
    - Fetching Blue Ocean stage information
    - Fetching build metadata

    Attributes:
        config (Config): Application configuration
        auth (HTTPBasicAuth): Jenkins API authentication
        error_handler (ErrorHandler): Retry handler for failed requests
    """

    def __init__(self, config: Config):
        """
        Initialize the Jenkins log fetcher.

        Args:
            config (Config): Application configuration with Jenkins settings

        Raises:
            ValueError: If Jenkins configuration is invalid
        """
        if not config.jenkins_enabled:
            raise ValueError("Jenkins is not enabled in configuration")

        self.config = config
        self.jenkins_url = config.jenkins_url
        self.auth = HTTPBasicAuth(config.jenkins_user, config.jenkins_api_token)

        # Initialize error handler for retries
        self.error_handler = ErrorHandler(
            max_retries=config.retry_attempts,
            base_delay=config.retry_delay
        )

        logger.info(f"Jenkins Log Fetcher initialized for: {self.jenkins_url}")

    def fetch_build_info(self, job_name: str, build_number: int) -> Dict[str, Any]:
        """
        Fetch build metadata from Jenkins.

        Args:
            job_name (str): Name of the Jenkins job
            build_number (int): Build number

        Returns:
            Dict[str, Any]: Build information including status, duration, timestamp, etc.

        Raises:
            requests.exceptions.RequestException: If API request fails
        """
        url = f"{self.jenkins_url}/job/{job_name}/{build_number}/api/json"
        logger.info(f"Fetching build info: {url}")

        try:
            response = self.error_handler.retry_with_backoff(
                self._make_request,
                'GET',
                url,
                exceptions=(requests.exceptions.RequestException,)
            )

            build_info = response.json()
            logger.debug(f"Build info fetched: {build_info.get('result', 'UNKNOWN')}")
            return build_info

        except RetryExhaustedError as e:
            logger.error(f"Failed to fetch build info after retries: {e}")
            raise

    def fetch_console_log(self, job_name: str, build_number: int) -> str:
        """
        Fetch console log from Jenkins build.

        Args:
            job_name (str): Name of the Jenkins job
            build_number (int): Build number

        Returns:
            str: Complete console log output

        Raises:
            requests.exceptions.RequestException: If API request fails
        """
        url = f"{self.jenkins_url}/job/{job_name}/{build_number}/consoleText"
        logger.info(f"Fetching console log: {url}")

        try:
            response = self.error_handler.retry_with_backoff(
                self._make_request,
                'GET',
                url,
                exceptions=(requests.exceptions.RequestException,)
            )

            console_log = response.text
            log_size = len(console_log)
            logger.info(f"Console log fetched: {log_size} bytes")
            return console_log

        except RetryExhaustedError as e:
            logger.error(f"Failed to fetch console log after retries: {e}")
            raise

    def fetch_stages(self, job_name: str, build_number: int) -> Optional[List[Dict[str, Any]]]:
        """
        Fetch stage information from Blue Ocean API.

        This endpoint provides structured stage data for pipeline builds,
        including stage names, statuses, durations, and parallel execution info.

        Args:
            job_name (str): Name of the Jenkins job
            build_number (int): Build number

        Returns:
            Optional[List[Dict[str, Any]]]: List of stage information, or None if not available

        Note:
            Returns None if Blue Ocean API is not available or job is not a pipeline.
            This is not an error - it just means we'll parse console logs instead.
        """
        url = f"{self.jenkins_url}/job/{job_name}/{build_number}/wfapi/describe"
        logger.info(f"Fetching Blue Ocean stage info: {url}")

        try:
            response = self._make_request('GET', url)

            if response.status_code == 404:
                logger.warning(f"Blue Ocean API not available for {job_name}/{build_number} (404)")
                return None

            stage_info = response.json()
            stages = stage_info.get('stages', [])
            logger.info(f"Fetched {len(stages)} stages from Blue Ocean API")
            return stages

        except requests.exceptions.RequestException as e:
            logger.warning(f"Failed to fetch Blue Ocean stages (non-critical): {e}")
            return None

    def fetch_stage_log(self, job_name: str, build_number: int, stage_id: str) -> Optional[str]:
        """
        Fetch log for a specific stage (if available).

        Args:
            job_name (str): Name of the Jenkins job
            build_number (int): Build number
            stage_id (str): Stage ID from Blue Ocean API

        Returns:
            Optional[str]: Stage log content, or None if not available
        """
        url = f"{self.jenkins_url}/job/{job_name}/{build_number}/execution/node/{stage_id}/wfapi/log"
        logger.debug(f"Fetching stage log: {url}")

        try:
            response = self._make_request('GET', url)

            if response.status_code == 404:
                logger.debug(f"Stage log not available for stage {stage_id}")
                return None

            return response.text

        except requests.exceptions.RequestException as e:
            logger.warning(f"Failed to fetch stage log (non-critical): {e}")
            return None

    def _make_request(self, method: str, url: str, **kwargs) -> requests.Response:
        """
        Make an authenticated HTTP request to Jenkins API.

        Args:
            method (str): HTTP method (GET, POST, etc.)
            url (str): Full URL to request
            **kwargs: Additional arguments to pass to requests

        Returns:
            requests.Response: HTTP response

        Raises:
            requests.exceptions.RequestException: If request fails
        """
        timeout = kwargs.pop('timeout', 30)

        response = requests.request(
            method=method,
            url=url,
            auth=self.auth,
            timeout=timeout,
            **kwargs
        )

        response.raise_for_status()
        return response
