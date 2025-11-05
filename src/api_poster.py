"""
API Poster Module

This module handles posting pipeline logs to an external API endpoint.
Instead of (or in addition to) saving logs to files, it POSTs them to
a configured API for centralized storage and processing.

Data Flow:
    Pipeline Info + All Logs → format_payload() → POST to API → Log Response

Module Dependencies:
    - requests: For HTTP POST requests
    - json: For JSON serialization
    - logging: For operation logging
    - time: For duration tracking
    - config_loader: For API configuration
    - error_handler: For retry logic
"""

import json
import logging
import time
from typing import Dict, Any, Optional, Tuple
from datetime import datetime
from pathlib import Path

try:
    import requests
except ImportError:
    requests = None

from .config_loader import Config
from .error_handler import ErrorHandler, RetryExhaustedError

# Configure module logger
logger = logging.getLogger(__name__)


class ApiPoster:
    """
    Posts pipeline logs to external API endpoint.

    This class formats pipeline logs and job data into JSON payloads
    and POSTs them to a configured API endpoint with authentication
    and retry support.

    Attributes:
        config (Config): Application configuration
        api_log_file (Path): Path to API request/response log file
    """

    def __init__(self, config: Config):
        """
        Initialize the API poster.

        Args:
            config (Config): Application configuration

        Raises:
            ImportError: If requests library is not available
        """
        if requests is None:
            raise ImportError(
                "requests library is required for API posting. "
                "Install it with: pip install requests"
            )

        self.config = config

        # Setup dedicated API log file
        log_dir = Path(config.log_output_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        self.api_log_file = log_dir / "api-requests.log"

        logger.info(f"API Poster initialized with endpoint: {config.api_post_url}")
        logger.debug(f"API log file: {self.api_log_file}")

    def format_payload(
        self,
        pipeline_info: Dict[str, Any],
        all_logs: Dict[int, Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Format pipeline and job data into API payload.

        Args:
            pipeline_info (Dict[str, Any]): Pipeline metadata
            all_logs (Dict[int, Dict[str, Any]]): Job logs mapped by job_id

        Returns:
            Dict[str, Any]: Formatted JSON payload

        Payload Structure:
            {
                "pipeline_id": int,
                "project_id": int,
                "project_name": str,
                "status": str,
                "ref": str,
                "sha": str,
                "source": str,
                "pipeline_type": str,
                "created_at": str,
                "finished_at": str,
                "duration": float,
                "user": dict,
                "stages": list,
                "jobs": [
                    {
                        "job_id": int,
                        "job_name": str,
                        "log_content": str,
                        "status": str,
                        "stage": str,
                        "created_at": str,
                        "started_at": str,
                        "finished_at": str,
                        "duration": float,
                        "ref": str
                    },
                    ...
                ]
            }
        """
        # Build jobs array
        jobs = []
        for job_id, job_data in all_logs.items():
            job_details = job_data.get('details', {})
            log_content = job_data.get('log', '')

            jobs.append({
                "job_id": job_id,
                "job_name": job_details.get('name', 'unknown'),
                "log_content": log_content,
                "status": job_details.get('status'),
                "stage": job_details.get('stage'),
                "created_at": job_details.get('created_at'),
                "started_at": job_details.get('started_at'),
                "finished_at": job_details.get('finished_at'),
                "duration": job_details.get('duration'),
                "ref": job_details.get('ref')
            })

        # Build complete payload
        payload = {
            "pipeline_id": pipeline_info['pipeline_id'],
            "project_id": pipeline_info['project_id'],
            "project_name": pipeline_info.get('project_name', 'unknown'),
            "status": pipeline_info['status'],
            "ref": pipeline_info.get('ref'),
            "sha": pipeline_info.get('sha'),
            "source": pipeline_info.get('source'),
            "pipeline_type": pipeline_info.get('pipeline_type'),
            "created_at": pipeline_info.get('created_at'),
            "finished_at": pipeline_info.get('finished_at'),
            "duration": pipeline_info.get('duration'),
            "user": pipeline_info.get('user'),
            "stages": pipeline_info.get('stages', []),
            "jobs": jobs
        }

        return payload

    def _post_to_api(self, payload: Dict[str, Any]) -> Tuple[int, str, float]:
        """
        Internal method to POST payload to API.

        Args:
            payload (Dict[str, Any]): JSON payload to POST

        Returns:
            Tuple[int, str, float]: (status_code, response_body, duration_ms)

        Raises:
            requests.RequestException: On request failures
        """
        headers = {
            "Content-Type": "application/json"
        }

        # Add authentication if configured
        if self.config.api_post_auth_token:
            headers["Authorization"] = f"Bearer {self.config.api_post_auth_token}"

        start_time = time.time()

        try:
            response = requests.post(
                self.config.api_post_url,
                json=payload,
                headers=headers,
                timeout=self.config.api_post_timeout
            )

            duration_ms = int((time.time() - start_time) * 1000)

            # Get response body (truncate if too long)
            response_body = response.text[:1000] if len(response.text) > 1000 else response.text

            # Raise exception for bad status codes
            response.raise_for_status()

            return response.status_code, response_body, duration_ms

        except requests.exceptions.RequestException as e:
            duration_ms = int((time.time() - start_time) * 1000)
            error_msg = str(e)[:1000]
            raise requests.exceptions.RequestException(
                f"API request failed after {duration_ms}ms: {error_msg}"
            )

    def _log_api_request(
        self,
        pipeline_id: int,
        project_id: int,
        status_code: Optional[int],
        response_body: str,
        duration_ms: int,
        error: Optional[str] = None
    ):
        """
        Log API request/response to dedicated log file.

        Args:
            pipeline_id (int): Pipeline ID
            project_id (int): Project ID
            status_code (Optional[int]): HTTP status code (None if error before request)
            response_body (str): Response body (truncated to 1000 chars)
            duration_ms (int): Request duration in milliseconds
            error (Optional[str]): Error message if request failed
        """
        timestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')

        # Truncate response body
        response_truncated = response_body[:1000] if response_body else ""

        # Build log entry
        if error:
            log_entry = (
                f"[{timestamp}] PIPELINE_ID={pipeline_id} PROJECT_ID={project_id} "
                f"URL={self.config.api_post_url} STATUS={status_code or 'ERROR'} "
                f"DURATION={duration_ms}ms ERROR={error} RESPONSE={response_truncated}\n"
            )
        else:
            log_entry = (
                f"[{timestamp}] PIPELINE_ID={pipeline_id} PROJECT_ID={project_id} "
                f"URL={self.config.api_post_url} STATUS={status_code} "
                f"DURATION={duration_ms}ms RESPONSE={response_truncated}\n"
            )

        # Write to file
        try:
            with open(self.api_log_file, 'a', encoding='utf-8') as f:
                f.write(log_entry)
        except IOError as e:
            logger.error(f"Failed to write to API log file: {e}")

    def post_pipeline_logs(
        self,
        pipeline_info: Dict[str, Any],
        all_logs: Dict[int, Dict[str, Any]]
    ) -> bool:
        """
        Post pipeline logs to API endpoint.

        This is the main method to call for posting pipeline logs.
        It handles formatting, posting, retrying, and logging.

        Args:
            pipeline_info (Dict[str, Any]): Pipeline metadata
            all_logs (Dict[int, Dict[str, Any]]): All job logs

        Returns:
            bool: True if successful, False if failed

        Example:
            api_poster = ApiPoster(config)
            success = api_poster.post_pipeline_logs(pipeline_info, all_logs)
            if not success:
                # Handle failure (e.g., fallback to file storage)
                pass
        """
        pipeline_id = pipeline_info['pipeline_id']
        project_id = pipeline_info['project_id']
        project_name = pipeline_info.get('project_name', 'unknown')

        logger.info(
            f"Posting pipeline logs to API for '{project_name}' (pipeline {pipeline_id})",
            extra={
                'pipeline_id': pipeline_id,
                'project_id': project_id,
                'project_name': project_name,
                'job_count': len(all_logs)
            }
        )

        # Format payload
        try:
            payload = self.format_payload(pipeline_info, all_logs)
            payload_size = len(json.dumps(payload))
            logger.debug(f"Formatted API payload (size: {payload_size} bytes)")
        except Exception as e:
            logger.error(
                f"Failed to format API payload for pipeline {pipeline_id}: {e}",
                exc_info=True
            )
            self._log_api_request(
                pipeline_id, project_id, None, "", 0,
                error=f"Payload formatting failed: {str(e)}"
            )
            return False

        # POST to API (with retry if enabled)
        try:
            if self.config.api_post_retry_enabled:
                # Use retry logic
                logger.debug("Using retry logic for API POST")
                error_handler = ErrorHandler(
                    max_retries=self.config.retry_attempts,
                    base_delay=self.config.retry_delay,
                    exponential=True
                )
                status_code, response_body, duration_ms = error_handler.retry_with_backoff(
                    self._post_to_api,
                    payload,
                    exceptions=(requests.exceptions.RequestException,)
                )
            else:
                # No retry, single attempt
                logger.debug("Retry disabled, single API POST attempt")
                status_code, response_body, duration_ms = self._post_to_api(payload)

            # Success
            logger.info(
                f"Successfully posted pipeline {pipeline_id} logs to API",
                extra={
                    'pipeline_id': pipeline_id,
                    'project_id': project_id,
                    'status_code': status_code,
                    'duration_ms': duration_ms,
                    'payload_size': payload_size
                }
            )

            # Log to file
            self._log_api_request(
                pipeline_id, project_id, status_code,
                response_body, duration_ms
            )

            return True

        except RetryExhaustedError as e:
            logger.error(
                f"Failed to post pipeline {pipeline_id} logs after retries: {e}",
                extra={
                    'pipeline_id': pipeline_id,
                    'project_id': project_id,
                    'error_type': 'RetryExhaustedError'
                }
            )
            self._log_api_request(
                pipeline_id, project_id, None, "", 0,
                error=f"Retry exhausted: {str(e)}"
            )
            return False

        except Exception as e:
            logger.error(
                f"Unexpected error posting pipeline {pipeline_id} logs: {e}",
                extra={
                    'pipeline_id': pipeline_id,
                    'project_id': project_id,
                    'error_type': type(e).__name__
                },
                exc_info=True
            )
            self._log_api_request(
                pipeline_id, project_id, None, "", 0,
                error=f"{type(e).__name__}: {str(e)}"
            )
            return False

    def post_jenkins_logs(self, jenkins_payload: Dict[str, Any]) -> bool:
        """
        Post Jenkins build logs to the API endpoint.

        Formats and sends Jenkins build data including stages and parallel blocks.

        Args:
            jenkins_payload (Dict[str, Any]): Jenkins build data with structure:
                {
                    'source': 'jenkins',
                    'job_name': str,
                    'build_number': int,
                    'build_url': str,
                    'status': str,
                    'duration_ms': int,
                    'timestamp': str,
                    'stages': List[Dict]
                }

        Returns:
            bool: True if successfully posted, False otherwise
        """
        if not self.config.api_post_enabled:
            logger.warning("API posting is disabled, cannot post Jenkins logs")
            return False

        if not self.config.api_post_url:
            logger.error("API_POST_URL is not configured")
            return False

        logger.info(
            f"Posting Jenkins build to API: {jenkins_payload['job_name']} #{jenkins_payload['build_number']}"
        )

        try:
            # Jenkins payload is already in the correct format
            payload = jenkins_payload

            # Use retry logic if enabled
            if self.config.api_post_retry_enabled:
                logger.debug("Using retry logic for Jenkins API POST")
                error_handler = ErrorHandler(
                    max_retries=self.config.retry_attempts,
                    base_delay=self.config.retry_delay
                )

                try:
                    status_code, response_body, duration_ms = error_handler.retry_with_backoff(
                        self._post_to_api,
                        payload,
                        exceptions=(requests.exceptions.RequestException,)
                    )
                except RetryExhaustedError as e:
                    logger.error(f"Retry exhausted posting Jenkins logs to API: {e}")
                    self._log_api_request(
                        payload=payload,
                        status_code=None,
                        response_body=str(e),
                        duration_ms=0,
                        error=str(e)
                    )
                    return False
            else:
                # Single attempt without retry
                status_code, response_body, duration_ms = self._post_to_api(payload)

            # Log the request/response
            self._log_api_request(
                payload=payload,
                status_code=status_code,
                response_body=response_body,
                duration_ms=duration_ms
            )

            # Check if successful
            if 200 <= status_code < 300:
                logger.info(
                    f"Successfully posted Jenkins build {jenkins_payload['job_name']} #{jenkins_payload['build_number']} to API",
                    extra={
                        'job_name': jenkins_payload['job_name'],
                        'build_number': jenkins_payload['build_number'],
                        'status_code': status_code,
                        'duration_ms': duration_ms
                    }
                )
                return True
            else:
                logger.warning(
                    f"API returned non-success status code for Jenkins build: {status_code}",
                    extra={
                        'job_name': jenkins_payload['job_name'],
                        'build_number': jenkins_payload['build_number'],
                        'status_code': status_code
                    }
                )
                return False

        except Exception as e:
            logger.error(
                f"Unexpected error posting Jenkins logs to API: {e}",
                extra={
                    'job_name': jenkins_payload.get('job_name', 'unknown'),
                    'build_number': jenkins_payload.get('build_number', 0),
                    'error_type': type(e).__name__,
                    'error': str(e)
                },
                exc_info=True
            )
            self._log_api_request(
                payload=jenkins_payload,
                status_code=None,
                response_body="",
                duration_ms=0,
                error=f"{type(e).__name__}: {str(e)}"
            )
            return False


if __name__ == "__main__":
    # Example usage
    logging.basicConfig(level=logging.INFO)

    # This is just for testing the module structure
    print("API Poster module loaded successfully")
    print("Note: Requires Config object and requests library to function")
