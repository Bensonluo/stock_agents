"""Stock-symbol validation utilities (the two validators with live consumers)."""

import re


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


def validate_symbol_count(symbols: list[str], max_count: int) -> None:
    """Reject symbol lists larger than max_count (0 disables the cap).

    Each symbol multiplies per-symbol network fetches, analysis and LLM
    work — without a cap one oversized POST holds an analysis-capacity
    slot indefinitely (iteration 174).
    """
    if max_count > 0 and len(symbols) > max_count:
        raise ValueError(f"Too many symbols: {len(symbols)} (max {max_count} per request)")
