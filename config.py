import os
from dotenv import load_dotenv

load_dotenv()

# --- Hard constraints enforcement (C1-C6) ---
ALLOWED_ACTIONS = frozenset({"long_call", "long_put"})  # Phase 1 only; straddle/strangle added later

# --- IV Regime thresholds ---
IVR_LOW_THRESHOLD = 30     # below: cheap options, entry allowed
IVR_HIGH_THRESHOLD = 50    # above: expensive, avoid naked longs

# --- Position sizing (C6) ---
MAX_RISK_PER_TRADE_PCT = 2.0    # % of account equity; hard cap
MAX_PORTFOLIO_HEAT_PCT = 20.0   # total open risk cap across all positions

# --- Exit guardrails (section 4.4) ---
MAX_LOSS_PCT = 50.0             # cut at -50% of premium paid
DTE_FLOOR = 7                   # never hold past this many days to expiry
CATALYST_EXIT_BUFFER_DAYS = 1   # close at least this many days before known catalyst

# --- Entry filters (section 4.5 liquidity) ---
MAX_BID_ASK_SPREAD_PCT = 5.0    # max (ask-bid)/mid as a percentage
MIN_OPEN_INTEREST = 100
MIN_VOLUME = 10

# --- Preferred entry DTE range ---
MIN_DTE_AT_ENTRY = 30
MAX_DTE_AT_ENTRY = 90

# --- Target delta for strike selection (OTM bias) ---
TARGET_DELTA_CALL = 0.40   # slightly OTM call
TARGET_DELTA_PUT = -0.40   # slightly OTM put

# --- Commissions (per contract leg) ---
COMMISSION_PER_CONTRACT = 0.65  # USD

# --- Alpaca paper API (C4: paper only) ---
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "")
ALPACA_PAPER = True  # hard-coded; never set to False here

# --- Default scan watchlist ---
WATCHLIST = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "META"]

# --- IV Rank computation ---
IV_RANK_MIN_HISTORY_DAYS = 30   # minimum cached IV days before using real IVR
IV_RANK_LOOKBACK_DAYS = 252     # ~52 trading weeks

# --- SQLite journal path ---
JOURNAL_DB_PATH = "journal/trades.db"
