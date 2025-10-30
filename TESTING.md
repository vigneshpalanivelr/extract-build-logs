# Testing Guide

Comprehensive guide for testing the GitLab Pipeline Log Extraction System, including the container management script, application code, and integration tests.

## Table of Contents

- [Overview](#overview)
- [Prerequisites](#prerequisites)
- [Testing the Container Management Script](#testing-the-container-management-script)
- [Running Unit Tests](#running-unit-tests)
- [Testing Individual Components](#testing-individual-components)
- [Integration Testing](#integration-testing)
- [Manual Testing](#manual-testing)
- [Continuous Integration](#continuous-integration)
- [Troubleshooting Tests](#troubleshooting-tests)

---

## Overview

The test suite covers:
- **Container Management Script** (`manage-container.py`) - Docker operations, CLI, configuration
- **Application Code** - Webhook processing, log fetching, storage
- **Integration Tests** - End-to-end workflows
- **API Endpoints** - FastAPI routes

**Test Framework:** pytest with mocking support

---

## Prerequisites

```bash
# Install test dependencies
pip install -r requirements.txt

# Verify pytest is installed
pytest --version

# Verify all dependencies
pip list | grep -E "pytest|docker|rich"
```

**Required packages:**
- pytest >= 7.4.3
- pytest-cov >= 4.1.0
- httpx >= 0.26.0 (for FastAPI testing)
- docker >= 7.0.0
- rich >= 13.0.0

---

## Testing the Container Management Script

### Quick Test

```bash
# Run all tests for manage-container.py
pytest tests/test_manage_container.py -v

# Run with coverage
pytest tests/test_manage_container.py --cov=manage_container --cov-report=term-missing

# Run specific test class
pytest tests/test_manage_container.py::TestLoadConfig -v

# Run specific test
pytest tests/test_manage_container.py::TestLoadConfig::test_load_config_with_defaults -v
```

### Test Coverage Report

```bash
# Generate HTML coverage report
pytest tests/test_manage_container.py --cov=manage_container --cov-report=html

# Open in browser
open htmlcov/index.html  # macOS
xdg-open htmlcov/index.html  # Linux
start htmlcov/index.html  # Windows
```

### Test Categories

**1. Configuration Management Tests**
```bash
# Test configuration loading and validation
pytest tests/test_manage_container.py::TestLoadConfig -v
pytest tests/test_manage_container.py::TestValidateConfig -v
pytest tests/test_manage_container.py::TestMaskValue -v
```

**2. Docker Operations Tests**
```bash
# Test Docker container operations
pytest tests/test_manage_container.py::TestBuildImage -v
pytest tests/test_manage_container.py::TestStartContainer -v
pytest tests/test_manage_container.py::TestStopContainer -v
pytest tests/test_manage_container.py::TestRestartContainer -v
```

**3. CLI Command Tests**
```bash
# Test CLI commands
pytest tests/test_manage_container.py::TestCLICommands -v
pytest tests/test_manage_container.py::TestMain -v
```

**4. Monitoring Tests**
```bash
# Test monitoring and export functionality
pytest tests/test_manage_container.py::TestShowMonitor -v
pytest tests/test_manage_container.py::TestExportMonitoringData -v
pytest tests/test_manage_container.py::TestTestWebhook -v
```

### Running Tests Without Docker

The unit tests mock the Docker SDK, so you don't need Docker running:

```bash
# Tests will pass even without Docker installed
pytest tests/test_manage_container.py -v
```

### What Gets Tested

✅ **Configuration:**
- Loading from .env files
- Applying default values
- Validating required fields
- Validating port ranges, log levels, retry settings
- Masking sensitive data

✅ **Docker Operations:**
- Building images
- Starting/stopping containers
- Checking container status
- Viewing logs
- Opening shell
- Removing containers
- Error handling

✅ **CLI:**
- Argument parsing
- Command routing
- Help text generation
- Exit codes
- Error messages

✅ **User Interaction:**
- Confirmation prompts
- Auto-confirm with --yes flag
- Keyboard interrupt handling

---

## Running Unit Tests

### All Application Tests

```bash
# Run all tests
pytest tests/ -v

# Run with coverage for all modules
pytest tests/ --cov=src --cov=. --cov-report=term-missing

# Run only fast tests (exclude slow integration tests)
pytest tests/ -m "not slow" -v
```

### Specific Test Files

```bash
# Test webhook listener
pytest tests/test_webhook_listener.py -v

# Test log fetcher
pytest tests/test_log_fetcher.py -v

# Test storage manager
pytest tests/test_storage_manager.py -v

# Test pipeline extractor
pytest tests/test_pipeline_extractor.py -v

# Test error handler
pytest tests/test_error_handler.py -v
```

### Parallel Testing

```bash
# Install pytest-xdist for parallel execution
pip install pytest-xdist

# Run tests in parallel (4 workers)
pytest tests/ -n 4 -v

# Run tests in parallel with coverage
pytest tests/ -n 4 --cov=src --cov-report=term-missing
```

### Watch Mode

```bash
# Install pytest-watch
pip install pytest-watch

# Auto-run tests on file changes
ptw tests/ -- -v
```

---

## Testing Individual Components

### Test Configuration Loader

```bash
# Run the module directly
python src/config_loader.py

# Expected output:
# ✓ Configuration loaded successfully
# GitLab URL: https://gitlab.com
# Webhook Port: 8000
# ...
```

### Test Logging System

```bash
# Test logging configuration
python src/logging_config.py

# Check logs directory
ls -la logs/
# Should show: application.log, access.log, performance.log
```

### Test Storage Manager

```bash
# Create test storage operations
python -c "
from src.storage_manager import StorageManager
sm = StorageManager('./logs')
sm.save_log(123, 789, 456, 'test', 'log content', {})
print('Storage test passed!')
"
```

### Test Monitoring

```bash
# Test monitoring database
python -c "
from src.monitoring import PipelineMonitor
monitor = PipelineMonitor('./logs/monitoring.db')
summary = monitor.get_summary(hours=24)
print(f'Monitoring test passed! Total requests: {summary[\"total_requests\"]}')
monitor.close()
"
```

---

## Integration Testing

### End-to-End Docker Workflow

```bash
# 1. Build image
./manage-container.py build

# 2. Start container
./manage-container.py start --yes

# 3. Verify running
./manage-container.py status

# 4. Send test webhook
./manage-container.py test

# 5. Check logs
./manage-container.py logs --no-follow | tail -20

# 6. View monitoring
./manage-container.py monitor

# 7. Export data
./manage-container.py export test_data.csv

# 8. Cleanup
./manage-container.py cleanup --force
```

### API Endpoint Testing

```bash
# Start container first
./manage-container.py start --yes

# Test health endpoint
curl http://localhost:8000/health
# Expected: {"status":"healthy","service":"gitlab-log-extractor","version":"1.0.0"}

# Test stats endpoint
curl http://localhost:8000/stats
# Expected: Storage and processing statistics

# Test monitoring summary
curl http://localhost:8000/monitor/summary?hours=24
# Expected: JSON with request counts and metrics

# Test webhook (using test payload)
curl -X POST http://localhost:8000/webhook \
  -H "Content-Type: application/json" \
  -H "X-Gitlab-Event: Pipeline Hook" \
  -d '{
    "object_kind": "pipeline",
    "object_attributes": {"id": 12345, "status": "success"},
    "project": {"id": 100, "name": "test-project"}
  }'
```

### Manual GitLab Integration Test

```bash
# 1. Set up ngrok tunnel (for local testing)
ngrok http 8000

# 2. Configure GitLab webhook
# Go to GitLab → Settings → Webhooks
# URL: https://your-ngrok-url/webhook
# Events: Pipeline events
# Secret: (from your .env WEBHOOK_SECRET)

# 3. Trigger a pipeline in GitLab
# Push code or manually trigger

# 4. Monitor logs in real-time
./manage-container.py logs

# 5. Check monitoring dashboard
./manage-container.py monitor

# 6. Verify logs were saved
ls -la logs/project_*/pipeline_*/
```

---

## Manual Testing

### Test Configuration Display

```bash
# View configuration
./manage-container.py config

# Validate only (no display)
./manage-container.py config --validate-only

# Quiet mode
./manage-container.py config --quiet
```

### Test Error Handling

**Missing .env file:**
```bash
# Temporarily rename .env
mv .env .env.bak

# Try to start (should fail gracefully)
./manage-container.py start

# Restore .env
mv .env.bak .env
```

**Invalid configuration:**
```bash
# Edit .env with invalid values
echo "WEBHOOK_PORT=99999" >> .env

# Try to start (should show warnings)
./manage-container.py config

# Fix .env
git checkout .env
```

**Docker not running:**
```bash
# Stop Docker
sudo systemctl stop docker  # Linux
# or stop Docker Desktop on Mac/Windows

# Try to build (should show clear error)
./manage-container.py build

# Start Docker again
sudo systemctl start docker  # Linux
```

### Test User Confirmation

```bash
# Without --yes flag (should prompt)
./manage-container.py start

# With --yes flag (should not prompt)
./manage-container.py start --yes

# Test cancellation (Ctrl+C during prompt)
./manage-container.py remove
# Press Ctrl+C when prompted
```

---

## Continuous Integration

### GitHub Actions Example

```yaml
# .github/workflows/test.yml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest

    steps:
    - uses: actions/checkout@v3

    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: '3.9'

    - name: Install dependencies
      run: |
        python -m pip install --upgrade pip
        pip install -r requirements.txt

    - name: Run unit tests
      run: |
        pytest tests/ -v --cov=src --cov=. --cov-report=xml

    - name: Upload coverage
      uses: codecov/codecov-action@v3
      with:
        file: ./coverage.xml
```

### GitLab CI Example

```yaml
# .gitlab-ci.yml
test:
  image: python:3.9
  script:
    - pip install -r requirements.txt
    - pytest tests/ -v --cov=src --cov=. --cov-report=term
  coverage: '/TOTAL.*\s+(\d+%)$/'
```

---

## Troubleshooting Tests

### Common Issues

**Issue 1: Import errors**
```bash
# Problem: ModuleNotFoundError
# Solution: Install dependencies
pip install -r requirements.txt

# Verify Python path
python -c "import sys; print('\n'.join(sys.path))"
```

**Issue 2: Tests fail with Docker errors**
```bash
# Problem: Docker not mocked properly
# Solution: Check mock setup in tests

# Run with verbose output
pytest tests/test_manage_container.py -vv -s
```

**Issue 3: Coverage report not generated**
```bash
# Problem: pytest-cov not installed
# Solution: Install coverage tools
pip install pytest-cov

# Generate report
pytest tests/ --cov=. --cov-report=html
```

**Issue 4: Tests are slow**
```bash
# Problem: Not using parallel execution
# Solution: Install and use pytest-xdist
pip install pytest-xdist
pytest tests/ -n auto
```

### Debugging Failed Tests

```bash
# Run with maximum verbosity
pytest tests/test_manage_container.py -vvv -s

# Run specific failing test
pytest tests/test_manage_container.py::TestClass::test_method -vv -s

# Show local variables on failure
pytest tests/test_manage_container.py --showlocals

# Drop into debugger on failure
pytest tests/test_manage_container.py --pdb

# Print output even for passing tests
pytest tests/test_manage_container.py -v -s
```

### Verify Test Environment

```bash
# Check Python version
python --version
# Should be 3.8 or higher

# Check pytest
pytest --version

# Check dependencies
pip list | grep -E "pytest|docker|rich|fastapi"

# Verify test discovery
pytest --collect-only tests/

# Dry run (don't execute)
pytest --collect-only tests/test_manage_container.py
```

---

## Best Practices

### Writing New Tests

1. **Use descriptive test names:**
   ```python
   def test_load_config_with_missing_gitlab_url():
       """Test that validation catches missing GITLAB_URL."""
   ```

2. **Mock external dependencies:**
   ```python
   @patch('manage_container.docker.from_env')
   def test_get_docker_client(self, mock_docker):
       # Test implementation
   ```

3. **Test both success and failure:**
   ```python
   def test_build_image_success(self):
       # Test happy path

   def test_build_image_failure(self):
       # Test error handling
   ```

4. **Use fixtures for common setup:**
   ```python
   @pytest.fixture
   def mock_config():
       return {'GITLAB_URL': 'test', 'GITLAB_TOKEN': 'test'}
   ```

### Running Tests Before Commit

```bash
# Create pre-commit hook
cat > .git/hooks/pre-commit << 'EOF'
#!/bin/bash
pytest tests/ -v --cov=src --cov=. --cov-report=term-missing
if [ $? -ne 0 ]; then
    echo "Tests failed! Commit aborted."
    exit 1
fi
EOF

chmod +x .git/hooks/pre-commit
```

---

## Quick Reference

```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=. --cov-report=html

# Run specific test file
pytest tests/test_manage_container.py -v

# Run specific test
pytest tests/test_manage_container.py::TestClass::test_method -v

# Run tests matching pattern
pytest tests/ -k "test_config" -v

# Run in parallel
pytest tests/ -n auto

# Watch mode
ptw tests/ -- -v

# Debug mode
pytest tests/ --pdb

# Verbose output
pytest tests/ -vv -s
```

---

For more information, see:
- [pytest documentation](https://docs.pytest.org/)
- [OPERATIONS.md](OPERATIONS.md) for running the application
- [README.md](README.md) for setup instructions
