"""
Configuration Module (v5.8.0)
Advanced AI Council & Premium Telegram Bridge
"""
import os

# ---------------------------------------------------------
 # [Cleaned garbled comment]
DATA_MODE = "STREAMING"  # Options: "POLLING", "STREAMING"
BOT_VERSION = "5.8.2"     # [v5.8.2] Disable MG in TIER_MASTER (backtest: WR 41.7% vs breakeven 76.8%, net -49 XRP)
COUNCIL_REAL_ADVISORY_ONLY = False # [v5.4.0] Full Loop Autonomy: AI Council can now auto-fix on REAL accounts.
ENABLE_THB_CONVERSION = True
XRP_THB_RATE_FALLBACK = 43.91
USD_THB_RATE_FALLBACK = 36.50

# [v3.11.25] Centralized Root Directory
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------
 # [Cleaned garbled comment]
# ---------------------------------------------------------
def load_env_file():
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'): continue
                if '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key.strip()] = value.strip()

load_env_file()

# Deriv Account
DERIV_APP_ID = os.getenv("DERIV_APP_ID", "1089")
DERIV_API_TOKEN = os.getenv("DERIV_API_TOKEN", "") 
DERIV_ACCOUNT_TYPE = os.getenv("DERIV_ACCOUNT_TYPE", "demo")  # "demo" or "real" — set via .env only

# ==========================================
 # [Cleaned garbled comment]
# ==========================================
ACTIVE_PROFILE = "TIER_MASTER" 

PROFILES = {
    "TIER_1": {
        "AMOUNT": 1.0, 
        "MAX_DAILY_LOSS_PERCENT": 5.0,
        "MAX_DAILY_LOSS_ABSOLUTE": 25,
        "MAX_MARTINGALE_STEPS": 0,
        "MAX_STAKE_AMOUNT": 5,
        "MARTINGALE_MULTIPLIER": 2.0,
        "AI_CONFIDENCE_THRESHOLD": 0.60, 
    },
    "TIER_2": { 
        "AMOUNT": 1.0,
        "MAX_DAILY_LOSS_PERCENT": 10.0,
        "MAX_DAILY_LOSS_ABSOLUTE": 50,
        "MAX_MARTINGALE_STEPS": 0,
        "MAX_STAKE_AMOUNT": 10,
        "MARTINGALE_MULTIPLIER": 2.0,
        "AI_CONFIDENCE_THRESHOLD": 0.70,
    },
    "TIER_MICRO": { 
        "AMOUNT": 0.35,
        "MAX_DAILY_LOSS_PERCENT": 20.0,
        "MAX_DAILY_LOSS_ABSOLUTE": 10,
        "MAX_MARTINGALE_STEPS": 2,
        "MAX_STAKE_AMOUNT": 2.0,
        "MARTINGALE_MULTIPLIER": 2.0,
        "AI_CONFIDENCE_THRESHOLD": 0.80,
    },
   "TIER_MASTER": {
        "AMOUNT": 1, # [v5.2.6] cleaned
        "MAX_DAILY_LOSS_PERCENT": 100.0,
        "MAX_DAILY_LOSS_ABSOLUTE": 15, # [Cleaned garbled comment]
        "MAX_MARTINGALE_STEPS": 0, # [v5.8.2] Disabled MG — backtest shows WR 41.7% vs breakeven 76.8% needed, net -49 XRP across 36 sequences
        "MAX_STAKE_AMOUNT": 4.0, # [Cleaned garbled comment]
        "MARTINGALE_MULTIPLIER": 2.0,
        "AI_CONFIDENCE_THRESHOLD": 0.75, # [Cleaned garbled comment]
    },
}

selected_config = PROFILES.get(ACTIVE_PROFILE, PROFILES["TIER_MICRO"])
AMOUNT = selected_config["AMOUNT"]
MAX_DAILY_LOSS_PERCENT = selected_config["MAX_DAILY_LOSS_PERCENT"]
MAX_DAILY_LOSS_ABSOLUTE = selected_config.get("MAX_DAILY_LOSS_ABSOLUTE", 0)
MAX_MARTINGALE_STEPS = selected_config.get("MAX_MARTINGALE_STEPS", 0)
MAX_STAKE_AMOUNT = selected_config.get("MAX_STAKE_AMOUNT", 0)
MARTINGALE_MULTIPLIER = selected_config["MARTINGALE_MULTIPLIER"]
AI_CONFIDENCE_THRESHOLD = selected_config["AI_CONFIDENCE_THRESHOLD"]  # [v3.6.7] Using profile value
MARTINGALE_RESET_TIMEOUT_MINS = 60

# Ollama Settings
OLLAMA_MODEL = "qwen2.5:14b"
OLLAMA_HOST = "http://localhost:11434"
OLLAMA_TIMEOUT_SECONDS = 60
OLLAMA_COUNCIL_TIMEOUT_SECONDS = 180  # Longer timeout for Council's large prompts

# Trading Settings
# CURRENCY = "USD"
# INITIAL_CAPITAL = 9999.6100  # [v3.6.6] Set this to your actual starting capital for accurate P/L tracking. Set to 0 to use current balance.

CURRENCY = "USD" if DERIV_ACCOUNT_TYPE == "demo" else "XRP"
INITIAL_CAPITAL = 9999.61 if DERIV_ACCOUNT_TYPE == "demo" else 12.344716
ACTION_DELAY = 1

# Helper to parse list from .env
def _parse_asset_list(env_var, default_val):
    val = os.getenv(env_var, default_val)
    return [x.strip() for x in val.split(",") if x.strip()]

# Assets (Volatility Indices)
 # [v5.2.5] cleaned
ASSETS_VOLATILITY = _parse_asset_list("ASSETS_VOLATILITY", "R_75,1HZ100V,1HZ50V,R_25,R_50,1HZ25V,1HZ10V")

# [v5.8.0] Sniper Mode Targets
DAILY_PROFIT_TARGET = 3.0  # Stop for the day if up 3 XRP
DAILY_LOSS_LIMIT = 4.0    # Stop for the day if down 4 XRP
ENABLE_ADX_FILTER = True
ADX_FILTER_THRESHOLD = 25

# [v5.8.3] Hour Filter — block dead UTC hours (backtest: WR 23.4% across 47 trades in these hours)
ENABLE_HOUR_FILTER = True
BLOCKED_UTC_HOURS = [2, 9, 11, 12, 21]  # UTC hours to block trading

# [v3.11.23] Global Shutdown state (Persisted in state for watchdog safety)
 # [Cleaned garbled comment]
ASSET_PRIORITY_TIERS = {
    "TIER_1": _parse_asset_list("ASSET_TIER_1", "R_75,1HZ50V"),
    "TIER_2": _parse_asset_list("ASSET_TIER_2", "1HZ100V"),
    "TIER_3": _parse_asset_list("ASSET_TIER_3", "R_50,1HZ10V"),
    "TIER_MASTER": _parse_asset_list("ASSET_TIER_MASTER", "R_75,R_100,R_50,R_25,R_10,1HZ50V,1HZ100V,1HZ75V,1HZ25V,1HZ10V")
}
ACTIVE_ASSET = os.getenv("ACTIVE_ASSET", "R_75") # [Cleaned garbled comment]

# [v3.6.0] Advanced Blocking Config
# [v3.6.5] Tuned Aggressive: Moderate Threshold (0.40)
MIN_TRADES_FOR_BLOCK = 15       
BAYES_BLOCK_THRESHOLD = 0.40    # Block if Bayesian Prob < 0.40 (Tightened from 0.30)
BAYES_UNBLOCK_THRESHOLD = 0.50  # Unblock if Bayesian Prob > 0.50 (Hysteresis)
ASSET_TIER3_MIN_CONFIDENCE = 0.80  # Require higher AI confidence for weak assets

# AI Settings
AI_PROVIDER = "CHATGPT" 
USE_AI_ANALYST = True
USE_AI_RISK_MANAGER = True
ENABLE_HARD_RULES = True  # [v3.5.3] Toggle hard safety checks (RSI/MACD blocks)
USE_CHATGPT_BET_GATE = True
BET_GATE_CONFIDENCE_THRESHOLD = 0.75  # Consolidated threshold for Unified AI Decision Engine
# AI Limits
CHATGPT_MAX_CALLS_PER_DAY = 200
AI_DAILY_LIMITS = {
    "CHATGPT": 200,
    "GEMINI": 500,
    "CLAUDE": 100,
    "OLLAMA": 9999
}

# AI Confidence Bet Scaling
ENABLE_AI_CONFIDENCE_BET_SCALING = False
AI_CONF_HIGH_THRESHOLD = 0.75
AI_CONF_HIGH_MULTIPLIER = 1.25
AI_CONF_LOW_THRESHOLD = 0.50
AI_CONF_LOW_MULTIPLIER = 0.35
AI_CONF_BET_MAX_MULTIPLIER = 1.5
AI_CONF_BET_MIN_MULTIPLIER = 0.7  # [v3.11.27] Allow risk reduction

# ---------------------------------------------------------
# Sniper Recovery System (Dynamic Confidence Threshold)
# ---------------------------------------------------------
 # [v5.2.0] cleaned
CONFIDENCE_BASE = 0.75 # [Cleaned garbled comment]
CONFIDENCE_MG_STEP_1 = 0.85 # [v5.6.1] Sniper Guard: ให้ AI conf=0.85 ผ่าน MG Step-1 ได้ (check เป็น `<` ไม่ใช่ `<=` ดังนั้น 0.85 < 0.85 = False = PASS)
CONFIDENCE_MG_STEP_2 = 0.80 # [Cleaned garbled comment]

# BOT_VERSION declaration moved to top

# [Safety Guards & Limits]
MIN_STAKE_AMOUNT = 0.8 # [Cleaned garbled comment]
SLIPPAGE_BUFFER = 0.10
ENABLE_RSI_GUARD = True

# [v5.7.1] RSI Guard Dynamic Range (wide PRE-AI filter — replaces tight profile bounds at PRE-AI stage)
# Profile call_min/call_max/put_min/put_max remain for TREND_FOLLOWING execution checks in smart_trader.py
RSI_GUARD_UPTREND_LO   = 45.0   # UPTREND CALL zone: RSI must be >= this
RSI_GUARD_UPTREND_HI   = 75.0   # UPTREND CALL zone: RSI must be <= this
RSI_GUARD_DOWNTREND_LO = 25.0   # DOWNTREND PUT zone: RSI must be >= this
RSI_GUARD_DOWNTREND_HI = 55.0   # DOWNTREND PUT zone: RSI must be <= this
RSI_GUARD_EXTREME_LO   = 15.0   # Always block RSI below this (crash zone / mega oversold)
RSI_GUARD_EXTREME_HI   = 90.0   # Always block RSI above this (mega overbought)
RSI_GUARD_HIGH_VOL_EXPAND = 5.0 # Expand both bounds by this in HIGH_VOL regime

# [v5.7.2] SIDEWAYS RSI directional pass-through (quasi-trend thresholds)
# If slope is flat (SIDEWAYS) but RSI is clearly directional → pass to AI instead of hard-skip
RSI_SIDEWAYS_UPBIAS = 55.0   # RSI > this in SIDEWAYS → treat as quasi-UPTREND (send to AI)
RSI_SIDEWAYS_DNBIAS = 45.0   # RSI < this in SIDEWAYS → treat as quasi-DOWNTREND (send to AI)

# [v5.7.3] PRE-AI RSI Soft Filter — block before LLM call if RSI ผิดฝั่ง
# Backtest 17-Mar: 3 blocked trades = 3 LOSS → WR +1.0%, ~78 API calls saved/day
PRE_AI_RSI_CALL_SOFT = float(os.getenv("PRE_AI_RSI_CALL_SOFT", "50.0"))  # CALL: RSI must be >= this
PRE_AI_RSI_PUT_SOFT  = float(os.getenv("PRE_AI_RSI_PUT_SOFT",  "50.0"))  # PUT:  RSI must be <= this

# [v5.7.4] POST-AI Edge Zone Confidence Gate
# When RSI is in an "edge zone" (near overbought/oversold), require higher AI confidence
# Backtest 17-18 Mar (61 trades): WR 55.7% → 64.1% (+8.4%), blocked 13L / 9W, net +4 trades
EDGE_ZONE_CALL_RSI   = float(os.getenv("EDGE_ZONE_CALL_RSI",   "63.0"))  # CALL RSI > this = edge zone
EDGE_ZONE_PUT_RSI    = float(os.getenv("EDGE_ZONE_PUT_RSI",    "38.0"))  # PUT  RSI < this = edge zone
EDGE_ZONE_MIN_CONF   = float(os.getenv("EDGE_ZONE_MIN_CONF",   "0.85"))  # Required conf in edge zone (lowered from 0.90 — Gemini rarely exceeds 0.85)

# [v5.1.6 LEGACY] RSI bounds below are NO LONGER USED by smart_trader.py
 # comment cleaned
# Kept for backward compatibility with any external tools referencing these values
RSI_CALL_MAX = 68
RSI_PUT_LOWER = 32
RSI_CALL_MIN = 55.0
RSI_PUT_UPPER = 45.0

# [v5.1.6 LEGACY] ATR/Slope thresholds below are NO LONGER USED by smart_trader.py
 # comment cleaned
# Regime thresholds below ARE still used by ai_engine.py regime detection
MIN_ATR_THRESHOLD_PCT = 0.015
MAX_ATR_THRESHOLD_PCT = 0.30
MA_SLOPE_THRESHOLD_PCT = 0.015  # [v5.7.2] Lowered from 0.020 → 0.015 (fewer SIDEWAYS false-positives)

# [v5.0 Adaptive Engine] Regime Detection Thresholds
# R_ assets (Volatility Index): lower ATR range
REGIME_HIGH_VOL_THRESHOLD_R = float(os.getenv("REGIME_HIGH_VOL_R", "0.100"))
REGIME_LOW_VOL_THRESHOLD_R  = float(os.getenv("REGIME_LOW_VOL_R",  "0.020"))

# 1HZ assets (1s Volatility Index): higher ATR range
REGIME_HIGH_VOL_THRESHOLD_1HZ = float(os.getenv("REGIME_HIGH_VOL_1HZ", "0.140"))
REGIME_LOW_VOL_THRESHOLD_1HZ  = float(os.getenv("REGIME_LOW_VOL_1HZ",  "0.030"))

# [v5.0 Adaptive Engine] Strategy auto-selection per regime
# When regime shifts, bot overrides profile strategy with these
REGIME_STRATEGY_HIGH_VOL = os.getenv("REGIME_STRATEGY_HIGH_VOL", "TREND_FOLLOWING") # [v5.7.2] was PULLBACK_ENTRY → Tier 2 fallback now uses TREND_FOLLOWING
REGIME_STRATEGY_LOW_VOL  = os.getenv("REGIME_STRATEGY_LOW_VOL",  "PULLBACK_ENTRY")
REGIME_STRATEGY_NORMAL   = os.getenv("REGIME_STRATEGY_NORMAL",   "AUTO")
 # [Cleaned garbled comment]

ENABLE_STOCHASTIC_BOUNCE_GUARD = True
 # [v5.2.6] cleaned
STOCH_PUT_STRICT = 20 # [Cleaned garbled comment]
STOCH_CALL_STRICT = 80 # [Cleaned garbled comment]




# [v3.11.17] Trade Cooldown Settings
COOLDOWN_ANY_TRADE_MINS = 3      # Default 3 mins after any trade
COOLDOWN_LOSS_TRADE_MINS = 3     # Default 3 mins after a loss

# [v3.11.41] Regime Stability Guard
ENABLE_REGIME_STABILITY_GUARD = True
REGIME_STABILITY_WINDOW = 10          # how many recent candles to evaluate
REGIME_MAX_FLIPS = 3                  # max allowed regime flips within the window
REGIME_COOLDOWN_CANDLES = 3           # if choppy detected, force skip for next N candles

# Models
GEMINI_MODEL = "gemini-2.5-flash"   # [v5.7.2] upgraded: API key นี้ migrate ไป Gemini 2.5 แล้ว (2.0 ทุกรุ่น 404)
# [v5.7.2] Gemini multi-model fallback — rotate เมื่อ model ถูก 429/404
# gemini-2.5-flash       = primary   (ฉลาดกว่า 2.0, ทดสอบ OK)
# gemini-2.5-flash-lite  = fallback  (เบากว่า เร็วกว่า ทดสอบ OK)
# gemini-flash-latest    = last resort alias (stable alias, ทดสอบ OK)
GEMINI_FALLBACK_MODELS = os.getenv("GEMINI_FALLBACK_MODELS", "gemini-2.5-flash,gemini-2.5-flash-lite,gemini-flash-latest").split(",")
CHATGPT_MODEL = "gpt-4o"
# [v5.7.2] Claude per-task model selection
# AI_ANALYST → Haiku 4.5 (fast, low-cost, real-time trading decisions)
# COUNCIL / everything else → Sonnet 4.5 (smart, deep-analysis)
CLAUDE_MODEL_HAIKU  = os.getenv("CLAUDE_MODEL_HAIKU",  "claude-haiku-4-5-20251001")
CLAUDE_MODEL_SONNET = os.getenv("CLAUDE_MODEL_SONNET", "claude-sonnet-4-5-20250929")
CLAUDE_MODEL        = CLAUDE_MODEL_SONNET   # legacy fallback (unused when routing active)
# Tasks that use Haiku — comma-separated override: CLAUDE_HAIKU_TASKS=AI_ANALYST,BET_GATE
_haiku_tasks_env = os.getenv("CLAUDE_HAIKU_TASKS", "AI_ANALYST")
CLAUDE_HAIKU_TASKS  = [t.strip() for t in _haiku_tasks_env.split(",") if t.strip()]

# Keys
OPENAI_API_KEY  = os.getenv("OPENAI_API_KEY", "")
GEMINI_API_KEY  = os.getenv("GEMINI_API_KEY", "")
GEMINI_API_KEY2 = os.getenv("GEMINI_API_KEY2", "")  # [v5.7.2] Backup key — rotate เมื่อ key แรก quota หมด
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# AI Task Routing
ENABLE_AI_TASK_ROUTING = True
AI_TASK_ROUTING = {
    # [v5.7.2] Provider names must match _PROVIDER_CALL_MAP keys: GEMINI, CHATGPT, CLAUDE, OLLAMA
    # Haiku vs Sonnet selection is handled inside _claude_raw_call() via CLAUDE_HAIKU_TASKS
    "ASSET_SCANNER":        ["GEMINI", "CHATGPT"],
    "TREND_FILTER":         ["GEMINI", "CHATGPT"],
    "AI_ANALYST":           ["GEMINI", "CLAUDE"],    # CLAUDE → Haiku (via CLAUDE_HAIKU_TASKS)
    "BET_GATE":             ["CLAUDE", "GEMINI"],    # CLAUDE → Haiku (via CLAUDE_HAIKU_TASKS)
    "RISK_MANAGER":         ["CLAUDE", "GEMINI"],    # CLAUDE → Sonnet (deep risk analysis)
    "COUNCIL":              ["CLAUDE", "CHATGPT"],   # CLAUDE → Sonnet (deep council analysis)
}
COUNCIL_TASK_NAME = "COUNCIL"
COUNCIL_MULTI_VOTE = True
COUNCIL_MIN_VOTES = 2

# Optimizations
USE_OLLAMA_TREND_FILTER = False  # [v3.5.9] Keep disabled - trend filter causing extended idle periods

# Strategies
STRATEGIES = ["MOMENTUM", "MEAN_REVERSION", "TREND_FOLLOWING"]
VERBOSE_MODE = False

# Logging
ENABLE_METRICS_LOGGING = True
METRICS_LOG_PATH = os.getenv("METRICS_LOG_PATH", os.path.join("logs", "metrics", "trade_metrics.jsonl"))
METRICS_LOG_CONSOLE = bool(int(os.getenv("METRICS_LOG_CONSOLE", "0")))

# Scanner Settings
AI_PROVIDER_TIMEOUT_SECONDS = 60
ENABLE_ASSET_ROTATION = True # [User Request] Re-enabled to Scan (R_75 + 1HZ50V)
SCAN_INTERVAL_MINUTES = 120                   # [v5.7.1] Reduced scan noise: 10 → 30 min
ASSET_SCAN_INTERVAL_MINS = 120               # [v5.7.1] Normal scan interval (was 10 min)
ASSET_SCAN_INTERVAL_NO_TRADE_MINS = 60      # Inactivity trigger stays at 10 min

 # [Cleaned garbled comment]
ENABLE_MACD_MOMENTUM_GUARD = True
ENABLE_TICK_VELOCITY_GUARD = True
MAX_TICK_VELOCITY_ATR_PCT = 0.5  # Tolerance for spike size relative to current ATR
TICK_VELOCITY_TOLERANCE_NORMAL   = 0.08   # [v5.7.1] 8% grace margin on spike limit (NORMAL regime)
TICK_VELOCITY_TOLERANCE_HIGH_VOL = 0.15   # [v5.7.1] 15% grace margin on spike limit (HIGH_VOL regime)
ANTI_REVERSAL_RSI_BOUNCE_LIMIT = 15.0 # [v5.1 Tuning] Raised from 10.0 to handle 1HZ10V volatility
ENABLE_MICRO_CONF_GUARD = False
ENABLE_DASHBOARD_CHART = False

# AI Council
ENABLE_AI_COUNCIL = True
COUNCIL_AUTO_FIX_PRACTICE = False
COUNCIL_MODERATOR_PROVIDER = "GEMINI"
ENABLE_AUTO_BACKTEST = True # [v3.11.0] Run backtest on NO_TRADE_TIMEOUT
COUNCIL_HISTORY_LIMIT = 50
MAX_CONSECUTIVE_LOSS_LIMIT = 3
NO_TRADE_TIMEOUT_MINS = 180  # [User Request] Extended to 3 hours for single-asset patience

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
ENABLE_TELEGRAM_NOTIFICATIONS = True  # [v3.6.8] Toggle for trade alerts via Telegram
ENABLE_AI_COUNCIL_NOTIFICATIONS = True  # [v3.6.9] Toggle for AI Council summaries via Telegram

# =========================================================
 # [Cleaned garbled comment]
# =========================================================
import json

ASSET_STRATEGY_MAP = {}

def load_asset_profiles():
    global ASSET_STRATEGY_MAP
    profile_path = os.path.join(ROOT_DIR, "asset_profiles.json")
    if os.path.exists(profile_path):
        try:
            with open(profile_path, "r", encoding="utf-8") as f:
                ASSET_STRATEGY_MAP = json.load(f)
        except Exception as e:
            print(f" Failed to load asset_profiles.json: {e}")
            ASSET_STRATEGY_MAP = {}
    
    # Ensure DEFAULT exists as a fallback
    if "DEFAULT" not in ASSET_STRATEGY_MAP:
        ASSET_STRATEGY_MAP["DEFAULT"] = {
            "strategy": "TREND_FOLLOWING",
            "allowed_signals": ["CALL", "PUT"],
            "rsi_bounds": {"call_min": 58.0, "call_max": 68.0, "put_min": 39.0, "put_max": 45.0},
            "bounce_limit": 6.0,
            "ma_slope_min": 0.025,
            "min_trades_before_trust": 0
        }

# Initial load on import
load_asset_profiles()

def get_asset_profile(asset, trade_count=0):
    profile = ASSET_STRATEGY_MAP.get(asset, ASSET_STRATEGY_MAP.get("DEFAULT", {}))
    
 # [Cleaned garbled comment]
    if profile.get("_disabled", False) or not profile.get("enabled", True):  
        return {
            "_disabled": True,
            "_disabled_reason": profile.get("_disabled_reason", profile.get("disabled_reason", f"{asset} disabled")),
            "strategy": "DISABLED",
            "allowed_signals": [],
        }
    min_trades = profile.get("min_trades_before_trust", 0)
    if trade_count < min_trades:
        return ASSET_STRATEGY_MAP.get("DEFAULT", {})
    return profile


