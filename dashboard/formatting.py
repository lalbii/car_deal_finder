from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

import pandas as pd


def format_euro(value: Any) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"€{int(round(float(value))):,}".replace(",", ".")


def format_mileage(value: Any) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{int(round(float(value))):,} km".replace(",", ".")


def format_percent(value: Any, decimals: int = 1) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{float(value):.{decimals}f}%"


def format_signed_euro(value: Any) -> str:
    if value is None or pd.isna(value):
        return "—"
    amount = int(round(float(value)))
    sign = "+" if amount > 0 else "-" if amount < 0 else ""
    return f"{sign}€{abs(amount):,}".replace(",", ".")


def format_signed_percent(value: Any, decimals: int = 1) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{float(value):+.{decimals}f}%"


def format_score(value: Any) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{float(value):.3f}"


def parse_timestamp(value: Any) -> pd.Timestamp | None:
    if value is None or pd.isna(value) or value == "":
        return None
    ts = pd.to_datetime(value, utc=True, errors="coerce")
    if pd.isna(ts):
        return None
    return ts


def format_datetime(value: Any) -> str:
    """Render a persisted timestamp compactly in UTC, or an explicit placeholder."""
    timestamp = parse_timestamp(value)
    return "—" if timestamp is None else timestamp.strftime("%Y-%m-%d %H:%M")


_DATE_ONLY_PATTERNS = (
    (re.compile(r"^\d{2}\.\d{2}\.\d{4}$"), "%d.%m.%Y"),
    (re.compile(r"^\d{4}-\d{2}-\d{2}$"), "%Y-%m-%d"),
)


def parse_listing_date(value: Any) -> tuple[pd.Timestamp | None, bool]:
    """Parse the persisted publication date and report whether it is date-only.

    Kleinanzeigen currently supplies posted_date as DD.MM.YYYY. Date-only values
    are interpreted as midnight UTC solely for deterministic calendar-day
    arithmetic; callers must not display sub-day precision for them.
    """
    if value is None or pd.isna(value) or value == "":
        return None, False
    if isinstance(value, str):
        text = value.strip()
        for pattern, date_format in _DATE_ONLY_PATTERNS:
            if pattern.fullmatch(text):
                parsed = pd.to_datetime(
                    text, format=date_format, utc=True, errors="coerce"
                )
                return (None, True) if pd.isna(parsed) else (parsed, True)
    return parse_timestamp(value), False


def format_listing_date(value: Any) -> str:
    """Render the canonical Kleinanzeigen publication date without fake time."""
    timestamp, _ = parse_listing_date(value)
    return "—" if timestamp is None else timestamp.strftime("%Y-%m-%d")


def format_listing_age(posted_date: Any, last_checked_at: Any) -> str:
    """Render age at the most recent direct check, or unavailable if invalid."""
    published, date_only = parse_listing_date(posted_date)
    checked = parse_timestamp(last_checked_at)
    if published is None or checked is None:
        return "—"

    if date_only:
        days = (checked.normalize() - published.normalize()).days
        return "—" if days < 0 else f"{days}d"

    seconds = int((checked - published).total_seconds())
    if seconds < 0:
        return "—"
    hours = seconds // 3_600
    days, remaining_hours = divmod(hours, 24)
    if days and remaining_hours:
        return f"{days}d {remaining_hours}h"
    if days:
        return f"{days}d"
    return f"{hours}h"


def relative_time(value: Any, now: pd.Timestamp | None = None) -> str:
    ts = parse_timestamp(value)
    if ts is None:
        return "—"

    now = now or pd.Timestamp.now(tz="UTC")
    delta = now - ts
    seconds = max(0, int(delta.total_seconds()))

    if seconds < 60:
        return f"{seconds}s ago"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    return f"{days}d ago"
