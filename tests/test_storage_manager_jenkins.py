"""
Tests for Jenkins-specific storage manager functionality.
"""

import json
import pytest
from src.storage_manager import StorageManager


class TestJenkinsStorageManager:
    """Test Jenkins storage functionality in StorageManager."""

    @pytest.fixture
    def temp_storage(self, tmp_path):
        """Create a temporary storage manager."""
        storage_dir = tmp_path / "logs"
        return StorageManager(str(storage_dir))

    def test_get_jenkins_build_directory(self, temp_storage):
        """Test creating Jenkins build directory."""
        build_dir = temp_storage.get_jenkins_build_directory("test-job", 123)

        assert build_dir.exists()
        assert build_dir.is_dir()
        assert "jenkins-builds" in str(build_dir)
        assert "test-job" in str(build_dir)
        assert "123" in str(build_dir)

    def test_get_jenkins_build_directory_sanitizes_job_name(self, temp_storage):
        """Test job name sanitization in directory creation."""
        build_dir = temp_storage.get_jenkins_build_directory("test job/with:special*chars", 456)

        assert build_dir.exists()
        # Should sanitize special characters
        assert "/" not in build_dir.name
        assert ":" not in build_dir.name
        assert "*" not in build_dir.name

    def test_save_jenkins_console_log(self, temp_storage):
        """Test saving Jenkins console log."""
        console_log = "Build started\nRunning tests\nBuild completed\n"

        log_path = temp_storage.save_jenkins_console_log(
            job_name="ci-build",
            build_number=789,
            console_log=console_log
        )

        assert log_path.exists()
        assert log_path.name == "console.log"
        assert log_path.read_text() == console_log

    def test_save_jenkins_console_log_large_content(self, temp_storage):
        """Test saving large Jenkins console log."""
        large_log = "Line\n" * 100000  # 100k lines

        log_path = temp_storage.save_jenkins_console_log(
            job_name="large-job",
            build_number=999,
            console_log=large_log
        )

        assert log_path.exists()
        saved_content = log_path.read_text()
        assert len(saved_content) == len(large_log)

    def test_save_jenkins_console_log_io_error(self, temp_storage, monkeypatch):
        """Test handling IO error when saving console log."""
        def mock_open(*args, **kwargs):
            raise IOError("Permission denied")

        monkeypatch.setattr("builtins.open", mock_open)

        with pytest.raises(IOError):
            temp_storage.save_jenkins_console_log(
                job_name="test-job",
                build_number=1,
                console_log="test"
            )

    def test_save_jenkins_stage_log(self, temp_storage):
        """Test saving Jenkins stage log."""
        stage_log = "Error: Test failed\nAssertion error at line 42\n"

        log_path = temp_storage.save_jenkins_stage_log(
            job_name="test-job",
            build_number=123,
            stage_name="Unit Tests",
            log_content=stage_log
        )

        assert log_path.exists()
        assert log_path.name == "stage_unit_tests.log"  # Sanitized and lowercase
        assert log_path.read_text() == stage_log

    def test_save_jenkins_stage_log_sanitizes_name(self, temp_storage):
        """Test stage name sanitization."""
        log_path = temp_storage.save_jenkins_stage_log(
            job_name="test-job",
            build_number=123,
            stage_name="Build & Deploy (Production)",
            log_content="stage log"
        )

        # Should be sanitized: lowercase, special chars replaced
        assert log_path.name == "stage_build_deploy_production.log"

    def test_save_jenkins_stage_log_empty_content(self, temp_storage):
        """Test saving empty stage log."""
        log_path = temp_storage.save_jenkins_stage_log(
            job_name="test-job",
            build_number=123,
            stage_name="empty-stage",
            log_content=""
        )

        assert log_path.exists()
        assert log_path.read_text() == ""

    def test_save_jenkins_stage_log_io_error(self, temp_storage, monkeypatch):
        """Test handling IO error when saving stage log."""
        def mock_open(*args, **kwargs):
            raise IOError("Disk full")

        monkeypatch.setattr("builtins.open", mock_open)

        with pytest.raises(IOError):
            temp_storage.save_jenkins_stage_log(
                job_name="test-job",
                build_number=1,
                stage_name="test",
                log_content="test"
            )

    def test_save_jenkins_metadata(self, temp_storage):
        """Test saving Jenkins build metadata."""
        build_data = {
            "job_name": "ci-build",
            "build_number": 123,
            "build_url": "https://jenkins.example.com/job/ci-build/123/",
            "jenkins_url": "https://jenkins.example.com",
            "status": "FAILED",
            "duration_ms": 45000,
            "stages": [
                {"name": "build", "status": "SUCCESS"},
                {"name": "test", "status": "FAILED"}
            ]
        }

        temp_storage.save_jenkins_metadata(
            job_name="ci-build",
            build_number=123,
            build_data=build_data
        )

        build_dir = temp_storage.get_jenkins_build_directory("ci-build", 123)
        metadata_path = build_dir / "metadata.json"

        assert metadata_path.exists()

        saved_metadata = json.loads(metadata_path.read_text())
        assert saved_metadata["source"] == "jenkins"
        assert saved_metadata["job_name"] == "ci-build"
        assert saved_metadata["build_number"] == 123
        assert saved_metadata["status"] == "FAILED"
        assert saved_metadata["duration_ms"] == 45000
        assert "last_updated" in saved_metadata
        assert len(saved_metadata["stages"]) == 2

    def test_save_jenkins_metadata_minimal(self, temp_storage):
        """Test saving Jenkins metadata with minimal data."""
        build_data = {
            "status": "SUCCESS"
        }

        temp_storage.save_jenkins_metadata(
            job_name="minimal-job",
            build_number=1,
            build_data=build_data
        )

        build_dir = temp_storage.get_jenkins_build_directory("minimal-job", 1)
        metadata_path = build_dir / "metadata.json"

        assert metadata_path.exists()
        saved_metadata = json.loads(metadata_path.read_text())
        assert saved_metadata["source"] == "jenkins"
        assert saved_metadata["status"] == "SUCCESS"

    def test_save_jenkins_metadata_io_error(self, temp_storage, monkeypatch):
        """Test handling IO error when saving metadata."""
        def mock_open(*args, **kwargs):
            raise IOError("Cannot write")

        monkeypatch.setattr("builtins.open", mock_open)

        with pytest.raises(IOError):
            temp_storage.save_jenkins_metadata(
                job_name="test-job",
                build_number=1,
                build_data={"status": "SUCCESS"}
            )

    def test_jenkins_complete_build_storage(self, temp_storage):
        """Test complete Jenkins build storage workflow."""
        # Save console log
        console_log_path = temp_storage.save_jenkins_console_log(
            job_name="full-build",
            build_number=555,
            console_log="Full console output\nWith multiple lines\n"
        )

        # Save stage logs
        stage1_path = temp_storage.save_jenkins_stage_log(
            job_name="full-build",
            build_number=555,
            stage_name="Build",
            log_content="Build logs here\n"
        )

        stage2_path = temp_storage.save_jenkins_stage_log(
            job_name="full-build",
            build_number=555,
            stage_name="Test",
            log_content="Test failed: error details\n"
        )

        # Save metadata
        temp_storage.save_jenkins_metadata(
            job_name="full-build",
            build_number=555,
            build_data={
                "status": "FAILED",
                "build_url": "https://jenkins.example.com/job/full-build/555/",
                "stages": [
                    {"name": "Build", "status": "SUCCESS"},
                    {"name": "Test", "status": "FAILED"}
                ]
            }
        )

        # Verify all files exist in same directory
        build_dir = temp_storage.get_jenkins_build_directory("full-build", 555)
        assert console_log_path.parent == build_dir
        assert stage1_path.parent == build_dir
        assert stage2_path.parent == build_dir
        assert (build_dir / "metadata.json").exists()

        # Verify directory structure
        assert len(list(build_dir.iterdir())) == 4  # console.log + 2 stage logs + metadata.json

    def test_multiple_jenkins_jobs_same_build_number(self, temp_storage):
        """Test storing multiple jobs with same build number."""
        # Job 1
        temp_storage.save_jenkins_console_log(
            job_name="job-one",
            build_number=100,
            console_log="Job one console\n"
        )

        # Job 2
        temp_storage.save_jenkins_console_log(
            job_name="job-two",
            build_number=100,
            console_log="Job two console\n"
        )

        # Both should exist in separate directories
        job1_dir = temp_storage.get_jenkins_build_directory("job-one", 100)
        job2_dir = temp_storage.get_jenkins_build_directory("job-two", 100)

        assert job1_dir != job2_dir
        assert (job1_dir / "console.log").exists()
        assert (job2_dir / "console.log").exists()

    def test_jenkins_build_directory_idempotent(self, temp_storage):
        """Test that calling get_jenkins_build_directory multiple times is safe."""
        dir1 = temp_storage.get_jenkins_build_directory("test-job", 123)
        dir2 = temp_storage.get_jenkins_build_directory("test-job", 123)
        dir3 = temp_storage.get_jenkins_build_directory("test-job", 123)

        assert dir1 == dir2 == dir3
        assert dir1.exists()
