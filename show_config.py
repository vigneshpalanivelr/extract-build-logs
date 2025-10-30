#!/usr/bin/env python3
"""
Configuration Display and Validation Script

Shows configuration values from .env file and asks for confirmation
before container operations. Validates required settings and displays
warnings for potential issues.

Exit Codes:
    0: Success (configuration valid and confirmed)
    1: Configuration error (critical validation failed)
    2: User cancelled (declined confirmation)
    3: File not found (.env missing)
"""

import argparse
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional

try:
    from dotenv import dotenv_values
    from tabulate import tabulate
except ImportError as e:
    print(f"Error: Required package not found: {e}")
    print("Please install: pip install python-dotenv tabulate")
    sys.exit(1)


# Exit codes
EXIT_SUCCESS = 0
EXIT_ERROR = 1
EXIT_CANCELLED = 2
EXIT_FILE_NOT_FOUND = 3


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
        return "Not Set"
    if len(value) <= show_chars:
        return "****"
    return f"{value[:show_chars]}****"


def load_config(env_file: Path = Path('.env')) -> Optional[Dict[str, str]]:
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
            warnings.append(f"RETRY_ATTEMPTS cannot be negative")
    except ValueError:
        warnings.append(f"RETRY_ATTEMPTS '{config.get('RETRY_ATTEMPTS')}' is not a valid number")

    try:
        retry_delay = int(config.get('RETRY_DELAY', '2'))
        if retry_delay < 0:
            warnings.append(f"RETRY_DELAY cannot be negative")
    except ValueError:
        warnings.append(f"RETRY_DELAY '{config.get('RETRY_DELAY')}' is not a valid number")

    return errors, warnings


def show_config_table(config: Dict[str, str], container_name: str = "gitlab-pipeline-extractor",
                     image_name: str = "gitlab-pipeline-extractor") -> None:
    """
    Display configuration in formatted tables.

    Args:
        config: Configuration dictionary
        container_name: Docker container name
        image_name: Docker image name
    """
    print("\n" + "=" * 70)
    print(" " * 20 + "📋 Configuration Review")
    print("=" * 70 + "\n")

    # Environment Configuration
    env_table = [
        ["GitLab URL", config.get('GITLAB_URL', 'Not Set')],
        ["GitLab Token", mask_value(config.get('GITLAB_TOKEN', 'Not Set'), 8)],
        ["Webhook Port", config.get('WEBHOOK_PORT', '8000')],
        ["Webhook Secret", mask_value(config.get('WEBHOOK_SECRET', ''), 4) if config.get('WEBHOOK_SECRET') else 'Not Set'],
        ["Log Level", config.get('LOG_LEVEL', 'INFO')],
        ["Log Directory", config.get('LOG_OUTPUT_DIR', './logs')],
        ["Retry Attempts", config.get('RETRY_ATTEMPTS', '3')],
        ["Retry Delay", f"{config.get('RETRY_DELAY', '2')}s"],
    ]

    print(tabulate(env_table,
                   headers=["Setting", "Value"],
                   tablefmt="fancy_grid",
                   colalign=("left", "left")))

    # Container Configuration
    print("\n" + "-" * 70)
    container_table = [
        ["Container Name", container_name],
        ["Image Name", image_name],
        ["Logs Volume", f"{Path.cwd()}/logs"],
    ]

    print(tabulate(container_table,
                   headers=["Container Setting", "Value"],
                   tablefmt="fancy_grid",
                   colalign=("left", "left")))

    print()


def show_validation_results(errors: List[str], warnings: List[str]) -> None:
    """
    Display validation errors and warnings.

    Args:
        errors: List of error messages
        warnings: List of warning messages
    """
    if errors or warnings:
        print("=" * 70)
        print(" " * 20 + "⚠️  Validation Results")
        print("=" * 70 + "\n")

    if errors:
        print("❌ ERRORS (must be fixed):")
        for error in errors:
            print(f"   • {error}")
        print()

    if warnings:
        print("⚠️  WARNINGS:")
        for warning in warnings:
            print(f"   • {warning}")
        print()


def confirm_action(message: str = "Continue with this configuration?") -> bool:
    """
    Ask user for confirmation.

    Args:
        message: Confirmation message to display

    Returns:
        True if user confirmed, False otherwise
    """
    while True:
        try:
            response = input(f"\n{message} (y/N): ").strip().lower()
            if response in ['y', 'yes']:
                return True
            elif response in ['n', 'no', '']:
                return False
            else:
                print("Please enter 'y' or 'n'")
        except (KeyboardInterrupt, EOFError):
            print("\n")
            return False


def parse_args() -> argparse.Namespace:
    """
    Parse command-line arguments.

    Returns:
        Parsed arguments namespace
    """
    parser = argparse.ArgumentParser(
        description="Display and validate configuration from .env file",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exit Codes:
  0 - Success (configuration valid and confirmed)
  1 - Configuration error (critical validation failed)
  2 - User cancelled (declined confirmation)
  3 - File not found (.env missing)

Examples:
  %(prog)s                    # Show config and ask for confirmation
  %(prog)s --yes              # Auto-confirm (skip prompt)
  %(prog)s --validate-only    # Only validate, don't ask for confirmation
  %(prog)s --quiet            # Minimal output, only show errors
  %(prog)s --env-file .env.prod  # Use different env file
        """
    )

    parser.add_argument(
        '-y', '--yes',
        action='store_true',
        help='Auto-confirm without prompting (for automation)'
    )

    parser.add_argument(
        '-q', '--quiet',
        action='store_true',
        help='Quiet mode - only show errors and warnings'
    )

    parser.add_argument(
        '--validate-only',
        action='store_true',
        help='Only validate configuration, do not ask for confirmation'
    )

    parser.add_argument(
        '--env-file',
        type=Path,
        default=Path('.env'),
        help='Path to .env file (default: .env)'
    )

    parser.add_argument(
        '--container-name',
        default='gitlab-pipeline-extractor',
        help='Docker container name (default: gitlab-pipeline-extractor)'
    )

    parser.add_argument(
        '--image-name',
        default='gitlab-pipeline-extractor',
        help='Docker image name (default: gitlab-pipeline-extractor)'
    )

    return parser.parse_args()


def main() -> int:
    """
    Main entry point.

    Returns:
        Exit code
    """
    args = parse_args()

    # Load configuration
    config = load_config(args.env_file)
    if config is None:
        print(f"❌ ERROR: Configuration file not found: {args.env_file}")
        print(f"Please create {args.env_file} from .env.example:")
        print(f"  cp .env.example {args.env_file}")
        return EXIT_FILE_NOT_FOUND

    # Display configuration (unless quiet mode)
    if not args.quiet:
        show_config_table(config, args.container_name, args.image_name)

    # Validate configuration
    errors, warnings = validate_config(config)

    # Always show validation results
    show_validation_results(errors, warnings)

    # If critical errors, exit
    if errors:
        print("❌ Configuration has critical errors. Please fix .env file.\n")
        return EXIT_ERROR

    # If validate-only mode, exit successfully
    if args.validate_only:
        if warnings:
            print("✅ Configuration is valid (but has warnings)\n")
        else:
            print("✅ Configuration is valid\n")
        return EXIT_SUCCESS

    # Ask for confirmation (unless --yes flag or quiet mode with no warnings)
    if args.yes:
        if not args.quiet:
            print("✅ Auto-confirmed (--yes flag)")
        return EXIT_SUCCESS

    if confirm_action():
        print("✅ Confirmed. Proceeding...\n")
        return EXIT_SUCCESS
    else:
        print("❌ Cancelled by user.\n")
        return EXIT_CANCELLED


if __name__ == "__main__":
    sys.exit(main())
