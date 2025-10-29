"""
Webhook Listener Module

This is the main application entry point. It runs a FastAPI web server that listens
for GitLab webhook events, processes them, fetches logs, and stores them.

Data Flow:
    GitLab → POST /webhook → validate_webhook() → process_pipeline_event() →
    PipelineExtractor → LogFetcher → StorageManager → Disk Storage

Module Dependencies:
    - fastapi: Web server framework
    - uvicorn: ASGI server
    - logging: Application logging
    - config_loader: Configuration management
    - pipeline_extractor: Event parsing
    - log_fetcher: GitLab API interaction
    - storage_manager: Log persistence
    - error_handler: Error handling and retries

Server Architecture:
    - FastAPI application listening on configured port (default: 8000)
    - Single webhook endpoint: POST /webhook
    - Optional webhook secret validation
    - Background task processing
"""

import logging
import sys
import hmac
import uuid
import time
from typing import Dict, Any, Optional
from datetime import datetime
from fastapi import FastAPI, Request, Header, BackgroundTasks, HTTPException, Query
from fastapi.responses import JSONResponse, FileResponse
import uvicorn

from .config_loader import ConfigLoader, Config
from .pipeline_extractor import PipelineExtractor
from .log_fetcher import LogFetcher
from .storage_manager import StorageManager
from .error_handler import RetryExhaustedError
from .monitoring import PipelineMonitor, RequestStatus
from .logging_config import (
    setup_logging,
    get_logger,
    get_access_logger,
    get_performance_logger,
    set_request_id,
    clear_request_id,
    mask_token
)

# Logging will be configured in init_app()
logger = get_logger(__name__)
access_logger = get_access_logger()
perf_logger = get_performance_logger()

# Initialize FastAPI app
app = FastAPI(
    title="GitLab Pipeline Log Extractor",
    description="Webhook server for extracting GitLab pipeline logs",
    version="1.0.0"
)

# Global configuration and components
config: Optional[Config] = None
log_fetcher: Optional[LogFetcher] = None
storage_manager: Optional[StorageManager] = None
pipeline_extractor: Optional[PipelineExtractor] = None
monitor: Optional[PipelineMonitor] = None


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
    global config, log_fetcher, storage_manager, pipeline_extractor, monitor

    try:
        # Load configuration first
        config = ConfigLoader.load()
        ConfigLoader.validate(config)

        # Initialize logging with configuration
        setup_logging(log_dir=config.log_output_dir, log_level=config.log_level)

        logger.info("=" * 70)
        logger.info("GitLab Pipeline Log Extractor - Initializing")
        logger.info("=" * 70)

        logger.info("Configuration loaded successfully", extra={
            'operation': 'config_load'
        })
        logger.debug(f"GitLab URL: {config.gitlab_url}")
        logger.debug(f"Webhook Port: {config.webhook_port}")
        logger.debug(f"Log Output Directory: {config.log_output_dir}")
        logger.debug(f"Log Level: {config.log_level}")
        logger.debug(f"Retry Attempts: {config.retry_attempts}")

        # Mask token in logs
        masked_token = mask_token(config.gitlab_token)
        logger.debug(f"GitLab Token: {masked_token}")

        # Initialize components
        logger.info("Initializing components...")

        pipeline_extractor = PipelineExtractor()
        logger.debug("Pipeline extractor initialized")

        log_fetcher = LogFetcher(config)
        logger.debug("Log fetcher initialized")

        storage_manager = StorageManager(config.log_output_dir)
        logger.debug("Storage manager initialized")

        monitor = PipelineMonitor(f"{config.log_output_dir}/monitoring.db")
        logger.debug("Pipeline monitor initialized")

        logger.info("All components initialized successfully")
        logger.info("=" * 70)

    except Exception as e:
        logger.critical(f"Failed to initialize application: {e}", exc_info=True)
        sys.exit(1)


def validate_webhook_secret(payload: bytes, signature: Optional[str]) -> bool:
    """
    Validate webhook signature using configured secret.

    Args:
        payload (bytes): Raw request body
        signature (Optional[str]): X-Gitlab-Token header value

    Returns:
        bool: True if validation passes or no secret is configured

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


@app.get('/health')
async def health_check():
    """
    Health check endpoint.

    Returns:
        JSON response with server status

    Example Response:
        {
            "status": "healthy",
            "service": "gitlab-log-extractor",
            "version": "1.0.0"
        }
    """
    return {
        "status": "healthy",
        "service": "gitlab-log-extractor",
        "version": "1.0.0"
    }


@app.post('/webhook')
async def webhook_handler(
    request: Request,
    background_tasks: BackgroundTasks,
    x_gitlab_token: Optional[str] = Header(None, alias="X-Gitlab-Token"),
    x_gitlab_event: Optional[str] = Header(None, alias="X-Gitlab-Event")
):
    """
    Main webhook endpoint for receiving GitLab events.

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
            "project_id": 123
        }
    """
    client_host = request.client.host if request.client else "unknown"
    logger.info(f"Received webhook request from {client_host}")

    # Get request body
    body = await request.body()

    # Validate webhook secret
    if not validate_webhook_secret(body, x_gitlab_token):
        logger.warning("Webhook authentication failed")
        raise HTTPException(
            status_code=401,
            detail={"status": "error", "message": "Authentication failed"}
        )

    # Check event type
    if x_gitlab_event != 'Pipeline Hook':
        logger.info(f"Ignoring non-pipeline event: {x_gitlab_event}")
        # Track ignored request
        monitor.track_request(
            status=RequestStatus.IGNORED,
            event_type=x_gitlab_event,
            client_ip=client_host
        )
        return {
            "status": "ignored",
            "message": f"Event type {x_gitlab_event} is not processed"
        }

    # Parse JSON payload
    try:
        payload = await request.json()
        if not payload:
            logger.error("Empty or invalid JSON payload")
            raise HTTPException(
                status_code=400,
                detail={"status": "error", "message": "Invalid JSON payload"}
            )
    except Exception as e:
        logger.error(f"Failed to parse JSON payload: {e}")
        raise HTTPException(
            status_code=400,
            detail={"status": "error", "message": "Failed to parse JSON"}
        )

    # Extract pipeline information
    try:
        pipeline_info = pipeline_extractor.extract_pipeline_info(payload)

        logger.info(
            f"Processing pipeline {pipeline_info['pipeline_id']} "
            f"for project {pipeline_info['project_id']} "
            f"(status: {pipeline_info['status']}, type: {pipeline_info['pipeline_type']})"
        )

        # Check if pipeline should be processed
        if not pipeline_extractor.should_process_pipeline(pipeline_info):
            # Track skipped request
            monitor.track_request(
                pipeline_info=pipeline_info,
                status=RequestStatus.SKIPPED,
                event_type=x_gitlab_event,
                client_ip=client_host
            )
            return {
                "status": "skipped",
                "message": "Pipeline not ready for processing",
                "pipeline_id": pipeline_info['pipeline_id'],
                "status_reason": pipeline_info['status']
            }

        # Track queued request
        request_id = monitor.track_request(
            pipeline_info=pipeline_info,
            status=RequestStatus.QUEUED,
            event_type=x_gitlab_event,
            client_ip=client_host
        )

        # Process pipeline in background to avoid blocking webhook response
        background_tasks.add_task(process_pipeline_event, pipeline_info, request_id)

        logger.info(f"Pipeline {pipeline_info['pipeline_id']} queued for processing")

        return {
            "status": "success",
            "message": "Pipeline logs queued for extraction",
            "pipeline_id": pipeline_info['pipeline_id'],
            "project_id": pipeline_info['project_id'],
            "request_id": request_id
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to process webhook: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"status": "error", "message": f"Processing failed: {str(e)}"}
        )


def process_pipeline_event(pipeline_info: Dict[str, Any], request_id: int):
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
        request_id (int): Monitoring request ID for tracking

    Error Handling:
        - Logs errors but continues processing remaining jobs
        - Uses retry logic for transient failures
        - Updates monitoring status on completion/failure
    """
    pipeline_id = pipeline_info['pipeline_id']
    project_id = pipeline_info['project_id']

    logger.info(f"Starting log extraction for pipeline {pipeline_id} (request #{request_id})")

    start_time = datetime.utcnow()

    # Update status to processing
    monitor.update_request(request_id, RequestStatus.PROCESSING)

    try:
        # Save pipeline metadata
        storage_manager.save_pipeline_metadata(
            project_id=project_id,
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

        # Fetch all logs for the pipeline
        all_logs = log_fetcher.fetch_all_logs_for_pipeline(project_id, pipeline_id)

        # Save each job log
        success_count = 0
        error_count = 0

        for job_id, job_data in all_logs.items():
            try:
                job_details = job_data['details']
                log_content = job_data['log']

                storage_manager.save_log(
                    project_id=project_id,
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

            except Exception as e:
                logger.error(f"Failed to save log for job {job_id}: {e}")
                error_count += 1

        logger.info(
            f"Completed processing pipeline {pipeline_id}: "
            f"{success_count} jobs saved, {error_count} errors"
        )

        # Log summary
        summary = pipeline_extractor.get_pipeline_summary(pipeline_info)
        logger.info(f"Pipeline summary:\n{summary}")

        # Update monitoring with success
        processing_time = (datetime.utcnow() - start_time).total_seconds()
        monitor.update_request(
            request_id=request_id,
            status=RequestStatus.COMPLETED,
            processing_time=processing_time,
            success_count=success_count,
            error_count=error_count
        )

    except RetryExhaustedError as e:
        error_msg = f"Failed to process pipeline {pipeline_id} after retries: {e}"
        logger.error(error_msg)
        # Update monitoring with failure
        processing_time = (datetime.utcnow() - start_time).total_seconds()
        monitor.update_request(
            request_id=request_id,
            status=RequestStatus.FAILED,
            processing_time=processing_time,
            error_message=str(e)
        )
    except Exception as e:
        error_msg = f"Unexpected error processing pipeline {pipeline_id}: {e}"
        logger.error(error_msg, exc_info=True)
        # Update monitoring with failure
        processing_time = (datetime.utcnow() - start_time).total_seconds()
        monitor.update_request(
            request_id=request_id,
            status=RequestStatus.FAILED,
            processing_time=processing_time,
            error_message=str(e)
        )


@app.get('/stats')
async def stats():
    """
    Get storage statistics.

    Returns:
        JSON response with storage statistics

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
    except Exception as e:
        logger.error(f"Failed to get storage stats: {e}")
        raise HTTPException(
            status_code=500,
            detail={"status": "error", "message": str(e)}
        )


@app.get('/monitor/summary')
async def monitor_summary(hours: int = Query(24, description="Number of hours to include")):
    """
    Get monitoring summary statistics.

    Args:
        hours (int): Number of hours to include in summary (default: 24)

    Returns:
        JSON response with monitoring statistics

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
    except Exception as e:
        logger.error(f"Failed to get monitor summary: {e}")
        raise HTTPException(
            status_code=500,
            detail={"status": "error", "message": str(e)}
        )


@app.get('/monitor/recent')
async def monitor_recent(limit: int = Query(50, description="Maximum number of requests")):
    """
    Get recent pipeline requests.

    Args:
        limit (int): Maximum number of requests to return (default: 50)

    Returns:
        JSON response with recent requests
    """
    try:
        requests = monitor.get_recent_requests(limit=limit)
        return {"requests": requests, "count": len(requests)}
    except Exception as e:
        logger.error(f"Failed to get recent requests: {e}")
        raise HTTPException(
            status_code=500,
            detail={"status": "error", "message": str(e)}
        )


@app.get('/monitor/pipeline/{pipeline_id}')
async def monitor_pipeline(pipeline_id: int):
    """
    Get all requests for a specific pipeline.

    Args:
        pipeline_id (int): Pipeline ID

    Returns:
        JSON response with pipeline requests
    """
    try:
        requests = monitor.get_pipeline_requests(pipeline_id)
        return {"pipeline_id": pipeline_id, "requests": requests, "count": len(requests)}
    except Exception as e:
        logger.error(f"Failed to get pipeline requests: {e}")
        raise HTTPException(
            status_code=500,
            detail={"status": "error", "message": str(e)}
        )


@app.get('/monitor/export/csv')
async def monitor_export_csv(
    hours: Optional[int] = Query(None, description="Only export last N hours (None = all)")
):
    """
    Export monitoring data to CSV file.

    Args:
        hours (Optional[int]): Only export requests from last N hours (None = all)

    Returns:
        CSV file download
    """
    try:
        import tempfile
        import os

        # Create temporary CSV file
        temp_file = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.csv')
        temp_file.close()

        # Export to CSV
        monitor.export_to_csv(temp_file.name, hours=hours)

        # Return file
        return FileResponse(
            path=temp_file.name,
            media_type='text/csv',
            filename=f"pipeline_monitoring_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
        )
    except Exception as e:
        logger.error(f"Failed to export CSV: {e}")
        raise HTTPException(
            status_code=500,
            detail={"status": "error", "message": str(e)}
        )


@app.on_event("startup")
async def startup_event():
    """
    FastAPI startup event handler.

    Initializes application components when the server starts.
    """
    init_app()


@app.on_event("shutdown")
async def shutdown_event():
    """
    FastAPI shutdown event handler.

    Performs cleanup when the server stops.
    """
    if log_fetcher:
        log_fetcher.close()
    if monitor:
        monitor.close()
    logger.info("Application shutdown complete")


def main():
    """
    Main entry point for the application.

    Initializes the application and starts the FastAPI server with uvicorn.
    """
    logger.info("=" * 60)
    logger.info("GitLab Pipeline Log Extraction System")
    logger.info("=" * 60)

    # Initialize application (will also be called by startup event)
    init_app()

    # Start FastAPI server with uvicorn
    logger.info(f"Starting webhook server on port {config.webhook_port}...")
    logger.info("Press Ctrl+C to stop")

    try:
        uvicorn.run(
            app,
            host='0.0.0.0',
            port=config.webhook_port,
            log_level=config.log_level.lower()
        )
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.error(f"Server error: {e}", exc_info=True)


if __name__ == "__main__":
    main()
