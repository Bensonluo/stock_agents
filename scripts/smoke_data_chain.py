"""Production data-chain smoke check -- post-deploy verification probe.

Solidifies the ad-hoc docker exec probes from 2026-09-28 into a repeatable
tool. Every check is independent (one PASS/FAIL/SKIP line each), ends with a
summary, and exits 0 when nothing failed.

Run (the script rides the stdin pipe -- deployment/docker/Dockerfile only
COPYs app/, so it never enters the image):

    ssh -i ~/.ssh/ssh_tencent.pem ubuntu@101.43.97.91 \\
        "docker exec -i stock_agent_api python -" < scripts/smoke_data_chain.py

With the --full gated end-to-end analysis chain (hits the real LLM pipeline,
budget up to 4 minutes):

    ssh -i ~/.ssh/ssh_tencent.pem ubuntu@101.43.97.91 \\
        "docker exec -i stock_agent_api python - --full" \\
        < scripts/smoke_data_chain.py

Design notes:

- ``python -`` executes stdin with ``__name__ == "__main__"`` (verified
  2026-09-28), so the main() guard fires under the pipe exactly as in a
  normal script run, while ``python -c`` importing this file stays
  side-effect free.
- Sync on purpose: the Tencent seams are sync functions, akshare is sync,
  and the HTTP probes use requests. The one async island is the sector-ETF
  benchmark check -- the Sina leg lives inside the async
  fetch_benchmark_history wrapper, so that check rides asyncio.run.
- Pre-deploy SKIP semantics: the production container may still run the
  pre-fallback image, where app.tools.data.tencent_spot /
  tencent_benchmark do not exist. Every app.* import is individually
  guarded; an ImportError records SKIP ("module absent (pre-deploy
  image)") instead of crashing the run.
- EM spot FAIL semantics: stock_zh_a_spot_em being blocked from the CN
  host is the known condition the Tencent fallbacks compensate for. A FAIL
  there reads "EM primary path still down", NOT "deployment broken" --
  weigh it against the fallback checks passing. It still counts toward the
  exit code, so a fully green run means EM recovered too.
- Option-signal FAIL semantics: the SSE/QVIX checks carry the same
  informational weighting as EM spot -- a dark CN option feed degrades the
  annotation honestly (insufficient_data) rather than breaking anything,
  so their FAIL reads "feature degraded", not "deployment broken". Both
  checks SKIP pre-deploy (option_signals.py arrived with the options layer).
- Exit codes: 0 = no FAIL, 1 = at least one FAIL. SKIPs never count.
"""

import asyncio
import os
import sys
import time
from datetime import datetime, timedelta

# akshare's tqdm progress bars would garble the one-line-per-check output;
# official off-switch since tqdm 4.66 (harmless no-op on older installs).
os.environ.setdefault("TQDM_DISABLE", "1")

import akshare as ak  # noqa: E402
import pandas as pd  # noqa: E402
import requests  # noqa: E402

# East Money stock_zh_a_spot_em column contract -- kept local (not imported
# from app.tools.data.tencent_spot) so this check keeps validating the
# structure even when the module itself is absent.
EM_SPOT_COLUMNS = [
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

ANALYZE_SYNC_URL = "http://localhost:8000/api/analysis/analyze/sync"


def check_tencent_daily_k() -> tuple[str, str]:
    """Tencent A-share daily bars for 600000 over the last 30 days."""
    end = datetime.now()
    start = end - timedelta(days=30)
    df = ak.stock_zh_a_hist_tx(
        symbol="sh600000",
        start_date=start.strftime("%Y%m%d"),
        end_date=end.strftime("%Y%m%d"),
        adjust="qfq",
    )
    if df is None or df.empty:
        return "FAIL", "empty frame from stock_zh_a_hist_tx"
    latest = pd.to_datetime(df["date"]).max()
    age_days = abs((end - latest.to_pydatetime()).days)
    detail = f"{len(df)} bars, latest {latest:%Y-%m-%d} ({age_days}d old)"
    if len(df) < 15:
        return "FAIL", f"thin history -- {detail} (need >=15 bars)"
    if age_days > 7:
        return "FAIL", f"stale history -- {detail} (need <=7d old)"
    return "PASS", detail


def check_tencent_spot_table() -> tuple[str, str]:
    """Tencent batch spot table in the EM 12-column contract."""
    try:
        from app.tools.data.tencent_spot import tencent_cn_spot_table
    except ImportError:
        return "SKIP", "module absent (pre-deploy image)"
    df = tencent_cn_spot_table(["600000", "000001"])
    if df is None:
        return "FAIL", "tencent_cn_spot_table returned None"
    missing = [c for c in EM_SPOT_COLUMNS if c not in df.columns]
    if missing:
        return "FAIL", f"missing EM columns: {missing}"
    prices = pd.to_numeric(df["最新价"], errors="coerce")
    if prices.isna().any() or not prices.between(1, 10000).all():
        return "FAIL", f"最新价 outside 1-10000 domain: {prices.tolist()}"
    return "PASS", f"{len(df)} rows, 12 EM columns, 最新价 {prices.min()}-{prices.max()}"


def check_tencent_benchmarks() -> tuple[str, str]:
    """Tencent kline for both market benchmarks, >=50 bars each."""
    try:
        from app.tools.data.tencent_benchmark import tencent_index_history
    except ImportError:
        return "SKIP", "module absent (pre-deploy image)"
    details = []
    for symbol in ("000001.SS", "^GSPC"):
        hist = tencent_index_history(symbol)
        if not hist or not hist.get("dates") or not hist.get("close"):
            return "FAIL", f"{symbol}: no history returned"
        n_dates, n_close = len(hist["dates"]), len(hist["close"])
        if n_dates < 50 or n_close < 50:
            return "FAIL", f"{symbol}: only {n_dates} dates / {n_close} closes (need >=50)"
        details.append(f"{symbol} {n_dates} bars")
    return "PASS", ", ".join(details)


def check_sector_etf_benchmark() -> tuple[str, str]:
    """Sector-ETF benchmark chain (XLF) -- the three-leg fallback end to end.

    Exercises the deployed fetch_benchmark_history wrapper under whatever
    state production has yfinance in: yfinance -> tencent (indexes only, no
    ETF mapping) -> Sina (SPDR tickers, the iteration-133 third leg). The
    provider-health snapshot says which leg served, so a PASS is attributable.
    Pre-deploy SKIP is keyed on _SECTOR_ETF_TICKERS -- the pre-fallback image
    already ships an older fetch_benchmark_history, so an ImportError guard
    alone would run old code and misread a missing leg as a broken deploy."""
    try:
        from app.tools.data import fetcher as fetcher_mod
        from app.tools.data.provider_health import provider_health_snapshot
    except ImportError:
        return "SKIP", "module absent (pre-deploy image)"
    if not hasattr(fetcher_mod, "_SECTOR_ETF_TICKERS"):
        return "SKIP", "Sina sector-ETF leg absent (pre-deploy image)"
    try:
        hist = asyncio.run(fetcher_mod.fetch_benchmark_history("XLF"))
    except Exception as e:
        return "FAIL", f"{type(e).__name__}: {e}"
    if not hist or not hist.get("dates") or not hist.get("close"):
        return "FAIL", "no sector-ETF history returned (all three legs dark)"
    if hist.get("symbol") != "XLF":
        return "FAIL", f"symbol mutated: {hist.get('symbol')!r}"
    n = len(hist["close"])
    if n < 50:
        return "FAIL", f"only {n} closes (need >=50)"
    providers = provider_health_snapshot()["providers"]
    if providers.get("sina-benchmark", {}).get("ok"):
        served = "sina"
    elif providers.get("yfinance-benchmark", {}).get("ok"):
        served = "yfinance"
    else:
        served = "unknown"
    return "PASS", f"XLF {n} bars via {served}, latest {hist['dates'][-1]}"


def check_em_financial_indicator() -> tuple[str, str]:
    """EM datacenter financial indicators -- the financial-chain anchor."""
    df = ak.stock_financial_analysis_indicator(symbol="600000")
    if df is None or df.empty:
        return "FAIL", "empty frame from stock_financial_analysis_indicator"
    return "PASS", f"{len(df)} reporting periods, {len(df.columns)} metrics"


def check_em_spot_table() -> tuple[str, str]:
    """EM full-market spot table -- primary-path health, fallback detector."""
    try:
        df = ak.stock_zh_a_spot_em()
    except Exception as e:
        return (
            "FAIL",
            f"EM push2 still blocked ({type(e).__name__}) -- this is the condition the "
            "Tencent fallbacks compensate for; informational, not a deploy blocker",
        )
    if df is None or df.empty:
        return (
            "FAIL",
            "EM push2 still blocked (empty frame) -- informational, not a deploy blocker",
        )
    return "PASS", f"EM push2 recovered: {len(df)} rows"


def check_em_sector_chain() -> tuple[str, str]:
    """EM stock_individual_info_em -- parked sector-benchmark chain."""
    try:
        df = ak.stock_individual_info_em(symbol="600000")
    except Exception as e:
        return "SKIP", f"sector chain parked (EM push2 blocked): {type(e).__name__}"
    if df is None or df.empty:
        return "SKIP", "sector chain parked (EM push2 blocked): empty frame"
    return "PASS", f"{len(df)} info rows -- EM push2 reachable again"


def check_sse_option_snapshot() -> tuple[str, str]:
    """SSE official option trio -- the option-signal layer's primary source.

    Exercises fetch_sse_option_snapshot end to end (risk table + directory
    join + official PCR, with trade-date walkback). None means the CN option
    feed is dark, in which case the annotation degrades honestly to
    insufficient_data -- same informational-FAIL semantics as the EM spot
    check, not a deploy blocker. Pre-deploy SKIP: the module arrived with
    the options layer."""
    try:
        from app.tools.data.option_signals import fetch_sse_option_snapshot
    except ImportError:
        return "SKIP", "module absent (pre-deploy image)"
    try:
        snapshot = fetch_sse_option_snapshot()
    except Exception as e:
        return "FAIL", f"unexpected {type(e).__name__}: {e}"
    if snapshot is None:
        return (
            "FAIL",
            "SSE option risk table unreachable -- option_implied degrades to "
            "insufficient_data; informational, not a deploy blocker",
        )
    status = snapshot.get("status")
    contracts = snapshot.get("contracts") or []
    pcr = snapshot.get("pcr_by_underlying") or {}
    detail = (
        f"status {status}, trade_date {snapshot.get('as_of')}, "
        f"{len(contracts)} contracts, pcr underlyings {len(pcr)}, "
        f"unmatched {snapshot.get('n_unmatched')}"
    )
    if status != "ok" or len(contracts) < 50:
        return "FAIL", f"degraded snapshot -- {detail} (informational, not a deploy blocker)"
    return "PASS", detail


def check_option_implied_annotation() -> tuple[str, str]:
    """Option-implied annotation chain end to end (QVIX regime + IV metrics).

    Re-fetches the snapshot (30-min shared TTL cache -- free after the SSE
    check) and the QVIX context (third-party host with local-store
    fallback), then runs the exact pure pipeline the risk layer uses:
    compute_iv_metrics -> compute_pcr -> build_option_implied. The regime
    label comes only from the QVIX 1-year percentile; a dark QVIX with an
    empty store yields insufficient_data (honest absence), which FAILs here
    informationally."""
    try:
        from app.tools.data.option_signals import (
            build_option_implied,
            compute_iv_metrics,
            compute_pcr,
            fetch_qvix_context,
            fetch_sse_option_snapshot,
        )
        from app.tools.data.qvix_store import get_qvix_store
    except ImportError:
        return "SKIP", "module absent (pre-deploy image)"
    try:
        snapshot = fetch_sse_option_snapshot()
        qvix = fetch_qvix_context(get_qvix_store())
        annotation = build_option_implied(
            compute_iv_metrics(snapshot.get("contracts") if snapshot else None),
            compute_pcr(snapshot.get("pcr_by_underlying") if snapshot else None),
            qvix,
        )
    except Exception as e:
        return "FAIL", f"unexpected {type(e).__name__}: {e}"
    expected_keys = {"status", "regime", "qvix", "iv", "pcr", "generated_at"}
    if set(annotation) != expected_keys:
        return "FAIL", f"annotation shape drift: {sorted(annotation)}"
    if annotation["status"] != "ok" or annotation["regime"] not in {"恐慌", "自满", "中性"}:
        missing = [name for name, part in (("sse snapshot", snapshot), ("qvix", qvix)) if not part]
        why = ", ".join(missing) if missing else "qvix percentile unavailable"
        return (
            "FAIL",
            f"regime unavailable ({why}) -- annotation degrades honestly to "
            "insufficient_data; informational, not a deploy blocker",
        )
    qvix_block = annotation.get("qvix") or {}
    iv = annotation.get("iv") or {}
    return (
        "PASS",
        f"regime {annotation['regime']}, qvix {qvix_block.get('current')} "
        f"(pct {qvix_block.get('percentile_1y')}), atm_iv_near {iv.get('atm_iv_near')} "
        f"({iv.get('near_expiry')}), term {iv.get('term_structure')}, "
        f"skew {iv.get('skew_25d')}, {iv.get('n_filtered', 0)}/{iv.get('n_contracts', 0)} rows",
    )


def check_trend_depth() -> tuple[str, str]:
    """Trend-depth data layer (iterations 190-192, trend_depth_enabled).

    The CN indicator history and US quarterly statements are the inputs the
    fundamental trend annotation rides on. Pre-deploy SKIP on the
    Settings-attribute gate (the pre-trend image's Settings lacks the flag
    entirely -- an ImportError-style crash would misread as "deploy broke
    it", iteration 134's lesson). Source-dark legs are informational FAILs:
    a dark EM/Sina or Yahoo feed degrades the wire to the pre-trend shape,
    it breaks nothing.
    """
    try:
        from app.config import get_settings

        settings = get_settings()
    except ImportError:
        return "SKIP", "app.config absent (pre-deploy image)"
    if not hasattr(settings, "trend_depth_enabled"):
        return "SKIP", "trend depth layer absent (pre-deploy image)"
    if not settings.trend_depth_enabled:
        return "SKIP", "trend_depth_enabled off by config"

    # CN leg: the same seam the pipeline's AkShare agent calls.
    cn: dict | None = None
    cn_err = ""
    try:
        from app.tools.data.fetcher_cn import _sync_fetch_akshare_financials

        cn = _sync_fetch_akshare_financials("600519", ak)
    except Exception as e:  # noqa: BLE001 -- one-line status per check, never crash
        cn_err = f"{type(e).__name__}"
    history = cn.get("indicators_history") if isinstance(cn, dict) else None
    cn_rows = len(history) if isinstance(history, list) else 0

    # US leg: informational only -- Yahoo-429 is the known host shape, the
    # quarterly statements just ride whatever the ticker session has.
    us_cols = 0
    us_err = ""
    try:
        import yfinance as yf

        frame = yf.Ticker("AAPL").quarterly_income_stmt
        us_cols = 0 if frame is None else len(frame.columns)
    except Exception as e:  # noqa: BLE001
        us_err = f"{type(e).__name__}"
    us_note = f"{us_cols} quarter cols" if us_cols else f"dark ({us_err or 'empty'})"

    if cn_rows >= 2:
        # Live proof the analysis seam emits off this history.
        from app.analysis.fundamental.trends import trend_annotation

        trend = trend_annotation(cn)
        if trend is not None:
            return (
                "PASS",
                f"CN indicators_history {cn_rows} rows, trend basis={trend['basis']} "
                f"as_of={trend.get('as_of', '?')} ({len(trend.get('metrics', {}))} metrics); "
                f"US quarterly {us_note}",
            )
        return (
            "PASS",
            f"CN indicators_history {cn_rows} rows, no same-period anchor -- "
            f"annotation degrades honestly; US quarterly {us_note}",
        )
    return (
        "FAIL",
        f"CN indicators_history dark ({cn_err or 'no history rows'}) -- informational, "
        "not a deploy blocker; the wire degrades to the pre-trend shape",
    )


def check_full_analysis() -> tuple[str, str]:
    """End-to-end analyze/sync pipeline call (--full gated)."""
    started = time.monotonic()
    try:
        resp = requests.post(
            ANALYZE_SYNC_URL,
            # query 是 StockAnalysisRequest 必填字段(min_length=1)——漏发会被
            # pydantic 422 秒拒(2026-09-29 首次生产 --full 冒烟实锤的脚本 bug)。
            json={"query": "smoke data chain: full pipeline analysis", "symbols": ["600000"]},
            timeout=240,
        )
        payload = resp.json()
    except Exception as e:
        return "FAIL", f"{type(e).__name__} after {time.monotonic() - started:.0f}s"
    elapsed = time.monotonic() - started
    if resp.status_code != 200:
        return "FAIL", f"HTTP {resp.status_code} after {elapsed:.0f}s"
    if "decisions" not in payload:
        return "FAIL", f"HTTP 200 but no decisions key after {elapsed:.0f}s"
    # Informational suffix: the option-implied annotation rides the CN
    # pipeline run (risk agent attaches it from state.option_snapshot). Key
    # presence -- even an insufficient_data value -- means the wiring fired;
    # honest absence when sources are dark or the toggle is off.
    annotation = (payload.get("risk_assessment") or {}).get("option_implied")
    if annotation is not None:
        regime = annotation.get("regime") if isinstance(annotation, dict) else None
        suffix = f"option_implied present (regime {regime or 'insufficient_data'})"
    else:
        suffix = "option_implied absent (sources dark or OPTION_SIGNALS_ENABLED off)"
    return "PASS", f"HTTP 200 with decisions after {elapsed:.0f}s; {suffix}"


def check_provider_health_endpoint() -> tuple[str, str]:
    """GET /api/monitoring/data-sources -- provider outcome counters live.

    Runs after the --full analysis so the counters have had a run to record;
    even a degraded run records its failed attempts, so an empty providers
    dict after a completed analysis means the wiring never fired."""
    try:
        resp = requests.get("http://localhost:8000/api/monitoring/data-sources", timeout=10)
    except Exception as e:
        return "FAIL", f"{type(e).__name__}"
    if resp.status_code != 200:
        return "FAIL", f"HTTP {resp.status_code}"
    body = resp.json()
    if set(body) != {"providers", "generated_at"}:
        return "FAIL", f"unexpected shape: {sorted(body)}"
    providers = body["providers"]
    n = len(providers)
    if n == 0:
        return "FAIL", "no provider outcomes recorded after a completed analysis"
    sample = next(iter(providers.values()))
    expected = {
        "total_calls",
        "ok",
        "fail",
        "fallback",
        "last_ok_at",
        "last_error",
        "last_error_at",
    }
    if set(sample) != expected:
        return "FAIL", f"per-provider shape drift: {sorted(sample)}"
    return "PASS", f"{n} providers recorded"


def main() -> int:
    checks = [
        ("tencent daily K (600000)", check_tencent_daily_k),
        ("tencent batch spot table", check_tencent_spot_table),
        ("tencent dual-market benchmarks", check_tencent_benchmarks),
        ("sector ETF benchmark chain (XLF)", check_sector_etf_benchmark),
        ("EM financial indicator (600000)", check_em_financial_indicator),
        ("EM full-market spot table", check_em_spot_table),
        ("EM sector-benchmark chain", check_em_sector_chain),
        ("SSE option snapshot", check_sse_option_snapshot),
        ("option-implied annotation chain", check_option_implied_annotation),
        ("trend-depth data layer", check_trend_depth),
    ]
    if "--full" in sys.argv:
        checks.append(("full analysis chain (--full)", check_full_analysis))
        checks.append(("provider health endpoint (post-analysis)", check_provider_health_endpoint))
    else:
        print("[INFO] --full absent -- end-to-end analysis chain not probed")
        print("       enable with: docker exec -i stock_agent_api python - --full \\")
        print("           < scripts/smoke_data_chain.py")

    counts = {"PASS": 0, "FAIL": 0, "SKIP": 0}
    for name, check in checks:
        try:
            status, detail = check()
        except Exception as e:
            status, detail = "FAIL", f"unexpected {type(e).__name__}: {e}"
        counts[status] += 1
        print(f"[{status}] {name} -- {detail}")

    print(f"\n{counts['PASS']} passed, {counts['FAIL']} failed, {counts['SKIP']} skipped")
    return 0 if counts["FAIL"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
