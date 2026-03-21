"""
📈 Technical Analysis Module (v4.0.1)
Handles MACD, Stochastic, RSI, ATR, and Multi-Timeframe Analysis.
[v3.5.2] Added Hard Rules (Check Blocks) to prevent Reversal/Momentum losses.
[v4.0.1] Fixed import portability for standalone/package execution.
"""

import time
import numpy as np
import pandas as pd
import config

# [v3.11.31] Robust config/module access (prevents ImportErrors in different contexts)
try:
    from .utils import safe_config_get
    from . import market_engine
except (ImportError, ValueError):
    # Fallback for non-package execution contexts (like unit tests running as scripts)
    def safe_config_get(key, default=None):
        return getattr(config, key, default)
    try:
        import market_engine
    except ImportError:
        # If absolute import fails, try relative to root if we are in a subdirectory
        import sys
        import os
        sys.path.append(os.path.dirname(os.path.abspath(__file__)))
        import market_engine

class TechnicalConfirmation:
    """Multi-timeframe analysis and advanced indicators for trade confirmation."""

    # [v5.6.7] MACD Exhaustion Cooldown state: {"{asset}_{signal}": expiry_timestamp}
    _exhaustion_cooldowns: dict = {}

    @staticmethod
    def get_macd(df, fast=12, slow=26, signal_period=9):
        if df is None or len(df) < slow + signal_period: return None, None, None
        close = df["close"]
        ema_fast = close.ewm(span=fast, adjust=False).mean()
        ema_slow = close.ewm(span=slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal_period, adjust=False).mean()
        histogram = macd_line - signal_line
        return macd_line.iloc[-1], signal_line.iloc[-1], histogram.iloc[-1]

    @staticmethod
    def get_stochastic(df, k_period=14, d_period=3):
        if df is None or len(df) < k_period + d_period: return None, None
        low, high, close = df["low"], df["high"], df["close"]
        lowest = low.rolling(window=k_period).min()
        highest = high.rolling(window=k_period).max()
        denom = (highest - lowest).replace(0, np.nan)
        k = 100 * (close - lowest) / denom
        d = k.rolling(window=d_period).mean()
        return k.iloc[-1], d.iloc[-1]

    @staticmethod
    def detect_candle_pattern(df):
        if df is None or len(df) < 3: return None
        c2, c3 = df.iloc[-2], df.iloc[-1]
        patterns = []
        c2_body, c3_body = c2["close"] - c2["open"], c3["close"] - c3["open"]
        
        # Engulfing
        if c2_body < 0 and c3_body > 0:
            if c3["open"] <= c2["close"] and c3["close"] >= c2["open"]:
                patterns.append(("BULLISH_ENGULFING", "CALL"))
        if c2_body > 0 and c3_body < 0:
            if c3["open"] >= c2["close"] and c3["close"] <= c2["open"]:
                patterns.append(("BEARISH_ENGULFING", "PUT"))
        
        # Pinbar / Hammer / Shooting Star
        body_size = abs(c3_body)
        total_range = c3["high"] - c3["low"]
        if total_range > 0 and body_size > 0:
            lower_wick = min(c3["open"], c3["close"]) - c3["low"]
            upper_wick = c3["high"] - max(c3["open"], c3["close"])
            
            # Hammer (Bullish Pinbar)
            if lower_wick > 2 * body_size and upper_wick < body_size:
                patterns.append(("HAMMER", "CALL"))
            # Shooting Star (Bearish Pinbar)
            if upper_wick > 2 * body_size and lower_wick < body_size:
                patterns.append(("SHOOTING_STAR", "PUT"))
                
        return patterns if patterns else None

    @staticmethod
    async def check_multi_timeframe(api, asset, signal):
        """
        Check 5m timeframe for trend alignment.
        Uses Price Action & SMA alignment to define trend.
        """
        try:
            # [v3.5.7] Fixed: params were swapped (count=300, gran=50 → count=50, gran=300)
            df_5m = await market_engine.get_candles_df(api, asset.replace("-OTC","-op").replace("-op",""), 50, 300)
            if df_5m is None or len(df_5m) < 20: 
                return True, "UNKNOWN", "Not enough 5m data"
            
            sma5 = df_5m["close"].rolling(5).mean().iloc[-1]
            sma10 = df_5m["close"].rolling(10).mean().iloc[-1]
            price = df_5m["close"].iloc[-1]
            
            # Trend Definition
            if price > sma5 > sma10: 
                htf = "UPTREND"
            elif price < sma5 < sma10: 
                htf = "DOWNTREND"
            else: 
                htf = "SIDEWAYS"
            
            # Conflict Check
            if signal.upper() == "CALL":
                if htf == "DOWNTREND":
                    return False, htf, f"5m DOWNTREND vs CALL"
                if htf == "UPTREND":
                    return True, htf, f"5m UPTREND aligns"
            
            if signal.upper() == "PUT":
                if htf == "UPTREND":
                    return False, htf, f"5m UPTREND vs PUT"
                if htf == "DOWNTREND":
                    return True, htf, f"5m DOWNTREND aligns"
            
            return True, htf, f"5m {htf} (Neutral)"
            
        except Exception as e: 
            return True, "ERROR", f"MTF error: {e}"

    @staticmethod
    def get_regime_label(df_segment):
        """
        [v3.11.41] Calculates a single regime label for the provided dataframe segment.
        Consistent with ai_engine.py slope logic.
        """
        if df_segment is None or len(df_segment) < 7:
            return "SIDEWAYS"
            
        sma = df_segment["close"].rolling(7).mean()
        slope_threshold = safe_config_get("MA_SLOPE_THRESHOLD_PCT", 0.03)
        
        if len(sma) >= 6:
            curr_ma = sma.iloc[-1]
            prev_ma = sma.iloc[-6]
            if pd.notna(curr_ma) and pd.notna(prev_ma) and prev_ma > 0:
                slope = (curr_ma - prev_ma) / prev_ma * 100
                if slope > slope_threshold: return "UPTREND"
                if slope < -slope_threshold: return "DOWNTREND"
        return "SIDEWAYS"

    @staticmethod
    def calculate_regime_stability(df, window=10, max_flips=2):
        """
        [v3.11.41] Evaluates regime stability over a window of candles.
        Optimized: Calculates SMA once for the entire dataframe.
        """
        if df is None or len(df) < window + 12: # Need enough for 7-MA + slope [5 bars]
            return False, 0, []
            
        # 1. Calculate SMA for the entire dataframe
        sma = df["close"].rolling(7).mean()
        slope_threshold = safe_config_get("MA_SLOPE_THRESHOLD_PCT", 0.03)
        
        labels = []
        # Calculate labels for the last 'window' positions
        for i in range(len(df) - window, len(df)):
            curr_ma = sma.iloc[i]
            prev_ma = sma.iloc[i-5] if i >= 5 else 0
            
            label = "SIDEWAYS"
            if pd.notna(curr_ma) and pd.notna(prev_ma) and prev_ma > 0:
                slope = (curr_ma - prev_ma) / prev_ma * 100
                if slope > slope_threshold: label = "UPTREND"
                elif slope < -slope_threshold: label = "DOWNTREND"
            labels.append(label)
            
        # Count flips
        flips = 0
        for i in range(1, len(labels)):
            if labels[i] != labels[i-1]:
                flips += 1
                
        is_choppy = flips > max_flips
        return is_choppy, flips, labels

    @staticmethod
    def get_rsi(df, period=14):
        """Calculate Relative Strength Index (RSI)."""
        if df is None or len(df) < period + 1: return None
        
        delta = df["close"].diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        
        avg_gain = gain.rolling(window=period).mean()
        avg_loss = loss.rolling(window=period).mean()
        
        rs = avg_gain / avg_loss.replace(0, 0.0000001) 
        rsi = 100 - (100 / (1 + rs))
        rsi = rsi.fillna(50) 
        return rsi.iloc[-1]

    @staticmethod
    def get_adx(df, window=14):
        """
        [v5.8.0] Calculate Average Directional Index (ADX) using Wilder's Smoothing.
        Formula: RMA = (Current + (N-1) * PrevRMA) / N.
        """
        if df is None or len(df) < window * 2: return 0.0
        try:
            high = df['high']
            low = df['low']
            close = df['close']
            
            # --- Wilder's Directional Movement ---
            plus_dm_raw = high.diff()
            minus_dm_raw = low.shift(1) - low
            
            plus_dm = plus_dm_raw.where((plus_dm_raw > minus_dm_raw) & (plus_dm_raw > 0), 0.0)
            minus_dm = minus_dm_raw.where((minus_dm_raw > plus_dm_raw) & (minus_dm_raw > 0), 0.0)
            
            # --- True Range ---
            tr = pd.concat([
                (high - low),
                (high - close.shift(1)).abs(),
                (low - close.shift(1)).abs()
            ], axis=1).max(axis=1)
            
            # Wilder's Smoothing Calculation (RMA)
            # Alpha for Wilder's is 1/window. RMAs start with SMA of the first 'window' periods.
            def wilders_ewm(series, n):
                if len(series) < n: return series
                # standard EWM(1/N, adjust=False) is functionally equivalent to RMA
                return series.ewm(alpha=1.0/n, adjust=False).mean()

            tr_s = wilders_ewm(tr, window)
            plus_dm_s = wilders_ewm(plus_dm, window)
            minus_dm_s = wilders_ewm(minus_dm, window)
            
            plus_di = 100 * (plus_dm_s / tr_s.replace(0, 0.00001))
            minus_di = 100 * (minus_dm_s / tr_s.replace(0, 0.00001))
            
            # --- ADX ---
            dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, 0.00001)
            adx_series = dx.iloc[window-1:].ewm(alpha=1.0/window, adjust=False).mean()
            
            if adx_series is None or adx_series.empty: return 0.0
            val = adx_series.iloc[-1]
            return float(val) if pd.notna(val) else 0.0
        except Exception:
            return 0.0

    @staticmethod
    def get_ema(df, period=20):
        if df is None or len(df) < period: return None
        try:
            ema = df["close"].ewm(span=period, adjust=False).mean()
            return float(ema.iloc[-1])
        except Exception: return None

    @staticmethod
    def get_atr(df, period=14):
        """Return latest ATR(period)."""
        if df is None or len(df) < period + 1: return None
        try:
            high = df["high"].astype(float)
            low = df["low"].astype(float)
            close = df["close"].astype(float)
            prev_close = close.shift(1)

            tr = pd.concat([
                (high - low),
                (high - prev_close).abs(),
                (low - prev_close).abs()
            ], axis=1).max(axis=1)

            atr = tr.rolling(window=period).mean()
            val = atr.iloc[-1]
            return float(val) if pd.notna(val) else None
        except Exception: 
            return None

    @staticmethod
    def get_atr_ema(df, atr_period=14, ema_period=20):
        """Return 14-period ATR smoothed by a 20-period EMA, and the atr_pct."""
        if df is None or len(df) < atr_period + ema_period: return None, None
        try:
            high = df["high"].astype(float)
            low = df["low"].astype(float)
            close = df["close"].astype(float)
            prev_close = close.shift(1)

            tr = pd.concat([
                (high - low),
                (high - prev_close).abs(),
                (low - prev_close).abs()
            ], axis=1).max(axis=1)

            atr = tr.rolling(window=atr_period).mean()
            atr_ema = atr.ewm(span=ema_period, adjust=False).mean()
            
            val = atr_ema.iloc[-1]
            current_close = close.iloc[-1]
            
            atr_pct = (val / current_close) * 100 if current_close > 0 else 0.0
            
            return float(val) if pd.notna(val) else None, float(atr_pct) if pd.notna(atr_pct) else None
        except Exception: return None, None

    @staticmethod
    def get_indicator_snapshot(df):
        if df is None or len(df) < 20: pass

        rsi = TechnicalConfirmation.get_rsi(df) if df is not None else None
        ema9 = TechnicalConfirmation.get_ema(df, 9) if df is not None else None
        ema21 = TechnicalConfirmation.get_ema(df, 21) if df is not None else None
        atr14 = TechnicalConfirmation.get_atr(df, 14) if df is not None else None

        atr_pct = None
        try:
            if atr14 is not None and df is not None:
                close = float(df["close"].iloc[-1])
                if close != 0: atr_pct = float(atr14) / close
        except: atr_pct = None

        return {
            "rsi14": rsi,
            "ema9": ema9,
            "ema21": ema21,
            "atr14": atr14,
            "atr14_pct": atr_pct
        }

    @staticmethod
    def check_hard_rules(df, signal, strategy="", rsi_bounds=None, asset="", mg_step=0):
        """
        [v5.2.2] Hard safety checks to prevent Reversal/Momentum losses.
        strategy param used to skip exhaustion guard for TREND_FOLLOWING.
        rsi_bounds: dict from asset_profile (e.g. {"call_min":45,"call_max":72,...})
                    If None, falls back to legacy config.py values.
        asset: used for MACD Exhaustion Cooldown tracking (v5.6.7).
        Returns: (passed: bool, reason: str)
        """
        if df is None or len(df) < 35: return True, "Not enough data"

        # [v5.6.7] MACD Exhaustion Cooldown — Pre-flight check
        # Prevents "dead-cat bounce" second entries right after an exhaustion block.
        # Skip if in Martingale Recovery (mg_step > 0).
        if asset and signal in ("CALL", "PUT") and mg_step == 0:
            _cd_key = f"{asset}_{signal}"
            _cd_expiry = TechnicalConfirmation._exhaustion_cooldowns.get(_cd_key, 0)
            if time.time() < _cd_expiry:
                _remaining = int(_cd_expiry - time.time())
                return False, f"Hard Block: {signal} rejected. Cooling down from recent MACD Exhaustion (wait {_remaining}s) 🛑"
        
        # 1. MACD Reversal Block
        # Calculate full series to get previous value
        close = df["close"]
        ema_fast = close.ewm(span=12, adjust=False).mean()
        ema_slow = close.ewm(span=26, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        histogram = macd_line - signal_line
        
        hist_now = histogram.iloc[-1]
        hist_prev = histogram.iloc[-2]
        
        # [v5.6.5] MACD Contradiction Rule (Strong momentum in opposite direction)
        if signal == "CALL" and hist_now < -0.0001:
            return False, f"Hard Block: CALL rejected. MACD Contradiction ({hist_now:.4f}) 🛑"
        if signal == "PUT" and hist_now > 0.0001:
            return False, f"Hard Block: PUT rejected. MACD Contradiction ({hist_now:.4f}) 🛑"

        # Bearish Cross (Positive -> Negative)
        if hist_prev > 0 and hist_now < 0:
            if signal == "CALL": return False, "Hard Block: MACD Bearish Cross 🛑"
            
        # Bullish Cross (Negative -> Positive)
        if hist_prev < 0 and hist_now > 0:
            if signal == "PUT": return False, "Hard Block: MACD Bullish Cross 🛑"

        # [v5.8.0] MACD Momentum Exhaustion Guard (Prevent late-trend entries)
        # Skip if in Martingale Recovery to allow recovery trades.
        if safe_config_get("ENABLE_MACD_MOMENTUM_GUARD", True) and mg_step == 0:
            if signal == "CALL" and hist_now <= hist_prev:
                decay = abs(hist_prev - hist_now) / abs(hist_prev) if hist_prev != 0 else 1.0
                if decay >= 0.35:  # Only block on significant decay (35%+), not minor oscillation
                    # [v5.6.7] Set 3-minute cooldown to prevent dead-cat-bounce second entries
                    if asset:
                        TechnicalConfirmation._exhaustion_cooldowns[f"{asset}_CALL"] = time.time() + 180
                    return False, f"Hard Block: CALL rejected. MACD Exhaustion ({hist_now:.4f}, decay {decay:.0%}) 🛑"
            if signal == "PUT" and hist_now >= hist_prev:
                decay = abs(hist_now - hist_prev) / abs(hist_prev) if hist_prev != 0 else 1.0
                if decay >= 0.35:
                    # [v5.6.7] Set 3-minute cooldown to prevent dead-cat-bounce second entries
                    if asset:
                        TechnicalConfirmation._exhaustion_cooldowns[f"{asset}_PUT"] = time.time() + 180
                    return False, f"Hard Block: PUT rejected. MACD Exhaustion ({hist_now:.4f}, decay {decay:.0%}) 🛑"
        # 2. RSI Block
        rsi = TechnicalConfirmation.get_rsi(df)
        if rsi is not None and safe_config_get("ENABLE_RSI_GUARD", True):
            # [v5.2.2] Use asset_profile rsi_bounds if provided, otherwise fallback to config.py
            if rsi_bounds:
                call_min = float(rsi_bounds.get("call_min", safe_config_get("RSI_CALL_MIN", 55)))
                call_max = float(rsi_bounds.get("call_max", safe_config_get("RSI_CALL_MAX", 60)))
                put_min = float(rsi_bounds.get("put_min", safe_config_get('RSI_PUT_LOWER', 32)))
                put_max = float(rsi_bounds.get("put_max", safe_config_get('RSI_PUT_UPPER', 48)))
            else:
                call_min = float(safe_config_get("RSI_CALL_MIN", 55))
                call_max = float(safe_config_get("RSI_CALL_MAX", 60))
                put_min = float(safe_config_get('RSI_PUT_LOWER', 32))
                put_max = float(safe_config_get('RSI_PUT_UPPER', 48))
            
            # Ensure min < max for safety
            if put_min > put_max: put_min, put_max = put_max, put_min

            sig = str(signal or "").upper()

            if sig == "CALL":
                if not (call_min <= rsi <= call_max):
                    return False, f"Hard Block: RSI {rsi:.1f} not in CALL window {call_min}-{call_max} 🛑"
            elif sig == "PUT":
                if not (put_min <= rsi <= put_max):
                    return False, f"Hard Block: RSI {rsi:.1f} not in PUT window {put_min}-{put_max} 🛑"

        # 3. Dead Market
        atr = TechnicalConfirmation.get_atr(df)
        price = df['close'].iloc[-1]
        if atr and price > 0 and (atr/price < 0.0001): return False, "Hard Block: Dead Market 🛑"

        # 4. Stochastic Bounce Guard (Prevent extreme oversold/overbought entries)
        # [v5.7.5] Adapted bounds strictly for TREND_FOLLOWING to allow momentum riding
        if safe_config_get("ENABLE_STOCHASTIC_BOUNCE_GUARD", True):
            stoch_k, stoch_d = TechnicalConfirmation.get_stochastic(df)
            if stoch_k is not None:
                if strategy == "TREND_FOLLOWING":
                    ob_threshold = 95.0
                    os_threshold = 5.0
                else:
                    ob_threshold = 80.0
                    os_threshold = 20.0

                if signal == "PUT" and stoch_k < os_threshold:
                    return False, f"Hard Block: PUT rejected. Stochastic in oversold bounce zone ({stoch_k:.1f} < {os_threshold}) 🛑"
                if signal == "CALL" and stoch_k > ob_threshold:
                    return False, f"Hard Block: CALL rejected. Stochastic in overbought pullback zone ({stoch_k:.1f} > {ob_threshold}) 🛑"

        return True, "Safe"

    @staticmethod
    async def get_confirmation_score(api, asset, signal, df_1m=None):
        """
        L2: Calculate confirmation score (0.0-1.0).
        UPDATED v3.5.0: Soft RSI Penalty, ATR Filter, Strict MTF.
        [v3.11.3] Added skip MTF if api is None (for simulations).
        """
        score, factors, details = 0.0, 0, []
        try:
            # --- 0. Pre-Check: Volatility (ATR) Filter ---
            # If market is too flat (sideways), risk is high for binary options.
            if df_1m is not None and len(df_1m) >= 15:
                atr = TechnicalConfirmation.get_atr(df_1m)
                close = df_1m["close"].iloc[-1]
                if atr and close > 0:
                    atr_pct = (atr / close) * 100
                    # Threshold: 0.01% is very low volatility
                    if atr_pct < 0.01: 
                        details.append(f"ATR Too Low ({atr_pct:.4f}%) 🛑")
                        return 0.0, details
                    details.append(f"ATR: {atr_pct:.4f}%")
            # --- 1. RSI (Aligned with Deterministic Windows) ---
            if df_1m is not None and len(df_1m) >= 15:
                rsi_val = TechnicalConfirmation.get_rsi(df_1m)
                if rsi_val is not None:
                    factors += 1

                    call_min = safe_config_get("RSI_CALL_MIN", 55)
                    call_max = safe_config_get("RSI_CALL_MAX", 60)
                    
                    # [v3.11.42] New explicit keys
                    # [v5.8.0] Explicit Sniper Bounds
                    put_min = float(safe_config_get('RSI_PUT_LOWER', 32))
                    put_max = float(safe_config_get('RSI_PUT_UPPER', 48))
                    if put_min > put_max: put_min, put_max = put_max, put_min

                    sig = signal.upper()

                    if sig == "CALL":
                        if rsi_val < call_min:
                            score -= 0.5; details.append(f"RSI too weak ({rsi_val:.1f}) < {call_min} ✗")
                        elif rsi_val > call_max:
                            score -= 0.5; details.append(f"RSI overbought ({rsi_val:.1f}) > {call_max} ✗")
                        else:
                            score += 1.0; details.append(f"RSI OK ({call_min}-{call_max}) ✓")
                    elif sig == "PUT":
                        if rsi_val < put_min:
                            score -= 0.5; details.append(f"RSI too oversold ({rsi_val:.1f}) < {put_min} ✗")
                        elif rsi_val > put_max:
                            score -= 0.5; details.append(f"RSI reversal risk ({rsi_val:.1f}) > {put_max} ✗")
                        else:
                            score += 1.0; details.append(f"RSI OK ({put_min}-{put_max}) ✓")

            # --- 2. MACD ---
            if df_1m is not None and len(df_1m) >= 35:
                macd, macd_sig, hist = TechnicalConfirmation.get_macd(df_1m)
                if macd is not None:
                    factors += 1
                    if signal.upper() == "CALL" and hist > 0:
                        score += 1.0; details.append("MACD: bullish ✓")
                    elif signal.upper() == "PUT" and hist < 0:
                        score += 1.0; details.append("MACD: bearish ✓")
                    else: 
                        details.append("MACD: against ✗")

            # --- 3. Stochastic ---
            if df_1m is not None and len(df_1m) >= 17:
                k, d = TechnicalConfirmation.get_stochastic(df_1m)
                if k is not None:
                    factors += 1
                    if signal.upper() == "CALL" and k < 80 and k > d:
                        score += 1.0; details.append(f"Stoch: K>D ✓")
                    elif signal.upper() == "PUT" and k > 20 and k < d:
                        score += 1.0; details.append(f"Stoch: K<D ✓")
                    else:
                        score += 0.0; details.append(f"Stoch: neutral")

            # --- 4. Candle Pattern ---
            if df_1m is not None and len(df_1m) >= 3:
                patterns = TechnicalConfirmation.detect_candle_pattern(df_1m)
                if patterns:
                    # factors += 1  <-- Don't count as full factor, just bonus
                    matching = [p for p in patterns if p[1] == signal.upper()]
                    if matching:
                        score += 0.5; details.append(f"Candle: {matching[0][0]} (+0.5)")
                    else: 
                        # Opposing pattern is dangerous
                        score -= 0.2; details.append(f"Candle: {patterns[0][0]} vs Signal")

            # --- 5. MTF (Multi-Timeframe) - CRITICAL ---
            if api is not None:
                # AWAIT HERE
                agrees, htf, htf_detail = await TechnicalConfirmation.check_multi_timeframe(api, asset, signal)
                if htf not in ("ERROR", "UNKNOWN"):
                    factors += 1
                    if agrees:
                        score += 1.0; details.append(f"MTF: {htf} ✓")
                    else: 
                        # Penalize MTF disagreement heavily
                        score -= 0.5; details.append(f"MTF: {htf_detail} 🛑")
            else:
                # [v3.11.3] Simulation Mode: MTF is skipped to prevent network lag
                pass

            # Final Score Calculation
            final = score / factors if factors > 0 else 0.5
            
            # Sanity Check bounds
            final = max(0.0, min(1.0, final))
            
            return round(final, 2), details

        except Exception as e:
            print(f"   ⚠️ Confirmation error: {e}")
            return 0.5, [f"Error: {e}"]