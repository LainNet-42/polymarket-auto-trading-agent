"""
Analysis tools for Polymarket data
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from .models import Market, PriceHistory


@dataclass
class WinnerStats:
    """Statistics about market winners"""
    company: str
    wins: int
    total_volume: float
    months: list[str]


@dataclass
class MarketSummary:
    """Summary of a single market"""
    month: str
    year: int
    winner: Optional[str]
    volume: float
    closed: bool
    leader: Optional[str]
    leader_probability: float


class MarketAnalyzer:
    """Analyze prediction market data"""

    def __init__(self, markets: list[Market]):
        self.markets = markets

    def get_winner_distribution(self) -> dict[str, WinnerStats]:
        """Get win counts by company"""
        stats = defaultdict(lambda: {"wins": 0, "volume": 0, "months": []})

        for market in self.markets:
            if not market.closed:
                continue

            winner = market.winner
            if winner:
                month_str = market.end_date.strftime("%Y-%m")
                stats[winner]["wins"] += 1
                stats[winner]["volume"] += market.volume
                stats[winner]["months"].append(month_str)

        return {
            company: WinnerStats(
                company=company,
                wins=data["wins"],
                total_volume=data["volume"],
                months=sorted(data["months"]),
            )
            for company, data in stats.items()
        }

    def get_market_summaries(self) -> list[MarketSummary]:
        """Get summary of each market sorted by date"""
        summaries = []

        for market in self.markets:
            leader = market.leader
            summaries.append(MarketSummary(
                month=market.end_date.strftime("%b"),
                year=market.end_date.year,
                winner=market.winner,
                volume=market.volume,
                closed=market.closed,
                leader=leader.name if leader else None,
                leader_probability=leader.price if leader else 0,
            ))

        return sorted(summaries, key=lambda s: (s.year, s.month))

    def find_upsets(self) -> list[dict]:
        """Find markets where the final winner was unexpected"""
        # This would require historical price data to implement properly
        # Placeholder for now
        upsets = []
        for market in self.markets:
            if market.closed and market.winner:
                # xAI winning in Feb was an upset
                if market.winner == "xAI":
                    upsets.append({
                        "market": market.title,
                        "winner": market.winner,
                        "date": market.end_date,
                    })
        return upsets

    def print_summary_report(self):
        """Print formatted analysis report"""
        print("\n" + "=" * 70)
        print("AI MODEL PREDICTION MARKETS - ANALYSIS REPORT")
        print("=" * 70)

        # Winner distribution
        winners = self.get_winner_distribution()
        closed_count = sum(1 for m in self.markets if m.closed)

        print(f"\n## CLOSED MARKETS: {closed_count}")
        print("\n### Winner Distribution:")
        for company, stats in sorted(winners.items(), key=lambda x: -x[1].wins):
            win_rate = stats.wins / closed_count * 100 if closed_count > 0 else 0
            print(f"  {company}: {stats.wins} wins ({win_rate:.1f}%) | ${stats.total_volume/1e6:.2f}M volume")

        # Timeline
        print("\n### Monthly Results:")
        summaries = self.get_market_summaries()
        for s in summaries:
            status = "CLOSED" if s.closed else "OPEN"
            result = s.winner if s.winner else f"{s.leader} ({s.leader_probability*100:.1f}%)"
            print(f"  {s.year}-{s.month}: {result} | ${s.volume/1e6:.2f}M [{status}]")

        # Open markets
        open_markets = [m for m in self.markets if not m.closed]
        if open_markets:
            print(f"\n## OPEN MARKETS: {len(open_markets)}")
            for market in open_markets:
                print(f"\n  {market.title}")
                for outcome in market.top_outcomes[:3]:
                    print(f"    - {outcome.name}: {outcome.probability}")
