"""Tencent batch-quote fallback for the A-share spot table.

Production (Tencent Cloud host) verified 2026-09-28: EM push2's
``stock_zh_a_spot_em`` — the full-market spot table the pipeline slices
per symbol — RemoteDisconnected, starving every CN symbol of its quote.
Tencent's qt.gtimg.cn batch quote endpoint answers from the same box:
one GET for all symbols (mirroring the EM spot table's single-round-trip
design), body GBK-encoded, lines ``v_sh600000="1~浦发银行~600000~..."``.
``~``-split anchors (0-indexed, cross-verified against Tencent's own
kline on 2026-09-28): [1] name, [2] code, [3] price, [4] prev close,
[5] open, [6] volume in 手 (EM's 成交量 unit — no conversion), [33] high,
[34] low, [37] amount in 万元. 涨跌额/涨跌幅/振幅 derive against 昨收;
成交额 converts 万 -> 元. The frame carries East Money's spot-table column
contract so the existing slicer consumes it with zero changes. Failure
degrades to None — never raises — the same contract the EM fetch already
has upstream.
"""

from typing import Any

import pandas as pd
import requests

from app.utils.logging import get_logger

logger = get_logger(__name__)

_TENCENT_QUOTE_URL = "https://qt.gtimg.cn/q="
_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

# East Money stock_zh_a_spot_em column contract (名称 included) — the
# exact shape _sync_fetch_akshare_stock_info slices.
_EM_SPOT_COLUMNS = [
    "代码",
    "名称",
    "最新价",
    "涨跌额",
    "涨跌幅",
    "成交量",
    "成交额",
    "振幅",
    "最高",
    "最低",
    "今开",
    "昨收",
]


def _cn_quote_symbols(symbols: list[str]) -> list[str]:
    """6-digit A-share codes -> Tencent market-prefixed codes.

    Same SH/SZ split as the kline fallback's helper (0/3 -> Shenzhen,
    anything else -> Shanghai); kept local instead of importing from the
    fetcher so this module stays import-cycle-free for any caller.
    """
    return [f"sz{s}" if s.startswith(("0", "3")) else f"sh{s}" for s in symbols]


def _num(fields: list[str], idx: int) -> float | None:
    """Anchor as float, None when absent/non-numeric (not a crash)."""
    try:
        return float(fields[idx])
    except (IndexError, TypeError, ValueError):
        return None


def _parse_quote_line(line: str) -> dict[str, Any] | None:
    """One ``v_sh600000="..."`` line -> an EM spot-table row dict.

    None for any malformed line (no key/value shape, unreachable anchors,
    non-numeric fields, zero prev-close making the derived fields divide
    by zero) — the caller skips it and keeps the healthy rows.
    """
    if "=" not in line:
        return None
    fields = line.split("=", 1)[1].strip().strip(";").strip('"').split("~")
    if len(fields) <= 37:
        return None
    name, code = fields[1], fields[2]
    price = _num(fields, 3)
    prev_close = _num(fields, 4)
    open_ = _num(fields, 5)
    volume = _num(fields, 6)
    high = _num(fields, 33)
    low = _num(fields, 34)
    amount_wan = _num(fields, 37)
    if (
        not name
        or not code
        or price is None
        or not prev_close
        or open_ is None
        or volume is None
        or high is None
        or low is None
        or amount_wan is None
    ):
        return None
    return {
        "代码": code,
        "名称": name,
        "最新价": price,
        "涨跌额": price - prev_close,
        "涨跌幅": (price - prev_close) / prev_close * 100,
        "成交量": int(volume),
        "成交额": amount_wan * 10000,
        "振幅": (high - low) / prev_close * 100,
        "最高": high,
        "最低": low,
        "今开": open_,
        "昨收": prev_close,
    }


def tencent_cn_spot_table(symbols: list[str]) -> pd.DataFrame | None:
    """A-share spot table from Tencent's batch quote, EM-column-shaped.

    ONE GET carries every symbol — the same single-round-trip design the
    EM spot table has, so a whole-market run stays at one request.
    Best-effort per line: malformed lines are skipped; all lines dead,
    HTTP failure, or empty input degrade to None, never an exception.
    """
    if not symbols:
        return None
    try:
        response = requests.get(
            _TENCENT_QUOTE_URL + ",".join(_cn_quote_symbols(symbols)),
            headers=_HEADERS,
            timeout=15,
        )
        if response.status_code != 200:
            return None
        text = response.content.decode("gbk", errors="replace")

        rows = []
        for line in text.splitlines():
            row = _parse_quote_line(line.strip())
            if row is not None:
                rows.append(row)
        if not rows:
            return None
        return pd.DataFrame(rows, columns=_EM_SPOT_COLUMNS)
    except Exception as e:
        logger.warning(f"[tencent-spot] failed for {len(symbols)} symbols: {e}")
        return None
