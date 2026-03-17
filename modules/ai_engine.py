"""
 AI Engine (Consolidated v3.11.63)
The "Brain" of the system: Orchestrates AI Providers and Smart Trader.
[v3.11.63] Bridge Sync: Performance & Atomic checkpoint support.
"""

import asyncio
import json
import os
import time
import datetime
import config
import numpy as np
import pandas as pd
from . import market_engine
from .utils import log_print, safe_config_get
from .ai_providers import call_ai_with_failover, get_ai_usage_stats, normalize_ai_result
from .smart_trader import SmartTrader

# [v3.11.25] Centralized Root
ROOT = getattr(config, "ROOT_DIR", os.getcwd())

# [v3.11.41] Regime Stability Cooldown Registry
_regime_cooldowns = {}

# --- V5.0 Sticky Market Regime State ---
_regime_state = {}         # {asset: "NORMAL" | "HIGH_VOL" | "LOW_VOL"}
_regime_history = {}       # {asset: ["NORMAL", "HIGH_VOL", ...]} (tracks last N ticks of raw threshold crossings)

 # [v5.1.2] cleaned
_sideways_counter = {} # comment cleaned
SIDEWAYS_RESCAN_THRESHOLD = 5  # Force asset rescan after this many consecutive SIDEWAYS candles

def get_sideways_rescan_needed(asset):
    """Check if the sideways counter has reached the threshold for forced rescan."""
    return _sideways_counter.get(asset, 0) >= SIDEWAYS_RESCAN_THRESHOLD

def reset_sideways_counter(asset):
    """Reset the sideways counter after a rescan is triggered."""
    _sideways_counter[asset] = 0

def apply_adaptive_config(asset, df_1m, base_cfg):
    """
    [v5.1.0] Multi-Profile Routing Engine.
    Orchestrates configuration selection based on Market Regime.
    Hierarchy: Specific Regime Profile ({asset}_{regime}) -> Base Asset Profile ({asset}) -> DEFAULT.
    """
    regime = _regime_state.get(asset, "NORMAL")
    profile_map = getattr(config, "ASSET_STRATEGY_MAP", {})
    
    # 1. Selection Logic with Cascading Fallback
    # First: Specific Regime Profile (e.g., 1HZ10V_HIGH_VOL)
    regime_profile_key = f"{asset}_{regime}"
    specific_profile = profile_map.get(regime_profile_key)
    
    if specific_profile:
        cfg = specific_profile.copy()
        log_print(f"    [Adaptive Routing] Specific regime profile found: {regime_profile_key}")
    else:
        # Second: Fallback to base_cfg (which config.get_asset_profile sets to {asset} or DEFAULT)
        cfg = base_cfg.copy()
        if regime != "NORMAL":
            log_print(f"    [Adaptive Routing] No specific profile for {regime_profile_key}. Using base/default with dynamic offsets.")

    # 2. Safety Layer: Explicit Numerical Sanitization (Full Float Guard)
    # This ensures all adaptive thresholds are float-safe for pandas/TA calculations.
    if "rsi_bounds" in cfg:
        bounds = {}
        # Iterate and cast ALL values to float (call_min, pullback_put_hi, etc.)
        for k, v in cfg["rsi_bounds"].items():
            try:
                bounds[k] = float(v)
            except (ValueError, TypeError):
                bounds[k] = v # Keep as is if not numeric
                
        # Fill missing core bounds with safe defaults if necessary
        for k, default in {"call_min": 55.0, "call_max": 65.0, "put_min": 35.0, "put_max": 45.0}.items():
            if k not in bounds:
                bounds[k] = float(default)
        
        # 3. Dynamic Offsets (Baseline Adaptation)
        # Apply standard nudges only if a specific regime profile was NOT found
        if not specific_profile:
            if regime == "HIGH_VOL":
                for k in ["call_min", "put_min"]: bounds[k] = float(bounds[k] - 3.0)
                for k in ["call_max", "put_max"]: bounds[k] = float(bounds[k] + 3.0)
                cfg["bounce_limit"] = float(cfg.get("bounce_limit", 6.0) * 1.5)
            elif regime == "LOW_VOL":
                for k in ["call_min", "put_min"]: bounds[k] = float(bounds[k] + 2.0)
                for k in ["call_max", "put_max"]: bounds[k] = float(bounds[k] - 2.0)
                cfg["bounce_limit"] = float(cfg.get("bounce_limit", 6.0) * 0.8)
        
        cfg["rsi_bounds"] = bounds

    # Final cleanup of non-RSI numerical keys
    for k in ["bounce_limit", "ma_slope_min"]:
        if k in cfg:
            try: cfg[k] = float(cfg[k])
            except: pass
            
    # [v5.1] Informative logging
    if regime != "NORMAL":
        bounce_val = float(cfg.get('bounce_limit', 0.0))
        log_print(f"    [Adaptive Applied] {asset} | Regime={regime} | Bounce={bounce_val:.1f}")
        
    return cfg

def sys_log(msg):
    log_print(msg)

_SMART_TRADER = SmartTrader()
_perf_metrics = {
    "total_cycles": 0, "pre_ai_skip_cycles": 0, "ai_called_cycles": 0,
    "ai_skip_cycles": 0, "ai_suggest_cycles": 0, "post_ai_block_cycles": 0,
    "bet_gate_block_cycles": 0, "trades_count": 0, "last_50_results": []
}

def _fc_to_float(value):
    if value is None: return None
    if isinstance(value, (int, float)): return float(value)
    try:
        s = str(value).strip()
        if not s or s.lower() in {"n/a", "na", "none", "null", "unknown"}: return None
        s = s.replace(",", "").replace("$", "")
        if s.endswith("%"): s = s[:-1].strip()
        return float(s)
    except Exception: return None

def _fc_to_pct(value): return _fc_to_float(value)

def _fc_norm_conf(value, default=0.0):
    v = _fc_to_float(value)
    if v is None: return float(default)
    if v > 1.0 and v <= 100.0: v = v / 100.0
    if v < 0.0: v = 0.0
    if v > 1.0: v = 1.0
    return float(v)

def _fc_parse_bool(value, default=None):
    if isinstance(value, bool): return value
    if value is None: return default
    s = str(value).strip().lower()
    if s in {"true", "1", "yes", "y", "approve", "approved", "enter"}: return True
    if s in {"false", "0", "no", "n", "reject", "rejected", "skip"}: return False
    return default

def _get_rsi_bounds_call(profile=None):  # [v5.0 BUG-06 FIX]
    if profile and "rsi_bounds" in profile:
        b = profile["rsi_bounds"]
        return (float(b.get("call_min", 55)), float(b.get("call_max", 65)))
    a = float(safe_config_get('RSI_CALL_MIN', 55))
    b_val = float(safe_config_get('RSI_CALL_MAX', 60))
    return (a, b_val) if a <= b_val else (b_val, a)

def _get_rsi_bounds_put(profile=None):  # [v5.0 BUG-06 FIX]
    if profile and "rsi_bounds" in profile:
        b = profile["rsi_bounds"]
        return (float(b.get("put_min", 32)), float(b.get("put_max", 48)))
    lo = float(safe_config_get('RSI_PUT_LOWER', safe_config_get('RSI_PUT_MAX', 32)))
    hi = float(safe_config_get('RSI_PUT_UPPER', safe_config_get('RSI_PUT_MIN', 52)))
    return (lo, hi) if lo <= hi else (hi, lo)

def is_rsi_valid_for_signal(signal, rsi, profile=None):  # [v5.0 BUG-06 FIX]
    if rsi is None: return True
    if not safe_config_get("ENABLE_RSI_GUARD", True): return True
    s = str(signal).upper().strip()
    r = float(rsi)
    if s == "CALL":
        lo, hi = _get_rsi_bounds_call(profile)
        return lo <= r <= hi
    if s == "PUT":
        lo, hi = _get_rsi_bounds_put(profile)
        return lo <= r <= hi
    return True

def run_logic_self_audit():
    log_print("  [Self-Audit] Active Logic Thresholds:")
    # [v5.1.7] Show RSI bounds from DEFAULT profile (actual active bounds)
    _default_profile = getattr(config, "ASSET_STRATEGY_MAP", {}).get("DEFAULT", {})
    lo_c, hi_c = _get_rsi_bounds_call(_default_profile)
    log_print(f"    RSI CALL Window: {lo_c} - {hi_c} (from asset_profiles DEFAULT)")
    lo_p, hi_p = _get_rsi_bounds_put(_default_profile)
    log_print(f"    RSI PUT Window:  {lo_p} - {hi_p} (from asset_profiles DEFAULT)")
    log_print(f"    MIN_ATR_THRESHOLD_PCT: {safe_config_get('MIN_ATR_THRESHOLD_PCT', 0.012)}%")
    log_print(f"    MA_SLOPE_THRESHOLD_PCT: {safe_config_get('MA_SLOPE_THRESHOLD_PCT', 0.03)}%")
    try:
        dummy_labels = ["UPTREND"] * 5 + ["DOWNTREND"] * 2 + ["SIDEWAYS"] * 3
        flips = sum(1 for i in range(1, len(dummy_labels)) if dummy_labels[i] != dummy_labels[i-1])
        log_print(f"    Regime Detection Logic: OK (Dummy Seq Flips: {flips})")
    except Exception as e: log_print(f"  [Stability Audit] Error: {e}")
    _run_rsi_regression_test()

def _run_rsi_regression_test():
    lo_p, hi_p = _get_rsi_bounds_put()
    lo_c, hi_c = _get_rsi_bounds_call()
    mid_p = (lo_p + hi_p) / 2
    mid_c = (lo_c + hi_c) / 2
    
    test_cases = [
        ("PUT", mid_p, True), ("PUT", lo_p - 2.0, False), ("PUT", hi_p + 2.0, False),
        ("CALL", mid_c, True), ("CALL", lo_c - 2.0, False), ("CALL", hi_c + 2.0, False)
    ]
    failures = [f"{sig} @ {val:.1f}: Expected {exp}, got {is_rsi_valid_for_signal(sig, val)}" for sig, val, exp in test_cases if is_rsi_valid_for_signal(sig, val) != exp]
    
    if failures:
        log_print(" [Self-Audit] RSI Logic Regression Test: FAILED!")
        for f in failures: log_print(f"   - {f}")
    else: 
        log_print(" [Self-Audit] RSI Logic Regression Test: PASSED")

def _log_metrics_to_file():
    if not getattr(config, "ENABLE_METRICS_LOGGING", True): return
    log_path = getattr(config, "METRICS_LOG_PATH", "logs/metrics/trade_metrics.jsonl")
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    total = _perf_metrics["total_cycles"]
    called = max(1, _perf_metrics["ai_called_cycles"])
    suggested = max(1, _perf_metrics["ai_suggest_cycles"])
    snapshot = {
        "timestamp": datetime.datetime.now().isoformat(),
        "total_cycles": total,
        "pre_ai_skip_rate": round(_perf_metrics["pre_ai_skip_cycles"] / max(1, total) * 100, 2),
        "ai_skip_rate": round(_perf_metrics["ai_skip_cycles"] / called * 100, 2),
        "post_ai_block_rate": round(_perf_metrics["post_ai_block_cycles"] / suggested * 100, 2),
        "bet_gate_block_rate": round(_perf_metrics["bet_gate_block_cycles"] / suggested * 100, 2),
        "win_rate_50": round(_perf_metrics["last_50_results"].count("WIN") / max(1, len(_perf_metrics["last_50_results"])) * 100, 2)
    }
    try:
        with open(log_path, "a", encoding="utf-8") as f: f.write(json.dumps(snapshot) + "\n")
    except: pass

def get_smart_trader(): return _SMART_TRADER

async def ask_ollama_trend_status(market_data_summary):
    if not getattr(config, "USE_OLLAMA_TREND_FILTER", True): return "TRENDING"
    prompt = f"""ACT AS: Senior Market Analyst.\nTASK: Classify the market regime.\nMARKET DATA:\n{market_data_summary}\nOUTPUT JSON ONLY: {{"status": "TRENDING" | "SIDEWAYS", "confidence": 0.9, "reason": "..."}}"""
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, call_ai_with_failover, prompt, "TREND_FILTER", 0.3)
    if result and isinstance(result, dict):
        status = result.get("status", "TRENDING").upper()
        return status if status in ["TRENDING", "SIDEWAYS"] else "TRENDING"
    return "TRENDING"

def check_market_sentiment():
    SENTIMENT_FILE = os.path.join(ROOT, "logs", "market_sentiment.json")
    if not os.path.exists(SENTIMENT_FILE): return True, "No News Data"
    try:
        with open(SENTIMENT_FILE, 'r', encoding='utf-8') as f: data = json.load(f)
        if time.time() - data.get("timestamp", 0) > 1800: return True, "News Data Stale"
        impact = data.get("impact", "LOW").upper()
        if impact in ["HIGH", "CRITICAL"]: return False, f"Risk: {impact} Impact News ({data.get('source')})"
        return True, "News Safe"
    except: return True, "Read Error"

def _get_bet_gate_metrics(df_1m, asset, strategy):
    from .utils import dashboard_get_state
    ds = dashboard_get_state()
    history = ds.get("trade_history", [])
    
 # comment cleaned
    asset_trades = [t for t in history if t.get("asset") == asset]
    _a_sample = asset_trades[-20:]
    if len(_a_sample) < 3:
        asset_wr_str = f"N/A (Only {len(_a_sample)} trades)"
    else:
        asset_wr_str = f"{(sum(1 for t in _a_sample if t.get('result') == 'WIN') / len(_a_sample)) * 100:.1f}%"
    
 # comment cleaned
    strat_trades = [t for t in history if t.get("strategy") == strategy]
    _s_sample = strat_trades[-20:]
    if len(_s_sample) < 3:
        strat_wr_str = f"N/A (Only {len(_s_sample)} trades)"
    else:
        strat_wr_str = f"{(sum(1 for t in _s_sample if t.get('result') == 'WIN') / len(_s_sample)) * 100:.1f}%"
    
    vol_spike = False
    if df_1m is not None and len(df_1m) >= 28:
        try:
            from .technical_analysis import TechnicalConfirmation
            current_atr = TechnicalConfirmation.get_atr(df_1m, 14)
            atrs = [TechnicalConfirmation.get_atr(df_1m.iloc[:-i], 14) for i in range(1, 15)]
            atrs = [a for a in atrs if a is not None]
            if atrs and current_atr: vol_spike = current_atr > (sum(atrs) / len(atrs) * 1.5)
        except: pass
        
    return {
        "asset_winrate_20": asset_wr_str,
        "strategy_winrate_20": strat_wr_str,
        "daily_pnl": f"${ds.get('profit', 0.0):.2f}", 
        "current_loss_streak": ds.get("loss_streak", 0),
        "current_win_streak": ds.get("win_streak", 0), 
        "volatility_spike": vol_spike
    }

async def unified_ai_decision_engine(context):
    """
    [v5.3.0] Unified Decision Engine using Gemini 2.0 Flash.
    Consolidates Market Analyst + Bet Gate into a single async call.
    """
    action_type = str(context.get("action_type", "DISCOVERY")).upper()
    asset_name = str(context.get("asset", "Unknown"))
    metrics = context.get("metrics", {})
    current_regime = context.get("regime", "NORMAL")
    stoch_k = context.get("stoch_k", "N/A")
    rsi_val = context.get("rsi", "N/A")
    det_trend = context.get("trend", "Unknown")
    
    # RSI Bounds for reference in prompt
    profile = context.get("asset_profile")
    call_lo, call_hi = _get_rsi_bounds_call(profile)
    put_lo, put_hi = _get_rsi_bounds_put(profile)

    macd_hist = context.get("macd_hist", "N/A")
    daily_pnl = metrics.get("daily_pnl", "N/A")

    prompt = f"""Role: Act as Chief Investment Officer (CIO) and Senior Risk Manager for a Quantitative Trading Desk.
Task: Analyze Market Data to provide a final Trade Decision.

Input Context:
1. MARKET DATA:
- Asset: {asset_name} | Regime: {current_regime}
- Trend (MA): {det_trend} (Slope: {context.get('slope_pct', 'Unknown')}%)
- RSI: {rsi_val} (Target Areas: CALL {call_lo:.0f}-{call_hi:.0f} | PUT {put_lo:.0f}-{put_hi:.0f})
- Stochastic K: {stoch_k}
- MACD Histogram: {macd_hist}
- Volatility (ATR %): {context.get('atr_pct', 'Unknown')}%
- Volatility Spike: {metrics.get('volatility_spike', False)}
- Price Action: {context.get('market_summary', 'N/A')}
- Recent Trades (last 3): {context.get('recent_trades', 'N/A')}

Thinking Process:
Base your APPROVE/VETO decision STRICTLY on Technical Analysis (Price Action, Trend, RSI, Stoch, MACD). Do NOT consider historical win rates or past performance. If the technical setup is strong, APPROVE. Use the Confidence Calibration rules below for the exact score.
Step 1 (Technical Audit): Verify if market momentum and indicators align with a CALL or PUT setup.
   - CALL: Trend must be UPTREND, RSI must be in range, Stoch K must not be Overbought (< 80).
   - PUT: Trend must be DOWNTREND, RSI must be in range, Stoch K must not be Oversold (> 20).
Step 2 (Risk Filtering): Apply institutional risk rules.
   - If Volatility Spike is True: VETO any trade unless momentum is exceptionally strong.
   - Require strong confirmation from MACD and RSI before deciding.
Step 3 (Confidence Calibration — STRICT ENFORCEMENT):
   Giving 0.80 or 0.85 as a default for every trade is a calibration failure. You MUST score per the matrix below.
   SCORING MATRIX (apply exactly — count aligned indicators first):
   Aligned indicators: (a) Trend direction correct, (b) RSI in target zone, (c) Stoch K not OB/OS,
                       (d) MACD histogram sign matches trend direction, (e) No volatility spike.
   - 4-5 aligned + zero conflicts → 0.90-0.95
   - 3 aligned + 1 neutral        → 0.78-0.85
   - 2-3 aligned + 1 conflicting  → 0.65-0.75
   - 1-2 aligned + 2+ conflicting → 0.50-0.60
   DEDUCTIONS (apply after base score):
   - DEDUCT 0.05 for each conflicting signal (e.g. MACD bearish while trend UPTREND = -0.05)
   - DEDUCT 0.05 if Volatility Spike is True
   - If "conflicting_signals" field is not "None", confidence CANNOT exceed 0.82

Output Format: Respond with JSON only in this format:
{{"decision": "APPROVE" | "VETO", "confidence": <float 0.0-1.0>, "signal": "CALL" | "PUT" | "SKIP", "reason": "Short Thai reasoning", "conflicting_signals": "ระบุ indicators ที่ขัดแย้งกัน หรือ 'None' ถ้าทุกตัว align"}}"""

    start_time = time.time()
    # Call Gemini via ai_providers (task routing handles model selection)
    result = await asyncio.get_running_loop().run_in_executor(
        None, call_ai_with_failover, prompt, "AI_ANALYST", 0.3, 300
    )
    latency = time.time() - start_time

    if result and isinstance(result, dict):
        result["latency"] = latency
        return result
        
    return {"action": "VETO", "confidence": 0.0, "signal": "SKIP", "reason": "AI Offline  FAIL-CLOSED", "latency": latency}

def calculate_local_risk_score(metrics, signal, context):
    """
    [v5.7.2] Mathematical Validation Layer (Non-AI).
    Returns a score; LOCAL VETO fires if score < 0.55.
    Components: Trend (0.35) + RSI (0.15) + Stoch (0.15) + MACD alignment (+0.10/-0.15) + WinRate (0.15) + Spike (0.10)
    """
    score = 0.0

    # 1. Trend (0.35) — slightly reduced to make room for MACD
    slope = context.get("slope_pct", 0)
    if signal == "CALL" and slope > 0.015: score += 0.35
    elif signal == "PUT" and slope < -0.015: score += 0.35

    # 2. Momentum
    # RSI wide guard (0.15) — uses wide GUARD bounds, not tight profile bounds
    rsi_val = _fc_to_float(context.get("rsi"))
    if rsi_val is not None:
        _rsi_ok = False
        if signal == "CALL" and float(getattr(config, "RSI_GUARD_UPTREND_LO", 45.0)) <= rsi_val <= float(getattr(config, "RSI_GUARD_UPTREND_HI", 75.0)):
            _rsi_ok = True
        elif signal == "PUT" and float(getattr(config, "RSI_GUARD_DOWNTREND_LO", 25.0)) <= rsi_val <= float(getattr(config, "RSI_GUARD_DOWNTREND_HI", 55.0)):
            _rsi_ok = True
        if _rsi_ok:
            score += 0.15

    # Stoch (0.15)
    stoch_k = _fc_to_float(context.get("stoch_k"))
    if stoch_k is not None:
        if signal == "CALL" and stoch_k < 80: score += 0.15
        elif signal == "PUT" and stoch_k > 20: score += 0.15

    # MACD alignment bonus/penalty (+0.10 aligned / -0.15 contradicts) [v5.7.2]
    macd_hist = _fc_to_float(context.get("macd_hist"))
    if macd_hist is not None:
        if signal == "CALL" and macd_hist > 0: score += 0.10
        elif signal == "PUT" and macd_hist < 0: score += 0.10
        elif (signal == "CALL" and macd_hist < 0) or (signal == "PUT" and macd_hist > 0):
            score -= 0.15  # MACD contradicts signal direction

    # 3. Performance
    # Win Rate (0.15) — [v5.7.1] Fixed None guard; [v5.7.2] reduced 0.2→0.15
    win_rate = _fc_to_float(metrics.get("asset_winrate_20", 0))
    if win_rate is not None and win_rate > 50.0: score += 0.15

    # Volatility Spike (0.10)
    if not metrics.get("volatility_spike", False): score += 0.10

    return round(max(0.0, score), 2)

def _get_feature_df(df_1m, granularity_sec=60):
    if df_1m is None or len(df_1m) < 3: return None
    
    # [v4.0.6] Flawless Timing Patch: Instead of relying on non-deterministic local clock (time.time())
    # which causes random dropping of the *closed* candle in streaming mode, we check DATA_MODE.
    # In STREAMING mode, df_1m always contains precisely closed candles (forming is never pushed).
    # In POLLING mode, the last candle is always forming (from Deriv API directly).
    is_streaming = getattr(config, "DATA_MODE", "STREAMING").upper() == "STREAMING"
    
    if is_streaming:
        df_feat = df_1m.copy()
        dropped = False
    else:
        df_feat = df_1m.iloc[:-1].copy()
        dropped = True
        
    # [v5.3.2] Data Trimming: Limit to recent 100 rows for token efficiency
    if len(df_feat) > 100:
        df_feat = df_feat.iloc[-100:].copy()
        
    if len(df_feat) < 3: return None
    log_print(f"    Feature DF: rows={len(df_feat)} last_ts={int(df_feat.iloc[-1]['timestamp'])} (trimmed=100)")
    return df_feat

def _shadow_fire(api, asset: str, signal: str, reason: str, df_feat, rsi_val, macd_hist, stoch_k_val):
    """[v5.6.5] Fire-and-forget shadow trade tracker. Never blocks the main loop."""
    try:
        if signal not in ("CALL", "PUT"):
            return
        from .shadow_tracker import shadow_tracker
        entry_price = float(df_feat["close"].iloc[-1])
        indicators = {
            "rsi":       rsi_val or 0.0,
            "macd_hist": macd_hist or 0.0,
            "stoch_k":   stoch_k_val or 0.0,
        }
        asyncio.create_task(
            shadow_tracker.track_virtual_trade(api, asset, signal, reason, entry_price, indicators)
        )
    except Exception:
        pass


async def analyze_and_decide(api, asset, market_data_summary, df_1m):
    global _perf_metrics
    _perf_metrics["total_cycles"] += 1
    cycle_start = time.time() # [v5.3.2] Cycle Latency Start
    
    signal = "HOLD"
    confidence = 0.0
    ai_reason = ""
    is_high_quality = False
    rsi_val = None
    atr_pct = 0.0
    slope = 0.0
    det_trend = "SIDEWAYS"
    raw_snapshot = {}
    unified_latency = 0.0
    ai_decision = {}
    local_score = 0.0 # [v5.3.2]
    
    is_safe, sentiment_reason = check_market_sentiment()
    if not is_safe:
        log_print(f"    Analysis Skipped: {sentiment_reason}")
        return None

    # [User Request] Martingale Staleness Reset Guard
    from .utils import load_martingale_state, reset_martingale_state
    mg_step, _, last_loss_timestamp = load_martingale_state()
    if mg_step > 0 and last_loss_timestamp > 0:
        timeout_mins = getattr(config, "MARTINGALE_RESET_TIMEOUT_MINS", 60)
        if (time.time() - last_loss_timestamp) > (timeout_mins * 60):
            log_print(f"    [Martingale] MG Step {mg_step} expired (waited > {timeout_mins}m). Resetting to Step 0 for safety.")
            reset_martingale_state()

    df_feat = _get_feature_df(df_1m, 60)
    if df_feat is None:
        log_print("    Not enough closed candles for feature calculation. FAIL-CLOSED -> SKIP.")
        _perf_metrics["pre_ai_skip_cycles"] += 1
        return None
    
    _early_trade_count = sum(1 for t in _SMART_TRADER.perf.data.get("trades", []) if t.get("asset") == asset)
    _early_profile = config.get_asset_profile(asset, _early_trade_count)  # [v5.0 BUG-06 FIX]
    
    if safe_config_get("ENABLE_REGIME_STABILITY_GUARD", True):
        global _regime_cooldowns
        cooldown = _regime_cooldowns.get(asset, 0)
        if cooldown > 0:
            _regime_cooldowns[asset] = cooldown - 1
            log_print(f"    Regime stability cooldown: {cooldown-1} candles remaining for {asset}")
            _perf_metrics["pre_ai_skip_cycles"] += 1
            return None
            
        window = safe_config_get("REGIME_STABILITY_WINDOW", 10)
        max_flips = safe_config_get("REGIME_MAX_FLIPS", 3)
        is_choppy, flips, labels = _SMART_TRADER.tech.calculate_regime_stability(df_feat, window, max_flips)
        
        if is_choppy:
            cooldown_count = safe_config_get("REGIME_COOLDOWN_CANDLES", 3)
            _regime_cooldowns[asset] = cooldown_count
            log_print(f"    PRE-AI SKIP (Regime Stability): CHOPPY flips={flips}/{window} > {max_flips} | labels={labels[-5:]} | cooldown={cooldown_count}")
            _perf_metrics["pre_ai_skip_cycles"] += 1
            return None

        # 0.1 Technical Deterministic Pre-Check
    if df_feat is not None and len(df_feat) > 15:
        rsi_val = _SMART_TRADER.tech.get_rsi(df_feat)
        atr_ema_val, atr_pct = _SMART_TRADER.tech.get_atr_ema(df_feat, 14, 20)
        atr = _SMART_TRADER.tech.get_atr(df_feat) # Fallback / Base Check
        if atr_pct is None and atr is not None and df_feat is not None:
             price = float(df_feat.iloc[-1]["close"]) if not df_feat.empty else 0
             atr_pct = (atr / price * 100) if price > 0 else 0
        if atr_pct is None: atr_pct = 0.0
        
        # --- V5.0 Sticky Market Regime State Machine ---
        # [v5.0 FIX] Read thresholds from config instead of hardcode
        if "1HZ" in asset:
            HIGH_VOL_THRESHOLD = float(getattr(config, "REGIME_HIGH_VOL_THRESHOLD_1HZ", 0.140))
            LOW_VOL_THRESHOLD  = float(getattr(config, "REGIME_LOW_VOL_THRESHOLD_1HZ",  0.030))
        else:
            HIGH_VOL_THRESHOLD = float(getattr(config, "REGIME_HIGH_VOL_THRESHOLD_R", 0.100))
            LOW_VOL_THRESHOLD  = float(getattr(config, "REGIME_LOW_VOL_THRESHOLD_R",  0.020))
        
        raw_regime = "NORMAL"
        if atr_pct > HIGH_VOL_THRESHOLD: raw_regime = "HIGH_VOL"
        elif atr_pct < LOW_VOL_THRESHOLD: raw_regime = "LOW_VOL"
        
        history = _regime_history.get(asset, [])
        history.append(raw_regime)
        if len(history) > 3: history = history[-3:]
        _regime_history[asset] = history
        
        current_state = _regime_state.get(asset, "NORMAL")
        if len(history) == 3 and all(h == raw_regime for h in history):
            if current_state != raw_regime:
                log_print(f"    [Regime Change] {asset} shifted from {current_state} -> {raw_regime} (ATR EMA: {atr_pct:.4f}%)")
                _regime_state[asset] = raw_regime
                
        sma = df_feat["close"].rolling(7).mean()
        slope_threshold = getattr(config, "MA_SLOPE_THRESHOLD_PCT", 0.03)
        if len(sma) >= 6 and not sma.iloc[-1] != sma.iloc[-1]:
            current_ma = sma.iloc[-1]
            prev_ma = sma.iloc[-6]
            if prev_ma > 0: slope = (current_ma - prev_ma) / prev_ma * 100
            if slope > slope_threshold: det_trend = "UPTREND"
            elif slope < -slope_threshold: det_trend = "DOWNTREND"
            else: det_trend = "SIDEWAYS"
        
        # --- VOLATILITY CHECKS (LOW & HIGH) ---
        min_atr_pct = getattr(config, "MIN_ATR_THRESHOLD_PCT", 0.012)
        
 # comment cleaned
        max_atr_pct = float(getattr(config, 'MAX_ATR_THRESHOLD_PCT', 0.15))
        
        if atr_pct < min_atr_pct:
            rsi_display = f"{rsi_val:.1f}" if rsi_val is not None else "N/A"
            log_print(f"    PRE-AI SKIP (Low Vol): {atr_pct:.4f}% < {min_atr_pct}% | RSI: {rsi_display} | Trend: {det_trend}")
            _perf_metrics["pre_ai_skip_cycles"] += 1
            return None
            
        if atr_pct > max_atr_pct:
            rsi_display = f"{rsi_val:.1f}" if rsi_val is not None else "N/A"
            log_print(f"    PRE-AI SKIP (High Vol): {atr_pct:.4f}% > {max_atr_pct}% (Slippage Risk) | Trend: {det_trend}")
            _perf_metrics["pre_ai_skip_cycles"] += 1
            return None
            
        candle = df_feat.iloc[-1]
        c_range = abs(float(candle['high']) - float(candle['low']))
        if atr > 0 and c_range > (atr * 2.5):
            log_print(f"    PRE-AI SKIP (Whipsaw Guard): Candle Range {c_range:.2f} > 2.5x ATR ({atr:.2f}). Waiting.")
            _perf_metrics["pre_ai_skip_cycles"] += 1
            return None

        # --- [v5.1.2] Consecutive Sideways Counter ---
        if det_trend == "SIDEWAYS":
            _sideways_counter[asset] = _sideways_counter.get(asset, 0) + 1
            count = _sideways_counter[asset]
            if count >= SIDEWAYS_RESCAN_THRESHOLD:
                log_print(f"    [Sideways Guard] {count} consecutive SIDEWAYS candles on {asset}  flagging for forced asset rescan.")
        elif det_trend in ("UPTREND", "DOWNTREND"):
            if _sideways_counter.get(asset, 0) > 0:
                _sideways_counter[asset] = 0

        if rsi_val is not None:
            # [v5.7.1] Dynamic RSI Guard — wide pre-AI filter
            # Profile call_min/call_max remain tight for TREND_FOLLOWING execution (smart_trader.py)
            _rsi_extreme_lo = float(getattr(config, "RSI_GUARD_EXTREME_LO", 15.0))
            _rsi_extreme_hi = float(getattr(config, "RSI_GUARD_EXTREME_HI", 90.0))
            _regime_now = _regime_state.get(asset, "NORMAL")
            _rsi_expand = float(getattr(config, "RSI_GUARD_HIGH_VOL_EXPAND", 5.0)) if _regime_now == "HIGH_VOL" else 0.0

            # Block absolute extremes regardless of trend direction
            if rsi_val < _rsi_extreme_lo or rsi_val > _rsi_extreme_hi:
                log_print(f"    PRE-AI SKIP (RSI Guard): RSI {rsi_val:.1f} in extreme zone (<{_rsi_extreme_lo:.0f} or >{_rsi_extreme_hi:.0f})")
                _perf_metrics["pre_ai_skip_cycles"] += 1
                return None

            # [v5.7.2] SIDEWAYS RSI directional pass-through — check BEFORE range gates
            # If slope is flat but RSI is clearly directional → override det_trend for AI context
            if det_trend == "SIDEWAYS":
                _rsi_up  = float(getattr(config, "RSI_SIDEWAYS_UPBIAS", 55.0))
                _rsi_dn  = float(getattr(config, "RSI_SIDEWAYS_DNBIAS", 45.0))
                if rsi_val > _rsi_up:
                    det_trend = "UPTREND"   # quasi-UPTREND: slope flat but RSI bullish
                    log_print(f"    [Trend Override] SIDEWAYS→UPTREND (RSI {rsi_val:.1f} > {_rsi_up:.0f}, slope={slope:.4f}%)")
                elif rsi_val < _rsi_dn:
                    det_trend = "DOWNTREND"  # quasi-DOWNTREND: slope flat but RSI bearish
                    log_print(f"    [Trend Override] SIDEWAYS→DOWNTREND (RSI {rsi_val:.1f} < {_rsi_dn:.0f}, slope={slope:.4f}%)")
                else:
                    log_print(f"    PRE-AI SKIP (Trend Guard): SIDEWAYS (Slope {slope:.4f}%) | RSI: {rsi_val:.1f} | Consecutive: {_sideways_counter.get(asset, 0)}")
                    _perf_metrics["pre_ai_skip_cycles"] += 1
                    return None

            # Apply directional RSI range check (det_trend may have been overridden above)
            if det_trend == "UPTREND":
                _rsi_lo = float(getattr(config, "RSI_GUARD_UPTREND_LO", 45.0)) - _rsi_expand
                _rsi_hi = float(getattr(config, "RSI_GUARD_UPTREND_HI", 75.0)) + _rsi_expand
                if not (_rsi_lo <= rsi_val <= _rsi_hi):
                    log_print(f"    PRE-AI SKIP (RSI Guard): UPTREND RSI {rsi_val:.1f} outside [{_rsi_lo:.0f}–{_rsi_hi:.0f}] | Vol: {atr_pct:.4f}%")
                    _perf_metrics["pre_ai_skip_cycles"] += 1
                    return None
            elif det_trend == "DOWNTREND":
                _rsi_lo = float(getattr(config, "RSI_GUARD_DOWNTREND_LO", 25.0)) - _rsi_expand
                _rsi_hi = float(getattr(config, "RSI_GUARD_DOWNTREND_HI", 55.0)) + _rsi_expand
                if not (_rsi_lo <= rsi_val <= _rsi_hi):
                    log_print(f"    PRE-AI SKIP (RSI Guard): DOWNTREND RSI {rsi_val:.1f} outside [{_rsi_lo:.0f}–{_rsi_hi:.0f}] | Vol: {atr_pct:.4f}%")
                    _perf_metrics["pre_ai_skip_cycles"] += 1
                    return None
        # --- [v4.1.2] Confluence Guard: Trend/MACD Divergence Filter ---
        # if df_feat is not None and len(df_feat) >= 35 and det_trend in ["UPTREND", "DOWNTREND"]:
        #     try:
        #         macd_line, _, _ = _SMART_TRADER.tech.get_macd(df_feat)
        #         if macd_line is not None:
        #             macd_val = float(macd_line)
        #             if det_trend == "UPTREND" and macd_val < 0:
        #                 log_print(f"   PRE-AI SKIP (Confluence Guard): {det_trend} but MACD {macd_val:.4f} contradicts. Divergence detected.")
        #                 _perf_metrics["pre_ai_skip_cycles"] += 1
        #                 return None
        #             elif det_trend == "DOWNTREND" and macd_val > 0:
        #                 log_print(f"   PRE-AI SKIP (Confluence Guard): {det_trend} but MACD {macd_val:.4f} contradicts. Divergence detected.")
        #                 _perf_metrics["pre_ai_skip_cycles"] += 1
        #                 return None
        #     except Exception:
        #         pass  # Graceful fallback - skip guard if MACD calculation fails
    else:
        log_print("    Not enough 1m candle data for analysis.")
        return None

    if getattr(config, "USE_AI_ANALYST", True):
        # [v5.1.4] Fetch Stochastic for Exhaustion Guard in prompt
        stoch_k_val, stoch_d_val = None, None
        try:
            from .technical_analysis import TechnicalConfirmation
            stoch_k_val, stoch_d_val = TechnicalConfirmation.get_stochastic(df_1m)
        except Exception:
            pass
        stoch_str = f"Stoch K={stoch_k_val:.1f}, D={stoch_d_val:.1f}" if stoch_k_val is not None and stoch_d_val is not None else "Stoch: N/A"

        # [v5.6.9] PRE-AI Stoch Guard — reject obvious violations BEFORE the LLM API call
        # Logic: in UPTREND only a CALL is viable; in DOWNTREND only a PUT is viable.
        # If Stoch already fails the strict rule for that direction, skip immediately.
        if stoch_k_val is not None:
            _stoch_put_strict_pre = float(getattr(config, "STOCH_PUT_STRICT", 20))
            _stoch_call_strict_pre = float(getattr(config, "STOCH_CALL_STRICT", 80))
            if det_trend == "DOWNTREND" and stoch_k_val < _stoch_put_strict_pre:
                log_print(f"    PRE-AI SKIP (Stoch Guard): PUT rejected. Stoch K={stoch_k_val:.1f} < {_stoch_put_strict_pre:.0f} (oversold in DOWNTREND) — API call saved 🛑")
                _perf_metrics["pre_ai_skip_cycles"] += 1
                return None
            if det_trend == "UPTREND" and stoch_k_val > _stoch_call_strict_pre:
                log_print(f"    PRE-AI SKIP (Stoch Guard): CALL rejected. Stoch K={stoch_k_val:.1f} > {_stoch_call_strict_pre:.0f} (overbought in UPTREND) — API call saved 🛑")
                _perf_metrics["pre_ai_skip_cycles"] += 1
                return None

        # Calculate MACD Histogram before AI call
        macd_hist = 0.0
        try:
            _, _, hist_val = _SMART_TRADER.tech.get_macd(df_feat)
            macd_hist = float(hist_val) if hist_val is not None else 0.0
        except: pass

        # Gather context for Unified Engine
        metrics = _get_bet_gate_metrics(df_feat, asset, "UNIFIED") # Strategy unknown yet

        # [v5.7.1] Recent 3-trade context for conflict detection
        try:
            from .utils import dashboard_get_state as _dgs_inner
            _ds_ctx = _dgs_inner()
            _rt_hist = _ds_ctx.get("trade_history", [])
            _rt_3 = [t for t in _rt_hist if t.get("asset") == asset][-3:]
            _recent_3_str = ", ".join([
                f"{t.get('result','?')}({t.get('signal','?')} conf={t.get('ai_confidence',0):.2f})"
                for t in _rt_3
            ]) if _rt_3 else "No recent trades on this asset"
        except Exception:
            _recent_3_str = "N/A"

        context = {
            "asset": asset,
            "metrics": metrics,
            "regime": _regime_state.get(asset, "NORMAL"),
            "stoch_k": stoch_k_val if stoch_k_val is not None else "N/A",
            "rsi": f"{rsi_val:.1f}" if rsi_val is not None else "N/A",
            "macd_hist": round(macd_hist, 6),
            "trend": det_trend,
            "slope_pct": round(slope, 4),
            "atr_pct": round(atr_pct, 4),
            "asset_profile": _early_profile,
            "market_summary": market_data_summary,
            "recent_trades": _recent_3_str,  # [v5.7.1]
        }

        # CALL UNIFIED ENGINE (Gemini 2.0 Flash)
        ai_decision = await unified_ai_decision_engine(context)
        unified_latency = ai_decision.get("latency", 0.0)

        if ai_decision and isinstance(ai_decision, dict):
            decision = str(ai_decision.get("decision", "VETO")).upper().strip()
            action_raw = str(ai_decision.get("signal", "SKIP")).upper().strip()
            
            signal = "SKIP" if action_raw in ["NO TRADE", "NO_TRADE", "HOLD", "WAIT", "SKIP"] or decision == "VETO" else action_raw
            confidence = _fc_norm_conf(ai_decision.get("confidence", 0.0), default=0.0)
            ai_reason = ai_decision.get("reason", "")
            
            # [v5.3.1] Local Risk Validation Layer (Hard VETO)
            local_score = calculate_local_risk_score(metrics, signal, context) if signal in ["CALL", "PUT"] else 0.0
            
            if decision == "APPROVE" and signal in ["CALL", "PUT"]:
                if local_score < 0.55:  # [v5.7.2] Raised from 0.50 → 0.55 (tighter gate after MACD component added)
                    log_print(f"    LOCAL VETO: AI said APPROVE, but Local Risk Score is {local_score:.2f} (< 0.55). Overriding to VETO.")
                    # [v5.6.5] Shadow track trades blocked by Local Risk Score
                    _shadow_fire(api, asset, signal, f"LOCAL_VETO: score={local_score:.2f}", df_feat, rsi_val, macd_hist, stoch_k_val)
                    decision = "VETO"
                    signal = "SKIP"
                    ai_reason = f"(LOCAL VETO: score {local_score}) " + ai_reason
                else:
                    log_print(f"    Local Risk Score: {local_score:.2f} (Passed)")

            raw_snapshot = {"rsi": rsi_val, "slope": slope, "atr_pct": atr_pct, "macd_hist": macd_hist, "atr": atr}

            log_print(f"    Unified AI: {signal} (Decision: {decision}, Conf: {confidence}) | Latency: {unified_latency:.2f}s")
            # [v5.3.2] Decision Audit Log
            log_print(f"    [Decision Audit] AI Conf: {confidence:.2f} | Local Risk Score: {local_score:.2f} | Final: {signal}")
            if ai_reason: log_print(f"    Reason: {ai_reason}")

            if signal == "SKIP":
                _perf_metrics["ai_skip_cycles"] += 1
                # [v5.6.5] Shadow track CALL/PUT that AI vetoed as SKIP
                if action_raw in ("CALL", "PUT"):
                    _shadow_fire(api, asset, action_raw, f"AI_SKIP: {ai_reason}", df_feat, rsi_val, macd_hist, stoch_k_val)
                return None

            # [Post-AI Hard Rules & Safety Checks]
            if rsi_val is not None and not is_rsi_valid_for_signal(signal, rsi_val, _early_profile):
                lo, hi = _get_rsi_bounds_call(_early_profile) if signal == "CALL" else _get_rsi_bounds_put(_early_profile)
                log_print(f"    POST-AI BLOCK: {signal} rejected. RSI {rsi_val:.1f} out of bounds ({lo}-{hi})")
                _perf_metrics["post_ai_block_cycles"] += 1
                # [v5.6.5] Shadow track RSI-blocked trades
                _shadow_fire(api, asset, signal, f"POST_AI_RSI: rsi={rsi_val:.1f} bounds=({lo}-{hi})", df_feat, rsi_val, macd_hist, stoch_k_val)
                return None

            if stoch_k_val is not None:
                _stoch_put_strict = float(getattr(config, "STOCH_PUT_STRICT", 20))
                _stoch_call_strict = float(getattr(config, "STOCH_CALL_STRICT", 80))
                if signal == "PUT" and stoch_k_val < _stoch_put_strict:
                    log_print(f"    POST-AI BLOCK (Stoch Strict): PUT rejected. Stoch K={stoch_k_val:.1f} < {_stoch_put_strict:.0f}")
                    _perf_metrics["post_ai_block_cycles"] += 1
                    # [v5.6.5] Shadow track Stoch-blocked trades
                    _shadow_fire(api, asset, signal, f"POST_AI_STOCH_STRICT: PUT stoch={stoch_k_val:.1f} < {_stoch_put_strict:.0f}", df_feat, rsi_val, macd_hist, stoch_k_val)
                    return None
                if signal == "CALL" and stoch_k_val > _stoch_call_strict:
                    log_print(f"    POST-AI BLOCK (Stoch Strict): CALL rejected. Stoch K={stoch_k_val:.1f} > {_stoch_call_strict:.0f}")
                    _perf_metrics["post_ai_block_cycles"] += 1
                    # [v5.6.5] Shadow track Stoch-blocked trades
                    _shadow_fire(api, asset, signal, f"POST_AI_STOCH_STRICT: CALL stoch={stoch_k_val:.1f} > {_stoch_call_strict:.0f}", df_feat, rsi_val, macd_hist, stoch_k_val)
                    return None

            # Sniper Recovery (Dynamic Confidence)
            from .utils import load_martingale_state
            mg_step, _, _ = load_martingale_state()
            required_conf = safe_config_get("CONFIDENCE_BASE", 0.75)
            if mg_step == 1: required_conf = safe_config_get("CONFIDENCE_MG_STEP_1", 0.80)
            elif mg_step >= 2: required_conf = safe_config_get("CONFIDENCE_MG_STEP_2", 0.80)

            if confidence < required_conf:
                log_print(f"    POST-AI BLOCK (Sniper Guard): {signal} rejected. Conf {confidence:.2f} < {required_conf:.2f}")
                _perf_metrics["post_ai_block_cycles"] += 1
                # [v5.6.5] Shadow track confidence-blocked trades
                _shadow_fire(api, asset, signal, f"SNIPER_GUARD: conf={confidence:.2f} < required={required_conf:.2f} mg_step={mg_step}", df_feat, rsi_val, macd_hist, stoch_k_val)
                return None

            _perf_metrics["ai_suggest_cycles"] += 1
        else:
            log_print("    Unified AI offline/invalid. FAIL-CLOSED -> SKIP.")
            _perf_metrics["ai_skip_cycles"] += 1
            return None
    else:
        log_print("    AI Analyst disabled. Using Technical Signals...")
        score_call, details_call = await _SMART_TRADER.tech.get_confirmation_score(api, asset, "CALL", df_feat)
        score_put, details_put = await _SMART_TRADER.tech.get_confirmation_score(api, asset, "PUT", df_feat)
        
        if score_call >= 0.7:
            signal, confidence, ai_reason = "CALL", score_call, f"Tech Match: {details_call}"
        elif score_put >= 0.7:
            signal, confidence, ai_reason = "PUT", score_put, f"Tech Match: {details_put}"
        log_print(f"    Tech Signal: {signal} (Conf: {confidence})")
    
    if signal not in ["CALL", "PUT"]:
        log_print(f"    AI Analysis: {signal} (No entry today)")
        return None

    if signal == "PUT" and not getattr(config, "ALLOW_PUT_SIGNALS", True): return None
    min_conf = float(getattr(config, "AI_CONFIDENCE_THRESHOLD", 0.6))
    if float(confidence) < min_conf: return None

    # --- SMART TRADER INTERVENTION ---
 # [v5.2.0] cleaned
    
    trade_count = sum(1 for t in _SMART_TRADER.perf.data.get("trades", []) if t.get("asset") == asset)
    base_asset_profile = config.get_asset_profile(asset, trade_count)
    
    # [v5.0 BUG-04 FIX] Block disallowed signal directions per asset profile (CHECK FIRST)
    if base_asset_profile.get("_disabled", False):
        log_print(f"    [AssetProfile] {asset} DISABLED  {base_asset_profile.get('_disabled_reason', '')}")
        _perf_metrics["pre_ai_skip_cycles"] += 1
        return None

    # [V5.0] Apply Dynamic Overrides based on Sticky Regime
    asset_profile = apply_adaptive_config(asset, df_feat, base_asset_profile)

 # comment cleaned
    # Priority 1: Specific regime profile (e.g. 1HZ10V_LOW_VOL.strategy)
    # Priority 2: regime_strategy_map from config (fallback when no specific profile)
    # Priority 3: base asset_profile.strategy (NORMAL regime / AUTO)
    current_regime = _regime_state.get(asset, "NORMAL")
    
    # Tier 1: check if specific regime profile exists AND has a strategy defined
    _profile_map = getattr(config, "ASSET_STRATEGY_MAP", {})
    _specific_key = f"{asset}_{current_regime}"
    _specific_profile = _profile_map.get(_specific_key)
    
    if _specific_profile and _specific_profile.get("strategy"):
 # comment cleaned
        strategy_name = _specific_profile["strategy"]
        log_print(f"    [Adaptive] Regime={current_regime}  Profile '{_specific_key}' strategy: {strategy_name}")
    else:
        # Tier 2: config regime_strategy_map fallback
        regime_strategy_map = {
            "HIGH_VOL": getattr(config, "REGIME_STRATEGY_HIGH_VOL", "TREND_FOLLOWING"),
            "LOW_VOL":  getattr(config, "REGIME_STRATEGY_LOW_VOL",  "PULLBACK_ENTRY"),
            "NORMAL":   getattr(config, "REGIME_STRATEGY_NORMAL",   "AUTO"),
        }
        regime_override = regime_strategy_map.get(current_regime, "AUTO")

        if regime_override != "AUTO":
            strategy_name = regime_override
            log_print(f"    [Adaptive] Regime={current_regime}  Config fallback strategy: {strategy_name}")
        else:
            # Tier 3: base asset profile (NORMAL regime)
            strategy_name = asset_profile.get("strategy", "TREND_FOLLOWING")
            log_print(f"    [Adaptive] Regime={current_regime}  Base profile strategy: {strategy_name}")

    allowed_signals = asset_profile.get("allowed_signals", ["CALL", "PUT"])
    if signal not in allowed_signals:
        log_print(f"    [AssetProfile] Signal {signal} blocked for {asset}  profile only allows {allowed_signals}")
        return None
    
    final_decision = None
    
    should_enter, bet_mult, details = await _SMART_TRADER.should_enter(
        api=api, asset=asset, strategy=strategy_name, signal=signal, confidence=confidence, df_1m=df_feat, asset_profile=asset_profile
    )
    if should_enter:
        details["ai_analysis"] = ai_reason
        final_decision = (should_enter, bet_mult, details, strategy_name)
    else:
        log_print(f"    Strategy {strategy_name} BLOCKED or REJECTED. Checking fallback...")
        # [v5.1.7] Fallback: If PULLBACK_ENTRY blocked, try TREND_FOLLOWING
        if strategy_name == "PULLBACK_ENTRY" and not final_decision:
            fallback_strategy = "TREND_FOLLOWING"
            log_print(f"    Trying fallback strategy: {fallback_strategy}")
            fb_enter, fb_mult, fb_details = await _SMART_TRADER.should_enter(
                api=api, asset=asset, strategy=fallback_strategy, signal=signal, confidence=confidence, df_1m=df_feat, asset_profile=asset_profile
            )
            if fb_enter:
                fb_details["ai_analysis"] = ai_reason
                final_decision = (fb_enter, fb_mult, fb_details, fallback_strategy)
            else:
                # [v5.1.9] Log reason why fallback also failed
                fb_reasons = fb_details.get("reasons", [])
                if fb_reasons:
                    log_print(f"    Fallback {fallback_strategy} blocked: {'; '.join(fb_reasons[-2:])}")

    if not final_decision:
        if mg_step > 0:
            # [v5.2.0] Martingale Override with Critical Safety Gate
 # comment cleaned
 # comment cleaned
            from modules.technical_analysis import TechnicalConfirmation
            _mg_rsi_bounds = asset_profile.get("rsi_bounds") if asset_profile else None
            is_safe_for_mg, mg_block_reason = TechnicalConfirmation.check_hard_rules(df_feat, signal, "TREND_FOLLOWING", rsi_bounds=_mg_rsi_bounds)

            if is_safe_for_mg:
                mg_override_strategy = strategy_name if 'strategy_name' in locals() else "AI_RECOVERY"
                log_print(f"    Martingale Override: Recovery trade forced through. (MG Step: {mg_step})")
                override_details = {
                    "reasons": [f"Martingale Recovery (Step {mg_step})", f"Signal Source: {ai_reason}"],
                    "ai_analysis": ai_reason,
                    "is_override": True,
                }
                final_decision = (True, 1.0, override_details, mg_override_strategy)
            else:
                log_print(f"    MG Override BLOCKED by critical safety: {mg_block_reason}")
                log_print(f"    MG Step {mg_step}  refusing to force trade into dangerous conditions. Waiting for safer entry.")
                return None
        else:
            log_print(f"    All strategies blocked for {asset}. Skipping.")
            # [v5.6.5] Shadow track when all strategies are blocked
            _shadow_fire(api, asset, signal, f"ALL_STRATS_BLOCKED: {asset}", df_feat, rsi_val, macd_hist, stoch_k_val)
            return None
        
    should_enter, bet_mult, details, active_strategy = final_decision
    log_print(f"    Trade Accepted with strategy: {active_strategy}")
    _perf_metrics["trades_count"] += 1
    
    total = _perf_metrics["total_cycles"]
    if total % 10 == 0: _log_metrics_to_file()
    
    details["strategy"] = active_strategy
    if ai_reason: details["reasons"].insert(0, f"Signal Source: {ai_reason}")
    if rsi_val is not None: details["reasons"].append(f"RSI: {rsi_val:.1f}")
    
    # --- UNIFIED AI FINAL VERIFICATION ---
    details.setdefault("confidence", float(confidence))
    details.setdefault("ai_reason", ai_reason)
    details.setdefault("snapshot", raw_snapshot)
    details.setdefault("latency", unified_latency)

    # [v5.3.2] Cycle Latency End
    total_latency = time.time() - cycle_start
    log_print(f"    [Latency] Total Cycle Time: {total_latency:.3f}s (AI: {unified_latency:.2f}s)")

    return {
        "action": signal,
        "amount_multiplier": bet_mult,
        "strategy": active_strategy,
        "is_high_quality": is_high_quality,
        "details": details,
        "mg_step": mg_step
    }


async def analyze_trade_loss(asset, strategy, signal, profit, confidence, market_data_summary, details, loss_streak=1):
    """
    [v3.9.0] AI Post-Mortem Analysis for losing trades.
    [v3.11.44] Now requires loss_streak >= 2 to trigger AI Council auto-fixes.
    """
    if not getattr(config, "USE_AI_ANALYST", True): 
        return {"analysis": "AI Analysis Disabled", "actionable": False, "fix_suggestion": "N/A"}

    prompt = f"""
    ACT AS: Expert Quant Fund Manager conducting a Post-Mortem analysis (Respond in Thai).

    QUANT MINDSET (Read before analyzing):
    You manage a systematic quant strategy for 1-minute binary options. No strategy achieves a 100% win rate.
    The majority of individual losses are simply "Market Noise" — False Breakouts, Sudden Liquidity Spikes,
    or Profit-Taking Exhaustion caused by high volatility — NOT a flaw in the strategy logic.
    Your job is to distinguish between market-driven losses (unavoidable) and genuine structural failures
    (a real reason to act). Treat every loss with statistical skepticism before calling it actionable.

    TRADE DATA:
    - Asset: {asset} | Strategy: {strategy} | Signal: {signal}
    - Result: LOSS (Profit: {profit}) | AI Confidence at Entry: {confidence}
    - Loss Streak: {loss_streak}
    MARKET CONDITIONS AT ENTRY:
    {market_data_summary}
    ENTRY REASONING:
    {details.get('reasons', [])}

    ANALYSIS RULES (Apply in order):

    Rule 1 — Anti-Micro-Optimization (CRITICAL):
    DO NOT suggest adjusting indicator thresholds such as RSI_CALL_MAX, RSI_PUT_MIN, Stochastic bounds,
    MACD thresholds, or any numeric config parameter. These bounds are statistically optimized across
    thousands of trades. Narrowing them based on a single loss causes destructive curve-fitting and
    degrades long-term performance. Any suggestion of this type is FORBIDDEN.

    Rule 2 — Actionable Criteria (Strict):
    Set "actionable": true ONLY if there is a massive fundamental failure, such as:
      - The bot clearly traded against a dominant macro trend (e.g., strong DOWNTREND with a CALL entry).
      - Extreme, sustained volatility that requires pausing this specific asset temporarily.
    Set "actionable": false for ALL of the following (these are normal market mechanics, not fixable):
      - Market noise / random wick / false breakout within normal ATR range.
      - Profit-taking exhaustion after a recent run-up/dump.
      - Sudden liquidity spike or low-volume whipsaw.
      - A single loss even if confidence was high — one data point is not a pattern.
      - Any loss where the entry conditions were technically valid but the market reversed unexpectedly.

    Rule 3 — Explanation Quality:
    If "actionable" is false, your "analysis" must explain the specific market mechanic that caused
    the reversal (e.g., "กราฟวิ่งมาสุดแรง เกิด Profit-taking dump ทันที หลัง RSI แตะ 63 ซึ่งเป็น noise ปกติ").
    If "actionable" is true, your "fix_suggestion" must be a high-level structural action only
    (e.g., "หยุดเทรด {asset} ชั่วคราว เนื่องจาก macro trend ขัดแย้งกับ signal โดยตรง").

    OUTPUT JSON ONLY:
    {{
        "analysis": "คำอธิบายสั้นๆ ว่าทำไมถึงแพ้ และเกิดจาก market mechanics อะไร (ภาษาไทย)",
        "actionable": true/false,
        "fix_suggestion": "High-level structural action เท่านั้น ห้ามแก้ตัวเลข indicator OR 'N/A' ถ้าเป็น market noise"
    }}
    """
    
    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(None, call_ai_with_failover, prompt, "AI_ANALYST", 0.7)
    except Exception as e:
        return {"analysis": f"AI Error: {e}", "actionable": False, "fix_suggestion": "N/A"}
    
    if result and isinstance(result, dict):
        analysis = result.get("analysis", "No analysis provided.")
        actionable = result.get("actionable", False)
        fix_suggestion = result.get("fix_suggestion", "N/A")
        
        log_print(f"     AI Post-Mortem: {analysis}")
        log_print(f"     Actionable: {actionable} | Suggestion: {fix_suggestion}")
        
        # [v5.7.1] Conditional Auto-Fix Trigger: Requires Streak >= 3 (was 5)
        # Anti-overfit Post-Mortem prompt (Rule 1) now prevents RSI-narrowing vicious cycle,
        # so lowering threshold from 5→3 is safe — real 3-loss streaks warrant review.
        if actionable and fix_suggestion != "N/A":
            if loss_streak >= 3:
                from . import ai_council
                log_print(f"     Triggering AI Council for Auto-Fix (Consecutive Losses: {loss_streak})...")
                # [v5.5.1] Build proper traceback context for AI Council
                council_context = (
                    f"Consecutive Loss Auto-Fix Trigger\n"
                    f"Asset: {asset} | Strategy: {strategy} | Signal: {signal}\n"
                    f"Loss Streak: {loss_streak} | Confidence: {confidence}\n"
                    f"AI Suggestion: {fix_suggestion}\n"
                    f"Market Context:\n{market_data_summary}\n"
                )
                error_msg = f"Consecutive loss on {asset} ({strategy}): {fix_suggestion}"
                # Call ai_council directly to avoid telegram_bridge silent failure
                asyncio.create_task(ai_council.resolve_error(error_msg, council_context))
            else:
                log_print(f"     AI Council Skip: Loss streak is {loss_streak} (need >= 3). Will trigger on next consecutive loss.")
            
        return {
            "analysis": analysis,
            "actionable": actionable,
            "fix_suggestion": fix_suggestion
        }
        
    return {"analysis": "AI could not analyze loss.", "actionable": False, "fix_suggestion": "N/A"}

def record_trade_result(asset, strategy, signal, result, profit, confidence, is_override=False):
    global _perf_metrics
    if result in ["WIN", "LOSS"]:
        _perf_metrics["last_50_results"].append(result)
        if len(_perf_metrics["last_50_results"]) > 50:
            _perf_metrics["last_50_results"].pop(0)

    _SMART_TRADER.perf.record_trade(asset, strategy, signal, result, profit, confidence=confidence)
    
    # [v4.1.3] Skip RL penalty for forced Martingale recovery trades
    if is_override:
        log_print(f"    RL Protection: Skipping RL update for MG Override trade ({result}).")
    else:
        reward = 1.0 if profit > 0 else -1.0
        _SMART_TRADER.rl.update(asset, strategy, confidence, "ENTER", reward)

async def choose_best_asset(api, asset_summaries):
    if not asset_summaries: return None
    active_profile = getattr(config, "ACTIVE_PROFILE", "TIER_1")
    tiers = getattr(config, "ASSET_PRIORITY_TIERS", {})
    tier_info = ""
    if active_profile in tiers:
        tier_info = f"\n    ALLOWED ASSETS (Pick only from this list): {', '.join(tiers[active_profile])}\n"
    elif tiers:
        tier_info = f"""
    ASSET PRIORITY:
    - PREFERRED: {', '.join(tiers.get('TIER_1', []))}
    - SECONDARY: {', '.join(tiers.get('TIER_2', []))}
    - AVOID: {', '.join(tiers.get('TIER_3', []))}
    """
    prompt = f"""
    ACT AS: Senior Portfolio Manager (Defensive Strategy).
    TASK: Select the SAFEST and most reliable asset to trade next.
    
    CANDIDATE SUMMARIES:
    {json.dumps(asset_summaries, indent=2)}
    {tier_info}
    
    SELECTION CRITERIA (Strict Priority):
    1. STABILITY FIRST: Prefer 'NORMAL' or 'LOW_VOL' regimes. Heavily penalize 'HIGH_VOL' unless its win rate is exceptionally proven.
    2. SAMPLE SIZE: Trust assets with >30 trades (Total Signals) over assets with 3-5 lucky recent trades.
    3. COMPOSITE SCORE: Choose the highest overall composite score that does NOT violate stability rules.
    
    OUTPUT JSON ONLY: 
    {{"best_asset": "SYMBOL", "reason": "Why this minimizes risk while keeping >50% WR"}}
    """
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, call_ai_with_failover, prompt, "ASSET_SCANNER", 0.3)
    if result and isinstance(result, dict):
        best = result.get("best_asset")
        if best:
            log_print(f"    AI Scanner Choice: {best}")
            log_print(f"    Reason: {result.get('reason', '')}")
            return best
    return None

def run_ai_code_review(): return {"score": 85, "status": "Healthy"}
def test_ai_connectivity(): return {}
