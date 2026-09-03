"""Pure password-gate helpers for the Streamlit application.

The module deliberately has no Streamlit or logging dependency.  Callers pass
``st.secrets`` and ``st.session_state`` as ordinary mapping objects, which keeps
the secret out of application state and makes the security behaviour testable.
"""

from __future__ import annotations

import hashlib
import hmac
import math
import os
import time
from collections.abc import Callable, Mapping, MutableMapping
from dataclasses import dataclass
from enum import Enum
from typing import Any


APP_PASSWORD_KEY = "APP_PASSWORD"
AUTH_SESSION_STATE_KEY = "_app_authenticated"
AUTH_THROTTLE_STATE_KEY = "_app_password_throttle"
APP_PIN_LENGTH = 4
MIN_LONG_PASSWORD_LENGTH = 20
MAX_APP_PASSWORD_LENGTH = 256
DEFAULT_MAX_FAILURES = 5
DEFAULT_COOLDOWN_SECONDS = 5 * 60.0
DEFAULT_AUTH_SESSION_TTL_SECONDS = 12 * 60 * 60.0


class AuthenticationStatus(str, Enum):
    """Possible outcomes from one password submission."""

    AUTHENTICATED = "authenticated"
    INVALID = "invalid"
    LOCKED = "locked"
    NOT_CONFIGURED = "not_configured"


@dataclass(frozen=True, slots=True)
class PasswordThrottleStatus:
    """Current failure budget for one session."""

    failed_attempts: int
    attempts_remaining: int
    retry_after_seconds: float

    @property
    def locked(self) -> bool:
        return self.retry_after_seconds > 0


@dataclass(frozen=True, slots=True)
class PasswordAttemptResult:
    """Security-relevant result of one password submission."""

    status: AuthenticationStatus
    failed_attempts: int
    attempts_remaining: int
    retry_after_seconds: float

    @property
    def authenticated(self) -> bool:
        return self.status is AuthenticationStatus.AUTHENTICATED

    @property
    def configured(self) -> bool:
        return self.status is not AuthenticationStatus.NOT_CONFIGURED

    @property
    def locked(self) -> bool:
        return self.status is AuthenticationStatus.LOCKED


_MISSING = object()


def _password_from(
    source: Mapping[str, Any] | None,
) -> tuple[bool, str | None]:
    """Return whether a source defines the key and its usable string value."""

    if source is None:
        return False, None
    try:
        value = source.get(APP_PASSWORD_KEY, _MISSING)
    except Exception:
        # Some lazy mappings (including an unconfigured secrets provider) may
        # raise while being read.  Treat that source as unavailable.
        return False, None
    if value is _MISSING:
        return False, None
    if not isinstance(value, str) or not value.strip():
        return True, None
    return True, value


def get_app_password(
    secrets: Mapping[str, Any] | None = None,
    environ: Mapping[str, Any] | None = None,
) -> str | None:
    """Return ``APP_PASSWORD`` from the environment or a secrets mapping.

    Streamlit Secrets takes precedence so rotating the deployment secret is
    not silently defeated by a stale process environment value. ``None`` is
    returned when neither source contains a non-blank string, so a caller can
    fail closed. Password values are never logged, printed, coerced to strings,
    or written to session state.
    """

    active_environ = os.environ if environ is None else environ
    secret_is_configured, secret_value = _password_from(secrets)
    if secret_is_configured:
        # An explicit but malformed secret must fail closed.  Falling through
        # to a stale environment value would violate Secrets precedence.
        return secret_value
    _, environment_value = _password_from(active_environ)
    return environment_value


def is_four_digit_pin(value: Any) -> bool:
    """Return whether *value* is exactly four ASCII decimal digits."""

    return (
        isinstance(value, str)
        and len(value) == APP_PIN_LENGTH
        and value.isascii()
        and value.isdecimal()
    )


def is_valid_app_password(value: Any) -> bool:
    """Accept a four-digit PIN or the existing long-password policy.

    Leading and trailing whitespace is rejected so a deployment typo cannot
    create a credential that is visually difficult to reproduce.
    """

    if not isinstance(value, str) or value != value.strip():
        return False
    return is_four_digit_pin(value) or (
        MIN_LONG_PASSWORD_LENGTH <= len(value) <= MAX_APP_PASSWORD_LENGTH
    )


def verify_password(candidate: Any, configured_password: Any) -> bool:
    """Verify an exact password using a fixed-length constant-time comparison."""

    if not isinstance(candidate, str) or not isinstance(configured_password, str):
        return False
    if not configured_password.strip():
        return False

    # Hashing both values first keeps the compare operation fixed-width even
    # when the submitted and configured password lengths differ.
    candidate_digest = hashlib.sha256(candidate.encode("utf-8")).digest()
    configured_digest = hashlib.sha256(configured_password.encode("utf-8")).digest()
    return hmac.compare_digest(candidate_digest, configured_digest)


def _validate_signing_key(signing_key: Any) -> bytes:
    if not isinstance(signing_key, bytes) or len(signing_key) < 32:
        raise ValueError("signing_key must contain at least 32 bytes")
    return signing_key


def _auth_session_version(configured_password: Any, signing_key: Any) -> str:
    if not isinstance(configured_password, str) or not configured_password.strip():
        raise ValueError("configured_password must be a non-blank string")
    key = _validate_signing_key(signing_key)
    return hmac.new(
        key,
        b"naver-blog-app-auth\0" + configured_password.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def build_authenticated_session(
    configured_password: Any,
    signing_key: Any,
    *,
    clock: Callable[[], float] = time.time,
) -> dict[str, Any]:
    """Create password-versioned session metadata without storing the password."""

    return {
        "version": _auth_session_version(configured_password, signing_key),
        "authenticated_at": _clock_value(clock),
    }


def authenticated_session_is_valid(
    raw_state: Any,
    configured_password: Any,
    signing_key: Any,
    *,
    clock: Callable[[], float] = time.time,
    max_age_seconds: float = DEFAULT_AUTH_SESSION_TTL_SECONDS,
) -> bool:
    """Validate session age and invalidate it when the configured password changes."""

    if not isinstance(max_age_seconds, (int, float)) or isinstance(max_age_seconds, bool):
        raise ValueError("max_age_seconds must be a positive finite number")
    maximum_age = float(max_age_seconds)
    if not math.isfinite(maximum_age) or maximum_age <= 0:
        raise ValueError("max_age_seconds must be a positive finite number")
    if not isinstance(raw_state, Mapping):
        return False

    version = raw_state.get("version")
    authenticated_at = raw_state.get("authenticated_at")
    if not isinstance(version, str) or not isinstance(authenticated_at, (int, float)):
        return False
    if isinstance(authenticated_at, bool) or not math.isfinite(float(authenticated_at)):
        return False

    now = _clock_value(clock)
    age = now - float(authenticated_at)
    if age < 0 or age > maximum_age:
        return False
    try:
        expected_version = _auth_session_version(configured_password, signing_key)
    except ValueError:
        return False
    return hmac.compare_digest(version, expected_version)


def _validate_policy(max_failures: int, cooldown_seconds: float) -> tuple[int, float]:
    if isinstance(max_failures, bool) or not isinstance(max_failures, int) or max_failures < 1:
        raise ValueError("max_failures must be a positive integer")
    if isinstance(cooldown_seconds, bool) or not isinstance(cooldown_seconds, (int, float)):
        raise ValueError("cooldown_seconds must be a positive finite number")
    cooldown = float(cooldown_seconds)
    if not math.isfinite(cooldown) or cooldown <= 0:
        raise ValueError("cooldown_seconds must be a positive finite number")
    return max_failures, cooldown


def _clock_value(clock: Callable[[], float]) -> float:
    now = float(clock())
    if not math.isfinite(now):
        raise ValueError("clock must return a finite number")
    return now


def _store_lockout(
    session_state: MutableMapping[str, Any],
    *,
    failed_attempts: int,
    locked_until: float,
) -> None:
    session_state[AUTH_THROTTLE_STATE_KEY] = {
        "failed_attempts": failed_attempts,
        "locked_until": locked_until,
    }


def get_password_throttle_status(
    session_state: MutableMapping[str, Any],
    *,
    clock: Callable[[], float] = time.monotonic,
    max_failures: int = DEFAULT_MAX_FAILURES,
    cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS,
) -> PasswordThrottleStatus:
    """Return and, when necessary, normalise one session's throttle state.

    Expired cooldowns are removed.  Malformed or incomplete state is treated as
    locked for a fresh cooldown instead of granting a new attempt budget.
    """

    max_failures, cooldown = _validate_policy(max_failures, cooldown_seconds)
    now = _clock_value(clock)
    raw_state = session_state.get(AUTH_THROTTLE_STATE_KEY)
    if raw_state is None:
        return PasswordThrottleStatus(0, max_failures, 0.0)

    if not isinstance(raw_state, Mapping):
        _store_lockout(
            session_state,
            failed_attempts=max_failures,
            locked_until=now + cooldown,
        )
        return PasswordThrottleStatus(max_failures, 0, cooldown)

    failures = raw_state.get("failed_attempts")
    locked_until = raw_state.get("locked_until")
    valid_failures = (
        isinstance(failures, int)
        and not isinstance(failures, bool)
        and 0 <= failures <= max_failures
    )
    valid_lock = (
        locked_until is None
        or (
            isinstance(locked_until, (int, float))
            and not isinstance(locked_until, bool)
            and math.isfinite(float(locked_until))
        )
    )
    state_is_complete = (failures < max_failures and locked_until is None) or (
        failures == max_failures and locked_until is not None
    ) if valid_failures and valid_lock else False

    if not state_is_complete:
        _store_lockout(
            session_state,
            failed_attempts=max_failures,
            locked_until=now + cooldown,
        )
        return PasswordThrottleStatus(max_failures, 0, cooldown)

    if locked_until is not None:
        retry_after = float(locked_until) - now
        if retry_after > 0:
            return PasswordThrottleStatus(max_failures, 0, retry_after)
        session_state.pop(AUTH_THROTTLE_STATE_KEY, None)
        return PasswordThrottleStatus(0, max_failures, 0.0)

    return PasswordThrottleStatus(failures, max_failures - failures, 0.0)


def reset_password_throttle(session_state: MutableMapping[str, Any]) -> None:
    """Clear only the failed-attempt state after successful authentication."""

    session_state.pop(AUTH_THROTTLE_STATE_KEY, None)


def authenticate_password(
    candidate: Any,
    configured_password: Any,
    session_state: MutableMapping[str, Any],
    *,
    clock: Callable[[], float] = time.monotonic,
    max_failures: int = DEFAULT_MAX_FAILURES,
    cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS,
) -> PasswordAttemptResult:
    """Check one submission and update only that session's failure throttle."""

    max_failures, cooldown = _validate_policy(max_failures, cooldown_seconds)

    if not isinstance(configured_password, str) or not configured_password.strip():
        return PasswordAttemptResult(
            AuthenticationStatus.NOT_CONFIGURED,
            failed_attempts=0,
            attempts_remaining=0,
            retry_after_seconds=0.0,
        )

    throttle = get_password_throttle_status(
        session_state,
        clock=clock,
        max_failures=max_failures,
        cooldown_seconds=cooldown,
    )
    if throttle.locked:
        return PasswordAttemptResult(
            AuthenticationStatus.LOCKED,
            failed_attempts=throttle.failed_attempts,
            attempts_remaining=0,
            retry_after_seconds=throttle.retry_after_seconds,
        )

    if verify_password(candidate, configured_password):
        reset_password_throttle(session_state)
        return PasswordAttemptResult(
            AuthenticationStatus.AUTHENTICATED,
            failed_attempts=0,
            attempts_remaining=max_failures,
            retry_after_seconds=0.0,
        )

    failed_attempts = throttle.failed_attempts + 1
    if failed_attempts >= max_failures:
        now = _clock_value(clock)
        _store_lockout(
            session_state,
            failed_attempts=max_failures,
            locked_until=now + cooldown,
        )
        return PasswordAttemptResult(
            AuthenticationStatus.LOCKED,
            failed_attempts=max_failures,
            attempts_remaining=0,
            retry_after_seconds=cooldown,
        )

    session_state[AUTH_THROTTLE_STATE_KEY] = {
        "failed_attempts": failed_attempts,
        "locked_until": None,
    }
    return PasswordAttemptResult(
        AuthenticationStatus.INVALID,
        failed_attempts=failed_attempts,
        attempts_remaining=max_failures - failed_attempts,
        retry_after_seconds=0.0,
    )
