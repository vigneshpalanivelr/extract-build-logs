"""
Unit tests for log_error_extractor.py

Comprehensive test coverage for log error extraction including:
- Initialization with custom parameters
- Error pattern detection (all patterns)
- Empty log handling
- Line cleaning (ANSI codes, timestamps, non-ASCII characters)
- Maximum line length truncation
- Error line finding
- Context extraction (lines before/after)
- Range merging for overlapping contexts
- Formatted output with line numbers
- Multiple error sections
- Edge cases (errors at start/end of log)
- Convenience function
"""

import unittest
from pathlib import Path
import sys

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.log_error_extractor import LogErrorExtractor, extract_error_sections


class TestLogErrorExtractor(unittest.TestCase):
    """Test cases for LogErrorExtractor class."""

    def setUp(self):
        """Set up test fixtures."""
        self.extractor = LogErrorExtractor()

    def test_initialization_default_parameters(self):
        """Test LogErrorExtractor initialization with default parameters."""
        extractor = LogErrorExtractor()

        self.assertEqual(extractor.lines_before, 50)
        self.assertEqual(extractor.lines_after, 10)
        self.assertEqual(extractor.max_line_length, 1000)

    def test_initialization_custom_parameters(self):
        """Test LogErrorExtractor initialization with custom parameters."""
        extractor = LogErrorExtractor(lines_before=20, lines_after=5, max_line_length=500)

        self.assertEqual(extractor.lines_before, 20)
        self.assertEqual(extractor.lines_after, 5)
        self.assertEqual(extractor.max_line_length, 500)

    def test_extract_error_sections_empty_log(self):
        """Test extraction from empty log content."""
        result = self.extractor.extract_error_sections("")

        self.assertEqual(result, [])

    def test_extract_error_sections_none_log(self):
        """Test extraction from None log content."""
        result = self.extractor.extract_error_sections(None)

        self.assertEqual(result, [])

    def test_extract_error_sections_no_errors(self):
        """Test extraction when no errors are present."""
        log_content = """
        Build started successfully
        Running tests
        All tests passed
        Build completed
        """

        result = self.extractor.extract_error_sections(log_content)

        self.assertEqual(result, [])

    def test_extract_error_sections_single_error(self):
        """Test extraction of single error with context."""
        log_content = """Line 1
Line 2
Line 3 with exception message
Line 4
Line 5"""

        result = self.extractor.extract_error_sections(log_content)

        self.assertEqual(len(result), 1)
        self.assertIn('exception', result[0])
        # Check that all lines are included in output
        self.assertIn('Line 1', result[0])
        self.assertIn('Line 5', result[0])

    def test_extract_error_sections_multiple_errors(self):
        """Test extraction of multiple separate errors."""
        extractor = LogErrorExtractor(lines_before=1, lines_after=1)
        log_content = """
        Line 1
        Line 2 exception first
        Line 3
        Line 4
        Line 5
        Line 6
        Line 7 build failed second
        Line 8
        """

        result = extractor.extract_error_sections(log_content)

        self.assertEqual(len(result), 1)
        # Should contain both error sections with separator
        self.assertIn('exception first', result[0])
        self.assertIn('build failed second', result[0])
        self.assertIn('--- Next Error Section ---', result[0])

    def test_clean_line_removes_ansi_codes(self):
        """Test that ANSI color codes are removed."""
        line_with_ansi = "\x1b[31mException\x1b[0m: Something failed"

        cleaned = self.extractor._clean_line(line_with_ansi)

        self.assertNotIn('\x1b', cleaned)
        self.assertIn('Exception', cleaned)
        self.assertIn('Something failed', cleaned)

    def test_clean_line_removes_timestamps(self):
        """Test that timestamp patterns are removed."""
        # ISO timestamp
        line1 = "2025-01-01 12:34:56.789 exception: Test error"
        cleaned1 = self.extractor._clean_line(line1)
        self.assertNotIn('2025-01-01', cleaned1)
        self.assertIn('exception', cleaned1)

        # Bracket timestamp
        line2 = "[12:34:56] build failed"
        cleaned2 = self.extractor._clean_line(line2)
        self.assertNotIn('[12:34:56]', cleaned2)
        self.assertIn('build failed', cleaned2)

    def test_clean_line_removes_non_ascii(self):
        """Test that non-ASCII characters are removed."""
        line_with_unicode = "Exception: Test traceback ✗"

        cleaned = self.extractor._clean_line(line_with_unicode)

        # Unicode checkmark should be replaced with space
        self.assertNotIn('✗', cleaned)
        self.assertIn('Exception', cleaned)

    def test_clean_line_collapses_multiple_spaces(self):
        """Test that multiple spaces are collapsed."""
        line_with_spaces = "exception:     Multiple    spaces    here"

        cleaned = self.extractor._clean_line(line_with_spaces)

        # Should have single spaces only
        self.assertNotIn('  ', cleaned)
        self.assertEqual(cleaned, "exception: Multiple spaces here")

    def test_clean_line_truncates_long_lines(self):
        """Test that long lines are truncated."""
        extractor = LogErrorExtractor(max_line_length=50)
        long_line = "exception: " + "A" * 100

        cleaned = extractor._clean_line(long_line)

        self.assertLessEqual(len(cleaned), 53)  # 50 + "..."
        self.assertTrue(cleaned.endswith('...'))

    def test_clean_line_empty_input(self):
        """Test cleaning empty line."""
        cleaned = self.extractor._clean_line("")

        self.assertEqual(cleaned, "")

    def test_find_error_lines_all_patterns(self):
        """Test that all error patterns are detected."""
        patterns_to_test = [
            'make: ***', 'Sending interrupt signal to process', 'Killed by signal', 'Git clone failed',
            'subprocess.CalledProcessError: Command', 'unknown: Bad credentials', 'npm ERR! EBUSY: resource busy',
            'build-packetlogic2/packages/buildenv/11_llvm:', 'docker.errors', 'aseline.tar.lzma: Unexpected end of input',
            'err!', 'exception', 'traceback', 'could not resolve', 'compilation error', 'build failed'
        ]

        for pattern in patterns_to_test:
            lines = [f"Test {pattern} line"]
            error_indices = self.extractor._find_error_lines(lines)

            self.assertEqual(len(error_indices), 1, f"Pattern '{pattern}' not detected")
            self.assertEqual(error_indices[0], 0)

    def test_find_error_lines_case_insensitive(self):
        """Test that error detection is case-insensitive."""
        lines = [
            "Normal line",
            "EXCEPTION in uppercase",
            "exception in lowercase",
            "ExCePtIoN in mixed case"
        ]

        error_indices = self.extractor._find_error_lines(lines)

        self.assertEqual(len(error_indices), 3)
        self.assertEqual(error_indices, [1, 2, 3])

    def test_find_error_lines_skips_empty_lines(self):
        """Test that empty lines are skipped."""
        lines = ["", "exception line", "", ""]

        error_indices = self.extractor._find_error_lines(lines)

        self.assertEqual(len(error_indices), 1)
        self.assertEqual(error_indices[0], 1)

    def test_extract_sections_with_context_basic(self):
        """Test basic context extraction around error."""
        extractor = LogErrorExtractor(lines_before=2, lines_after=2)
        lines = ["line1", "line2", "line3 exception", "line4", "line5"]
        error_indices = [2]

        sections = extractor._extract_sections_with_context(lines, error_indices)

        # Should extract lines 1-5 (index 0-4)
        self.assertIn("Line 1: line1", sections)
        self.assertIn("Line 3: line3 exception", sections)
        self.assertIn("Line 5: line5", sections)

    def test_extract_sections_with_context_at_start(self):
        """Test context extraction when error is at start of log."""
        extractor = LogErrorExtractor(lines_before=5, lines_after=2)
        lines = ["exception at start", "line2", "line3"]
        error_indices = [0]

        sections = extractor._extract_sections_with_context(lines, error_indices)

        # Should extract from line 1 (can't go before start)
        self.assertIn("Line 1: exception at start", sections)
        self.assertIn("Line 3: line3", sections)

    def test_extract_sections_with_context_at_end(self):
        """Test context extraction when error is at end of log."""
        extractor = LogErrorExtractor(lines_before=2, lines_after=5)
        lines = ["line1", "line2", "exception at end"]
        error_indices = [2]

        sections = extractor._extract_sections_with_context(lines, error_indices)

        # Should extract to end (can't go past end)
        self.assertIn("Line 1: line1", sections)
        self.assertIn("Line 3: exception at end", sections)

    def test_extract_sections_with_context_empty_indices(self):
        """Test extraction with no error indices."""
        lines = ["line1", "line2", "line3"]
        error_indices = []

        sections = self.extractor._extract_sections_with_context(lines, error_indices)

        self.assertEqual(sections, [])

    def test_merge_ranges_non_overlapping(self):
        """Test merging of non-overlapping ranges."""
        ranges = [(0, 5), (10, 15), (20, 25)]

        merged = self.extractor._merge_ranges(ranges)

        self.assertEqual(merged, [(0, 5), (10, 15), (20, 25)])

    def test_merge_ranges_overlapping(self):
        """Test merging of overlapping ranges."""
        ranges = [(0, 5), (3, 8), (10, 15)]

        merged = self.extractor._merge_ranges(ranges)

        self.assertEqual(merged, [(0, 8), (10, 15)])

    def test_merge_ranges_adjacent(self):
        """Test merging of adjacent ranges."""
        ranges = [(0, 5), (5, 10)]

        merged = self.extractor._merge_ranges(ranges)

        self.assertEqual(merged, [(0, 10)])

    def test_merge_ranges_all_overlapping(self):
        """Test merging when all ranges overlap."""
        ranges = [(0, 5), (3, 8), (6, 10), (9, 15)]

        merged = self.extractor._merge_ranges(ranges)

        self.assertEqual(merged, [(0, 15)])

    def test_merge_ranges_empty_list(self):
        """Test merging empty list of ranges."""
        ranges = []

        merged = self.extractor._merge_ranges(ranges)

        self.assertEqual(merged, [])

    def test_merge_ranges_single_range(self):
        """Test merging single range."""
        ranges = [(5, 10)]

        merged = self.extractor._merge_ranges(ranges)

        self.assertEqual(merged, [(5, 10)])

    def test_merge_ranges_unsorted_input(self):
        """Test that unsorted ranges are handled correctly."""
        ranges = [(10, 15), (0, 5), (3, 8)]

        merged = self.extractor._merge_ranges(ranges)

        # Should be sorted and merged
        self.assertEqual(merged, [(0, 8), (10, 15)])

    def test_extract_error_sections_line_numbers_1_indexed(self):
        """Test that line numbers in output are 1-indexed."""
        extractor = LogErrorExtractor(lines_before=0, lines_after=0)
        log_content = "Line with exception"

        result = extractor.extract_error_sections(log_content)

        # Line numbers should start at 1, not 0
        self.assertIn("Line 1:", result[0])

    def test_extract_error_sections_skips_empty_lines_in_output(self):
        """Test that empty lines are skipped in formatted output."""
        extractor = LogErrorExtractor(lines_before=1, lines_after=1)
        log_content = "\nLine with exception\n"

        result = extractor.extract_error_sections(log_content)

        # Should only contain the non-empty line
        lines_in_output = [line for line in result[0].split('\n') if line.startswith('Line ')]
        self.assertEqual(len(lines_in_output), 1)
        self.assertIn('exception', lines_in_output[0])

    def test_convenience_function(self):
        """Test the convenience function extract_error_sections."""
        log_content = """
        Line 1
        Line 2 exception here
        Line 3
        """

        result = extract_error_sections(log_content, lines_before=1, lines_after=1)

        self.assertEqual(len(result), 1)
        self.assertIn('exception', result[0])

    def test_convenience_function_default_parameters(self):
        """Test convenience function with default parameters."""
        log_content = "exception line"

        result = extract_error_sections(log_content)

        self.assertEqual(len(result), 1)
        self.assertIn('exception', result[0])

    def test_extract_error_sections_returns_single_string(self):
        """Test that extract_error_sections returns list with single string."""
        log_content = "exception line"

        result = self.extractor.extract_error_sections(log_content)

        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], str)

    def test_error_pattern_in_middle_of_word(self):
        """Test that error patterns are detected even in middle of words."""
        log_content = "RuntimeException: Something went wrong"

        result = self.extractor.extract_error_sections(log_content)

        # Should detect 'exception' within 'RuntimeException'
        self.assertEqual(len(result), 1)
        self.assertIn('RuntimeException', result[0])

    def test_multiple_errors_close_together_merged(self):
        """Test that close errors are merged into single section."""
        extractor = LogErrorExtractor(lines_before=2, lines_after=2)
        log_content = """
        Line 1
        Line 2 exception first
        Line 3
        Line 4 build failed second
        Line 5
        """

        result = extractor.extract_error_sections(log_content)

        # Should be merged into single section (no separator)
        self.assertEqual(len(result), 1)
        self.assertNotIn('--- Next Error Section ---', result[0])

    def test_multiple_errors_far_apart_separate_sections(self):
        """Test that distant errors are in separate sections."""
        extractor = LogErrorExtractor(lines_before=1, lines_after=1)
        log_content = """
        Line 1
        Line 2 exception first
        Line 3
        Line 4
        Line 5
        Line 6
        Line 7 build failed second
        Line 8
        """

        result = extractor.extract_error_sections(log_content)

        # Should have separator between sections
        self.assertEqual(len(result), 1)
        self.assertIn('--- Next Error Section ---', result[0])

    def test_extract_with_all_error_patterns(self):
        """Integration test with all error patterns in single log."""
        log_content = '\n'.join([
            "make: *** Error",
            "err! Something went wrong",
            "Killed by signal 9",
            "Git clone failed",
            "exception occurred",
            "traceback found",
            "could not resolve dependency",
            "compilation error in code",
            "build failed completely",
            "docker.errors.APIError",
            "subprocess.CalledProcessError: Command failed"
        ])

        result = self.extractor.extract_error_sections(log_content)

        # Should detect all patterns
        self.assertEqual(len(result), 1)
        for pattern in ['err!', 'exception', 'traceback', 'build failed']:
            self.assertIn(pattern, result[0].lower())


class TestIgnorePatterns(unittest.TestCase):
    """Test cases for IGNORE_PATTERNS functionality."""

    def test_initialization_with_ignore_patterns(self):
        """Test LogErrorExtractor initialization with custom ignore_patterns."""
        ignore_patterns = ['error: tag', '0 errors']
        extractor = LogErrorExtractor(ignore_patterns=ignore_patterns)

        self.assertEqual(extractor.ignore_patterns, ignore_patterns)

    def test_initialization_default_ignore_patterns(self):
        """Test that default ignore_patterns is empty list."""
        extractor = LogErrorExtractor()

        self.assertEqual(extractor.ignore_patterns, [])

    def test_ignore_pattern_filters_false_positive(self):
        """Test that ignore pattern filters out false positive errors."""
        extractor = LogErrorExtractor(ignore_patterns=['docker.errors.tag'])
        lines = [
            "Building image with docker.errors.tag latest",
            "Real exception: something failed"
        ]

        error_indices = extractor._find_error_lines(lines)

        # Should only detect the real error, not the "docker.errors.tag" false positive
        self.assertEqual(len(error_indices), 1)
        self.assertEqual(error_indices[0], 1)

    def test_ignore_pattern_case_insensitive(self):
        """Test that ignore patterns are case-insensitive."""
        extractor = LogErrorExtractor(ignore_patterns=['docker.errors.tag'])
        lines = [
            "DOCKER.ERRORS.TAG latest",
            "docker.errors.tag latest",
            "Real exception message"
        ]

        error_indices = extractor._find_error_lines(lines)

        # Only the real error should be detected
        self.assertEqual(len(error_indices), 1)
        self.assertEqual(error_indices[0], 2)

    def test_ignore_pattern_uppercase_pattern(self):
        """Test that ignore patterns work when provided in uppercase."""
        extractor = LogErrorExtractor(ignore_patterns=['DOCKER.ERRORS.TAG'])
        lines = [
            "docker.errors.tag latest",
            "DOCKER.ERRORS.TAG latest",
            "Real exception message"
        ]

        error_indices = extractor._find_error_lines(lines)

        # Only the real error should be detected
        self.assertEqual(len(error_indices), 1)
        self.assertEqual(error_indices[0], 2)

    def test_ignore_pattern_0_errors_success_message(self):
        """Test filtering success message containing 'error' word."""
        extractor = LogErrorExtractor(ignore_patterns=['0 errors'])
        lines = [
            "Build completed: 0 errors, 5 warnings",
            "Compilation error: missing semicolon"
        ]

        error_indices = extractor._find_error_lines(lines)

        # Should only detect the real error
        self.assertEqual(len(error_indices), 1)
        self.assertEqual(error_indices[0], 1)

    def test_multiple_ignore_patterns(self):
        """Test with multiple ignore patterns."""
        extractor = LogErrorExtractor(ignore_patterns=['docker.errors.tag', 'err! skipped', 'traceback ignored'])
        lines = [
            "Docker docker.errors.tag myimage",
            "Build: err! skipped",
            "Test traceback ignored",
            "Real exception occurred"
        ]

        error_indices = extractor._find_error_lines(lines)

        # Only the real error should be detected
        self.assertEqual(len(error_indices), 1)
        self.assertEqual(error_indices[0], 3)

    def test_empty_ignore_patterns_no_filtering(self):
        """Test that empty ignore_patterns list doesn't filter anything."""
        extractor = LogErrorExtractor(ignore_patterns=[])
        lines = [
            "docker.errors.tag latest",
            "Real exception message"
        ]

        error_indices = extractor._find_error_lines(lines)

        # Both lines should be detected as errors
        self.assertEqual(len(error_indices), 2)

    def test_ignore_patterns_none_uses_class_default(self):
        """Test that None ignore_patterns uses class default (empty list)."""
        extractor = LogErrorExtractor(ignore_patterns=None)
        lines = [
            "docker.errors.tag latest",
            "Real exception message"
        ]

        error_indices = extractor._find_error_lines(lines)

        # Both lines should be detected as errors (no filtering)
        self.assertEqual(len(error_indices), 2)

    def test_extract_error_sections_with_ignore_patterns(self):
        """Test full extraction with ignore patterns."""
        extractor = LogErrorExtractor(lines_before=1, lines_after=1, ignore_patterns=['docker.errors.tag'])
        log_content = """
Line 1
Docker docker.errors.tag myimage
Line 3
Real exception: build failed
Line 5
"""

        result = extractor.extract_error_sections(log_content)

        # Should only contain the real error section
        self.assertEqual(len(result), 1)
        self.assertIn('Real exception: build failed', result[0])
        self.assertNotIn('docker.errors.tag', result[0])

    def test_convenience_function_with_ignore_patterns(self):
        """Test convenience function accepts ignore_patterns."""
        # Create log where only "docker.errors.tag" line has error pattern (no other errors)
        log_content = """
Line 1
docker.errors.tag latest
Line 3
"""
        # With ignore_patterns=['docker.errors.tag'], no errors should be detected
        result = extract_error_sections(log_content, ignore_patterns=['docker.errors.tag'])
        self.assertEqual(result, [])  # No errors detected

        # Test with a real error and ignore pattern
        log_content2 = """
docker.errors.tag latest
Real exception: something failed
"""
        result2 = extract_error_sections(log_content2, lines_before=0, lines_after=0,
                                         ignore_patterns=['docker.errors.tag'])
        self.assertEqual(len(result2), 1)
        self.assertIn('Real exception', result2[0])
        # With lines_before=0, the "docker.errors.tag" line won't be included as context
        self.assertNotIn('docker.errors.tag', result2[0])

    def test_ignore_pattern_partial_match(self):
        """Test that ignore pattern works with partial match."""
        extractor = LogErrorExtractor(ignore_patterns=['failed to create optional'])
        lines = [
            "Operation failed to create optional cache - continuing",
            "Build FAILED: missing dependencies"
        ]

        error_indices = extractor._find_error_lines(lines)

        # Should only detect the real failure
        self.assertEqual(len(error_indices), 1)
        self.assertEqual(error_indices[0], 1)

    def test_line_matching_error_but_also_ignore(self):
        """Test that line matching both error and ignore is filtered out."""
        extractor = LogErrorExtractor(ignore_patterns=['build failed successfully'])
        lines = [
            "Previous build failed successfully recovered",
            "Current build FAILED"
        ]

        error_indices = extractor._find_error_lines(lines)

        # Only the current failure should be detected
        self.assertEqual(len(error_indices), 1)
        self.assertEqual(error_indices[0], 1)


if __name__ == '__main__':
    unittest.main()
