"""
Output formatters for MCP tools
Produces AI-friendly text output
"""

from polymarket.models import Market, PriceHistory, PricePoint


def format_volume(vol: float) -> str:
    """Format volume as human-readable string"""
    if vol >= 1_000_000:
        return f"${vol/1_000_000:.1f}M"
    elif vol >= 1_000:
        return f"${vol/1_000:.0f}K"
    else:
        return f"${vol:.0f}"


def format_market_list(markets: list[Market], query: str) -> str:
    """Format market list for AI consumption"""
    if not markets:
        return f"No markets found matching '{query}'"

    lines = [f"Found {len(markets)} markets matching '{query}':\n"]

    for i, market in enumerate(markets, 1):
        status = "CLOSED" if market.closed else "OPEN"
        lines.append(f"{i}. [{status}] {market.title}")

        # Top outcomes (sorted by price/probability)
        sorted_outcomes = sorted(market.outcomes, key=lambda o: o.price, reverse=True)
        for outcome in sorted_outcomes[:4]:
            prob = f"{outcome.price*100:.1f}%"
            vol = format_volume(outcome.volume)
            lines.append(f"   - {outcome.name}: {prob} ({vol} volume)")

        # Market stats
        lines.append(f"   Liquidity: {format_volume(market.liquidity)} | Volume: {format_volume(market.volume)}")
        lines.append(f"   Ends: {market.end_date.strftime('%Y-%m-%d')}")
        lines.append(f"   Slug: {market.slug}")
        if market.description:
            lines.append(f"   Rules: {market.description}")
        lines.append("")

    return "\n".join(lines)


def format_market_details(market: Market, price_histories: dict = None, clob_prices: dict = None) -> str:
    """Format detailed market info"""
    status = "CLOSED" if market.closed else "OPEN"

    lines = [
        f"Market: {market.title}",
        f"Status: {status}",
        f"End Date: {market.end_date.strftime('%Y-%m-%d %H:%M UTC')}",
        f"Total Volume: {format_volume(market.volume)}",
        f"Liquidity: {format_volume(market.liquidity)}",
    ]

    if market.description:
        lines.append("")
        lines.append(f"Resolution Rules: {market.description}")

    lines.extend(["", "Outcomes (sorted by probability):"])

    sorted_outcomes = sorted(market.outcomes, key=lambda o: o.price, reverse=True)
    for i, outcome in enumerate(sorted_outcomes, 1):
        prob = f"{outcome.price*100:.1f}%"
        lines.append(f"{i}. {outcome.name} - {prob} (probability: ${outcome.price:.3f})")

        # CLOB real prices
        if clob_prices and outcome.name in clob_prices:
            cp = clob_prices[outcome.name]
            ask_str = f"${cp['best_ask']}" if cp['best_ask'] is not None else "N/A"
            bid_str = f"${cp['best_bid']}" if cp['best_bid'] is not None else "N/A"
            lines.append(f"   CLOB: ask={ask_str}, bid={bid_str}")

        # Add price changes if history available
        if price_histories and outcome.name in price_histories:
            points = price_histories[outcome.name]
            if len(points) >= 24:
                try:
                    change_24h = (points[-1].price - points[-24].price) / points[-24].price * 100
                    lines.append(f"   24h change: {change_24h:+.1f}%")
                except (ZeroDivisionError, IndexError):
                    pass

        lines.append(f"   Volume: {format_volume(outcome.volume)}")
        if outcome.token_id:
            lines.append(f"   Token ID: {outcome.token_id[:20]}...")
        lines.append("")

    return "\n".join(lines)


def format_price_history(history: PriceHistory) -> str:
    """Format price history data"""
    if not history or not history.data_points:
        return "No price history available"

    points = history.data_points
    lines = [
        f"Price History: {history.outcome_name}",
        f"Market: {history.market_slug}",
        f"Data Points: {len(points)}",
        "",
    ]

    # Summary stats
    prices = [p.price for p in points]
    lines.extend([
        f"Current: ${prices[-1]:.3f}",
        f"High: ${max(prices):.3f}",
        f"Low: ${min(prices):.3f}",
        "",
        "Recent prices:",
    ])

    # Last 10 data points
    for p in points[-10:]:
        lines.append(f"  {p.timestamp.strftime('%Y-%m-%d %H:%M')}: ${p.price:.3f}")

    return "\n".join(lines)


def format_anomaly_report(market: Market, anomalies: list, window_hours: int) -> str:
    """Format anomaly detection report with scores"""
    lines = [
        "=== ANOMALY REPORT ===",
        "",
        f"Market: {market.title}",
        f"End Date: {market.end_date.strftime('%Y-%m-%d %H:%M UTC')}",
        f"Detection Window: {window_hours} hours",
        "",
    ]

    if not anomalies:
        lines.append("No anomalies detected (score >= 10 required).")
    else:
        lines.append(f"Top {len(anomalies)} anomalies (sorted by score):")
        lines.append("")
        for i, anomaly in enumerate(anomalies, 1):
            score_str = f"score={anomaly.score:.0f}" if hasattr(anomaly, 'score') else ""
            vol_str = f"vol={format_volume(anomaly.volume)}" if hasattr(anomaly, 'volume') and anomaly.volume else ""
            lines.append(f"{i}. [{anomaly.severity.upper()}] {anomaly.timestamp.strftime('%Y-%m-%d %H:%M')} - {anomaly.outcome}")
            lines.append(f"   ${anomaly.price_before:.3f} -> ${anomaly.price_after:.3f} ({anomaly.change_pct:+.1f}%) {score_str} {vol_str}")
            lines.append("")

    return "\n".join(lines)


def format_opportunity_analysis(
    market: Market,
    winner_stats: dict,
    anomalies: list,
    strategy: str,
) -> str:
    """Format opportunity analysis for AI decision making"""
    lines = [
        "=== OPPORTUNITY ANALYSIS ===",
        "",
        f"Market: {market.title}",
        f"Strategy: {strategy.upper()}",
        "",
    ]

    # Historical context
    if winner_stats:
        lines.append("## Historical Context")
        total_closed = sum(s.wins for s in winner_stats.values())
        for company, stats in sorted(winner_stats.items(), key=lambda x: -x[1].wins):
            if stats.wins > 0:
                pct = stats.wins / total_closed * 100 if total_closed > 0 else 0
                lines.append(f"- {company}: {stats.wins}/{total_closed} wins ({pct:.1f}%)")
        lines.append("")

    # Current market
    lines.append("## Current Market")
    sorted_outcomes = sorted(market.outcomes, key=lambda o: o.price, reverse=True)
    if sorted_outcomes:
        leader = sorted_outcomes[0]
        potential_return = (1 - leader.price) / leader.price * 100 if leader.price > 0 else 0
        lines.extend([
            f"Leader: {leader.name} @ ${leader.price:.2f} ({leader.price*100:.1f}%)",
            f"Potential Return: {potential_return:.1f}% if {leader.name} wins",
            f"Break-even probability: {leader.price*100:.1f}%",
            "",
        ])

    # Risk factors
    lines.append("## Risk Factors")
    if anomalies:
        lines.append(f"- [ALERT] {len(anomalies)} price anomalies detected recently")
        for a in anomalies[:3]:
            lines.append(f"  - {a.outcome}: {a.change_pct:+.1f}% on {a.timestamp.strftime('%Y-%m-%d')}")
    else:
        lines.append("- [OK] No unusual price movements detected")

    lines.append(f"- Liquidity: {format_volume(market.liquidity)}")

    # Recommendation
    lines.extend([
        "",
        "## Recommendation",
    ])
    if market.liquidity < 10000:
        lines.append("CAUTION: Low liquidity - position size should be minimal")
    elif anomalies:
        lines.append("CAUTION: Recent anomalies detected - monitor closely")
    else:
        lines.append("CONSIDER: Market appears stable")

    return "\n".join(lines)
