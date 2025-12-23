"""
Error Handler Module

This module provides error handling and retry logic for API calls and network operations.
It implements exponential backoff and configurable retry strategies to handle transient failures.

Data Flow:
    Function Call → retry_with_backoff() → [Attempt → Error → Wait → Retry] → Success/Failure

Module Dependencies:
    - time: For sleep between retries
    - logging: For error logging
    - typing: For type hints
    - functools: For decorator functionality
"""

import time
import logging
from typing import Callable, Any, Optional, Type, Tuple
from functools import wraps

# Configure module logger
logger = logging.getLogger(__name__)


class RetryExhaustedError(Exception):
    """
    Raised when all retry attempts have been exhausted.

    Attributes:
        attempts (int): Number of attempts made
        last_exception (Exception): The last exception that was raised
    """

    def __init__(self, attempts: int, last_exception: Exception):
        self.attempts = attempts
        self.last_exception = last_exception
        super().__init__(
            f"All {attempts} retry attempts exhausted. Last error: {str(last_exception)}"
        )


class CircuitBreakerError(Exception):
    """
    Raised when circuit breaker is open and blocking requests.

    This exception indicates that the circuit breaker has detected too many
    failures and is temporarily blocking requests to prevent cascading failures.
    """

    def __init__(self, message: str = "Circuit breaker is OPEN, request blocked"):
        super().__init__(message)


class ErrorHandler:
    """
    Error handler with retry logic and exponential backoff.

    This class provides methods to handle errors gracefully and retry failed operations
    with configurable backoff strategies.

    Attributes:
        max_retries (int): Maximum number of retry attempts
        base_delay (float): Base delay in seconds between retries
        exponential (bool): Whether to use exponential backoff
    """

    def __init__(self, max_retries: int = 3, base_delay: float = 2.0, exponential: bool = True):
        """
        Initialize the error handler.

        Args:
            max_retries (int): Maximum number of retry attempts (default: 3)
            base_delay (float): Base delay in seconds between retries (default: 2.0)
            exponential (bool): Use exponential backoff if True, constant delay if False (default: True)
        """
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.exponential = exponential

    def retry_with_backoff(
        self,
        func: Callable,
        *args,
        exceptions: Tuple[Type[Exception], ...] = (Exception,),
        **kwargs
    ) -> Any:
        """
        Execute a function with retry logic and exponential backoff.

        This method will retry the function call if it raises one of the specified exceptions.
        The delay between retries increases exponentially if exponential=True.

        Args:
            func (Callable): The function to execute
            *args: Positional arguments to pass to the function
            exceptions (Tuple[Type[Exception], ...]): Tuple of exception types to catch and retry
            **kwargs: Keyword arguments to pass to the function

        Returns:
            Any: The return value of the successful function call

        Raises:
            RetryExhaustedError: If all retry attempts are exhausted

        Example:
            handler = ErrorHandler(max_retries=3)
            result = handler.retry_with_backoff(api_call, project_id, job_id)
        """
        last_exception = None

        for attempt in range(self.max_retries + 1):
            try:
                logger.debug("Attempt %s/%s for %s", attempt + 1, self.max_retries + 1, func.__name__)
                result = func(*args, **kwargs)  # pylint: disable=redefined-outer-name
                if attempt > 0:
                    logger.info("Success on attempt %s for %s", attempt + 1, func.__name__)
                return result

            except exceptions as e:  # pylint: disable=redefined-outer-name
                last_exception = e
                if attempt < self.max_retries:
                    delay = self._calculate_delay(attempt)
                    logger.warning(
                        "Attempt %d failed for %s: %s. Retrying in %.2f seconds...",
                        attempt + 1, func.__name__, str(e), delay
                    )
                    time.sleep(delay)
                else:
                    logger.error(
                        "All %d attempts failed for %s. Last error: %s",
                        self.max_retries + 1, func.__name__, str(e)
                    )

        raise RetryExhaustedError(self.max_retries + 1, last_exception)

    def _calculate_delay(self, attempt: int) -> float:
        """
        Calculate delay before next retry attempt.

        Args:
            attempt (int): Current attempt number (0-indexed)

        Returns:
            float: Delay in seconds

        Implementation:
            - Exponential: delay = base_delay * (2 ^ attempt)
            - Constant: delay = base_delay
        """
        if self.exponential:
            return self.base_delay * (2 ** attempt)
        return self.base_delay


def retry_on_failure(
    max_retries: int = 3,
    base_delay: float = 2.0,
    exponential: bool = True,
    exceptions: Tuple[Type[Exception], ...] = (Exception,)
):
    """
    Decorator for automatic retry with exponential backoff.

    This decorator can be applied to any function to automatically retry it
    on failure with configurable retry parameters.

    Args:
        max_retries (int): Maximum number of retry attempts (default: 3)
        base_delay (float): Base delay in seconds between retries (default: 2.0)
        exponential (bool): Use exponential backoff if True (default: True)
        exceptions (Tuple[Type[Exception], ...]): Exception types to catch (default: (Exception,))

    Returns:
        Callable: Decorated function with retry logic

    Example:
        @retry_on_failure(max_retries=3, base_delay=1.0)
        def fetch_data(url):
            response = requests.get(url)
            response.raise_for_status()
            return response.json()

    Data Flow:
        Decorated Function Call → retry_wrapper() → ErrorHandler.retry_with_backoff() → Original Function
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            handler = ErrorHandler(max_retries, base_delay, exponential)
            return handler.retry_with_backoff(func, *args, exceptions=exceptions, **kwargs)
        return wrapper
    return decorator


class CircuitBreaker:
    """
    Circuit breaker pattern implementation for preventing cascade failures.

    The circuit breaker monitors failures and can stop making requests to a failing
    service, giving it time to recover.

    States:
        - CLOSED: Normal operation, requests pass through
        - OPEN: Too many failures, requests are blocked
        - HALF_OPEN: Testing if service has recovered

    Attributes:
        failure_threshold (int): Number of failures before opening circuit
        recovery_timeout (float): Time to wait before attempting recovery
        failure_count (int): Current number of consecutive failures
        last_failure_time (Optional[float]): Timestamp of last failure
        state (str): Current circuit state (CLOSED, OPEN, HALF_OPEN)
    """

    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 60.0):
        """
        Initialize circuit breaker.

        Args:
            failure_threshold (int): Number of failures before opening circuit (default: 5)
            recovery_timeout (float): Seconds to wait before testing recovery (default: 60.0)
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.last_failure_time: Optional[float] = None
        self.state = "CLOSED"

    def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        Execute function through circuit breaker.

        Args:
            func (Callable): Function to execute
            *args: Positional arguments for function
            **kwargs: Keyword arguments for function

        Returns:
            Any: Function return value

        Raises:
            Exception: If circuit is OPEN or function fails
        """
        if self.state == "OPEN":
            if self._should_attempt_reset():
                self.state = "HALF_OPEN"
                logger.info("Circuit breaker entering HALF_OPEN state")
            else:
                raise CircuitBreakerError()

        try:
            result = func(*args, **kwargs)  # pylint: disable=redefined-outer-name
            self._on_success()
            return result
        except Exception as e:  # pylint: disable=redefined-outer-name,broad-exception-caught
            self._on_failure()
            raise e

    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to attempt recovery."""
        if self.last_failure_time is None:
            return False
        return time.time() - self.last_failure_time >= self.recovery_timeout

    def _on_success(self):
        """Handle successful function call."""
        self.failure_count = 0
        if self.state == "HALF_OPEN":
            self.state = "CLOSED"
            logger.info("Circuit breaker CLOSED after successful recovery")

    def _on_failure(self):
        """Handle failed function call."""
        self.failure_count += 1
        self.last_failure_time = time.time()

        if self.failure_count >= self.failure_threshold:
            self.state = "OPEN"
            logger.error(
                "Circuit breaker OPEN after %d failures. Will attempt recovery in %d seconds",
                self.failure_count, self.recovery_timeout
            )


if __name__ == "__main__":
    # Example usage
    logging.basicConfig(level=logging.DEBUG)

    class TestError(Exception):
        """Exception for testing retry logic."""

    @retry_on_failure(max_retries=3, base_delay=1.0)
    def unreliable_function(success_on_attempt: int):
        """Test function that succeeds on specified attempt."""
        if not hasattr(unreliable_function, 'attempt'):
            unreliable_function.attempt = 0
        unreliable_function.attempt += 1

        if unreliable_function.attempt < success_on_attempt:
            raise TestError(f"Failed on attempt {unreliable_function.attempt}")

        return f"Success on attempt {unreliable_function.attempt}"

    try:
        result = unreliable_function(3)  # pylint: disable=redefined-outer-name
        print(result)
    except RetryExhaustedError as e:  # pylint: disable=redefined-outer-name
        print(f"Function failed: {e}")
