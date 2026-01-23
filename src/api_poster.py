"""
API Poster Module

This module handles posting pipeline logs to an external API endpoint.
Instead of (or in addition to) saving logs to files, it POSTs them to
a configured API for centralized storage and processing.

Data Flow:
    Pipeline Info + All Logs → format_payload() → POST to API → Log Response

Invoked by: webhook_listener
Invokes: log_error_extractor, config_loader, error_handler, token_manager
"""

import json
import logging
import time
from typing import Dict, Any, Optional, Tuple
from datetime import datetime
from pathlib import Path

import requests
from requests.exceptions import RequestException

from .log_error_extractor import extract_error_sections
from .config_loader import Config
from .error_handler import ErrorHandler, RetryExhaustedError
from .token_manager import TokenManager

# Configure module logger
logger = logging.getLogger(__name__)


class ApiPoster:
    """
    Posts pipeline logs to external API endpoint.
    This class formats pipeline logs and job data into JSON payloads and POSTs them to a configured API endpoint with
    authentication and retry support.

    Attributes:
        config (Config): Application configuration
        api_log_file (Path): Path to API request/response log file
    """

    def __init__(self, config: Config):
        """
        Initialize the API poster.

        Args:
            config (Config): Application configuration
        """
        self.config = config

        # Setup dedicated API log file
        log_dir = Path(config.log_output_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        self.api_log_file = log_dir / "api-requests.log"

        # Initialize token manager for JWT authentication
        self.token_manager = None
        self.bfa_token_cache = None  # Cache token fetched from BFA server
        self.bfa_token_expiry = None  # Track token expiration

        if config.bfa_secret_key:
            try:
                self.token_manager = TokenManager(config.bfa_secret_key)
                logger.debug("6. TokenManager initialized for JWT authentication")
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.error("6. Failed to initialize TokenManager: %s", e, exc_info=True)
                logger.warning("6. JWT authentication will be disabled, using raw secret key")
        elif config.bfa_host:
            logger.debug("6. BFA_SECRET_KEY not set, will fetch tokens from BFA server: %s", config.bfa_host)
        else:
            logger.warning("6. Neither BFA_SECRET_KEY nor BFA_HOST configured - API authentication may fail")

        # Initialize GitLab API session for Jenkins user lookups
        self.gitlab_session = None
        self.gitlab_base_url = None
        if config.gitlab_url and config.gitlab_token:
            self.gitlab_session = requests.Session()
            self.gitlab_session.headers.update({
                'PRIVATE-TOKEN': config.gitlab_token,
                'Content-Type': 'application/json'
            })
            self.gitlab_base_url = f"{config.gitlab_url}/api/v4"
            logger.debug("6. GitLab API session initialized for Jenkins user lookups")
        else:
            logger.debug("6. GitLab API session not available - Jenkins user lookups will be limited")

        logger.info("6. API Poster log file: %s", self.api_log_file)
        logger.debug("6. API Poster initialized")

    def format_payload(self, pipeline_info: Dict[str, Any], all_logs: Dict[int, Dict[str, Any]]) -> Dict[str, Any]:
        """
        Format pipeline and job data into simplified API payload.

        Args:
            pipeline_info (Dict[str, Any]): Pipeline metadata
            all_logs (Dict[int, Dict[str, Any]]): Job logs mapped by job_id

        Returns:
            Dict[str, Any]: Formatted JSON payload

        Simplified Payload Structure:
            {
                "repo": str,              # Repository name (short form)
                "branch": str,            # Branch/ref name
                "commit": str,            # Short commit SHA (7 chars)
                "job_name": [str],        # List of all job names
                "pipeline_id": str,       # Full pipeline URL
                "triggered_by": str,      # Username or source
                "failed_steps": [         # Only jobs with status="failed"
                    {
                        "step_name": str,
                        "error_lines": [str]  # ASCII-only error lines
                    }
                ]
            }

        Note: error_lines are sanitized to ASCII-only to avoid JSON encoding issues with special characters.
        """
        # Extract repository name (short form) "my-org/demo-repo" -> "demo-repo"
        project_name = pipeline_info.get('project_name', 'unknown')
        repo = project_name.split('/')[-1] if '/' in project_name else project_name
        # Extract branch
        branch = pipeline_info.get('ref', 'unknown')
        # Extract short commit SHA (first 7 characters)
        sha = pipeline_info.get('sha', '')
        commit = sha[:7] if sha else 'unknown'
        # Build job_name str (all jobs)
        job_names = ",".join(job_data.get("details", {}).get("name", "unknown") for job_data in all_logs.values())

        # Extract triggered_by Priority: user.username -> user.name -> source
        user_info = pipeline_info.get('user', {})
        if isinstance(user_info, dict):
            triggered_by = user_info.get('username') or user_info.get('name')
            if triggered_by:
                triggered_by = f"{triggered_by}@sandvine.com"
        else:
            triggered_by = None

        if not triggered_by:
            triggered_by = pipeline_info.get('source', 'unknown')

        # Build failed_steps (only jobs with status="failed")
        failed_steps = []
        for job_data in all_logs.values():
            job_details = job_data.get('details', {})
            job_status = job_details.get('status', '')

            # Only include failed jobs
            if job_status == 'failed':
                step_name = job_details.get('name', 'unknown')
                log_content = job_data.get('log', '')

                # Extract error sections with context using configurable parameters
                error_lines = extract_error_sections(
                    log_content=log_content,
                    lines_before=self.config.error_context_lines_before,
                    lines_after=self.config.error_context_lines_after
                )

                if error_lines:
                    # error_lines is a list with one string element containing all lines joined by \n
                    line_count = error_lines[0].count('\n') + 1 if error_lines else 0
                    logger.debug(
                        "Extracted error context from job '%s': %d lines (context: %d before, %d after)",
                        step_name, line_count, self.config.error_context_lines_before,
                        self.config.error_context_lines_after,
                        extra={'job_name': step_name, 'error_line_count': line_count}
                    )

                failed_steps.append({"step_name": step_name, "error_lines": error_lines})

        # Extract pipeline URL (provided by GitLab in webhook)
        pipeline_url = pipeline_info.get('pipeline_url', '')

        # Build complete payload
        payload = {
            "source": "gitlab",                        # Identify as GitLab source
            "repo": repo,
            "branch": branch,
            "commit": commit,
            "job_name": job_names,
            "pipeline_id": pipeline_url,               # Full pipeline URL from GitLab
            "triggered_by": triggered_by,
            "failed_steps": failed_steps
        }

        return payload

    def format_jenkins_payload(
        self,
        jenkins_payload: Dict[str, Any],
        build_metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Transform Jenkins payload to match GitLab API format.

        Args:
            jenkins_payload: Raw Jenkins webhook payload with structure:
                {
                    "source": "jenkins",
                    "job_name": str,
                    "build_number": int,
                    "build_url": str,
                    "status": str,
                    "parameters": {
                        "gitlabSourceRepoName": str,
                        "gitlabSourceBranch": str,
                        "gitlabMergeRequestLastCommit": str (optional)
                    },
                    "stages": [
                        {
                            "stage_name": str,
                            "status": str,
                            "log_content": str
                        }
                    ]
                }
            build_metadata: Optional Jenkins build metadata from API (for user extraction)

        Returns:
            Dict[str, Any]: Transformed payload matching GitLab format:
                {
                    "repo": str,              # From parameters or job_name
                    "branch": str,            # From parameters or "unknown"
                    "commit": str,            # From parameters or "unknown"
                    "job_name": str,          # job_name
                    "pipeline_id": str,       # Full build URL
                    "triggered_by": str,      # Username@internal.com
                    "failed_steps": [
                        {
                            "step_name": str,
                            "error_lines": [str]  # List with single element containing formatted lines
                        }
                    ]
                }
        """
        job_name = jenkins_payload.get('job_name', 'unknown')
        build_number = jenkins_payload.get('build_number', 0)
        build_url = jenkins_payload.get('build_url', '')
        parameters = jenkins_payload.get('parameters', {})
        stages = jenkins_payload.get('stages', [])

        # Extract repo, branch, commit from pipeline parameters
        repo = parameters.get('gitlabSourceRepoName', job_name)
        branch = parameters.get('gitlabSourceBranch', 'unknown')
        commit = parameters.get('gitlabMergeRequestLastCommit', 'unknown')

        # Determine who triggered the build (Jenkins user or GitLab user)
        if build_metadata:
            triggered_by = self._determine_jenkins_triggered_by(parameters, build_metadata)
        else:
            # Fallback if metadata not available
            triggered_by = "jenkins@internal.com"
            logger.warning("Build metadata not available, using fallback triggered_by")

        # Filter to only failed stages
        failed_stages = [s for s in stages if s.get('status') in ['FAILED', 'FAILURE']]

        logger.debug(
            "Transforming Jenkins payload: job=%s, build=%s, repo=%s, branch=%s, total_stages=%d, failed_stages=%d",
            job_name, build_number, repo, branch, len(stages), len(failed_stages)
        )

        # Build failed_steps from failed stages
        failed_steps = []
        for stage in failed_stages:
            stage_name = stage.get('stage_name', 'unknown')
            log_content = stage.get('log_content', '')

            # Transform log_content to error_lines format
            # log_content is already formatted with "Line N:" prefixes from log_error_extractor
            # Include the stage even if log_content is empty (better than dropping it completely)
            if log_content:
                # error_lines should be a list with single element (matching GitLab format)
                error_lines = [log_content]

                line_count = log_content.count('\n') + 1
                logger.debug(
                    "Transformed stage '%s': %d error lines",
                    stage_name, line_count
                )
            else:
                # Stage failed but has no log content - include it with placeholder
                error_lines = [f"Stage '{stage_name}' failed but no log content available"]
                logger.warning(
                    "Stage '%s' has no log content, using placeholder",
                    stage_name
                )

            failed_steps.append({
                "step_name": stage_name,
                "error_lines": error_lines
            })

        # Build transformed payload matching GitLab format
        payload = {
            "source": "jenkins",                       # Identify as Jenkins source
            "repo": repo,                              # From parameters or job_name
            "branch": branch,                          # From parameters or "unknown"
            "commit": commit,                          # From parameters or "unknown"
            "job_name": job_name,                      # Job name
            "pipeline_id": build_url,                  # Full build URL
            "triggered_by": triggered_by,              # Jenkins or GitLab user
            "failed_steps": failed_steps               # Failed stages with error context
        }

        logger.debug(
            "Transformed Jenkins payload: repo=%s, branch=%s, pipeline_id=%s, failed_steps=%d",
            payload['repo'], payload['branch'], payload['pipeline_id'], len(failed_steps)
        )

        return payload

    def _get_gitlab_project_id(self, namespace: str, repo_name: str) -> Optional[int]:
        """
        Get GitLab project ID from namespace and repo name.

        Args:
            namespace: GitLab namespace/group (e.g., "sandvine-platform")
            repo_name: Repository name (e.g., "ci_build")

        Returns:
            Project ID or None if not found

        API: GET /api/v4/projects/:namespace%2F:repo_name
        """
        if not self.gitlab_session:
            logger.debug("GitLab API session not available")
            return None

        try:
            project_path = f"{namespace}/{repo_name}"
            encoded_path = requests.utils.quote(project_path, safe='')
            url = f"{self.gitlab_base_url}/projects/{encoded_path}"

            logger.debug("Fetching GitLab project ID for: %s", project_path)
            response = self.gitlab_session.get(url, timeout=10)
            response.raise_for_status()

            project_data = response.json()
            project_id = project_data.get('id')
            logger.debug("Found project ID %d for %s", project_id, project_path)
            return project_id

        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning(
                "Failed to fetch GitLab project ID for %s/%s: %s",
                namespace, repo_name, e
            )
            return None

    def _get_user_from_merge_request(self, project_id: int, mr_iid: int) -> Optional[str]:
        """
        Get username from GitLab merge request.

        Args:
            project_id: GitLab project ID
            mr_iid: Merge request IID (project-specific)

        Returns:
            Username or None if not found

        API: GET /api/v4/projects/:id/merge_requests/:merge_request_iid
        """
        if not self.gitlab_session:
            return None

        try:
            url = f"{self.gitlab_base_url}/projects/{project_id}/merge_requests/{mr_iid}"

            logger.debug("Fetching MR !%d from project %d", mr_iid, project_id)
            response = self.gitlab_session.get(url, timeout=10)
            response.raise_for_status()

            mr_data = response.json()
            author = mr_data.get('author', {})
            username = author.get('username')

            if username:
                logger.info("Found MR author: %s for MR !%d", username, mr_iid)
                return username

            return None

        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning(
                "Failed to fetch MR !%d from project %d: %s",
                mr_iid, project_id, e
            )
            return None

    def _get_user_from_commit(self, project_id: int, commit_sha: str) -> Optional[str]:
        """
        Get username from GitLab commit.

        Args:
            project_id: GitLab project ID
            commit_sha: Commit SHA

        Returns:
            Username or None if not found

        API: GET /api/v4/projects/:id/repository/commits/:sha
        """
        if not self.gitlab_session:
            return None

        try:
            url = f"{self.gitlab_base_url}/projects/{project_id}/repository/commits/{commit_sha}"

            logger.debug("Fetching commit %s from project %d", commit_sha[:8], project_id)
            response = self.gitlab_session.get(url, timeout=10)
            response.raise_for_status()

            commit_data = response.json()

            # GitLab returns author_name and author_email, but not username directly
            # Extract username from email if it matches pattern (e.g., "john.doe@internal.com" -> "john.doe")
            author_email = commit_data.get('author_email', '')

            if '@' in author_email:
                username = author_email.split('@')[0]
                logger.info("Extracted username '%s' from commit %s", username, commit_sha[:8])
                return username

            # Fallback: use author_name
            author_name = commit_data.get('author_name')
            if author_name:
                logger.info("Using author name '%s' for commit %s", author_name, commit_sha[:8])
                return author_name

            return None

        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning(
                "Failed to fetch commit %s from project %d: %s",
                commit_sha[:8], project_id, e
            )
            return None

    def _get_user_from_branch(self, project_id: int, branch_name: str) -> Optional[str]:
        """
        Get username from latest commit on GitLab branch.

        Args:
            project_id: GitLab project ID
            branch_name: Branch name

        Returns:
            Username or None if not found

        API: GET /api/v4/projects/:id/repository/branches/:branch
        """
        if not self.gitlab_session:
            return None

        try:
            encoded_branch = requests.utils.quote(branch_name, safe='')
            url = f"{self.gitlab_base_url}/projects/{project_id}/repository/branches/{encoded_branch}"

            logger.debug("Fetching branch '%s' from project %d", branch_name, project_id)
            response = self.gitlab_session.get(url, timeout=10)
            response.raise_for_status()

            branch_data = response.json()
            commit_data = branch_data.get('commit', {})
            commit_sha = commit_data.get('id')

            if commit_sha:
                # Get user from the latest commit
                return self._get_user_from_commit(project_id, commit_sha)

            return None

        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning(
                "Failed to fetch branch '%s' from project %d: %s",
                branch_name, project_id, e
            )
            return None

    def _extract_jenkins_user_from_metadata(self, build_metadata: Dict[str, Any]) -> Optional[str]:
        """
        Extract Jenkins user who triggered the build from metadata.

        Args:
            build_metadata: Jenkins build metadata from API

        Returns:
            Username (e.g., "john.doe") or None if not found

        Looks for hudson.model.Cause$UserIdCause in actions[].causes[]
        """
        try:  # pylint: disable=too-many-nested-blocks
            actions = build_metadata.get('actions', [])
            for action in actions:
                if action.get('_class') == 'hudson.model.CauseAction':
                    causes = action.get('causes', [])
                    for cause in causes:
                        if cause.get('_class') == 'hudson.model.Cause$UserIdCause':
                            user_id = cause.get('userId')
                            if user_id:
                                logger.debug("Found Jenkins userId from metadata: %s", user_id)
                                return user_id

            logger.debug("No UserIdCause found in Jenkins metadata")
            return None

        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning("Failed to extract Jenkins user from metadata: %s", e)
            return None

    def _determine_jenkins_triggered_by(
        self,
        parameters: Dict[str, Any],
        build_metadata: Dict[str, Any]
    ) -> str:
        """
        Determine who triggered the Jenkins pipeline.

        Strategy:
        1. Extract Jenkins user from build metadata
        2. If user is "jenkins" → GitLab webhook triggered it → Look up actual GitLab user
        3. If user is not "jenkins" → Manual trigger → Use Jenkins user directly
        4. Always append @internal.com

        Args:
            parameters: Jenkins pipeline parameters
            build_metadata: Jenkins build metadata

        Returns:
            Username formatted as "username@internal.com"
        """
        # Step 1: Extract Jenkins user from metadata
        jenkins_user = self._extract_jenkins_user_from_metadata(build_metadata)

        # Step 2: Check if it's the "jenkins" system user (GitLab webhook trigger)
        if jenkins_user and jenkins_user.lower() != "jenkins":
            # Manual Jenkins trigger - use Jenkins username directly
            result = f"{jenkins_user}@internal.com"
            logger.info("Jenkins build triggered manually by Jenkins user: %s", result)
            return result

        # Step 3: GitLab webhook trigger - look up actual GitLab user
        logger.debug("Jenkins build triggered by GitLab webhook (user='jenkins'), looking up actual user")

        namespace = parameters.get('gitlabSourceNamespace') or parameters.get('sourceNamespace')
        repo_name = parameters.get('gitlabSourceRepoName')

        if not namespace or not repo_name:
            logger.warning(
                "Missing namespace or repo name in Jenkins parameters, cannot determine GitLab user"
            )
            return "jenkins@internal.com"

        # Get GitLab project ID
        project_id = self._get_gitlab_project_id(namespace, repo_name)
        if not project_id:
            logger.warning("Could not find GitLab project ID, falling back to 'jenkins@internal.com'")
            return "jenkins@internal.com"

        gitlab_username = None

        # Strategy 1: Pre-merge pipeline (has MR IID)
        mr_iid = parameters.get('gitlabMergeRequestIid')
        if mr_iid:
            try:
                mr_iid_int = int(mr_iid)
                gitlab_username = self._get_user_from_merge_request(project_id, mr_iid_int)
                if gitlab_username:
                    logger.info("Determined Jenkins pipeline triggered by MR author: %s", gitlab_username)
            except (ValueError, TypeError) as e:
                logger.warning("Invalid MR IID '%s': %s", mr_iid, e)

        # Strategy 2: Build pipeline with commit SHA
        if not gitlab_username:
            commit_sha = parameters.get('gitlabMergeRequestLastCommit')
            if commit_sha and commit_sha != 'unknown':
                gitlab_username = self._get_user_from_commit(project_id, commit_sha)
                if gitlab_username:
                    logger.info(
                        "Determined Jenkins pipeline triggered by commit author: %s",
                        gitlab_username
                    )

        # Strategy 3: Build pipeline with branch only
        if not gitlab_username:
            branch = parameters.get('gitlabSourceBranch')
            if branch and branch != 'unknown':
                gitlab_username = self._get_user_from_branch(project_id, branch)
                if gitlab_username:
                    logger.info(
                        "Determined Jenkins pipeline triggered by branch's last committer: %s",
                        gitlab_username
                    )

        # Format username
        if gitlab_username:
            return f"{gitlab_username}@internal.com"

        # Fallback
        logger.warning("Could not determine Jenkins pipeline trigger user, using 'jenkins@internal.com'")
        return "jenkins@internal.com"

    def _fetch_token_from_bfa_server(self, subject: str) -> Optional[str]:
        """
        Fetch authentication token from BFA server's /api/token endpoint.

        Args:
            subject: Token subject (e.g., "gitlab_repository_1066055")

        Returns:
            Token string if successful, None otherwise
        """
        if not self.config.bfa_host:
            logger.error("Cannot fetch token: BFA_HOST not configured")
            return None

        # Check if cached token is still valid (expires in 50 minutes, fetch new before expiry)
        if self.bfa_token_cache and self.bfa_token_expiry:
            if time.time() < self.bfa_token_expiry:
                logger.debug("Using cached BFA token")
                return self.bfa_token_cache

        # Construct token endpoint URL
        token_url = f"http://{self.config.bfa_host}:8000/api/token"

        try:
            logger.info("Fetching JWT token from BFA server: %s", token_url)

            # Make request to BFA server
            response = requests.post(token_url, json={"subject": subject, "expires_in": 60}, timeout=10)
            response.raise_for_status()

            # Parse response
            token_data = response.json()
            token = token_data.get('token')

            if not token:
                logger.error("BFA server response missing 'token' field: %s", token_data)
                return None

            # Cache the token (expires in 50 minutes to refresh before actual expiry)
            self.bfa_token_cache = token
            self.bfa_token_expiry = time.time() + (50 * 60)  # 50 minutes

            logger.info("Successfully fetched token from BFA server for subject: %s", subject)
            return token

        except RequestException as e:
            logger.error("Failed to fetch token from BFA server: %s", e, exc_info=True)
            return None
        except (ValueError, KeyError) as e:
            logger.error("Failed to parse token response from BFA server: %s", e, exc_info=True)
            return None

    def _prepare_authentication_header(self, subject: str) -> Optional[str]:
        """
        Prepare authentication header value based on available configuration.

        Authentication Strategy:
        1. If TokenManager available -> Generate JWT locally
        2. Else if BFA_HOST configured -> Fetch token from BFA server
        3. Else if BFA_SECRET_KEY -> Use raw secret key
        4. Else -> No authentication

        Args:
            subject: Subject for JWT token (format: source_repo_pipeline_id)

        Returns:
            Authorization header value (without "Bearer " prefix) or None
        """
        # Strategy 1: Generate JWT locally
        if self.token_manager:
            try:
                jwt_token = self.token_manager.generate_token(subject, expires_in_minutes=60)
                logger.info("Generated JWT token locally for subject: %s", subject)
                return jwt_token
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.error("Failed to generate JWT token: %s", e, exc_info=True)
                # Fallback to other strategies
                return self._prepare_fallback_authentication(subject)

        # Strategy 2: Fetch token from BFA server
        if self.config.bfa_host:
            try:
                fetched_token = self._fetch_token_from_bfa_server(subject)
                if fetched_token:
                    logger.info("Using token fetched from BFA server for subject: %s", subject)
                    return fetched_token
                logger.error("Failed to fetch token from BFA server, no authentication will be sent")
                return None
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.error("Error fetching token from BFA server: %s", e, exc_info=True)
                return None

        # Strategy 3: Use raw secret key (legacy)
        if self.config.bfa_secret_key:
            logger.info("Using raw secret key for authentication (no TokenManager or BFA_HOST)")
            return self.config.bfa_secret_key

        # Strategy 4: No authentication
        logger.warning("No authentication configured (no BFA_SECRET_KEY or BFA_HOST)")
        return None

    def _prepare_fallback_authentication(self, subject: str) -> Optional[str]:
        """
        Prepare fallback authentication when JWT generation fails.

        Args:
            subject: Subject for JWT token

        Returns:
            Authorization token or None
        """
        if self.config.bfa_host:
            fetched_token = self._fetch_token_from_bfa_server(subject)
            if fetched_token:
                logger.warning("JWT generation failed, using token from BFA server")
                return fetched_token

        if self.config.bfa_secret_key:
            logger.warning("JWT generation failed, using raw secret key")
            return self.config.bfa_secret_key

        return None

    def _post_to_api(
        self, payload: Dict[str, Any]
    ) -> Tuple[int, str, float]:
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

        # Extract info for subject/authentication
        repo = payload.get('repo', 'unknown')
        pipeline_id = payload.get('pipeline_id', '0')
        source = payload.get('source', 'gitlab')
        subject = f"{source}_{repo}_{pipeline_id}"

        # Prepare authentication
        auth_token = self._prepare_authentication_header(subject)
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"

        start_time = time.time()

        try:
            response = requests.post(
                self.config.api_post_url,
                json=payload,
                headers=headers,
                timeout=self.config.api_post_timeout
            )

            duration_ms = int((time.time() - start_time) * 1000)

            # Get full response body for logging
            response_body = response.text

            # Parse JSON response to check status field
            try:
                response_json = response.json()
            except ValueError as exc:
                logger.error("API returned non-JSON response: %s", response_body[:500])
                raise RequestException(
                    f"API returned non-JSON response after {duration_ms}ms"
                ) from exc

            # Check "status" field in response body (not HTTP status code)
            # API returns: {"status": "ok", "results": [...]}
            response_status = response_json.get("status")

            if response_status == "ok":
                # Success - log results if present
                results = response_json.get("results", [])
                logger.info(
                    "API returned success status",
                    extra={
                        'response_status': response_status,
                        'results_count': len(results),
                        'http_status': response.status_code,
                        'duration_ms': duration_ms
                    }
                )

                # Log each result for debugging
                for idx, result in enumerate(results):
                    logger.debug(
                        "Result %d: step=%s, error_hash=%s, source=%s",
                        idx + 1, result.get('step_name'),
                        result.get('error_hash'), result.get('source')
                    )

                return response.status_code, response_body, duration_ms

            # Failure - status is not "ok"
            # Just log basic info (retry handler will log payload on final failure)
            logger.debug(
                "API returned status '%s' (expected 'ok') | http_status=%s duration_ms=%s",
                response_status, response.status_code, duration_ms
            )
            raise RequestException(
                f"API returned status '{response_status}' (expected 'ok') after {duration_ms}ms"
            )

        except requests.exceptions.HTTPError as e:
            # HTTP error (4xx, 5xx)
            duration_ms = int((time.time() - start_time) * 1000)
            error_msg = str(e)[:1000]
            raise RequestException(
                f"API request failed after {duration_ms}ms: {error_msg}"
            ) from e

        except RequestException as e:
            # Other request errors (timeout, connection, etc.) - just re-raise
            duration_ms = int((time.time() - start_time) * 1000)
            error_msg = str(e)[:1000]
            raise RequestException(
                f"API request failed after {duration_ms}ms: {error_msg}"
            ) from e

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
            logger.error("Failed to write to API log file: %s", e)

    def post_pipeline_logs(self, pipeline_info: Dict[str, Any], all_logs: Dict[int, Dict[str, Any]]) -> bool:
        """
        Post pipeline logs to API endpoint.
        This method to call for posting pipeline logs. It handles formatting, posting, retrying, and logging.

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
            "Posting pipeline logs to API for '%s' (pipeline %s)",
            project_name, pipeline_id,
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
            payload_json = json.dumps(payload, indent=2)
            payload_size = len(payload_json)

            # Always log payload summary
            logger.info(
                "Formatted API payload for pipeline %s",
                pipeline_id,
                extra={
                    'pipeline_id': pipeline_id,
                    'repo': payload.get('repo'),
                    'branch': payload.get('branch'),
                    'commit': payload.get('commit'),
                    'job_count': len(payload.get('job_name', [])),
                    'failed_steps_count': len(payload.get('failed_steps', [])),
                    'payload_size_bytes': payload_size
                }
            )

            # Log full payload in DEBUG mode for troubleshooting
            logger.debug("Full API payload:\n%s", payload_json)

        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error(
                "Failed to format API payload for pipeline %s: %s",
                pipeline_id, e,
                extra={
                    'pipeline_id': pipeline_id,
                    'project_id': project_id,
                    'project_name': project_name,
                    'error_type': type(e).__name__
                },
                exc_info=True
            )

            # Log pipeline_info to understand what data failed
            logger.error("Pipeline info that caused formatting error: %s",
                         json.dumps(pipeline_info, indent=2, default=str))

            self._log_api_request(pipeline_id, project_id, None, "", 0, error=f"Payload formatting failed: {str(e)}")
            return False

        # POST to API (with retry if enabled)
        try:
            if self.config.api_post_retry_enabled:
                # Use retry logic
                logger.info("Using retry logic for API POST")
                error_handler = ErrorHandler(
                    max_retries=self.config.retry_attempts,
                    base_delay=self.config.retry_delay,
                    exponential=True
                )
                status_code, response_body, duration_ms = error_handler.retry_with_backoff(
                    self._post_to_api,
                    payload,
                    exceptions=(RequestException,)
                )
            else:
                # No retry, single attempt
                logger.info("Retry disabled, single API POST attempt")
                status_code, response_body, duration_ms = self._post_to_api(payload)

            # Success
            logger.info(
                "Successfully posted pipeline %s logs to API",
                pipeline_id,
                extra={
                    'pipeline_id': pipeline_id,
                    'project_id': project_id,
                    'status_code': status_code,
                    'duration_ms': duration_ms,
                    'payload_size': payload_size
                }
            )

            # Log to file
            self._log_api_request(pipeline_id, project_id, status_code, response_body, duration_ms)

            return True

        except RetryExhaustedError as e:
            logger.error(
                "Failed to post pipeline %s logs after retries: %s",
                pipeline_id, e,
                extra={
                    'pipeline_id': pipeline_id,
                    'project_id': project_id,
                    'project_name': project_name,
                    'error_type': 'RetryExhaustedError',
                    'error_message': str(e)
                },
                exc_info=True
            )

            # Log the payload that failed after all retries
            logger.error("Payload that failed after all retries:\n%s", json.dumps(payload, indent=2))

            self._log_api_request(pipeline_id, project_id, None, "", 0, error=f"Retry exhausted: {str(e)}")

            return False

        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error(
                "Unexpected error posting pipeline %s logs: %s",
                pipeline_id, e,
                extra={
                    'pipeline_id': pipeline_id,
                    'project_id': project_id,
                    'project_name': project_name,
                    'error_type': type(e).__name__,
                    'error_message': str(e)
                },
                exc_info=True
            )

            # Log the payload that caused the unexpected error
            logger.error("Payload that caused unexpected error:\n%s", json.dumps(payload, indent=2))

            self._log_api_request(pipeline_id, project_id, None, "", 0, error=f"{type(e).__name__}: {str(e)}")

            return False

    def post_jenkins_logs(
        self,
        jenkins_payload: Dict[str, Any],
        build_metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
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
            build_metadata: Optional Jenkins build metadata from API (for user extraction)

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
            "Posting Jenkins build to API: %s #%s",
            jenkins_payload['job_name'], jenkins_payload['build_number']
        )

        try:
            # Transform Jenkins payload to match GitLab API format
            payload = self.format_jenkins_payload(jenkins_payload, build_metadata)

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
                        exceptions=(RequestException,)
                    )
                except RetryExhaustedError as e:
                    logger.error("Retry exhausted posting Jenkins logs to API: %s", e)

                    # Log the payload that failed after all retries
                    logger.error("Payload that failed after all retries:\n%s", json.dumps(payload, indent=2))

                    # Extract pipeline_id and project_id from payload
                    pipeline_id = payload.get('build_number', 0)
                    project_id = 0  # Jenkins doesn't have project_id concept
                    self._log_api_request(
                        pipeline_id=pipeline_id,
                        project_id=project_id,
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
            # Extract pipeline_id and project_id from payload
            pipeline_id = payload.get('build_number', 0)
            project_id = 0  # Jenkins doesn't have project_id concept
            self._log_api_request(
                pipeline_id=pipeline_id,
                project_id=project_id,
                status_code=status_code,
                response_body=response_body,
                duration_ms=duration_ms
            )

            # Check if successful
            if 200 <= status_code < 300:
                job_name = jenkins_payload['job_name']
                build_num = jenkins_payload['build_number']
                logger.info(
                    "Successfully posted Jenkins build %s #%s to API",
                    job_name, build_num,
                    extra={
                        'job_name': job_name,
                        'build_number': build_num,
                        'status_code': status_code,
                        'duration_ms': duration_ms
                    }
                )

                # Log successful payload for debugging
                logger.debug("Payload posted successfully:\n%s", json.dumps(payload, indent=2))

                return True

            logger.warning(
                "API returned non-success status code for Jenkins build: %s",
                status_code,
                extra={
                    'job_name': jenkins_payload['job_name'],
                    'build_number': jenkins_payload['build_number'],
                    'status_code': status_code
                }
            )
            return False

        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error(
                "Unexpected error posting Jenkins logs to API: %s",
                e,
                extra={
                    'job_name': jenkins_payload.get('job_name', 'unknown'),
                    'build_number': jenkins_payload.get('build_number', 0),
                    'error_type': type(e).__name__,
                    'error': str(e)
                },
                exc_info=True
            )

            # Log the payload that caused the unexpected error
            logger.error("Payload that caused unexpected error:\n%s", json.dumps(jenkins_payload, indent=2))

            # Extract pipeline_id and project_id from payload
            pipeline_id = jenkins_payload.get('build_number', 0)
            project_id = 0  # Jenkins doesn't have project_id concept
            self._log_api_request(
                pipeline_id=pipeline_id,
                project_id=project_id,
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
