#!/usr/bin/env python3
"""
GitLab Pipeline Log Extractor - Container Management Script

This script manages the Docker container lifecycle with beautiful CLI output,
configuration validation, and comprehensive error handling.

Features:
- Docker container operations (build, start, stop, restart, logs, status, remove)
- Configuration display and validation from .env file
- Monitoring dashboard integration
- Test webhook functionality
- Export monitoring data
- Rich terminal output with colors, tables, and progress bars

Exit Codes:
    0: Success
    1: General error
    2: Configuration error
    3: Docker error
    4: User cancelled operation

Testing:
    Run unit tests with: pytest tests/test_manage_container.py -v
    Run with coverage: pytest tests/test_manage_container.py --cov=. --cov-report=html

Usage:
    ./manage_container.py --help
    ./manage_container.py build
    ./manage_container.py start
    ./manage_container.py status
    ./manage_container.py logs
"""

import sys
import os
import json
import argparse
import socket
import subprocess
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import time
import requests

try:
    import docker
    from docker.errors import DockerException, ImageNotFound, NotFound, APIError
    from dotenv import dotenv_values
except ImportError as e:
    print(f"Error: Required package not found: {e}")
    print("Please install dependencies: pip install -r requirements.txt")
    sys.exit(1)

# Try to import rich, but make it optional for Python 3.6.0 compatibility
RICH_AVAILABLE = False
try:
    from rich.console import Console
    from rich.table import Table
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from rich.prompt import Prompt
    RICH_AVAILABLE = True
except ImportError:
    # Rich not available - will use basic fallback
    pass


# Constants
IMAGE_NAME = "bfa-gitlab-pipeline-extractor"
CONTAINER_NAME = "bfa-gitlab-pipeline-extractor"
LOGS_DIR = "./logs"
ENV_FILE = ".env"

# Exit codes
EXIT_SUCCESS = 0
EXIT_ERROR = 1
EXIT_CONFIG_ERROR = 2
EXIT_DOCKER_ERROR = 3
EXIT_CANCELLED = 4


# Simple console wrapper that works with or without rich
class SimpleConsole:
    """Fallback console for when rich is not available."""

    def print(self, *args, **kwargs):
        """Simple print that strips rich markup."""
        if len(args) == 1 and isinstance(args[0], SimpleTable):
            # Handle SimpleTable objects
            print(str(args[0]))
        else:
            message = ' '.join(str(arg) for arg in args)
            # Remove rich markup tags like [bold], [red], etc.
            import re
            message = re.sub(r'\[/?[a-z]+[^\]]*\]', '', message)
            print(message)


class SimpleTable:
    """Fallback table for when rich is not available."""

    def __init__(self, title="", **kwargs):
        self.title = title
        self.columns = []
        self.rows = []

    def add_column(self, name, **kwargs):
        self.columns.append(name)

    def add_row(self, *values):
        self.rows.append(values)

    def __str__(self):
        output = []
        if self.title:
            output.append(f"\n{self.title}")
            output.append("=" * len(self.title))

        if self.rows:
            # Calculate column widths
            col_widths = [len(col) for col in self.columns]
            for row in self.rows:
                for i, val in enumerate(row):
                    col_widths[i] = max(col_widths[i], len(str(val)))

            # Print header
            header = " | ".join(col.ljust(col_widths[i]) for i, col in enumerate(self.columns))
            output.append(header)
            output.append("-" * len(header))

            # Print rows
            for row in self.rows:
                row_str = " | ".join(str(val).ljust(col_widths[i]) for i, val in enumerate(row))
                output.append(row_str)

        return "\n".join(output)


class SimpleProgress:
    """Fallback progress for when rich is not available."""

    def __init__(self, *args, **kwargs):
        self.tasks = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def add_task(self, description, **kwargs):
        print(f"  {description}")
        return len(self.tasks)

    def update(self, task_id, **kwargs):
        pass


class SimplePrompt:
    """Fallback prompt for when rich is not available."""

    @staticmethod
    def ask(prompt, choices=None, default=None):
        """Simple input prompt with choices validation."""
        while True:
            if choices:
                prompt_text = f"{prompt} ({'/'.join(choices)})"
                if default:
                    prompt_text += f" [{default}]"
                prompt_text += ": "
            else:
                prompt_text = f"{prompt}: "

            response = input(prompt_text).strip()

            if not response and default:
                return default

            if choices is None or response in choices:
                return response

            print(f"Invalid choice. Please select from: {', '.join(choices)}")


# Initialize console (rich or simple fallback)
if RICH_AVAILABLE:
    console = Console()
else:
    # Dummy classes for Progress columns (only needed in simple mode)
    class SpinnerColumn:  # noqa: F811
        """Dummy spinner column for simple mode."""
        pass

    class TextColumn:  # noqa: F811
        """Dummy text column for simple mode."""
        def __init__(self, *args, **kwargs):
            pass

    # Assign fallback classes - noqa to suppress false positive F811 warnings
    console = SimpleConsole()
    Table = SimpleTable  # noqa: F811
    Progress = SimpleProgress  # noqa: F811
    Prompt = SimplePrompt  # noqa: F811
    print("Note: Running in basic mode (rich library not available)")
    print("For enhanced output, upgrade to Python 3.6.1+ and install rich==12.6.0\n")


# Configuration Management (merged from show_config.py)
def format_bytes(bytes_val: int) -> str:
    """
    Format bytes to human-readable size.

    Args:
        bytes_val: Size in bytes

    Returns:
        Formatted string (e.g., "1.2 GB")
    """
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_val < 1024.0:
            return f"{bytes_val:.1f} {unit}"
        bytes_val /= 1024.0
    return f"{bytes_val:.1f} PB"


def mask_value(value: Optional[str], show_chars: int = 8) -> str:
    """
    Mask sensitive values, showing only first N characters.

    Args:
        value: The value to mask
        show_chars: Number of characters to show before masking

    Returns:
        Masked string (e.g., "glpat-ab****")
    """
    if not value or value == "Not Set":
        return "[dim]Not Set[/dim]"
    if len(value) <= show_chars:
        return "****"
    return f"{value[:show_chars]}****"


def create_config_table(title: str):
    """
    Create a standardized configuration table with consistent styling.

    Args:
        title: Table title

    Returns:
        Configured Rich Table or SimpleTable ready for adding rows
    """
    if RICH_AVAILABLE:
        table = Table(title=title, show_header=True, header_style="bold cyan")
        table.add_column("Setting", style="yellow", width=30)
        table.add_column("Value", style="green")
    else:
        table = SimpleTable(title=title)
        table.add_column("Setting")
        table.add_column("Value")
    return table


def get_host_ip() -> str:
    """Get the local IP address of the host machine."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(('8.8.8.8', 80))
            return s.getsockname()[0]
    except Exception:
        return '127.0.0.1'


def load_config(env_file: Path = Path(ENV_FILE)) -> Optional[Dict[str, str]]:
    """
    Load configuration from .env file.

    Args:
        env_file: Path to .env file

    Returns:
        Dictionary of configuration values, or None if file doesn't exist
    """
    if not env_file.exists():
        return None

    # Load from .env file
    config = dotenv_values(env_file)

    # Add defaults for missing values
    defaults = {
        'WEBHOOK_PORT': '8000',
        'LOG_LEVEL': 'INFO',
        'LOG_OUTPUT_DIR': './logs',
        'RETRY_ATTEMPTS': '3',
        'RETRY_DELAY': '2',
        'WEBHOOK_SECRET': '',
    }

    for key, default in defaults.items():
        if key not in config or not config[key]:
            config[key] = default

    return config


def validate_required_fields(config: Dict[str, str]) -> Tuple[List[str], List[str]]:
    """Validate required configuration fields."""
    errors = []
    warnings = []

    if not config.get('GITLAB_URL'):
        errors.append("GITLAB_URL is not set (required)")
    if not config.get('GITLAB_TOKEN'):
        errors.append("GITLAB_TOKEN is not set (required)")
    if not config.get('WEBHOOK_SECRET'):
        warnings.append("WEBHOOK_SECRET is not set (webhooks will be unauthenticated)")

    return errors, warnings


def validate_logging_config(config: Dict[str, str]) -> Tuple[List[str], List[str]]:
    """Validate logging and retry configuration."""
    errors = []
    warnings = []

    # Log level validation
    valid_levels = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
    log_level = config.get('LOG_LEVEL', '').upper()
    if log_level not in valid_levels:
        warnings.append(f"LOG_LEVEL '{log_level}' is invalid (should be one of: {', '.join(valid_levels)})")

    # Port validation
    try:
        port = int(config.get('WEBHOOK_PORT', '8000'))
        if port < 1 or port > 65535:
            warnings.append(f"WEBHOOK_PORT {port} is out of valid range (1-65535)")
    except ValueError:
        warnings.append(f"WEBHOOK_PORT '{config.get('WEBHOOK_PORT')}' is not a valid number")

    # Retry validation
    try:
        retry_attempts = int(config.get('RETRY_ATTEMPTS', '3'))
        if retry_attempts < 0:
            warnings.append("RETRY_ATTEMPTS cannot be negative")
    except ValueError:
        warnings.append(f"RETRY_ATTEMPTS '{config.get('RETRY_ATTEMPTS')}' is not a valid number")

    try:
        retry_delay = int(config.get('RETRY_DELAY', '2'))
        if retry_delay < 0:
            warnings.append("RETRY_DELAY cannot be negative")
    except ValueError:
        warnings.append(f"RETRY_DELAY '{config.get('RETRY_DELAY')}' is not a valid number")

    return errors, warnings


def validate_api_config(config: Dict[str, str]) -> Tuple[List[str], List[str]]:
    """Validate API posting configuration."""
    errors = []
    warnings = []

    api_enabled = config.get('API_POST_ENABLED', 'false').lower() == 'true'
    if api_enabled:
        if not config.get('BFA_HOST'):
            errors.append("API_POST_ENABLED is true but BFA_HOST is not set")

        try:
            timeout = int(config.get('API_POST_TIMEOUT', '30'))
            if timeout < 1:
                warnings.append("API_POST_TIMEOUT should be at least 1 second")
            elif timeout > 300:
                warnings.append("API_POST_TIMEOUT is very high (>300s), consider reducing it")
        except ValueError:
            warnings.append(f"API_POST_TIMEOUT '{config.get('API_POST_TIMEOUT')}' is not a valid number")

    return errors, warnings


def validate_jenkins_config(config: Dict[str, str]) -> Tuple[List[str], List[str]]:
    """Validate Jenkins integration configuration."""
    errors = []
    warnings = []

    jenkins_enabled = config.get('JENKINS_ENABLED', 'false').lower() == 'true'
    if jenkins_enabled:
        if not config.get('JENKINS_URL'):
            errors.append("JENKINS_ENABLED is true but JENKINS_URL is not set")
        elif not config.get('JENKINS_URL').startswith(('http://', 'https://')):
            warnings.append("JENKINS_URL should start with http:// or https://")

        if not config.get('JENKINS_USER'):
            errors.append("JENKINS_ENABLED is true but JENKINS_USER is not set")
        if not config.get('JENKINS_API_TOKEN'):
            errors.append("JENKINS_ENABLED is true but JENKINS_API_TOKEN is not set")
        if not config.get('JENKINS_WEBHOOK_SECRET'):
            warnings.append("JENKINS_WEBHOOK_SECRET is not set (Jenkins webhooks will be unauthenticated)")

    return errors, warnings


def validate_log_filters(config: Dict[str, str]) -> Tuple[List[str], List[str]]:
    """Validate log filtering configuration."""
    errors = []
    warnings = []

    valid_statuses = ['all', 'failed', 'success', 'running', 'canceled', 'skipped']

    pipeline_status = config.get('LOG_SAVE_PIPELINE_STATUS', 'all').lower()
    if pipeline_status not in valid_statuses and ',' not in pipeline_status:
        warnings.append(f"LOG_SAVE_PIPELINE_STATUS '{pipeline_status}' is invalid")
    elif ',' in pipeline_status:
        for status in pipeline_status.split(','):
            if status.strip() not in valid_statuses:
                warnings.append(f"LOG_SAVE_PIPELINE_STATUS contains invalid status '{status.strip()}'")
                break

    job_status = config.get('LOG_SAVE_JOB_STATUS', 'all').lower()
    if job_status not in valid_statuses and ',' not in job_status:
        warnings.append(f"LOG_SAVE_JOB_STATUS '{job_status}' is invalid")
    elif ',' in job_status:
        for status in job_status.split(','):
            if status.strip() not in valid_statuses:
                warnings.append(f"LOG_SAVE_JOB_STATUS contains invalid status '{status.strip()}'")
                break

    return errors, warnings


def validate_system_resources(config: Dict[str, str]) -> Tuple[List[str], List[str]]:
    """Validate system resources (disk space, permissions, directories)."""
    errors = []
    warnings = []

    # Check disk space
    try:
        import shutil
        stat = shutil.disk_usage(Path.cwd())
        gb_free = stat.free / (1024 ** 3)
        if gb_free < 1:
            warnings.append(f"Low disk space: Only {gb_free:.1f} GB available")
        elif gb_free < 5:
            warnings.append(f"Disk space is getting low: {gb_free:.1f} GB available")
    except Exception:
        pass

    # Check .env file permissions
    env_file = Path(ENV_FILE)
    if env_file.exists():
        try:
            st = env_file.stat()
            perms = oct(st.st_mode)[-3:]
            if perms not in ['600', '400']:
                warnings.append(f".env file has insecure permissions ({perms}), consider setting to 600 or 400")
        except Exception:
            pass

    # Check log directory
    log_dir = Path(config.get('LOG_OUTPUT_DIR', './logs'))
    # Only check if directory exists - if not, it will be created on start (no warning needed)
    if log_dir.exists() and not os.access(log_dir, os.W_OK):
        errors.append(f"Log directory '{log_dir}' is not writable")

    return errors, warnings


def validate_config(config: Dict[str, str]) -> Tuple[List[str], List[str]]:
    """
    Validate configuration with comprehensive checks.

    Args:
        config: Configuration dictionary

    Returns:
        Tuple of (errors, warnings) lists
    """
    all_errors, all_warnings = [], []

    # Run all validation functions
    validators = [
        validate_required_fields,
        validate_logging_config,
        validate_api_config,
        validate_jenkins_config,
        validate_log_filters,
        validate_system_resources
    ]

    for validator in validators:
        errors, warnings = validator(config)
        all_errors.extend(errors)
        all_warnings.extend(warnings)

    return all_errors, all_warnings


def get_directory_size(path: Path) -> str:
    """
    Get directory size in human-readable format.

    Args:
        path: Directory path

    Returns:
        Size string (e.g., "1.2 GB")
    """
    try:
        if not path.exists():
            return "N/A (not created)"

        total_size = 0
        for entry in path.rglob('*'):
            if entry.is_file():
                total_size += entry.stat().st_size

        return format_bytes(total_size)
    except Exception:
        return "Unknown"


def get_disk_space(path: Path) -> Tuple[str, str, float]:
    """
    Get available and total disk space.

    Args:
        path: Path to check

    Returns:
        Tuple of (available, total, percent_used)
    """
    try:
        import shutil
        stat = shutil.disk_usage(path)

        available = format_bytes(stat.free)
        total = format_bytes(stat.total)
        percent_used = (stat.used / stat.total) * 100

        return available, total, percent_used
    except Exception:
        return "Unknown", "Unknown", 0.0


def check_file_permissions(file_path: Path) -> Tuple[str, bool]:
    """
    Check file permissions.

    Args:
        file_path: Path to file

    Returns:
        Tuple of (permissions_string, is_secure)
    """
    try:
        st = file_path.stat()
        mode = st.st_mode

        # Get octal permissions (e.g., 0o600)
        perms = oct(mode)[-3:]

        # Check if secure (600 or 400)
        is_secure = perms in ['600', '400']

        return perms, is_secure
    except Exception:
        return "Unknown", False


def show_config_table(config: Dict[str, str], quiet: bool = False) -> None:
    """
    Display configuration in formatted tables using Rich.

    Args:
        config: Configuration dictionary
        quiet: If True, show minimal output
    """
    if quiet:
        return

    # Environment Configuration
    env_table = create_config_table("Configuration Review")
    env_table.add_row("GitLab URL", config.get('GITLAB_URL', '[dim]Not Set[/dim]'))
    env_table.add_row("GitLab Token", mask_value(config.get('GITLAB_TOKEN', 'Not Set'), 8))
    env_table.add_row("Webhook Port", config.get('WEBHOOK_PORT', '8000'))
    env_table.add_row("Webhook Secret", mask_value(config.get('WEBHOOK_SECRET', ''), 4) if config.get('WEBHOOK_SECRET') else '[dim]Not Set[/dim]')
    env_table.add_row("Log Level", config.get('LOG_LEVEL', 'INFO'))
    env_table.add_row("Log Directory", config.get('LOG_OUTPUT_DIR', './logs'))
    env_table.add_row("Retry Attempts", config.get('RETRY_ATTEMPTS', '3'))
    env_table.add_row("Retry Delay", f"{config.get('RETRY_DELAY', '2')}s")
    console.print(env_table)
    console.print()

    # Log Filtering Configuration
    log_filter_table = create_config_table("Log Filtering Settings")
    log_filter_table.add_row("Pipeline Status Filter", config.get('LOG_SAVE_PIPELINE_STATUS', 'all'))
    log_filter_table.add_row("Job Status Filter", config.get('LOG_SAVE_JOB_STATUS', 'all'))

    save_projects = config.get('LOG_SAVE_PROJECTS', '').strip()
    exclude_projects = config.get('LOG_EXCLUDE_PROJECTS', '').strip()
    if save_projects:
        log_filter_table.add_row("Save Projects (IDs)", save_projects)
    elif exclude_projects:
        log_filter_table.add_row("Exclude Projects (IDs)", exclude_projects)
    else:
        log_filter_table.add_row("Project Filter", "[dim]All Projects[/dim]")

    log_filter_table.add_row("Save Metadata Always", config.get('LOG_SAVE_METADATA_ALWAYS', 'true'))
    console.print(log_filter_table)
    console.print()

    # API Posting Configuration (if enabled)
    api_enabled = config.get('API_POST_ENABLED', 'false').lower() == 'true'
    if api_enabled:
        api_table = create_config_table("API Posting Configuration")
        api_table.add_row("API Posting Enabled", "[bold green]Yes[/bold green]")

        bfa_host = config.get('BFA_HOST', '')
        api_url = f"http://{bfa_host}:8000/api/analyze" if bfa_host else '[dim]Not Set (BFA_HOST missing)[/dim]'
        api_table.add_row("API URL", api_url)
        api_table.add_row("Auth Token", mask_value(config.get('BFA_SECRET_KEY', ''), 8) if config.get('BFA_SECRET_KEY') else '[dim]Not Set[/dim]')
        api_table.add_row("API Timeout", f"{config.get('API_POST_TIMEOUT', '30')}s")
        api_table.add_row("API Retry Enabled", config.get('API_POST_RETRY_ENABLED', 'true'))
        api_table.add_row("Also Save to File", config.get('API_POST_SAVE_TO_FILE', 'false'))
        console.print(api_table)
        console.print()

    # Jenkins Integration (if enabled)
    jenkins_enabled = config.get('JENKINS_ENABLED', 'false').lower() == 'true'
    if jenkins_enabled:
        jenkins_table = create_config_table("Jenkins Integration")
        jenkins_table.add_row("Jenkins Enabled", "[bold green]Yes[/bold green]")
        jenkins_table.add_row("Jenkins URL", config.get('JENKINS_URL', '[dim]Not Set[/dim]'))
        jenkins_table.add_row("Jenkins User", config.get('JENKINS_USER', '[dim]Not Set[/dim]'))
        jenkins_table.add_row("Jenkins API Token", mask_value(config.get('JENKINS_API_TOKEN', ''), 8) if config.get('JENKINS_API_TOKEN') else '[dim]Not Set[/dim]')
        jenkins_table.add_row("Jenkins Webhook Secret", mask_value(config.get('JENKINS_WEBHOOK_SECRET', ''), 4) if config.get('JENKINS_WEBHOOK_SECRET') else '[dim]Not Set[/dim]')
        console.print(jenkins_table)
        console.print()

    # BFA Token Generation Configuration
    bfa_table = create_config_table("BFA JWT Token Generation")
    bfa_table.add_row("BFA Host", config.get('BFA_HOST', '[dim]Not Set[/dim]'))
    bfa_table.add_row("BFA Secret Key", mask_value(config.get('BFA_SECRET_KEY', ''), 8) if config.get('BFA_SECRET_KEY') else '[bold red]Not Set[/bold red]')
    bfa_table.add_row("Token Endpoint", "/api/token")
    bfa_table.add_row("Token Usage", "Dynamic JWT for API authentication")
    if not config.get('BFA_SECRET_KEY'):
        bfa_table.add_row("Status", "[bold red]⚠ Token generation disabled[/bold red]")
    console.print(bfa_table)
    console.print()

    # Container Configuration
    container_table = create_config_table("Container Settings")
    container_table.add_row("Container Name", CONTAINER_NAME)
    container_table.add_row("Image Name", IMAGE_NAME)
    container_table.add_row("Logs Volume", f"{Path.cwd()}/{LOGS_DIR}")
    console.print(container_table)
    console.print()

    # System Information
    system_table = create_config_table("System Information")
    log_dir = Path(config.get('LOG_OUTPUT_DIR', './logs'))
    system_table.add_row("Log Directory Size", get_directory_size(log_dir))

    available, total, percent_used = get_disk_space(Path.cwd())
    disk_color = "green" if percent_used < 80 else ("yellow" if percent_used < 90 else "red")
    system_table.add_row("Disk Available", f"[{disk_color}]{available} / {total} ({percent_used:.1f}% used)[/{disk_color}]")

    env_file = Path(ENV_FILE)
    if env_file.exists():
        perms, is_secure = check_file_permissions(env_file)
        perm_color = "green" if is_secure else "yellow"
        perm_text = f"[{perm_color}]{perms}[/{perm_color}]"
        if not is_secure:
            perm_text += " [yellow](consider 600 or 400)[/yellow]"
        system_table.add_row(".env File Permissions", perm_text)

    console.print(system_table)
    console.print()


def show_validation_results(errors: List[str], warnings: List[str]) -> None:
    """
    Display validation errors and warnings using Rich.

    Args:
        errors: List of error messages
        warnings: List of warning messages
    """
    if errors:
        console.print("\n[bold red]✗ ERRORS (must be fixed):[/bold red]")
        for error in errors:
            console.print(f"   • {error}", style="red")
        console.print()

    if warnings:
        console.print("[bold yellow]!  WARNINGS:[/bold yellow]")
        for warning in warnings:
            console.print(f"   • {warning}", style="yellow")
        console.print()


def confirm_action(message: str = "Continue with this configuration?", auto_yes: bool = False) -> bool:
    """
    Ask user for confirmation.

    Args:
        message: Confirmation message to display
        auto_yes: If True, auto-confirm without prompting

    Returns:
        True if user confirmed, False otherwise
    """
    if auto_yes:
        console.print("✓ Auto-confirmed (--yes flag)", style="green")
        return True

    while True:
        try:
            response = input(f"{message} (y/N): ").strip().lower()
            if response in ['y', 'yes']:
                return True
            elif response in ['n', 'no', '']:
                return False
            else:
                console.print("[yellow]Please enter 'y' or 'n'[/yellow]")
        except (KeyboardInterrupt, EOFError):
            console.print("\n")
            return False


# Docker Operations
def get_docker_client() -> Optional[docker.DockerClient]:
    """
    Get Docker client, return None if Docker is not available.

    Returns:
        Docker client or None
    """
    try:
        client = docker.from_env()
        client.ping()  # Test connection
        return client
    except DockerException as e:
        console.print(f"[bold red]✗ Docker Error:[/bold red] {str(e)}", style="red")
        console.print("\nPlease ensure Docker is installed and running.")
        return None


def get_port_from_config() -> int:
    """
    Get webhook port from configuration.

    Returns:
        Port number (default 8000)
    """
    config = load_config()
    if config:
        return int(config.get('WEBHOOK_PORT', '8000'))
    return 8000


def build_image(client: docker.DockerClient) -> bool:
    """
    Build Docker image with build args.

    Args:
        client: Docker client

    Returns:
        True if successful, False otherwise
    """
    import time

    try:
        # Get USER_UID and USER_GID from environment or use defaults
        user_uid = os.environ.get('USER_UID', os.getuid() if hasattr(os, 'getuid') else '1000')
        user_gid = os.environ.get('USER_GID', os.getgid() if hasattr(os, 'getgid') else '1000')

        console.print(f"[bold blue]Building Docker image:[/bold blue] {IMAGE_NAME}:latest")
        console.print(f"[dim]Build args: USER_UID={user_uid}, USER_GID={user_gid}[/dim]")

        # Show shell equivalent
        shell_cmd = (
            f"docker build --build-arg USER_UID={user_uid} "
            f"--build-arg USER_GID={user_gid} "
            f"-t {IMAGE_NAME}:latest --rm ."
        )
        console.print(f"[dim]Shell equivalent: {shell_cmd}[/dim]\n")

        start_time = time.time()

        # Use subprocess to call docker CLI directly
        # The Docker SDK has issues with user namespace mapping that the CLI doesn't have
        build_cmd = [
            'docker', 'build',
            '--build-arg', f'USER_UID={user_uid}',
            '--build-arg', f'USER_GID={user_gid}',
            '-t', f'{IMAGE_NAME}:latest',
            '--rm',
            '.'
        ]

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task("Building image...", total=None)

            # Run docker build command
            result = subprocess.run(
                build_cmd,
                capture_output=True,
                text=True,
                cwd=os.path.abspath(".")
            )

            progress.update(task, completed=True)

            if result.returncode != 0:
                console.print("[bold red]ERROR: Build failed[/bold red]", style="red")
                console.print(result.stderr)
                return False

        elapsed_time = time.time() - start_time

        console.print("[bold green]SUCCESS: Image built successfully![/bold green]")
        console.print(f"[green]  Build time: {elapsed_time:.1f} seconds[/green]")
        console.print(f"[green]  Image: {IMAGE_NAME}:latest[/green]")
        return True

    except subprocess.CalledProcessError as e:
        console.print(f"[bold red]ERROR: Build failed - {str(e)}[/bold red]", style="red")
        return False
    except Exception as e:
        console.print(f"[bold red]ERROR: Build failed - {str(e)}[/bold red]", style="red")
        return False


def container_exists(client: docker.DockerClient) -> bool:
    """
    Check if container exists.

    Args:
        client: Docker client

    Returns:
        True if container exists, False otherwise
    """
    try:
        client.containers.get(CONTAINER_NAME)
        return True
    except NotFound:
        return False


def container_running(client: docker.DockerClient) -> bool:
    """
    Check if container is running.

    Args:
        client: Docker client

    Returns:
        True if container is running, False otherwise
    """
    try:
        container = client.containers.get(CONTAINER_NAME)
        return container.status == 'running'
    except NotFound:
        return False


def start_container(client: docker.DockerClient, config: Dict[str, str], skip_confirm: bool = False) -> bool:
    """
    Start container (create if needed).

    Args:
        client: Docker client
        config: Configuration dictionary
        skip_confirm: Skip confirmation prompt

    Returns:
        True if successful, False otherwise
    """
    try:
        port = int(config.get('WEBHOOK_PORT', '8000'))
        logs_path = Path(LOGS_DIR)
        if not logs_path.exists():
            logs_path.mkdir(parents=True, exist_ok=True)
            logs_path.chmod(0o755)
            console.print(f"[green]✓ Created logs directory: {LOGS_DIR}[/green]")
        elif not os.access(logs_path, os.W_OK):
            console.print(f"[yellow]⚠ Warning: {LOGS_DIR} may not be writable. Run: sudo chown -R $USER:$USER {LOGS_DIR}[/yellow]")

        if container_exists(client):
            if container_running(client):
                console.print("[yellow]!  Container is already running. Use 'restart' to restart it.[/yellow]")
                return True
            console.print("[blue]Starting existing container...[/blue]")
            client.containers.get(CONTAINER_NAME).start()
            console.print("[bold green]✓ Container started![/bold green]")
            show_endpoints(port)
            return True

        console.print(f"[bold blue]Starting new container: {CONTAINER_NAME} (port {port})[/bold blue]")

        # Build volumes dictionary with absolute paths
        logs_path = Path.cwd() / LOGS_DIR
        env_path = Path.cwd() / ENV_FILE
        volumes = {
            str(logs_path.absolute()): {'bind': '/app/logs', 'mode': 'rw'},
            str(env_path.absolute()): {'bind': '/app/.env', 'mode': 'ro'}
        }

        # Add jenkins_instances.json if it exists (for multi-instance Jenkins support)
        jenkins_instances_file = Path.cwd() / 'jenkins_instances.json'
        if jenkins_instances_file.exists():
            volumes[str(jenkins_instances_file.absolute())] = {'bind': '/app/jenkins_instances.json', 'mode': 'ro'}
            console.print("[dim]  → Found jenkins_instances.json, mounting for multi-instance Jenkins support[/dim]")

        # Start container with host network and user namespace
        client.containers.run(
            f"{IMAGE_NAME}:latest",
            name=CONTAINER_NAME,
            detach=True,
            network_mode='host',
            userns_mode='host',
            ports={f'{port}/tcp': port},
            volumes=volumes,
            restart_policy={"Name": "unless-stopped"}
        )
        console.print("[bold green]✓ Container started successfully![/bold green]")

        # Show shell equivalent
        shell_cmd = (
            f"docker run -d --name {CONTAINER_NAME} "
            f"--network host --userns=host "
            f"-p {port}:{port} "
            f"-v {logs_path.absolute()}:/app/logs:rw "
            f"-v {env_path.absolute()}:/app/.env:ro "
        )
        if jenkins_instances_file.exists():
            shell_cmd += f"-v {jenkins_instances_file.absolute()}:/app/jenkins_instances.json:ro "
        shell_cmd += (
            f"--restart unless-stopped "
            f"{IMAGE_NAME}:latest"
        )
        console.print("[dim]Shell equivalent:[/dim]")
        console.print(f"[dim]{shell_cmd}[/dim]\n")

        show_endpoints(port)
        return True
    except ImageNotFound:
        console.print(f"[bold red]✗ Image '{IMAGE_NAME}:latest' not found. Run 'build' command first.[/bold red]")
        return False
    except APIError as e:
        console.print(f"[bold red]✗ Failed to start container: {str(e)}[/bold red]")
        return False


def show_endpoints(port: int, host: Optional[str] = None) -> None:
    """
    Display service endpoints.

    Args:
        port: Webhook port number
        host: Host IP address (defaults to auto-detected IP)
    """
    if host is None:
        host = get_host_ip()

    endpoints_table = Table(show_header=True, header_style="bold cyan")
    endpoints_table.add_column("Endpoint", style="yellow")
    endpoints_table.add_column("URL", style="green")

    endpoints_table.add_row("GitLab Webhook", f"http://{host}:{port}/webhook/gitlab")
    endpoints_table.add_row("Jenkins Webhook", f"http://{host}:{port}/webhook/jenkins")
    endpoints_table.add_row("Health Check", f"http://{host}:{port}/health")
    endpoints_table.add_row("API Docs", f"http://{host}:{port}/docs")
    endpoints_table.add_row("Monitoring", f"http://{host}:{port}/monitor/summary")

    console.print(endpoints_table)


def stop_container(client: docker.DockerClient) -> bool:
    """
    Stop container.

    Args:
        client: Docker client

    Returns:
        True if successful, False otherwise
    """
    try:
        if not container_running(client):
            console.print("[yellow]!  Container is not running.[/yellow]")
            return True

        console.print(f"[blue]Stopping container:[/blue] {CONTAINER_NAME}")
        container = client.containers.get(CONTAINER_NAME)
        container.stop()
        console.print("[bold green]✓ Container stopped![/bold green]")
        console.print(f"[dim]Shell equivalent: docker stop {CONTAINER_NAME}[/dim]")
        return True

    except NotFound:
        console.print(f"[yellow]!  Container '{CONTAINER_NAME}' does not exist.[/yellow]")
        return True
    except APIError as e:
        console.print(f"[bold red]✗ Failed to stop container:[/bold red] {str(e)}", style="red")
        return False


def restart_container(client: docker.DockerClient, config: Dict[str, str]) -> bool:
    """
    Restart container. Container must exist and be running.

    Args:
        client: Docker client
        config: Configuration dictionary

    Returns:
        True if successful, False otherwise
    """
    # Check if container exists first
    if not container_exists(client):
        console.print(f"[bold red]✗ Container '{CONTAINER_NAME}' does not exist.[/bold red]")
        console.print("[yellow]Use 'start' command to create and start the container.[/yellow]")
        return False

    # Check if container is running
    if not container_running(client):
        console.print("[yellow]!  Container exists but is not running.[/yellow]")
        console.print("[yellow]Use 'start' command to start it.[/yellow]")
        return False

    console.print(f"[bold blue]Restarting container:[/bold blue] {CONTAINER_NAME}")
    console.print(f"[dim]Shell equivalent: docker restart {CONTAINER_NAME}[/dim]")
    console.print(f"[dim]Or: docker stop {CONTAINER_NAME} && docker start {CONTAINER_NAME}[/dim]\n")

    if not stop_container(client):
        return False

    time.sleep(2)

    return start_container(client, config, skip_confirm=True)


def show_logs(client: docker.DockerClient, follow: bool = True) -> bool:
    """
    Show container logs.

    Args:
        client: Docker client
        follow: If True, follow logs in real-time

    Returns:
        True if successful, False otherwise
    """
    try:
        if not container_exists(client):
            console.print(f"[bold red]✗ Container '{CONTAINER_NAME}' does not exist.[/bold red]")
            return False

        console.print(f"[blue]Showing logs for:[/blue] {CONTAINER_NAME}")
        if follow:
            console.print("[dim]Press Ctrl+C to exit[/dim]\n")

        container = client.containers.get(CONTAINER_NAME)

        if follow:
            for line in container.logs(stream=True, follow=True):
                try:
                    console.print(line.decode('utf-8'), end='')
                except KeyboardInterrupt:
                    console.print("\n[yellow]Stopped following logs.[/yellow]")
                    break
        else:
            logs = container.logs().decode('utf-8')
            console.print(logs)

        return True

    except NotFound:
        console.print(f"[bold red]✗ Container '{CONTAINER_NAME}' not found.[/bold red]")
        return False
    except APIError as e:
        console.print(f"[bold red]✗ Failed to get logs:[/bold red] {str(e)}", style="red")
        return False


def show_status(client: docker.DockerClient) -> bool:  # noqa: C901
    """
    Show container status and resource usage.

    Args:
        client: Docker client

    Returns:
        True if successful, False otherwise
    """
    console.print("[bold blue]Container Status:[/bold blue]\n")
    if not container_exists(client):
        console.print("[yellow]!  Container does not exist. Use 'start' command to create it.[/yellow]")
        return True

    try:
        container = client.containers.get(CONTAINER_NAME)
        if container.status == 'running':
            console.print("[bold green]✓ Container is RUNNING[/bold green]\n")

            info_table = Table(show_header=True, header_style="bold cyan")
            info_table.add_column("Property", style="yellow")
            info_table.add_column("Value", style="green")
            info_table.add_row("Container Name", container.name)
            info_table.add_row("Container ID", container.short_id)
            info_table.add_row("Status", container.status)
            info_table.add_row("Created", container.attrs['Created'][:19])

            from datetime import datetime, timezone
            import re
            started_at = container.attrs['State'].get('StartedAt')
            if started_at:
                # Python 3.6 compatible: Manual ISO format parsing instead of fromisoformat()
                started_at = re.sub(r'(\.\d{6})\d+', r'\1', started_at)
                # Parse ISO 8601 format manually for Python 3.6 compatibility
                # Format: 2024-01-01T10:00:00.123456Z or 2024-01-01T10:00:00.123456+00:00
                datetime_str = started_at.replace('Z', '').replace('+00:00', '').replace('-00:00', '')
                try:
                    if '.' in datetime_str:
                        # Has microseconds: 2024-01-01T10:00:00.123456
                        start_time = datetime.strptime(datetime_str, '%Y-%m-%dT%H:%M:%S.%f')
                    else:
                        # No microseconds: 2024-01-01T10:00:00
                        start_time = datetime.strptime(datetime_str, '%Y-%m-%dT%H:%M:%S')
                    # Make timezone-aware for UTC
                    start_time = start_time.replace(tzinfo=timezone.utc)
                except ValueError:
                    # Fallback if parsing fails
                    start_time = datetime.now(timezone.utc)
                uptime = datetime.now(timezone.utc) - start_time
                days, hours = uptime.days, uptime.seconds // 3600
                minutes = (uptime.seconds % 3600) // 60
                uptime_str = f"{days}d {hours}h {minutes}m" if days > 0 else (f"{hours}h {minutes}m" if hours > 0 else f"{minutes}m")
                info_table.add_row("Uptime", uptime_str)

            ports = container.attrs.get('NetworkSettings', {}).get('Ports', {})
            port_str = ", ".join([f"{k} -> {v[0]['HostPort']}" for k, v in ports.items() if v])
            info_table.add_row("Ports", port_str if port_str else "None")
            console.print(info_table)
            console.print()

            health = container.attrs.get('State', {}).get('Health', {}).get('Status')
            if health:
                health_color = "green" if health == "healthy" else "yellow"
                console.print(f"[{health_color}]Health Status: {health}[/{health_color}]\n")

            try:
                stats = container.stats(stream=False)
                cpu_delta = stats['cpu_stats']['cpu_usage']['total_usage'] - stats['precpu_stats']['cpu_usage']['total_usage']
                system_delta = stats['cpu_stats']['system_cpu_usage'] - stats['precpu_stats']['system_cpu_usage']
                cpu_percent = (cpu_delta / system_delta) * stats['cpu_stats'].get('online_cpus', 1) * 100.0 if system_delta > 0 and cpu_delta > 0 else 0.0
                mem_usage = stats['memory_stats'].get('usage', 0) / (1024 * 1024)
                mem_limit = stats['memory_stats'].get('limit', 0) / (1024 * 1024)

                resource_table = Table(show_header=True, header_style="bold cyan")
                resource_table.add_column("Resource", style="yellow")
                resource_table.add_column("Usage", style="green")
                resource_table.add_row("CPU", f"{cpu_percent:.2f}%")
                resource_table.add_row("Memory", f"{mem_usage:.1f} MB / {mem_limit:.1f} MB")
                console.print(resource_table)
                console.print()
            except Exception as e:
                console.print(f"[yellow]!  Could not fetch resource usage: {str(e)}[/yellow]")

            try:
                logs = container.logs(tail=100, timestamps=True).decode('utf-8', errors='ignore')
                error_lines = [
                    line[:97] + '...' if len(line) > 100 else line
                    for line in logs.split('\n')
                    if any(p in line.lower() for p in ['error', 'critical', 'exception', 'traceback', 'failed'])
                ]

                if error_lines:
                    console.print("[bold yellow]Recent Errors (last 100 log lines):[/bold yellow]")
                    for error_line in error_lines[-5:]:
                        console.print(f"[red]  {error_line}[/red]")
                    if len(error_lines) > 5:
                        console.print(f"[yellow]  ... and {len(error_lines) - 5} more errors[/yellow]")
                    console.print()
                else:
                    console.print("[green]✓ No recent errors found[/green]\n")
            except Exception as e:
                console.print(f"[yellow]!  Could not fetch recent logs: {str(e)}[/yellow]\n")
        else:
            console.print(f"[yellow]!  Container exists but is NOT RUNNING (Status: {container.status})[/yellow]")
            console.print("Use 'start' command to start it.")
        return True
    except NotFound:
        console.print(f"[bold red]✗ Container '{CONTAINER_NAME}' not found.[/bold red]")
        return False
    except APIError as e:
        console.print(f"[bold red]✗ Failed to get status:[/bold red] {str(e)}", style="red")
        return False


def remove_container(client: docker.DockerClient, force: bool = False, force_remove: bool = False) -> bool:  # noqa: C901
    """
    Remove container and optionally image with user confirmation.

    Args:
        client: Docker client
        force: If True, skip confirmation
        force_remove: If True, force remove even if container is running/restarting

    Returns:
        True if successful, False otherwise
    """
    try:
        container_exists_flag = container_exists(client)
        try:
            client.images.get(f"{IMAGE_NAME}:latest")
            image_exists_flag = True
        except ImageNotFound:
            image_exists_flag = False

        if not container_exists_flag and not image_exists_flag:
            console.print("[yellow]!  Neither container nor image exist.[/yellow]")
            return True

        remove_image = False
        if not force:
            console.print(f"[bold yellow]What would you like to remove? (Logs preserved in {LOGS_DIR})[/bold yellow]")
            if container_exists_flag and image_exists_flag:
                console.print("[cyan]1.[/cyan] Container only\n[cyan]2.[/cyan] Container and image\n[cyan]3.[/cyan] Cancel")
                choice = Prompt.ask("Select option", choices=["1", "2", "3"], default="3")
                if choice == "3":
                    console.print("[blue]Cancelled.[/blue]")
                    return False
                remove_image = (choice == "2")
            elif container_exists_flag:
                if not confirm_action("Remove container?", False):
                    console.print("[blue]Cancelled.[/blue]")
                    return False
            elif image_exists_flag:
                if not confirm_action("Remove image?", False):
                    console.print("[blue]Cancelled.[/blue]")
                    return False

        if container_exists_flag:
            console.print(f"[blue]Removing container: {CONTAINER_NAME}[/blue]")
            container = client.containers.get(CONTAINER_NAME)
            if not force_remove and container.status in ['running', 'restarting']:
                try:
                    console.print("[blue]Stopping container first...[/blue]")
                    container.stop(timeout=10)
                except Exception as e:
                    console.print(f"[yellow]!  Could not stop: {e}. Attempting force removal...[/yellow]")
                    force_remove = True
            container.remove(force=force_remove)
            console.print("[bold green]✓ Container removed![/bold green]")

        if remove_image and image_exists_flag:
            try:
                console.print(f"[blue]Removing image: {IMAGE_NAME}:latest[/blue]")
                client.images.remove(f"{IMAGE_NAME}:latest", force=force_remove)
                console.print("[bold green]✓ Image removed![/bold green]")
            except APIError as e:
                console.print(f"[bold red]✗ Failed to remove image: {str(e)}[/bold red]")
                if not force_remove:
                    console.print("[yellow]💡 Tip: Try --force-remove flag[/yellow]")
                return False
        return True
    except NotFound:
        console.print(f"[yellow]!  Container '{CONTAINER_NAME}' does not exist.[/yellow]")
        return True
    except APIError as e:
        console.print(f"[bold red]✗ Failed to remove: {str(e)}[/bold red]")
        console.print("[yellow]💡 Tip: Try --force-remove flag[/yellow]")
        return False


# Monitoring Operations
def show_monitor(client: docker.DockerClient, args: List[str]) -> bool:
    """
    Show monitoring dashboard.

    Args:
        client: Docker client
        args: Arguments to pass to monitor command

    Returns:
        True if successful, False otherwise
    """
    try:
        if not container_running(client):
            console.print("[bold red]✗ Container is not running.[/bold red]")
            return False

        console.print("[blue]Opening monitoring dashboard...[/blue]\n")

        # Run scripts/monitor_dashboard.py inside container
        container = client.containers.get(CONTAINER_NAME)
        cmd = ['python', 'scripts/monitor_dashboard.py'] + args

        result = container.exec_run(cmd, stream=True, tty=True)
        for line in result.output:
            console.print(line.decode('utf-8'), end='')

        return True

    except Exception as e:
        console.print(f"[bold red]✗ Failed to show monitor:[/bold red] {str(e)}", style="red")
        return False


def export_monitoring_data(filename: str = "monitoring_export.csv") -> bool:
    """
    Export monitoring data to CSV.

    Args:
        filename: Output filename

    Returns:
        True if successful, False otherwise
    """
    try:
        port = get_port_from_config()
        host = get_host_ip()

        console.print(f"[blue]Exporting monitoring data to:[/blue] {filename}")

        response = requests.get(f"http://{host}:{port}/monitor/export/csv", timeout=30)
        response.raise_for_status()

        with open(filename, 'w') as f:
            f.write(response.text)

        console.print(f"[bold green]✓ Data exported to: {filename}[/bold green]")
        return True

    except Exception as e:
        console.print(f"[bold red]✗ Failed to export data:[/bold red] {str(e)}", style="red")
        return False


# Testing Operations
def test_webhook() -> bool:
    """
    Send test webhook to container.

    Returns:
        True if successful, False otherwise
    """
    try:
        port = get_port_from_config()
        host = get_host_ip()

        console.print("[blue]Testing GitLab webhook endpoint with sample payload...[/blue]")
        console.print(f"[blue]Target:[/blue] http://{host}:{port}/webhook/gitlab\n")

        # Sample GitLab pipeline webhook payload
        sample_payload = {
            "object_kind": "pipeline",
            "object_attributes": {
                "id": 12345,
                "status": "success",
                "stages": ["build", "test"],
                "created_at": "2024-01-01 10:00:00 UTC",
                "finished_at": "2024-01-01 10:15:00 UTC"
            },
            "project": {
                "id": 100,
                "name": "test-project",
                "web_url": "https://gitlab.com/test/project"
            },
            "builds": [
                {
                    "id": 1001,
                    "name": "build-job",
                    "stage": "build",
                    "status": "success"
                },
                {
                    "id": 1002,
                    "name": "test-job",
                    "stage": "test",
                    "status": "success"
                }
            ]
        }

        response = requests.post(
            f"http://{host}:{port}/webhook/gitlab",
            json=sample_payload,
            headers={
                "Content-Type": "application/json",
                "X-Gitlab-Event": "Pipeline Hook"
            },
            timeout=30
        )

        response.raise_for_status()
        result = response.json()

        console.print("[bold green]✓ Test webhook sent successfully![/bold green]")
        console.print("\n[bold]Response:[/bold]")
        console.print(json.dumps(result, indent=2))
        console.print("\n[dim]Check logs with: ./manage_container.py logs[/dim]")

        return True

    except Exception as e:
        console.print(f"[bold red]✗ Failed to send test webhook:[/bold red] {str(e)}", style="red")
        return False


# CLI Commands (argparse)
def cmd_config(args):
    """Display and validate configuration from .env file."""

    # Load configuration
    cfg = load_config(Path(args.env_file))
    if cfg is None:
        console.print(f"[bold red]✗ Configuration file not found: {args.env_file}[/bold red]")
        console.print(f"Please create {args.env_file} from .env.example:")
        console.print(f"  cp .env.example {args.env_file}")
        sys.exit(EXIT_CONFIG_ERROR)

    # Display configuration
    if not args.quiet:
        show_config_table(cfg, args.quiet)

    # Validate
    errors, warnings = validate_config(cfg)
    show_validation_results(errors, warnings)

    # Exit on errors
    if errors:
        console.print("[bold red]✗ Configuration has critical errors. Please fix .env file.[/bold red]")
        sys.exit(EXIT_CONFIG_ERROR)

    if args.validate_only:
        if warnings:
            console.print("[bold green]✓ Configuration is valid (but has warnings)[/bold green]")
        else:
            console.print("[bold green]✓ Configuration is valid[/bold green]")

    sys.exit(EXIT_SUCCESS)


def cmd_build(args):
    """Build the Docker image."""

    client = get_docker_client()
    if not client:
        sys.exit(EXIT_DOCKER_ERROR)

    success = build_image(client)
    sys.exit(EXIT_SUCCESS if success else EXIT_DOCKER_ERROR)


def cmd_start(args):
    """Start the container (creates if needed)."""

    # Check .env file
    if not Path(ENV_FILE).exists():
        console.print(f"[bold red]✗ Configuration file not found: {ENV_FILE}[/bold red]")
        console.print(f"Please create {ENV_FILE} from .env.example:")
        console.print(f"  cp .env.example {ENV_FILE}")
        sys.exit(EXIT_CONFIG_ERROR)

    # Load and validate configuration
    cfg = load_config()
    if cfg is None:
        sys.exit(EXIT_CONFIG_ERROR)

    # Display configuration
    show_config_table(cfg)

    # Validate
    errors, warnings = validate_config(cfg)
    show_validation_results(errors, warnings)

    if errors:
        console.print("[bold red]✗ Configuration has critical errors. Please fix .env file.[/bold red]")
        sys.exit(EXIT_CONFIG_ERROR)

    # Confirm
    if not confirm_action("Continue with this configuration?", args.yes):
        console.print("[blue]Cancelled by user.[/blue]")
        sys.exit(EXIT_CANCELLED)

    # Start container
    client = get_docker_client()
    if not client:
        sys.exit(EXIT_DOCKER_ERROR)

    success = start_container(client, cfg, skip_confirm=args.yes)
    sys.exit(EXIT_SUCCESS if success else EXIT_DOCKER_ERROR)


def cmd_stop(args):
    """Stop the container."""

    client = get_docker_client()
    if not client:
        sys.exit(EXIT_DOCKER_ERROR)

    success = stop_container(client)
    sys.exit(EXIT_SUCCESS if success else EXIT_DOCKER_ERROR)


def cmd_restart(args):
    """Restart the container."""

    # Load config
    cfg = load_config()
    if cfg is None:
        console.print(f"[bold red]✗ Configuration file not found: {ENV_FILE}[/bold red]")
        sys.exit(EXIT_CONFIG_ERROR)

    client = get_docker_client()
    if not client:
        sys.exit(EXIT_DOCKER_ERROR)

    success = restart_container(client, cfg)
    sys.exit(EXIT_SUCCESS if success else EXIT_DOCKER_ERROR)


def cmd_logs(args):
    """View container logs."""

    client = get_docker_client()
    if not client:
        sys.exit(EXIT_DOCKER_ERROR)

    success = show_logs(client, args.follow)
    sys.exit(EXIT_SUCCESS if success else EXIT_DOCKER_ERROR)


def cmd_status(args):
    """Show container status and resource usage."""

    client = get_docker_client()
    if not client:
        sys.exit(EXIT_DOCKER_ERROR)

    success = show_status(client)
    sys.exit(EXIT_SUCCESS if success else EXIT_DOCKER_ERROR)


def cmd_remove(args):
    """Remove the container (keeps logs)."""

    client = get_docker_client()
    if not client:
        sys.exit(EXIT_DOCKER_ERROR)

    force_remove = getattr(args, 'force_remove', False)
    success = remove_container(client, args.force, force_remove=force_remove)
    sys.exit(EXIT_SUCCESS if success else EXIT_DOCKER_ERROR)


def cmd_monitor(args):
    """View monitoring dashboard."""

    client = get_docker_client()
    if not client:
        sys.exit(EXIT_DOCKER_ERROR)

    success = show_monitor(client, args.monitor_args)
    sys.exit(EXIT_SUCCESS if success else EXIT_ERROR)


def cmd_export(args):
    """Export monitoring data to CSV."""

    success = export_monitoring_data(args.filename)
    sys.exit(EXIT_SUCCESS if success else EXIT_ERROR)


def cmd_test(args):
    """Send test webhook to the container."""

    success = test_webhook()
    sys.exit(EXIT_SUCCESS if success else EXIT_ERROR)


def main():
    """Main CLI entry point using argparse."""
    parser = argparse.ArgumentParser(
        prog='manage_container.py',
        description='GitLab Pipeline Log Extractor - Container Management Script',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s build                    # Build Docker image
  %(prog)s start                    # Start container with confirmation
  %(prog)s start --yes              # Start container without confirmation
  %(prog)s logs                     # Follow logs in real-time
  %(prog)s logs --no-follow         # Show logs without following
  %(prog)s status                   # Show container status
  %(prog)s monitor --hours 24       # Show monitoring dashboard
  %(prog)s export data.csv          # Export monitoring data
  %(prog)s test                     # Send test webhook
  %(prog)s remove                   # Remove container/image (interactive)

For more information, see OPERATIONS.md
        """
    )

    parser.add_argument('--version', action='version', version='%(prog)s 2.0.0')
    # Note: required=True is not supported in Python 3.6, added in Python 3.7
    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    parser_config = subparsers.add_parser('config', help='Display and validate configuration')
    parser_config.add_argument('--env-file', default=ENV_FILE, help='Path to .env file')
    parser_config.add_argument('-q', '--quiet', action='store_true', help='Minimal output')
    parser_config.add_argument('--validate-only', action='store_true', help='Only validate')
    parser_config.set_defaults(func=cmd_config)

    parser_build = subparsers.add_parser('build', help='Build the Docker image')
    parser_build.set_defaults(func=cmd_build)

    parser_start = subparsers.add_parser('start', help='Start container (creates if needed)')
    parser_start.add_argument('-y', '--yes', action='store_true', help='Auto-confirm')
    parser_start.set_defaults(func=cmd_start)

    parser_stop = subparsers.add_parser('stop', help='Stop the container')
    parser_stop.set_defaults(func=cmd_stop)

    parser_restart = subparsers.add_parser('restart', help='Restart the container')
    parser_restart.set_defaults(func=cmd_restart)

    parser_logs = subparsers.add_parser('logs', help='View container logs')
    parser_logs.add_argument('-f', '--follow', action='store_true', default=True, help='Follow logs')
    parser_logs.add_argument('--no-follow', dest='follow', action='store_false', help='No follow')
    parser_logs.set_defaults(func=cmd_logs)

    parser_status = subparsers.add_parser('status', help='Show container status')
    parser_status.set_defaults(func=cmd_status)

    parser_remove = subparsers.add_parser('remove', help='Remove container/image')
    parser_remove.add_argument('-f', '--force', action='store_true', help='Skip confirmation')
    parser_remove.add_argument('--force-remove', action='store_true', help='Force remove if running')
    parser_remove.set_defaults(func=cmd_remove)

    parser_monitor = subparsers.add_parser('monitor', help='View monitoring dashboard')
    parser_monitor.add_argument('monitor_args', nargs='*', help='Monitor args')
    parser_monitor.set_defaults(func=cmd_monitor)

    parser_export = subparsers.add_parser('export', help='Export monitoring data')
    parser_export.add_argument('filename', nargs='?', default='monitoring_export.csv', help='Output filename')
    parser_export.set_defaults(func=cmd_export)

    parser_test = subparsers.add_parser('test', help='Send test webhook')
    parser_test.set_defaults(func=cmd_test)

    args = parser.parse_args()

    # Handle Python 3.6 compatibility - required=True not supported in add_subparsers
    if not hasattr(args, 'func') or args.command is None:
        parser.print_help()
        sys.exit(EXIT_ERROR)

    args.func(args)


if __name__ == "__main__":
    main()
