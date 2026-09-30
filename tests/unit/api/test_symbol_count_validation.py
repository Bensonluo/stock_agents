"""Count cap on the analyze endpoints' symbols list.

The public-demo defense grid bounded every axis except request size:
the rate limiter (iteration 169) bounds requests per client, the
concurrency cap (iteration 170) bounds in-flight workflows, the node
timeout (iteration 173) bounds agent duration — but nothing bounded
symbols per request. Each symbol multiplies per-symbol network fetches,
analysis and LLM work, so one 500-symbol POST holds one of the two
capacity slots indefinitely. These pins lock the missing axis on both
public analyze models (pipeline StockAnalysisRequest + ReAct twin).
"""

from string import ascii_uppercase

import pytest
from pydantic import ValidationError

from app.api.routes.agent import AnalyzeRequest
from app.api.routes.analysis import StockAnalysisRequest
from app.config import Settings, get_settings


def _symbols(n: int) -> list[str]:
    """n valid US tickers: A..Z then AA, BB.. (matches ^[A-Z]{1,5}$)."""
    return [ascii_uppercase[i % 26] * (1 + i // 26) for i in range(n)]


class TestPipelineSymbolsCap:
    def test_over_cap_rejected(self) -> None:
        with pytest.raises(ValidationError) as exc:
            StockAnalysisRequest(query="analyze", symbols=_symbols(11))
        assert "max 10" in str(exc.value)

    def test_at_cap_accepted(self) -> None:
        request = StockAnalysisRequest(query="analyze", symbols=_symbols(10))
        assert len(request.symbols) == 10


class TestReActSymbolsCap:
    def test_over_cap_rejected(self) -> None:
        with pytest.raises(ValidationError) as exc:
            AnalyzeRequest(query="analyze", symbols=_symbols(11))
        assert "max 10" in str(exc.value)

    def test_at_cap_accepted(self) -> None:
        request = AnalyzeRequest(query="analyze", symbols=_symbols(10))
        assert len(request.symbols) == 10


class TestCapIsConfigurable:
    def test_settings_read_at_call_time(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The cap comes from get_settings() inside the validator (not
        Field-definition time), so an instance-level override moves it —
        the iteration-169 monkeypatch contract."""
        monkeypatch.setattr(get_settings(), "max_symbols_per_request", 3)

        with pytest.raises(ValidationError):
            StockAnalysisRequest(query="analyze", symbols=_symbols(4))
        with pytest.raises(ValidationError):
            AnalyzeRequest(query="analyze", symbols=_symbols(4))
        assert AnalyzeRequest(query="analyze", symbols=_symbols(3)).symbols is not None

    def test_zero_disables_the_cap(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """0 = unlimited escape hatch, mirroring the concurrency-cap and
        timeout knob convention (iterations 170/173)."""
        monkeypatch.setattr(get_settings(), "max_symbols_per_request", 0)

        assert len(StockAnalysisRequest(query="q", symbols=_symbols(50)).symbols) == 50
        assert len(AnalyzeRequest(query="q", symbols=_symbols(50)).symbols) == 50


class TestWiring:
    def test_default_cap_is_ten(self) -> None:
        assert Settings.model_fields["max_symbols_per_request"].default == 10

    def test_env_example_documents_the_knob(self) -> None:
        with open(".env.example") as f:
            assert "MAX_SYMBOLS_PER_REQUEST" in f.read()
