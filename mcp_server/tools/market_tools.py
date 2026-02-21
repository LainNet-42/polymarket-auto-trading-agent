"""
Market query tools for Polymarket MCP Server
"""
import json
import requests
from datetime import datetime, timezone

from polymarket.client import PolymarketClient
from ..formatters import format_market_list, format_market_details, format_price_history


def search_markets(
    client: PolymarketClient,
    query: str,
    min_probability: float = 0,
    min_volume: float = 0,
    open_only: bool = True,
    limit: int = 20,
) -> str:
    """
    Search markets and return formatted list

    Args:
        client: Polymarket API client
        query: Search keyword
        min_probability: Min probability threshold (0-1)
        min_volume: Min volume in USD
        open_only: Only return open markets
        limit: Max results
    """
    # Fetch more to allow for filtering
    markets = client.search_events(
        query=query,
        limit=limit * 3,
        closed=False if open_only else None,
    )

    # Filter
    filtered = []
    for market in markets:
        if open_only and market.closed:
            continue
        if market.volume < min_volume:
            continue

        # Check if any outcome meets probability threshold
        if min_probability > 0:
            has_high_prob = any(
                o.price >= min_probability
                for o in market.outcomes
            )
            if not has_high_prob:
                continue

        filtered.append(market)
        if len(filtered) >= limit:
            break

    return format_market_list(filtered, query)


def get_market_details(
    client: PolymarketClient,
    event_slug: str,
    include_price_history: bool = False,
) -> str:
    """
    Get detailed market information

    Args:
        client: Polymarket API client
        event_slug: Event slug (from find_opportunities)
        include_price_history: Whether to fetch price history
    """
    market = client.get_event_by_slug(event_slug)
    if not market:
        return f"Market not found: {event_slug}"

    # Fetch CLOB order book prices for each outcome
    clob_prices = {}
    for outcome in market.outcomes:
        if outcome.token_id:
            book = _get_order_book(outcome.token_id)
            if book:
                asks = book.get('asks', [])
                bids = book.get('bids', [])
                # CLOB API: asks sorted HIGH→LOW, bids sorted LOW→HIGH
                # Best ask = lowest ask = last; Best bid = highest bid = last
                clob_prices[outcome.name] = {
                    'best_ask': float(asks[-1]['price']) if asks else None,
                    'best_bid': float(bids[-1]['price']) if bids else None,
                }

    price_histories = {}
    if include_price_history:
        # Get top 3 outcomes by price
        sorted_outcomes = sorted(market.outcomes, key=lambda o: o.price, reverse=True)
        for outcome in sorted_outcomes[:3]:
            if outcome.token_id:
                points = client.get_price_history(
                    outcome.token_id,
                    interval="1w",
                    fidelity=60,  # hourly
                )
                if points:
                    price_histories[outcome.name] = points

    return format_market_details(market, price_histories, clob_prices)


def get_price_history(
    client: PolymarketClient,
    event_slug: str,
    outcome: str,
    interval: str = "1d",
) -> str:
    """
    Get price history for specific outcome

    Args:
        client: Polymarket API client
        event_slug: Event slug (from find_opportunities)
        outcome: Outcome name
        interval: Time interval (1h, 1d, 1w, max)
    """
    market = client.get_event_by_slug(event_slug)
    if not market:
        return f"Market not found: {event_slug}"

    # Find outcome
    target_outcome = None
    for o in market.outcomes:
        if o.name.lower() == outcome.lower():
            target_outcome = o
            break

    if not target_outcome:
        available = [o.name for o in market.outcomes]
        return f"Outcome '{outcome}' not found. Available: {', '.join(available)}"

    if not target_outcome.token_id:
        return f"No token ID for outcome: {outcome}"

    # Map interval to fidelity
    fidelity_map = {
        "1h": 1,      # 1 min granularity
        "1d": 60,     # hourly
        "1w": 360,    # 6 hourly
        "max": 720,   # 12 hourly
    }
    fidelity = fidelity_map.get(interval, 60)

    history = client.get_full_price_history(market, target_outcome.name, interval)
    if not history:
        return f"No price history for {outcome}"

    return format_price_history(history)


def _get_best_ask(token_id: str) -> float | None:
    """Get best (lowest) ask price from CLOB order book.
    CLOB API returns asks sorted HIGH to LOW, so best ask = last element."""
    book = _get_order_book(token_id)
    if not book:
        return None
    asks = book.get('asks', [])
    return float(asks[-1]['price']) if asks else None


def _get_order_book(token_id: str) -> dict | None:
    """Get order book from CLOB API."""
    try:
        r = requests.get(
            f'https://clob.polymarket.com/book?token_id={token_id}',
            timeout=5
        )
        return r.json()
    except Exception:
        return None


def find_opportunities(
    max_hours: int = 48,
    min_probability: float = 0.90,
    max_probability: float = 0.95,
    limit: int = 20,
    neg_risk: bool = None,
    order: str = "endDate",
    binary_only: bool = True,
) -> str:
    """
    Find high-certainty binary markets ending soon.
    Uses CLOB order book for real ask prices (not Gamma probability estimates).

    Args:
        max_hours: Max hours until market ends (default 48)
        min_probability: Min probability threshold (default 0.90)
        max_probability: Max probability threshold (default 0.95, ceiling 0.995)
        limit: Max results to return
        neg_risk: Filter by neg_risk type (True=multi-outcome, False=simple, None=all)
        order: Gamma API sort field (endDate, volume, volume24hr, liquidity)
        binary_only: True=only Yes/No markets, False=any 2-outcome market

    Returns:
        JSON with opportunities list
    """
    MAX_PROB_CEILING = 0.995
    MAX_PHASE2_CANDIDATES = 80

    now = datetime.now(timezone.utc)
    effective_max = min(max_probability, MAX_PROB_CEILING)

    # Fetch active events sorted by order param, only future end dates
    all_events = []
    now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    for offset in range(0, 600, 100):
        try:
            r = requests.get(
                f'https://gamma-api.polymarket.com/events?closed=false&limit=100&offset={offset}'
                f'&end_date_min={now_iso}&order={order}&ascending=true',
                timeout=10
            )
            data = r.json()
            if not data:
                break
            all_events.extend(data)
        except:
            break

    # Phase 1: Coarse filter using Gamma API probability
    coarse_candidates = []
    for event in all_events:
        # Hardcoded: skip sports (game-result driven, no edge)
        tags = [t.get('label', '').lower() for t in event.get('tags', [])]
        if 'sports' in tags:
            continue

        markets = event.get('markets', [])
        for market in markets:
            # Check outcome structure
            outcomes = market.get('outcomes', '')
            try:
                parsed_outcomes = json.loads(outcomes)
            except Exception:
                continue
            if binary_only:
                if parsed_outcomes != ["Yes", "No"]:
                    continue
            else:
                if len(parsed_outcomes) != 2:
                    continue

            # Skip closed markets
            if market.get('closed'):
                continue

            market_neg_risk = market.get('negRisk', False)
            # Honor explicit filter param
            if neg_risk is not None and market_neg_risk != neg_risk:
                continue

            # Check end date
            end_date_str = market.get('endDate')
            if not end_date_str:
                continue
            try:
                end_date = datetime.fromisoformat(end_date_str.replace('Z', '+00:00'))
            except:
                continue

            # Only markets ending within max_hours
            hours_until = (end_date - now).total_seconds() / 3600
            if hours_until < 0 or hours_until > max_hours:
                continue

            # Check prices (Gamma probability - used for coarse filtering only)
            prices_str = market.get('outcomePrices', '[]')
            try:
                prices = json.loads(prices_str)
                yes_price = float(prices[0])
                no_price = float(prices[1])
            except:
                continue

            # Filter by probability range (effective_max capped at 0.995)
            max_prob = max(yes_price, no_price)
            if max_prob < min_probability or max_prob >= effective_max:
                continue

            # Get token IDs
            token_ids = market.get('clobTokenIds', '')
            try:
                tokens = json.loads(token_ids) if token_ids else []
            except:
                tokens = []

            if len(tokens) < 2:
                continue

            # Determine recommended side
            if yes_price > no_price:
                rec_side = 'YES'
                rec_token = tokens[0]
            else:
                rec_side = 'NO'
                rec_token = tokens[1]

            coarse_candidates.append({
                'slug': market.get('slug', ''),
                'event_slug': event.get('slug', ''),
                'title': market.get('question', '')[:60],
                'description': market.get('description') or event.get('description') or '',
                'end_date': end_date.isoformat(),
                'hours_until': round(hours_until, 1),
                'yes_price': yes_price,
                'no_price': no_price,
                'recommended_side': rec_side,
                'rec_token': rec_token,
                'probability': max_prob,
                'volume': float(market.get('volume', 0)),
                'neg_risk': market_neg_risk,
                'token_id_yes': tokens[0],
                'token_id_no': tokens[1],
            })

    # Cap Phase 2 candidates to avoid CLOB API timeout
    if len(coarse_candidates) > MAX_PHASE2_CANDIDATES:
        coarse_candidates.sort(key=lambda x: x['volume'], reverse=True)
        coarse_candidates = coarse_candidates[:MAX_PHASE2_CANDIDATES]

    # Phase 2: Get real ask prices from CLOB order book
    candidates = []
    for c in coarse_candidates:
        real_ask = _get_best_ask(c['rec_token'])
        if real_ask is None:
            continue

        real_profit_pct = round((1 - real_ask) * 100, 1)

        # Hard filters: must be tradeable
        # 1. real_ask >= 0.98 means < 2% profit (slippage eats margin)
        if real_ask >= 0.98:
            continue
        # 2. Volume < $1,000 means thin order book, bad fills
        if c['volume'] < 1000:
            continue

        # Drop rec_token (internal only)
        del c['rec_token']

        c['real_ask_price'] = real_ask
        c['potential_profit_pct'] = real_profit_pct
        candidates.append(c)

    # Sort by hours until end
    candidates.sort(key=lambda x: x['hours_until'])

    return json.dumps({
        'count': len(candidates[:limit]),
        'opportunities': candidates[:limit]
    }, indent=2)
