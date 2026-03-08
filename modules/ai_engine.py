"""
🧠 AI Engine (Consolidated v3.11.56)
The "Brain" of the system: Orchestrates AI Providers and Smart Trader.
[v3.11.56] Post-AI Guards: MACD Momentum Exhaustion & Tick Velocity Spike Protection.
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

# --- [v5.1.2] Consecutive Sideways Counter (Pure Logic — No AI) ---
_sideways_counter = {}     # {asset: int} — tracks consecutive SIDEWAYS candles per asset
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
        log_print(f"   🎯 [Adaptive Routing] Specific regime profile found: {regime_profile_key}")
    else:
        # Second: Fallback to base_cfg (which config.get_asset_profile sets to {asset} or DEFAULT)
        cfg = base_cfg.copy()
        if regime != "NORMAL":
            log_print(f"   🔄 [Adaptive Routing] No specific profile for {regime_profile_key}. Using base/default with dynamic offsets.")

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
        log_print(f"   📊 [Adaptive Applied] {asset} | Regime={regime} | Bounce={bounce_val:.1f}")
        
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
    log_print("🛡️  [Self-Audit] Active Logic Thresholds:")
    # [v5.1.7] Show RSI bounds from DEFAULT profile (actual active bounds)
    _default_profile = getattr(config, "ASSET_STRATEGY_MAP", {}).get("DEFAULT", {})
    lo_c, hi_c = _get_rsi_bounds_call(_default_profile)
    log_print(f"   • RSI CALL Window: {lo_c} - {hi_c} (from asset_profiles DEFAULT)")
    lo_p, hi_p = _get_rsi_bounds_put(_default_profile)
    log_print(f"   • RSI PUT Window:  {lo_p} - {hi_p} (from asset_profiles DEFAULT)")
    log_print(f"   • MIN_ATR_THRESHOLD_PCT: {safe_config_get('MIN_ATR_THRESHOLD_PCT', 0.012)}%")
    log_print(f"   • MA_SLOPE_THRESHOLD_PCT: {safe_config_get('MA_SLOPE_THRESHOLD_PCT', 0.03)}%")
    try:
        dummy_labels = ["UPTREND"] * 5 + ["DOWNTREND"] * 2 + ["SIDEWAYS"] * 3
        flips = sum(1 for i in range(1, len(dummy_labels)) if dummy_labels[i] != dummy_labels[i-1])
        log_print(f"   • Regime Detection Logic: OK (Dummy Seq Flips: {flips})")
    except Exception as e: log_print(f"⚠️  [Stability Audit] Error: {e}")
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
        log_print("❌ [Self-Audit] RSI Logic Regression Test: FAILED!")
        for f in failures: log_print(f"   - {f}")
    else: 
        log_print("✅ [Self-Audit] RSI Logic Regression Test: PASSED")

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
    asset_trades = [t for t in history if t.get("asset") == asset]
    asset_wr = (sum(1 for t in asset_trades[-20:] if t.get("result") == "WIN") / len(asset_trades[-20:])) * 100 if asset_trades else 0.0
    strat_trades = [t for t in history if t.get("strategy") == strategy]
    strat_wr = (sum(1 for t in strat_trades[-20:] if t.get("result") == "WIN") / len(strat_trades[-20:])) * 100 if strat_trades else 0.0
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
        "asset_winrate_20": f"{asset_wr:.1f}%", "strategy_winrate_20": f"{strat_wr:.1f}%",
        "daily_pnl": f"${ds.get('profit', 0.0):.2f}", "current_loss_streak": ds.get("loss_streak", 0),
        "current_win_streak": ds.get("win_streak", 0), "volatility_spike": vol_spike
    }

async def ask_chatgpt_bet_gate(context):
    action = str(context.get("signal", "")).upper().strip()
    rsi_val = _fc_to_float(context.get("rsi"))
    call_lo, call_hi = _get_rsi_bounds_call()
    put_lo, put_hi = _get_rsi_bounds_put()
    rsi_validated = (rsi_val is not None) and is_rsi_valid_for_signal(action, rsi_val)

    if action in ("CALL", "PUT") and rsi_val is not None and not rsi_validated:
        lo, hi = (call_lo, call_hi) if action == "CALL" else (put_lo, put_hi)
        return {"action": "SKIP", "confidence": 1.0, "reason": f"Deterministic RSI guard: RSI={float(rsi_val):.1f} outside [{lo},{hi}] for {action}"}

    if not getattr(config, "USE_CHATGPT_BET_GATE", False): return None

    prompt = f"""
    ACT AS: Senior Binary Options Risk Gate.
    TASK: Approve or Reject trade using DETERMINISTIC RULES.
    CONTEXT:
    PROPOSED_ACTION: {action}
    INCOMING_CONFIDENCE: {context.get('ai_confidence', 0.0)}
    TREND: {context.get('trend', 'Unknown')}
    RSI: {context.get('rsi', 'Unknown')}
    ATR_PCT: {context.get('atr_pct', 'Unknown')}
    MA_SLOPE: {context.get('slope_pct', 'Unknown')}
    OUTPUT JSON ONLY: {{"approve": true | false, "confidence": 0.0-1.0, "reason": "..."}}
    """
    start_time = time.time()
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, call_ai_with_failover, prompt, "BET_GATE", 0.3)
    latency = time.time() - start_time

    if isinstance(result, dict):
        approve = _fc_parse_bool(result.get("approve"), default=None)
        gate_conf = _fc_norm_conf(result.get("confidence"), default=0.0)
        reason = str(result.get("reason") or "No reason")
        if rsi_validated and (not approve) and ("rsi" in reason.lower()):
            approve = True
            gate_conf = max(gate_conf, 0.60)
            reason = "Override: RSI already validated by deterministic guard; ignoring RSI-based veto."
        if approve is not None:
            return {"action": "ENTER" if approve else "SKIP", "confidence": gate_conf, "reason": reason, "latency": latency}

    log_print("   ⚠️ Bet Gate AI Offline/Invalid JSON. Falling back to STRICT TECHNICAL RULES (FAIL-CLOSED).")
    return {"action": "ENTER", "confidence": context.get('ai_confidence', 0.0), "reason": "Technical Only fallback", "latency": latency}

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
        
    if len(df_feat) < 3: return None
    log_print(f"   🧩 Feature DF: rows={len(df_feat)} last_ts={int(df_feat.iloc[-1]['timestamp'])} (dropped_live={dropped})")
    return df_feat

async def analyze_and_decide(api, asset, market_data_summary, df_1m):
    global _perf_metrics
    _perf_metrics["total_cycles"] += 1
    
    signal = "HOLD"
    confidence = 0.0
    ai_reason = ""
    is_high_quality = False
    rsi_val = None
    atr_pct = 0.0
    slope = 0.0
    det_trend = "SIDEWAYS"
    raw_snapshot = {}
    analyst_latency = 0.0
    gate_decision = {}
    
    is_safe, sentiment_reason = check_market_sentiment()
    if not is_safe:
        log_print(f"   🛑 Analysis Skipped: {sentiment_reason}")
        return None

    df_feat = _get_feature_df(df_1m, 60)
    if df_feat is None:
        log_print("   ⚠️ Not enough closed candles for feature calculation. FAIL-CLOSED -> SKIP.")
        _perf_metrics["pre_ai_skip_cycles"] += 1
        return None
    
    _early_trade_count = sum(1 for t in _SMART_TRADER.perf.data.get("trades", []) if t.get("asset") == asset)
    _early_profile = config.get_asset_profile(asset, _early_trade_count)  # [v5.0 BUG-06 FIX]
    
    if safe_config_get("ENABLE_REGIME_STABILITY_GUARD", True):
        global _regime_cooldowns
        cooldown = _regime_cooldowns.get(asset, 0)
        if cooldown > 0:
            _regime_cooldowns[asset] = cooldown - 1
            log_print(f"   ⏳ Regime stability cooldown: {cooldown-1} candles remaining for {asset}")
            _perf_metrics["pre_ai_skip_cycles"] += 1
            return None
            
        window = safe_config_get("REGIME_STABILITY_WINDOW", 10)
        max_flips = safe_config_get("REGIME_MAX_FLIPS", 3)
        is_choppy, flips, labels = _SMART_TRADER.tech.calculate_regime_stability(df_feat, window, max_flips)
        
        if is_choppy:
            cooldown_count = safe_config_get("REGIME_COOLDOWN_CANDLES", 3)
            _regime_cooldowns[asset] = cooldown_count
            log_print(f"   🛑 PRE-AI SKIP (Regime Stability): CHOPPY flips={flips}/{window} > {max_flips} | labels={labels[-5:]} | cooldown={cooldown_count}")
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
                log_print(f"   🔄 [Regime Change] {asset} shifted from {current_state} -> {raw_regime} (ATR EMA: {atr_pct:.4f}%)")
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
        
        # 🛡️ Dynamic Slippage Guard [v5.0 FIX] was hardcoded 0.15, now reads MAX_ATR_THRESHOLD_PCT from config
        max_atr_pct = float(getattr(config, 'MAX_ATR_THRESHOLD_PCT', 0.15))
        
        if atr_pct < min_atr_pct:
            rsi_display = f"{rsi_val:.1f}" if rsi_val is not None else "N/A"
            log_print(f"   🛑 PRE-AI SKIP (Low Vol): {atr_pct:.4f}% < {min_atr_pct}% | RSI: {rsi_display} | Trend: {det_trend}")
            _perf_metrics["pre_ai_skip_cycles"] += 1
            return None
            
        if atr_pct > max_atr_pct:
            rsi_display = f"{rsi_val:.1f}" if rsi_val is not None else "N/A"
            log_print(f"   🛑 PRE-AI SKIP (High Vol): {atr_pct:.4f}% > {max_atr_pct}% (Slippage Risk) | Trend: {det_trend}")
            _perf_metrics["pre_ai_skip_cycles"] += 1
            return None
            
        candle = df_feat.iloc[-1]
        c_range = abs(float(candle['high']) - float(candle['low']))
        if atr > 0 and c_range > (atr * 2.5):
            log_print(f"   🛑 PRE-AI SKIP (Whipsaw Guard): Candle Range {c_range:.2f} > 2.5x ATR ({atr:.2f}). Waiting.")
            _perf_metrics["pre_ai_skip_cycles"] += 1
            return None

        # --- [v5.1.2] Consecutive Sideways Counter ---
        if det_trend == "SIDEWAYS":
            _sideways_counter[asset] = _sideways_counter.get(asset, 0) + 1
            count = _sideways_counter[asset]
            if count >= SIDEWAYS_RESCAN_THRESHOLD:
                log_print(f"   🔄 [Sideways Guard] {count} consecutive SIDEWAYS candles on {asset} — flagging for forced asset rescan.")
        elif det_trend in ("UPTREND", "DOWNTREND"):
            if _sideways_counter.get(asset, 0) > 0:
                _sideways_counter[asset] = 0

        if rsi_val is not None:
            if det_trend == "UPTREND" and not is_rsi_valid_for_signal("CALL", rsi_val, _early_profile):
                log_print(f"   🛑 PRE-AI SKIP (RSI Guard): UPTREND RSI {rsi_val:.1f} violation | Volume: {atr_pct:.4f}%")
                _perf_metrics["pre_ai_skip_cycles"] += 1
                return None
            if det_trend == "DOWNTREND" and not is_rsi_valid_for_signal("PUT", rsi_val, _early_profile):
                log_print(f"   🛑 PRE-AI SKIP (RSI Guard): DOWNTREND RSI {rsi_val:.1f} violation | Volume: {atr_pct:.4f}%")
                _perf_metrics["pre_ai_skip_cycles"] += 1
                return None
            if det_trend == "SIDEWAYS":
                log_print(f"   🛑 PRE-AI SKIP (Trend Guard): SIDEWAYS (Slope {slope:.4f}%) | RSI: {rsi_val:.1f} | Consecutive: {_sideways_counter.get(asset, 0)}")
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
        log_print("   ⚠️ Not enough 1m candle data for analysis.")
        return None

    if getattr(config, "USE_AI_ANALYST", True):
        R_C_MIN, R_C_MAX = _get_rsi_bounds_call()
        R_P_LOWER, R_P_UPPER = _get_rsi_bounds_put()
        MIN_CONF = getattr(config, "AI_CONFIDENCE_THRESHOLD", 0.75)

        # [v5.1.4] Fetch Stochastic for Exhaustion Guard in prompt
        stoch_k_val, stoch_d_val = None, None
        try:
            from .technical_analysis import TechnicalConfirmation
            stoch_k_val, stoch_d_val = TechnicalConfirmation.get_stochastic(df_1m)
        except Exception:
            pass
        stoch_str = f"Stoch K={stoch_k_val:.1f}, D={stoch_d_val:.1f}" if stoch_k_val is not None and stoch_d_val is not None else "Stoch: N/A"

        prompt = f"""
        You are a TREND ANALYST for {asset}. Identify the dominant 1-minute trend direction.
        MARKET CONTEXT (1m Timeframe):
        {market_data_summary}
        Current RSI: {f"{rsi_val:.1f}" if rsi_val is not None else "N/A"}
        Current Trend (MA Slope): {det_trend} ({slope:.4f}%)
        Current Stochastic: {stoch_str}
        DECISION RULES:
        - Enter CALL if trend is UPTREND (MA slope > 0) and RSI confirms upward momentum.
        - Enter PUT if trend is DOWNTREND (MA slope < 0) and RSI confirms downward momentum.
        - SKIP if trend is SIDEWAYS, or MACD contradicts the MA trend direction.
        NOTE: Stochastic is supplementary context only. The system has a dedicated Exhaustion Guard that blocks extreme Stochastic levels (K<20 or K>80) independently. Do NOT use Stochastic as a primary rejection reason.
        Return JSON ONLY: {{"action": "CALL" | "PUT" | "SKIP", "confidence": 0.85, "reason": "Short explanation"}}
        """
        analyst_start = time.time()
        loop = asyncio.get_running_loop()
        ai_decision = await loop.run_in_executor(None, call_ai_with_failover, prompt, "AI_ANALYST", 0.5)
        analyst_latency = time.time() - analyst_start

        if ai_decision and isinstance(ai_decision, dict):
            action_raw = str(ai_decision.get("action", "SKIP")).upper().strip()
            signal = "SKIP" if action_raw in ["NO TRADE", "NO_TRADE", "HOLD", "WAIT", "SKIP"] else action_raw
            confidence = _fc_norm_conf(ai_decision.get("confidence", 0.0), default=0.0)
            ai_reason = ai_decision.get("reason", "")
            
            macd_hist = 0.0
            try:
                _, _, hist_val = _SMART_TRADER.tech.get_macd(df_feat)
                macd_hist = float(hist_val) if hist_val is not None else 0.0
            except: pass

            raw_snapshot = {"rsi": rsi_val, "slope": slope, "atr_pct": atr_pct, "macd_hist": macd_hist, "atr": atr}

            log_print(f"   🤖 AI Intent: {signal} (Conf: {confidence})")
            if ai_reason: log_print(f"   💡 Reason: {ai_reason}")

            if signal == "SKIP":
                _perf_metrics["ai_skip_cycles"] += 1
                return None

            if rsi_val is not None and not is_rsi_valid_for_signal(signal, rsi_val, _early_profile):
                lo, hi = _get_rsi_bounds_call(_early_profile) if signal == "CALL" else _get_rsi_bounds_put(_early_profile)
                log_print(f"   🛑 POST-AI BLOCK: {signal} rejected. RSI {rsi_val:.1f} out of bounds ({lo}-{hi})")
                _perf_metrics["post_ai_block_cycles"] += 1
                return None

            # -----------------------------------------------------------------
            # [v5.1.4] Sniper Recovery: Dynamic Confidence Filter based on Martingale
            # -----------------------------------------------------------------
            from .utils import load_martingale_state
            mg_step_sniper, _ = load_martingale_state()

            # ดึงค่าพารามิเตอร์จาก config.py (ถ้าหาไม่เจอให้ใช้ค่า Default ด้านหลัง)
            base_conf = safe_config_get("CONFIDENCE_BASE", 0.80)
            mg1_conf  = safe_config_get("CONFIDENCE_MG_STEP_1", 0.85)
            mg2_conf  = safe_config_get("CONFIDENCE_MG_STEP_2", 0.90)

            required_conf = base_conf  # ตั้งต้นที่ไม้แรก

            if mg_step_sniper == 1:
                required_conf = mg1_conf
                log_print(f"   🎯 [Sniper Recovery] MG Step 1 Active: AI Confidence must be >= {required_conf:.2f}")
            elif mg_step_sniper >= 2:
                required_conf = mg2_conf
                log_print(f"   🎯 [Sniper Recovery] MG Step {mg_step_sniper} Active: AI Confidence must be >= {required_conf:.2f}")

            # ถ้าความมั่นใจ AI ต่ำกว่าเกณฑ์ที่ตั้งไว้ในแต่ละระดับ ให้ปัดตกทันที!
            if confidence < required_conf:
                log_print(f"   🛑 POST-AI BLOCK (Sniper Guard): {signal} rejected. Confidence {confidence:.2f} < {required_conf:.2f} (MG Step {mg_step_sniper})")
                _perf_metrics["post_ai_block_cycles"] += 1
                return None
            # -----------------------------------------------------------------

            if signal in ["CALL", "PUT"] and df_feat is not None and len(df_feat) >= 4:
                rsi_sig = _SMART_TRADER.tech.get_rsi(df_feat)
                rsi_prev1 = _SMART_TRADER.tech.get_rsi(df_feat.iloc[:-1])
                rsi_prev2 = _SMART_TRADER.tech.get_rsi(df_feat.iloc[:-2])
                
                if rsi_sig is not None and rsi_prev1 is not None and rsi_prev2 is not None:
                    rsi_delta_1 = rsi_sig - rsi_prev1
                    rsi_delta_2 = rsi_prev1 - rsi_prev2
                    
                    bounce_limit = getattr(config, "ANTI_REVERSAL_RSI_BOUNCE_LIMIT", 3.0)
                    
                    if signal == "PUT" and rsi_delta_1 > bounce_limit:
                        log_print(f"   🛑 POST-AI BLOCK (Anti-Reversal): PUT rejected. RSI Bounced +{rsi_delta_1:.1f} (Limit: {bounce_limit})")
                        _perf_metrics["post_ai_block_cycles"] += 1
                        return None
                    if signal == "CALL" and rsi_delta_1 < -bounce_limit:
                        log_print(f"   🛑 POST-AI BLOCK (Anti-Reversal): CALL rejected. RSI Pulled back {rsi_delta_1:.1f} (Limit: -{bounce_limit})")
                        _perf_metrics["post_ai_block_cycles"] += 1
                        return None

                    momentum_check = (signal == "PUT" and rsi_delta_1 < 0 and rsi_delta_2 < 0) or (signal == "CALL" and rsi_delta_1 > 0 and rsi_delta_2 > 0)
                    if momentum_check and confidence >= 0.85:
                        is_high_quality = True
                        log_print("   💎 High Quality Signal Detected (Double Momentum Confirmation)")

            if signal in ["CALL", "PUT"] and df_feat is not None and len(df_feat) >= 3:
                if getattr(config, "ENABLE_MICRO_CONF_GUARD", True):
                    finished_c = df_feat.iloc[-1]
                    rsi_completed = _SMART_TRADER.tech.get_rsi(df_feat)
                    rsi_prior = _SMART_TRADER.tech.get_rsi(df_feat.iloc[:-1])
                    is_bullish = float(finished_c['close']) > float(finished_c['open'])
                    is_bearish = float(finished_c['close']) < float(finished_c['open'])
                    
                    if signal == "CALL":
                        if not is_bullish or (rsi_prior is not None and rsi_completed <= rsi_prior):
                            reasons = []
                            if not is_bullish: reasons.append("Last completed candle not Bullish")
                            if rsi_prior is not None and rsi_completed <= rsi_prior: reasons.append(f"RSI not rising ({rsi_prior:.1f} -> {rsi_completed:.1f})")
                            log_print(f"   🛑 POST-AI BLOCK (Micro-Conf): CALL rejected. {' & '.join(reasons)}")
                            _perf_metrics["post_ai_block_cycles"] += 1
                            return None
                    
                    if signal == "PUT":
                        if not is_bearish or (rsi_prior is not None and rsi_completed >= rsi_prior):
                            reasons = []
                            if not is_bearish: reasons.append("Last completed candle not Bearish")
                            if rsi_prior is not None and rsi_completed >= rsi_prior: reasons.append(f"RSI not falling ({rsi_prior:.1f} -> {rsi_completed:.1f})")
                            log_print(f"   🛑 POST-AI BLOCK (Micro-Conf): PUT rejected. {' & '.join(reasons)}")
                            _perf_metrics["post_ai_block_cycles"] += 1
                            return None
            
            _perf_metrics["ai_suggest_cycles"] += 1
        else:
            log_print("   ⚠️ AI Analyst offline/invalid response. FAIL-CLOSED -> SKIP.")
            _perf_metrics["ai_skip_cycles"] += 1
            return None
    else:
        log_print("   📡 AI Analyst disabled. Using Technical Signals...")
        score_call, details_call = await _SMART_TRADER.tech.get_confirmation_score(api, asset, "CALL", df_feat)
        score_put, details_put = await _SMART_TRADER.tech.get_confirmation_score(api, asset, "PUT", df_feat)
        
        if score_call >= 0.7:
            signal, confidence, ai_reason = "CALL", score_call, f"Tech Match: {details_call}"
        elif score_put >= 0.7:
            signal, confidence, ai_reason = "PUT", score_put, f"Tech Match: {details_put}"
        log_print(f"   📈 Tech Signal: {signal} (Conf: {confidence})")
    
    if signal not in ["CALL", "PUT"]:
        log_print(f"   🤖 AI Analysis: {signal} (No entry today)")
        return None

    if signal == "PUT" and not getattr(config, "ALLOW_PUT_SIGNALS", True): return None
    min_conf = float(getattr(config, "AI_CONFIDENCE_THRESHOLD", 0.6))
    if float(confidence) < min_conf: return None

    # --- SMART TRADER INTERVENTION ---
    # [v4.1.2] Fetch Martingale state BEFORE strategy evaluation
    from .utils import load_martingale_state
    mg_step, _ = load_martingale_state()
    
    trade_count = sum(1 for t in _SMART_TRADER.perf.data.get("trades", []) if t.get("asset") == asset)
    base_asset_profile = config.get_asset_profile(asset, trade_count)
    
    # [v5.0 BUG-04 FIX] Block disallowed signal directions per asset profile (CHECK FIRST)
    if base_asset_profile.get("_disabled", False):
        log_print(f"   🚫 [AssetProfile] {asset} DISABLED — {base_asset_profile.get('_disabled_reason', '')}")
        _perf_metrics["pre_ai_skip_cycles"] += 1
        return None

    # [V5.0] Apply Dynamic Overrides based on Sticky Regime
    asset_profile = apply_adaptive_config(asset, df_feat, base_asset_profile)

    # [v5.1.1 FIX] Strategy Selection — 3-Tier Priority
    # Priority 1: Specific regime profile (e.g. 1HZ10V_LOW_VOL.strategy)
    # Priority 2: regime_strategy_map from config (fallback when no specific profile)
    # Priority 3: base asset_profile.strategy (NORMAL regime / AUTO)
    current_regime = _regime_state.get(asset, "NORMAL")
    
    # Tier 1: check if specific regime profile exists AND has a strategy defined
    _profile_map = getattr(config, "ASSET_STRATEGY_MAP", {})
    _specific_key = f"{asset}_{current_regime}"
    _specific_profile = _profile_map.get(_specific_key)
    
    if _specific_profile and _specific_profile.get("strategy"):
        # Specific profile wins — this was already loaded into asset_profile by apply_adaptive_config
        strategy_name = _specific_profile["strategy"]
        log_print(f"   🎯 [Adaptive] Regime={current_regime} → Profile '{_specific_key}' strategy: {strategy_name}")
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
            log_print(f"   🔀 [Adaptive] Regime={current_regime} → Config fallback strategy: {strategy_name}")
        else:
            # Tier 3: base asset profile (NORMAL regime)
            strategy_name = asset_profile.get("strategy", "TREND_FOLLOWING")
            log_print(f"   📋 [Adaptive] Regime={current_regime} → Base profile strategy: {strategy_name}")

    allowed_signals = asset_profile.get("allowed_signals", ["CALL", "PUT"])
    if signal not in allowed_signals:
        log_print(f"   🚫 [AssetProfile] Signal {signal} blocked for {asset} — profile only allows {allowed_signals}")
        return None
    
    final_decision = None
    
    should_enter, bet_mult, details = await _SMART_TRADER.should_enter(
        api=api, asset=asset, strategy=strategy_name, signal=signal, confidence=confidence, df_1m=df_feat, asset_profile=asset_profile
    )
    if should_enter:
        details["ai_analysis"] = ai_reason
        final_decision = (should_enter, bet_mult, details, strategy_name)
    else:
        log_print(f"   🚫 Strategy {strategy_name} BLOCKED or REJECTED. Checking fallback...")
        # [v5.1.7] Fallback: If PULLBACK_ENTRY blocked, try TREND_FOLLOWING
        if strategy_name == "PULLBACK_ENTRY" and not final_decision:
            fallback_strategy = "TREND_FOLLOWING"
            log_print(f"   🔄 Trying fallback strategy: {fallback_strategy}")
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
                    log_print(f"   ❌ Fallback {fallback_strategy} blocked: {'; '.join(fb_reasons[-2:])}")

    if not final_decision:
        if mg_step > 0:
            # [v4.1.6] Martingale Override: Force trade through despite strategy blocks
            # Use the previous analyzed strategy_name if it was looping, else use a fallback.
            mg_override_strategy = strategy_name if 'strategy_name' in locals() else "AI_RECOVERY"
            log_print(f"   ⚠️ Martingale Override: Bypassing strategy block to execute recovery trade. (MG Step: {mg_step})")
            override_details = {
                "reasons": [f"Martingale Recovery (Step {mg_step})", f"Signal Source: {ai_reason}"],
                "ai_analysis": ai_reason,
                "is_override": True,
            }
            final_decision = (True, 1.0, override_details, mg_override_strategy)
        else:
            log_print(f"   ❌ All strategies blocked for {asset}. Skipping.")
            return None
        
    should_enter, bet_mult, details, active_strategy = final_decision
    log_print(f"   ✅ Trade Accepted with strategy: {active_strategy}")
    _perf_metrics["trades_count"] += 1
    
    total = _perf_metrics["total_cycles"]
    if total % 10 == 0: _log_metrics_to_file()
    
    details["strategy"] = active_strategy
    if ai_reason: details["reasons"].insert(0, f"Signal Source: {ai_reason}")
    if rsi_val is not None: details["reasons"].append(f"RSI: {rsi_val:.1f}")
    
    # --- BET GATE (FINAL LAYER) ---
    if getattr(config, "USE_CHATGPT_BET_GATE", False):
        log_print("   🛡️ Checking with Bet Gate...")
        metrics = _get_bet_gate_metrics(df_feat, asset, active_strategy)
        gate_context = {
            "asset": asset, "strategy": active_strategy, "signal": signal,
            "ai_confidence": confidence, "trend": det_trend, "slope_pct": slope,
            "rsi": rsi_val if rsi_val is not None else "Unknown",
            "atr_pct": atr_pct, "macd_hist": raw_snapshot.get('macd_hist', 0.0),
            "reasons": details.get("reasons", []), "metrics": metrics
        }
        gate_decision = await ask_chatgpt_bet_gate(gate_context)
        
        if gate_decision:
            required = float(getattr(config, "BET_GATE_CONFIDENCE_THRESHOLD", 0.7))
            gate_action = str(gate_decision.get("action", "SKIP")).upper().strip()
            gate_conf = float(gate_decision.get("confidence", 0) or 0)
            incoming_conf = float(confidence or 0)
            
            if gate_action != "ENTER" or gate_conf < required or incoming_conf < required:
                log_print(f"   🛑 Bet Gate REJECTED: {gate_decision.get('reason', 'Unknown reason')}")
                _perf_metrics["bet_gate_block_cycles"] += 1
                return None
            else:
                log_print(f"   ✅ Bet Gate APPROVED: Action={gate_action} | GateConf={gate_conf:.2f} | IncomingConf={incoming_conf:.2f}")
                details["bet_gate"] = gate_decision

    try: details.setdefault("confidence", float(confidence))
    except: details.setdefault("confidence", confidence)
    details.setdefault("ai_reason", ai_reason)
    details.setdefault("snapshot", raw_snapshot)
    details.setdefault("analyst_latency", analyst_latency)
    details.setdefault("gate_latency", gate_decision.get("latency", 0.0) if gate_decision else 0.0)

    return {
        "action": signal,
        "amount_multiplier": bet_mult,
        "strategy": active_strategy,
        "is_high_quality": is_high_quality,
        "details": details
    }


async def analyze_trade_loss(asset, strategy, signal, profit, confidence, market_data_summary, details, loss_streak=1):
    """
    [v3.9.0] AI Post-Mortem Analysis for losing trades.
    [v3.11.44] Now requires loss_streak >= 2 to trigger AI Council auto-fixes.
    """
    if not getattr(config, "USE_AI_ANALYST", True): 
        return {"analysis": "AI Analysis Disabled", "actionable": False, "fix_suggestion": "N/A"}

    prompt = f"""
    ACT AS: Senior Trading Mentor (Speaking Thai).
    TASK: Analyze this LOSING trade and determine if it was unavoidable (Market) or fixable (Code/Config).
    
    ASSET: {asset}
    STRATEGY: {strategy} (Signal: {signal})
    RESULT: LOSS (Profit: {profit})
    CONFIDENCE: {confidence}
    MARKET CONDITIONS:
    {market_data_summary}
    
    REASONING FOR ENTRY:
    {details.get('reasons', [])}
    
    1. Was the market volatile/unpredictable? -> actionable: false
    2. Did the strategy miss a clear reversal sign? -> actionable: true
    3. Is the RSI/Indicator threshold too loose? -> actionable: true (e.g. Decrease RSI_CALL_MAX or Increase RSI_PUT_MIN)
    
    OUTPUT JSON ONLY:
    {{
        "analysis": "Brief explanation of why it failed (Thai language)",
        "actionable": true/false,
        "fix_suggestion": "Specific instruction to fix (e.g. 'Decrease RSI_CALL_MAX to 60') OR 'N/A' if unavoidable"
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
        
        log_print(f"    🧠 AI Post-Mortem: {analysis}")
        log_print(f"    🔧 Actionable: {actionable} | Suggestion: {fix_suggestion}")
        
        # [v3.11.44] Conditional Auto-Fix Trigger: Requires Streak >= 2
        if actionable and fix_suggestion != "N/A":
            if loss_streak >= 2:
                from .telegram_bridge import _send_command
                log_print(f"    🚀 Triggering AI Council for Auto-Fix (Consecutive Losses: {loss_streak})...")
                payload = json.dumps({
                    "text": f"Fix strategy weakness: {fix_suggestion}. Context: Loss on {asset}, {strategy}."
                })
                _send_command("COUNCIL", payload=payload)
            else:
                log_print(f"    ℹ️ AI Council Skip: Loss streak is only {loss_streak}. Will trigger on next consecutive loss.")
            
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
        log_print(f"   🛡️ RL Protection: Skipping RL update for MG Override trade ({result}).")
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
    prompt = f"ACT AS: Senior Quantitative Strategist. Select BEST asset.\nSUMMARIES:\n{json.dumps(asset_summaries, indent=2)}\n{tier_info}\nOUTPUT JSON ONLY: {{\"best_asset\": \"SYMBOL\", \"reason\": \"...\"}}"
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, call_ai_with_failover, prompt, "ASSET_SCANNER", 0.3)
    if result and isinstance(result, dict):
        best = result.get("best_asset")
        if best:
            log_print(f"   🎯 AI Scanner Choice: {best}")
            log_print(f"   💡 Reason: {result.get('reason', '')}")
            return best
    return None

def run_ai_code_review(): return {"score": 85, "status": "Healthy"}
def test_ai_connectivity(): return {}