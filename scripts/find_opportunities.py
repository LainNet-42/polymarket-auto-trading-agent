#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Find high-certainty binary markets ending soon
"""
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import requests
import json
from datetime import datetime, timedelta, timezone

def find_opportunities(max_hours=48, min_probability=0.90):
    now = datetime.now(timezone.utc)
    print(f"Current UTC: {now}")
    print(f"Looking for: Binary YES/NO, ending <{max_hours}h, probability >{min_probability*100}%")
    print()

    # Fetch all active events
    all_events = []
    for offset in range(0, 600, 100):
        r = requests.get(
            f'https://gamma-api.polymarket.com/events?closed=false&limit=100&offset={offset}',
            timeout=10
        )
        data = r.json()
        if not data:
            break
        all_events.extend(data)

    print(f"Total active events: {len(all_events)}")
    print()

    # Filter candidates
    candidates = []
    for event in all_events:
        markets = event.get('markets', [])
        for market in markets:
            # Check if binary YES/NO
            outcomes = market.get('outcomes', '')
            if outcomes != '["Yes", "No"]':
                continue

            # Skip closed markets
            if market.get('closed'):
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

            # Check prices for high certainty
            prices_str = market.get('outcomePrices', '[]')
            try:
                prices = json.loads(prices_str)
                yes_price = float(prices[0])
                no_price = float(prices[1])
            except:
                continue

            # High certainty = one side > min_probability but < 99.5% (need profit room)
            max_prob = max(yes_price, no_price)
            if max_prob < min_probability or max_prob >= 0.995:
                continue  # Skip <95% (too risky) and >=99.5% (no profit)

            candidates.append({
                'slug': market.get('slug', ''),
                'title': market.get('question', '')[:60],
                'end_date': end_date,
                'hours_until': hours_until,
                'yes_price': yes_price,
                'no_price': no_price,
                'high_side': 'YES' if yes_price > no_price else 'NO',
                'probability': max_prob,
                'volume': float(market.get('volume', 0))
            })

    # Sort by hours until end
    candidates.sort(key=lambda x: x['hours_until'])

    print(f"=== FOUND {len(candidates)} OPPORTUNITIES ===")
    print()
    print(f"{'Hours':>6} | {'Side':>3} {'Prob':>6} | {'Volume':>10} | Slug")
    print("-" * 80)

    for c in candidates[:30]:
        vol_str = f"${c['volume']/1000:.0f}k" if c['volume'] >= 1000 else f"${c['volume']:.0f}"
        print(f"{c['hours_until']:6.1f}h | {c['high_side']:>3} {c['probability']*100:5.1f}% | {vol_str:>10} | {c['slug'][:40]}")

    return candidates


if __name__ == "__main__":
    # Find markets ending in 48h with >90% certainty
    opportunities = find_opportunities(max_hours=48, min_probability=0.90)

    print()
    print("=== TOP 5 DETAILED ===")
    for c in opportunities[:5]:
        print()
        print(f"Slug: {c['slug']}")
        print(f"Title: {c['title']}")
        print(f"Ends in: {c['hours_until']:.1f} hours ({c['end_date']})")
        print(f"Prediction: {c['high_side']} @ {c['probability']*100:.1f}%")
        print(f"Volume: ${c['volume']:,.0f}")
