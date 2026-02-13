"""Data validation utilities."""

import re
from typing import Any, Optional


def validate_stock_symbol(symbol: str) -> bool:
    """Validate stock symbol format."""
    if not symbol:
        return False

    symbol = symbol.upper().strip()

    # US stocks: 1-5 letters
    if re.match(r"^[A-Z]{1,5}$", symbol):
        return True

    # Chinese stocks: 6 digits
    if re.match(r"^\d{6}$", symbol):
        return True

    # HK stocks: 4-5 digits followed by .HK (with optional leading 0)
    if re.match(r"^\d{4,5}\.HK$", symbol):
        return True

    return False


def normalize_stock_symbol(symbol: str) -> str:
    """Normalize stock symbol to uppercase and trimmed."""
    return symbol.upper().strip()


def validate_date_range(
    start_date: Optional[Any], end_date: Optional[Any]
) -> tuple[Optional[Any], Optional[Any]]:
    """Validate date range."""
    if start_date is None and end_date is None:
        return None, None

    if start_date and end_date and start_date > end_date:
        raise ValueError("start_date must be before end_date")

    return start_date, end_date


def validate_positive_number(value: Any, name: str = "value") -> float:
    """Validate that a value is a positive number."""
    try:
        num_value = float(value)
        if num_value < 0:
            raise ValueError(f"{name} must be positive")
        return num_value
    except (TypeError, ValueError) as e:
        raise ValueError(f"{name} must be a valid number: {e}")


def validate_percentage(value: Any, name: str = "value") -> float:
    """Validate that a value is a percentage (0-100)."""
    num_value = validate_positive_number(value, name)
    if num_value > 100:
        raise ValueError(f"{name} must be between 0 and 100")
    return num_value


def validate_email(email: str) -> bool:
    """Validate email format."""
    pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    return bool(re.match(pattern, email))


def sanitize_string(value: Any, max_length: int = 1000) -> str:
    """Sanitize string input."""
    if value is None:
        return ""

    result = str(value).strip()
    if len(result) > max_length:
        result = result[:max_length]

    # Remove any potentially harmful characters
    result = re.sub(r"[\x00-\x1f\x7f-\x9f]", "", result)

    return result


def validate_pagination(
    page: int = 1, page_size: int = 20, max_page_size: int = 100
) -> tuple[int, int]:
    """Validate and correct pagination parameters."""
    page = max(1, page)
    page_size = max(1, min(page_size, max_page_size))
    return page, page_size


def validate_sort_field(
    field: str, allowed_fields: list[str], default: str = "created_at"
) -> str:
    """Validate sort field against allowed fields."""
    if field not in allowed_fields:
        return default
    return field


def validate_sort_order(order: str, default: str = "desc") -> str:
    """Validate sort order."""
    if order.lower() not in ("asc", "desc"):
        return default
    return order.lower()
