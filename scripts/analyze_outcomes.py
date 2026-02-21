"""Analyze Gamma API outcome patterns - find missed binary markets."""
import requests
import json
from collections import Counter

all_events = []
for offset in range(0, 600, 100):
    try:
        r = requests.get(
            f"https://gamma-api.polymarket.com/events?closed=false&limit=100&offset={offset}",
            timeout=10,
        )
        data = r.json()
        if not data:
            break
        all_events.append(data)
    except Exception:
        break

events = [e for page in all_events for e in page]
print(f"Total events fetched: {len(events)}")

outcome_counter = Counter()
binary_non_yesno = []
total_markets = 0

for event in events:
    for market in event.get("markets", []):
        if market.get("closed"):
            continue
        total_markets += 1
        outcomes_raw = market.get("outcomes", "")
        try:
            parsed = json.loads(outcomes_raw)
        except Exception:
            parsed = []

        if len(parsed) == 2:
            outcome_counter[str(parsed)] += 1
            if parsed != ["Yes", "No"]:
                prices = market.get("outcomePrices", "[]")
                try:
                    p = json.loads(prices)
                    max_p = max(float(p[0]), float(p[1]))
                except Exception:
                    max_p = 0
                vol = round(float(market.get("volume", 0)))
                end = market.get("endDate", "")[:10]
                q = market.get("question", "")[:70]
                binary_non_yesno.append((max_p, vol, end, parsed, q))

print(f"Total open markets: {total_markets}")
print()
print("Binary outcome patterns (2 outcomes):")
for k, v in outcome_counter.most_common(10):
    print(f"  {k}: {v} markets")

print()
print(f"Binary but NOT Yes/No ({len(binary_non_yesno)} markets):")
for mp, vol, end, oc, q in sorted(binary_non_yesno, key=lambda x: -x[0])[:20]:
    print(f"  {mp:.0%} | ${vol:,} | {end} | {oc} | {q}")
