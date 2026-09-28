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
- Pure sync on purpose: the Tencent seams are sync functions, akshare is
  sync, and the HTTP probes use requests -- no asyncio anywhere.
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
- Exit codes: 0 = no FAIL, 1 = at least one FAIL. SKIPs never count.
"""

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


def check_full_analysis() -> tuple[str, str]:
    """End-to-end analyze/sync pipeline call (--full gated)."""
    started = time.monotonic()
    try:
        resp = requests.post(
            ANALYZE_SYNC_URL,
            json={"symbols": ["600000"], "mode": "pipeline"},
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
    return "PASS", f"HTTP 200 with decisions after {elapsed:.0f}s"


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
    expected = {"total_calls", "ok", "fail", "fallback", "last_ok_at", "last_error", "last_error_at"}
    if set(sample) != expected:
        return "FAIL", f"per-provider shape drift: {sorted(sample)}"
    return "PASS", f"{n} providers recorded"


def main() -> int:
    checks = [
        ("tencent daily K (600000)", check_tencent_daily_k),
        ("tencent batch spot table", check_tencent_spot_table),
        ("tencent dual-market benchmarks", check_tencent_benchmarks),
        ("EM financial indicator (600000)", check_em_financial_indicator),
        ("EM full-market spot table", check_em_spot_table),
        ("EM sector-benchmark chain", check_em_sector_chain),
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
