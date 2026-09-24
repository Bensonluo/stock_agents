"""Deflated Sharpe Ratio (Bailey & López de Prado, JPM 2014).

Walk-forward parameter search tries N configurations and keeps the best:
the winner's apparent skill is inflated by max-of-N selection even when
every trial is pure noise. The DSR converts the winner's Sharpe into the
probability that its TRUE Sharpe is positive AFTER paying for the search
— the missing counterweight to ``configs_tested`` telemetry.

Three corrections in one statistic:

- **Selection**: the expected maximum Sharpe of N noise trials,
  SR0 = sqrt(V[SR_trials]) * ((1-γ)·Z(1-1/N) + γ·Z(1-1/(N·e))), grows
  with the number of configurations tried; the winner must beat THAT
  bar, not zero.
- **Non-normality**: the standard error of the Sharpe itself widens
  with negative skew and fat tails (Mertens/Lo),
  σ(SR) = sqrt((1 - γ3·SR + (γ4-1)/4·SR²) / (T-1)).
- **Sample size**: σ(SR) shrinks with the number of return
  observations, so the same Sharpe over more bars is more believable.

Pure functions, stdlib ``statistics.NormalDist`` for Φ/Φ⁻¹ — no scipy.
Guards return ``None`` (honest refusal), never a fabricated 0.5.
"""

from __future__ import annotations

import math
from statistics import NormalDist
from typing import Any

EULER_GAMMA = 0.577_215_664_901_532_9
BARS_PER_YEAR_SQRT = math.sqrt(252)
MIN_OOS_BARS = 20  # below this, skew/kurtosis of the OOS stream are noise

_NORMAL = NormalDist()


def deflated_sharpe_ratio(
    oos_returns: list[float],
    trial_sharpes_annualized: list[float],
    n_configurations: int,
) -> dict[str, Any] | None:
    """DSR of a search winner from its out-of-sample return stream.

    Args:
        oos_returns: The strategy's concatenated out-of-sample daily
            returns (test segments of the walk-forward).
        trial_sharpes_annualized: The train-segment Sharpes of every
            configuration tried, pooled across windows (the selection
            pool; annualized, same convention as ``metrics._sharpe``).
        n_configurations: Distinct configurations in the grid — the N
            of the max-of-N selection (per window the search picks the
            best of N, so N is the grid size, not the pooled count).

    Returns:
        ``{"status": "ok", "dsr", "sharpe_annualized", "sr0_annualized",
        "n_trials", "trial_sharpe_std_annualized", "oos_bars", "skew",
        "kurtosis"}`` or ``None`` when the inputs cannot support the
        statistic (single trial, no trial dispersion, degenerate or too
        short a return stream).
    """
    returns = [float(r) for r in oos_returns if isinstance(r, int | float) and math.isfinite(r)]
    if len(returns) < MIN_OOS_BARS or n_configurations < 2:
        return None
    trials = [
        float(s) / BARS_PER_YEAR_SQRT
        for s in trial_sharpes_annualized
        if isinstance(s, int | float) and math.isfinite(float(s))
    ]
    if len(trials) < 2:
        return None

    mean = sum(returns) / len(returns)
    var = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    std = math.sqrt(var)
    if std <= 0:
        return None
    sr_hat = mean / std  # per-bar Sharpe of the delivered stream

    trial_mean = sum(trials) / len(trials)
    trial_var = sum((s - trial_mean) ** 2 for s in trials) / (len(trials) - 1)
    if trial_var <= 0:
        # Every configuration scored identically — no selection happened
        # (or the search space is degenerate); nothing to deflate.
        return None

    # Expected max of N zero-mean trials with this dispersion.
    z1 = _inv_cdf_safe(1 - 1 / n_configurations)
    z2 = _inv_cdf_safe(1 - 1 / (n_configurations * math.e))
    if z1 is None or z2 is None:
        return None
    sr0 = math.sqrt(trial_var) * ((1 - EULER_GAMMA) * z1 + EULER_GAMMA * z2)

    # Non-normality of the delivered stream widens the SR standard error.
    skew = sum((r - mean) ** 3 for r in returns) / len(returns) / std**3
    kurt = sum((r - mean) ** 4 for r in returns) / len(returns) / std**4
    se_sq = (1 - skew * sr_hat + (kurt - 1) / 4 * sr_hat**2) / (len(returns) - 1)
    if se_sq <= 0:
        return None
    dsr = _NORMAL.cdf((sr_hat - sr0) / math.sqrt(se_sq))
    if not (0.0 <= dsr <= 1.0):  # cdf is [0,1]; guard the float edge anyway
        return None

    return {
        "status": "ok",
        "dsr": round(dsr, 4),
        "sharpe_annualized": round(sr_hat * BARS_PER_YEAR_SQRT, 6),
        "sr0_annualized": round(sr0 * BARS_PER_YEAR_SQRT, 6),
        "n_trials": n_configurations,
        "trial_sharpe_std_annualized": round(math.sqrt(trial_var) * BARS_PER_YEAR_SQRT, 6),
        "oos_bars": len(returns),
        "skew": round(skew, 4),
        "kurtosis": round(kurt, 4),
    }


def _inv_cdf_safe(p: float) -> float | None:
    """Normal inverse CDF guarded against p at the closed endpoints."""
    if not (0.0 < p < 1.0):
        return None
    return _NORMAL.inv_cdf(p)
