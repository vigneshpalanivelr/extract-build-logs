"""
Unit tests for jenkins_instance_manager module.

Tests the JenkinsInstanceManager class which handles loading and managing
multiple Jenkins instance configurations.
"""

import json
import os
import tempfile
import pytest
from src.jenkins_instance_manager import JenkinsInstance, JenkinsInstanceManager


class TestJenkinsInstance:
    """Tests for JenkinsInstance dataclass."""

    def test_jenkins_instance_creation(self):
        """Test creating a JenkinsInstance with all fields."""
        instance = JenkinsInstance(
            jenkins_url="https://jenkins.example.com",
            jenkins_user="admin",
            jenkins_api_token="token123",
            jenkins_webhook_secret="secret123",
            description="Test Jenkins"
        )

        assert instance.jenkins_url == "https://jenkins.example.com"
        assert instance.jenkins_user == "admin"
        assert instance.jenkins_api_token == "token123"
        assert instance.jenkins_webhook_secret == "secret123"
        assert instance.description == "Test Jenkins"

    def test_jenkins_instance_without_optionals(self):
        """Test creating a JenkinsInstance without optional fields."""
        instance = JenkinsInstance(
            jenkins_url="https://jenkins.example.com",
            jenkins_user="admin",
            jenkins_api_token="token123"
        )

        assert instance.jenkins_url == "https://jenkins.example.com"
        assert instance.jenkins_user == "admin"
        assert instance.jenkins_api_token == "token123"
        assert instance.jenkins_webhook_secret is None
        assert instance.description is None


class TestJenkinsInstanceManager:
    """Tests for JenkinsInstanceManager class."""

    @pytest.fixture
    def temp_config_file(self):
        """Create a temporary config file for testing."""
        fd, path = tempfile.mkstemp(suffix='.json')
        yield path
        os.close(fd)
        if os.path.exists(path):
            os.remove(path)

    @pytest.fixture
    def valid_config_data(self):
        """Return valid Jenkins instances configuration data."""
        return {
            "instances": [
                {
                    "jenkins_url": "https://jenkins1.example.com",
                    "jenkins_user": "admin",
                    "jenkins_api_token": "token1",
                    "jenkins_webhook_secret": "secret1",
                    "description": "Main Jenkins"
                },
                {
                    "jenkins_url": "https://jenkins2.example.com/",
                    "jenkins_user": "ci-user",
                    "jenkins_api_token": "token2",
                    "jenkins_webhook_secret": "secret2",
                    "description": "Team B Jenkins"
                },
                {
                    "jenkins_url": "HTTPS://JENKINS3.EXAMPLE.COM",
                    "jenkins_user": "devops",
                    "jenkins_api_token": "token3"
                }
            ]
        }

    def test_manager_with_nonexistent_file(self):
        """Test manager initialization when config file doesn't exist."""
        manager = JenkinsInstanceManager(config_file="nonexistent.json")
        assert not manager.has_instances()
        assert len(manager.instances) == 0

    def test_manager_with_valid_config(self, temp_config_file, valid_config_data):
        """Test manager initialization with valid configuration."""
        with open(temp_config_file, 'w', encoding='utf-8') as f:
            json.dump(valid_config_data, f)

        manager = JenkinsInstanceManager(config_file=temp_config_file)

        assert manager.has_instances()
        assert len(manager.instances) == 3

        # Check first instance
        instance1 = manager.get_instance("https://jenkins1.example.com")
        assert instance1 is not None
        assert instance1.jenkins_user == "admin"
        assert instance1.jenkins_api_token == "token1"
        assert instance1.jenkins_webhook_secret == "secret1"
        assert instance1.description == "Main Jenkins"

    def test_url_normalization(self, temp_config_file, valid_config_data):
        """Test that URLs are normalized (trailing slash removed, lowercase)."""
        with open(temp_config_file, 'w', encoding='utf-8') as f:
            json.dump(valid_config_data, f)

        manager = JenkinsInstanceManager(config_file=temp_config_file)

        # jenkins2 has trailing slash in config, should still match without it
        instance2 = manager.get_instance("https://jenkins2.example.com")
        assert instance2 is not None
        assert instance2.jenkins_user == "ci-user"

        # jenkins3 is uppercase in config, should match lowercase
        instance3 = manager.get_instance("https://jenkins3.example.com")
        assert instance3 is not None
        assert instance3.jenkins_user == "devops"

        # Should also match with trailing slash
        instance2_slash = manager.get_instance("https://jenkins2.example.com/")
        assert instance2_slash is not None
        assert instance2_slash.jenkins_user == "ci-user"

    def test_get_instance_not_found(self, temp_config_file, valid_config_data):
        """Test getting an instance that doesn't exist."""
        with open(temp_config_file, 'w', encoding='utf-8') as f:
            json.dump(valid_config_data, f)

        manager = JenkinsInstanceManager(config_file=temp_config_file)
        instance = manager.get_instance("https://nonexistent.example.com")
        assert instance is None

    def test_get_all_urls(self, temp_config_file, valid_config_data):
        """Test getting all configured Jenkins URLs."""
        with open(temp_config_file, 'w', encoding='utf-8') as f:
            json.dump(valid_config_data, f)

        manager = JenkinsInstanceManager(config_file=temp_config_file)
        urls = manager.get_all_urls()

        assert len(urls) == 3
        assert "https://jenkins1.example.com" in urls
        assert "https://jenkins2.example.com" in urls  # Normalized without trailing slash
        assert "https://jenkins3.example.com" in urls  # Normalized to lowercase

    def test_validate_webhook_secret_no_instance(self, temp_config_file):
        """Test webhook validation when instance is not found."""
        with open(temp_config_file, 'w', encoding='utf-8') as f:
            json.dump({"instances": []}, f)

        manager = JenkinsInstanceManager(config_file=temp_config_file)

        # Should return True when instance not found (permissive)
        result = manager.validate_webhook_secret(
            "https://unknown.example.com",
            "any_secret"
        )
        assert result is True

    def test_validate_webhook_secret_no_secret_configured(self, temp_config_file):
        """Test webhook validation when instance has no secret configured."""
        config_data = {
            "instances": [
                {
                    "jenkins_url": "https://jenkins.example.com",
                    "jenkins_user": "admin",
                    "jenkins_api_token": "token123"
                    # No jenkins_webhook_secret
                }
            ]
        }
        with open(temp_config_file, 'w', encoding='utf-8') as f:
            json.dump(config_data, f)

        manager = JenkinsInstanceManager(config_file=temp_config_file)

        # Should return True when no secret is configured
        result = manager.validate_webhook_secret(
            "https://jenkins.example.com",
            "any_secret"
        )
        assert result is True

        # Should also return True when no secret provided
        result = manager.validate_webhook_secret(
            "https://jenkins.example.com",
            None
        )
        assert result is True

    def test_validate_webhook_secret_success(self, temp_config_file, valid_config_data):
        """Test successful webhook secret validation."""
        with open(temp_config_file, 'w', encoding='utf-8') as f:
            json.dump(valid_config_data, f)

        manager = JenkinsInstanceManager(config_file=temp_config_file)

        result = manager.validate_webhook_secret(
            "https://jenkins1.example.com",
            "secret1"
        )
        assert result is True

    def test_validate_webhook_secret_failure(self, temp_config_file, valid_config_data):
        """Test failed webhook secret validation."""
        with open(temp_config_file, 'w', encoding='utf-8') as f:
            json.dump(valid_config_data, f)

        manager = JenkinsInstanceManager(config_file=temp_config_file)

        # Wrong secret
        result = manager.validate_webhook_secret(
            "https://jenkins1.example.com",
            "wrong_secret"
        )
        assert result is False

        # No secret provided but one is configured
        result = manager.validate_webhook_secret(
            "https://jenkins1.example.com",
            None
        )
        assert result is False

    def test_invalid_json_config(self, temp_config_file):
        """Test loading invalid JSON configuration."""
        with open(temp_config_file, 'w', encoding='utf-8') as f:
            f.write("{ invalid json }")

        with pytest.raises(ValueError, match="Invalid Jenkins instances configuration file"):
            JenkinsInstanceManager(config_file=temp_config_file)

    def test_missing_required_fields(self, temp_config_file):
        """Test configuration with missing required fields."""
        invalid_config = {
            "instances": [
                {
                    "jenkins_url": "https://jenkins.example.com"
                    # Missing jenkins_user and jenkins_api_token
                }
            ]
        }
        with open(temp_config_file, 'w', encoding='utf-8') as f:
            json.dump(invalid_config, f)

        with pytest.raises(ValueError, match="Invalid Jenkins instances configuration file"):
            JenkinsInstanceManager(config_file=temp_config_file)

    def test_empty_instances_array(self, temp_config_file):
        """Test configuration with empty instances array."""
        config_data = {"instances": []}
        with open(temp_config_file, 'w', encoding='utf-8') as f:
            json.dump(config_data, f)

        manager = JenkinsInstanceManager(config_file=temp_config_file)
        assert not manager.has_instances()
        assert len(manager.instances) == 0

    def test_instances_without_description(self, temp_config_file):
        """Test instances without optional description field."""
        config_data = {
            "instances": [
                {
                    "jenkins_url": "https://jenkins.example.com",
                    "jenkins_user": "admin",
                    "jenkins_api_token": "token123",
                    "jenkins_webhook_secret": "secret123"
                }
            ]
        }
        with open(temp_config_file, 'w', encoding='utf-8') as f:
            json.dump(config_data, f)

        manager = JenkinsInstanceManager(config_file=temp_config_file)
        instance = manager.get_instance("https://jenkins.example.com")

        assert instance is not None
        assert instance.description is None

    def test_multiple_instances_same_url(self, temp_config_file):
        """Test that later instances override earlier ones for same URL."""
        config_data = {
            "instances": [
                {
                    "jenkins_url": "https://jenkins.example.com",
                    "jenkins_user": "admin1",
                    "jenkins_api_token": "token1",
                    "description": "First"
                },
                {
                    "jenkins_url": "https://jenkins.example.com",
                    "jenkins_user": "admin2",
                    "jenkins_api_token": "token2",
                    "description": "Second"
                }
            ]
        }
        with open(temp_config_file, 'w', encoding='utf-8') as f:
            json.dump(config_data, f)

        manager = JenkinsInstanceManager(config_file=temp_config_file)

        # Should have only one instance (the second one)
        assert len(manager.instances) == 1

        instance = manager.get_instance("https://jenkins.example.com")
        assert instance.jenkins_user == "admin2"
        assert instance.description == "Second"

    def test_url_normalization_edge_cases(self, temp_config_file):
        """Test URL normalization with various edge cases."""
        config_data = {
            "instances": [
                {
                    "jenkins_url": "HTTP://Jenkins.Example.COM///",
                    "jenkins_user": "admin",
                    "jenkins_api_token": "token"
                }
            ]
        }
        with open(temp_config_file, 'w', encoding='utf-8') as f:
            json.dump(config_data, f)

        manager = JenkinsInstanceManager(config_file=temp_config_file)

        # All these variations should match due to normalization
        urls_to_test = [
            "HTTP://Jenkins.Example.COM",
            "http://jenkins.example.com",
            "http://jenkins.example.com/",
            "http://jenkins.example.com///",
        ]

        for url in urls_to_test:
            instance = manager.get_instance(url)
            assert instance is not None, f"Failed to match URL: {url}"
            assert instance.jenkins_user == "admin"
