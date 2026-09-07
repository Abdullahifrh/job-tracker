import pytest
from src.retry import retry_with_backoff

def test_retries_until_success():
    calls = {"count": 0}

    @retry_with_backoff(max_attempts=3, base_delay=0.01)
    def flaky():
        calls["count"] += 1
        if calls["count"] < 3:
            raise ValueError("transient failure")
        return "ok"

    assert flaky() == "ok"
    assert calls["count"] == 3

def test_raises_after_max_attempts():
    calls = {"count": 0}

    @retry_with_backoff(max_attempts=2, base_delay=0.01)
    def always_fails():
        calls["count"] += 1
        raise ValueError("permanent failure")

    with pytest.raises(ValueError):
        always_fails()

    assert calls["count"] == 2

def test_succeeds_on_first_try_without_retry():
    calls = {"count": 0}

    @retry_with_backoff(max_attempts=3, base_delay=0.01)
    def always_works():
        calls["count"] += 1
        return "ok"

    assert always_works() == "ok"
    assert calls["count"] == 1
