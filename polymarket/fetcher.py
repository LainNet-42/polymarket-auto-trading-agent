"""
Data fetching orchestration
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Optional

from .client import PolymarketClient
from .config import AI_MODEL_MARKET_SLUGS
from .models import Market, PriceHistory


class DataFetcher:
    """Orchestrates data fetching from Polymarket"""

    def __init__(self, output_dir: str = "."):
        self.client = PolymarketClient()
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def fetch_ai_model_markets(self, verbose: bool = True) -> list[Market]:
        """Fetch all AI model prediction markets"""
        markets = []

        if verbose:
            print("Fetching AI model prediction markets...")

        for slug in AI_MODEL_MARKET_SLUGS:
            if verbose:
                print(f"  -> {slug}")

            market = self.client.get_event_by_slug(slug)
            if market:
                markets.append(market)
                if verbose:
                    status = "CLOSED" if market.closed else "OPEN"
                    winner = market.winner or market.leader.name if market.leader else "?"
                    print(f"     {status} | {winner}")
            else:
                if verbose:
                    print(f"     NOT FOUND")

        if verbose:
            print(f"\nTotal markets found: {len(markets)}")

        return markets

    def fetch_price_history(
        self,
        market: Market,
        outcome_names: list[str] = None,
        interval: str = "1d",
        verbose: bool = True,
    ) -> list[PriceHistory]:
        """
        Fetch price history for outcomes in a market

        Args:
            market: The market to fetch history for
            outcome_names: List of outcome names to fetch (None = top 5)
            interval: Time interval (1m, 5m, 1h, 6h, 1d)
        """
        histories = []

        if outcome_names is None:
            outcome_names = [o.name for o in market.top_outcomes]

        if verbose:
            print(f"\nFetching price history for: {market.title}")

        for name in outcome_names:
            if verbose:
                print(f"  -> {name}")

            history = self.client.get_full_price_history(market, name, interval)
            if history and history.data_points:
                histories.append(history)
                if verbose:
                    print(f"     {len(history.data_points)} data points")
            else:
                if verbose:
                    print(f"     No data")

        return histories

    def save_markets(self, markets: list[Market], filename: str = "markets.json"):
        """Save markets to JSON file"""
        filepath = self.output_dir / filename

        data = []
        for market in markets:
            data.append({
                "title": market.title,
                "slug": market.slug,
                "closed": market.closed,
                "end_date": market.end_date.isoformat(),
                "liquidity": market.liquidity,
                "volume": market.volume,
                "winner": market.winner,
                "outcomes": [
                    {
                        "name": o.name,
                        "token_id": o.token_id,
                        "price": o.price,
                        "probability": o.probability,
                        "volume": o.volume,
                    }
                    for o in market.outcomes
                    if o.volume > 0 or o.price > 0.001  # Filter out empty placeholders
                ],
            })

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        print(f"Saved {len(markets)} markets to {filepath}")

    def save_price_histories(
        self,
        histories: list[PriceHistory],
        filename: str = "price_history.json",
    ):
        """Save price histories to JSON file"""
        filepath = self.output_dir / filename

        data = [h.to_dict() for h in histories]

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        print(f"Saved {len(histories)} price histories to {filepath}")
