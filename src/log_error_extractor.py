"""
Log Error Extractor

Extracts error sections from build logs with configurable context.
Provides surrounding lines before and after errors for better LLM analysis.

Invoked by: api_poster
Invokes: None
"""

import json
import re
from collections import defaultdict
from typing import List, Tuple, Dict, Any
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
        'make: ***',                                      # Make errors
        'Sending interrupt signal to process',            # Process interruption
        'killed by signal',                               # Signal termination
        'git clone failed',                               # Git failures
        'err!',                                           # npm errors (uppercase)
        'subprocess.calledprocesserror: command',         # Python subprocess errors
        'unknown: bad credentials',                       # Git auth errors
        'npm err! ebusy: resource busy',                  # npm resource errors
        'build-packetlogic2/packages/buildenv/11_llvm:',  # Specific build path errors
        'docker.errors',                                  # Docker errors
        'exception:',                                     # Python/Java exceptions (with colon)
        'traceback',                                      # Python tracebacks
        'could not resolve',                              # Dependency resolution
        'compilation error',                              # Compilation failures
        'build failed',                                   # Build failures (uppercase)
        'baseline.tar.lzma: unexpected end of input',     # Archive errors
        'error: ',                                        # Generic errors (capital E with colon-space)
    ]

    # Ignore patterns - lines matching these are NOT considered errors even if they match ERROR_PATTERNS
    # This filters out false positives (case-insensitive)
    IGNORE_PATTERNS: List[str] = [
        'error: tag ',                                    # Git tag operations (capital E)
        '[ FAIL ]',                                       # Test framework markers
        '[new branch]',                                   # Git branch operations
        'INFO: I/O exception',                            # Info-level exceptions
        '-exception-',                                    # Exception in variable names
    ]

    def __init__(self, lines_before: int = 50, lines_after: int = 10, max_line_length: int = 1000,
                 ignore_patterns: List[str] = None, use_adaptive_context: bool = True,
                 adaptive_thresholds: List[Tuple[int, int, int]] = None):
        """
        Initialize the error extractor.

        Args:
            lines_before: Number of context lines to include before each error (default: 50)
            lines_after: Number of context lines to include after each error (default: 10)
            max_line_length: Maximum length of individual lines before truncation (default: 1000)
            ignore_patterns: List of patterns to ignore - lines matching these won't be considered
                           errors even if they match ERROR_PATTERNS (default: None)
            use_adaptive_context: Enable INCREMENTAL BUCKET extraction (default: True)
            adaptive_thresholds: List of (count, before, after) tuples defining incremental buckets
                               (default: [(50, 50, 10), (100, 10, 5), (150, 5, 2)])
                               Each tuple: (error_count, lines_before, lines_after)
                               Example: [(5, 50, 10), (10, 10, 5), (20, 5, 2)]
                                 → First 5 errors: 50b/10a, Next 10: 10b/5a, Next 20: 5b/2a
                                 → Total: 35 errors extracted, rest ignored
        """
        self.lines_before = lines_before
        self.lines_after = lines_after
        self.max_line_length = max_line_length
        self.ignore_patterns = ignore_patterns if ignore_patterns is not None else self.IGNORE_PATTERNS
        self.use_adaptive_context = use_adaptive_context
        self.adaptive_thresholds = adaptive_thresholds if adaptive_thresholds is not None else [
            (50, 50, 10), (100, 10, 5), (150, 5, 2)
        ]
        self.last_error_summary = None  # Store last extraction summary for later access
        self.last_extraction_status = None  # Track extraction status: "success", "no_errors", "too_many_errors"

    def extract_error_sections(self, log_content: str, log_file_path: str = None) -> List[str]:
        """
        Extract error sections with surrounding context from log content.
        Uses bottom-to-top extraction with INCREMENTAL BUCKET approach.

        Adaptive thresholds define incremental buckets (when use_adaptive_context=True):
        Config "5:50:10,10:10:5,20:5:2" means:
        - First 5 errors (from bottom): 50 lines before, 10 lines after each
        - Next 10 errors: 10 lines before, 5 lines after each
        - Next 20 errors: 5 lines before, 2 lines after each
        - Remaining errors (36+): IGNORED (not extracted)

        Total extracted: 5 + 10 + 20 = 35 errors maximum

        Default thresholds: "50:50:10,100:10:5,150:5:2"
        - First 50 errors: 50 before, 10 after
        - Next 100 errors: 10 before, 5 after
        - Next 150 errors: 5 before, 2 after
        - Remaining errors: IGNORED
        Total: 300 errors maximum

        Args:
            log_content: Raw log content as string
            log_file_path: Optional path where log is saved (for logging purposes)

        Returns:
            List with a single string element containing all error lines with context,
            joined by newlines. Each line includes line numbers for reference.

        Example output:
            ["Line 100: npm install started\\nLine 101: Resolving dependencies...\\n...\\n
            Line 150: npm ERR! code ERESOLVE"]
        """
        if not log_content:
            return []

        # Split log into lines and clean them
        all_lines = log_content.split('\n')
        cleaned_lines = [self._clean_line(line) for line in all_lines]

        # Extract using bottom-to-top algorithm with adaptive context
        sections = self._extract_bottom_to_top(cleaned_lines, log_file_path)

        if not sections:
            logger.debug("No error patterns found in log content")
            return []

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
        Find all line indices that contain error patterns but not ignore patterns.

        A line is considered an error if:
        - It matches at least one ERROR_PATTERN, AND
        - It does NOT match any IGNORE_PATTERN

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

            # Check if line matches any error pattern
            if any(pattern in line_lower for pattern in self.ERROR_PATTERNS):
                # Check if line should be ignored (matches any ignore pattern)
                if self.ignore_patterns and any(ignore.lower() in line_lower for ignore in self.ignore_patterns):
                    continue  # Skip this line - it matches an ignore pattern
                error_indices.append(idx)

        return error_indices

    def _extract_sections_with_context(self, lines: List[str], error_indices: List[int]) -> List[str]:
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

    def _is_error_line(self, line: str) -> bool:
        """
        Check if a single line matches error patterns but not ignore patterns.

        Args:
            line: A single cleaned log line

        Returns:
            True if line is an error, False otherwise
        """
        if not line:
            return False

        line_lower = line.lower()

        # Check if line matches any error pattern
        if any(pattern in line_lower for pattern in self.ERROR_PATTERNS):
            # Check if line should be ignored (matches any ignore pattern)
            if self.ignore_patterns and any(ignore.lower() in line_lower for ignore in self.ignore_patterns):
                return False  # Not an error - matches ignore pattern
            return True  # It's an error

        return False  # Doesn't match any error pattern

    def _count_errors(self, lines: List[str]) -> int:
        """
        Count total number of error lines in the log.

        Args:
            lines: List of cleaned log lines

        Returns:
            Total count of error lines
        """
        error_count = 0
        for line in lines:
            if self._is_error_line(line):
                error_count += 1

        return error_count

    def _get_adaptive_context(self, error_count: int) -> Tuple[int, int]:
        """
        Determine context size based on error count using adaptive thresholds.

        Args:
            error_count: Total number of errors found

        Returns:
            Tuple of (lines_before, lines_after)
        """
        # Iterate through thresholds and return context for first match
        for threshold, lines_before, lines_after in self.adaptive_thresholds:
            if error_count <= threshold:
                return (lines_before, lines_after)

        # If exceeded all thresholds, use the last threshold's context (minimal)
        _, lines_before, lines_after = self.adaptive_thresholds[-1]
        return (lines_before, lines_after)

    def _get_bucket_context(self, errors_extracted: int) -> Tuple[int, int]:
        """
        Determine context size based on which incremental bucket this error belongs to.

        Thresholds are treated as incremental buckets:
        "5:50:10,10:10:5,20:5:2" means:
          - Errors 0-4 (first 5): 50 before, 10 after
          - Errors 5-14 (next 10): 10 before, 5 after
          - Errors 15-34 (next 20): 5 before, 2 after

        Args:
            errors_extracted: Number of errors extracted so far (0-indexed)

        Returns:
            Tuple of (lines_before, lines_after) for this error's bucket
        """
        cumulative = 0
        for bucket_count, lines_before, lines_after in self.adaptive_thresholds:
            if errors_extracted < cumulative + bucket_count:
                # This error belongs to this bucket
                return (lines_before, lines_after)
            cumulative += bucket_count

        # Should never reach here if max_errors_to_extract is set correctly
        # But if we do, use the last bucket's context
        _, lines_before, lines_after = self.adaptive_thresholds[-1]
        return (lines_before, lines_after)

    def _analyze_errors(self, lines: List[str]) -> Dict[str, Any]:
        """
        Analyze error patterns in log lines and return detailed breakdown.

        Args:
            lines: List of cleaned log lines

        Returns:
            Dictionary with error analysis including counts and line numbers by pattern
        """
        error_types = defaultdict(int)
        error_lines = defaultdict(list)
        ignored_patterns = defaultdict(int)

        for idx, line in enumerate(lines):
            if not line:
                continue

            line_lower = line.lower()
            line_num = idx + 1  # 1-indexed for user readability

            # Check for error patterns
            matched_pattern = None
            for pattern in self.ERROR_PATTERNS:
                if pattern in line_lower:
                    matched_pattern = pattern
                    break

            if matched_pattern:
                # Check if this should be ignored
                ignored = False
                if self.ignore_patterns:
                    for ignore_pattern in self.ignore_patterns:
                        if ignore_pattern.lower() in line_lower:
                            ignored_patterns[ignore_pattern] += 1
                            ignored = True
                            break

                # If not ignored, count it as an error
                if not ignored:
                    error_types[matched_pattern] += 1
                    error_lines[matched_pattern].append(line_num)

        return {
            'error_types': dict(error_types),
            'error_lines': dict(error_lines),
            'ignored_patterns': dict(ignored_patterns)
        }

    @staticmethod
    def _format_line_sample(line_numbers: List[int]) -> str:
        """
        Format line numbers as sample range (first 5 ... last (total)).

        Args:
            line_numbers: List of line numbers

        Returns:
            Formatted string like "45,67,89,112,134 ... 8945 (180 total)"
        """
        if not line_numbers:
            return ""

        total = len(line_numbers)

        if total <= 5:
            # Show all line numbers if 5 or fewer
            return f"{','.join(map(str, line_numbers))} ({total} total)"

        # Show first 5 and last
        first_five = ','.join(map(str, line_numbers[:5]))
        last = line_numbers[-1]
        return f"{first_five} ... {last} ({total} total)"

    def _extract_single_section_with_context(self, lines: List[str], error_idx: int,
                                             lines_before: int, lines_after: int) -> List[str]:
        """
        Extract a single error section with context.

        Args:
            lines: List of all cleaned log lines
            error_idx: Index of the error line
            lines_before: Number of lines to include before error
            lines_after: Number of lines to include after error

        Returns:
            List of formatted lines with line numbers for this section
        """
        total_lines = len(lines)
        start = max(0, error_idx - lines_before)
        end = min(total_lines, error_idx + lines_after + 1)

        section_lines = []
        for idx in range(start, end):
            if lines[idx]:  # Skip empty lines
                # Line numbers are 1-indexed for user readability
                section_lines.append(f"Line {idx + 1}: {lines[idx]}")

        return section_lines

    def _format_sections(self, sections: List[List[str]]) -> List[str]:
        """
        Format multiple sections with separators between them.

        Args:
            sections: List of sections, where each section is a list of formatted lines

        Returns:
            Flattened list with separators between sections
        """
        if not sections:
            return []

        result = []
        for i, section in enumerate(sections):
            # Add separator before each section except the first
            if i > 0:
                result.append("")
                result.append("--- Next Error Section ---")
                result.append("")

            # Add the section lines
            result.extend(section)

        return result

    def _extract_bottom_to_top(self, lines: List[str], log_file_path: str = None) -> List[str]:
        """
        Extract errors from bottom to top with adaptive context.

        Algorithm:
        1. Count total errors to determine adaptive context size
        2. If >150 errors, skip extraction entirely
        3. Scan from bottom (last line) to top
        4. When error found, extract with context and skip that context range
        5. Reverse output to show chronologically (oldest first)

        Args:
            lines: List of cleaned log lines
            log_file_path: Optional path where log is saved (for logging purposes)

        Returns:
            List of formatted lines with line numbers
        """
        # Step 1: Analyze errors in detail
        error_analysis = self._analyze_errors(lines)
        error_count = sum(error_analysis['error_types'].values())

        if error_count == 0:
            self.last_extraction_status = "no_errors"
            return []

        # Step 2: Calculate incremental buckets and max errors to extract
        # NOTE: Incremental buckets only apply when using default values (50, 10)
        use_incremental_buckets = (
            self.use_adaptive_context
            and self.adaptive_thresholds
            and self.lines_before == 50
            and self.lines_after == 10
        )

        if use_incremental_buckets:
            max_errors_to_extract = sum(bucket[0] for bucket in self.adaptive_thresholds)

            if error_count > max_errors_to_extract:
                logger.warning(
                    "Too many errors (%d > %d), extracting first %d errors using incremental buckets (%s)",
                    error_count, max_errors_to_extract, max_errors_to_extract,
                    ' + '.join([str(b[0]) for b in self.adaptive_thresholds])
                )

            # Build context description showing bucket structure
            cumulative = 0
            bucket_descs = []
            for count, before, after in self.adaptive_thresholds:
                bucket_descs.append(f"errors {cumulative + 1}-{cumulative + count}: {before}b/{after}a")
                cumulative += count
            context_description = f"incremental buckets ({', '.join(bucket_descs)})"
        else:
            max_errors_to_extract = None
            context_description = f"{self.lines_before} before, {self.lines_after} after (fixed)"

        # Step 3: Build error summary
        error_summary = {
            "total_errors_found": error_count,
            "error_settings": ','.join([f"{t}:{b}:{a}" for t, b, a in self.adaptive_thresholds]),
            "search_technique": "bottom-up",
            "context_used": context_description,
            "error_types": error_analysis['error_types'],
            "line_samples": {
                p: self._format_line_sample(nums)
                for p, nums in error_analysis['error_lines'].items()
            },
            "ignored_patterns": error_analysis['ignored_patterns'],
            "extracted_content": log_file_path if log_file_path else "N/A",
            "extraction_capped": max_errors_to_extract is not None,
            "max_errors_extracted": max_errors_to_extract if max_errors_to_extract is not None else error_count
        }

        # Store summary for later access
        self.last_error_summary = error_summary

        # Log the error summary at INFO level
        logger.info("Error Extraction Summary:\n%s", json.dumps(error_summary, indent=2))

        # Step 4: Extract bottom-to-top with incremental buckets
        result_sections = []
        current_idx = len(lines) - 1
        errors_extracted = 0

        while current_idx >= 0:
            if self._is_error_line(lines[current_idx]):
                # Check if we've hit the extraction cap
                if max_errors_to_extract is not None and errors_extracted >= max_errors_to_extract:
                    logger.info(
                        "Reached error extraction cap (%d/%d total errors), extracted %d errors",
                        max_errors_to_extract, error_count, errors_extracted
                    )
                    break

                # Determine context for this error based on which bucket it belongs to
                # Only use bucket context if we're using incremental buckets (max_errors_to_extract is set)
                if max_errors_to_extract is not None:
                    lines_before, lines_after = self._get_bucket_context(errors_extracted)
                else:
                    lines_before = self.lines_before
                    lines_after = self.lines_after

                # Extract section with context
                section = self._extract_single_section_with_context(
                    lines, current_idx, lines_before, lines_after
                )
                result_sections.append(section)
                errors_extracted += 1

                # Skip context range - move to line before context starts
                start_idx = max(0, current_idx - lines_before)
                current_idx = start_idx - 1
            else:
                current_idx -= 1

        # Step 6: Reverse for chronological order (oldest first)
        result_sections.reverse()

        # Step 7: Format sections with separators
        self.last_extraction_status = "success"
        return self._format_sections(result_sections)


def extract_error_sections(log_content: str, lines_before: int = 50, lines_after: int = 10,
                           ignore_patterns: List[str] = None, use_adaptive_context: bool = True,
                           adaptive_thresholds: List[Tuple[int, int, int]] = None,
                           log_file_path: str = None) -> List[str]:
    """
    Convenience function to extract error sections from log content using INCREMENTAL BUCKETS.

    Args:
        log_content: Raw log content as string
        lines_before: Number of context lines before each error (default: 50)
        lines_after: Number of context lines after each error (default: 10)
        ignore_patterns: List of patterns to ignore - lines matching these won't be considered
                       errors even if they match ERROR_PATTERNS (default: None)
        use_adaptive_context: Enable INCREMENTAL BUCKET extraction (default: True)
        adaptive_thresholds: List of (count, before, after) tuples defining incremental buckets
                           (default: [(50, 50, 10), (100, 10, 5), (150, 5, 2)])
                           Example: [(5, 50, 10), (10, 10, 5), (20, 5, 2)]
                             → First 5: 50b/10a, Next 10: 10b/5a, Next 20: 5b/2a, Rest: ignored
        log_file_path: Optional path where log is saved (for logging purposes)

    Returns:
        List with single string element containing all error lines with context, joined by newlines
    """
    extractor = LogErrorExtractor(
        lines_before=lines_before,
        lines_after=lines_after,
        ignore_patterns=ignore_patterns,
        use_adaptive_context=use_adaptive_context,
        adaptive_thresholds=adaptive_thresholds
    )
    return extractor.extract_error_sections(log_content, log_file_path)
