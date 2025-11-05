"""
Jenkins Extractor Module

This module handles extracting build information from Jenkins webhook payloads
and parsing console logs to identify stages and parallel blocks.

Data Flow:
    Webhook Payload → extract_webhook_data() → Job Info
    Console Log + Blue Ocean Data → parse_console_log() → Structured Stages

Module Dependencies:
    - re: For regex pattern matching in console logs
    - typing: For type hints
    - logging: For operation logging
"""

import re
import logging
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime

# Configure module logger
logger = logging.getLogger(__name__)


class JenkinsExtractor:
    """
    Extracts and parses Jenkins build information from webhooks and logs.

    This class handles:
    - Extracting job information from webhook payloads
    - Parsing console logs to identify stages
    - Identifying parallel execution blocks
    - Combining Blue Ocean API data with console logs
    """

    # Regex patterns for console log parsing
    STAGE_START_PATTERN = re.compile(r'\[Pipeline\] // stage \((.*?)\)')
    STAGE_HEADER_PATTERN = re.compile(r'\[Pipeline\] stage \((.*?)\)')
    PARALLEL_START_PATTERN = re.compile(r'\[Pipeline\] parallel')
    PARALLEL_END_PATTERN = re.compile(r'\[Pipeline\] // parallel')
    PARALLEL_BRANCH_PATTERN = re.compile(r'\[Pipeline\] \{ \((.*?)\)')

    def __init__(self):
        """Initialize the Jenkins extractor."""
        logger.info("Jenkins Extractor initialized")

    def extract_webhook_data(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract build information from Jenkins webhook payload.

        This method supports multiple webhook payload formats:
        - Custom curl POST from Jenkinsfile (our recommended approach)
        - Generic Webhook Trigger Plugin
        - Notification Plugin

        Args:
            payload (Dict[str, Any]): Webhook payload from Jenkins

        Returns:
            Dict[str, Any]: Extracted build information with keys:
                - job_name: Name of the Jenkins job
                - build_number: Build number
                - build_url: URL to the build
                - status: Build status (SUCCESS, FAILURE, etc.)
                - jenkins_url: Jenkins instance URL (if provided)

        Raises:
            ValueError: If required fields are missing from payload
        """
        logger.debug(f"Extracting webhook data from payload: {payload.keys()}")

        # Try custom format first (from Jenkinsfile curl)
        if 'job_name' in payload and 'build_number' in payload:
            return self._extract_custom_format(payload)

        # Try Generic Webhook Trigger format
        if 'job' in payload and 'build' in payload:
            return self._extract_generic_webhook_format(payload)

        # Try Notification Plugin format
        if 'name' in payload and 'build' in payload:
            return self._extract_notification_format(payload)

        # If none match, try to extract what we can
        logger.warning("Unknown webhook format, attempting best-effort extraction")
        return self._extract_fallback(payload)

    def _extract_custom_format(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Extract data from custom Jenkinsfile curl format."""
        return {
            'job_name': payload['job_name'],
            'build_number': int(payload['build_number']),
            'build_url': payload.get('build_url', ''),
            'status': payload.get('status', 'UNKNOWN'),
            'jenkins_url': payload.get('jenkins_url', ''),
            'timestamp': payload.get('timestamp', datetime.utcnow().isoformat())
        }

    def _extract_generic_webhook_format(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Extract data from Generic Webhook Trigger plugin format."""
        job = payload.get('job', {})
        build = payload.get('build', {})

        return {
            'job_name': job.get('name', ''),
            'build_number': int(build.get('number', 0)),
            'build_url': build.get('url', ''),
            'status': build.get('status', 'UNKNOWN'),
            'jenkins_url': job.get('url', '').rstrip('/job/' + job.get('name', '')),
            'timestamp': datetime.utcnow().isoformat()
        }

    def _extract_notification_format(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Extract data from Notification plugin format."""
        build = payload.get('build', {})

        return {
            'job_name': payload.get('name', ''),
            'build_number': int(build.get('number', 0)),
            'build_url': build.get('url', ''),
            'status': build.get('status', 'UNKNOWN'),
            'jenkins_url': '',  # Not provided in notification format
            'timestamp': datetime.utcnow().isoformat()
        }

    def _extract_fallback(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Fallback extraction for unknown formats."""
        job_name = payload.get('job_name') or payload.get('name') or 'unknown'
        build_number = payload.get('build_number') or payload.get('number') or 0

        if not job_name or not build_number:
            raise ValueError(
                "Cannot extract required fields from webhook payload. "
                "Expected 'job_name' and 'build_number' fields."
            )

        return {
            'job_name': job_name,
            'build_number': int(build_number),
            'build_url': payload.get('build_url', ''),
            'status': payload.get('status', 'UNKNOWN'),
            'jenkins_url': payload.get('jenkins_url', ''),
            'timestamp': datetime.utcnow().isoformat()
        }

    def parse_console_log(
        self,
        console_log: str,
        blue_ocean_stages: Optional[List[Dict[str, Any]]] = None
    ) -> List[Dict[str, Any]]:
        """
        Parse console log to extract stages and parallel blocks.

        This method intelligently combines Blue Ocean API data (if available)
        with console log parsing to create a structured representation of
        pipeline stages and parallel execution.

        Args:
            console_log (str): Complete console log from Jenkins
            blue_ocean_stages (Optional[List[Dict[str, Any]]]): Stage data from Blue Ocean API

        Returns:
            List[Dict[str, Any]]: List of stages with structure:
                [{
                    'stage_name': str,
                    'stage_id': str,
                    'status': str,
                    'duration_ms': int,
                    'is_parallel': bool,
                    'log_content': str (if not parallel),
                    'parallel_blocks': List[Dict] (if parallel)
                }]
        """
        logger.info(f"Parsing console log ({len(console_log)} bytes)")

        # If Blue Ocean data available, use it as the primary structure
        if blue_ocean_stages:
            return self._parse_with_blue_ocean(console_log, blue_ocean_stages)

        # Otherwise, parse console log directly
        return self._parse_console_only(console_log)

    def _parse_with_blue_ocean(
        self,
        console_log: str,
        stages: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Parse console log using Blue Ocean stage information."""
        logger.debug(f"Parsing with Blue Ocean data: {len(stages)} stages")

        result = []
        log_lines = console_log.split('\n')

        for stage in stages:
            stage_name = stage.get('name', 'Unknown')
            stage_id = stage.get('id', '')
            status = stage.get('status', 'UNKNOWN')
            duration_ms = stage.get('durationMillis', 0)

            # Check if this stage has parallel execution
            parallel_flows = stage.get('stageFlowNodes', [])
            is_parallel = len(parallel_flows) > 1

            if is_parallel:
                # Extract parallel block logs
                parallel_blocks = []
                for flow in parallel_flows:
                    block_name = flow.get('name', 'Unknown')
                    block_log = self._extract_block_log(log_lines, block_name)
                    parallel_blocks.append({
                        'block_name': block_name,
                        'status': flow.get('status', 'UNKNOWN'),
                        'duration_ms': flow.get('durationMillis', 0),
                        'log_content': block_log
                    })

                result.append({
                    'stage_name': stage_name,
                    'stage_id': stage_id,
                    'status': status,
                    'duration_ms': duration_ms,
                    'is_parallel': True,
                    'parallel_blocks': parallel_blocks
                })
            else:
                # Single stage, extract its log
                stage_log = self._extract_stage_log(log_lines, stage_name)
                result.append({
                    'stage_name': stage_name,
                    'stage_id': stage_id,
                    'status': status,
                    'duration_ms': duration_ms,
                    'is_parallel': False,
                    'log_content': stage_log
                })

        logger.info(f"Parsed {len(result)} stages with Blue Ocean data")
        return result

    def _parse_console_only(self, console_log: str) -> List[Dict[str, Any]]:
        """Parse console log without Blue Ocean data (fallback)."""
        logger.debug("Parsing console log without Blue Ocean data")

        log_lines = console_log.split('\n')
        stages = []
        current_stage = None
        in_parallel = False
        parallel_blocks = []
        current_block = None

        for i, line in enumerate(log_lines):
            # Check for stage start
            stage_match = self.STAGE_HEADER_PATTERN.search(line)
            if stage_match:
                # Save previous stage
                if current_stage:
                    stages.append(current_stage)

                current_stage = {
                    'stage_name': stage_match.group(1),
                    'stage_id': str(len(stages) + 1),
                    'status': 'UNKNOWN',
                    'duration_ms': 0,
                    'is_parallel': False,
                    'log_content': ''
                }
                continue

            # Check for parallel start
            if self.PARALLEL_START_PATTERN.search(line):
                in_parallel = True
                if current_stage:
                    current_stage['is_parallel'] = True
                    current_stage['parallel_blocks'] = []
                continue

            # Check for parallel branch
            branch_match = self.PARALLEL_BRANCH_PATTERN.search(line)
            if branch_match and in_parallel:
                if current_block:
                    if current_stage:
                        current_stage['parallel_blocks'].append(current_block)

                current_block = {
                    'block_name': branch_match.group(1),
                    'status': 'UNKNOWN',
                    'duration_ms': 0,
                    'log_content': ''
                }
                continue

            # Check for parallel end
            if self.PARALLEL_END_PATTERN.search(line):
                if current_block and current_stage:
                    current_stage['parallel_blocks'].append(current_block)
                    current_block = None
                in_parallel = False
                continue

            # Collect log lines
            if current_block:
                current_block['log_content'] += line + '\n'
            elif current_stage:
                if 'log_content' in current_stage:
                    current_stage['log_content'] += line + '\n'

        # Save last stage
        if current_stage:
            stages.append(current_stage)

        logger.info(f"Parsed {len(stages)} stages from console log")
        return stages

    def _extract_stage_log(self, log_lines: List[str], stage_name: str) -> str:
        """Extract log lines for a specific stage."""
        in_stage = False
        stage_log = []

        for line in log_lines:
            if f'stage ({stage_name})' in line:
                in_stage = True
                continue

            if in_stage and '// stage' in line:
                break

            if in_stage:
                stage_log.append(line)

        return '\n'.join(stage_log)

    def _extract_block_log(self, log_lines: List[str], block_name: str) -> str:
        """Extract log lines for a specific parallel block."""
        in_block = False
        block_log = []

        for line in log_lines:
            if f'{ ({block_name})' in line or f'Branch: {block_name}' in line:
                in_block = True
                continue

            # Check for end of block
            if in_block and ('[Pipeline] }' in line or '// parallel' in line):
                break

            if in_block:
                block_log.append(line)

        return '\n'.join(block_log)
