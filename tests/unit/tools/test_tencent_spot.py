"""Tencent batch-quote fallback for the A-share spot table.

Production (Tencent Cloud host) verified 2026-09-28: EM push2's
``stock_zh_a_spot_em`` — the full-market spot table the pipeline slices
per symbol — dies with RemoteDisconnected, which starved every CN symbol
of its quote AND (through the spot-gates-history design) of its daily
bars. Tencent's qt.gtimg.cn batch quote endpoint answers from the same
box. Contract traps pinned here: the body is GBK (not UTF-8), lines are
``v_sh600000="1~浦发银行~600000~..."`` with ``~``-split anchors ([1] name,
[2] code, [3] price, [4] prev close, [5] open, [6] volume in 手, [33]
high, [34] low, [37] amount in 万元), and the emitted frame must carry
East Money's spot-table column contract so the existing slicer consumes
it with zero changes. Offline fakes throughout.
"""

from __future__ import annotations

from typing import Any

import pytest

import app.tools.data.tencent_spot as tencent_spot_mod
from app.tools.data.tencent_spot import tencent_cn_spot_table

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


def _quote_line(
    tencent_code: str,
    name: str,
    code: str,
    price: str,
    prev_close: str,
    open_: str,
    volume_lots: str,
    timestamp: str,
    high: str,
    low: str,
    amount_wan: str,
) -> str:
    """One qt.gtimg.cn response line with the production ~-split anchors.

    Unobserved positions stay empty strings — the parser must read only
    the anchored indices, never lean on filler fields.
    """
    fields = [""] * 40
    fields[0] = "1"
    fields[1] = name
    fields[2] = code
    fields[3] = price
    fields[4] = prev_close
    fields[5] = open_
    fields[6] = volume_lots
    fields[30] = timestamp
    fields[33] = high
    fields[34] = low
    fields[37] = amount_wan
    return f'v_{tencent_code}="' + "~".join(fields) + '";'


# Anchors cross-verified against Tencent's own kline on 2026-09-28:
# volume 1,184,853 手 == kline 118,485,300 股 ÷ 100; amount 108,085 万
# × 1e4 ≈ kline turnover 1,080,846,770 元.
_SH600000_LINE = _quote_line(
    tencent_code="sh600000",
    name="浦发银行",
    code="600000",
    price="9.16",
    prev_close="9.00",
    open_="9.03",
    volume_lots="1184853",
    timestamp="20260928161458",
    high="9.18",
    low="9.00",
    amount_wan="108085",
)
_SZ000001_LINE = _quote_line(
    tencent_code="sz000001",
    name="平安银行",
    code="000001",
    price="10.50",
    prev_close="10.30",
    open_="10.40",
    volume_lots="900000",
    timestamp="20260928161458",
    high="10.60",
    low="10.30",
    amount_wan="94000",
)


class _FakeResponse:
    """requests.Response stand-in: status code + raw bytes content."""

    def __init__(self, *, status_code: int = 200, content: bytes = b"") -> None:
        self.status_code = status_code
        self.content = content


class _RecorderGet:
    """Stands in for requests.get; records every call's url/headers/timeout."""

    def __init__(self, *, response: Any = None, error: Exception | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._response = response
        self._error = error

    def __call__(self, url: str, **kwargs: Any) -> Any:
        self.calls.append({"url": url, **kwargs})
        if self._error is not None:
            raise self._error
        return self._response


class TestTencentCnSpotTable:
    def test_one_batch_get_for_all_symbols(self, monkeypatch) -> None:
        """N symbols ride ONE request — mirroring the EM spot table's
        single-round-trip design; a per-symbol fan-out would re-ask the
        endpoint N times for what EM served in one."""
        body = (_SH600000_LINE + "\n" + _SZ000001_LINE).encode("gbk")
        recorder = _RecorderGet(response=_FakeResponse(content=body))
        monkeypatch.setattr(tencent_spot_mod.requests, "get", recorder)

        df = tencent_cn_spot_table(["600000", "000001"])

        assert df is not None and len(df) == 2
        assert len(recorder.calls) == 1
        call = recorder.calls[0]
        assert call["url"] == "https://qt.gtimg.cn/q=sh600000,sz000001"
        assert "Mozilla" in call["headers"]["User-Agent"]
        assert call["timeout"] == 15

    def test_sz_prefix_routing(self, monkeypatch) -> None:
        """0/3-leading codes route to sz, everything else to sh — the same
        split the kline fallback uses; a swapped prefix asks for the wrong
        security."""
        recorder = _RecorderGet(response=_FakeResponse(content=_SH600000_LINE.encode("gbk")))
        monkeypatch.setattr(tencent_spot_mod.requests, "get", recorder)

        tencent_cn_spot_table(["600000", "300750", "000001"])

        assert recorder.calls[0]["url"] == "https://qt.gtimg.cn/q=sh600000,sz300750,sz000001"

    def test_gbk_body_decodes_into_em_column_contract(self, monkeypatch) -> None:
        """The whole point: a GBK body becomes an EM spot table — Chinese
        name included — with 涨跌额/涨跌幅/振幅 derived against 昨收 and 成交额
        converted 万 -> 元, in East Money's exact column order so the
        existing slicer is a zero-change consumer."""
        recorder = _RecorderGet(response=_FakeResponse(content=_SH600000_LINE.encode("gbk")))
        monkeypatch.setattr(tencent_spot_mod.requests, "get", recorder)

        df = tencent_cn_spot_table(["600000"])

        assert df is not None
        assert list(df.columns) == _EM_SPOT_COLUMNS
        row = df.iloc[0]
        assert row["代码"] == "600000"
        assert row["名称"] == "浦发银行"
        assert row["最新价"] == pytest.approx(9.16)
        assert row["昨收"] == pytest.approx(9.00)
        assert row["今开"] == pytest.approx(9.03)
        assert row["成交量"] == 1184853  # 手 on both sides — no conversion
        assert row["成交额"] == pytest.approx(1_080_850_000.0)  # 万 -> 元
        assert row["涨跌额"] == pytest.approx(0.16)
        assert row["涨跌幅"] == pytest.approx(1.7777778)
        assert row["振幅"] == pytest.approx(2.0)
        assert row["最高"] == pytest.approx(9.18)
        assert row["最低"] == pytest.approx(9.00)

    def test_malformed_line_skipped_good_rows_kept(self, monkeypatch) -> None:
        """Tencent answers unknown codes with ``v_pv_none`` and junk lines
        exist — one bad line must cost only its own row, never the table."""
        body = "\n".join(
            [
                'v_pv_none="1";',  # unknown-code marker: no anchors at all
                _SH600000_LINE,
                "garbage without an equals sign",  # no key/value shape
                'v_sh688981="1~too~few~fields";',  # anchors unreachable
            ]
        ).encode("gbk")
        recorder = _RecorderGet(response=_FakeResponse(content=body))
        monkeypatch.setattr(tencent_spot_mod.requests, "get", recorder)

        df = tencent_cn_spot_table(["600000"])

        assert df is not None
        assert len(df) == 1
        assert df.iloc[0]["代码"] == "600000"

    def test_non_numeric_anchor_kills_the_row(self, monkeypatch) -> None:
        """A price anchor of "n/a" makes the derived fields garbage — the
        row is untrustworthy and skipped; every row dead means the table
        is None, the contract the slicer already understands."""
        bad = _quote_line(
            tencent_code="sh600000",
            name="浦发银行",
            code="600000",
            price="n/a",
            prev_close="9.00",
            open_="9.03",
            volume_lots="1184853",
            timestamp="20260928161458",
            high="9.18",
            low="9.00",
            amount_wan="108085",
        )
        recorder = _RecorderGet(response=_FakeResponse(content=bad.encode("gbk")))
        monkeypatch.setattr(tencent_spot_mod.requests, "get", recorder)

        assert tencent_cn_spot_table(["600000"]) is None

    def test_http_non_200_returns_none(self, monkeypatch) -> None:
        recorder = _RecorderGet(response=_FakeResponse(status_code=500))
        monkeypatch.setattr(tencent_spot_mod.requests, "get", recorder)

        assert tencent_cn_spot_table(["600000"]) is None

    def test_empty_body_returns_none(self, monkeypatch) -> None:
        recorder = _RecorderGet(response=_FakeResponse(content=b""))
        monkeypatch.setattr(tencent_spot_mod.requests, "get", recorder)

        assert tencent_cn_spot_table(["600000"]) is None

    def test_empty_symbols_returns_none_without_http(self, monkeypatch) -> None:
        """Nothing to ask for means no request at all."""
        recorder = _RecorderGet(response=_FakeResponse(content=b""))
        monkeypatch.setattr(tencent_spot_mod.requests, "get", recorder)

        assert tencent_cn_spot_table([]) is None
        assert recorder.calls == []

    def test_request_exception_returns_none(self, monkeypatch) -> None:
        """Timeout/connection errors must degrade to None, never raise."""
        recorder = _RecorderGet(error=TimeoutError("connect timed out"))
        monkeypatch.setattr(tencent_spot_mod.requests, "get", recorder)

        assert tencent_cn_spot_table(["600000"]) is None
