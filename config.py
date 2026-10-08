import os
from dotenv import load_dotenv

load_dotenv()

# --- Hard constraints enforcement (C1-C6) ---
ALLOWED_ACTIONS = frozenset({"long_call", "long_put"})  # Phase 1 only; straddle/strangle added later

# --- IV Regime thresholds ---
IVR_LOW_THRESHOLD = 30     # below: cheap options, entry allowed
IVR_HIGH_THRESHOLD = 50    # above: expensive, avoid naked longs

# --- Momentum override (trend-following regime) ---
# Allows entries above IVR_LOW_THRESHOLD when price trend is strong.
# IVR MEDIUM (30-50) + trend STRONG/MODERATE → entry at 75% normal risk
# IVR HIGH   (50-70) + trend STRONG only     → entry at 50% normal risk
# IVR > 70                                   → refused regardless of trend
IVR_MOMENTUM_OVERRIDE_MAX = 70    # hard ceiling; never buy above this IVR
MOMENTUM_RISK_MULT_MEDIUM  = 0.75  # risk multiplier for MEDIUM IVR + good trend
MOMENTUM_RISK_MULT_HIGH    = 0.50  # risk multiplier for HIGH IVR (≤70) + strong trend

# --- Position sizing (C6) ---
MAX_RISK_PER_TRADE_PCT = 3.0    # % of account equity; hard cap
MAX_PORTFOLIO_HEAT_PCT = 20.0   # total open risk cap across all positions

# --- Exit guardrails (section 4.4) ---
MAX_LOSS_PCT = 50.0             # cut at -50% of premium paid
DTE_FLOOR = 7                   # never hold past this many days to expiry
CATALYST_EXIT_BUFFER_DAYS = 1   # close at least this many days before known catalyst

# --- Entry filters (section 4.5 liquidity) ---
MAX_BID_ASK_SPREAD_PCT = 10.0   # max (ask-bid)/mid as a percentage; 10% accommodates lower-priced OTM options
MIN_OPEN_INTEREST = 100
MIN_VOLUME = 10

# --- Preferred entry DTE range ---
MIN_DTE_AT_ENTRY = 21
MAX_DTE_AT_ENTRY = 48

# --- OTM strike targeting (momentum/accumulation style) ---
# Selector targets this % OTM then walks in until budget is met.
TARGET_OTM_PCT_CALL = 0.12   # 12% above spot for calls
TARGET_OTM_PCT_PUT  = 0.12   # 12% below spot for puts
# Minimum OTM floor — prevents picking near-ATM strikes on low-priced stocks
# where $5 tick sizes collapse the OTM% (e.g. HIMS $34 → C35 is only 1.7% OTM)
MIN_OTM_PCT_CALL    = 0.05   # call strike must be at least 5% above spot
MIN_OTM_PCT_PUT     = 0.05   # put strike must be at least 5% below spot

# --- Commissions (per contract leg) ---
COMMISSION_PER_CONTRACT = 0.65  # USD

# --- Alpaca paper API (C4: paper only) ---
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "")
ALPACA_PAPER = True  # hard-coded; never set to False here

# --- AI Stack watchlist (categorized) ---
AI_STACK: dict[str, list[str]] = {
    # Custom XPUs/DPUs with hyperscaler design wins (Google, AWS, Meta)
    "ai_compute_asic": ["AVGO", "MRVL"],
    # HBM3E — the memory physically stacked on every AI accelerator
    "ai_memory": ["MU"],
    # Nearline HDD + NAND for petabyte-scale training data lakes
    "ai_storage": ["STX", "WDC"],
    # 800G/1.6T optical transceivers — GPU cluster interconnect plumbing
    "ai_optical": ["COHR"],
    # GaN power ICs for high-density data center PSUs; MPWR for GPU board voltage regs
    "ai_power": ["NVTS", "MPWR"],
    # Independent GPU cloud (Nebius Group) — pure-play AI infra
    "ai_cloud_infra": ["NBIS"],
    # Ethernet switching for GPU-to-GPU traffic in AI clusters
    "ai_networking": ["ANET", "CRDO"],
    # GPU rack servers shipped to hyperscalers; AI server backlogs
    "ai_servers": ["SMCI", "DELL"],
    # Liquid cooling + power mgmt for high-density GPU racks
    "ai_datacenter_infra": ["VRT"],
    # Manufactures every leading AI chip; EUV gatekeeper
    "ai_chip_supply_chain": ["TSM", "ASML"],
    # Nuclear/gas baseload contracted directly by hyperscalers for AI power demand
    "ai_power_generation": ["CEG", "VST"],
}

# Flat watchlist: broad market anchors + full AI stack
WATCHLIST: list[str] = (
    ["SPY", "QQQ", "NVDA", "AAPL", "MSFT", "TSLA", "AMZN", "META"]
    + [ticker for tickers in AI_STACK.values() for ticker in tickers]
)

# --- Focused scan universe: AI Compute / Semiconductor / IT only ---
# Narrower than WATCHLIST — excludes broad indices, power-generation utilities
# (CEG/VST), and all of DIVERSIFICATION (GLP1, travel, financials). Used by
# --focus on scan_watchlist.py / scan_momentum.py to cut scan time and keep
# interactive "market analysis" requests pointed at this sector by default.
FOCUS_AI_SEMI_IT: list[str] = [
    # AI compute / cloud infra
    "AVGO", "MRVL", "MU", "NBIS", "SMCI", "DELL", "VRT",
    # Semiconductor complex
    "NVDA", "TSM", "ASML", "COHR", "ANET", "CRDO", "NVTS", "MPWR", "STX", "WDC",
    # Mega-cap IT
    "MSFT", "AAPL", "AMZN", "META",
]

# --- Day-trade universe expansion (added in small batches, 2026-10-06 onward) ---
# Admission is STRUCTURAL only (never by backtest P&L per name - too few trades,
# that would be cherry-picking): 20-day avg dollar volume >= $1.5B (deep option
# markets), a 0-0.4 sigma two-week strike fits the $1,000 budget, and preference
# for sectors OUTSIDE AI/semis so day-trade entries are not one correlated bet.
# Verified next-earnings dates live in DAYTRADE_EARNINGS; a name with no verified
# date is not traded. Batch 1 (2026-10-06):
DAYTRADE_EXPANSION: list[str] = ["GOOGL", "PLTR", "JPM", "XOM", "V"]
DAYTRADE_EARNINGS: dict[str, str] = {
    # focus names reporting inside the current windows (verified 10-05/10-06)
    "ASML": "2026-10-14", "TSM": "2026-10-15", "VRT": "2026-10-21",   # VRT: sources say 10-21 or 10-28
    "MSFT": "2026-10-28", "AMZN": "2026-10-29", "ANET": "2026-11-02",
    "NVDA": "2026-11-17", "AVGO": "2026-12-10",
    "SMCI": "2026-11-03",
    "AAPL": "2026-11-02",   # Apple IR via MacRumors 10-06 (estimate sites: 10-29)
    # batch 1
    "GOOGL": "2026-10-28", "JPM": "2026-10-13", "V": "2026-10-27",
    "XOM": "2026-10-09",    # sources say 10-09 or 10-30: take the earlier
    "PLTR": "2026-11-02",   # sources say 11-02 or 11-09: take the earlier
}

# --- Diversification watchlist (non-AI sectors) ---
DIVERSIFICATION: dict[str, list[str]] = {
    # GLP-1 weight loss drugs — structural multi-year demand tailwind
    "glp1_weight_loss":     ["LLY", "NVO", "HIMS"],
    # Leisure & travel — consumer spending resilience, post-COVID normalization
    "leisure_travel":       ["MAR", "HLT", "RCL", "BKNG"],
    # Payment networks — transaction volume tied to consumer spending
    "financials_payments":  ["V", "MA", "AXP"],
    # Watching but not yet actionable (HIGH IVR or WEAK trend today)
    "watchlist_pending":    ["GS", "FCX", "CAT", "NUE", "COIN", "NFLX", "PLTR"],
}
IV_RANK_MIN_HISTORY_DAYS = 30   # minimum cached IV days before using real IVR
IV_RANK_LOOKBACK_DAYS = 252     # ~52 trading weeks

# --- Yahoo Finance rate-limit guard ---
YF_INTER_CALL_DELAY = 1.5   # seconds between yfinance API calls during batch scans
YF_MAX_RETRIES      = 3     # attempts per call before giving up
YF_RETRY_BACKOFF    = 2.0   # exponential backoff multiplier (delays: 1.5s → 3s → 6s)

# --- SQLite journal path ---
JOURNAL_DB_PATH = "journal/trades.db"
