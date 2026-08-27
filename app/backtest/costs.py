"""Transaction cost model (V2 plan §7.1).

Every backtest must account for commissions, minimum fees, taxes and
slippage — a strategy only "works" if it survives its own trading costs.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CostModel:
    """Per-side transaction costs as fractions of traded value.

    Attributes:
        commission_rate: Broker commission per side (e.g. 0.0003 for CN A-share).
        min_commission: Minimum commission per trade in currency units.
        stamp_tax: Tax applied on the SELL side only (e.g. 0.001 for CN A-share);
            0.0 for markets without one.
        transfer_fee: Small per-side fee (e.g. 0.00001 CN transfer fee).
        slippage_rate: Half-spread paid on BOTH sides, as a fraction of price.
    """

    commission_rate: float = 0.001
    min_commission: float = 0.0
    stamp_tax: float = 0.0
    transfer_fee: float = 0.0
    slippage_rate: float = 0.0

    def __post_init__(self) -> None:
        for name in ("commission_rate", "stamp_tax", "transfer_fee", "slippage_rate"):
            value = getattr(self, name)
            if value < 0:
                raise ValueError(f"{name} must be non-negative, got {value}")
        if self.min_commission < 0:
            raise ValueError("min_commission must be non-negative")

    def buy_price(self, market_price: float) -> float:
        """Effective price paid when buying (slippage pushes it up)."""
        return market_price * (1 + self.slippage_rate)

    def sell_price(self, market_price: float) -> float:
        """Effective price received when selling (slippage pushes it down)."""
        return market_price * (1 - self.slippage_rate)

    def buy_cost(self, traded_value: float) -> float:
        """Total cost incurred when buying ``traded_value`` worth of stock."""
        return self._side_cost(traded_value)

    def sell_cost(self, traded_value: float) -> float:
        """Total cost incurred when selling ``traded_value`` worth of stock."""
        return self._side_cost(traded_value) + traded_value * self.stamp_tax

    def _side_cost(self, traded_value: float) -> float:
        if traded_value <= 0:
            return 0.0
        commission = max(traded_value * self.commission_rate, self.min_commission)
        return commission + traded_value * self.transfer_fee


# Presets per market (starting points, not advice; configurable per run).
CN_STOCK = CostModel(commission_rate=0.0003, min_commission=5.0, stamp_tax=0.0005, transfer_fee=0.00001, slippage_rate=0.001)
US_STOCK = CostModel(commission_rate=0.001, min_commission=0.0, slippage_rate=0.0005)
ZERO = CostModel(commission_rate=0.0, slippage_rate=0.0)
