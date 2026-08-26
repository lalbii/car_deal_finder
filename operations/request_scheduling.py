from collections.abc import Mapping
from datetime import datetime, timedelta, timezone


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Scheduling timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


def parse_persisted_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        # Legacy values were written with datetime.now(), so interpret them in
        # the server's local timezone before comparing them with UTC timestamps.
        parsed = parsed.astimezone()
    return parsed.astimezone(timezone.utc)


def _is_stale(
    timestamp: object,
    now: datetime,
    interval: timedelta,
) -> bool:
    if interval.total_seconds() <= 0:
        raise ValueError("Scheduling intervals must be greater than zero")
    checked_at = parse_persisted_datetime(timestamp)
    if checked_at is None:
        return True
    return _as_utc(now) - checked_at >= interval


def should_refresh_detail(
    listing: Mapping[str, object] | None,
    now: datetime,
    refresh_interval: timedelta,
) -> bool:
    if listing is None:
        return True
    if not listing.get("is_active", True):
        return True
    return _is_stale(listing.get("last_detail_at"), now, refresh_interval)


def should_check_status(
    listing: Mapping[str, object],
    now: datetime,
    status_check_interval: timedelta,
) -> bool:
    return _is_stale(
        listing.get("last_checked_at"),
        now,
        status_check_interval,
    )
