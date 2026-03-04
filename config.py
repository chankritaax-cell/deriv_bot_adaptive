"""
⚙️ Configuration Module (v5.1.0)
Central configuration for Deriv Bot, including account settings, AI parameters, and trading profiles.
"""
import os

# ---------------------------------------------------------
# 🏷️ BOT_VERSION (Single Source of Truth)
DATA_MODE = "STREAMING"  # Options: "POLLING", "STREAMING"
BOT_VERSION = "5.1.2"     # [v5.1.2] Stream Auto-Reconnect & Relaxed AI Guards
COUNCIL_REAL_ADVISORY_ONLY = True  # If True, AI Council only gives advice in REAL mode, never pauses or edits code.
ENABLE_THB_CONVERSION = True
XRP_THB_RATE_FALLBACK = 43.91
USD_THB_RATE_FALLBACK = 36.50

# [v3.11.25] Centralized Root Directory
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------
# 🔐 LOAD ENV VARS
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
DERIV_ACCOUNT_TYPE = "demo" # "demo" or "real"

# ==========================================
# ⚙️ TIERED CONFIGURATION SYSTEM
# ==========================================
ACTIVE_PROFILE = "TIER_COUNCIL" 

PROFILES = {
    "TIER_1": {
        "AMOUNT": 1.0, 
        "MAX_DAILY_LOSS_PERCENT": 5.0,
        "MAX_DAILY_LOSS_ABSOLUTE": 25,
        "MAX_MARTINGALE_STEPS": 3,
        "MAX_STAKE_AMOUNT": 5,
        "MARTINGALE_MULTIPLIER": 2.0,
        "AI_CONFIDENCE_THRESHOLD": 0.60, 
    },
    "TIER_2": { 
        "AMOUNT": 1.0,
        "MAX_DAILY_LOSS_PERCENT": 10.0,
        "MAX_DAILY_LOSS_ABSOLUTE": 50,
        "MAX_MARTINGALE_STEPS": 5,
        "MAX_STAKE_AMOUNT": 10,
        "MARTINGALE_MULTIPLIER": 2.0,
        "AI_CONFIDENCE_THRESHOLD": 0.70,
    },
    "TIER_MICRO": { 
        "AMOUNT": 0.35,
        "MAX_DAILY_LOSS_PERCENT": 20.0,
        "MAX_DAILY_LOSS_ABSOLUTE": 10,
        "MAX_MARTINGALE_STEPS": 0,
        "MAX_STAKE_AMOUNT": 2,
        "MARTINGALE_MULTIPLIER": 1.0,
        "AI_CONFIDENCE_THRESHOLD": 0.80,
    },
   "TIER_COUNCIL": {
        "AMOUNT": 1.0,
        "MAX_DAILY_LOSS_PERCENT": 100.0,
        "MAX_DAILY_LOSS_ABSOLUTE": 15,  # เผื่อพื้นที่ให้หายใจนิดนึงเวลาตลาดผันผวน
        "MAX_MARTINGALE_STEPS": 2,      # ทบได้สูงสุด 2 ครั้ง (1$ -> 2$ -> 4$) โอกาสกลับมาขนะสูงมาก
        "MAX_STAKE_AMOUNT": 4,          # ล็อคเพดานไว้ที่ 4$ (เซฟตี้สุดๆ)
        "MARTINGALE_MULTIPLIER": 2.0,
        "AI_CONFIDENCE_THRESHOLD": 0.80, # บังคับให้ AI ต้องมั่นใจ 80% ขึ้นไปถึงจะให้ยิง!
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

# Ollama Settings
OLLAMA_MODEL = "qwen2.5:14b"
OLLAMA_HOST = "http://localhost:11434"
OLLAMA_TIMEOUT_SECONDS = 60
OLLAMA_COUNCIL_TIMEOUT_SECONDS = 180  # Longer timeout for Council's large prompts

# Trading Settings
# CURRENCY = "USD"
# INITIAL_CAPITAL = 9999.6100  # [v3.6.6] Set this to your actual starting capital for accurate P/L tracking. Set to 0 to use current balance.

CURRENCY = "USD" if DERIV_ACCOUNT_TYPE == "demo" else "XRP"
INITIAL_CAPITAL = 9999.61 if DERIV_ACCOUNT_TYPE == "demo" else 19.50 
ACTION_DELAY = 1

# Helper to parse list from .env
def _parse_asset_list(env_var, default_val):
    val = os.getenv(env_var, default_val)
    return [x.strip() for x in val.split(",") if x.strip()]

# Assets (Volatility Indices)
ASSETS_VOLATILITY = _parse_asset_list("ASSETS_VOLATILITY", "1HZ100V,1HZ75V,1HZ50V,1HZ25V,1HZ10V")

# [v3.6.7] Asset Priority Tiers (Recalculated from Trade History)
ASSET_PRIORITY_TIERS = {
    "TIER_1": _parse_asset_list("ASSET_TIER_1", "1HZ50V,R_75"),
    "TIER_2": _parse_asset_list("ASSET_TIER_2", "1HZ25V,1HZ100V,R_10,R_25,R_100"),
    "TIER_3": _parse_asset_list("ASSET_TIER_3", "1HZ75V,R_50,1HZ10V"),
    "TIER_COUNCIL": _parse_asset_list("ASSET_TIER_COUNCIL", "R_75,R_25")
}
ACTIVE_ASSET = os.getenv("ACTIVE_ASSET", "R_75") # ดึงค่าจาก .env ถ้าไม่มีให้ใช้ R_75 เป็นค่าเริ่มต้น

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
BET_GATE_CONFIDENCE_THRESHOLD = 0.80
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

# BOT_VERSION declaration moved to top

# [Safety Guards & Limits]
MIN_STAKE_AMOUNT = 1.0
SLIPPAGE_BUFFER = 0.10
ENABLE_RSI_GUARD = True   

RSI_CALL_MAX = 68           # ขยายกรอบฝั่งขึ้นให้หายใจสะดวกขึ้น
RSI_PUT_LOWER = 32          # ยอมให้ยิงลงได้ลึกขึ้น     # [v3.11.43] Safe lower bound to avoid bounce

RSI_CALL_MIN = 52.0
RSI_PUT_UPPER = 48.0


MIN_ATR_THRESHOLD_PCT = 0.015
MAX_ATR_THRESHOLD_PCT = 0.30  # [v5.1 Tuning] Raised from 0.20 to allow 1HZ100V to trade during high volatility
MA_SLOPE_THRESHOLD_PCT = 0.015  # [v5.0 FIX] lowered from 0.025 to allow moderate trends

# [v5.0 Adaptive Engine] Regime Detection Thresholds
# R_ assets (Volatility Index): lower ATR range
REGIME_HIGH_VOL_THRESHOLD_R = float(os.getenv("REGIME_HIGH_VOL_R", "0.100"))
REGIME_LOW_VOL_THRESHOLD_R  = float(os.getenv("REGIME_LOW_VOL_R",  "0.020"))

# 1HZ assets (1s Volatility Index): higher ATR range
REGIME_HIGH_VOL_THRESHOLD_1HZ = float(os.getenv("REGIME_HIGH_VOL_1HZ", "0.140"))
REGIME_LOW_VOL_THRESHOLD_1HZ  = float(os.getenv("REGIME_LOW_VOL_1HZ",  "0.030"))

# [v5.0 Adaptive Engine] Strategy auto-selection per regime
# When regime shifts, bot overrides profile strategy with these
REGIME_STRATEGY_HIGH_VOL = os.getenv("REGIME_STRATEGY_HIGH_VOL", "TREND_FOLLOWING")
REGIME_STRATEGY_LOW_VOL  = os.getenv("REGIME_STRATEGY_LOW_VOL",  "PULLBACK_ENTRY")
REGIME_STRATEGY_NORMAL   = os.getenv("REGIME_STRATEGY_NORMAL",   "AUTO")
# AUTO = ใช้ strategy จาก asset_profiles.json ตามปกติ

ENABLE_STOCHASTIC_BOUNCE_GUARD = True




# [v3.11.17] Trade Cooldown Settings
COOLDOWN_ANY_TRADE_MINS = 3      # Default 5 mins after any trade
COOLDOWN_LOSS_TRADE_MINS = 0    # Default 10 mins after a loss

# [v3.11.41] Regime Stability Guard
ENABLE_REGIME_STABILITY_GUARD = True
REGIME_STABILITY_WINDOW = 10          # how many recent candles to evaluate
REGIME_MAX_FLIPS = 3                  # max allowed regime flips within the window
REGIME_COOLDOWN_CANDLES = 3           # if choppy detected, force skip for next N candles

# Models
GEMINI_MODEL = "gemini-2.0-flash"
CHATGPT_MODEL = "gpt-4o"
CLAUDE_MODEL = "claude-sonnet-4-20250514"

# Keys
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# AI Task Routing
ENABLE_AI_TASK_ROUTING = True
AI_TASK_ROUTING = {
    "ASSET_SCANNER":        ["CHATGPT", "GEMINI"],  # ChatGPT เก่งเรื่องสแกนไว
    "TREND_FILTER":         ["CHATGPT", "GEMINI"],
    "AI_ANALYST":           ["GEMINI", "CHATGPT"],  # Gemini เก่งเรื่องหา Pattern กราฟ
    "BET_GATE":             ["CLAUDE", "CHATGPT"],  # 🟢 เปลี่ยนให้ Claude คุมประตูด่านสุดท้าย
    "RISK_MANAGER":         ["CLAUDE", "GEMINI"],   # 🟢 ให้ Claude จัดการความเสี่ยง
    "COUNCIL":              ["CLAUDE", "CHATGPT"],  # 🟢 ให้ Claude เป็นประธานสภาวิเคราะห์ความพ่ายแพ้
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
ENABLE_ASSET_ROTATION = True # [User Request] Re-enabled to Scan (R_75 + 1HZ50V)
SCAN_INTERVAL_MINUTES = 10
ASSET_SCAN_INTERVAL_MINS = 10
ASSET_SCAN_INTERVAL_NO_TRADE_MINS = 10

# 🛡️ Mathematical Guards (Post-AI Veto)
ENABLE_MACD_MOMENTUM_GUARD = True
ENABLE_TICK_VELOCITY_GUARD = True
MAX_TICK_VELOCITY_ATR_PCT = 0.5  # Tolerance for spike size relative to current ATR
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
# 🗺️ V5.0: ASSET-STRATEGY DYNAMIC MAPPING
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
            print(f"⚠️ Failed to load asset_profiles.json: {e}")
            ASSET_STRATEGY_MAP = {}
    
    # Ensure DEFAULT exists as a fallback
    if "DEFAULT" not in ASSET_STRATEGY_MAP:
        ASSET_STRATEGY_MAP["DEFAULT"] = {
            "strategy": "TREND_FOLLOWING",
            "allowed_signals": ["CALL", "PUT"],
            "rsi_bounds": {"call_min": 55.0, "call_max": 65.0, "put_min": 35.0, "put_max": 45.0},
            "bounce_limit": 6.0,
            "ma_slope_min": 0.025,
            "min_trades_before_trust": 0
        }

# Initial load on import
load_asset_profiles()

def get_asset_profile(asset, trade_count=0):
    profile = ASSET_STRATEGY_MAP.get(asset, ASSET_STRATEGY_MAP.get("DEFAULT", {}))
    
    # [FIXED] เช็คทั้ง 2 เงื่อนไข ป้องกันการหลุดรอด (v5.1.0 Refined)
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
