"""
Centralized risk management parameters.
All risk thresholds imported from here by trading_tools, session_start, etc.
"""

# place_order: reject BUY orders at or above this price.
# Binary outcomes pay $1.00, so buying at >= $0.99 means <= 1% profit.
MAX_BUY_PRICE = 0.99

# place_order: reject BUY if (existing position + order cost) > this % of total_value.
# Prevents over-concentration in a single market.
MAX_POSITION_PCT = 0.20

# session_start: auto-sell if current best_bid drops >= this % below entry_price.
# Triggers market sell at best bid to limit losses.
STOP_LOSS_DROP_PCT = 0.20

# Hibernate: allow agent to set next wake time and leave a D-mail for future self.
HIBERNATE_ENABLED = True
MAX_HIBERNATE_HOURS = 24          # Max sleep duration (hours)
DEFAULT_WAKE_INTERVAL_HOURS = 4   # Fallback interval if agent didn't call hibernate()
