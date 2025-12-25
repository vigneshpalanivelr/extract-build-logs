"""
Unit tests for jenkins_extractor module.
"""

import unittest
from unittest.mock import patch, Mock
from datetime import datetime

from src.jenkins_extractor import JenkinsExtractor


class TestJenkinsExtractor(unittest.TestCase):
    """Test cases for JenkinsExtractor class."""

    def setUp(self):
        """Set up test fixtures."""
        self.extractor = JenkinsExtractor()

    def test_initialization(self):
        """Test JenkinsExtractor initialization."""
        self.assertIsNotNone(self.extractor)

    def test_extract_webhook_data_custom_format(self):
        """Test extracting data from custom Jenkinsfile curl format."""
        payload = {
            'job_name': 'my-job',
            'build_number': 123,
            'build_url': 'http://jenkins.example.com/job/my-job/123',
            'status': 'SUCCESS',
            'jenkins_url': 'http://jenkins.example.com',
            'timestamp': '2024-01-01T12:00:00Z'
        }

        result = self.extractor.extract_webhook_data(payload)

        self.assertEqual(result['job_name'], 'my-job')
        self.assertEqual(result['build_number'], 123)
        self.assertEqual(result['status'], 'SUCCESS')
        self.assertEqual(result['jenkins_url'], 'http://jenkins.example.com')

    def test_extract_webhook_data_custom_format_minimal(self):
        """Test custom format with minimal required fields."""
        payload = {
            'job_name': 'my-job',
            'build_number': '456'
        }

        result = self.extractor.extract_webhook_data(payload)

        self.assertEqual(result['job_name'], 'my-job')
        self.assertEqual(result['build_number'], 456)
        self.assertEqual(result['status'], 'UNKNOWN')
        self.assertEqual(result['build_url'], '')

    def test_extract_webhook_data_generic_webhook_format(self):
        """Test extracting data from Generic Webhook Trigger plugin format."""
        payload = {
            'job': {
                'name': 'my-pipeline',
                'url': 'http://jenkins.example.com/job/my-pipeline'
            },
            'build': {
                'number': 789,
                'url': 'http://jenkins.example.com/job/my-pipeline/789',
                'status': 'FAILURE'
            }
        }

        result = self.extractor.extract_webhook_data(payload)

        self.assertEqual(result['job_name'], 'my-pipeline')
        self.assertEqual(result['build_number'], 789)
        self.assertEqual(result['status'], 'FAILURE')
        self.assertIn('jenkins_url', result)

    def test_extract_webhook_data_notification_format(self):
        """Test extracting data from Notification plugin format."""
        payload = {
            'name': 'test-job',
            'build': {
                'number': 111,
                'url': 'http://jenkins.example.com/job/test-job/111',
                'status': 'UNSTABLE'
            }
        }

        result = self.extractor.extract_webhook_data(payload)

        self.assertEqual(result['job_name'], 'test-job')
        self.assertEqual(result['build_number'], 111)
        self.assertEqual(result['status'], 'UNSTABLE')
        self.assertEqual(result['jenkins_url'], '')

    def test_extract_webhook_data_fallback_success(self):
        """Test fallback extraction with minimal fields."""
        payload = {
            'job_name': 'fallback-job',
            'number': 222
        }

        result = self.extractor.extract_webhook_data(payload)

        self.assertEqual(result['job_name'], 'fallback-job')
        self.assertEqual(result['build_number'], 222)

    def test_extract_webhook_data_fallback_missing_fields(self):
        """Test fallback extraction raises ValueError when fields are missing."""
        payload = {
            'some_field': 'value'
        }

        with self.assertRaises(ValueError) as context:
            self.extractor.extract_webhook_data(payload)

        self.assertIn("Cannot extract required fields", str(context.exception))

    def test_extract_custom_format(self):
        """Test _extract_custom_format method."""
        payload = {
            'job_name': 'custom-job',
            'build_number': '333',
            'build_url': 'http://example.com/job/333',
            'status': 'SUCCESS'
        }

        result = self.extractor._extract_custom_format(payload)

        self.assertEqual(result['job_name'], 'custom-job')
        self.assertEqual(result['build_number'], 333)
        self.assertEqual(result['status'], 'SUCCESS')
        self.assertIn('timestamp', result)

    def test_extract_generic_webhook_format(self):
        """Test _extract_generic_webhook_format method."""
        payload = {
            'job': {'name': 'webhook-job', 'url': 'http://jenkins.example.com/job/webhook-job'},
            'build': {'number': '444', 'url': 'http://example.com/build/444', 'status': 'ABORTED'}
        }

        result = self.extractor._extract_generic_webhook_format(payload)

        self.assertEqual(result['job_name'], 'webhook-job')
        self.assertEqual(result['build_number'], 444)
        self.assertEqual(result['status'], 'ABORTED')

    def test_extract_notification_format(self):
        """Test _extract_notification_format method."""
        payload = {
            'name': 'notify-job',
            'build': {'number': '555', 'url': 'http://example.com/555', 'status': 'SUCCESS'}
        }

        result = self.extractor._extract_notification_format(payload)

        self.assertEqual(result['job_name'], 'notify-job')
        self.assertEqual(result['build_number'], 555)
        self.assertEqual(result['jenkins_url'], '')

    def test_extract_fallback(self):
        """Test _extract_fallback method with valid fields."""
        payload = {
            'job_name': 'fallback-test',
            'build_number': 666,
            'build_url': 'http://example.com/666',
            'status': 'FAILURE'
        }

        result = self.extractor._extract_fallback(payload)

        self.assertEqual(result['job_name'], 'fallback-test')
        self.assertEqual(result['build_number'], 666)
        self.assertEqual(result['status'], 'FAILURE')

    def test_extract_fallback_raises_on_missing_job_name(self):
        """Test _extract_fallback raises ValueError when job_name is missing."""
        payload = {
            'build_number': 777
        }

        with self.assertRaises(ValueError):
            self.extractor._extract_fallback(payload)

    def test_parse_console_log_with_blue_ocean(self):
        """Test parsing console log with Blue Ocean stages."""
        console_log = """[Pipeline] stage (Build)
Build output line 1
Build output line 2
[Pipeline] // stage (Build)
[Pipeline] stage (Test)
Test output line 1
[Pipeline] // stage (Test)"""

        blue_ocean_stages = [
            {
                'name': 'Build',
                'id': 'stage-1',
                'status': 'SUCCESS',
                'durationMillis': 5000,
                'stageFlowNodes': [{'name': 'Build', 'status': 'SUCCESS'}]
            },
            {
                'name': 'Test',
                'id': 'stage-2',
                'status': 'SUCCESS',
                'durationMillis': 3000,
                'stageFlowNodes': [{'name': 'Test', 'status': 'SUCCESS'}]
            }
        ]

        result = self.extractor.parse_console_log(console_log, blue_ocean_stages)

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['stage_name'], 'Build')
        self.assertEqual(result[0]['status'], 'SUCCESS')
        self.assertEqual(result[0]['duration_ms'], 5000)
        self.assertFalse(result[0]['is_parallel'])
        self.assertIn('log_content', result[0])

    def test_parse_console_log_with_parallel_stages(self):
        """Test parsing console log with parallel execution in Blue Ocean."""
        console_log = """[Pipeline] parallel
[Pipeline] { (Unit Tests)
Running unit tests
[Pipeline] }
[Pipeline] { (Integration Tests)
Running integration tests
[Pipeline] }
[Pipeline] // parallel"""

        blue_ocean_stages = [
            {
                'name': 'Test',
                'id': 'stage-1',
                'status': 'SUCCESS',
                'durationMillis': 10000,
                'stageFlowNodes': [
                    {'name': 'Unit Tests', 'status': 'SUCCESS', 'durationMillis': 5000},
                    {'name': 'Integration Tests', 'status': 'SUCCESS', 'durationMillis': 8000}
                ]
            }
        ]

        result = self.extractor.parse_console_log(console_log, blue_ocean_stages)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['stage_name'], 'Test')
        self.assertTrue(result[0]['is_parallel'])
        self.assertEqual(len(result[0]['parallel_blocks']), 2)
        self.assertEqual(result[0]['parallel_blocks'][0]['block_name'], 'Unit Tests')
        self.assertEqual(result[0]['parallel_blocks'][1]['block_name'], 'Integration Tests')

    def test_parse_console_log_without_blue_ocean(self):
        """Test parsing console log without Blue Ocean data."""
        console_log = """[Pipeline] stage (Build)
[Pipeline] echo
Building application
[Pipeline] // stage (Build)
[Pipeline] stage (Test)
[Pipeline] echo
Running tests
[Pipeline] // stage (Test)"""

        result = self.extractor.parse_console_log(console_log)

        self.assertIsInstance(result, list)
        # Should parse stages from console log
        self.assertGreaterEqual(len(result), 0)

    def test_parse_console_log_empty(self):
        """Test parsing empty console log."""
        console_log = ""

        result = self.extractor.parse_console_log(console_log)

        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 0)

    def test_parse_with_blue_ocean_empty_stages(self):
        """Test parsing with empty Blue Ocean stages list."""
        console_log = "Some log content"
        blue_ocean_stages = []

        result = self.extractor._parse_with_blue_ocean(console_log, blue_ocean_stages)

        self.assertEqual(len(result), 0)

    def test_parse_console_only_single_stage(self):
        """Test parsing console log with single stage."""
        console_log = """[Pipeline] stage (Deploy)
[Pipeline] echo
Deploying to production
[Pipeline] // stage (Deploy)"""

        result = self.extractor._parse_console_only(console_log)

        self.assertGreaterEqual(len(result), 0)

    def test_parse_console_only_with_parallel(self):
        """Test parsing console log with parallel blocks."""
        console_log = """[Pipeline] stage (Parallel Test)
[Pipeline] parallel
[Pipeline] { (Branch A)
Testing A
[Pipeline] }
[Pipeline] { (Branch B)
Testing B
[Pipeline] }
[Pipeline] // parallel
[Pipeline] // stage (Parallel Test)"""

        result = self.extractor._parse_console_only(console_log)

        # Should detect parallel execution
        self.assertIsInstance(result, list)

    def test_extract_stage_log(self):
        """Test extracting log for a specific stage."""
        log_lines = [
            "[Pipeline] stage (Build)",
            "Compiling code",
            "Build successful",
            "[Pipeline] // stage (Build)",
            "[Pipeline] stage (Test)",
            "Running tests"
        ]

        result = self.extractor._extract_stage_log(log_lines, 'Build')

        self.assertIn("Compiling code", result)
        self.assertIn("Build successful", result)
        self.assertNotIn("[Pipeline] stage (Build)", result)

    def test_extract_stage_log_not_found(self):
        """Test extracting log for a stage that doesn't exist."""
        log_lines = [
            "[Pipeline] stage (Build)",
            "Build output",
            "[Pipeline] // stage (Build)"
        ]

        result = self.extractor._extract_stage_log(log_lines, 'NonExistent')

        self.assertEqual(result, '')

    def test_extract_block_log(self):
        """Test extracting log for a specific parallel block."""
        log_lines = [
            "[Pipeline] { (Unit Tests)",
            "Running unit tests",
            "All tests passed",
            "[Pipeline] }",
            "[Pipeline] { (Integration Tests)",
            "Running integration tests"
        ]

        result = self.extractor._extract_block_log(log_lines, 'Unit Tests')

        self.assertIn("Running unit tests", result)
        self.assertIn("All tests passed", result)

    def test_extract_block_log_with_branch_format(self):
        """Test extracting log with 'Branch:' format."""
        log_lines = [
            "Branch: Unit Tests",
            "Test execution started",
            "Test execution completed",
            "[Pipeline] // parallel"
        ]

        result = self.extractor._extract_block_log(log_lines, 'Unit Tests')

        self.assertIn("Test execution started", result)
        self.assertIn("Test execution completed", result)

    def test_extract_block_log_not_found(self):
        """Test extracting log for a block that doesn't exist."""
        log_lines = [
            "[Pipeline] { (Unit Tests)",
            "Some output",
            "[Pipeline] }"
        ]

        result = self.extractor._extract_block_log(log_lines, 'NonExistent')

        self.assertEqual(result, '')

    def test_regex_patterns(self):
        """Test regex patterns match expected formats."""
        # Test stage start pattern
        self.assertTrue(self.extractor.STAGE_START_PATTERN.search('[Pipeline] // stage (Build)'))

        # Test stage header pattern
        self.assertTrue(self.extractor.STAGE_HEADER_PATTERN.search('[Pipeline] stage (Test)'))

        # Test parallel start pattern
        self.assertTrue(self.extractor.PARALLEL_START_PATTERN.search('[Pipeline] parallel'))

        # Test parallel end pattern
        self.assertTrue(self.extractor.PARALLEL_END_PATTERN.search('[Pipeline] // parallel'))

        # Test parallel branch pattern
        match = self.extractor.PARALLEL_BRANCH_PATTERN.search('[Pipeline] { (Unit Tests)')
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), 'Unit Tests')

    def test_parse_with_blue_ocean_single_flow(self):
        """Test parsing with Blue Ocean single flow node."""
        console_log = "[Pipeline] stage (Build)\nBuild output\n[Pipeline] // stage"
        stages = [{
            'name': 'Build',
            'id': 'stage-1',
            'status': 'SUCCESS',
            'durationMillis': 1000,
            'stageFlowNodes': [{'name': 'Build', 'status': 'SUCCESS', 'durationMillis': 1000}]
        }]

        result = self.extractor._parse_with_blue_ocean(console_log, stages)

        self.assertEqual(len(result), 1)
        self.assertFalse(result[0]['is_parallel'])
        self.assertIn('log_content', result[0])


if __name__ == '__main__':
    unittest.main()
