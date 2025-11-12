"""
Log Error Extractor

Extracts error sections from build logs with configurable context.
Provides surrounding lines before and after errors for better LLM analysis.
"""

import re
from typing import List, Tuple
import logging

logger = logging.getLogger(__name__)


class LogErrorExtractor:
    """
    Extracts error sections from logs with surrounding context.

    This extractor identifies error lines and captures N lines before and M lines after
    each error to provide meaningful context for LLM analysis.
    """

    # Error patterns to search for (case-insensitive)
    ERROR_PATTERNS = [
        'error', 'err!', 'failed', 'failure', 'exception', 'traceback',
        'syntaxerror', 'typeerror', 'assertionerror', 'valueerror',
        'fatal', 'critical', 'exit code', 'tests failed',
        'assertion failed', 'could not resolve', 'eresolve',
        'compilation error', 'build failed'
    ]

    def __init__(
        self,
        lines_before: int = 50,
        lines_after: int = 10,
        max_line_length: int = 1000
    ):
        """
        Initialize the error extractor.

        Args:
            lines_before: Number of context lines to include before each error (default: 50)
            lines_after: Number of context lines to include after each error (default: 10)
            max_line_length: Maximum length of individual lines before truncation (default: 1000)
        """
        self.lines_before = lines_before
        self.lines_after = lines_after
        self.max_line_length = max_line_length

    def extract_error_sections(self, log_content: str) -> List[str]:
        """
        Extract error sections with surrounding context from log content.

        Args:
            log_content: Raw log content as string

        Returns:
            List with a single string element containing all error lines with context,
            joined by newlines. Each line includes line numbers for reference.

        Example output:
            ["Line 100: npm install started\nLine 101: Resolving dependencies...\n...\nLine 150: npm ERR! code ERESOLVE"]
        """
        if not log_content:
            return []

        # Split log into lines and clean them
        all_lines = log_content.split('\n')
        cleaned_lines = [self._clean_line(line) for line in all_lines]

        # Find all error line indices
        error_indices = self._find_error_lines(cleaned_lines)

        if not error_indices:
            logger.debug("No error patterns found in log content")
            return []

        logger.debug(f"Found {len(error_indices)} error line(s) in log")

        # Extract sections with context and merge overlapping ranges
        sections = self._extract_sections_with_context(
            cleaned_lines,
            error_indices
        )

        # Join all lines into a single string with newlines and return as list with one element
        return ['\n'.join(sections)]

    def _clean_line(self, line: str) -> str:
        """
        Clean a log line by removing ANSI codes and non-ASCII characters.

        Args:
            line: Raw log line

        Returns:
            Cleaned line with only ASCII printable characters
        """
        if not line:
            return ""

        cleaned = line.strip()

        # Remove ANSI color codes
        cleaned = re.sub(r'\x1b\[[0-9;]*m', '', cleaned)

        # Remove common timestamp patterns (but keep the rest of the line)
        cleaned = re.sub(r'^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}[.,]\d+\s*', '', cleaned)
        cleaned = re.sub(r'^\[\d{2}:\d{2}:\d{2}\]', '', cleaned)

        # ASCII-only sanitization: Keep only printable ASCII (32-126) and tabs/newlines
        cleaned = ''.join(c if 32 <= ord(c) <= 126 or c in '\t\n' else ' ' for c in cleaned)

        # Collapse multiple spaces
        cleaned = re.sub(r' +', ' ', cleaned)
        cleaned = cleaned.strip()

        # Truncate if too long
        if len(cleaned) > self.max_line_length:
            cleaned = cleaned[:self.max_line_length] + "..."

        return cleaned

    def _find_error_lines(self, lines: List[str]) -> List[int]:
        """
        Find all line indices that contain error patterns.

        Args:
            lines: List of cleaned log lines

        Returns:
            List of line indices (0-based) that contain errors
        """
        error_indices = []

        for idx, line in enumerate(lines):
            if not line:
                continue

            line_lower = line.lower()
            if any(pattern in line_lower for pattern in self.ERROR_PATTERNS):
                error_indices.append(idx)

        return error_indices

    def _extract_sections_with_context(
        self,
        lines: List[str],
        error_indices: List[int]
    ) -> List[str]:
        """
        Extract sections with context around error lines and merge overlapping ranges.

        Args:
            lines: List of all cleaned log lines
            error_indices: List of error line indices

        Returns:
            List of formatted lines with line numbers
        """
        if not error_indices:
            return []

        total_lines = len(lines)

        # Calculate ranges for each error with context
        ranges = []
        for error_idx in error_indices:
            start = max(0, error_idx - self.lines_before)
            end = min(total_lines, error_idx + self.lines_after + 1)
            ranges.append((start, end))

        # Merge overlapping ranges
        merged_ranges = self._merge_ranges(ranges)

        # Extract lines from merged ranges with line numbers
        result_lines = []
        for start, end in merged_ranges:
            # Add separator between sections (except for first section)
            if result_lines:
                result_lines.append("")
                result_lines.append("--- Next Error Section ---")
                result_lines.append("")

            # Add lines with line numbers (1-indexed for readability)
            for idx in range(start, end):
                if lines[idx]:  # Skip empty lines
                    # Line numbers are 1-indexed for user readability
                    result_lines.append(f"Line {idx + 1}: {lines[idx]}")

        return result_lines

    def _merge_ranges(self, ranges: List[Tuple[int, int]]) -> List[Tuple[int, int]]:
        """
        Merge overlapping ranges.

        Args:
            ranges: List of (start, end) tuples

        Returns:
            List of merged (start, end) tuples
        """
        if not ranges:
            return []

        # Sort ranges by start position
        sorted_ranges = sorted(ranges)
        merged = [sorted_ranges[0]]

        for current_start, current_end in sorted_ranges[1:]:
            last_start, last_end = merged[-1]

            # If ranges overlap or are adjacent, merge them
            if current_start <= last_end:
                merged[-1] = (last_start, max(last_end, current_end))
            else:
                merged.append((current_start, current_end))

        return merged


def extract_error_sections(
    log_content: str,
    lines_before: int = 50,
    lines_after: int = 10
) -> List[str]:
    """
    Convenience function to extract error sections from log content.

    Args:
        log_content: Raw log content as string
        lines_before: Number of context lines before each error (default: 50)
        lines_after: Number of context lines after each error (default: 10)

    Returns:
        List with single string element containing all error lines with context, joined by newlines
    """
    extractor = LogErrorExtractor(
        lines_before=lines_before,
        lines_after=lines_after
    )
    return extractor.extract_error_sections(log_content)
