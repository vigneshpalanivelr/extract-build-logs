"""
Jenkins Log Fetcher Module

This module handles fetching logs and build information from Jenkins via REST API.
It retrieves console logs, stage information (Blue Ocean API), and build metadata.

Data Flow:
    Jenkins Build → REST API → fetch_console_log() / fetch_stages() → Log Data

Invoked by: webhook_listener
Invokes: config_loader, error_handler
"""

import json
import logging
import os
from typing import Dict, Any, Optional, List

import requests
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
        jenkins_url (str): Jenkins instance URL
        auth (HTTPBasicAuth): Jenkins API authentication
        error_handler (ErrorHandler): Retry handler for failed requests
    """

    def __init__(self, config: Optional[Config] = None, jenkins_url: Optional[str] = None,
                 jenkins_user: Optional[str] = None, jenkins_api_token: Optional[str] = None,
                 retry_attempts: int = 3, retry_delay: int = 2):
        """
        Initialize the Jenkins log fetcher.

        Can be initialized either from a Config object or with explicit credentials.

        Args:
            config (Optional[Config]): Application configuration with Jenkins settings
            jenkins_url (Optional[str]): Jenkins instance URL (alternative to config)
            jenkins_user (Optional[str]): Jenkins username (alternative to config)
            jenkins_api_token (Optional[str]): Jenkins API token (alternative to config)
            retry_attempts (int): Number of retry attempts (default: 3)
            retry_delay (int): Base delay for retries in seconds (default: 2)

        Raises:
            ValueError: If neither config nor explicit credentials are provided
        """
        # Store config for log limits
        self.config = config

        if config:
            # Initialize from config object
            if not config.jenkins_enabled:
                raise ValueError("Jenkins is not enabled in configuration")

            self.jenkins_url = config.jenkins_url
            self.auth = HTTPBasicAuth(config.jenkins_user, config.jenkins_api_token)
            retry_attempts = config.retry_attempts
            retry_delay = config.retry_delay
        elif jenkins_url and jenkins_user and jenkins_api_token:
            # Initialize from explicit credentials
            self.jenkins_url = jenkins_url.rstrip('/')
            self.auth = HTTPBasicAuth(jenkins_user, jenkins_api_token)
            self.config = None  # No config available
        else:
            raise ValueError("Must provide either config or explicit Jenkins credentials")

        # Initialize error handler for retries
        self.error_handler = ErrorHandler(
            max_retries=retry_attempts,
            base_delay=retry_delay
        )

        logger.info("Jenkins Log Fetcher initialized for: %s", self.jenkins_url)

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
        logger.debug("Fetching build info for job %s #%s", job_name, build_number)

        try:
            response = self.error_handler.retry_with_backoff(
                self._make_request,
                'GET',
                url,
                exceptions=(requests.exceptions.RequestException,)
            )

            build_info = response.json()
            logger.debug(
                "Successfully fetched build info for job %s #%s: %s",
                job_name, build_number, build_info.get('result', 'UNKNOWN')
            )
            return build_info

        except RetryExhaustedError as error:
            logger.error(
                "Failed to fetch build info for job %s #%s after retries: %s",
                job_name, build_number, error
            )
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
        logger.info("Fetching console log for job %s #%s", job_name, build_number)

        try:
            response = self.error_handler.retry_with_backoff(
                self._make_request,
                'GET',
                url,
                exceptions=(requests.exceptions.RequestException,)
            )

            console_log = response.text
            log_size = len(console_log)
            logger.info(
                "Successfully fetched console log for job %s #%s (%s bytes)",
                job_name, build_number, log_size
            )
            return console_log

        except RetryExhaustedError as error:
            logger.error(
                "Failed to fetch console log for job %s #%s after retries: %s",
                job_name, build_number, error
            )
            raise

    def fetch_console_log_tail(self, job_name: str, build_number: int, tail_lines: Optional[int] = None) -> str:
        """
        Fetch only the last N lines of console log (memory efficient).
        Errors usually appear at the end of failed builds.

        Args:
            job_name (str): Name of the Jenkins job
            build_number (int): Build number
            tail_lines (Optional[int]): Number of lines from tail (uses config.tail_log_lines if None)

        Returns:
            str: Tail portion of console log

        Raises:
            requests.exceptions.RequestException: If API request fails
        """
        if tail_lines is None:
            tail_lines = self.config.tail_log_lines if self.config else int(os.getenv('TAIL_LOG_LINES', '5000'))

        url = f"{self.jenkins_url}/job/{job_name}/{build_number}/consoleText"
        logger.info("Fetching console log tail (last %d lines) for job %s #%s", tail_lines, job_name, build_number)

        try:
            # First, get total log size
            head_response = requests.head(url, auth=self.auth, timeout=10)
            total_size = int(head_response.headers.get('Content-Length', 0))

            if total_size == 0:
                logger.warning("Console log is empty for job %s #%s", job_name, build_number)
                return ""

            # Calculate start position (approximate bytes per line = 150)
            estimated_bytes = tail_lines * 150
            start_pos = max(0, total_size - estimated_bytes)

            logger.debug("Total log size: %d bytes, fetching from byte %d", total_size, start_pos)

            # Fetch from start position
            headers = {'Range': f'bytes={start_pos}-'} if start_pos > 0 else {}
            response = requests.get(url, auth=self.auth, headers=headers, timeout=60)
            response.raise_for_status()

            tail_log = response.text
            actual_lines = len(tail_log.split('\n'))

            logger.info(
                "Successfully fetched console log tail for job %s #%s (%d bytes, ~%d lines)",
                job_name, build_number, len(tail_log), actual_lines
            )

            return tail_log

        except requests.exceptions.RequestException as error:
            logger.error(
                "Failed to fetch console log tail for job %s #%s: %s",
                job_name, build_number, error
            )
            raise

    def fetch_console_log_streaming(self, job_name: str, build_number: int,
                                    max_lines: Optional[int] = None) -> Dict[str, Any]:
        """
        Stream console log and extract only error sections (memory efficient).
        Prevents loading massive logs entirely into memory.

        Args:
            job_name (str): Name of the Jenkins job
            build_number (int): Build number
            max_lines (Optional[int]): Maximum lines to process (uses config.max_log_lines if None)

        Returns:
            Dict with 'log_content', 'truncated' (bool), and 'total_lines' (int)

        Raises:
            requests.exceptions.RequestException: If API request fails
        """
        if max_lines is None:
            max_lines = self.config.max_log_lines if self.config else int(os.getenv('MAX_LOG_LINES', '100000'))

        url = f"{self.jenkins_url}/job/{job_name}/{build_number}/consoleText"
        logger.info("Streaming console log for job %s #%s (max %d lines)", job_name, build_number, max_lines)

        try:
            # Stream the response
            response = requests.get(url, auth=self.auth, stream=True, timeout=120)
            response.raise_for_status()

            collected_lines = []
            line_count = 0
            truncated = False

            # Process line by line
            for line in response.iter_lines(decode_unicode=True):
                line_count += 1
                collected_lines.append(line)

                # Safety limit
                if line_count >= max_lines:
                    logger.warning(
                        "Hit max line limit %d for job %s #%s, truncating",
                        max_lines, job_name, build_number
                    )
                    truncated = True
                    break

            log_content = '\n'.join(collected_lines)

            logger.info(
                "Streamed console log for job %s #%s: %d lines, %d bytes (truncated=%s)",
                job_name, build_number, line_count, len(log_content), truncated
            )

            return {
                'log_content': log_content,
                'truncated': truncated,
                'total_lines': line_count
            }

        except requests.exceptions.RequestException as error:
            logger.error(
                "Failed to stream console log for job %s #%s: %s",
                job_name, build_number, error
            )
            raise

    def fetch_console_log_hybrid(self, job_name: str, build_number: int) -> Dict[str, Any]:
        """
        Hybrid approach: Try tail first (fast), fall back to streaming if needed.
        This is the RECOMMENDED method for memory-efficient log fetching.

        Strategy:
        1. Fetch tail (last 5000 lines) - fast, low memory
        2. Check if errors exist in tail
        3. If yes, return tail (works for 99% of failed builds)
        4. If no, stream full log with safety limits

        Args:
            job_name (str): Name of the Jenkins job
            build_number (int): Build number

        Returns:
            Dict with 'log_content', 'method' ('tail' or 'streaming'), 'truncated', 'total_lines'
        """
        from .log_error_extractor import LogErrorExtractor  # pylint: disable=import-outside-toplevel

        logger.info("Fetching console log (hybrid) for job %s #%s", job_name, build_number)

        # Try tail first
        try:
            tail_log = self.fetch_console_log_tail(job_name, build_number)
            tail_lines = len(tail_log.split('\n')) if tail_log else 0

            # Quick check: does tail have error patterns?
            extractor = LogErrorExtractor(lines_before=10, lines_after=5)
            if extractor._find_error_lines(tail_log.split('\n')):
                logger.info("Found errors in tail for job %s #%s, using tail only", job_name, build_number)
                return {
                    'log_content': tail_log,
                    'method': 'tail',
                    'truncated': False,
                    'total_lines': tail_lines
                }

            logger.info("No errors in tail for job %s #%s, streaming full log", job_name, build_number)

        except Exception as error:  # pylint: disable=broad-exception-caught
            logger.warning(
                "Tail fetch failed for job %s #%s: %s, falling back to streaming",
                job_name, build_number, error
            )

        # Fall back to streaming full log
        result = self.fetch_console_log_streaming(job_name, build_number)
        result['method'] = 'streaming'
        return result

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
        logger.debug("Fetching Blue Ocean stage info for job %s #%s", job_name, build_number)

        try:
            response = self._make_request('GET', url)

            if response.status_code == 404:
                logger.debug("Blue Ocean API not available for job %s #%s (404)", job_name, build_number)
                return None

            stage_info = response.json()
            stages = stage_info.get('stages', [])
            logger.info(
                "Successfully fetched %s stages from Blue Ocean API for job %s #%s",
                len(stages), job_name, build_number
            )
            return stages

        except requests.exceptions.RequestException as error:
            logger.debug(
                "Failed to fetch Blue Ocean stages for job %s #%s (non-critical): %s",
                job_name, build_number, error
            )
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
        logger.debug("Fetching stage log: %s", url)

        try:
            response = self._make_request('GET', url)

            if response.status_code == 404:
                logger.debug("Stage log not available for stage %s", stage_id)
                return None

            # Blue Ocean wfapi/log can return either:
            # 1. JSON metadata: {"nodeId":"X","nodeStatus":"Y","length":0,"hasMore":false}
            # 2. Plain text log content
            try:
                log_data = response.json()
                # If it's JSON with length=0, no log content available
                if isinstance(log_data, dict) and log_data.get('length', 0) == 0:
                    logger.debug("Stage log empty (length=0) for stage %s", stage_id)
                    return None
                # If JSON has text field, return that
                if isinstance(log_data, dict) and 'text' in log_data:
                    return log_data['text']
                # Otherwise, JSON response without useful log data
                logger.debug("Stage log API returned metadata without log text for stage %s", stage_id)
                return None
            except (ValueError, json.JSONDecodeError):
                # Not JSON, treat as plain text log
                return response.text

        except requests.exceptions.RequestException as error:
            logger.warning("Failed to fetch stage log (non-critical): %s", error)
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
