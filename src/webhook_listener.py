"""
Webhook Listener Module

This is the main application entry point. It runs a Flask web server that listens
for GitLab webhook events, processes them, fetches logs, and stores them.

Data Flow:
    GitLab → POST /webhook → validate_webhook() → process_pipeline_event() →
    PipelineExtractor → LogFetcher → StorageManager → Disk Storage

Module Dependencies:
    - flask: Web server framework
    - logging: Application logging
    - config_loader: Configuration management
    - pipeline_extractor: Event parsing
    - log_fetcher: GitLab API interaction
    - storage_manager: Log persistence
    - error_handler: Error handling and retries

Server Architecture:
    - Flask application listening on configured port (default: 8000)
    - Single webhook endpoint: POST /webhook
    - Optional webhook secret validation
    - Async processing support (optional)
"""

import logging
import sys
import hmac
import hashlib
from typing import Dict, Any, Optional
from flask import Flask, request, jsonify
import threading

from config_loader import ConfigLoader, Config
from pipeline_extractor import PipelineExtractor
from log_fetcher import LogFetcher
from storage_manager import StorageManager
from error_handler import RetryExhaustedError

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('webhook_server.log')
    ]
)

logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)

# Global configuration and components
config: Optional[Config] = None
log_fetcher: Optional[LogFetcher] = None
storage_manager: Optional[StorageManager] = None
pipeline_extractor: Optional[PipelineExtractor] = None


def init_app():
    """
    Initialize application components.

    This function loads configuration and initializes all required components:
    - Configuration loader
    - Pipeline extractor
    - Log fetcher
    - Storage manager

    Should be called before starting the server.
    """
    global config, log_fetcher, storage_manager, pipeline_extractor

    logger.info("Initializing GitLab Pipeline Log Extractor...")

    try:
        # Load configuration
        config = ConfigLoader.load()
        ConfigLoader.validate(config)
        logger.info(f"Configuration loaded successfully")
        logger.info(f"GitLab URL: {config.gitlab_url}")
        logger.info(f"Webhook Port: {config.webhook_port}")
        logger.info(f"Log Output Directory: {config.log_output_dir}")

        # Set logging level from config
        logging.getLogger().setLevel(config.log_level)

        # Initialize components
        pipeline_extractor = PipelineExtractor()
        log_fetcher = LogFetcher(config)
        storage_manager = StorageManager(config.log_output_dir)

        logger.info("All components initialized successfully")

    except Exception as e:
        logger.error(f"Failed to initialize application: {e}")
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


@app.route('/health', methods=['GET'])
def health_check():
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
    return jsonify({
        "status": "healthy",
        "service": "gitlab-log-extractor",
        "version": "1.0.0"
    }), 200


@app.route('/webhook', methods=['POST'])
def webhook_handler():
    """
    Main webhook endpoint for receiving GitLab events.

    This endpoint:
    1. Validates the webhook signature (if configured)
    2. Parses the pipeline event
    3. Determines if logs should be fetched
    4. Fetches and stores logs (optionally in background)

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
    logger.info(f"Received webhook request from {request.remote_addr}")

    # Validate webhook secret
    signature = request.headers.get('X-Gitlab-Token')
    if not validate_webhook_secret(request.data, signature):
        logger.warning("Webhook authentication failed")
        return jsonify({
            "status": "error",
            "message": "Authentication failed"
        }), 401

    # Check event type
    event_type = request.headers.get('X-Gitlab-Event')
    if event_type != 'Pipeline Hook':
        logger.info(f"Ignoring non-pipeline event: {event_type}")
        return jsonify({
            "status": "ignored",
            "message": f"Event type {event_type} is not processed"
        }), 200

    # Parse JSON payload
    try:
        payload = request.get_json()
        if not payload:
            logger.error("Empty or invalid JSON payload")
            return jsonify({
                "status": "error",
                "message": "Invalid JSON payload"
            }), 400
    except Exception as e:
        logger.error(f"Failed to parse JSON payload: {e}")
        return jsonify({
            "status": "error",
            "message": "Failed to parse JSON"
        }), 400

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
            return jsonify({
                "status": "skipped",
                "message": "Pipeline not ready for processing",
                "pipeline_id": pipeline_info['pipeline_id'],
                "status_reason": pipeline_info['status']
            }), 200

        # Process pipeline (in background thread to avoid blocking webhook response)
        thread = threading.Thread(
            target=process_pipeline_event,
            args=(pipeline_info,),
            daemon=True
        )
        thread.start()

        logger.info(f"Pipeline {pipeline_info['pipeline_id']} queued for processing")

        return jsonify({
            "status": "success",
            "message": "Pipeline logs queued for extraction",
            "pipeline_id": pipeline_info['pipeline_id'],
            "project_id": pipeline_info['project_id']
        }), 200

    except Exception as e:
        logger.error(f"Failed to process webhook: {e}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": f"Processing failed: {str(e)}"
        }), 500


def process_pipeline_event(pipeline_info: Dict[str, Any]):
    """
    Process a pipeline event: fetch and store logs.

    This function is the main processing logic that:
    1. Fetches all jobs for the pipeline
    2. Retrieves logs for each job
    3. Stores logs with metadata

    Runs in a background thread to avoid blocking webhook responses.

    Args:
        pipeline_info (Dict[str, Any]): Extracted pipeline information

    Error Handling:
        - Logs errors but continues processing remaining jobs
        - Uses retry logic for transient failures
    """
    pipeline_id = pipeline_info['pipeline_id']
    project_id = pipeline_info['project_id']

    logger.info(f"Starting log extraction for pipeline {pipeline_id}")

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

    except RetryExhaustedError as e:
        logger.error(f"Failed to process pipeline {pipeline_id} after retries: {e}")
    except Exception as e:
        logger.error(f"Unexpected error processing pipeline {pipeline_id}: {e}", exc_info=True)


@app.route('/stats', methods=['GET'])
def stats():
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
        return jsonify(storage_stats), 200
    except Exception as e:
        logger.error(f"Failed to get storage stats: {e}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


def main():
    """
    Main entry point for the application.

    Initializes the application and starts the Flask server.
    """
    logger.info("=" * 60)
    logger.info("GitLab Pipeline Log Extraction System")
    logger.info("=" * 60)

    # Initialize application
    init_app()

    # Start Flask server
    logger.info(f"Starting webhook server on port {config.webhook_port}...")
    logger.info("Press Ctrl+C to stop")

    try:
        app.run(
            host='0.0.0.0',
            port=config.webhook_port,
            debug=False,  # Set to True for development
            threaded=True
        )
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.error(f"Server error: {e}", exc_info=True)
    finally:
        # Cleanup
        if log_fetcher:
            log_fetcher.close()
        logger.info("Application shutdown complete")


if __name__ == "__main__":
    main()
