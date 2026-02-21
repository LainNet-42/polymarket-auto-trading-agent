"""
Data models for Polymarket entities
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Outcome:
    """Single outcome/option in a market"""
    name: str
    token_id: str
    price: float
    volume: float
    resolved: bool = False
    resolution: Optional[str] = None

    @property
    def probability(self) -> str:
        return f"{self.price * 100:.2f}%"

    @property
    def is_winner(self) -> bool:
        return self.resolution == "Yes" or (self.resolved and self.price > 0.99)


@dataclass
class Market:
    """A prediction market event"""
    title: str
    slug: str
    closed: bool
    end_date: datetime
    liquidity: float
    volume: float
    description: str = ""
    outcomes: list[Outcome] = field(default_factory=list)

    @property
    def winner(self) -> Optional[str]:
        for outcome in self.outcomes:
            if outcome.is_winner:
                return outcome.name
        # If closed and one outcome has price ~1.0, that's the winner
        if self.closed:
            for outcome in self.outcomes:
                if outcome.price > 0.99:
                    return outcome.name
        return None

    @property
    def leader(self) -> Optional[Outcome]:
        if not self.outcomes:
            return None
        return max(self.outcomes, key=lambda o: o.price)

    @property
    def top_outcomes(self) -> list[Outcome]:
        return sorted(self.outcomes, key=lambda o: o.price, reverse=True)[:5]


@dataclass
class PricePoint:
    """Single price point in time series"""
    timestamp: datetime
    price: float


@dataclass
class PriceHistory:
    """Historical price data for an outcome"""
    token_id: str
    outcome_name: str
    market_slug: str
    data_points: list[PricePoint] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "token_id": self.token_id,
            "outcome_name": self.outcome_name,
            "market_slug": self.market_slug,
            "prices": [
                {"timestamp": p.timestamp.isoformat(), "price": p.price}
                for p in self.data_points
            ]
        }
