import pytest

from src.rate_limiter import SlidingWindowRateLimiter


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


def test_sliding_window_blocks_until_oldest_slot_expires():
    clock = Clock()
    limiter = SlidingWindowRateLimiter(2, 60, clock=clock)

    assert limiter.acquire() == 0
    clock.now += 10
    assert limiter.acquire() == 0
    clock.now += 10
    assert limiter.acquire() == pytest.approx(40)

    clock.now += 40
    assert limiter.acquire() == 0


@pytest.mark.parametrize("max_events", [0, -1, True])
def test_sliding_window_rejects_invalid_capacity(max_events):
    with pytest.raises(ValueError):
        SlidingWindowRateLimiter(max_events, 60)
