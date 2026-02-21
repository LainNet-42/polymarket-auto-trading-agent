"""
Polymarket MCP Server
Exposes Polymarket market data and analysis via MCP protocol
"""

import sys
import asyncio
import logging
from pathlib import Path

# Add parent dir to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from polymarket.client import PolymarketClient

from .tools.market_tools import search_markets, get_market_details, get_price_history, find_opportunities
from .tools.analysis_tools import analyze_opportunity, detect_anomalies, scan_anomalies
from .tools.trading_tools import get_balance, place_order, get_open_orders, cancel_order, hibernate

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Server("polymarket")

# Singleton client
_client: PolymarketClient = None


def get_client() -> PolymarketClient:
    global _client
    if _client is None:
        _client = PolymarketClient()
    return _client


@app.list_tools()
async def list_tools() -> list[Tool]:
    """List available MCP tools"""
    return [
        Tool(
            name="search_markets",
            description="Search Polymarket prediction markets. Returns list with names, prices, volumes. Use for getting a long list of opportunities.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search keyword (e.g., 'AI model', 'Trump', 'Bitcoin')"
                    },
                    "min_probability": {
                        "type": "number",
                        "description": "Min probability threshold (0-1) for filtering high-certainty markets",
                        "default": 0
                    },
                    "min_volume": {
                        "type": "number",
                        "description": "Min volume in USD",
                        "default": 0
                    },
                    "open_only": {
                        "type": "boolean",
                        "description": "Only return open (unsettled) markets",
                        "default": True
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max number of results",
                        "default": 20
                    }
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="get_market_details",
            description="Get detailed info about a specific market including all outcomes, prices, volumes.",
            inputSchema={
                "type": "object",
                "properties": {
                    "event_slug": {
                        "type": "string",
                        "description": "Event slug (e.g., 'fed-decision-in-january')"
                    },
                    "include_price_history": {
                        "type": "boolean",
                        "description": "Include price history for top outcomes",
                        "default": False
                    }
                },
                "required": ["event_slug"]
            }
        ),
        Tool(
            name="get_price_history",
            description="Get historical price data for a specific outcome in a market.",
            inputSchema={
                "type": "object",
                "properties": {
                    "event_slug": {
                        "type": "string",
                        "description": "Event slug (from find_opportunities)"
                    },
                    "outcome": {
                        "type": "string",
                        "description": "Outcome name (e.g., 'Google', 'xAI')"
                    },
                    "interval": {
                        "type": "string",
                        "enum": ["1h", "1d", "1w", "max"],
                        "description": "Time interval",
                        "default": "1d"
                    }
                },
                "required": ["event_slug", "outcome"]
            }
        ),
        Tool(
            name="analyze_opportunity",
            description="Analyze a market for betting opportunities. Returns risk assessment, historical context, and recommendations.",
            inputSchema={
                "type": "object",
                "properties": {
                    "event_slug": {
                        "type": "string",
                        "description": "Event slug (from find_opportunities)"
                    },
                    "strategy": {
                        "type": "string",
                        "enum": ["high_certainty", "value_bet"],
                        "description": "Analysis strategy",
                        "default": "high_certainty"
                    }
                },
                "required": ["event_slug"]
            }
        ),
        Tool(
            name="detect_anomalies",
            description="Detect unusual price movements using score-based classification. Score = |Change%| x LiquidityWeight x TimeWeight. Higher scores are more suspicious.",
            inputSchema={
                "type": "object",
                "properties": {
                    "event_slug": {
                        "type": "string",
                        "description": "Event slug (from find_opportunities)"
                    },
                    "window_hours": {
                        "type": "integer",
                        "description": "Detection window in hours",
                        "default": 24
                    },
                    "min_severity": {
                        "type": "string",
                        "enum": ["low", "medium", "high"],
                        "description": "Minimum severity to report",
                        "default": "medium"
                    },
                    "top_n": {
                        "type": "integer",
                        "description": "Maximum anomalies to return (sorted by score)",
                        "default": 20
                    }
                },
                "required": ["event_slug"]
            }
        ),
        Tool(
            name="scan_anomalies",
            description="Scan all active markets for price anomalies. No slug required. Returns top anomalies sorted by score.",
            inputSchema={
                "type": "object",
                "properties": {
                    "max_hours": {
                        "type": "integer",
                        "description": "Only scan markets ending within this time",
                        "default": 48
                    },
                    "window_hours": {
                        "type": "integer",
                        "description": "Detection window for price changes",
                        "default": 24
                    },
                    "min_severity": {
                        "type": "string",
                        "enum": ["low", "medium", "high"],
                        "description": "Minimum severity to include",
                        "default": "high"
                    },
                    "top_n": {
                        "type": "integer",
                        "description": "Maximum anomalies to return",
                        "default": 10
                    }
                }
            }
        ),
        Tool(
            name="find_opportunities",
            description="Find high-certainty binary markets ending soon. Returns list with slug, token_ids, recommended side, and potential profit. Sports markets are excluded. Probability ceiling hardcoded at 0.995. Use 'order' to change sort (endDate/volume/volume24hr/liquidity). Set binary_only=false to include non-Yes/No 2-outcome markets (Up/Down, Over/Under).",
            inputSchema={
                "type": "object",
                "properties": {
                    "max_hours": {
                        "type": "integer",
                        "description": "Max hours until market ends",
                        "default": 48
                    },
                    "min_probability": {
                        "type": "number",
                        "description": "Min probability threshold (0-1)",
                        "default": 0.90
                    },
                    "max_probability": {
                        "type": "number",
                        "description": "Max probability threshold (0-1). Hardcoded ceiling at 0.995.",
                        "default": 0.95
                    },
                    "neg_risk": {
                        "type": "boolean",
                        "description": "Filter by market type: true=multi-outcome events, false=simple binary. Omit for all."
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results",
                        "default": 20
                    },
                    "order": {
                        "type": "string",
                        "description": "Gamma API sort field",
                        "default": "endDate",
                        "enum": ["endDate", "volume", "volume24hr", "liquidity"]
                    },
                    "binary_only": {
                        "type": "boolean",
                        "description": "True=only Yes/No ONLY markets, False=any 2-outcome market (Up/Down, Over/Under, etc.)",
                        "default": True
                    }
                },
                "required": ["min_probability", "max_probability"]
            }
        ),
        # Trading tools
        Tool(
            name="get_balance",
            description="Get current USDC balance on Polymarket.",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="place_order",
            description="Place a BUY or SELL order on Polymarket. BUY auto-calculates price from order book and rejects if cost >= $0.99/share. Check actual_avg_price in response.",
            inputSchema={
                "type": "object",
                "properties": {
                    "token_id": {
                        "type": "string",
                        "description": "Token ID of the outcome (get from find_opportunities or market details)"
                    },
                    "side": {
                        "type": "string",
                        "enum": ["BUY", "SELL"],
                        "description": "Order side"
                    },
                    "size": {
                        "type": "number",
                        "description": "Number of shares to trade"
                    },
                    "event_slug": {
                        "type": "string",
                        "description": "Event slug for tracking (from find_opportunities)"
                    },
                    "outcome": {
                        "type": "string",
                        "description": "Outcome name (e.g. 'YES', 'NO')"
                    }
                },
                "required": ["token_id", "side", "size"]
            }
        ),
        Tool(
            name="get_open_orders",
            description="Get all open orders.",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="cancel_order",
            description="Cancel an open order by ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "order_id": {
                        "type": "string",
                        "description": "Order ID to cancel"
                    }
                },
                "required": ["order_id"]
            }
        ),
        # Hibernate tool
        Tool(
            name="hibernate",
            description="Enter hibernation. Like Steins;Gate D-mail: send a message to your future self across time. Scheduler skips invocations until you wake.",
            inputSchema={
                "type": "object",
                "properties": {
                    "hours": {
                        "type": "number",
                        "description": "How many hours to sleep. Min 0.5 (30min), max 24.",
                        "minimum": 0.5,
                        "maximum": 24
                    },
                    "d_mail": {
                        "type": "string",
                        "description": "Message to your future self - what you care about, what to watch for, what's on your mind. NOT the same as decision 'why' in trading_log. Think: what would you want to remember when you wake up?",
                        "default": ""
                    },
                    "invoke_num": {
                        "type": "integer",
                        "description": "Current invocation number (from your prompt header, e.g. 'Invocation #28' -> 28)"
                    }
                },
                "required": ["hours"]
            }
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Handle MCP tool calls"""
    try:
        client = get_client()

        if name == "search_markets":
            result = search_markets(client, **arguments)
        elif name == "get_market_details":
            result = get_market_details(client, **arguments)
        elif name == "get_price_history":
            result = get_price_history(client, **arguments)
        elif name == "analyze_opportunity":
            result = analyze_opportunity(client, **arguments)
        elif name == "detect_anomalies":
            result = detect_anomalies(client, **arguments)
        elif name == "scan_anomalies":
            result = scan_anomalies(client, **arguments)
        elif name == "find_opportunities":
            result = find_opportunities(**arguments)
        # Trading tools (don't need Gamma client)
        elif name == "get_balance":
            result = get_balance()
        elif name == "place_order":
            result = place_order(**arguments)
        elif name == "get_open_orders":
            result = get_open_orders()
        elif name == "cancel_order":
            result = cancel_order(**arguments)
        elif name == "hibernate":
            result = hibernate(**arguments)
        else:
            result = f"Unknown tool: {name}"

        return [TextContent(type="text", text=result)]

    except Exception as e:
        logger.error(f"Error executing tool {name}: {e}", exc_info=True)
        return [TextContent(type="text", text=f"Error: {str(e)}")]


async def main():
    """Main entry point for MCP server"""
    logger.info("Starting Polymarket MCP Server...")

    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())
