"""
Storage Manager Module

This module handles persistent storage of pipeline logs and metadata.
It organizes logs by project, pipeline, and job, and maintains metadata files
for easy retrieval and analysis.

Data Flow:
    Log Data + Metadata → save_log() → File System (organized directory structure)

Module Dependencies:
    - os: For file system operations
    - json: For metadata serialization
    - datetime: For timestamps
    - pathlib: For path manipulation
    - logging: For operation logging
"""

import os
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List

# Configure module logger
logger = logging.getLogger(__name__)


class StorageManager:
    """
    Manages storage of pipeline logs and metadata.

    This class creates organized directory structures for logs and maintains
    metadata files that make it easy to search and analyze stored logs.

    Directory Structure:
        logs/
        └── project_{project_id}/
            └── pipeline_{pipeline_id}/
                ├── metadata.json
                ├── job_{job_id}_{job_name}.log
                ├── job_{job_id}_{job_name}.log
                └── ...

    Attributes:
        base_dir (Path): Base directory for log storage
    """

    def __init__(self, base_dir: str = "./logs"):
        """
        Initialize the storage manager.

        Args:
            base_dir (str): Base directory for storing logs (default: ./logs)

        Creates the base directory if it doesn't exist.
        """
        self.base_dir = Path(base_dir)
        self._ensure_directory(self.base_dir)
        logger.info(f"Storage manager initialized with base directory: {self.base_dir}")

    def _ensure_directory(self, path: Path):
        """
        Ensure a directory exists, creating it if necessary.

        Args:
            path (Path): Directory path to create
        """
        path.mkdir(parents=True, exist_ok=True)

    def _sanitize_filename(self, name: str) -> str:
        """
        Sanitize a string to be safe for use as a filename.

        Args:
            name (str): Original name

        Returns:
            str: Sanitized name safe for filesystem

        Replaces:
            - Spaces with underscores
            - Special characters with underscores
            - Multiple consecutive underscores with single underscore
        """
        # Replace spaces and special characters
        safe_chars = []
        for char in name:
            if char.isalnum() or char in ['-', '_', '.']:
                safe_chars.append(char)
            else:
                safe_chars.append('_')

        sanitized = ''.join(safe_chars)

        # Replace multiple underscores with single
        while '__' in sanitized:
            sanitized = sanitized.replace('__', '_')

        return sanitized.strip('_')

    def get_pipeline_directory(self, project_id: int, pipeline_id: int) -> Path:
        """
        Get (and create if needed) the directory for a specific pipeline.

        Args:
            project_id (int): GitLab project ID
            pipeline_id (int): GitLab pipeline ID

        Returns:
            Path: Path to pipeline directory

        Directory Structure:
            {base_dir}/project_{project_id}/pipeline_{pipeline_id}/
        """
        pipeline_dir = self.base_dir / f"project_{project_id}" / f"pipeline_{pipeline_id}"
        self._ensure_directory(pipeline_dir)
        return pipeline_dir

    def save_log(
        self,
        project_id: int,
        pipeline_id: int,
        job_id: int,
        job_name: str,
        log_content: str,
        job_details: Optional[Dict[str, Any]] = None
    ) -> Path:
        """
        Save a job log to the filesystem.

        Args:
            project_id (int): GitLab project ID
            pipeline_id (int): GitLab pipeline ID
            job_id (int): GitLab job ID
            job_name (str): Name of the job
            log_content (str): Raw log content
            job_details (Optional[Dict[str, Any]]): Additional job metadata

        Returns:
            Path: Path to saved log file

        File Format:
            {pipeline_dir}/job_{job_id}_{sanitized_job_name}.log

        Example:
            manager = StorageManager()
            log_path = manager.save_log(
                project_id=123,
                pipeline_id=789,
                job_id=456,
                job_name="build:production",
                log_content="Build started...",
                job_details={"status": "success", "duration": 120.5}
            )
        """
        pipeline_dir = self.get_pipeline_directory(project_id, pipeline_id)

        # Create sanitized filename
        sanitized_name = self._sanitize_filename(job_name)
        log_filename = f"job_{job_id}_{sanitized_name}.log"
        log_path = pipeline_dir / log_filename

        # Save log content
        try:
            with open(log_path, 'w', encoding='utf-8') as f:
                f.write(log_content)

            logger.info(f"Saved log for job {job_id} ({job_name}) to {log_path}")

            # Update metadata
            if job_details:
                self._update_job_metadata(
                    pipeline_dir,
                    job_id,
                    job_name,
                    log_filename,
                    job_details
                )

            return log_path

        except IOError as e:
            logger.error(f"Failed to save log for job {job_id}: {str(e)}")
            raise

    def save_pipeline_metadata(
        self,
        project_id: int,
        pipeline_id: int,
        pipeline_data: Dict[str, Any]
    ):
        """
        Save metadata for an entire pipeline.

        Args:
            project_id (int): GitLab project ID
            pipeline_id (int): GitLab pipeline ID
            pipeline_data (Dict[str, Any]): Pipeline metadata

        Creates/updates:
            {pipeline_dir}/metadata.json

        Metadata Structure:
            {
                "pipeline_id": 789,
                "project_id": 123,
                "status": "success",
                "ref": "main",
                "created_at": "2023-01-01T00:00:00Z",
                "updated_at": "2023-01-01T00:05:00Z",
                "jobs": {...}
            }
        """
        pipeline_dir = self.get_pipeline_directory(project_id, pipeline_id)
        metadata_path = pipeline_dir / "metadata.json"

        try:
            # Load existing metadata if it exists
            if metadata_path.exists():
                with open(metadata_path, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)
            else:
                metadata = {
                    "pipeline_id": pipeline_id,
                    "project_id": project_id,
                    "jobs": {}
                }

            # Update with new pipeline data
            metadata.update(pipeline_data)
            metadata["last_updated"] = datetime.utcnow().isoformat()

            # Save metadata
            with open(metadata_path, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)

            logger.info(f"Saved pipeline metadata to {metadata_path}")

        except IOError as e:
            logger.error(f"Failed to save pipeline metadata: {str(e)}")
            raise

    def _update_job_metadata(
        self,
        pipeline_dir: Path,
        job_id: int,
        job_name: str,
        log_filename: str,
        job_details: Dict[str, Any]
    ):
        """
        Update job metadata in the pipeline metadata file.

        Args:
            pipeline_dir (Path): Pipeline directory path
            job_id (int): Job ID
            job_name (str): Job name
            log_filename (str): Name of the log file
            job_details (Dict[str, Any]): Job metadata
        """
        metadata_path = pipeline_dir / "metadata.json"

        try:
            # Load existing metadata
            if metadata_path.exists():
                with open(metadata_path, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)
            else:
                metadata = {"jobs": {}}

            # Update job entry
            metadata["jobs"][str(job_id)] = {
                "job_id": job_id,
                "job_name": job_name,
                "log_file": log_filename,
                "saved_at": datetime.utcnow().isoformat(),
                **job_details
            }

            # Save updated metadata
            with open(metadata_path, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)

            logger.debug(f"Updated metadata for job {job_id}")

        except IOError as e:
            logger.error(f"Failed to update job metadata: {str(e)}")

    def get_pipeline_metadata(
        self,
        project_id: int,
        pipeline_id: int
    ) -> Optional[Dict[str, Any]]:
        """
        Retrieve metadata for a pipeline.

        Args:
            project_id (int): GitLab project ID
            pipeline_id (int): GitLab pipeline ID

        Returns:
            Optional[Dict[str, Any]]: Pipeline metadata or None if not found
        """
        pipeline_dir = self.get_pipeline_directory(project_id, pipeline_id)
        metadata_path = pipeline_dir / "metadata.json"

        if not metadata_path.exists():
            logger.warning(f"No metadata found for pipeline {pipeline_id}")
            return None

        try:
            with open(metadata_path, 'r', encoding='utf-8') as f:
                metadata = json.load(f)
            return metadata
        except (IOError, json.JSONDecodeError) as e:
            logger.error(f"Failed to read pipeline metadata: {str(e)}")
            return None

    def list_stored_pipelines(self, project_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        List all stored pipelines, optionally filtered by project.

        Args:
            project_id (Optional[int]): Filter by project ID, or None for all projects

        Returns:
            List[Dict[str, Any]]: List of pipeline information

        Example:
            manager = StorageManager()
            pipelines = manager.list_stored_pipelines(project_id=123)
            for pipeline in pipelines:
                print(f"Pipeline {pipeline['pipeline_id']}: {pipeline['status']}")
        """
        pipelines = []

        # Determine which project directories to search
        if project_id is not None:
            project_dirs = [self.base_dir / f"project_{project_id}"]
        else:
            project_dirs = [d for d in self.base_dir.iterdir() if d.is_dir()]

        for project_dir in project_dirs:
            if not project_dir.exists():
                continue

            # Iterate through pipeline directories
            for pipeline_dir in project_dir.iterdir():
                if not pipeline_dir.is_dir():
                    continue

                metadata_path = pipeline_dir / "metadata.json"
                if metadata_path.exists():
                    try:
                        with open(metadata_path, 'r', encoding='utf-8') as f:
                            metadata = json.load(f)
                        pipelines.append({
                            "project_id": metadata.get("project_id"),
                            "pipeline_id": metadata.get("pipeline_id"),
                            "status": metadata.get("status"),
                            "ref": metadata.get("ref"),
                            "created_at": metadata.get("created_at"),
                            "job_count": len(metadata.get("jobs", {})),
                            "path": str(pipeline_dir)
                        })
                    except (IOError, json.JSONDecodeError) as e:
                        logger.error(f"Failed to read metadata from {metadata_path}: {str(e)}")

        return pipelines

    def get_storage_stats(self) -> Dict[str, Any]:
        """
        Get statistics about stored logs.

        Returns:
            Dict[str, Any]: Storage statistics including counts and sizes

        Example Result:
            {
                "total_projects": 5,
                "total_pipelines": 23,
                "total_jobs": 156,
                "total_size_bytes": 45678901,
                "total_size_mb": 43.56
            }
        """
        stats = {
            "total_projects": 0,
            "total_pipelines": 0,
            "total_jobs": 0,
            "total_size_bytes": 0
        }

        if not self.base_dir.exists():
            return stats

        # Count projects
        project_dirs = [d for d in self.base_dir.iterdir() if d.is_dir()]
        stats["total_projects"] = len(project_dirs)

        # Count pipelines and jobs
        for project_dir in project_dirs:
            pipeline_dirs = [d for d in project_dir.iterdir() if d.is_dir()]
            stats["total_pipelines"] += len(pipeline_dirs)

            for pipeline_dir in pipeline_dirs:
                log_files = list(pipeline_dir.glob("*.log"))
                stats["total_jobs"] += len(log_files)

                # Calculate total size
                for log_file in log_files:
                    stats["total_size_bytes"] += log_file.stat().st_size

        stats["total_size_mb"] = round(stats["total_size_bytes"] / (1024 * 1024), 2)

        return stats


if __name__ == "__main__":
    # Example usage
    logging.basicConfig(level=logging.INFO)

    # Create storage manager
    manager = StorageManager("./logs")

    # Save example log
    log_path = manager.save_log(
        project_id=123,
        pipeline_id=789,
        job_id=456,
        job_name="build:production",
        log_content="Example log content\nBuild started...\nBuild completed successfully.",
        job_details={
            "status": "success",
            "stage": "build",
            "duration": 120.5
        }
    )
    print(f"Log saved to: {log_path}")

    # Get storage stats
    stats = manager.get_storage_stats()
    print(f"\nStorage Statistics:")
    print(f"  Projects: {stats['total_projects']}")
    print(f"  Pipelines: {stats['total_pipelines']}")
    print(f"  Jobs: {stats['total_jobs']}")
    print(f"  Total Size: {stats['total_size_mb']} MB")
