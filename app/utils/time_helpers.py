"""Time utility functions."""

from datetime import datetime, timedelta, timezone
from typing import Optional


def now_utc() -> datetime:
    """Get current UTC datetime."""
    return datetime.now(timezone.utc)


def now_timestamp() -> int:
    """Get current Unix timestamp."""
    return int(now_utc().timestamp())


def from_timestamp(ts: int) -> datetime:
    """Convert Unix timestamp to datetime."""
    return datetime.fromtimestamp(ts, tz=timezone.utc)


def to_datetime(dt: Optional[datetime]) -> Optional[datetime]:
    """Ensure datetime is timezone-aware (UTC)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_datetime(dt: Optional[datetime], fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    """Format datetime to string."""
    if dt is None:
        return ""
    return to_datetime(dt).strftime(fmt)


def add_seconds(dt: datetime, seconds: int) -> datetime:
    """Add seconds to datetime."""
    return to_datetime(dt) + timedelta(seconds=seconds)


def time_ago(dt: datetime) -> str:
    """Get human-readable time ago string."""
    if dt is None:
        return "unknown"

    delta = now_utc() - to_datetime(dt)
    seconds = int(delta.total_seconds())

    if seconds < 60:
        return f"{seconds}s ago"
    elif seconds < 3600:
        return f"{seconds // 60}m ago"
    elif seconds < 86400:
        return f"{seconds // 3600}h ago"
    else:
        return f"{seconds // 86400}d ago"


def market_is_open() -> bool:
    """Check if US market is currently open."""
    now = now_utc()
    # US market is open 9:30 AM - 4:00 PM EST, Monday-Friday
    # Convert to EST (UTC-5 in winter, UTC-4 in summer)
    est_time = now - timedelta(hours=5)  # Simplified for winter
    hour = est_time.hour
    minute = est_time.minute
    weekday = est_time.weekday()

    # Check if weekday (0-4, Monday-Friday)
    if weekday >= 5:
        return False

    # Check if market hours (9:30 AM - 4:00 PM)
    market_open = 9 * 60 + 30  # 9:30 AM in minutes
    market_close = 16 * 60  # 4:00 PM in minutes
    current_time = hour * 60 + minute

    return market_open <= current_time < market_close


def get_trading_days(start: datetime, end: datetime) -> list[datetime]:
    """Get list of trading days between two dates (excluding weekends)."""
    trading_days = []
    current = to_datetime(start).replace(hour=0, minute=0, second=0, microsecond=0)
    end_dt = to_datetime(end).replace(hour=0, minute=0, second=0, microsecond=0)

    while current <= end_dt:
        if current.weekday() < 5:  # Monday-Friday
            trading_days.append(current)
        current += timedelta(days=1)

    return trading_days
