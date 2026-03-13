
import asyncio
import datetime
import time
import pandas as pd
import numpy as np
import config
from modules.smart_trader import SmartTrader
from modules.technical_analysis import TechnicalConfirmation
from modules.utils import log_print
from modules.market_engine import _FAILED_ASSETS


class AssetSelector:
    """
    [v5.1.8] Handles dynamic asset selection based on recent performance.
    Runs a mini-backtest on available assets using profile-matched strategy,
    improved WIN simulation, regime awareness, composite scoring, and recency bias.
    """

    @staticmethod
    def _detect_regime_for_scan(asset, df):
        """
        Lightweight regime detection for asset scanning.
        Mirrors ai_engine.py logic but without global state mutation.
        Returns: "NORMAL" | "HIGH_VOL" | "LOW_VOL"
        """
        if len(df) < 20:
            return "NORMAL"

        # ATR calculation (same as ai_engine.py)
        high = df['high'].astype(float)
        low = df['low'].astype(float)
        close = df['close'].astype(float)

        tr = pd.concat([
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs()
        ], axis=1).max(axis=1)

        atr_ema = tr.ewm(span=20).mean()
        if len(atr_ema) == 0 or atr_ema.iloc[-1] != atr_ema.iloc[-1]:
            return "NORMAL"

        atr_val = atr_ema.iloc[-1]
        current_close = close.iloc[-1]
        if current_close == 0:
            return "NORMAL"

        atr_pct = (atr_val / current_close) * 100

        # Use config thresholds (same as ai_engine.py)
        if "1HZ" in asset:
            high_thresh = float(getattr(config, "REGIME_HIGH_VOL_THRESHOLD_1HZ", 0.140))
            low_thresh = float(getattr(config, "REGIME_LOW_VOL_THRESHOLD_1HZ", 0.030))
        else:
            high_thresh = float(getattr(config, "REGIME_HIGH_VOL_THRESHOLD_R", 0.100))
            low_thresh = float(getattr(config, "REGIME_LOW_VOL_THRESHOLD_R", 0.020))

        if atr_pct > high_thresh:
            return "HIGH_VOL"
        elif atr_pct < low_thresh:
            return "LOW_VOL"
        return "NORMAL"

    @staticmethod
    def _calc_trend_strength(df):
        """
        Calculate trend strength score (0.0 - 1.0) from MA slope and directional consistency.
        Higher = stronger, clearer trend = better for trading.
        """
        if len(df) < 20:
            return 0.0

        close = df['close'].astype(float)
        sma7 = close.rolling(7).mean()

        if len(sma7) < 7 or sma7.iloc[-1] != sma7.iloc[-1]:
            return 0.0

        # Slope strength (0-0.5)
        current_ma = sma7.iloc[-1]
        prev_ma = sma7.iloc[-7]
        if prev_ma == 0:
            return 0.0
        slope = abs((current_ma - prev_ma) / prev_ma * 100)
        slope_score = min(slope / 0.10, 1.0) * 0.5  # 0.10% slope = max score

        # Directional consistency (0-0.5): count how many candles close in trend direction
        recent = close.iloc[-10:]
        if len(recent) < 10:
            return slope_score

        diffs = recent.diff().dropna()
        if len(diffs) == 0:
            return slope_score

        # How many candles go in the dominant direction
        pos = (diffs > 0).sum()
        neg = (diffs < 0).sum()
        consistency = max(pos, neg) / len(diffs)
        consistency_score = consistency * 0.5

        return round(slope_score + consistency_score, 4)

    @staticmethod
    async def find_best_asset(api, lookback_hours=12, min_trades=10):
        """
        [v5.1.8] Enhanced asset selection with:
        1. Profile-matched strategy (not hardcoded AI_MOMENTUM)
        2. Multi-candle WIN simulation (3-candle majority direction)
        3. Regime-aware scoring
        4. Composite score (WR + confidence + trend strength + trade volume)
        5. Recency bias (recent trades weighted 2x)

        Returns: (best_asset, win_rate, details_dict)
        """
        now = datetime.datetime.now()
        start_dt = now - datetime.timedelta(hours=lookback_hours)
        start_epoch = int(start_dt.timestamp())
        end_epoch = int(now.timestamp())

        # Recency split: last 3 hours get 2x weight
        recency_cutoff = int((now - datetime.timedelta(hours=3)).timestamp())

        candidates = []
        assets_to_scan = config.ASSETS_VOLATILITY

        log_print(f"🕵️ [Asset Selector v5.1.8] Scanning {len(assets_to_scan)} assets (Last {lookback_hours}h)...")

        for asset in assets_to_scan:
            try:
                # 0. [v5.1.1 FIX] Skip Blacklisted Assets (Cut & Run Active)
                if asset in _FAILED_ASSETS:
                    if time.time() - _FAILED_ASSETS[asset] < 3600:
                        log_print(f"   ⏭️ [Asset Selector] {asset} skipped — FAILED Blacklist cooldown.")
                        continue

                # [v5.0 FIX-A] Skip disabled assets BEFORE fetching history
                _profile_check = config.get_asset_profile(asset)
                if _profile_check.get("_disabled", False):
                    log_print(f"   ⏭️ [Asset Selector] {asset} skipped — disabled ({_profile_check.get('_disabled_reason', 'no reason')})")
                    continue

                # 1. Fetch History
                fetch_start = start_epoch - 3600
                resp = await api.ticks_history({
                    "ticks_history": asset,
                    "style": "candles",
                    "granularity": 60,
                    "start": fetch_start,
                    "end": end_epoch,
                    "count": 2000
                })

                if "error" in resp:
                    continue

                history = resp.get("candles")
                if not history:
                    continue

                df = pd.DataFrame(history)
                df['time'] = pd.to_datetime(df['epoch'], unit='s')
                df.set_index('time', inplace=True)
                for col in ['close','open','high','low']:
                    df[col] = df[col].astype(float)

                # [v5.1.8 FIX #3] Detect regime for this asset
                regime = AssetSelector._detect_regime_for_scan(asset, df)

                # [v5.1.8 FIX #1] Use profile strategy instead of hardcoded AI_MOMENTUM
                strategy = _profile_check.get("strategy", "TREND_FOLLOWING")

                # If regime-specific profile exists, use that strategy
                regime_profile_key = f"{asset}_{regime}"
                regime_profile = getattr(config, "ASSET_STRATEGY_MAP", {}).get(regime_profile_key)
                if regime_profile and not regime_profile.get("_disabled", False):
                    strategy = regime_profile.get("strategy", strategy)
                    _sim_profile = regime_profile
                else:
                    _sim_profile = _profile_check

                # 2. Run Simulation
                st = SmartTrader()
                if "strategy_stats" not in st.perf.data:
                    st.perf.data["strategy_stats"] = {}

                signals = 0
                wins = 0
                recent_signals = 0
                recent_wins = 0
                total_confidence = 0.0

                # Need at least 3 future candles for improved simulation
                for i in range(50, len(df) - 3):
                    ts = df.index[i]
                    if ts.timestamp() < start_epoch:
                        continue

                    sl = df.iloc[i-50:i+1]

                    for direction in ["CALL", "PUT"]:
                        if direction == "PUT" and not getattr(config, "ALLOW_PUT_SIGNALS", True):
                            continue

                        try:
                            score, _ = await TechnicalConfirmation.get_confirmation_score(None, asset, direction, sl)
                        except Exception:
                            continue

                        if score >= 0.7:
                            # [v5.1.8 FIX #1] Use actual profile strategy
                            should_enter, _, details = await st.should_enter(
                                None, asset, strategy, direction,
                                confidence=score, df_1m=sl,
                                asset_profile=_sim_profile,
                                verbose=False  # [v5.1.9] Suppress hard rule logs during simulation
                            )

                            if should_enter:
                                signals += 1
                                total_confidence += score

                                entry = sl.iloc[-1]['close']

                                # [v5.1.8 FIX #2] Multi-candle WIN simulation
                                # Check next 3 candles (simulates ~3min contract window)
                                # WIN = majority of candles close in predicted direction
                                future_candles = df.iloc[i+1:i+4]
                                direction_wins = 0
                                for _, fc in future_candles.iterrows():
                                    fc_close = fc['close']
                                    if direction == "CALL" and fc_close > entry:
                                        direction_wins += 1
                                    elif direction == "PUT" and fc_close < entry:
                                        direction_wins += 1

                                is_win = direction_wins >= 2  # Majority (2 out of 3)

                                if is_win:
                                    wins += 1

                                # [v5.1.8 FIX #5] Recency tracking
                                if ts.timestamp() >= recency_cutoff:
                                    recent_signals += 1
                                    if is_win:
                                        recent_wins += 1

                # 3. Calculate Stats
                wr = (wins / signals * 100) if signals > 0 else 0
                recent_wr = (recent_wins / recent_signals * 100) if recent_signals > 0 else 0
                avg_confidence = (total_confidence / signals) if signals > 0 else 0

                # [v5.1.8 FIX #3] Calculate trend strength
                trend_strength = AssetSelector._calc_trend_strength(df)

                if signals >= min_trades:
                    # [v5.1.8 FIX #4] Composite Score calculation
                    # Components:
                    #   WR (40%): Base win rate performance
                    #   Recent WR (25%): Recency-weighted performance (FIX #5)
                    #   Avg Confidence (15%): How confident are signals
                    #   Trend Strength (10%): Clarity of current trend
                    #   Trade Volume (10%): More trades = more reliable

                    # Normalize trade volume (8 trades = 0.5, 40+ = 1.0)
                    vol_score = min(signals / 100.0, 1.0)

                    # Use recent_wr if we have enough recent data, otherwise fall back to overall WR
                    effective_recent_wr = recent_wr if recent_signals >= 5 else wr

                    composite_score = (
                        (wr / 100.0) * 0.40 +
                        (effective_recent_wr / 100.0) * 0.25 +
                        avg_confidence * 0.15 +
                        trend_strength * 0.10 +
                        vol_score * 0.10
                    ) * 100  # Scale to 0-100

                    # [v5.2.2] Current Tradability Check — prevent selecting untradeable assets
                    # Check if the LATEST candle passes Hard Rules for at least one direction
                    _live_tradeable = False
                    _live_slice = df.iloc[-50:] if len(df) >= 50 else df
                    _live_rsi_bounds = _sim_profile.get("rsi_bounds", {})
                    for _dir in ["CALL", "PUT"]:
                        _dir_safe, _ = TechnicalConfirmation.check_hard_rules(
                            _live_slice, _dir, strategy, rsi_bounds=_live_rsi_bounds
                        )
                        if _dir_safe:
                            _live_tradeable = True
                            break

                    if not _live_tradeable:
                        composite_score -= 5.0  # Soft penalty — conditions change every minute

                    candidates.append({
                        "asset": asset,
                        "wr": wr,
                        "recent_wr": effective_recent_wr,
                        "trades": signals,
                        "recent_trades": recent_signals,
                        "avg_conf": avg_confidence,
                        "trend_str": trend_strength,
                        "regime": regime,
                        "strategy": strategy,
                        "composite": round(composite_score, 2),
                        "live_tradeable": _live_tradeable
                    })
                    _live_tag = "" if _live_tradeable else " | BLOCKED"
                    log_print(
                        f"   📊 {asset}: WR {wr:.1f}% ({signals}t) | "
                        f"Recent {effective_recent_wr:.1f}% ({recent_signals}t) | "
                        f"Regime: {regime} | Strategy: {strategy} | "
                        f"Composite: {composite_score:.1f}{_live_tag}"
                    )
                else:
                    pass  # Low volume, skip silently

            except Exception as e:
                log_print(f"   ⚠️ Error scanning {asset}: {e}")
                continue

        # 4. Rank Candidates
        if not candidates:
            return None, 0, "No valid assets found"

        # [v5.1.8 FIX #4] Sort by Composite Score (not just WR)
        candidates.sort(key=lambda x: x["composite"], reverse=True)
        best = candidates[0]

        log_print(
            f"   🏆 [Asset Selector] Best: {best['asset']} "
            f"(Composite: {best['composite']:.1f}, WR: {best['wr']:.1f}%, "
            f"Regime: {best['regime']}, Strategy: {best['strategy']})"
        )

        return best["asset"], best["wr"], candidates
