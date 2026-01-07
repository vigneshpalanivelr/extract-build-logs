"""
Jenkins Instance Manager Module

This module manages multiple Jenkins instances and their credentials.
It loads configuration from jenkins_instances.json and provides
lookup functionality based on Jenkins URL.

Data Flow:
    jenkins_instances.json → JenkinsInstanceManager → Credentials Lookup

Invoked by: webhook_listener
Invokes: None
"""

import json
import os
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class JenkinsInstance:
    """
    Data class representing a single Jenkins instance configuration.

    Attributes:
        jenkins_url: Base URL of the Jenkins instance
        jenkins_user: Username for authentication
        jenkins_api_token: API token for authentication
        jenkins_webhook_secret: Webhook secret for validation (optional)
        description: Human-readable description (optional)
    """
    jenkins_url: str
    jenkins_user: str
    jenkins_api_token: str
    jenkins_webhook_secret: Optional[str] = None
    description: Optional[str] = None


class JenkinsInstanceManager:
    """
    Manager class for handling multiple Jenkins instances.

    This class loads Jenkins instance configurations from a JSON file
    and provides methods to look up credentials based on Jenkins URL.
    """

    def __init__(self, config_file: str = "jenkins_instances.json"):
        """
        Initialize the Jenkins instance manager.

        Args:
            config_file: Path to the JSON configuration file
        """
        self.config_file = config_file
        self.instances: Dict[str, JenkinsInstance] = {}
        self._load_instances()

    def _load_instances(self):
        """
        Load Jenkins instances from configuration file.

        The configuration file should be in JSON format:
        {
            "instances": [
                {
                    "jenkins_url": "https://jenkins1.example.com",
                    "jenkins_user": "admin",
                    "jenkins_api_token": "token123",
                    "jenkins_webhook_secret": "secret123",
                    "description": "Main Jenkins instance"
                },
                ...
            ]
        }
        """
        if not os.path.exists(self.config_file):
            # No configuration file - this is okay, will fall back to env vars
            logger.debug("Jenkins instances file not found: %s", self.config_file)
            return

        logger.info("Loading Jenkins instances from: %s", self.config_file)

        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)

            instances_list = config.get('instances', [])
            logger.debug("Found %d Jenkins instance(s) in config file", len(instances_list))

            for idx, instance_data in enumerate(instances_list):
                original_url = instance_data['jenkins_url']
                normalized_url = self._normalize_url(original_url)

                logger.debug(
                    "Loading instance #%d: original_url='%s', normalized='%s', user='%s', description='%s'",
                    idx + 1,
                    original_url,
                    normalized_url,
                    instance_data['jenkins_user'],
                    instance_data.get('description', 'N/A')
                )

                instance = JenkinsInstance(
                    jenkins_url=normalized_url,
                    jenkins_user=instance_data['jenkins_user'],
                    jenkins_api_token=instance_data['jenkins_api_token'],
                    jenkins_webhook_secret=instance_data.get('jenkins_webhook_secret'),
                    description=instance_data.get('description')
                )

                # Store instance keyed by normalized URL
                self.instances[instance.jenkins_url] = instance
                logger.debug("Stored instance with key: '%s'", instance.jenkins_url)

            logger.info("Successfully loaded %d Jenkins instance(s)", len(self.instances))
            logger.debug("Available instance URLs: %s", list(self.instances.keys()))

        except (json.JSONDecodeError, KeyError) as e:
            logger.error("Failed to load Jenkins instances: %s", e)
            raise ValueError(f"Invalid Jenkins instances configuration file: {e}") from e

    def _normalize_url(self, url: str) -> str:
        """
        Normalize Jenkins URL for consistent lookup.

        Removes trailing slashes and converts to lowercase.

        Args:
            url: Jenkins URL to normalize

        Returns:
            Normalized URL
        """
        return url.rstrip('/').lower()

    def get_instance(self, jenkins_url: str) -> Optional[JenkinsInstance]:
        """
        Get Jenkins instance configuration by URL.

        Args:
            jenkins_url: Jenkins URL to look up

        Returns:
            JenkinsInstance if found, None otherwise
        """
        logger.debug("Looking up Jenkins instance for URL: '%s'", jenkins_url)
        normalized_url = self._normalize_url(jenkins_url)
        logger.debug("Normalized URL for lookup: '%s'", normalized_url)
        logger.debug("Available instance keys: %s", list(self.instances.keys()))

        instance = self.instances.get(normalized_url)

        if instance:
            logger.info(
                "Found Jenkins instance: url='%s', user='%s', description='%s'",
                instance.jenkins_url,
                instance.jenkins_user,
                instance.description
            )
        else:
            logger.warning(
                "No Jenkins instance found for URL '%s' (normalized: '%s')",
                jenkins_url,
                normalized_url
            )

        return instance

    def has_instances(self) -> bool:
        """
        Check if any Jenkins instances are configured.

        Returns:
            True if at least one instance is configured
        """
        return len(self.instances) > 0

    def get_all_urls(self) -> List[str]:
        """
        Get list of all configured Jenkins URLs.

        Returns:
            List of Jenkins URLs
        """
        return list(self.instances.keys())

    def validate_webhook_secret(self, jenkins_url: str, provided_secret: Optional[str]) -> bool:
        """
        Validate webhook secret for a specific Jenkins instance.

        Args:
            jenkins_url: Jenkins URL
            provided_secret: Secret provided in webhook request

        Returns:
            True if validation passes (or no secret configured), False otherwise
        """
        instance = self.get_instance(jenkins_url)
        if not instance or not instance.jenkins_webhook_secret:
            # No instance found or no secret configured - allow
            return True

        if not provided_secret:
            # Secret is configured but not provided
            return False

        # Simple string comparison (Jenkins doesn't use HMAC)
        return provided_secret == instance.jenkins_webhook_secret
