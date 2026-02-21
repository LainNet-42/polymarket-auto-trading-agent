"""
Analysis tools for Polymarket MCP Server
"""

from polymarket.client import PolymarketClient
from polymarket.anomaly_detector import AnomalyDetector
from polymarket.config import AI_MODEL_MARKET_SLUGS
from ..formatters import format_anomaly_report, format_opportunity_analysis


def analyze_opportunity(
    client: PolymarketClient,
    event_slug: str,
    strategy: str = "high_certainty",
) -> str:
    """
    Analyze market for betting opportunities

    Args:
        client: Polymarket API client
        event_slug: Event slug (from find_opportunities)
        strategy: Analysis strategy (high_certainty, value_bet)
    """
    market = client.get_event_by_slug(event_slug)
    if not market:
        return f"Market not found: {event_slug}"

    # Get historical winner stats for related markets
    winner_stats = _get_winner_stats(client, market)

    # Detect recent anomalies
    detector = AnomalyDetector(window_hours=168)  # 7 days
    anomalies = []

    sorted_outcomes = sorted(market.outcomes, key=lambda o: o.price, reverse=True)
    for outcome in sorted_outcomes[:5]:
        if outcome.token_id:
            points = client.get_price_history(
                outcome.token_id,
                interval="1w",
                fidelity=60,
            )
            if points:
                outcome_anomalies = detector.detect(points, outcome.name)
                anomalies.extend(outcome_anomalies)

    # Sort anomalies by timestamp
    anomalies.sort(key=lambda a: a.timestamp, reverse=True)

    return format_opportunity_analysis(
        market=market,
        winner_stats=winner_stats,
        anomalies=anomalies[:5],  # Top 5 recent
        strategy=strategy,
    )


def detect_anomalies(
    client: PolymarketClient,
    event_slug: str,
    window_hours: int = 24,
    min_severity: str = "medium",
    top_n: int = 20,
) -> str:
    """
    Detect price anomalies in market using score-based classification.

    Score = |Price Change %| x Liquidity Weight x Time Weight
    - Liquidity Weight penalizes low-volume markets
    - Time Weight increases for markets closer to settlement

    Args:
        client: Polymarket API client
        event_slug: Event slug (from find_opportunities)
        window_hours: Detection window in hours
        min_severity: Minimum severity to report (low, medium, high)
        top_n: Maximum number of anomalies to return
    """
    from datetime import datetime, timezone

    market = client.get_event_by_slug(event_slug)
    if not market:
        return f"Market not found: {event_slug}"

    # Calculate hours until market closes
    now = datetime.now(timezone.utc)
    hours_until_close = (market.end_date - now).total_seconds() / 3600
    if hours_until_close < 0:
        hours_until_close = 0

    detector = AnomalyDetector(window_hours=window_hours)
    all_anomalies = []

    for outcome in market.outcomes:
        if not outcome.token_id:
            continue

        # Use 1w instead of max to limit data
        points = client.get_price_history(
            outcome.token_id,
            interval="1w",
            fidelity=60,  # hourly
        )
        if points:
            # Pass volume and hours_until_close for score calculation
            anomalies = detector.detect(
                points,
                outcome.name,
                volume=outcome.volume,
                hours_until_close=hours_until_close,
            )
            all_anomalies.extend(anomalies)

    # Filter by severity
    severity_order = {"low": 0, "medium": 1, "high": 2}
    min_level = severity_order.get(min_severity, 1)
    filtered = [a for a in all_anomalies if severity_order.get(a.severity, 0) >= min_level]

    # Sort by score descending (most suspicious first)
    filtered.sort(key=lambda a: a.score, reverse=True)

    # Limit to top N
    filtered = filtered[:top_n]

    return format_anomaly_report(market, filtered, window_hours)


def scan_anomalies(
    client: PolymarketClient,
    max_hours: int = 48,
    window_hours: int = 24,
    min_severity: str = "high",
    top_n: int = 10,
) -> str:
    """
    Scan all active markets for anomalies. No slug required.

    Args:
        client: Polymarket API client
        max_hours: Only scan markets ending within this time
        window_hours: Detection window for each market
        min_severity: Minimum severity to include
        top_n: Maximum total anomalies to return

    Returns:
        Combined anomaly report across all scanned markets
    """
    import requests
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)

    # Fetch active events
    try:
        r = requests.get(
            'https://gamma-api.polymarket.com/events?closed=false&limit=100',
            timeout=15
        )
        events = r.json()
    except Exception as e:
        return f"Error fetching events: {e}"

    # Filter events ending soon
    candidates = []
    for event in events:
        # Skip sports markets (price changes driven by game results, not information asymmetry)
        tags = [t.get('label', '').lower() for t in event.get('tags', [])]
        if 'sports' in tags:
            continue

        end_date_str = event.get('endDate', '')
        if not end_date_str:
            continue
        try:
            end_date = datetime.fromisoformat(end_date_str.replace('Z', '+00:00'))
            hours_until = (end_date - now).total_seconds() / 3600
            if 0 < hours_until <= max_hours:
                candidates.append({
                    'slug': event.get('slug'),
                    'title': event.get('title'),
                    'hours_until': hours_until,
                })
        except:
            continue

    if not candidates:
        return f"No markets found ending within {max_hours} hours."

    # Scan each candidate for anomalies
    detector = AnomalyDetector(window_hours=window_hours)
    all_anomalies = []
    scanned_markets = []

    severity_order = {"low": 0, "medium": 1, "high": 2}
    min_level = severity_order.get(min_severity, 2)

    for cand in candidates[:20]:  # Limit to 20 markets to avoid timeout
        slug = cand['slug']
        if not slug:
            continue

        market = client.get_event_by_slug(slug)
        if not market:
            continue

        # Skip closed/settled markets
        if market.closed:
            continue

        scanned_markets.append(cand['title'][:40])
        hours_until_close = cand['hours_until']

        for outcome in market.outcomes:
            if not outcome.token_id:
                continue

            points = client.get_price_history(
                outcome.token_id,
                interval="1w",
                fidelity=60,
            )
            if not points:
                continue

            anomalies = detector.detect(
                points,
                outcome.name,
                volume=outcome.volume,
                hours_until_close=hours_until_close,
            )

            # Add market context to each anomaly
            for a in anomalies:
                if severity_order.get(a.severity, 0) >= min_level:
                    a.market_slug = slug
                    a.market_title = cand['title'][:30]
                    all_anomalies.append(a)

    # Sort by score and take top N
    all_anomalies.sort(key=lambda a: a.score, reverse=True)
    top_anomalies = all_anomalies[:top_n]

    # Format output
    lines = [
        "=== SCAN ANOMALIES ===",
        "",
        f"Scanned {len(scanned_markets)} markets ending within {max_hours}h",
        f"Found {len(all_anomalies)} anomalies, showing top {len(top_anomalies)}:",
        "",
    ]

    for i, a in enumerate(top_anomalies, 1):
        market_info = getattr(a, 'market_title', 'Unknown')
        lines.append(f"{i}. [{a.severity.upper()}] score={a.score:.0f}")
        lines.append(f"   Market: {market_info}")
        lines.append(f"   {a.outcome}: ${a.price_before:.3f} -> ${a.price_after:.3f} ({a.change_pct:+.1f}%)")
        lines.append(f"   Time: {a.timestamp.strftime('%Y-%m-%d %H:%M')}")
        lines.append("")

    return "\n".join(lines)


def _get_winner_stats(client: PolymarketClient, market) -> dict:
    """Get historical winner stats for related markets"""
    # For AI model markets, get historical data
    if "ai model" in market.title.lower() or "ai" in market.slug.lower():
        return _get_ai_model_winner_stats(client)

    return {}


def _get_ai_model_winner_stats(client: PolymarketClient) -> dict:
    """Get winner stats for AI model prediction markets"""
    from dataclasses import dataclass

    @dataclass
    class WinnerStats:
        wins: int = 0
        total_volume: float = 0
        months: list = None

        def __post_init__(self):
            if self.months is None:
                self.months = []

    stats = {}

    for slug in AI_MODEL_MARKET_SLUGS:
        try:
            market = client.get_event_by_slug(slug)
            if not market or not market.closed:
                continue

            # Find winner (resolved outcome)
            for outcome in market.outcomes:
                if outcome.resolved and outcome.resolution == "1":
                    company = outcome.name
                    if company not in stats:
                        stats[company] = WinnerStats()
                    stats[company].wins += 1
                    stats[company].total_volume += outcome.volume
                    stats[company].months.append(slug)
                    break
        except Exception:
            continue

    return stats
