"""IC-driven dimension weighting: the feedback edge of the IC loop.

adaptive_dimension_weights blends the static 45/30/15 prior toward measured
IC targets under strict gates (every directional dimension qualified, all
non-positive ICs refused), James-Stein-style shrinkage governed by the
weakest dimension's run count, and bounded distortion via a true
box-simplex projection (floor/cap hold in the final weights).
derive_recommendation consumes the blend with per-key static fallbacks.
"""

from __future__ import annotations

import pytest

from app.agents.decision_agent import DecisionMakingAgent
from app.analysis.ic import (
    ADAPT_SHRINK_K,
    MIN_ADAPT_RUNS,
    STATIC_DIMENSION_WEIGHTS,
    WEIGHT_CAP,
    WEIGHT_FLOOR,
    adaptive_dimension_weights,
)
from app.services.report_service import derive_recommendation


def _qualified(runs: int = 30, ic_mean: float = 0.10, ic_std: float = 0.20) -> dict:
    return {"runs": runs, "ic_mean": ic_mean, "ic_std": ic_std, "ic_positive_rate": 0.6}


def _evidence(fund: dict | None, tech: dict | None, sent: dict | None) -> dict[str, dict | None]:
    return {"fundamental": fund, "technical": tech, "sentiment": sent}


class TestGating:
    def test_empty_evidence_keeps_static(self) -> None:
        weights, provenance = adaptive_dimension_weights({})
        assert weights == STATIC_DIMENSION_WEIGHTS
        assert provenance["mode"] == "static"
        assert "no summary" in provenance["reason"]

    def test_thin_history_keeps_static_with_named_reason(self) -> None:
        weights, provenance = adaptive_dimension_weights(
            _evidence(_qualified(runs=MIN_ADAPT_RUNS - 1), _qualified(), _qualified())
        )
        assert weights == STATIC_DIMENSION_WEIGHTS
        assert f"{MIN_ADAPT_RUNS - 1} runs < {MIN_ADAPT_RUNS}" in provenance["reason"]
        assert provenance["reason"].startswith("fundamental:")

    def test_missing_dispersion_keeps_static(self) -> None:
        summary = _qualified()
        summary["ic_std"] = None
        weights, provenance = adaptive_dimension_weights(
            _evidence(_qualified(), summary, _qualified())
        )
        assert weights == STATIC_DIMENSION_WEIGHTS
        assert "no dispersion estimate" in provenance["reason"]

    def test_all_nonpositive_ic_refuses_to_reweight(self) -> None:
        weights, provenance = adaptive_dimension_weights(
            _evidence(_qualified(ic_mean=-0.1), _qualified(ic_mean=-0.2), _qualified(ic_mean=0.0))
        )
        assert weights == STATIC_DIMENSION_WEIGHTS
        assert "no dimension shows positive measured IC" in provenance["reason"]

    def test_extra_dimensions_are_ignored(self) -> None:
        evidence = _evidence(_qualified(), _qualified(), _qualified())
        evidence["regime"] = _qualified(runs=99, ic_mean=0.9)
        weights, provenance = adaptive_dimension_weights(evidence)
        assert set(weights) == set(STATIC_DIMENSION_WEIGHTS)
        assert provenance["mode"] == "adaptive"


class TestAdaptiveMath:
    def test_shrinkage_uses_the_weakest_dimension(self) -> None:
        n_min = 15
        weights, provenance = adaptive_dimension_weights(
            _evidence(_qualified(runs=40), _qualified(runs=n_min), _qualified(runs=30))
        )
        assert provenance["mode"] == "adaptive"
        assert provenance["lambda"] == pytest.approx(n_min / (n_min + ADAPT_SHRINK_K), abs=1e-4)
        assert provenance["runs_weakest_dimension"] == n_min

    def test_higher_ic_dimensions_gain_weight(self) -> None:
        weights, _ = adaptive_dimension_weights(
            _evidence(_qualified(ic_mean=0.02), _qualified(ic_mean=0.30), _qualified(ic_mean=0.01))
        )
        assert weights["technical"] > STATIC_DIMENSION_WEIGHTS["technical"]
        assert weights["fundamental"] < STATIC_DIMENSION_WEIGHTS["fundamental"]

    def test_negative_ic_dimension_shrinks_toward_the_floor(self) -> None:
        weights, _ = adaptive_dimension_weights(
            _evidence(_qualified(ic_mean=0.10), _qualified(ic_mean=0.10), _qualified(ic_mean=-0.5))
        )
        # Sentiment's IC target is 0; only the floor keeps it alive.
        assert weights["sentiment"] <= STATIC_DIMENSION_WEIGHTS["sentiment"]

    def test_mass_and_bounds_are_preserved(self) -> None:
        weights, _ = adaptive_dimension_weights(
            _evidence(_qualified(ic_mean=0.9), _qualified(ic_mean=0.01), _qualified(ic_mean=0.0))
        )
        mass = sum(STATIC_DIMENSION_WEIGHTS.values())
        assert sum(weights.values()) == pytest.approx(mass)
        for value in weights.values():
            assert WEIGHT_FLOOR * mass - 1e-6 <= value <= WEIGHT_CAP * mass + 1e-6

    def test_extreme_skew_with_strong_lambda_still_honors_the_cap(self) -> None:
        # 200 runs -> lambda = 200/224 ~= 0.89, near-total trust in an
        # extremely skewed IC profile. The capped dimension must stay at or
        # below cap*mass AFTER the projection restores the directional mass
        # — the failure mode of a naive clip-then-renormalize.
        weights, provenance = adaptive_dimension_weights(
            _evidence(
                _qualified(runs=200, ic_mean=0.99),
                _qualified(runs=200, ic_mean=0.005),
                _qualified(runs=200, ic_mean=0.0),
            )
        )
        mass = sum(STATIC_DIMENSION_WEIGHTS.values())
        assert provenance["mode"] == "adaptive"
        assert weights["fundamental"] <= WEIGHT_CAP * mass + 1e-6
        assert sum(weights.values()) == pytest.approx(mass)

    def test_equal_ics_blend_toward_uniform_shares(self) -> None:
        # Equal ICs mean equal targets: the blend moves from the static
        # 50/33/17 shares toward 1/3 each. Technical starts at 1/3 of the
        # directional mass and therefore stays put.
        weights, provenance = adaptive_dimension_weights(
            _evidence(_qualified(ic_mean=0.10), _qualified(ic_mean=0.10), _qualified(ic_mean=0.10))
        )
        assert provenance["mode"] == "adaptive"
        assert weights["fundamental"] < STATIC_DIMENSION_WEIGHTS["fundamental"]
        assert weights["sentiment"] > STATIC_DIMENSION_WEIGHTS["sentiment"]
        assert weights["technical"] == pytest.approx(STATIC_DIMENSION_WEIGHTS["technical"])

    def test_lambda_zero_would_return_static_exactly(self) -> None:
        # shrink_k -> inf drives lambda -> 0: the blend must converge to static.
        weights, _ = adaptive_dimension_weights(
            _evidence(_qualified(ic_mean=0.9), _qualified(ic_mean=0.1), _qualified(ic_mean=0.0)),
            shrink_k=10**9,
        )
        assert weights == pytest.approx(STATIC_DIMENSION_WEIGHTS, abs=1e-6)


class TestDeriveRecommendationWeights:
    def _inputs(self) -> tuple[dict, dict, dict, dict]:
        return (
            {"overall_score": 40},  # weak fundamentals
            {"sentiment": {"score": 90}},  # strong technicals
            {"score": 50, "article_count": 3},
            {"risk_level": "low"},
        )

    def test_none_weights_are_bit_identical_to_the_classic_blend(self) -> None:
        baseline = derive_recommendation("AAA", *self._inputs())
        explicit = derive_recommendation(
            "AAA", *self._inputs(), dimension_weights=dict(STATIC_DIMENSION_WEIGHTS)
        )
        assert baseline == explicit

    def test_technical_heavy_weights_lift_the_composite(self) -> None:
        tilted = derive_recommendation(
            "AAA",
            *self._inputs(),
            dimension_weights={"fundamental": 0.05, "technical": 0.80, "sentiment": 0.05},
        )
        baseline = derive_recommendation("AAA", *self._inputs())
        assert tilted["composite_score"] > baseline["composite_score"]

    def test_partial_dict_falls_back_per_key_never_zeroes(self) -> None:
        partial = derive_recommendation(
            "AAA", *self._inputs(), dimension_weights={"technical": 0.9}
        )
        assert partial == derive_recommendation(
            "AAA",
            *self._inputs(),
            dimension_weights={"technical": 0.9, "fundamental": 0.45, "sentiment": 0.15},
        )


class TestDecisionAgentWiring:
    @pytest.mark.asyncio
    async def test_process_carries_weights_provenance(self, monkeypatch) -> None:
        import app.services.ic_service as ic_service_module

        weights = {"fundamental": 0.3, "technical": 0.5, "sentiment": 0.1}
        provenance = {"mode": "adaptive", "reason": None, "weights": weights}
        captured: list[dict | None] = []

        async def fake_provider(**kwargs):
            return dict(weights), provenance

        # The decision agent lazy-imports the provider inside process(), so
        # patching the module attribute is what the call-time import sees.
        monkeypatch.setattr(ic_service_module, "get_adaptive_dimension_weights", fake_provider)

        agent = DecisionMakingAgent("test-decision")
        agent.llm = None  # keep the synthesis branch out of the way

        async def stub_decision(symbol, technical, fundamental, sentiment, risk, **kw):
            captured.append(kw.get("dimension_weights"))
            return {
                "symbol": symbol,
                "action": "hold",
                "confidence": 0.5,
                "score": 50.0,
                "component_scores": {},
                "position_size": {},
                "price_targets": {},
                "rationale": "",
                "warnings": [],
            }

        agent._make_decision = stub_decision

        result = await agent.process(
            {
                "symbols": ["AAA"],
                "technical_analysis": {"AAA": {}},
                "fundamental_analysis": {"AAA": {}},
                "sentiment_analysis": {},
                "risk_assessment": {},
            }
        )

        assert result["dimension_weights"] == provenance
        assert captured == [weights]
