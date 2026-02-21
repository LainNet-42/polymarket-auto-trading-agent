"""
Polymarket API Client - handles all API interactions
"""

import time
import requests
from datetime import datetime, timezone
from typing import Optional

from .config import GAMMA_API_BASE, CLOB_API_BASE, REQUEST_DELAY, REQUEST_TIMEOUT
from .models import Market, Outcome, PriceHistory, PricePoint


class PolymarketClient:
    """Unified client for Polymarket APIs (Gamma + CLOB)"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
            "User-Agent": "PolymarketAnalyzer/1.0"
        })
        self._last_request_time = 0

    def _rate_limit(self):
        """Enforce rate limiting between requests"""
        elapsed = time.time() - self._last_request_time
        if elapsed < REQUEST_DELAY:
            time.sleep(REQUEST_DELAY - elapsed)
        self._last_request_time = time.time()

    def _get(self, url: str, params: dict = None) -> Optional[dict | list]:
        """Make GET request with error handling"""
        self._rate_limit()
        try:
            resp = self.session.get(url, params=params, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            print(f"API Error: {e}")
            return None

    # ==================== Gamma API (Market Data) ====================

    def get_event_by_slug(self, slug: str) -> Optional[Market]:
        """Fetch event/market group by slug"""
        data = self._get(f"{GAMMA_API_BASE}/events", params={"slug": slug})
        if not data or len(data) == 0:
            return None
        return self._parse_event(data[0])

    def search_events(self, query: str, limit: int = 50, closed: bool = None) -> list[Market]:
        """Search for events matching query via /public-search endpoint"""
        params = {"q": query, "limit_per_type": limit}
        if closed is False:
            params["events_status"] = "active"
        data = self._get(f"{GAMMA_API_BASE}/public-search", params=params)
        if not data:
            return []
        events = data.get("events", [])
        return [self._parse_event(e) for e in events]

    def get_markets_by_tag(self, tag: str, limit: int = 100) -> list[Market]:
        """Get markets by tag (e.g., 'AI', 'Tech')"""
        data = self._get(f"{GAMMA_API_BASE}/events", params={"tag": tag, "limit": limit})
        if not data:
            return []
        return [self._parse_event(e) for e in data]

    def _parse_event(self, event: dict) -> Market:
        """Parse raw event JSON into Market model"""
        outcomes = []
        for market in event.get("markets", []):
            outcome = self._parse_market_outcome(market)
            if outcome:
                outcomes.append(outcome)

        end_date_str = event.get("endDate", "")
        try:
            end_date = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            end_date = datetime.now(timezone.utc)

        return Market(
            title=event.get("title", "Unknown"),
            slug=event.get("slug", ""),
            closed=event.get("closed", False),
            end_date=end_date,
            liquidity=float(event.get("liquidity", 0) or 0),
            volume=float(event.get("volume", 0) or 0),
            description=event.get("description", ""),
            outcomes=outcomes,
        )

    def _parse_market_outcome(self, market: dict) -> Optional[Outcome]:
        """Parse single market into Outcome"""
        name = market.get("groupItemTitle") or market.get("question", "Unknown")
        if not name or name.startswith("Company "):
            # Skip placeholder outcomes
            if market.get("volume", "0") == "0":
                return None

        token_id = market.get("clobTokenIds", "")
        if isinstance(token_id, str) and token_id.startswith("["):
            # Parse JSON array format
            try:
                import json
                token_id = json.loads(token_id)[0]
            except (json.JSONDecodeError, IndexError):
                token_id = ""

        price = self._parse_price(market.get("outcomePrices"))
        volume = float(market.get("volume", 0) or 0)

        return Outcome(
            name=name,
            token_id=token_id,
            price=price,
            volume=volume,
            resolved=market.get("resolved", False),
            resolution=market.get("resolution"),
        )

    def _parse_price(self, price_str) -> float:
        """Parse price from various formats"""
        if price_str is None:
            return 0.0
        if isinstance(price_str, (int, float)):
            return float(price_str)
        try:
            cleaned = str(price_str).replace("[", "").replace("]", "").replace('"', "")
            return float(cleaned.split(",")[0])
        except (ValueError, AttributeError):
            return 0.0

    # ==================== CLOB API (Price History) ====================

    def get_price_history(
        self,
        token_id: str,
        interval: str = "max",  # 1m, 1h, 6h, 1d, 1w, max
        fidelity: int = 60,     # minutes (60 = hourly, best for historical data)
        start_ts: int = None,
        end_ts: int = None,
    ) -> list[PricePoint]:
        """
        Fetch historical price data for a token

        Args:
            token_id: The CLOB token ID
            interval: Time interval (1m, 1h, 6h, 1d, 1w, max)
            fidelity: Granularity in minutes (1440 = daily)
            start_ts: Start timestamp (unix seconds)
            end_ts: End timestamp (unix seconds)
        """
        params = {
            "market": token_id,  # API uses "market" not "tokenId"
            "interval": interval,
            "fidelity": fidelity,
        }
        if start_ts:
            params["startTs"] = start_ts
        if end_ts:
            params["endTs"] = end_ts

        data = self._get(f"{CLOB_API_BASE}/prices-history", params=params)
        if not data or "history" not in data:
            return []

        points = []
        for item in data["history"]:
            try:
                ts = datetime.fromtimestamp(item["t"], tz=timezone.utc)
                price = float(item["p"])
                points.append(PricePoint(timestamp=ts, price=price))
            except (KeyError, ValueError):
                continue

        return points

    def get_full_price_history(
        self,
        market: Market,
        outcome_name: str,
        interval: str = "1d",
    ) -> Optional[PriceHistory]:
        """Get full price history for a specific outcome in a market"""
        # Find the outcome
        outcome = None
        for o in market.outcomes:
            if o.name == outcome_name:
                outcome = o
                break

        if not outcome or not outcome.token_id:
            return None

        points = self.get_price_history(outcome.token_id, interval=interval)
        if not points:
            return None

        return PriceHistory(
            token_id=outcome.token_id,
            outcome_name=outcome_name,
            market_slug=market.slug,
            data_points=points,
        )
