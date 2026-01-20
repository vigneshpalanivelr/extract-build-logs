"""
Storage Manager Module

This module handles persistent storage of pipeline logs and metadata.
It organizes logs by project, pipeline, and job, and maintains metadata files
for easy retrieval and analysis.

Data Flow:
    Log Data + Metadata → save_log() → File System (organized directory structure)

Invoked by: webhook_listener
Invokes: None
"""

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
        logs/pipeline-logs/
        └── project_{project_id}/
            └── pipeline_{pipeline_id}/
                ├── metadata.json
                ├── job_{job_id}_{job_name}.log
                ├── job_{job_id}_{job_name}.log
                └── ...

    Attributes:
        base_dir (Path): Base directory for log storage
    """

    def __init__(self, base_dir: str = "./logs/pipeline-logs"):
        """
        Initialize the storage manager.

        Args:
            base_dir (str): Base directory for storing logs (default: ./logs/pipeline-logs)

        Creates the base directory if it doesn't exist.
        """
        self.base_dir = Path(base_dir)
        self._ensure_directory(self.base_dir)
        logger.info("Storage manager initialized with base directory: %s", self.base_dir)

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

    def get_pipeline_directory(self, project_id: int, pipeline_id: int, project_name: Optional[str] = None) -> Path:
        """
        Get (and create if needed) the directory for a specific pipeline.

        Args:
            project_id (int): GitLab project ID
            pipeline_id (int): GitLab pipeline ID
            project_name (Optional[str]): GitLab project name for readability

        Returns:
            Path: Path to pipeline directory

        Directory Structure:
            If project_name provided: {base_dir}/{project_name}_{project_id}/pipeline_{pipeline_id}/
            Otherwise: {base_dir}/project_{project_id}/pipeline_{pipeline_id}/
        """
        if project_name:
            safe_project_name = self._sanitize_filename(project_name)
            project_dir = f"{safe_project_name}_{project_id}"
        else:
            project_dir = f"project_{project_id}"

        pipeline_dir = self.base_dir / project_dir / f"pipeline_{pipeline_id}"
        self._ensure_directory(pipeline_dir)
        return pipeline_dir

    def save_log(
        self,
        project_id: int,
        pipeline_id: int,
        job_id: int,
        job_name: str,
        log_content: str,
        job_details: Optional[Dict[str, Any]] = None,
        project_name: Optional[str] = None
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
            project_name (Optional[str]): GitLab project name for readability

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
                job_details={"status": "success", "duration": 120.5},
                project_name="my-app"
            )
        """
        pipeline_dir = self.get_pipeline_directory(project_id, pipeline_id, project_name)

        # Create sanitized filename
        sanitized_name = self._sanitize_filename(job_name)
        log_filename = f"job_{job_id}_{sanitized_name}.log"
        log_path = pipeline_dir / log_filename  # pylint: disable=redefined-outer-name

        # Save log content
        try:
            with open(log_path, 'w', encoding='utf-8') as f:
                f.write(log_content)

            logger.info("Saved log for job %s (%s) to %s", job_id, job_name, log_path)

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
            logger.error("Failed to save log for job %s: %s", job_id, str(e))
            raise

    def save_pipeline_metadata(
        self,
        project_id: int,
        pipeline_id: int,
        pipeline_data: Dict[str, Any],
        project_name: Optional[str] = None
    ):
        """
        Save metadata for an entire pipeline.

        Args:
            project_id (int): GitLab project ID
            pipeline_id (int): GitLab pipeline ID
            pipeline_data (Dict[str, Any]): Pipeline metadata
            project_name (Optional[str]): GitLab project name for readability

        Creates/updates:
            {pipeline_dir}/metadata.json

        Metadata Structure:
            {
                "pipeline_id": 789,
                "project_id": 123,
                "project_name": "my-app",
                "status": "success",
                "ref": "main",
                "created_at": "2023-01-01T00:00:00Z",
                "updated_at": "2023-01-01T00:05:00Z",
                "jobs": {...}
            }
        """
        pipeline_dir = self.get_pipeline_directory(project_id, pipeline_id, project_name)
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
                    "project_name": project_name or "unknown",
                    "jobs": {}
                }

            # Update with new pipeline data
            metadata.update(pipeline_data)
            # Ensure project_name is in metadata
            if project_name:
                metadata["project_name"] = project_name
            metadata["last_updated"] = datetime.utcnow().isoformat()

            # Save metadata
            with open(metadata_path, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)

            logger.info("Saved pipeline metadata to %s", metadata_path)

        except IOError as e:
            logger.error("Failed to save pipeline metadata: %s", str(e))
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

            logger.debug("Updated metadata for job %s", job_id)

        except IOError as e:
            logger.error("Failed to update job metadata: %s", str(e))

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
            logger.warning("No metadata found for pipeline %s", pipeline_id)
            return None

        try:
            with open(metadata_path, 'r', encoding='utf-8') as f:
                metadata = json.load(f)
            return metadata
        except (IOError, json.JSONDecodeError) as e:
            logger.error("Failed to read pipeline metadata: %s", str(e))
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
                        logger.error("Failed to read metadata from %s: %s", metadata_path, str(e))

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
        stats = {  # pylint: disable=redefined-outer-name
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

    # ============================================================================
    # Jenkins Storage Methods
    # ============================================================================

    def get_jenkins_build_directory(self, job_name: str, build_number: int) -> Path:
        """
        Get (and create if needed) the directory for a specific Jenkins build.

        Args:
            job_name (str): Jenkins job name
            build_number (int): Jenkins build number

        Returns:
            Path: Path to build directory

        Directory Structure:
            {base_dir}/jenkins-builds/{job_name}/{build_number}/
        """
        # Create jenkins-builds subdirectory under base_dir
        jenkins_base = self.base_dir / "jenkins-builds"

        # Sanitize job name for filesystem safety
        safe_job_name = self._sanitize_filename(job_name)

        # Create full path: jenkins-builds/{job_name}/{build_number}/
        build_dir = jenkins_base / safe_job_name / str(build_number)
        self._ensure_directory(build_dir)

        return build_dir

    def save_jenkins_console_log(
        self,
        job_name: str,
        build_number: int,
        console_log: str
    ) -> Path:
        """
        Save Jenkins console log to filesystem.

        Args:
            job_name (str): Jenkins job name
            build_number (int): Jenkins build number
            console_log (str): Full console log content

        Returns:
            Path: Path to saved console.log file

        File Format:
            {build_dir}/console.log
        """
        build_dir = self.get_jenkins_build_directory(job_name, build_number)
        log_path = build_dir / "console.log"

        try:
            with open(log_path, 'w', encoding='utf-8') as f:
                f.write(console_log)

            logger.info(
                "Saved Jenkins console log for %s #%s to %s",
                job_name,
                build_number,
                log_path
            )
            return log_path

        except IOError as e:
            logger.error(
                "Failed to save Jenkins console log for %s #%s: %s",
                job_name,
                build_number,
                str(e)
            )
            raise

    def save_jenkins_stage_log(
        self,
        job_name: str,
        build_number: int,
        stage_name: str,
        log_content: str
    ) -> Path:
        """
        Save Jenkins stage log to filesystem.

        Args:
            job_name (str): Jenkins job name
            build_number (int): Jenkins build number
            stage_name (str): Stage name
            log_content (str): Stage log content (usually error context)

        Returns:
            Path: Path to saved stage log file

        File Format:
            {build_dir}/stage_{sanitized_stage_name}.log
        """
        build_dir = self.get_jenkins_build_directory(job_name, build_number)

        # Sanitize stage name and create filename
        safe_stage_name = self._sanitize_filename(stage_name.lower())
        log_filename = f"stage_{safe_stage_name}.log"
        log_path = build_dir / log_filename

        try:
            with open(log_path, 'w', encoding='utf-8') as f:
                f.write(log_content)

            logger.info(
                "Saved Jenkins stage log for %s #%s stage '%s' to %s",
                job_name,
                build_number,
                stage_name,
                log_path
            )
            return log_path

        except IOError as e:
            logger.error(
                "Failed to save Jenkins stage log for %s #%s stage '%s': %s",
                job_name,
                build_number,
                stage_name,
                str(e)
            )
            raise

    def save_jenkins_metadata(
        self,
        job_name: str,
        build_number: int,
        build_data: Dict[str, Any]
    ):
        """
        Save metadata for a Jenkins build.

        Args:
            job_name (str): Jenkins job name
            build_number (int): Jenkins build number
            build_data (Dict[str, Any]): Build metadata

        Creates/updates:
            {build_dir}/metadata.json

        Metadata Structure:
            {
                "source": "jenkins",
                "job_name": "ci_build",
                "build_number": 8320,
                "build_url": "https://jenkins.example.com/job/ci_build/8320/",
                "jenkins_url": "https://jenkins.example.com",
                "triggered_by": "user@internal.com",
                "timestamp": "2026-01-13T10:30:45.123Z",
                "status": "FAILED",
                "duration_ms": 245000,
                "parameters": {...},
                "stages": [...]
            }
        """
        build_dir = self.get_jenkins_build_directory(job_name, build_number)
        metadata_path = build_dir / "metadata.json"

        try:
            # Add source identifier
            build_data["source"] = "jenkins"
            build_data["job_name"] = job_name
            build_data["build_number"] = build_number
            build_data["last_updated"] = datetime.utcnow().isoformat()

            # Save metadata
            with open(metadata_path, 'w', encoding='utf-8') as f:
                json.dump(build_data, f, indent=2, ensure_ascii=False)

            logger.info(
                "Saved Jenkins build metadata for %s #%s to %s",
                job_name,
                build_number,
                metadata_path
            )

        except IOError as e:
            logger.error(
                "Failed to save Jenkins build metadata for %s #%s: %s",
                job_name,
                build_number,
                str(e)
            )
            raise


if __name__ == "__main__":
    # Example usage
    logging.basicConfig(level=logging.INFO)

    # Create storage manager
    manager = StorageManager("./logs/pipeline-logs")

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
    print("\nStorage Statistics:")
    print(f"  Projects: {stats['total_projects']}")
    print(f"  Pipelines: {stats['total_pipelines']}")
    print(f"  Jobs: {stats['total_jobs']}")
    print(f"  Total Size: {stats['total_size_mb']} MB")
