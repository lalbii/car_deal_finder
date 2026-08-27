from __future__ import annotations

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
