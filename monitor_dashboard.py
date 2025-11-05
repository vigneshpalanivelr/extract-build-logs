#!/usr/bin/env python3
"""
Pipeline Monitoring Dashboard

A command-line dashboard for viewing GitLab pipeline request statistics,
processing status, and exporting data for analysis.

Usage:
    python monitor_dashboard.py                     # Show dashboard
    python monitor_dashboard.py --recent 100        # Show recent 100 requests
    python monitor_dashboard.py --export output.csv  # Export to CSV
    python monitor_dashboard.py --pipeline 12345    # Show specific pipeline
"""

import sys
import argparse
from datetime import datetime
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from monitoring import PipelineMonitor
from tabulate import tabulate


def print_summary(monitor: PipelineMonitor, hours: int = 24):
    """Print summary statistics."""
    summary = monitor.get_summary(hours=hours)

    print("\n" + "=" * 70)
    print(f"  PIPELINE MONITORING DASHBOARD - Last {hours} Hours")
    print("=" * 70)
    print(f"\nGenerated: {summary['generated_at']}")
    print(f"\nOVERALL STATISTICS")
    print(f"   Total Requests:      {summary['total_requests']}")
    print(f"   Success Rate:        {summary['success_rate']}%")
    print(f"   Avg Processing Time: {summary['avg_processing_time_seconds']}s")
    print(f"   Total Jobs Processed: {summary['total_jobs_processed']}")

    # Status breakdown
    print(f"\nREQUESTS BY STATUS")
    status_data = [[status.title(), count] for status, count in summary['by_status'].items()]
    print(tabulate(status_data, headers=['Status', 'Count'], tablefmt='grid'))

    # Type breakdown
    if summary['by_type']:
        print(f"\nREQUESTS BY PIPELINE TYPE")
        type_data = [[ptype.title(), count] for ptype, count in summary['by_type'].items()]
        print(tabulate(type_data, headers=['Type', 'Count'], tablefmt='grid'))

    print("\n" + "=" * 70 + "\n")


def print_recent_requests(monitor: PipelineMonitor, limit: int = 50):
    """Print recent requests."""
    requests = monitor.get_recent_requests(limit=limit)

    print("\n" + "=" * 70)
    print(f"  RECENT PIPELINE REQUESTS (Last {limit})")
    print("=" * 70 + "\n")

    if not requests:
        print("No requests found.\n")
        return

    # Prepare table data
    table_data = []
    for req in requests:
        table_data.append([
            req['id'],
            req['timestamp'][:19],  # Trim milliseconds
            req['pipeline_id'] or '-',
            req['pipeline_type'] or '-',
            req['status'],
            f"{req['processing_time']:.1f}s" if req['processing_time'] else '-',
            f"{req['success_count'] or 0}/{req['job_count'] or 0}" if req['job_count'] else '-'
        ])

    headers = ['ID', 'Timestamp', 'Pipeline', 'Type', 'Status', 'Time', 'Jobs']
    print(tabulate(table_data, headers=headers, tablefmt='grid'))
    print(f"\nTotal: {len(requests)} requests\n")


def print_pipeline_details(monitor: PipelineMonitor, pipeline_id: int):
    """Print details for a specific pipeline."""
    requests = monitor.get_pipeline_requests(pipeline_id)

    print("\n" + "=" * 70)
    print(f"  PIPELINE #{pipeline_id} DETAILS")
    print("=" * 70 + "\n")

    if not requests:
        print(f"No requests found for pipeline {pipeline_id}.\n")
        return

    # Prepare table data
    table_data = []
    for req in requests:
        table_data.append([
            req['id'],
            req['timestamp'][:19],
            req['status'],
            f"{req['processing_time']:.1f}s" if req['processing_time'] else '-',
            f"{req['success_count']}/{req['error_count']}" if req['success_count'] is not None else '-',
            req['error_message'][:30] + '...' if req['error_message'] and len(req['error_message']) > 30 else req['error_message'] or '-'
        ])

    headers = ['Request ID', 'Timestamp', 'Status', 'Time', 'Success/Error', 'Error']
    print(tabulate(table_data, headers=headers, tablefmt='grid'))
    print(f"\nTotal: {len(requests)} requests for this pipeline\n")


def export_data(monitor: PipelineMonitor, filepath: str, hours: int = None):
    """Export data to CSV."""
    monitor.export_to_csv(filepath, hours=hours)
    print(f"\n✓ Data exported to: {filepath}")

    # Show what was exported
    import csv
    with open(filepath, 'r') as f:
        reader = csv.reader(f)
        rows = list(reader)
        print(f"  Total rows: {len(rows) - 1}")  # Exclude header
        print(f"  Columns: {len(rows[0]) if rows else 0}\n")


def main():
    parser = argparse.ArgumentParser(
        description='Pipeline Monitoring Dashboard',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python monitor_dashboard.py                        # Show 24-hour summary
  python monitor_dashboard.py --hours 48             # Show 48-hour summary
  python monitor_dashboard.py --recent 100           # Show recent 100 requests
  python monitor_dashboard.py --pipeline 12345       # Show pipeline details
  python monitor_dashboard.py --export data.csv      # Export all data
  python monitor_dashboard.py --export data.csv --hours 24  # Export last 24 hours
        """
    )

    parser.add_argument(
        '--db',
        default='./logs/monitoring.db',
        help='Path to monitoring database (default: ./logs/monitoring.db)'
    )
    parser.add_argument(
        '--hours',
        type=int,
        default=24,
        help='Number of hours to include in summary (default: 24)'
    )
    parser.add_argument(
        '--recent',
        type=int,
        metavar='N',
        help='Show N most recent requests'
    )
    parser.add_argument(
        '--pipeline',
        type=int,
        metavar='ID',
        help='Show details for specific pipeline ID'
    )
    parser.add_argument(
        '--export',
        metavar='FILE',
        help='Export data to CSV file'
    )

    args = parser.parse_args()

    # Check if database exists
    if not Path(args.db).exists():
        print(f"\n✗ Error: Monitoring database not found at {args.db}")
        print(f"   Make sure the webhook server has been running and processing requests.\n")
        sys.exit(1)

    # Initialize monitor
    try:
        monitor = PipelineMonitor(args.db)
    except Exception as e:
        print(f"\n✗ Error: Failed to initialize monitor: {e}\n")
        sys.exit(1)

    try:
        # Handle different commands
        if args.export:
            export_data(monitor, args.export, hours=args.hours if args.hours != 24 else None)
        elif args.recent:
            print_recent_requests(monitor, limit=args.recent)
        elif args.pipeline:
            print_pipeline_details(monitor, args.pipeline)
        else:
            print_summary(monitor, hours=args.hours)

    except KeyboardInterrupt:
        print("\n\nInterrupted by user.\n")
    except Exception as e:
        print(f"\n✗ Error: {e}\n")
        sys.exit(1)
    finally:
        monitor.close()


if __name__ == "__main__":
    main()
