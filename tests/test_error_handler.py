"""
Tests for Error Handler Module
"""

import unittest
import time
from src.error_handler import ErrorHandler, RetryExhaustedError, retry_on_failure, CircuitBreaker


class TestErrorHandler(unittest.TestCase):
    """Test cases for ErrorHandler class."""

    def test_successful_call(self):
        """Test that successful calls work without retry."""
        handler = ErrorHandler(max_retries=3, base_delay=0.1)

        def success_func():
            return "success"

        result = handler.retry_with_backoff(success_func)
        self.assertEqual(result, "success")

    def test_retry_eventually_succeeds(self):
        """Test that function succeeds after retries."""
        handler = ErrorHandler(max_retries=3, base_delay=0.1)
        attempts = {'count': 0}

        def eventually_succeeds():
            attempts['count'] += 1
            if attempts['count'] < 3:
                raise ValueError("Not yet")
            return "success"

        result = handler.retry_with_backoff(eventually_succeeds, exceptions=(ValueError,))
        self.assertEqual(result, "success")
        self.assertEqual(attempts['count'], 3)

    def test_retry_exhausted(self):
        """Test that RetryExhaustedError is raised after all retries."""
        handler = ErrorHandler(max_retries=2, base_delay=0.1)

        def always_fails():
            raise ValueError("Always fails")

        with self.assertRaises(RetryExhaustedError) as context:
            handler.retry_with_backoff(always_fails, exceptions=(ValueError,))

        self.assertEqual(context.exception.attempts, 3)  # max_retries + 1

    def test_exponential_backoff(self):
        """Test that exponential backoff increases delay correctly."""
        handler = ErrorHandler(max_retries=3, base_delay=1.0, exponential=True)

        delays = [
            handler._calculate_delay(0),  # 1.0
            handler._calculate_delay(1),  # 2.0
            handler._calculate_delay(2),  # 4.0
        ]

        self.assertEqual(delays, [1.0, 2.0, 4.0])

    def test_constant_delay(self):
        """Test that constant delay remains the same."""
        handler = ErrorHandler(max_retries=3, base_delay=2.0, exponential=False)

        delays = [
            handler._calculate_delay(0),
            handler._calculate_delay(1),
            handler._calculate_delay(2),
        ]

        self.assertEqual(delays, [2.0, 2.0, 2.0])

    def test_specific_exception_only(self):
        """Test that only specified exceptions are retried."""
        handler = ErrorHandler(max_retries=3, base_delay=0.1)

        def raises_type_error():
            raise TypeError("Type error")

        # Should not retry TypeError when only catching ValueError
        with self.assertRaises(TypeError):
            handler.retry_with_backoff(raises_type_error, exceptions=(ValueError,))


class TestRetryDecorator(unittest.TestCase):
    """Test cases for retry_on_failure decorator."""

    def test_decorator_success(self):
        """Test decorator on successful function."""
        @retry_on_failure(max_retries=3, base_delay=0.1)
        def success_func():
            return "decorated success"

        result = success_func()
        self.assertEqual(result, "decorated success")

    def test_decorator_retry(self):
        """Test decorator retries failed calls."""
        attempts = {'count': 0}

        @retry_on_failure(max_retries=3, base_delay=0.1, exceptions=(ValueError,))
        def eventually_succeeds():
            attempts['count'] += 1
            if attempts['count'] < 2:
                raise ValueError("Not yet")
            return "success"

        result = eventually_succeeds()
        self.assertEqual(result, "success")
        self.assertGreaterEqual(attempts['count'], 2)


class TestCircuitBreaker(unittest.TestCase):
    """Test cases for CircuitBreaker class."""

    def test_circuit_closed_initially(self):
        """Test that circuit starts in CLOSED state."""
        breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=1.0)
        self.assertEqual(breaker.state, "CLOSED")

    def test_circuit_opens_after_threshold(self):
        """Test that circuit opens after failure threshold."""
        breaker = CircuitBreaker(failure_threshold=2, recovery_timeout=1.0)

        def always_fails():
            raise ValueError("Failed")

        # Fail twice to reach threshold
        for _ in range(2):
            try:
                breaker.call(always_fails)
            except ValueError:
                pass

        self.assertEqual(breaker.state, "OPEN")

    def test_circuit_recovers(self):
        """Test that circuit moves to HALF_OPEN and recovers."""
        breaker = CircuitBreaker(failure_threshold=2, recovery_timeout=0.2)

        def always_fails():
            raise ValueError("Failed")

        def always_succeeds():
            return "success"

        # Open the circuit
        for _ in range(2):
            try:
                breaker.call(always_fails)
            except ValueError:
                pass

        self.assertEqual(breaker.state, "OPEN")

        # Wait for recovery timeout
        time.sleep(0.3)

        # Next call should move to HALF_OPEN
        result = breaker.call(always_succeeds)
        self.assertEqual(result, "success")
        self.assertEqual(breaker.state, "CLOSED")

    def test_circuit_blocks_when_open(self):
        """Test that circuit blocks calls when OPEN."""
        breaker = CircuitBreaker(failure_threshold=1, recovery_timeout=10.0)

        def always_fails():
            raise ValueError("Failed")

        # Open the circuit
        try:
            breaker.call(always_fails)
        except ValueError:
            pass

        self.assertEqual(breaker.state, "OPEN")

        # Should block subsequent calls
        with self.assertRaises(Exception) as context:
            breaker.call(lambda: "should not run")

        self.assertIn("Circuit breaker is OPEN", str(context.exception))


if __name__ == '__main__':
    unittest.main()
