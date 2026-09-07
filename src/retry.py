import functools
import logging
import time

logger = logging.getLogger(__name__)

def retry_with_backoff(max_attempts: int = 3, base_delay: float = 1.0):
    """Retry a function with exponential backoff on any exception, re-raising after the final attempt."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            attempt = 0
            while True:
                try:
                    return func(*args, **kwargs)
                except Exception as exc:
                    attempt += 1
                    if attempt >= max_attempts:
                        logger.error("%s failed after %d attempts: %s", func.__name__, attempt, exc)
                        raise
                    delay = base_delay * (2 ** (attempt - 1))
                    logger.warning(
                        "%s failed (attempt %d/%d): %s — retrying in %.1fs",
                        func.__name__, attempt, max_attempts, exc, delay,
                    )
                    time.sleep(delay)
        return wrapper
    return decorator
