"""
Webhook Listener Module

This is the main application entry point. It runs a FastAPI web server that listens
for GitLab webhook events, processes them, fetches logs, and stores them.

Data Flow:
    GitLab → POST /webhook → validate_webhook() → process_pipeline_event() →
    PipelineExtractor → LogFetcher → StorageManager → Disk Storage

Server Architecture:
    - FastAPI application listening on configured port (default: 8000)
    - Single webhook endpoint: POST /webhook
    - Optional webhook secret validation
    - Background task processing

Invoked by: None (application entry point)
Invokes: config_loader, pipeline_extractor, log_fetcher, storage_manager, error_handler,
         monitoring, api_poster, jenkins_extractor, jenkins_log_fetcher, token_manager,
         logging_config
"""
# pylint: disable=too-many-lines

import logging
import sys
import hmac
import uuid
import time
import tempfile
from typing import Dict, Any, Optional
from datetime import datetime
from fastapi import FastAPI, Request, Header, BackgroundTasks, HTTPException, Query
from fastapi.responses import FileResponse
import uvicorn  # pylint: disable=import-error

from .config_loader import ConfigLoader, Config
from .pipeline_extractor import PipelineExtractor
from .log_fetcher import LogFetcher
from .storage_manager import StorageManager
from .error_handler import RetryExhaustedError
from .monitoring import PipelineMonitor, RequestStatus
from .api_poster import ApiPoster
from .jenkins_extractor import JenkinsExtractor
from .jenkins_log_fetcher import JenkinsLogFetcher
from .jenkins_instance_manager import JenkinsInstanceManager
from .log_error_extractor import LogErrorExtractor
from .token_manager import TokenManager
from .logging_config import (
    setup_logging,
    get_logger,
    set_request_id,
    clear_request_id,
    mask_token
)

# Logging will be configured in init_app()
logger = get_logger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="GitLab Pipeline Log Extractor",
    description="Webhook server for extracting GitLab pipeline logs",
    version="1.0.0"
)


# Custom access logging middleware
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """
    Middleware to log HTTP requests in our custom format. Replaces Uvicorn's default access logger.
    """
    start_time = time.time()

    # Get request ID from context if available
    request_id = getattr(request.state, 'request_id', '-')

    # Process request
    response = await call_next(request)

    # Calculate duration
    duration_ms = int((time.time() - start_time) * 1000)

    # Get access logger (defined in logging_config.py)
    logger = logging.getLogger('access')  # pylint: disable=redefined-outer-name

    # Log in our custom format with context
    logger.info(
        "HTTP request",
        extra={
            'request_id': request_id,
            'method': request.method,
            'path': request.url.path,
            'status': response.status_code,
            'duration_ms': duration_ms,
            'client_ip': request.client.host if request.client else '-'
        }
    )

    return response


# Global configuration and components
config: Optional[Config] = None
log_fetcher: Optional[LogFetcher] = None
storage_manager: Optional[StorageManager] = None
pipeline_extractor: Optional[PipelineExtractor] = None
monitor: Optional[PipelineMonitor] = None
api_poster: Optional[ApiPoster] = None
jenkins_extractor: Optional[JenkinsExtractor] = None
jenkins_log_fetcher: Optional[JenkinsLogFetcher] = None
jenkins_instance_manager: Optional[JenkinsInstanceManager] = None
token_manager: Optional[TokenManager] = None


def init_app():
    """
    Initialize application components.

    This function loads configuration and initializes all required components:
    - Logging configuration
    - Configuration loader
    - Pipeline extractor
    - Log fetcher
    - Storage manager
    - Pipeline monitor

    Should be called before starting the server.
    """
    # Global state is necessary for FastAPI application components
    # These are initialized once at startup and accessed by request handlers
    global config, log_fetcher, storage_manager, pipeline_extractor, monitor, api_poster  # pylint: disable=global-statement
    global jenkins_extractor, jenkins_log_fetcher, jenkins_instance_manager, token_manager  # pylint: disable=global-statement

    try:
        # Load configuration first
        config = ConfigLoader.load()
        ConfigLoader.validate(config)

        # Initialize logging with configuration
        setup_logging(log_dir=config.log_output_dir, log_level=config.log_level)

        logger.info("=" * 70)
        logger.info("GitLab Pipeline Log Extractor - Initializing")
        logger.info("=" * 70)

        logger.info("Configuration .env loaded successfully", extra={'operation': 'config_load'})
        logger.info("GitLab URL: %s", config.gitlab_url)
        logger.info("Webhook receiver Port: %s", config.webhook_port)
        logger.debug("Log Output Directory: %s", config.log_output_dir)
        logger.debug("Log Level: %s", config.log_level)
        logger.debug("Retry Attempts: %s", config.retry_attempts)

        # Mask tokens in logs
        masked_token = mask_token(config.gitlab_token)
        logger.debug("GitLab Token: %s", masked_token)

        # Log BFA configuration
        if config.bfa_host:
            logger.debug("BFA Host: %s", config.bfa_host)
        else:
            logger.debug("BFA Host: Not Set")

        if config.bfa_secret_key:
            masked_bfa_key = mask_token(config.bfa_secret_key)
            logger.debug("BFA Secret Key: %s", masked_bfa_key)
        else:
            logger.debug("BFA Secret Key: Not Set")

        # Initialize components
        logger.info("Initializing 7 components...")

        pipeline_extractor = PipelineExtractor()
        logger.debug("1. Pipeline extractor initialized")

        log_fetcher = LogFetcher(config)
        logger.debug("2. Log fetcher initialized")

        storage_manager = StorageManager(config.log_output_dir)
        logger.debug("3. Storage manager initialized")

        monitor = PipelineMonitor(f"{config.log_output_dir}/monitoring.db")
        logger.debug("4. Pipeline monitor initialized")

        # Initialize BFA JWT token manager based on authentication configuration
        # Scenario 1: BFA_SECRET_KEY set → Generate JWT tokens locally
        # Scenario 2: BFA_HOST set (no SECRET_KEY) → Fetch tokens from BFA server
        # Scenario 3: Neither set → Cannot authenticate (API posting will fail)
        if config.bfa_secret_key:
            # Scenario 1: Local JWT generation
            token_manager = TokenManager(secret_key=config.bfa_secret_key)
            logger.info("5. BFA_SECRET_KEY configured - /api/token not needed as JWT token already available in .env")
            logger.debug("5. TokenManager initialized for local JWT generation")
        elif config.bfa_host:
            # Scenario 2: Will fetch tokens from BFA server
            token_manager = None
            logger.info("5. BFA_SECRET_KEY not set - /api/token endpoint will be used to fetch tokens from BFA server")
        else:
            # Scenario 3: No authentication method available
            token_manager = None
            logger.error("5. Cannot post API to LLM: No BFA_SECRET_KEY or BFA_HOST configured")

        # Initialize API poster if enabled
        if config.api_post_enabled:
            logger.info("6. API Poster endpoint: %s", config.api_post_url)
            logger.info("6. API Poster timeout: %ss", config.api_post_timeout)
            logger.info("6. API Poster retry enabled: %s", config.api_post_retry_enabled)
            logger.info("6. API Poster response save: %s", config.api_post_save_to_file)
            api_poster = ApiPoster(config)
        else:
            logger.info("6. API posting is DISABLED (file storage only)")
            api_poster = None

        # Initialize Jenkins instance manager (supports multiple Jenkins instances)
        try:
            jenkins_instance_manager = JenkinsInstanceManager()
            if jenkins_instance_manager.has_instances():
                logger.info("7. Jenkins instance manager loaded: %d instances configured",
                           len(jenkins_instance_manager.instances))
                for url in jenkins_instance_manager.get_all_urls():
                    logger.debug("7. Jenkins instance: %s", url)
            else:
                logger.debug("7. No jenkins_instances.json found - will use .env configuration")
        except ValueError as e:
            logger.error("7. Failed to load Jenkins instance manager: %s", e)
            jenkins_instance_manager = None

        # Initialize Jenkins components if enabled (fallback to .env config)
        if config.jenkins_enabled:
            logger.info("7. Jenkins integration: ENABLED (fallback mode)")
            logger.debug("7. Jenkins URL: %s", config.jenkins_url)
            logger.debug("7. Jenkins User: %s", config.jenkins_user)
            jenkins_extractor = JenkinsExtractor()
            jenkins_log_fetcher = JenkinsLogFetcher(config)
            logger.debug("7. Jenkins components initialized from .env")
        else:
            logger.info("7. Jenkins integration: DISABLED")
            jenkins_extractor = None
            jenkins_log_fetcher = None

        logger.info("All components initialized successfully")
        logger.info("=" * 70)

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.critical("Failed to initialize application: %s", e, exc_info=True)
        sys.exit(1)


def validate_webhook_secret(_payload: bytes, signature: Optional[str]) -> bool:
    """
    Validate webhook signature using configured secret.

    Args:
        payload (bytes): Raw request body
        signature (Optional[str]): X-Gitlab-Token header value

    Returns: bool: True if validation passes or no secret is configured

    GitLab sends the token in the X-Gitlab-Token header.
    """
    if not config.webhook_secret:
        logger.debug("No webhook secret configured, skipping validation")
        return True

    if not signature:
        logger.warning("Webhook secret is configured but no signature provided")
        return False

    # GitLab uses simple token comparison (not HMAC)
    is_valid = hmac.compare_digest(signature, config.webhook_secret)

    if not is_valid:
        logger.warning("Webhook signature validation failed")

    return is_valid


def should_save_pipeline_logs(pipeline_info: Dict[str, Any]) -> bool:
    """
    Determine if logs should be saved for this pipeline based on filtering config.

    Args:    pipeline_info: Pipeline information dictionary
    Returns: bool: True if logs should be saved
    Checks:
        1. Pipeline status filter (LOG_SAVE_PIPELINE_STATUS)
        2. Project whitelist (LOG_SAVE_PROJECTS)
        3. Project blacklist (LOG_EXCLUDE_PROJECTS)
    """
    pipeline_status = pipeline_info.get('status', '').lower()
    project_id = str(pipeline_info.get('project_id', ''))
    project_name = pipeline_info.get('project_name', 'unknown')

    # Check pipeline status filter
    if 'all' not in config.log_save_pipeline_status:
        if pipeline_status not in config.log_save_pipeline_status:
            logger.info(
                "Pipeline %s from '%s' skipped - status '%s' not in filter %s",
                pipeline_info['pipeline_id'], project_name,
                pipeline_status, config.log_save_pipeline_status,
                extra={
                    'pipeline_id': pipeline_info['pipeline_id'],
                    'project_id': project_id,
                    'project_name': project_name,
                    'status': pipeline_status,
                    'filter': 'pipeline_status'
                }
            )
            return False

    # Check project whitelist
    if config.log_save_projects:
        if project_id not in config.log_save_projects:
            logger.info(
                "Pipeline %s from '%s' (ID: %s) skipped - not in whitelist %s",
                pipeline_info['pipeline_id'], project_name,
                project_id, config.log_save_projects,
                extra={
                    'pipeline_id': pipeline_info['pipeline_id'],
                    'project_id': project_id,
                    'project_name': project_name,
                    'filter': 'project_whitelist'
                }
            )
            return False

    # Check project blacklist (only if whitelist is empty)
    if not config.log_save_projects and config.log_exclude_projects:
        if project_id in config.log_exclude_projects:
            logger.info(
                "Pipeline %s from '%s' (ID: %s) skipped - in blacklist %s",
                pipeline_info['pipeline_id'], project_name,
                project_id, config.log_exclude_projects,
                extra={
                    'pipeline_id': pipeline_info['pipeline_id'],
                    'project_id': project_id,
                    'project_name': project_name,
                    'filter': 'project_blacklist'
                }
            )
            return False

    return True


def should_save_job_log(job_details: Dict[str, Any], pipeline_info: Dict[str, Any]) -> bool:
    """
    Determine if a specific job log should be saved based on filtering config.

    Args:
        job_details: Job information dictionary
        pipeline_info: Pipeline information dictionary

    Returns: bool: True if job log should be saved
    Checks:
        1. Job status filter (LOG_SAVE_JOB_STATUS)
    """
    job_status = job_details.get('status', '').lower()
    job_id = job_details.get('id')
    job_name = job_details.get('name', 'unknown')
    project_name = pipeline_info.get('project_name', 'unknown')

    # Check job status filter
    if 'all' not in config.log_save_job_status:
        if job_status not in config.log_save_job_status:
            logger.debug(
                "Job %s '%s' from '%s' skipped - status '%s' not in filter %s",
                job_id, job_name, project_name,
                job_status, config.log_save_job_status,
                extra={
                    'job_id': job_id,
                    'job_name': job_name,
                    'project_name': project_name,
                    'status': job_status,
                    'filter': 'job_status'
                }
            )
            return False

    return True


@app.get('/health')
async def health_check():
    """
    Health check endpoint.
    Returns: JSON response with server status
    Example Response:
        {
            "status": "healthy",
            "service": "gitlab-log-extractor",
            "version": "1.0.0"
        }
    """
    return {"status": "healthy", "service": "gitlab-log-extractor", "version": "1.0.0"}


@app.post('/api/token')
async def generate_token(request: Request):
    """
    Generate JWT token for API authentication.

    This endpoint generates a JWT token that can be used for API posting
    instead of using a static API_POST_AUTH_TOKEN. The token is signed
    with the BFA_SECRET_KEY.

    Request Body:
        {
            "subject": "<source>_<repository>_<pipeline_id>",
            "expires_in": 60  # Optional, default: 60 minutes
        }

    Returns:
        JSON response with generated token

    Example Request:
        POST /api/token
        {
            "subject": "gitlab_myproject_12345"
        }

    Example Response:
        {
            "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
            "subject": "gitlab_myproject_12345",
            "expires_in": 60
        }

    Error Responses:
        400: Invalid subject format
        503: BFA_SECRET_KEY not configured (token generation disabled)
        500: Token generation failed
    """
    try:
        # Check if token_manager is initialized
        if token_manager is None:
            logger.error("Token generation requested but BFA_SECRET_KEY is not configured", extra={
                'operation': 'token_generation_error'
            })
            raise HTTPException(
                status_code=503,
                detail="JWT token generation is disabled: BFA_SECRET_KEY not configured. "
                       "Please set BFA_SECRET_KEY in your environment configuration."
            )

        # Parse request body
        body = await request.json()
        subject = body.get('subject')
        expires_in = body.get('expires_in', 60)

        if not subject:
            raise HTTPException(status_code=400, detail="Missing required field: subject")

        # Validate expires_in
        if not isinstance(expires_in, int) or expires_in < 1 or expires_in > 1440:
            raise HTTPException(status_code=400, detail="expires_in must be an integer between 1 and 1440 minutes")

        # Generate token
        token = token_manager.generate_token(subject=subject, expires_in_minutes=expires_in)

        logger.info("Generated JWT token for subject: %s", subject, extra={
            'operation': 'token_generation',
            'subject': subject,
            'expires_in': expires_in
        })

        return {"token": token, "subject": subject, "expires_in": expires_in}

    except ValueError as e:
        logger.warning("Invalid token request: %s", str(e), extra={'operation': 'token_generation_error'})
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Token generation failed: %s", str(e), extra={'operation': 'token_generation_error'})
        raise HTTPException(status_code=500, detail="Token generation failed") from e


@app.post('/webhook/gitlab')
async def webhook_gitlab_handler(
    request: Request,
    background_tasks: BackgroundTasks,
    x_gitlab_token: Optional[str] = Header(None, alias="X-Gitlab-Token"),
    x_gitlab_event: Optional[str] = Header(None, alias="X-Gitlab-Event")
):
    """
    GitLab webhook endpoint for receiving pipeline events.

    This endpoint:
    1. Validates the webhook signature (if configured)
    2. Parses the pipeline event
    3. Determines if logs should be fetched
    4. Fetches and stores logs (in background)

    Request Headers:
        - X-Gitlab-Token: Webhook secret token
        - X-Gitlab-Event: Event type (should be "Pipeline Hook")

    Request Body:
        JSON payload from GitLab pipeline webhook

    Returns:
        JSON response with processing status
        - 200: Successfully processed
        - 400: Invalid request
        - 401: Authentication failed
        - 500: Processing error

    Example Response:
        {
            "status": "success",
            "message": "Pipeline logs queued for extraction",
            "pipeline_id": 12345,
            "project_id": 123,
            "request_id": "a1b2c3d4"
        }
    """
    # Generate unique request ID for tracking
    req_id = str(uuid.uuid4())[:8]
    set_request_id(req_id)

    # Start timing
    start_time = time.time()

    # Get client info
    client_host = request.client.host if request.client else "unknown"

    # Log webhook received
    logger.info("Webhook received", extra={'event_type': x_gitlab_event or 'unknown', 'source_ip': client_host})

    # Access log
    logger.info("Webhook request", extra={
        'source_ip': client_host,
        'event_type': x_gitlab_event or 'unknown',
        'path': str(request.url.path)
    })

    try:
        # Get request body
        body = await request.body()
        logger.debug("Request body size: %s bytes", len(body))

        # Validate webhook secret
        if not validate_webhook_secret(body, x_gitlab_token):
            logger.warning("Webhook authentication failed",
                           extra={'source_ip': client_host, 'reason': 'invalid_token'})
            logger.warning("Authentication failed",
                           extra={'source_ip': client_host, 'event_type': x_gitlab_event or 'unknown'})
            raise HTTPException(status_code=401, detail={"status": "error", "message": "Authentication failed"})

        logger.debug("Webhook authentication successful")

        # Check event type
        if x_gitlab_event != 'Pipeline Hook':
            logger.info("Ignoring non-pipeline event", extra={'event_type': x_gitlab_event, 'source_ip': client_host})
            # Track ignored request
            monitor.track_request(status=RequestStatus.IGNORED, event_type=x_gitlab_event, client_ip=client_host)

            duration_ms = int((time.time() - start_time) * 1000)
            logger.info("Request ignored", extra={
                'event_type': x_gitlab_event,
                'source_ip': client_host,
                'duration_ms': duration_ms
            })

            return {
                "status": "ignored",
                "message": f"Event type {x_gitlab_event} is not processed",
                "request_id": req_id
            }

        # Parse JSON payload
        try:
            payload = await request.json()
            if not payload:
                logger.error("Empty or invalid JSON payload")
                raise HTTPException(status_code=400, detail={"status": "error", "message": "Invalid JSON payload"})
            logger.debug("JSON payload parsed successfully")
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("Failed to parse JSON payload", extra={'error_type': type(e).__name__, 'error': str(e)})
            raise HTTPException(status_code=400, detail={"status": "error", "message": "Failed to parse JSON"}) from e

        # Extract pipeline information
        try:
            pipeline_info = pipeline_extractor.extract_pipeline_info(payload)

            # Log request ID tracking info for easy correlation
            logger.info(
                "Request ID %s tracking pipeline %s from project '%s' (ID: %s)",
                req_id, pipeline_info['pipeline_id'],
                pipeline_info['project_name'], pipeline_info['project_id'],
                extra={
                    'pipeline_id': pipeline_info['pipeline_id'],
                    'project_id': pipeline_info['project_id'],
                    'project_name': pipeline_info['project_name']
                }
            )

            logger.info("Pipeline info extracted", extra={
                'pipeline_id': pipeline_info['pipeline_id'],
                'project_id': pipeline_info['project_id'],
                'project_name': pipeline_info['project_name'],
                'status': pipeline_info['status'],
                'pipeline_type': pipeline_info['pipeline_type']
            })

            logger.debug("Pipeline details", extra={
                'pipeline_id': pipeline_info['pipeline_id'],
                'project_id': pipeline_info['project_id'],
                'ref': pipeline_info.get('ref', 'unknown'),
                'source': pipeline_info.get('source', 'unknown'),
                'job_count': len(pipeline_info.get('builds', []))
            })

            # Check if pipeline should be processed
            if not pipeline_extractor.should_process_pipeline(pipeline_info):
                logger.info("Pipeline skipped - not ready for processing", extra={
                    'pipeline_id': pipeline_info['pipeline_id'],
                    'status': pipeline_info['status']
                })

                # Track skipped request
                monitor.track_request(
                    pipeline_info=pipeline_info,
                    status=RequestStatus.SKIPPED,
                    event_type=x_gitlab_event,
                    client_ip=client_host
                )

                duration_ms = int((time.time() - start_time) * 1000)
                logger.info("Pipeline skipped", extra={
                    'pipeline_id': pipeline_info['pipeline_id'],
                    'project_id': pipeline_info['project_id'],
                    'status': pipeline_info['status'],
                    'duration_ms': duration_ms
                })

                return {
                    "status": "skipped",
                    "message": "Pipeline not ready for processing",
                    "pipeline_id": pipeline_info['pipeline_id'],
                    "status_reason": pipeline_info['status'],
                    "request_id": req_id
                }

            # Track queued request
            db_request_id = monitor.track_request(
                pipeline_info=pipeline_info,
                status=RequestStatus.QUEUED,
                event_type=x_gitlab_event,
                client_ip=client_host
            )

            logger.info("Pipeline queued for processing", extra={
                'pipeline_id': pipeline_info['pipeline_id'],
                'project_id': pipeline_info['project_id'],
                'job_count': len(pipeline_info.get('builds', []))
            })

            # Process pipeline in background to avoid blocking webhook response
            background_tasks.add_task(process_pipeline_event, pipeline_info, db_request_id, req_id)

            # Log response time
            duration_ms = int((time.time() - start_time) * 1000)

            logger.info("Pipeline queued", extra={
                'pipeline_id': pipeline_info['pipeline_id'],
                'project_id': pipeline_info['project_id'],
                'event_type': x_gitlab_event,
                'source_ip': client_host,
                'duration_ms': duration_ms
            })

            logger.info("Webhook processed", extra={
                'pipeline_id': pipeline_info['pipeline_id'],
                'duration_ms': duration_ms,
                'operation': 'webhook_handler'
            })

            return {
                "status": "success",
                "message": "Pipeline logs queued for extraction",
                "pipeline_id": pipeline_info['pipeline_id'],
                "project_id": pipeline_info['project_id'],
                "request_id": req_id,
                "db_request_id": db_request_id
            }

        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("Failed to extract pipeline info",
                         extra={'error_type': type(e).__name__, 'error': str(e)},
                         exc_info=True)
            raise HTTPException(
                status_code=500,
                detail={"status": "error", "message": f"Failed to extract pipeline info: {str(e)}"}
            ) from e

    except HTTPException:
        # Re-raise HTTP exceptions
        duration_ms = int((time.time() - start_time) * 1000)
        logger.debug("Request failed with HTTP exception", extra={'duration_ms': duration_ms})
        raise
    except Exception as e:  # pylint: disable=broad-exception-caught
        duration_ms = int((time.time() - start_time) * 1000)
        logger.error("Failed to process webhook", extra={
            'error_type': type(e).__name__,
            'error': str(e),
            'duration_ms': duration_ms
        }, exc_info=True)

        logger.error("Webhook processing failed", extra={
            'source_ip': client_host,
            'event_type': x_gitlab_event or 'unknown',
            'duration_ms': duration_ms,
            'error_type': type(e).__name__
        })

        raise HTTPException(
            status_code=500,
            detail={"status": "error", "message": f"Processing failed: {str(e)}"}
        ) from e
    finally:
        # Clear request ID from context
        clear_request_id()


@app.post('/webhook/jenkins')
async def webhook_jenkins_handler(
    request: Request,
    background_tasks: BackgroundTasks,
    x_jenkins_token: Optional[str] = Header(None, alias="X-Jenkins-Token")
):
    """
    Jenkins webhook endpoint for receiving build completion events.

    This endpoint:
    1. Validates the webhook secret (if configured)
    2. Extracts build information from payload
    3. Fetches console logs and Blue Ocean stage data
    4. Posts to API (in background)

    Request Headers:
        - X-Jenkins-Token: Webhook secret token (optional)

    Request Body:
        JSON payload from Jenkins (custom format):
        {
            "job_name": "my-pipeline",
            "build_number": 123,
            "build_url": "https://jenkins.example.com/job/my-pipeline/123/",
            "status": "FAILURE",
            "jenkins_url": "https://jenkins.example.com"
        }

    Returns:
        JSON response with processing status
        - 200: Successfully queued for processing
        - 400: Invalid request
        - 401: Authentication failed
        - 503: Jenkins integration not enabled
    """
    # Generate unique request ID
    req_id = str(uuid.uuid4())[:8]
    set_request_id(req_id)

    start_time = time.time()
    client_host = request.client.host if request.client else "unknown"

    logger.info("Jenkins webhook received", extra={'source_ip': client_host, 'source': 'jenkins'})

    try:
        # Check if Jenkins is enabled
        if not config.jenkins_enabled or not jenkins_extractor or not jenkins_log_fetcher:
            logger.warning("Jenkins webhook received but Jenkins integration is disabled")
            raise HTTPException(
                status_code=503,
                detail={"status": "error", "message": "Jenkins integration is not enabled"}
            )

        # Get request body
        body = await request.body()
        logger.debug("Request body size: %s bytes", len(body))

        # Validate webhook secret if configured
        if config.jenkins_webhook_secret:
            if not x_jenkins_token:
                logger.warning("Jenkins webhook secret configured but no token provided")
                raise HTTPException(status_code=401, detail={"status": "error", "message": "Authentication required"})
            if not hmac.compare_digest(x_jenkins_token, config.jenkins_webhook_secret):
                logger.warning("Jenkins webhook authentication failed")
                raise HTTPException(status_code=401, detail={"status": "error", "message": "Authentication failed"})

        # Parse JSON payload
        try:
            payload = await request.json()
            if not payload:
                raise HTTPException(status_code=400, detail={"status": "error", "message": "Invalid JSON payload"})
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("Failed to parse JSON payload: %s", e)
            raise HTTPException(status_code=400, detail={"status": "error", "message": "Failed to parse JSON"}) from e

        # Extract build information
        try:
            build_info = jenkins_extractor.extract_webhook_data(payload)
            job_name = build_info['job_name']
            build_number = build_info['build_number']
            status = build_info['status']

            logger.info(
                "Jenkins build extracted: %s #%s - %s",
                job_name, build_number, status,
                extra={'job_name': job_name, 'build_number': build_number, 'status': status, 'source': 'jenkins'}
            )

            # Track request in monitoring
            db_request_id = monitor.track_request(
                pipeline_info={'pipeline_id': build_number, 'project_name': job_name},
                status=RequestStatus.QUEUED,
                event_type='Jenkins Build',
                client_ip=client_host
            )

            # Queue background processing
            background_tasks.add_task(process_jenkins_build, build_info, db_request_id, req_id)

            duration_ms = int((time.time() - start_time) * 1000)
            logger.info(
                "Jenkins build queued for processing: %s #%s",
                job_name, build_number,
                extra={'job_name': job_name, 'build_number': build_number, 'duration_ms': duration_ms}
            )

            return {
                "status": "success",
                "message": "Jenkins build logs queued for extraction",
                "job_name": job_name,
                "build_number": build_number,
                "request_id": req_id,
                "db_request_id": db_request_id
            }

        except ValueError as e:
            logger.error("Failed to extract build info: %s", e)
            raise HTTPException(
                status_code=400,
                detail={"status": "error", "message": f"Invalid payload: {str(e)}"}
            ) from e

    except HTTPException:
        raise
    except Exception as e:  # pylint: disable=broad-exception-caught
        duration_ms = int((time.time() - start_time) * 1000)
        logger.error("Failed to process Jenkins webhook: %s", e, extra={
            'error_type': type(e).__name__,
            'duration_ms': duration_ms
        }, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"status": "error", "message": f"Processing failed: {str(e)}"}
        ) from e
    finally:
        clear_request_id()


def process_jenkins_build(build_info: Dict[str, Any], db_request_id: int, req_id: str):
    """
    Process a Jenkins build: fetch logs and post to API.

    This function:
    1. Determines Jenkins instance credentials from webhook payload
    2. Fetches console log from Jenkins
    3. Fetches Blue Ocean stage information (if available)
    4. Parses logs to extract parallel blocks
    5. Posts structured data to API

    Args:
        build_info (Dict[str, Any]): Extracted build information (must include jenkins_url)
        db_request_id (int): Monitoring database request ID
        req_id (str): Request correlation ID
    """
    set_request_id(req_id)

    job_name = build_info['job_name']
    build_number = build_info['build_number']
    status = build_info['status']
    jenkins_url = build_info.get('jenkins_url')

    logger.info("Processing Jenkins build: %s #%s from %s", job_name, build_number, jenkins_url, extra={
        'job_name': job_name,
        'build_number': build_number,
        'jenkins_url': jenkins_url,
        'status': status,
        'db_request_id': db_request_id
    })

    start_time = time.time()
    monitor.update_request(db_request_id, RequestStatus.PROCESSING)

    # Get Jenkins instance credentials
    fetcher = None
    if jenkins_url and jenkins_instance_manager:
        # Try to get credentials from jenkins_instances.json
        instance = jenkins_instance_manager.get_instance(jenkins_url)
        if instance:
            logger.info("Using credentials for Jenkins instance: %s", jenkins_url)
            fetcher = JenkinsLogFetcher(
                jenkins_url=instance.jenkins_url,
                jenkins_user=instance.jenkins_user,
                jenkins_api_token=instance.jenkins_api_token,
                retry_attempts=config.retry_attempts,
                retry_delay=config.retry_delay
            )
        else:
            logger.warning("No configuration found for Jenkins URL: %s", jenkins_url)

    # Fall back to global jenkins_log_fetcher if no specific instance found
    if not fetcher and jenkins_log_fetcher:
        logger.debug("Using default Jenkins configuration from .env")
        fetcher = jenkins_log_fetcher
    elif not fetcher:
        logger.error("No Jenkins configuration available for %s", jenkins_url)
        monitor.update_request(db_request_id, RequestStatus.FAILED)
        return

    try:
        # Fetch build metadata
        try:
            metadata = fetcher.fetch_build_info(job_name, build_number)
            build_info['duration_ms'] = metadata.get('duration', 0)
            build_info['timestamp'] = metadata.get('timestamp')
            build_info['result'] = metadata.get('result', status)

            # Extract pipeline parameters from metadata
            parameters = {}
            for action in metadata.get('actions', []):
                if action.get('_class') == 'hudson.model.ParametersAction':
                    for param in action.get('parameters', []):
                        parameters[param.get('name')] = param.get('value')

            build_info['parameters'] = parameters
            logger.debug("Extracted %d parameters from build metadata", len(parameters))
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning("Failed to fetch build metadata: %s", e)
            build_info['parameters'] = {}

        # Fetch console log
        console_log = fetcher.fetch_console_log(job_name, build_number)

        # Fetch Blue Ocean stages (if available)
        blue_ocean_stages = fetcher.fetch_stages(job_name, build_number)

        # Parse console log to extract stages
        stages = jenkins_extractor.parse_console_log(console_log, blue_ocean_stages)
        logger.info("Parsed %s stages from build", len(stages))

        # Filter to only failed stages
        failed_stages = [s for s in stages if s.get('status') in ['FAILED', 'FAILURE']]
        logger.info("Found %s failed stage(s)", len(failed_stages))

        if not failed_stages:
            logger.info("No failed stages to process")
            monitor.update_request(db_request_id, RequestStatus.COMPLETED)
            return

        # Extract error context from failed stages
        error_extractor = LogErrorExtractor(
            lines_before=config.error_context_lines_before,
            lines_after=config.error_context_lines_after
        )

        for stage in failed_stages:
            stage_name = stage.get('stage_name')
            stage_id = stage.get('stage_id')

            # Try to fetch individual stage log from Blue Ocean API
            stage_log = ''
            if stage_id:
                try:
                    stage_log = fetcher.fetch_stage_log(job_name, build_number, stage_id)
                except Exception as e:  # pylint: disable=broad-exception-caught
                    logger.debug("Could not fetch stage log from Blue Ocean: %s", e)

            # Fallback: use log_content from parsed console log if available
            if not stage_log:
                stage_log = stage.get('log_content', '')

            # If stage has parallel blocks, combine their logs
            if not stage_log and stage.get('is_parallel'):
                parallel_blocks = stage.get('parallel_blocks', [])
                stage_log = '\n'.join([
                    f"=== {block.get('block_name', 'Unknown')} ===\n{block.get('log_content', '')}"
                    for block in parallel_blocks
                ])

            # Extract error sections with context
            if stage_log:
                error_sections = error_extractor.extract_error_sections(stage_log)
                if error_sections:
                    # Replace full log with error-only context
                    stage['log_content'] = error_sections[0]
                    logger.info(
                        "Extracted error context for stage '%s': %s bytes",
                        stage_name,
                        len(error_sections[0])
                    )
                else:
                    # No errors found, send full log
                    stage['log_content'] = stage_log
                    logger.warning(
                        "No error patterns found in failed stage '%s', sending full log",
                        stage_name
                    )
            else:
                logger.warning(
                    "Stage '%s' marked as FAILED but has no log content",
                    stage_name
                )

        # Post to API if enabled
        if config.api_post_enabled and api_poster:
            api_start = time.time()

            try:
                # Format Jenkins-specific payload with only failed stages
                jenkins_payload = {
                    'source': 'jenkins',
                    'job_name': job_name,
                    'build_number': build_number,
                    'build_url': build_info.get('build_url', ''),
                    'status': status,
                    'duration_ms': build_info.get('duration_ms', 0),
                    'timestamp': build_info.get('timestamp', ''),
                    'parameters': build_info.get('parameters', {}),  # Pipeline parameters
                    'stages': failed_stages  # Only send failed stages with error context
                }

                api_success = api_poster.post_jenkins_logs(jenkins_payload)
                api_duration_ms = int((time.time() - api_start) * 1000)

                if api_success:
                    logger.info("Successfully posted Jenkins build to API", extra={
                        'job_name': job_name,
                        'build_number': build_number,
                        'api_duration_ms': api_duration_ms,
                        'failed_stages': len(failed_stages)
                    })
                else:
                    logger.warning("Failed to post Jenkins build to API", extra={
                        'job_name': job_name,
                        'build_number': build_number
                    })
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.error("Error posting to API: %s", e, exc_info=True)

        # Update monitoring status
        processing_time = time.time() - start_time
        monitor.update_request(
            request_id=db_request_id,
            status=RequestStatus.COMPLETED,
            processing_time=processing_time,
            success_count=len(failed_stages),
            error_count=0
        )

        logger.info("Jenkins build processing completed: %s #%s | %s failed stages",
                   job_name, build_number, len(failed_stages), extra={
            'job_name': job_name,
            'build_number': build_number,
            'processing_time_ms': int(processing_time * 1000),
            'failed_stages': len(failed_stages)
        })

    except Exception as e:  # pylint: disable=broad-exception-caught
        processing_time = time.time() - start_time
        logger.error("Failed to process Jenkins build: %s", e, extra={
            'job_name': job_name,
            'build_number': build_number,
            'error_type': type(e).__name__
        }, exc_info=True)

        monitor.update_request(
            request_id=db_request_id,
            status=RequestStatus.FAILED,
            processing_time=processing_time,
            error_message=str(e)
        )
    finally:
        clear_request_id()


def process_pipeline_event(pipeline_info: Dict[str, Any], db_request_id: int, req_id: str):  # pylint: disable=too-many-branches  # noqa: C901
    """
    Process a pipeline event: fetch and store logs.

    This function is the main processing logic that:
    1. Fetches all jobs for the pipeline
    2. Retrieves logs for each job
    3. Stores logs with metadata
    4. Updates monitoring status

    Runs in a background task to avoid blocking webhook responses.

    Args:
        pipeline_info (Dict[str, Any]): Extracted pipeline information
        db_request_id (int): Monitoring database request ID for tracking
        req_id (str): Request correlation ID for logging

    Error Handling:
        - Logs errors but continues processing remaining jobs
        - Uses retry logic for transient failures
        - Updates monitoring status on completion/failure
    """
    # Set request ID in context for all logs in this background task
    set_request_id(req_id)

    pipeline_id = pipeline_info['pipeline_id']
    project_id = pipeline_info['project_id']
    project_name = pipeline_info.get('project_name', 'unknown')

    logger.info("Starting pipeline log extraction for '%s'", project_name, extra={
        'pipeline_id': pipeline_id,
        'project_id': project_id,
        'project_name': project_name,
        'db_request_id': db_request_id
    })

    start_time = time.time()

    # Update status to processing
    monitor.update_request(db_request_id, RequestStatus.PROCESSING)
    logger.debug("Request status updated to PROCESSING")

    try:
        # Check if logs should be saved based on filtering config
        save_logs = should_save_pipeline_logs(pipeline_info)

        # Save metadata (always if configured, or if logs will be saved)
        if save_logs or config.log_save_metadata_always:
            logger.debug("Saving pipeline metadata for '%s'", project_name, extra={
                'pipeline_id': pipeline_id,
                'project_id': project_id,
                'project_name': project_name
            })

            storage_manager.save_pipeline_metadata(
                project_id=project_id,
                project_name=project_name,
                pipeline_id=pipeline_id,
                pipeline_data={
                    "status": pipeline_info['status'],
                    "ref": pipeline_info['ref'],
                    "sha": pipeline_info['sha'],
                    "source": pipeline_info['source'],
                    "pipeline_type": pipeline_info['pipeline_type'],
                    "created_at": pipeline_info['created_at'],
                    "finished_at": pipeline_info['finished_at'],
                    "duration": pipeline_info['duration'],
                    "user": pipeline_info['user'],
                    "stages": pipeline_info['stages']
                }
            )
            logger.debug("Pipeline metadata saved successfully")

        # Skip log fetching if filtered out
        if not save_logs:
            logger.info(
                "Pipeline %s from '%s' - logs filtered, only metadata saved",
                pipeline_id, project_name,
                extra={
                    'pipeline_id': pipeline_id,
                    'project_id': project_id,
                    'project_name': project_name,
                    'filtered': True
                }
            )
            # Mark as completed with no jobs processed
            monitor.update_request(
                request_id=db_request_id,
                status=RequestStatus.COMPLETED,
                processing_time=time.time() - start_time,
                success_count=0,
                error_count=0
            )
            return

        # Fetch job list first (lightweight API call)
        logger.info("Fetching job list for pipeline in '%s'", project_name, extra={
            'pipeline_id': pipeline_id,
            'project_id': project_id,
            'project_name': project_name
        })

        fetch_start = time.time()
        all_jobs = log_fetcher.fetch_pipeline_jobs(project_id, pipeline_id)

        # Filter jobs BEFORE fetching logs (optimization)
        jobs_to_fetch = []
        skipped_before_fetch = 0

        for job in all_jobs:
            if should_save_job_log(job, pipeline_info):
                jobs_to_fetch.append(job)
            else:
                skipped_before_fetch += 1

        logger.info(
            "Job filtering: %s jobs to fetch, %s jobs skipped by filter",
            len(jobs_to_fetch), skipped_before_fetch, extra={
                'pipeline_id': pipeline_id,
                'jobs_to_fetch': len(jobs_to_fetch),
                'jobs_skipped': skipped_before_fetch,
                'total_jobs': len(all_jobs)
            }
        )

        # Now fetch logs only for filtered jobs
        all_logs = {}
        for job in jobs_to_fetch:
            job_id = job['id']
            try:
                log_content = log_fetcher.fetch_job_log(project_id, job_id)
                all_logs[job_id] = {'details': job, 'log': log_content}
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.error("Failed to fetch log for job %s: %s", job_id, str(e))
                all_logs[job_id] = {'details': job, 'log': f"[Error fetching log: {str(e)}]"}

        fetch_duration_ms = int((time.time() - fetch_start) * 1000)

        job_count = len(all_logs)
        logger.info("Pipeline logs fetched", extra={
            'pipeline_id': pipeline_id,
            'job_count': job_count,
            'duration_ms': fetch_duration_ms
        })

        # Process logs based on API posting configuration
        success_count = 0
        error_count = 0
        skipped_count = 0
        save_start = time.time()
        api_post_success = False

        # Try API posting if enabled
        if config.api_post_enabled and api_poster:
            logger.info("Posting pipeline logs to API for '%s'", project_name)
            api_start = time.time()

            try:
                api_post_success = api_poster.post_pipeline_logs(pipeline_info, all_logs)
                api_duration_ms = int((time.time() - api_start) * 1000)

                if api_post_success:
                    logger.info(
                        "Successfully posted pipeline %s logs to API",
                        pipeline_id,
                        extra={
                            'pipeline_id': pipeline_id,
                            'project_id': project_id,
                            'project_name': project_name,
                            'api_duration_ms': api_duration_ms,
                            'job_count': job_count
                        }
                    )
                else:
                    logger.warning(
                        "Failed to post pipeline %s logs to API",
                        pipeline_id,
                        extra={
                            'pipeline_id': pipeline_id,
                            'project_id': project_id,
                            'project_name': project_name
                        }
                    )
            except Exception as e:  # pylint: disable=broad-exception-caught
                api_duration_ms = int((time.time() - api_start) * 1000)
                logger.error(
                    "Unexpected error posting to API: %s",
                    e,
                    extra={
                        'pipeline_id': pipeline_id,
                        'project_id': project_id,
                        'error_type': type(e).__name__
                    },
                    exc_info=True
                )

        # Determine if we should save to files
        should_save_to_files = False

        if not config.api_post_enabled:
            # API posting disabled, always save to files
            should_save_to_files = True
            logger.debug("Saving to files (API posting disabled)")
        elif config.api_post_save_to_file:
            # Dual mode: save to files regardless of API result
            should_save_to_files = True
            logger.debug("Saving to files (dual mode enabled)")
        elif not api_post_success:
            # API posting failed, fallback to file storage
            should_save_to_files = True
            logger.info("Saving to files as fallback (API posting failed)")
        else:
            # API posting succeeded and save_to_file is false
            should_save_to_files = False
            logger.info("Skipping file storage (API posting succeeded, file storage disabled)")

        # Save to files if needed
        if should_save_to_files:
            logger.debug("Starting file storage")

            for job_id, job_data in all_logs.items():
                try:
                    job_details = job_data['details']
                    log_content = job_data['log']
                    log_size = len(log_content)

                    # Note: Jobs are already filtered before fetching, so all jobs in all_logs should be saved
                    logger.debug("Saving job log to file", extra={
                        'pipeline_id': pipeline_id,
                        'job_id': job_id,
                        'job_name': job_details['name'],
                        'log_size_bytes': log_size
                    })

                    storage_manager.save_log(
                        project_id=project_id,
                        project_name=project_name,
                        pipeline_id=pipeline_id,
                        job_id=job_id,
                        job_name=job_details['name'],
                        log_content=log_content,
                        job_details={
                            "status": job_details.get('status'),
                            "stage": job_details.get('stage'),
                            "created_at": job_details.get('created_at'),
                            "started_at": job_details.get('started_at'),
                            "finished_at": job_details.get('finished_at'),
                            "duration": job_details.get('duration'),
                            "ref": job_details.get('ref')
                        }
                    )
                    success_count += 1
                    logger.debug("Job log saved to file successfully", extra={
                        'job_id': job_id,
                        'job_name': job_details['name']
                    })

                except Exception as e:  # pylint: disable=broad-exception-caught
                    error_count += 1
                    logger.error("Failed to save job log to file", extra={
                        'pipeline_id': pipeline_id,
                        'job_id': job_id,
                        'error_type': type(e).__name__,
                        'error': str(e)
                    })
        else:
            # API posting succeeded, count all jobs as successful
            success_count = job_count

        save_duration_ms = int((time.time() - save_start) * 1000)
        total_duration_ms = int((time.time() - start_time) * 1000)

        logger.info("Pipeline processing completed for '%s'", project_name, extra={
            'pipeline_id': pipeline_id,
            'project_id': project_id,
            'project_name': project_name,
            'success_count': success_count,
            'error_count': error_count,
            'skipped_count': skipped_count,
            'total_jobs': job_count
        })

        if skipped_count > 0:
            logger.info("Skipped %s job(s) due to filtering", skipped_count, extra={
                'pipeline_id': pipeline_id,
                'project_name': project_name,
                'skipped_count': skipped_count
            })

        # Log summary
        summary = pipeline_extractor.get_pipeline_summary(pipeline_info)
        logger.debug("Pipeline summary: %s", summary)

        # Performance metrics
        logger.info("Pipeline processing metrics", extra={
            'pipeline_id': pipeline_id,
            'project_id': project_id,
            'project_name': project_name,
            'total_duration_ms': total_duration_ms,
            'fetch_duration_ms': fetch_duration_ms,
            'save_duration_ms': save_duration_ms,
            'job_count': job_count,
            'success_count': success_count,
            'error_count': error_count,
            'skipped_count': skipped_count,
            'operation': 'pipeline_processing'
        })

        # Update monitoring with success
        processing_time = total_duration_ms / 1000.0
        monitor.update_request(
            request_id=db_request_id,
            status=RequestStatus.COMPLETED,
            processing_time=processing_time,
            success_count=success_count,
            error_count=error_count
        )
        logger.debug("Monitoring status updated to COMPLETED")

    except RetryExhaustedError as e:
        total_duration_ms = int((time.time() - start_time) * 1000)
        logger.error("Pipeline processing failed after retries", extra={
            'pipeline_id': pipeline_id,
            'project_id': project_id,
            'error_type': 'RetryExhaustedError',
            'error': str(e),
            'duration_ms': total_duration_ms
        })

        # Update monitoring with failure
        processing_time = total_duration_ms / 1000.0
        monitor.update_request(
            request_id=db_request_id,
            status=RequestStatus.FAILED,
            processing_time=processing_time,
            error_message=str(e)
        )

        logger.info("Pipeline processing failed", extra={
            'pipeline_id': pipeline_id,
            'project_id': project_id,
            'duration_ms': total_duration_ms,
            'error_type': 'RetryExhaustedError',
            'operation': 'pipeline_processing'
        })

    except Exception as e:  # pylint: disable=broad-exception-caught
        total_duration_ms = int((time.time() - start_time) * 1000)
        logger.error("Unexpected error processing pipeline", extra={
            'pipeline_id': pipeline_id,
            'project_id': project_id,
            'error_type': type(e).__name__,
            'error': str(e),
            'duration_ms': total_duration_ms
        }, exc_info=True)

        # Update monitoring with failure
        processing_time = total_duration_ms / 1000.0
        monitor.update_request(
            request_id=db_request_id,
            status=RequestStatus.FAILED,
            processing_time=processing_time,
            error_message=str(e)
        )

        logger.info("Pipeline processing failed", extra={
            'pipeline_id': pipeline_id,
            'project_id': project_id,
            'duration_ms': total_duration_ms,
            'error_type': type(e).__name__,
            'operation': 'pipeline_processing'
        })
    finally:
        # Clear request ID from context
        clear_request_id()


@app.get('/stats')
async def stats():
    """
    Get storage statistics.
    Returns: JSON response with storage statistics
    Example Response:
        {
            "total_projects": 5,
            "total_pipelines": 23,
            "total_jobs": 156,
            "total_size_mb": 43.56
        }
    """
    try:
        storage_stats = storage_manager.get_storage_stats()
        return storage_stats
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Failed to get storage stats: %s", e)
        raise HTTPException(status_code=500, detail={"status": "error", "message": str(e)}) from e


@app.get('/monitor/summary')
async def monitor_summary(hours: int = Query(24, description="Number of hours to include")):
    """
    Get monitoring summary statistics.
    Args:    hours (int): Number of hours to include in summary (default: 24)
    Returns: JSON response with monitoring statistics
    Example Response:
        {
            "time_period_hours": 24,
            "total_requests": 150,
            "by_status": {
                "completed": 120,
                "failed": 10,
                "skipped": 15,
                "processing": 5
            },
            "by_type": {
                "main": 100,
                "child": 30,
                "merge_request": 20
            },
            "success_rate": 92.3,
            "avg_processing_time_seconds": 12.5,
            "total_jobs_processed": 450
        }
    """
    try:
        summary = monitor.get_summary(hours=hours)
        return summary
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Failed to get monitor summary: %s", e)
        raise HTTPException(status_code=500, detail={"status": "error", "message": str(e)}) from e


@app.get('/monitor/recent')
async def monitor_recent(limit: int = Query(50, description="Maximum number of requests")):
    """
    Get recent pipeline requests.
    Args:    limit (int): Maximum number of requests to return (default: 50)
    Returns: JSON response with recent requests
    """
    try:
        requests = monitor.get_recent_requests(limit=limit)
        return {"requests": requests, "count": len(requests)}
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Failed to get recent requests: %s", e)
        raise HTTPException(status_code=500, detail={"status": "error", "message": str(e)}) from e


@app.get('/monitor/pipeline/{pipeline_id}')
async def monitor_pipeline(pipeline_id: int):
    """
    Get all requests for a specific pipeline.
    Args:    pipeline_id (int): Pipeline ID
    Returns: JSON response with pipeline requests
    """
    try:
        requests = monitor.get_pipeline_requests(pipeline_id)
        return {"pipeline_id": pipeline_id, "requests": requests, "count": len(requests)}
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Failed to get pipeline requests: %s", e)
        raise HTTPException(status_code=500, detail={"status": "error", "message": str(e)}) from e


@app.get('/monitor/export/csv')
async def monitor_export_csv(
    hours: Optional[int] = Query(None, description="Only export last N hours (None = all)")
):
    """
    Export monitoring data to CSV file.
    Args:    hours (Optional[int]): Only export requests from last N hours (None = all)
    Returns: CSV file download
    """
    try:
        # Create temporary CSV file
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.csv') as temp_file:
            temp_path = temp_file.name

        # Export to CSV
        monitor.export_to_csv(temp_path, hours=hours)

        # Return file
        return FileResponse(
            path=temp_path,
            media_type='text/csv',
            filename=f"pipeline_monitoring_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
        )
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Failed to export CSV: %s", e)
        raise HTTPException(status_code=500, detail={"status": "error", "message": str(e)}) from e


@app.on_event("startup")
async def startup_event():
    """FastAPI startup event handler. Initializes application components when the server starts"""
    init_app()


@app.on_event("shutdown")
async def shutdown_event():
    """FastAPI shutdown event handler. Performs cleanup when the server stops"""
    if log_fetcher:
        log_fetcher.close()
    if monitor:
        monitor.close()
    logger.info("Application shutdown complete")


def main():
    """Main entry point for the application. Initializes the application and starts the FastAPI server with uvicorn."""
    logger.info("=" * 60)
    logger.info("GitLab Pipeline Log Extraction System")
    logger.info("=" * 60)

    # Initialize application (will also be called by startup event)
    init_app()

    # Start FastAPI server with uvicorn
    logger.info("Starting webhook server on port %s...", config.webhook_port)
    logger.info("Press Ctrl+C to stop")

    try:
        uvicorn.run(
            app,
            host='0.0.0.0',
            port=config.webhook_port,
            log_level=config.log_level.lower(),
            access_log=False  # Disable Uvicorn's access logger, use our middleware
        )
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Server error: %s", e, exc_info=True)


if __name__ == "__main__":
    main()
