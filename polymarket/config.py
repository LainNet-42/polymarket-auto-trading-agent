"""
Configuration and constants for Polymarket API
"""

# API Endpoints
GAMMA_API_BASE = "https://gamma-api.polymarket.com"
CLOB_API_BASE = "https://clob.polymarket.com"

# Rate limiting
REQUEST_DELAY = 0.2  # seconds between requests
REQUEST_TIMEOUT = 30  # seconds

# Market slugs for historical analysis (used by analyze_opportunity)
# Add market slugs here to track historical winner patterns
AI_MODEL_MARKET_SLUGS: list[str] = []
