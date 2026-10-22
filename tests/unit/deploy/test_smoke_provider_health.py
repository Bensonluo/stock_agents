"""check_provider_health_endpoint -- offline pins for the seam-recording gate.

The post-analysis health check (iteration 206's wiring, verified by the
2026-10-22 deploy) asserted endpoint shape and non-empty providers -- but a
silently dead news/events seam would leave the dict non-empty via the other
providers and still read PASS. Iteration 212 pins the seams the --full
analysis (symbols=[600000], a CN symbol) must have recorded: yfinance-news
and em-news-cn fire per-run regardless of outcome (a failed fetch still
counts as wired); akshare-cn-events only when EVENTS_ENABLED is on;
em-us-quarterly is US-only and out of scope for a CN run.

All pins are offline: requests.get is stubbed at module scope, Settings via
the app.config.get_settings patch point the sibling smoke tests established.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

MODULE_PATH = Path(__file__).resolve().parents[3] / "scripts" / "smoke_data_chain.py"


@pytest.fixture(scope="module")
def smoke():
    spec = importlib.util.spec_from_file_location("smoke_data_chain_under_test", MODULE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _entry() -> dict:
    return {
        "total_calls": 1,
        "ok": 1,
        "fail": 0,
        "fallback": 0,
        "last_ok_at": "2026-10-22T23:00:00",
        "last_error": None,
        "last_error_at": None,
    }


def _body(providers: dict) -> dict:
    return {"providers": providers, "generated_at": "2026-10-22T23:00:00"}


def _settings(**overrides):
    flags: dict = {"events_enabled": True}
    flags.update(overrides)
    return SimpleNamespace(**flags)


def _patch(monkeypatch, smoke, *, providers, settings=None):
    import app.config as config_mod

    if settings is None:
        settings = _settings()
    monkeypatch.setattr(config_mod, "get_settings", lambda: settings)

    def _get(_url, timeout=0):
        return SimpleNamespace(status_code=200, json=lambda: _body(providers))

    monkeypatch.setattr(smoke, "requests", SimpleNamespace(get=_get))


def test_fail_on_zero_providers_after_analysis(smoke, monkeypatch):
    _patch(monkeypatch, smoke, providers={})
    status, detail = smoke.check_provider_health_endpoint()
    assert status == "FAIL"
    assert "no provider outcomes" in detail


def test_fail_on_endpoint_shape_drift(smoke, monkeypatch):
    import app.config as config_mod

    monkeypatch.setattr(config_mod, "get_settings", lambda: _settings())
    monkeypatch.setattr(
        smoke,
        "requests",
        SimpleNamespace(
            get=lambda _u, timeout=0: SimpleNamespace(
                status_code=200, json=lambda: {"providers": {}}
            )
        ),
    )
    status, detail = smoke.check_provider_health_endpoint()
    assert status == "FAIL"
    assert "unexpected shape" in detail


def test_pass_includes_pinned_seam_names_in_detail(smoke, monkeypatch):
    providers = {
        "yfinance-news": _entry(),
        "em-news-cn": _entry(),
        "akshare-cn-events": _entry(),
        "em-cn-daily": _entry(),  # unrelated provider -- pinning is non-exclusive
    }
    _patch(monkeypatch, smoke, providers=providers)
    status, detail = smoke.check_provider_health_endpoint()
    assert status == "PASS"
    assert "4 providers" in detail
    assert "yfinance-news" in detail and "em-news-cn" in detail


def test_fail_when_yfinance_news_seam_silent(smoke, monkeypatch):
    providers = {"em-news-cn": _entry(), "akshare-cn-events": _entry()}
    _patch(monkeypatch, smoke, providers=providers)
    status, detail = smoke.check_provider_health_endpoint()
    assert status == "FAIL"
    assert "yfinance-news" in detail


def test_fail_when_em_news_cn_seam_silent(smoke, monkeypatch):
    providers = {"yfinance-news": _entry(), "akshare-cn-events": _entry()}
    _patch(monkeypatch, smoke, providers=providers)
    status, detail = smoke.check_provider_health_endpoint()
    assert status == "FAIL"
    assert "em-news-cn" in detail


def test_fail_when_events_seam_silent_while_enabled(smoke, monkeypatch):
    providers = {"yfinance-news": _entry(), "em-news-cn": _entry()}
    _patch(monkeypatch, smoke, providers=providers, settings=_settings(events_enabled=True))
    status, detail = smoke.check_provider_health_endpoint()
    assert status == "FAIL"
    assert "akshare-cn-events" in detail


def test_events_seam_not_expected_when_disabled(smoke, monkeypatch):
    providers = {"yfinance-news": _entry(), "em-news-cn": _entry()}
    _patch(monkeypatch, smoke, providers=providers, settings=_settings(events_enabled=False))
    status, detail = smoke.check_provider_health_endpoint()
    assert status == "PASS"


def test_pre_deploy_settings_without_events_flag_treated_as_off(smoke, monkeypatch):
    providers = {"yfinance-news": _entry(), "em-news-cn": _entry()}
    _patch(monkeypatch, smoke, providers=providers, settings=SimpleNamespace())
    status, _detail = smoke.check_provider_health_endpoint()
    assert status == "PASS"
