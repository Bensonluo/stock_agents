"""check_us_quarterly_em — deploy-time liveness probe for the EM F10 fallback (offline pins).

Iteration 201 shipped the East Money 单季报 fallback for the US quarterly
trend leg; its one open caveat is EM F10 liveness on the production host
(ssh probing banned; push2his's domain-level block is a different endpoint
cluster, EM push2/datacenter-web audited alive 2026-09-28). This smoke
check rides the deploy harness so the next authorized deploy answers the
question from inside the container — same role check_trend_depth played for
iterations 190-192.

All pins are offline: settings-flag SKIP gates (pre-deploy image / config
off), PASS off a stubbed fetcher, informational FAIL when the source is
dark, and main() registration.
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


def _settings(**overrides):
    flags = {"trend_depth_enabled": True, "us_quarterly_em_enabled": True}
    flags.update(overrides)
    return SimpleNamespace(**flags)


def _patch(monkeypatch, *, settings=None, fetch=None, fetch_raises=None):
    import app.config as config_mod
    import app.tools.data.fetcher_us_quarterly as fetcher_mod

    if settings is None:
        settings = _settings()
    monkeypatch.setattr(config_mod, "get_settings", lambda: settings)

    def _fetch(_symbol):
        if fetch_raises is not None:
            raise fetch_raises
        return fetch

    monkeypatch.setattr(fetcher_mod, "fetch_us_quarterly_income_em", _fetch)


def _stub_block():
    return {
        "income_statement": {
            "dates": ["2026-03-28", "2026-06-27"],
            "data": {"Total Revenue": [111.184e9, 109.417e9], "Net Income": [29.578e9, 29.789e9]},
            "visible_from": ["2026-05-27", "2026-08-26"],
        }
    }


def test_skip_pre_deploy_image_lacks_the_flag(smoke, monkeypatch):
    _patch(monkeypatch, settings=SimpleNamespace(trend_depth_enabled=True))
    status, detail = smoke.check_us_quarterly_em()
    assert status == "SKIP"
    assert "pre-deploy" in detail


def test_skip_when_trend_depth_disabled(smoke, monkeypatch):
    _patch(monkeypatch, settings=_settings(trend_depth_enabled=False))
    status, detail = smoke.check_us_quarterly_em()
    assert status == "SKIP"
    assert "trend depth" in detail


def test_skip_when_fallback_flag_off(smoke, monkeypatch):
    _patch(monkeypatch, settings=_settings(us_quarterly_em_enabled=False))
    status, detail = smoke.check_us_quarterly_em()
    assert status == "SKIP"
    assert "config" in detail


def test_pass_when_em_answers_and_trend_fires(smoke, monkeypatch):
    _patch(monkeypatch, fetch=_stub_block())
    status, detail = smoke.check_us_quarterly_em()
    assert status == "PASS"
    assert "EM F10" in detail
    assert "quarter_over_quarter" in detail
    assert "2 quarters" in detail  # quarters surfaced in the status line


def test_fail_informational_when_source_dark(smoke, monkeypatch):
    _patch(monkeypatch, fetch=None)
    status, detail = smoke.check_us_quarterly_em()
    assert status == "FAIL"
    assert "informational" in detail


def test_fail_records_exception_type_when_fetch_raises(smoke, monkeypatch):
    _patch(monkeypatch, fetch_raises=ConnectionError("endpoint dark"))
    status, detail = smoke.check_us_quarterly_em()
    assert status == "FAIL"
    assert "ConnectionError" in detail


def test_check_registered_in_main():
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert "check_us_quarterly_em" in source  # defined AND referenced by main()'s checks list
