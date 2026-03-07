"""
📈 Market Engine (v3.5.1)
Handles market data fetching, candle processing, and technical indicator calculation.
"""
import asyncio
import time
import pandas as pd
import numpy as np
from deriv_api import DerivAPI
import config
from .utils import log_print, save_json_atomic, load_json_safe, ROOT
import os

# Cache for open assets
_ASSET_CACHE = {"data": [], "timestamp": 0}

FAILED_ASSETS_FILE = os.path.join(ROOT, "logs", "market", "failed_assets.json")

# Failed Asset Cache (Blacklist)
_FAILED_ASSETS = load_json_safe(FAILED_ASSETS_FILE, {}) # {symbol: timestamp}
_ASSET_COOLDOWN = 3600 # [v4.1.0] 1 hour cooldown for Cut and Run strategy (1 Loss)

def blacklist_asset(asset, duration_secs=None, reason=""):
    """
    Blacklist an asset for a cooldown period.
    duration_secs: Custom duration in seconds. If None, uses the default _ASSET_COOLDOWN (1 hour).
    reason: Optional log reason (e.g., "Sideways Exhaustion", "Cut & Run").
    """
    global _FAILED_ASSETS
    if duration_secs is not None and duration_secs < _ASSET_COOLDOWN:
        # Store an offset timestamp so is_blacklisted() expires after `duration_secs`
        _FAILED_ASSETS[asset] = time.time() - (_ASSET_COOLDOWN - duration_secs)
    else:
        _FAILED_ASSETS[asset] = time.time()
    save_json_atomic(_FAILED_ASSETS, FAILED_ASSETS_FILE)
    reset_asset_cache()  # [v5.0 BUG-07 FIX] banned asset must leave cache immediately

def remove_from_blacklist(asset):
    global _FAILED_ASSETS
    if asset in _FAILED_ASSETS:
        del _FAILED_ASSETS[asset]
        save_json_atomic(_FAILED_ASSETS, FAILED_ASSETS_FILE)

# Track last market-layer error so the bot can distinguish between
# (a) per-asset issues vs (b) global network/API connectivity issues.
_LAST_ERROR = {"type": None, "message": "", "ts": 0.0, "asset": None, "op": None}


def _looks_like_network_issue(msg: str) -> bool:
    m = (msg or "").lower()
    keywords = [
        "keepalive", "ping timeout", "timed out", "timeout", "connection error",
        "no close frame", "1011", "websocket", "connection closed", "handshake",
        "internal error",
    ]
    return any(k in m for k in keywords)


def _set_last_error(err_type, message, asset=None, op=None):
    global _LAST_ERROR
    _LAST_ERROR = {
        "type": err_type,
        "message": str(message) if message is not None else "",
        "ts": time.time(),
        "asset": asset,
        "op": op,
    }


def get_last_error():
    return dict(_LAST_ERROR)


def clear_last_error():
    _set_last_error(None, "", None, None)


def reset_asset_cache():
    _ASSET_CACHE["data"] = []
    _ASSET_CACHE["timestamp"] = 0

# Asset Name Mapping
_ASSET_NAMES = {
    "1HZ100V": "Volatility 100 (1s) Index",
    "1HZ10V": "Volatility 10 (1s) Index",
    "1HZ25V": "Volatility 25 (1s) Index",
    "1HZ50V": "Volatility 50 (1s) Index",
    "1HZ75V": "Volatility 75 (1s) Index",
    "R_100": "Volatility 100 Index",
    "R_10": "Volatility 10 Index",
    "R_25": "Volatility 25 Index",
    "R_50": "Volatility 50 Index",
    "R_75": "Volatility 75 Index",
    "JD10": "Jump 10 Index",
    "JD25": "Jump 25 Index",
    "JD50": "Jump 50 Index",
    "JD75": "Jump 75 Index",
    "JD100": "Jump 100 Index"
}

def get_asset_name(symbol):
    """Returns human readable name from symbol."""
    return _ASSET_NAMES.get(symbol, symbol)

async def get_candles(api: DerivAPI, asset, count, granularity):
    """
    Fetch candles from Deriv API.
    granularity: seconds (60, 120, etc.)
    """
    try:
        # Deriv API expects style='candles'
        ticks_history_request = {
            "ticks_history": asset,
            "adjust_start_time": 1,
            "count": count,
            "end": "latest",
            "start": 1,
            "style": "candles",
            "granularity": granularity
        }
        
        # Call API with timeout
        data = await asyncio.wait_for(api.ticks_history(ticks_history_request), timeout=10.0)
        
        if "candles" in data:
            return data["candles"]
        elif "history" in data:
             # Handle tick data if candles not returned (should not happen with style='candles')
             return []
        else:
             log_print(f"   🐛 DEBUG: No 'candles' in response for {asset}. Keys: {list(data.keys())}")
             if "error" in data:
                 log_print(f"   ❌ API Error: {data['error']}")
             return []
    except asyncio.TimeoutError:
        log_print(f"    ⚠️ [Market] Timeout fetching candles for {asset}")
        _set_last_error('network', 'timeout fetching candles', asset=asset, op='candles')
        return []
    except Exception as e:
        msg = str(e)
        if _looks_like_network_issue(msg):
            log_print(f"   ⚠️ [Market] connection error for {asset}: {msg}")
            _set_last_error("network", msg, asset=asset, op="candles")
            return []
        log_print(f"   ⚠️ [Market] error fetching candles for {asset}: {msg}")
        _set_last_error("asset", msg, asset=asset, op="candles")
        blacklist_asset(asset)
        return []
    
def candles_to_df(candles: list[dict]) -> pd.DataFrame:
    """Helper to transform list of candles into indexed DataFrame."""
    if not candles:
        return pd.DataFrame()
    
    df = pd.DataFrame(candles)
    # Deriv returns: epoch, open, high, low, close
    df['open'] = df['open'].astype(float)
    df['high'] = df['high'].astype(float)
    df['low'] = df['low'].astype(float)
    df['close'] = df['close'].astype(float)
    
    # [v3.11.7] Robust timestamp field detection
    ts_field = None
    for field in ['epoch', 'time', 'timestamp']:
        if field in df.columns:
            ts_field = field
            break
            
    if ts_field:
        df['timestamp'] = df[ts_field].astype(int)
        # Set index to timestamp but keep column for easy access
        df.set_index("timestamp", inplace=True, drop=False)
        df.sort_index(inplace=True)
    else:
        log_print("   ❌ [Market] CRITICAL: No timestamp field found in candles! Falling back to RangeIndex.")
    
    return df

async def get_candles_df(api: DerivAPI, asset, count, granularity):
    """Returns candles as DataFrame with 'open','high','low','close' and epoch index."""
    candles = await get_candles(api, asset, count, granularity)
    if not candles:
        err = get_last_error()
        if not err.get("type"):
            _set_last_error("data", f"no candles returned for {asset}", asset=asset, op="candles_df")
        return None
    clear_last_error()
    
    return candles_to_df(candles)

async def scan_open_assets(api: DerivAPI, smart_trader_instance=None, limit=5):
    """
    Returns list of open Volatility Indices with > 75% payout (approx).
    Deriv payouts are dynamic, but Volatility Indices are always open.
    Also caches display names.
    """
    global _ASSET_CACHE, _ASSET_NAMES
    if time.time() - _ASSET_CACHE["timestamp"] < 60:
        return _ASSET_CACHE["data"]
    
    # In Deriv, Volatility Indices are 24/7.
    # We filter by what's in config.ASSETS_VOLATILITY
    
    # To get real payouts, we'd need to propose a contract.
    # For scanning, we'll assume they are available.
    
    active_symbols_req = {"active_symbols": "brief", "product_type": "basic"}
    try:
        res = await asyncio.wait_for(api.active_symbols(active_symbols_req), timeout=10.0)
        active_symbols = res.get("active_symbols", [])
        
        candidates = []
        
        active_profile = getattr(config, "ACTIVE_PROFILE", "TIER_1")
        tiers = getattr(config, "ASSET_PRIORITY_TIERS", {})
        
        allowed_assets = tiers.get(active_profile)
        if not allowed_assets:
            allowed_assets = tiers.get("TIER_1", []) + tiers.get("TIER_2", []) + tiers.get("TIER_3", [])
        if not allowed_assets:
            allowed_assets = getattr(config, "ASSETS_VOLATILITY", [])
            
        for symbol in active_symbols:
            sym = symbol["symbol"]
            # Cache display name
            _ASSET_NAMES[sym] = symbol.get("display_name", sym)
            
            if sym in allowed_assets:
                # Check Blacklist
                if sym in _FAILED_ASSETS:
                    if time.time() - _FAILED_ASSETS[sym] < _ASSET_COOLDOWN:
                        # Still in cooldown, skip
                        continue
                    else:
                        # Cooldown expired, remove
                        remove_from_blacklist(sym)

                # Mock payout of 95% for now (Deriv is usually high)
                candidates.append((sym, 95.0))
        
        # [v3.6.0] Scanner Awareness: Check if Primary Strategy is Blocked
        # Uses dependency injection for SmartTrader to avoid circular imports
        
        def _tier_rank(sym):
            base_rank = 3
            if sym in tiers.get("TIER_1", []): base_rank = 0
            elif sym in tiers.get("TIER_2", []): base_rank = 1
            elif sym in tiers.get("TIER_3", []): base_rank = 2
            elif active_profile in tiers and sym in tiers[active_profile]: base_rank = 0
            
            # [v3.6.0] Check if blocked
            # We assume AI_MOMENTUM is primary. Check both directions?
            # Let's check if EITHER Call or Put is blocked for AI_MOMENTUM
            # If both blocked -> Rank 4 (Lowest)
            # If one blocked -> Rank 3 (Low)
            
            if smart_trader_instance:
                # Note: We need to use valid keys. Perf tracker uses Strategy|Direction|TF
                # We'll check standard "AI_MOMENTUM|CALL|1m" and "AI_MOMENTUM|PUT|1m"
                is_call_blocked, _ = smart_trader_instance.perf.should_block_combo(sym, "AI_MOMENTUM", "CALL", "1m")
                is_put_blocked, _ = smart_trader_instance.perf.should_block_combo(sym, "AI_MOMENTUM", "PUT", "1m")
                
                if is_call_blocked and is_put_blocked:
                    return 4 # Fully blocked, lowest priority
                elif is_call_blocked or is_put_blocked:
                    return base_rank + 1 # Partially blocked, lower priority
            
            return base_rank
        
        final_list = sorted(candidates, key=lambda c: _tier_rank(c[0]))
        
        _ASSET_CACHE["data"] = final_list
        _ASSET_CACHE["timestamp"] = time.time()
        
        clear_last_error()
        return final_list
    except Exception as e:
        msg = str(e)
        log_print(f"   ⚠️ [Market] Scan error: {msg}")
        _set_last_error('network' if _looks_like_network_issue(msg) else 'api', msg, op='active_symbols')
        return []

def get_asset_name(symbol):
    """Returns friendly display name if available, else symbol."""
    return _ASSET_NAMES.get(symbol, symbol)

async def check_asset_open(api: DerivAPI, asset):
    """Deriv Volatility Indices are always open, but good to check."""
    return True # Simplified for V-Indices

def is_blacklisted(asset):
    """Check if asset is currently in the cooldown blacklist."""
    if asset in _FAILED_ASSETS:
        if time.time() - _FAILED_ASSETS[asset] < _ASSET_COOLDOWN:
            return True
        else:
             # Expired
             remove_from_blacklist(asset)
    return False

def is_sleep_mode() -> tuple:
    """
    Returns (is_sleeping: bool, seconds_remaining: float).
    Bot should sleep and skip all trading logic when True.
    Sleep ends when earliest banned council asset expires.
    [v5.0 BUG-08 FIX]
    """
    council = list(getattr(config, "ASSET_PRIORITY_TIERS", {}).get("TIER_COUNCIL", ["R_75", "R_25"]))
    if not council:
        return False, 0.0
    all_banned = all(is_blacklisted(a) for a in council)
    if not all_banned:
        return False, 0.0
    # Find when first ban expires
    earliest_expire = min(
        _FAILED_ASSETS.get(a, time.time()) + _ASSET_COOLDOWN
        for a in council if a in _FAILED_ASSETS
    )
    remaining = earliest_expire - time.time()
    if remaining <= 0:
        return False, 0.0
    return True, remaining

def get_market_summary_from_df(df):
    """Snapshot for AI Prompt from an existing DataFrame — Enhanced with technical indicators."""
    if df is None or len(df) < 20: return None
    
    # [v4.0.6] Ensure AI only analyzes firmly closed candles in all modes.
    is_streaming = getattr(config, "DATA_MODE", "STREAMING").upper() == "STREAMING"
    working_df = df.copy() if is_streaming else df.iloc[:-1].copy()
    
    if len(working_df) < 20: return None
    
    price = float(working_df.iloc[-1]['close'])
    first_price = float(working_df.iloc[0]['close'])
    change = ((price - first_price) / first_price) * 100
    sma5 = working_df['close'].rolling(5).mean().iloc[-1]
    sma20 = working_df['close'].rolling(20).mean().iloc[-1]
    trend = "UPTREND" if sma5 > sma20 else "DOWNTREND"
    
    # SMA gap — how strong the trend is (closer = weaker trend)
    sma_gap_pct = abs(sma5 - sma20) / sma20 * 100 if sma20 > 0 else 0
    
    # Technical Indicators (safe — wrapped in try/except)
    rsi_str = "N/A"
    macd_str = "N/A"
    atr_str = "N/A"
    stoch_str = "N/A"
    
    try:
        from .technical_analysis import TechnicalConfirmation
        # Placeholder logic if needed
        
        # RSI
        if len(working_df) >= 15:
            rsi = TechnicalConfirmation.get_rsi(working_df)
            if rsi is not None:
                state = "Neutral"
                if rsi > 70: state = "Overbought ⚠️"
                elif rsi < 30: state = "Oversold ⚠️"
                rsi_str = f"{rsi:.1f} ({state})"
        
        # MACD
        if len(working_df) >= 35:
            macd, macd_sig, hist = TechnicalConfirmation.get_macd(working_df)
            if hist is not None:
                direction = "Bullish" if hist > 0 else "Bearish"
                momentum = "Strong" if abs(hist) > 0.5 else "Weak"
                macd_str = f"{hist:.4f} ({direction}/{momentum})"
        
        # ATR
        if len(working_df) >= 15:
            atr = TechnicalConfirmation.get_atr(working_df)
            if atr and price > 0:
                atr_pct = (atr / price) * 100
                vol_state = "Healthy"
                if atr_pct < 0.01: vol_state = "Dead/Flat ⚠️"
                elif atr_pct > 0.1: vol_state = "High Volatility"
                atr_str = f"{atr_pct:.4f}% ({vol_state})"
        
        # Stochastic
        if len(working_df) >= 17:
            k, d = TechnicalConfirmation.get_stochastic(working_df)
            if k is not None:
                stoch_state = "Neutral"
                if k > 80: stoch_state = "Overbought"
                elif k < 20: stoch_state = "Oversold"
                stoch_str = f"K={k:.1f}, D={d:.1f} ({stoch_state})"
    except Exception:
        pass  # Graceful fallback — basic summary still works
    
    return (
        f"Trend: {trend} (SMA_Gap: {sma_gap_pct:.3f}%), "
        f"RSI: {rsi_str}, MACD: {macd_str}, "
        f"ATR: {atr_str}, Stoch: {stoch_str}"
    )

async def get_market_summary_for_ai(api: DerivAPI, asset):
    """Snapshot for AI Prompt (Async) — Enhanced with technical indicators."""
    df = await get_candles_df(api, asset, 100, 60) # 100 candles, 1m granularity
    return get_market_summary_from_df(df)


def market_status_summary():
    """Returns a brief status string for the dashboard."""
    active_count = len(_ASSET_CACHE.get("data", []))
    last_scan = time.time() - _ASSET_CACHE.get("timestamp", 0)
    failed = len(_FAILED_ASSETS)
    return f"Active: {active_count} | Cached: {last_scan:.0f}s ago | Blacklisted: {failed}"

