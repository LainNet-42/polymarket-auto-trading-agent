"""
Price Anomaly Detector for Polymarket
Detects unusual price movements that may indicate insider trading or market manipulation

Score Formula:
    Score = |Price Change %| x Liquidity Weight x Time Weight

    Liquidity Weight = min(1, log10(volume + 1) / 5)
    Time Weight = 1 + 4 / (1 + exp((hours - 12) / 6))  # Sigmoid, inflection at 12h
"""

import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from .models import PricePoint


@dataclass
class Anomaly:
    """Detected price anomaly"""
    timestamp: datetime
    outcome: str
    price_before: float
    price_after: float
    change_pct: float
    window_hours: int
    severity: str  # "low", "medium", "high"
    score: float = 0.0  # Anomaly score (higher = more suspicious)
    volume: float = 0.0  # Outcome volume for context

    def __str__(self):
        direction = "+" if self.change_pct > 0 else ""
        return (
            f"[{self.severity.upper()}] {self.timestamp.strftime('%Y-%m-%d %H:%M')} "
            f"{self.outcome}: ${self.price_before:.3f} -> ${self.price_after:.3f} "
            f"({direction}{self.change_pct:.1f}%) score={self.score:.1f}"
        )


class AnomalyDetector:
    """Detect price anomalies in market data"""

    # Score thresholds for severity classification
    SCORE_THRESHOLDS = {
        "high": 50,
        "medium": 20,
        "low": 10,
    }

    def __init__(self, window_hours: int = 24):
        """
        Args:
            window_hours: Time window for detecting changes (default 24h)
        """
        self.window_hours = window_hours

    @staticmethod
    def calculate_liquidity_weight(volume: float) -> float:
        """
        Calculate liquidity weight - penalize low-volume markets.

        Formula: min(1, log10(volume + 1) / 5)
        - volume < $100:     weight ~ 0.4
        - volume = $10,000:  weight ~ 0.8
        - volume = $100,000: weight = 1.0
        """
        if volume <= 0:
            return 0.2  # Minimum weight for unknown volume
        return min(1.0, math.log10(volume + 1) / 5)

    @staticmethod
    def calculate_time_weight(hours_until_close: float) -> float:
        """
        Calculate time weight - events closer to settlement are more suspicious.

        Formula: 1 + 4 / (1 + exp((hours - 12) / 6))
        - Sigmoid with inflection point at 12 hours
        - hours = 1:   weight = 4.8
        - hours = 12:  weight = 3.0
        - hours = 48:  weight = 1.1
        """
        if hours_until_close <= 0:
            return 5.0  # Maximum weight for expired/settling
        return 1 + 4 / (1 + math.exp((hours_until_close - 12) / 6))

    def calculate_score(
        self,
        price_change_pct: float,
        volume: float = 100000,
        hours_until_close: float = 168,
    ) -> float:
        """
        Calculate anomaly score.

        Score = |Price Change %| x Liquidity Weight x Time Weight

        Args:
            price_change_pct: Price change as percentage (e.g., 20.0 for 20%)
            volume: Outcome trading volume in USD
            hours_until_close: Hours until market settlement

        Returns:
            Anomaly score (higher = more suspicious)
        """
        liquidity_weight = self.calculate_liquidity_weight(volume)
        time_weight = self.calculate_time_weight(hours_until_close)
        return abs(price_change_pct) * liquidity_weight * time_weight

    def classify_severity(self, score: float) -> Optional[str]:
        """Classify severity based on score."""
        if score >= self.SCORE_THRESHOLDS["high"]:
            return "high"
        elif score >= self.SCORE_THRESHOLDS["medium"]:
            return "medium"
        elif score >= self.SCORE_THRESHOLDS["low"]:
            return "low"
        return None

    def detect_from_file(self, filepath: str) -> list[Anomaly]:
        """Load price history from JSON file and detect anomalies"""
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        all_anomalies = []
        for outcome_data in data:
            outcome_name = outcome_data.get("outcome_name", "Unknown")
            prices = outcome_data.get("prices", [])

            # Convert to PricePoint objects
            points = []
            for p in prices:
                try:
                    ts = datetime.fromisoformat(p["timestamp"])
                    points.append(PricePoint(timestamp=ts, price=p["price"]))
                except (KeyError, ValueError):
                    continue

            # Detect anomalies
            anomalies = self.detect(points, outcome_name)
            all_anomalies.extend(anomalies)

        # Sort by timestamp
        all_anomalies.sort(key=lambda a: a.timestamp)
        return all_anomalies

    def detect(
        self,
        prices: list[PricePoint],
        outcome: str = "",
        volume: float = 100000,
        hours_until_close: float = 168,
    ) -> list[Anomaly]:
        """
        Detect anomalies in a price series using score-based classification.

        Args:
            prices: List of PricePoint objects (must be sorted by time)
            outcome: Name of the outcome for labeling
            volume: Trading volume for this outcome (for liquidity weighting)
            hours_until_close: Hours until market settlement (for time weighting)

        Returns:
            List of detected anomalies, sorted by score descending
        """
        if len(prices) < 2:
            return []

        anomalies = []
        window_delta = timedelta(hours=self.window_hours)

        for i, current in enumerate(prices):
            # Find the price point closest to window_hours ago
            target_time = current.timestamp - window_delta
            prev_point = None

            for j in range(i - 1, -1, -1):
                if prices[j].timestamp <= target_time:
                    prev_point = prices[j]
                    break
                prev_point = prices[j]

            if prev_point is None or prev_point.price == 0:
                continue

            # Calculate change percentage
            change_pct = ((current.price - prev_point.price) / prev_point.price) * 100

            # Calculate score using new formula
            score = self.calculate_score(change_pct, volume, hours_until_close)

            # Classify severity based on score
            severity = self.classify_severity(score)

            if severity:
                # Check if we already have a similar anomaly nearby
                duplicate = False
                for existing in anomalies[-5:]:  # Check last 5
                    if (existing.outcome == outcome and
                        abs((existing.timestamp - current.timestamp).total_seconds()) < 3600):
                        # Skip if same outcome within 1 hour
                        duplicate = True
                        break

                if not duplicate:
                    anomalies.append(Anomaly(
                        timestamp=current.timestamp,
                        outcome=outcome,
                        price_before=prev_point.price,
                        price_after=current.price,
                        change_pct=change_pct,
                        window_hours=self.window_hours,
                        severity=severity,
                        score=score,
                        volume=volume,
                    ))

        # Sort by score descending (most suspicious first)
        anomalies.sort(key=lambda a: a.score, reverse=True)
        return anomalies

    def print_report(self, anomalies: list[Anomaly], min_severity: str = "low"):
        """Print anomaly report"""
        severity_order = {"low": 0, "medium": 1, "high": 2}
        min_level = severity_order.get(min_severity, 0)

        filtered = [a for a in anomalies if severity_order[a.severity] >= min_level]

        print(f"\n{'=' * 70}")
        print(f"ANOMALY REPORT ({len(filtered)} events, min severity: {min_severity})")
        print(f"{'=' * 70}\n")

        # Group by date
        by_date = {}
        for a in filtered:
            date_str = a.timestamp.strftime("%Y-%m-%d")
            if date_str not in by_date:
                by_date[date_str] = []
            by_date[date_str].append(a)

        for date_str in sorted(by_date.keys()):
            print(f"## {date_str}")
            for a in by_date[date_str]:
                print(f"  {a}")
            print()


def analyze_price_history(filepath: str, window_hours: int = 24, min_severity: str = "medium"):
    """Convenience function to analyze a price history file"""
    detector = AnomalyDetector(window_hours=window_hours)
    anomalies = detector.detect_from_file(filepath)
    detector.print_report(anomalies, min_severity=min_severity)
    return anomalies


if __name__ == "__main__":
    import sys

    filepath = sys.argv[1] if len(sys.argv) > 1 else "data/price_history_2025.json"
    analyze_price_history(filepath, window_hours=24, min_severity="medium")
