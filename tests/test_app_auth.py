import pytest

from src import app_auth
from src.app_auth import (
    AUTH_THROTTLE_STATE_KEY,
    AuthenticationStatus,
    authenticate_password,
    authenticated_session_is_valid,
    build_authenticated_session,
    get_app_password,
    get_password_throttle_status,
    is_four_digit_pin,
    is_valid_app_password,
    verify_password,
)


class Clock:
    def __init__(self, now=100.0):
        self.now = now

    def __call__(self):
        return self.now


def test_streamlit_secret_takes_precedence_over_stale_environment_password():
    password = get_app_password(
        {"APP_PASSWORD": "streamlit-secret"},
        {"APP_PASSWORD": "deployment-secret"},
    )

    assert password == "streamlit-secret"


def test_missing_or_invalid_values_fail_closed():
    assert get_app_password({"APP_PASSWORD": "streamlit-secret"}, {}) == "streamlit-secret"
    assert get_app_password({}, {}) is None
    assert get_app_password({"APP_PASSWORD": "   "}, {}) is None
    assert get_app_password({"APP_PASSWORD": 1234}, {}) is None


def test_explicit_invalid_secret_never_falls_back_to_stale_environment_password():
    environment = {"APP_PASSWORD": "environment-password-at-least-20"}

    assert get_app_password({"APP_PASSWORD": 1234}, environment) is None
    assert get_app_password({"APP_PASSWORD": "   "}, environment) is None


def test_missing_secret_key_falls_back_to_environment_password():
    assert get_app_password(
        {},
        {"APP_PASSWORD": "environment-password-at-least-20"},
    ) == "environment-password-at-least-20"


def test_unavailable_secrets_mapping_does_not_expose_or_break_environment_fallback():
    class UnavailableSecrets(dict):
        def get(self, _key, _default=None):
            raise RuntimeError("secrets provider unavailable")

    assert get_app_password(UnavailableSecrets(), {"APP_PASSWORD": "environment-secret"}) == (
        "environment-secret"
    )


@pytest.mark.parametrize(
    "value",
    ["0123", "9876", "x" * 20, "x" * 256],
)
def test_app_password_policy_accepts_four_ascii_digits_or_long_password(value):
    assert is_valid_app_password(value)


@pytest.mark.parametrize(
    "value",
    [
        "123",
        "12345",
        "12a4",
        "１２３４",
        " 1234",
        "1234 ",
        "x" * 19,
        "x" * 257,
        1234,
        None,
    ],
)
def test_app_password_policy_rejects_ambiguous_or_unsupported_values(value):
    assert not is_valid_app_password(value)


def test_four_digit_pin_check_is_ascii_only_and_preserves_leading_zero():
    assert is_four_digit_pin("0123")
    assert not is_four_digit_pin("１２３４")
    assert not is_four_digit_pin("12a4")


def test_password_verification_uses_fixed_width_constant_time_comparison(monkeypatch):
    compared = []

    def fake_compare_digest(left, right):
        compared.append((left, right))
        return left == right

    monkeypatch.setattr(app_auth.hmac, "compare_digest", fake_compare_digest)

    assert verify_password("correct horse", "correct horse") is True
    assert verify_password("wrong", "correct horse") is False
    assert all(len(left) == len(right) == 32 for left, right in compared)
    assert verify_password(None, "correct horse") is False
    assert verify_password("correct horse", "") is False


def test_missing_configuration_never_authenticates_or_creates_session_state():
    state = {}

    result = authenticate_password("anything", None, state)

    assert result.status is AuthenticationStatus.NOT_CONFIGURED
    assert result.authenticated is False
    assert result.configured is False
    assert state == {}


def test_fifth_failed_attempt_starts_five_minute_session_cooldown():
    clock = Clock()
    state = {}

    for expected_failures in range(1, 5):
        result = authenticate_password("wrong", "secret", state, clock=clock)
        assert result.status is AuthenticationStatus.INVALID
        assert result.failed_attempts == expected_failures
        assert result.attempts_remaining == 5 - expected_failures

    result = authenticate_password("wrong", "secret", state, clock=clock)

    assert result.status is AuthenticationStatus.LOCKED
    assert result.locked is True
    assert result.failed_attempts == 5
    assert result.attempts_remaining == 0
    assert result.retry_after_seconds == pytest.approx(300)
    assert state[AUTH_THROTTLE_STATE_KEY] == {
        "failed_attempts": 5,
        "locked_until": 400.0,
    }
    assert "wrong" not in repr(state)
    assert "secret" not in repr(state)


def test_correct_password_is_rejected_during_cooldown_then_clears_expired_state():
    clock = Clock()
    state = {}
    for _ in range(5):
        authenticate_password("wrong", "secret", state, clock=clock)

    clock.now += 125
    blocked = authenticate_password("secret", "secret", state, clock=clock)
    assert blocked.status is AuthenticationStatus.LOCKED
    assert blocked.retry_after_seconds == pytest.approx(175)

    clock.now += 175
    accepted = authenticate_password("secret", "secret", state, clock=clock)
    assert accepted.status is AuthenticationStatus.AUTHENTICATED
    assert accepted.authenticated is True
    assert AUTH_THROTTLE_STATE_KEY not in state


def test_failed_attempts_are_isolated_by_session_mapping():
    clock = Clock()
    first_session = {}
    second_session = {}

    for _ in range(5):
        authenticate_password("wrong", "secret", first_session, clock=clock)

    assert get_password_throttle_status(first_session, clock=clock).locked is True
    assert get_password_throttle_status(second_session, clock=clock).locked is False
    assert authenticate_password("secret", "secret", second_session, clock=clock).authenticated


def test_malformed_throttle_state_fails_closed_for_a_fresh_cooldown():
    clock = Clock()
    state = {AUTH_THROTTLE_STATE_KEY: {"failed_attempts": "five"}}

    status = get_password_throttle_status(state, clock=clock)

    assert status.locked is True
    assert status.failed_attempts == 5
    assert status.retry_after_seconds == pytest.approx(300)


@pytest.mark.parametrize(
    ("max_failures", "cooldown_seconds"),
    [(0, 300), (True, 300), (5, 0), (5, float("inf")), (5, True)],
)
def test_invalid_throttle_policy_is_rejected(max_failures, cooldown_seconds):
    with pytest.raises(ValueError):
        authenticate_password(
            "candidate",
            "secret",
            {},
            max_failures=max_failures,
            cooldown_seconds=cooldown_seconds,
        )


def test_authenticated_session_expires_and_password_rotation_invalidates_it():
    clock = Clock(now=1_000.0)
    signing_key = b"k" * 32
    session = build_authenticated_session(
        "a-long-configured-password",
        signing_key,
        clock=clock,
    )
    assert "a-long-configured-password" not in repr(session)

    assert authenticated_session_is_valid(
        session,
        "a-long-configured-password",
        signing_key,
        clock=clock,
        max_age_seconds=100,
    )
    assert not authenticated_session_is_valid(
        session,
        "a-different-long-password",
        signing_key,
        clock=clock,
        max_age_seconds=100,
    )

    clock.now += 101
    assert not authenticated_session_is_valid(
        session,
        "a-long-configured-password",
        signing_key,
        clock=clock,
        max_age_seconds=100,
    )


def test_authenticated_session_rejects_malformed_state_and_weak_signer():
    assert not authenticated_session_is_valid(
        {"version": "invalid", "authenticated_at": float("nan")},
        "a-long-configured-password",
        b"k" * 32,
    )
    with pytest.raises(ValueError, match="32 bytes"):
        build_authenticated_session("a-long-configured-password", b"too-short")
