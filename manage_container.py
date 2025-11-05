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
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import subprocess
import time

try:
    import docker
    from docker.errors import DockerException, ImageNotFound, NotFound, APIError
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from rich.prompt import Prompt
    from rich import print as rprint
    from dotenv import dotenv_values
except ImportError as e:
    print(f"Error: Required package not found: {e}")
    print("Please install dependencies: pip install -r requirements.txt")
    sys.exit(1)


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

# Initialize console for rich output
console = Console()


# ============================================================================
# Configuration Management (merged from show_config.py)
# ============================================================================

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


def get_host_ip() -> str:
    """
    Get the local IP address of the host machine.

    Returns:
        IP address as string, or '127.0.0.1' if unable to determine
    """
    try:
        # Create a socket to determine the local IP
        # This doesn't actually connect, just determines which interface would be used
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        # Fallback to localhost if unable to determine IP
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


def validate_config(config: Dict[str, str]) -> Tuple[List[str], List[str]]:
    """
    Validate configuration and return lists of errors and warnings.

    Args:
        config: Configuration dictionary

    Returns:
        Tuple of (errors, warnings) lists
    """
    errors = []
    warnings = []

    # Critical validations (errors)
    if not config.get('GITLAB_URL'):
        errors.append("GITLAB_URL is not set (required)")

    if not config.get('GITLAB_TOKEN'):
        errors.append("GITLAB_TOKEN is not set (required)")

    # Non-critical validations (warnings)
    if not config.get('WEBHOOK_SECRET'):
        warnings.append("WEBHOOK_SECRET is not set (webhooks will be unauthenticated)")

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
    env_table = Table(title="Configuration Review", show_header=True, header_style="bold cyan")
    env_table.add_column("Setting", style="yellow", width=20)
    env_table.add_column("Value", style="green")

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

    # Container Configuration
    container_table = Table(show_header=True, header_style="bold cyan")
    container_table.add_column("Container Setting", style="yellow", width=20)
    container_table.add_column("Value", style="green")

    container_table.add_row("Container Name", CONTAINER_NAME)
    container_table.add_row("Image Name", IMAGE_NAME)
    container_table.add_row("Logs Volume", f"{Path.cwd()}/{LOGS_DIR}")

    console.print(container_table)
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


# ============================================================================
# Docker Operations
# ============================================================================

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
    Build Docker image.

    Args:
        client: Docker client

    Returns:
        True if successful, False otherwise
    """
    import time

    try:
        console.print(f"[bold blue]Building Docker image:[/bold blue] {IMAGE_NAME}")

        # Show shell equivalent
        console.print("[dim]Shell equivalent: docker build -t gitlab-log-extractor:latest --rm .[/dim]\n")

        start_time = time.time()

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task("Building image...", total=None)

            # Build image
            image, build_logs = client.images.build(
                path=".",
                tag=IMAGE_NAME,
                rm=True
            )

            progress.update(task, completed=True)

        elapsed_time = time.time() - start_time

        console.print(f"[bold green]✓ Image built successfully![/bold green]")
        console.print(f"[green]  Build time: {elapsed_time:.1f} seconds[/green]")
        return True

    except APIError as e:
        console.print(f"[bold red]✗ Build failed:[/bold red] {str(e)}", style="red")
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

        # Check if container already exists
        if container_exists(client):
            if container_running(client):
                console.print("[yellow]!  Container is already running.[/yellow]")
                console.print("Use 'restart' command to restart it.")
                return True
            else:
                console.print("[blue]Starting existing container...[/blue]")
                container = client.containers.get(CONTAINER_NAME)
                container.start()
                console.print("[bold green]✓ Container started![/bold green]")
                console.print(f"[dim]Shell equivalent: docker start {CONTAINER_NAME}[/dim]")
                show_endpoints(port)
                return True

        # Create logs directory
        Path(LOGS_DIR).mkdir(parents=True, exist_ok=True)

        # Start new container
        console.print(f"[bold blue]Starting new container:[/bold blue] {CONTAINER_NAME}")
        console.print(f"[blue]Using port:[/blue] {port}")

        container = client.containers.run(
            IMAGE_NAME,
            name=CONTAINER_NAME,
            detach=True,
            ports={f'{port}/tcp': port},
            volumes={
                str(Path.cwd() / LOGS_DIR): {'bind': '/app/logs', 'mode': 'rw'},
                str(Path.cwd() / ENV_FILE): {'bind': '/app/.env', 'mode': 'ro'}
            },
            restart_policy={"Name": "unless-stopped"}
        )

        console.print("[bold green]✓ Container started successfully![/bold green]")

        # Show shell equivalent
        logs_path = Path.cwd() / LOGS_DIR
        env_path = Path.cwd() / ENV_FILE
        shell_cmd = (
            f"docker run -d --name {CONTAINER_NAME} "
            f"-p {port}:{port} "
            f"-v {logs_path}:/app/logs "
            f"-v {env_path}:/app/.env:ro "
            f"--restart unless-stopped "
            f"{IMAGE_NAME}"
        )
        console.print(f"[dim]Shell equivalent:[/dim]")
        console.print(f"[dim]{shell_cmd}[/dim]\n")

        show_endpoints(port)
        return True

    except ImageNotFound:
        console.print(f"[bold red]✗ Image '{IMAGE_NAME}' not found.[/bold red]")
        console.print("Run 'build' command first to create the image.")
        return False
    except APIError as e:
        console.print(f"[bold red]✗ Failed to start container:[/bold red] {str(e)}", style="red")
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
    Restart container.

    Args:
        client: Docker client
        config: Configuration dictionary

    Returns:
        True if successful, False otherwise
    """
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


def show_status(client: docker.DockerClient) -> bool:
    """
    Show container status and resource usage.

    Args:
        client: Docker client

    Returns:
        True if successful, False otherwise
    """
    console.print("[bold blue]Container Status:[/bold blue]\n")

    if not container_exists(client):
        console.print("[yellow]!  Container does not exist.[/yellow]")
        console.print("Use 'start' command to create it.")
        return True

    try:
        container = client.containers.get(CONTAINER_NAME)

        if container.status == 'running':
            console.print("[bold green]✓ Container is RUNNING[/bold green]\n")

            # Container info
            info_table = Table(show_header=True, header_style="bold cyan")
            info_table.add_column("Property", style="yellow")
            info_table.add_column("Value", style="green")

            info_table.add_row("Container Name", container.name)
            info_table.add_row("Container ID", container.short_id)
            info_table.add_row("Status", container.status)
            info_table.add_row("Created", container.attrs['Created'][:19])

            # Calculate uptime
            from datetime import datetime, timezone
            import re
            started_at = container.attrs['State'].get('StartedAt')
            if started_at:
                # Docker returns nanosecond precision, but Python only handles microseconds
                # Truncate to 6 decimal places: 2025-11-05T09:40:28.666285451+00:00 -> 2025-11-05T09:40:28.666285+00:00
                started_at = re.sub(r'(\.\d{6})\d+', r'\1', started_at)
                start_time = datetime.fromisoformat(started_at.replace('Z', '+00:00'))
                uptime = datetime.now(timezone.utc) - start_time
                days = uptime.days
                hours, remainder = divmod(uptime.seconds, 3600)
                minutes, seconds = divmod(remainder, 60)
                if days > 0:
                    uptime_str = f"{days}d {hours}h {minutes}m"
                elif hours > 0:
                    uptime_str = f"{hours}h {minutes}m"
                else:
                    uptime_str = f"{minutes}m {seconds}s"
                info_table.add_row("Uptime", uptime_str)

            # Ports
            ports = container.attrs.get('NetworkSettings', {}).get('Ports', {})
            port_str = ", ".join([f"{k} -> {v[0]['HostPort']}" for k, v in ports.items() if v])
            info_table.add_row("Ports", port_str if port_str else "None")

            console.print(info_table)
            console.print()

            # Health status
            health = container.attrs.get('State', {}).get('Health', {}).get('Status')
            if health:
                health_color = "green" if health == "healthy" else "yellow"
                console.print(f"[{health_color}]Health Status: {health}[/{health_color}]")
                console.print()

            # Resource usage
            try:
                stats = container.stats(stream=False)
                cpu_percent = calculate_cpu_percent(stats)
                mem_usage = stats['memory_stats'].get('usage', 0) / (1024 * 1024)  # MB
                mem_limit = stats['memory_stats'].get('limit', 0) / (1024 * 1024)  # MB

                resource_table = Table(show_header=True, header_style="bold cyan")
                resource_table.add_column("Resource", style="yellow")
                resource_table.add_column("Usage", style="green")

                resource_table.add_row("CPU", f"{cpu_percent:.2f}%")
                resource_table.add_row("Memory", f"{mem_usage:.1f} MB / {mem_limit:.1f} MB")

                console.print(resource_table)
                console.print()

            except Exception as e:
                console.print(f"[yellow]!  Could not fetch resource usage: {str(e)}[/yellow]")

            # Recent errors
            try:
                # Get last 100 lines of logs
                logs = container.logs(tail=100, timestamps=True).decode('utf-8', errors='ignore')
                error_lines = []
                for line in logs.split('\n'):
                    # Look for ERROR, CRITICAL, or exception patterns
                    line_lower = line.lower()
                    if any(pattern in line_lower for pattern in ['error', 'critical', 'exception', 'traceback', 'failed']):
                        # Limit line length for display
                        if len(line) > 100:
                            line = line[:97] + '...'
                        error_lines.append(line)

                if error_lines:
                    console.print("[bold yellow]Recent Errors (last 100 log lines):[/bold yellow]")
                    # Show up to 5 most recent errors
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
            console.print(f"[yellow]!  Container exists but is NOT RUNNING[/yellow]")
            console.print(f"Status: {container.status}\n")
            console.print("Use 'start' command to start it.")

        return True

    except NotFound:
        console.print(f"[bold red]✗ Container '{CONTAINER_NAME}' not found.[/bold red]")
        return False
    except APIError as e:
        console.print(f"[bold red]✗ Failed to get status:[/bold red] {str(e)}", style="red")
        return False


def calculate_cpu_percent(stats: dict) -> float:
    """
    Calculate CPU percentage from Docker stats.

    Args:
        stats: Docker stats dictionary

    Returns:
        CPU percentage
    """
    cpu_delta = stats['cpu_stats']['cpu_usage']['total_usage'] - \
                stats['precpu_stats']['cpu_usage']['total_usage']
    system_delta = stats['cpu_stats']['system_cpu_usage'] - \
                   stats['precpu_stats']['system_cpu_usage']

    if system_delta > 0 and cpu_delta > 0:
        cpu_count = stats['cpu_stats'].get('online_cpus', 1)
        return (cpu_delta / system_delta) * cpu_count * 100.0
    return 0.0


def remove_container(client: docker.DockerClient, force: bool = False, force_remove: bool = False) -> bool:
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
        # Check what exists
        container_exists_flag = container_exists(client)

        try:
            client.images.get(IMAGE_NAME)
            image_exists_flag = True
        except ImageNotFound:
            image_exists_flag = False

        if not container_exists_flag and not image_exists_flag:
            console.print(f"[yellow]!  Neither container nor image exist.[/yellow]")
            return True

        # Ask user what to remove (if not forced)
        remove_image = False
        if not force:
            console.print(f"[bold yellow]What would you like to remove?[/bold yellow]")
            console.print(f"  Logs will be preserved in {LOGS_DIR}")
            console.print()

            if container_exists_flag and image_exists_flag:
                console.print("[cyan]1.[/cyan] Container only")
                console.print("[cyan]2.[/cyan] Container and image")
                console.print("[cyan]3.[/cyan] Cancel")

                choice = Prompt.ask("Select option", choices=["1", "2", "3"], default="3")

                if choice == "3":
                    console.print("[blue]Cancelled.[/blue]")
                    return False
                elif choice == "2":
                    remove_image = True
            elif container_exists_flag:
                console.print("[cyan]Container exists, image does not.[/cyan]")
                if not confirm_action("Remove container?", False):
                    console.print("[blue]Cancelled.[/blue]")
                    return False
            elif image_exists_flag:
                console.print("[cyan]Image exists, container does not.[/cyan]")
                if not confirm_action("Remove image?", False):
                    console.print("[blue]Cancelled.[/blue]")
                    return False

        # Remove container if it exists
        if container_exists_flag:
            console.print(f"[blue]Removing container:[/blue] {CONTAINER_NAME}")
            container = client.containers.get(CONTAINER_NAME)

            # Try to stop first (if not force_remove)
            if not force_remove:
                try:
                    if container.status in ['running', 'restarting']:
                        console.print("[blue]Stopping container first...[/blue]")
                        container.stop(timeout=10)
                except Exception as e:
                    console.print(f"[yellow]!  Could not stop container: {e}[/yellow]")
                    console.print("[yellow]Attempting force removal...[/yellow]")
                    force_remove = True

            # Remove container (with force if needed)
            container.remove(force=force_remove)

            console.print("[bold green]✓ Container removed![/bold green]")
            if force_remove:
                console.print(f"[dim]Shell equivalent: docker rm -f {CONTAINER_NAME}[/dim]")
            else:
                console.print(f"[dim]Shell equivalent: docker rm {CONTAINER_NAME}[/dim]")

        # Remove image if requested and it exists
        if remove_image and image_exists_flag:
            try:
                console.print(f"[blue]Removing image:[/blue] {IMAGE_NAME}")
                client.images.remove(IMAGE_NAME, force=force_remove)
                console.print("[bold green]✓ Image removed![/bold green]")
                console.print(f"[dim]Shell equivalent: docker rmi {IMAGE_NAME}[/dim]")
            except APIError as e:
                console.print(f"[bold red]✗ Failed to remove image:[/bold red] {str(e)}", style="red")
                if not force_remove:
                    console.print("[yellow]💡 Tip: Try running with --force-remove flag[/yellow]")
                return False

        return True

    except NotFound:
        console.print(f"[yellow]!  Container '{CONTAINER_NAME}' does not exist.[/yellow]")
        return True
    except APIError as e:
        console.print(f"[bold red]✗ Failed to remove:[/bold red] {str(e)}", style="red")
        console.print("[yellow]💡 Tip: Try running with --force-remove flag[/yellow]")
        return False


# ============================================================================
# Monitoring Operations
# ============================================================================

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

        # Run monitor_dashboard.py inside container
        container = client.containers.get(CONTAINER_NAME)
        cmd = ['python', 'monitor_dashboard.py'] + args

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

        import requests
        response = requests.get(f"http://{host}:{port}/monitor/export/csv", timeout=30)
        response.raise_for_status()

        with open(filename, 'w') as f:
            f.write(response.text)

        console.print(f"[bold green]✓ Data exported to: {filename}[/bold green]")
        return True

    except Exception as e:
        console.print(f"[bold red]✗ Failed to export data:[/bold red] {str(e)}", style="red")
        return False


# ============================================================================
# Testing Operations
# ============================================================================

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

        import requests
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


# ============================================================================
# CLI Commands (argparse)
# ============================================================================

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

    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    subparsers.required = True

    # config command
    parser_config = subparsers.add_parser('config', help='Display and validate configuration')
    parser_config.add_argument('--env-file', default=ENV_FILE, help=f'Path to .env file (default: {ENV_FILE})')
    parser_config.add_argument('-q', '--quiet', action='store_true', help='Minimal output')
    parser_config.add_argument('--validate-only', action='store_true', help='Only validate configuration')
    parser_config.set_defaults(func=cmd_config)

    # build command
    parser_build = subparsers.add_parser('build', help='Build the Docker image')
    parser_build.set_defaults(func=cmd_build)

    # start command
    parser_start = subparsers.add_parser('start', help='Start the container (creates if needed)')
    parser_start.add_argument('-y', '--yes', action='store_true', help='Auto-confirm without prompting')
    parser_start.set_defaults(func=cmd_start)

    # stop command
    parser_stop = subparsers.add_parser('stop', help='Stop the container')
    parser_stop.set_defaults(func=cmd_stop)

    # restart command
    parser_restart = subparsers.add_parser('restart', help='Restart the container')
    parser_restart.set_defaults(func=cmd_restart)

    # logs command
    parser_logs = subparsers.add_parser('logs', help='View container logs')
    parser_logs.add_argument('-f', '--follow', action='store_true', default=True,
                            help='Follow logs in real-time (default: True)')
    parser_logs.add_argument('--no-follow', dest='follow', action='store_false',
                            help='Show logs without following')
    parser_logs.set_defaults(func=cmd_logs)

    # status command
    parser_status = subparsers.add_parser('status', help='Show container status and resource usage')
    parser_status.set_defaults(func=cmd_status)

    # remove command
    parser_remove = subparsers.add_parser('remove', help='Remove container and/or image (interactive)')
    parser_remove.add_argument('-f', '--force', action='store_true', help='Skip confirmation')
    parser_remove.add_argument('--force-remove', action='store_true', help='Force remove even if container is running/restarting')
    parser_remove.set_defaults(func=cmd_remove)

    # monitor command
    parser_monitor = subparsers.add_parser('monitor', help='View monitoring dashboard')
    parser_monitor.add_argument('monitor_args', nargs='*', help='Arguments to pass to monitor (e.g., --hours 24)')
    parser_monitor.set_defaults(func=cmd_monitor)

    # export command
    parser_export = subparsers.add_parser('export', help='Export monitoring data to CSV')
    parser_export.add_argument('filename', nargs='?', default='monitoring_export.csv',
                               help='Output filename (default: monitoring_export.csv)')
    parser_export.set_defaults(func=cmd_export)

    # test command
    parser_test = subparsers.add_parser('test', help='Send test webhook to the container')
    parser_test.set_defaults(func=cmd_test)

    # Parse arguments
    args = parser.parse_args()

    # Call the appropriate command function
    args.func(args)


if __name__ == "__main__":
    main()
