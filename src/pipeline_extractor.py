"""
Pipeline Extractor Module

This module analyzes GitLab webhook events and pipeline data to identify pipeline types
(main, child, parallel) and extract relevant information for log processing.

Data Flow:
    Webhook Event → extract_pipeline_info() → Pipeline Type & Metadata → Log Fetcher

Invoked by: webhook_listener
Invokes: None
"""

import logging
from typing import Dict, Any, List
from enum import Enum

# Configure module logger
logger = logging.getLogger(__name__)


class PipelineType(Enum):
    """
    Enumeration of pipeline types.

    Values:
        MAIN: Top-level pipeline triggered by commits, tags, or schedules
        CHILD: Child pipeline triggered by a parent pipeline
        PARALLEL: Parallel jobs within a pipeline (not a separate pipeline type in GitLab API)
        MERGE_REQUEST: Pipeline triggered by merge request
        UNKNOWN: Unable to determine pipeline type
    """
    MAIN = "main"
    CHILD = "child"
    PARALLEL = "parallel"
    MERGE_REQUEST = "merge_request"
    UNKNOWN = "unknown"


class PipelineExtractor:
    """
    Extracts and analyzes pipeline information from GitLab webhook events.

    This class parses webhook payloads and pipeline data to identify pipeline types,
    extract metadata, and provide structured information for downstream processing.
    """

    @staticmethod
    def extract_pipeline_info(webhook_payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract pipeline information from a webhook payload.

        This is the main entry point for processing webhook events. It extracts
        all relevant information needed to fetch and store pipeline logs.

        Args:
            webhook_payload (Dict[str, Any]): GitLab webhook payload

        Returns:
            Dict[str, Any]: Extracted pipeline information
                {
                    "event_type": str,           # "Pipeline Hook"
                    "pipeline_id": int,          # Pipeline ID
                    "project_id": int,           # Project ID
                    "project_name": str,         # Project name
                    "pipeline_type": str,        # main/child/merge_request
                    "status": str,               # success/failed/running
                    "ref": str,                  # Branch or tag name
                    "sha": str,                  # Commit SHA
                    "source": str,               # push/web/trigger/schedule
                    "created_at": str,           # ISO timestamp
                    "finished_at": str,          # ISO timestamp or None
                    "duration": float,           # Duration in seconds or None
                    "user": dict,                # User information
                    "commit": dict,              # Commit information
                    "builds": list,              # List of jobs
                }

        Example:
            extractor = PipelineExtractor()
            pipeline_info = extractor.extract_pipeline_info(webhook_data)
            print(f"Pipeline {pipeline_info['pipeline_id']} is {pipeline_info['status']}")
        """
        logger.debug("Extracting pipeline information from webhook payload")

        # Extract basic event info
        object_kind = webhook_payload.get("object_kind", "unknown")

        # Extract object attributes (main pipeline data)
        object_attrs = webhook_payload.get("object_attributes", {})

        # Extract project information
        project = webhook_payload.get("project", {})

        # Determine pipeline type
        pipeline_type = PipelineExtractor._determine_pipeline_type(
            object_attrs,
            webhook_payload
        )

        # Extract builds (jobs) information
        builds = webhook_payload.get("builds", [])

        pipeline_info = {
            "event_type": object_kind,
            "pipeline_id": object_attrs.get("id"),
            "pipeline_url": object_attrs.get("url"),  # GitLab provides the full pipeline URL
            "project_id": project.get("id"),
            "project_name": project.get("name"),
            "project_path": project.get("path_with_namespace"),
            "pipeline_type": pipeline_type.value,
            "status": object_attrs.get("status"),
            "ref": object_attrs.get("ref"),
            "sha": object_attrs.get("sha"),
            "source": object_attrs.get("source"),
            "created_at": object_attrs.get("created_at"),
            "finished_at": object_attrs.get("finished_at"),
            "duration": object_attrs.get("duration"),
            "user": webhook_payload.get("user", {}),
            "commit": webhook_payload.get("commit", {}),
            "builds": PipelineExtractor._extract_job_info(builds),
            "stages": object_attrs.get("stages", []),
            "variables": object_attrs.get("variables", [])
        }

        logger.info(
            "Extracted info for pipeline %s from project '%s' (type: %s, status: %s)",
            pipeline_info['pipeline_id'], pipeline_info['project_name'],
            pipeline_type.value, pipeline_info['status'],
            extra={'project_name': pipeline_info['project_name'], 'project_id': pipeline_info['project_id']}
        )

        return pipeline_info

    @staticmethod
    def _determine_pipeline_type(object_attrs: Dict[str, Any], webhook_payload: Dict[str, Any]) -> PipelineType:
        """
        Determine the type of pipeline from webhook data.

        Args:
            object_attrs (Dict[str, Any]): Pipeline object attributes from webhook
            webhook_payload (Dict[str, Any]): Full webhook payload

        Returns:
            PipelineType: Identified pipeline type

        Logic:
            - Check for merge_request object → MERGE_REQUEST
            - Check source == "parent_pipeline" → CHILD
            - Check source in ["push", "web", "schedule", "trigger"] → MAIN
            - Default → UNKNOWN
        """
        # Check for merge request pipeline
        if webhook_payload.get("merge_request"):
            return PipelineType.MERGE_REQUEST

        # Check pipeline source
        source = object_attrs.get("source", "")

        if source == "parent_pipeline":
            return PipelineType.CHILD
        if source in ["push", "web", "schedule", "trigger", "api"]:
            return PipelineType.MAIN

        logger.warning("Unknown pipeline source: %s", source)
        return PipelineType.UNKNOWN

    @staticmethod
    def _extract_job_info(builds: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Extract relevant information from build/job objects.

        Args:
            builds (List[Dict[str, Any]]): List of build objects from webhook

        Returns:
            List[Dict[str, Any]]: Simplified job information

        Extracted Fields:
            - id: Job ID
            - name: Job name
            - stage: Pipeline stage
            - status: Job status
            - started_at: Start timestamp
            - finished_at: Finish timestamp
            - duration: Duration in seconds
            - allow_failure: Whether job is allowed to fail
        """
        job_info = []

        for build in builds:
            job_info.append({
                "id": build.get("id"),
                "name": build.get("name"),
                "stage": build.get("stage"),
                "status": build.get("status"),
                "started_at": build.get("started_at"),
                "finished_at": build.get("finished_at"),
                "duration": build.get("duration"),
                "allow_failure": build.get("allow_failure", False),
                "runner": build.get("runner", {})
            })

        return job_info

    @staticmethod
    def should_process_pipeline(pipeline_info: Dict[str, Any]) -> bool:
        """
        Determine if a pipeline should be processed for log extraction.

        This method implements business logic to decide whether logs should be
        fetched for a given pipeline based on its status and type.

        Args:
            pipeline_info (Dict[str, Any]): Pipeline information from extract_pipeline_info()

        Returns:
            bool: True if pipeline should be processed, False otherwise

        Processing Rules:
            - Process pipelines with status in ["success", "failed"]
            - Skip pipelines with status "running" or "pending"
            - Process all pipeline types (main, child, merge_request)

        Example:
            pipeline_info = extractor.extract_pipeline_info(webhook_data)
            if extractor.should_process_pipeline(pipeline_info):
                # Fetch and store logs
                pass
        """
        status = pipeline_info.get("status", "").lower()

        # Only process completed pipelines
        if status in ["success", "failed"]:
            logger.info("Pipeline %s should be processed (status: %s)", pipeline_info['pipeline_id'], status)
            return True

        # Skip running or pending pipelines
        if status in ["running", "pending", "created"]:
            logger.info(
                "Skipping pipeline %s (status: %s, not yet completed)",
                pipeline_info['pipeline_id'], status
            )
            return False

        # Process other statuses (canceled, skipped, manual)
        logger.info("Pipeline %s will be processed (status: %s)", pipeline_info['pipeline_id'], status)
        return True

    @staticmethod
    def filter_jobs_to_fetch(
        pipeline_info: Dict[str, Any],
        include_success: bool = True,
        include_failed: bool = True,
        include_canceled: bool = False,
        include_skipped: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Filter jobs to determine which ones to fetch logs for.

        Args:
            pipeline_info (Dict[str, Any]): Pipeline information
            include_success (bool): Include successful jobs (default: True)
            include_failed (bool): Include failed jobs (default: True)
            include_canceled (bool): Include canceled jobs (default: False)
            include_skipped (bool): Include skipped jobs (default: False)

        Returns:
            List[Dict[str, Any]]: Filtered list of jobs to fetch

        Example:
            # Only fetch logs for failed jobs
            jobs = extractor.filter_jobs_to_fetch(
                pipeline_info,
                include_success=False,
                include_failed=True
            )
        """
        builds = pipeline_info.get("builds", [])
        filtered_jobs = []

        for job in builds:
            status = job.get("status", "").lower()

            # Check if job should be included based on status filters
            status_checks = [
                (status == "success" and include_success),
                (status == "failed" and include_failed),
                (status == "canceled" and include_canceled),
                (status == "skipped" and include_skipped)
            ]
            if any(status_checks):
                filtered_jobs.append(job)

        logger.info(
            "Filtered %d jobs from %d total jobs for pipeline %s",
            len(filtered_jobs), len(builds),
            pipeline_info.get('pipeline_id', 'unknown')
        )

        return filtered_jobs

    @staticmethod
    def get_pipeline_summary(pipeline_info: Dict[str, Any]) -> str:
        """
        Generate a human-readable summary of the pipeline.

        Args:
            pipeline_info (Dict[str, Any]): Pipeline information

        Returns:
            str: Formatted summary string

        Example Output:
            Pipeline #123 (main branch)
            Type: main
            Status: success
            Duration: 3m 45s
            Jobs: 5 total (4 success, 1 failed)
        """
        pipeline_id = pipeline_info.get("pipeline_id")
        ref = pipeline_info.get("ref")
        status = pipeline_info.get("status")
        duration = pipeline_info.get("duration", 0)
        pipeline_type = pipeline_info.get("pipeline_type")
        builds = pipeline_info.get("builds", [])

        # Calculate duration in readable format
        if duration:
            minutes = int(duration // 60)
            seconds = int(duration % 60)
            duration_str = f"{minutes}m {seconds}s"
        else:
            duration_str = "N/A"

        # Count job statuses
        job_counts = {}
        for job in builds:
            job_status = job.get("status", "unknown")
            job_counts[job_status] = job_counts.get(job_status, 0) + 1

        job_summary = ", ".join([f"{count} {status}" for status, count in job_counts.items()])

        summary = f"""Pipeline #{pipeline_id} ({ref})
Type: {pipeline_type}
Status: {status}
Duration: {duration_str}
Jobs: {len(builds)} total ({job_summary})"""

        return summary


if __name__ == "__main__":
    # Example usage with sample webhook data
    logging.basicConfig(level=logging.INFO)

    # Sample webhook payload
    sample_payload = {
        "object_kind": "pipeline",
        "object_attributes": {
            "id": 12345,
            "ref": "main",
            "sha": "abc123",
            "status": "success",
            "source": "push",
            "duration": 225,
            "created_at": "2023-01-01T00:00:00Z",
            "finished_at": "2023-01-01T00:03:45Z"
        },
        "project": {
            "id": 123,
            "name": "my-project",
            "path_with_namespace": "group/my-project"
        },
        "user": {
            "name": "John Doe",
            "username": "jdoe"
        },
        "builds": [
            {"id": 1, "name": "build", "stage": "build", "status": "success"},
            {"id": 2, "name": "test", "stage": "test", "status": "success"},
            {"id": 3, "name": "deploy", "stage": "deploy", "status": "failed"}
        ]
    }

    extractor = PipelineExtractor()
    test_pipeline_info = extractor.extract_pipeline_info(sample_payload)

    print(extractor.get_pipeline_summary(test_pipeline_info))
    print(f"\nShould process: {extractor.should_process_pipeline(test_pipeline_info)}")

    failed_jobs = extractor.filter_jobs_to_fetch(
        test_pipeline_info,
        include_success=False,
        include_failed=True
    )
    print(f"\nFailed jobs to fetch: {len(failed_jobs)}")
