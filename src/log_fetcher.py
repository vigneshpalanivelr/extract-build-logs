"""
Log Fetcher Module

This module handles fetching job logs from GitLab API. It retrieves logs for individual jobs,
handles pagination, and manages API authentication.

Data Flow:
    Pipeline Event → extract_job_ids() → fetch_job_log() → GitLab API → Raw Log Content

Module Dependencies:
    - requests: For HTTP API calls
    - logging: For operation logging
    - config_loader: For GitLab credentials
    - error_handler: For retry logic
"""

import logging
from typing import Dict, List, Any

import requests

from .config_loader import Config
from .error_handler import retry_on_failure

# Configure module logger
logger = logging.getLogger(__name__)


class GitLabAPIError(Exception):
    """Raised when GitLab API returns an error."""


class LogFetcher:
    """
    Fetches job logs from GitLab API.

    This class handles all interactions with the GitLab API for retrieving job logs,
    including authentication, error handling, and pagination.

    Attributes:
        config (Config): Application configuration
        session (requests.Session): Reusable HTTP session for API calls
    """

    def __init__(self, config: Config):
        """
        Initialize the log fetcher.

        Args:
            config (Config): Application configuration containing GitLab URL and token

        Sets up:
            - HTTP session with authentication headers
            - Base API URL
        """
        self.config = config
        self.session = requests.Session()
        self.session.headers.update({
            'PRIVATE-TOKEN': config.gitlab_token,
            'Content-Type': 'application/json'
        })
        self.base_url = f"{config.gitlab_url}/api/v4"

    @retry_on_failure(max_retries=3, base_delay=2.0, exceptions=(requests.RequestException,))
    def fetch_job_log(self, project_id: int, job_id: int) -> str:
        """
        Fetch log content for a specific job.

        This method retrieves the complete log output for a given job from GitLab.
        It automatically retries on network failures.

        Args:
            project_id (int): GitLab project ID
            job_id (int): GitLab job ID

        Returns:
            str: Raw log content from the job

        Raises:
            GitLabAPIError: If the API returns an error
            RetryExhaustedError: If all retry attempts fail

        API Endpoint:
            GET /projects/:id/jobs/:job_id/trace

        Example:
            fetcher = LogFetcher(config)
            log_content = fetcher.fetch_job_log(123, 456)
        """
        url = f"{self.base_url}/projects/{project_id}/jobs/{job_id}/trace"

        logger.info("Fetching log for job %s in project %s", job_id, project_id)

        try:
            response = self.session.get(url, timeout=30)

            if response.status_code == 404:
                logger.warning("Job %s not found or log not available", job_id)
                return f"[Log not available for job {job_id}]"

            if response.status_code == 401:
                raise GitLabAPIError("Authentication failed. Check GITLAB_TOKEN")

            if response.status_code == 403:
                raise GitLabAPIError("Access forbidden. Check token permissions")

            response.raise_for_status()

            log_content = response.text
            logger.info("Successfully fetched log for job %s (%s bytes)", job_id, len(log_content))
            return log_content

        except requests.RequestException:
            logger.error("Failed to fetch log for job %s", job_id)
            raise

    @retry_on_failure(max_retries=3, base_delay=2.0, exceptions=(requests.RequestException,))
    def fetch_job_details(self, project_id: int, job_id: int) -> Dict[str, Any]:
        """
        Fetch detailed information about a job.

        Retrieves metadata about a job including its name, status, stage, and other details.

        Args:
            project_id (int): GitLab project ID
            job_id (int): GitLab job ID

        Returns:
            Dict[str, Any]: Job details including name, status, stage, duration, etc.

        Raises:
            GitLabAPIError: If the API returns an error
            RetryExhaustedError: If all retry attempts fail

        API Endpoint:
            GET /projects/:id/jobs/:job_id

        Example Response:
            {
                "id": 123,
                "name": "build",
                "stage": "build",
                "status": "success",
                "created_at": "2023-01-01T00:00:00Z",
                "started_at": "2023-01-01T00:01:00Z",
                "finished_at": "2023-01-01T00:05:00Z",
                "duration": 240.5
            }
        """
        url = f"{self.base_url}/projects/{project_id}/jobs/{job_id}"

        logger.debug("Fetching details for job %s in project %s", job_id, project_id)

        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()

            job_data = response.json()
            logger.debug("Successfully fetched details for job %s", job_id)
            return job_data

        except requests.RequestException:
            logger.error("Failed to fetch details for job %s", job_id)
            raise

    @retry_on_failure(max_retries=3, base_delay=2.0, exceptions=(requests.RequestException,))
    def fetch_pipeline_jobs(self, project_id: int, pipeline_id: int) -> List[Dict[str, Any]]:
        """
        Fetch all jobs associated with a pipeline.

        Retrieves a list of all jobs in a pipeline, including jobs in child pipelines.
        Handles pagination automatically.

        Args:
            project_id (int): GitLab project ID
            pipeline_id (int): GitLab pipeline ID

        Returns:
            List[Dict[str, Any]]: List of job details

        Raises:
            GitLabAPIError: If the API returns an error
            RetryExhaustedError: If all retry attempts fail

        API Endpoint:
            GET /projects/:id/pipelines/:pipeline_id/jobs

        Example:
            fetcher = LogFetcher(config)
            jobs = fetcher.fetch_pipeline_jobs(123, 789)
            for job in jobs:
                print(f"Job: {job['name']}, Status: {job['status']}")
        """
        url = f"{self.base_url}/projects/{project_id}/pipelines/{pipeline_id}/jobs"

        logger.info("Fetching jobs for pipeline %s in project %s", pipeline_id, project_id)

        all_jobs = []
        page = 1
        per_page = 100

        try:
            while True:
                response = self.session.get(
                    url,
                    params={'page': page, 'per_page': per_page},
                    timeout=30
                )
                response.raise_for_status()

                jobs = response.json()
                if not jobs:
                    break

                all_jobs.extend(jobs)
                logger.debug("Fetched page %s with %s jobs", page, len(jobs))

                # Check if there are more pages
                if len(jobs) < per_page:
                    break

                page += 1

            logger.info("Successfully fetched %s jobs for pipeline %s", len(all_jobs), pipeline_id)
            return all_jobs

        except requests.RequestException:
            logger.error("Failed to fetch jobs for pipeline %s", pipeline_id)
            raise

    def fetch_all_logs_for_pipeline(
        self,
        project_id: int,
        pipeline_id: int
    ) -> Dict[int, Dict[str, Any]]:
        """
        Fetch logs for all jobs in a pipeline.

        This is a convenience method that fetches all jobs in a pipeline and then
        retrieves the log content for each job.

        Args:
            project_id (int): GitLab project ID
            pipeline_id (int): GitLab pipeline ID

        Returns:
            Dict[int, Dict[str, Any]]: Dictionary mapping job IDs to job data with logs
                {
                    job_id: {
                        "details": {...},  # Job metadata
                        "log": "..."       # Log content
                    }
                }

        Example:
            fetcher = LogFetcher(config)
            all_logs = fetcher.fetch_all_logs_for_pipeline(123, 789)
            for job_id, job_data in all_logs.items():
                print(f"Job {job_id}: {job_data['details']['name']}")
                print(job_data['log'][:100])  # First 100 chars
        """
        logger.info("Fetching all logs for pipeline %s", pipeline_id)

        # Fetch all jobs in the pipeline
        jobs = self.fetch_pipeline_jobs(project_id, pipeline_id)

        # Fetch logs for each job
        all_logs = {}
        for job in jobs:
            job_id = job['id']
            try:
                log_content = self.fetch_job_log(project_id, job_id)
                all_logs[job_id] = {
                    'details': job,
                    'log': log_content
                }
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.error("Failed to fetch log for job %s: %s", job_id, str(e))
                all_logs[job_id] = {
                    'details': job,
                    'log': f"[Error fetching log: {str(e)}]"
                }

        logger.info("Successfully fetched logs for %s jobs", len(all_logs))
        return all_logs

    @retry_on_failure(max_retries=3, base_delay=2.0, exceptions=(requests.RequestException,))
    def fetch_pipeline_details(self, project_id: int, pipeline_id: int) -> Dict[str, Any]:
        """
        Fetch detailed information about a pipeline.

        Args:
            project_id (int): GitLab project ID
            pipeline_id (int): GitLab pipeline ID

        Returns:
            Dict[str, Any]: Pipeline details including status, ref, user, etc.

        Raises:
            GitLabAPIError: If the API returns an error
            RetryExhaustedError: If all retry attempts fail

        API Endpoint:
            GET /projects/:id/pipelines/:pipeline_id
        """
        url = f"{self.base_url}/projects/{project_id}/pipelines/{pipeline_id}"

        logger.debug("Fetching details for pipeline %s", pipeline_id)

        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()

            pipeline_data = response.json()
            logger.debug("Successfully fetched details for pipeline %s", pipeline_id)
            return pipeline_data

        except requests.RequestException:
            logger.error("Failed to fetch details for pipeline %s", pipeline_id)
            raise

    def close(self):
        """
        Close the HTTP session.

        Should be called when the log fetcher is no longer needed to free up resources.
        """
        self.session.close()
        logger.debug("Log fetcher session closed")


if __name__ == "__main__":
    # Example usage
    import sys  # pylint: disable=import-outside-toplevel,unused-import
    from config_loader import ConfigLoader  # pylint: disable=import-outside-toplevel,import-error

    logging.basicConfig(level=logging.INFO)

    try:
        # Load configuration
        config = ConfigLoader.load()  # pylint: disable=redefined-outer-name

        # Create log fetcher
        fetcher = LogFetcher(config)

        # Example: Fetch logs for a specific job
        if len(sys.argv) >= 3:
            project_id = int(sys.argv[1])  # pylint: disable=redefined-outer-name
            job_id = int(sys.argv[2])  # pylint: disable=redefined-outer-name

            print(f"Fetching log for job {job_id} in project {project_id}...")
            log = fetcher.fetch_job_log(project_id, job_id)
            print(f"\nLog content ({len(log)} bytes):")
            print(log[:500])  # Print first 500 characters

        fetcher.close()

    except Exception as e:  # pylint: disable=broad-exception-caught
        print(f"Error: {e}")
