"""
Custom tools for the Polymarket agent.

Wraps existing polymarket/ code as SDK-compatible tools.
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from claude_agent_sdk import tool, create_sdk_mcp_server
from polymarket.client import PolymarketClient


def get_client() -> PolymarketClient:
    """Get a cached Polymarket client instance."""
    if not hasattr(get_client, "_client"):
        get_client._client = PolymarketClient()
    return get_client._client


@tool(
    name="search_high_certainty_markets",
    description="Search Polymarket for markets with high probability outcomes (>90%). Returns market names, probabilities, and settlement dates.",
    input_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query (e.g., 'Trump', 'Fed', 'AI model')"
            },
            "min_probability": {
                "type": "number",
                "description": "Minimum probability threshold (0-1), default 0.95",
                "default": 0.95
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of markets to return",
                "default": 10
            }
        },
        "required": ["query"]
    }
)
async def search_high_certainty_markets(args: dict) -> dict:
    """Search for high-certainty markets."""
    client = get_client()
    query = args.get("query", "")
    min_prob = args.get("min_probability", 0.95)
    limit = args.get("limit", 10)

    try:
        # Search markets
        markets = client.search_events(query=query, limit=limit * 3)

        # Filter by probability
        results = []
        for market in markets:
            if not market.outcomes:
                continue

            # Find highest probability outcome
            max_outcome = max(market.outcomes, key=lambda o: o.price or 0)
            if max_outcome.price and max_outcome.price >= min_prob:
                results.append({
                    "name": market.title,
                    "slug": market.slug,
                    "top_outcome": max_outcome.name,
                    "probability": f"{max_outcome.price * 100:.1f}%",
                    "end_date": market.end_date,
                    "volume": f"${market.volume:,.0f}" if market.volume else "N/A",
                    "liquidity": f"${market.liquidity:,.0f}" if market.liquidity else "N/A",
                    "status": "OPEN" if market.active else "CLOSED"
                })

                if len(results) >= limit:
                    break

        if not results:
            return {
                "content": [{
                    "type": "text",
                    "text": f"No markets found with probability >= {min_prob*100:.0f}% for query '{query}'"
                }]
            }

        # Format output
        lines = [f"Found {len(results)} high-certainty markets for '{query}':\n"]
        for i, m in enumerate(results, 1):
            lines.append(f"{i}. [{m['status']}] {m['name']}")
            lines.append(f"   Top: {m['top_outcome']} at {m['probability']}")
            lines.append(f"   Ends: {m['end_date']}")
            lines.append(f"   Volume: {m['volume']} | Liquidity: {m['liquidity']}")
            lines.append(f"   Slug: {m['slug']}")
            lines.append("")

        return {
            "content": [{
                "type": "text",
                "text": "\n".join(lines)
            }]
        }

    except Exception as e:
        return {
            "content": [{
                "type": "text",
                "text": f"Error searching markets: {str(e)}"
            }]
        }


@tool(
    name="get_market_details",
    description="Get detailed information about a specific Polymarket market including all outcomes, prices, and resolution rules.",
    input_schema={
        "type": "object",
        "properties": {
            "slug": {
                "type": "string",
                "description": "Market slug (e.g., 'which-company-has-the-best-ai-model-end-of-january')"
            }
        },
        "required": ["slug"]
    }
)
async def get_market_details(args: dict) -> dict:
    """Get detailed market information."""
    client = get_client()
    slug = args.get("slug", "")

    try:
        market = client.get_event_by_slug(slug)
        if not market:
            return {
                "content": [{
                    "type": "text",
                    "text": f"Market not found: {slug}"
                }]
            }

        lines = [
            f"Market: {market.title}",
            f"Status: {'OPEN' if market.active else 'CLOSED'}",
            f"End Date: {market.end_date}",
            f"Volume: ${market.volume:,.0f}" if market.volume else "Volume: N/A",
            f"Liquidity: ${market.liquidity:,.0f}" if market.liquidity else "Liquidity: N/A",
            "",
            "Outcomes (sorted by probability):"
        ]

        # Sort outcomes by price
        sorted_outcomes = sorted(
            market.outcomes,
            key=lambda o: o.price or 0,
            reverse=True
        )

        for i, o in enumerate(sorted_outcomes, 1):
            price_pct = f"{o.price * 100:.1f}%" if o.price else "N/A"
            lines.append(f"  {i}. {o.name}: {price_pct}")

        # Add resolution info if available
        if hasattr(market, 'description') and market.description:
            lines.append("")
            lines.append("Resolution Rules:")
            # Truncate if too long
            desc = market.description[:500] + "..." if len(market.description) > 500 else market.description
            lines.append(desc)

        return {
            "content": [{
                "type": "text",
                "text": "\n".join(lines)
            }]
        }

    except Exception as e:
        return {
            "content": [{
                "type": "text",
                "text": f"Error fetching market details: {str(e)}"
            }]
        }


def create_polymarket_tools_server():
    """Create an SDK MCP server with Polymarket tools."""
    return create_sdk_mcp_server(
        name="polymarket-tools",
        version="1.0.0",
        tools=[
            search_high_certainty_markets,
            get_market_details
        ]
    )
