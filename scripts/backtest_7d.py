
import asyncio
import datetime
import os
import sys
import pandas as pd
from deriv_api import DerivAPI

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from modules.smart_trader import SmartTrader
from modules.technical_analysis import TechnicalConfirmation
from modules.utils import log_print, ROOT

# Assets to backtest
ASSETS = ["R_75", "1HZ100V", "1HZ50V"]

async def fetch_7d_data(api, asset):
    """Fetches approx 10,080 candles by batching."""
    now = datetime.datetime.now()
    end_epoch = int(now.timestamp())
    # 7 days = 10080 minutes
    start_epoch = end_epoch - (7 * 24 * 3600)
    
    all_candles = []
    current_end = end_epoch
    
    log_print(f"[Market] Fetching 7 days of data for {asset}...")
    
    # Deriv limit is 5000 per request
    batch_size = 4000 
    while current_end > start_epoch:
        try:
            resp = await api.ticks_history({
                "ticks_history": asset,
                "style": "candles",
                "granularity": 60,
                "end": current_end,
                "count": batch_size
            })
            if "error" in resp:
                log_print(f"   [Error] API Error: {resp['error']['message']}")
                break
                
            batch = resp.get("candles", [])
            if not batch:
                break
            
            all_candles = batch + all_candles
            # Move current_end to the oldest candle in this batch
            current_end = batch[0]["epoch"] - 1
            
            if len(all_candles) >= 10080:
                break
                
            log_print(f"   Collected {len(all_candles)} candles...")
            await asyncio.sleep(0.5) # Avoid rate limits
        except Exception as e:
            log_print(f"   [Error] Fetch error: {e}")
            break
            
    if not all_candles:
        return None
        
    df = pd.DataFrame(all_candles)
    # Ensure no duplicates and sorted
    df.drop_duplicates(subset=['epoch'], inplace=True)
    df.sort_values('epoch', inplace=True)
    df.reset_index(drop=True, inplace=True)
    
    for col in ['close','open','high','low']:
        df[col] = df[col].astype(float)
        
    log_print(f"   [Success] Total data points: {len(df)}")
    return df

async def run_backtest_7d():
    api = DerivAPI(app_id=config.DERIV_APP_ID)
    try:
        # Optional: Auth if needed for specific assets, but for history usually not required for public ones
        # await api.authorize(config.DERIV_API_TOKEN)
        
        st = SmartTrader()
        
        report_data = []

        for asset in ASSETS:
            df = await fetch_7d_data(api, asset)
            if df is None or len(df) < 100:
                continue
                
            log_print(f"[Backtest] Simulating V5.0 Adaptive Logic for {asset}...")
            
            trades = []
            # Local regime state for simulation
            regime_state = "NORMAL"
            regime_history = []
            
            # Start from 50 to have enough data for indicators
            for i in range(50, len(df) - 1):
                df_slice = df.iloc[:i+1]
                current_candle = df.iloc[i]
                next_candle = df.iloc[i+1]
                
                # --- V5.0 Regime Logic (Simulated) ---
                _, atr_pct = TechnicalConfirmation.get_atr_ema(df_slice, 14, 20)
                if atr_pct is None: atr_pct = 0.0
                
                if "1HZ" in asset:
                    hi_v = getattr(config, "REGIME_HIGH_VOL_THRESHOLD_1HZ", 0.140)
                    lo_v = getattr(config, "REGIME_LOW_VOL_THRESHOLD_1HZ", 0.030)
                else:
                    hi_v = getattr(config, "REGIME_HIGH_VOL_THRESHOLD_R", 0.100)
                    lo_v = getattr(config, "REGIME_LOW_VOL_THRESHOLD_R", 0.020)
                
                raw = "NORMAL"
                if atr_pct > hi_v: raw = "HIGH_VOL"
                elif atr_pct < lo_v: raw = "LOW_VOL"
                
                regime_history.append(raw)
                if len(regime_history) > 3: regime_history.pop(0)
                
                if len(regime_history) == 3 and all(h == raw for h in regime_history):
                    regime_state = raw
                
                # --- Strategy Selection ---
                base_profile = config.get_asset_profile(asset, len(trades))
                # Mock adaptive config apply
                profile = base_profile.copy()
                if "rsi_bounds" in profile:
                    bounds = profile["rsi_bounds"].copy()
                    if regime_state == "HIGH_VOL":
                        bounds["call_min"] -= 3.0
                        bounds["call_max"] += 3.0
                        bounds["put_min"] -= 3.0
                        bounds["put_max"] += 3.0
                    elif regime_state == "LOW_VOL":
                        bounds["call_min"] += 2.0
                        bounds["call_max"] -= 2.0
                        bounds["put_min"] += 2.0
                        bounds["put_max"] -= 2.0
                    profile["rsi_bounds"] = bounds

                regime_strategy_map = {
                    "HIGH_VOL": getattr(config, "REGIME_STRATEGY_HIGH_VOL", "TREND_FOLLOWING"),
                    "LOW_VOL":  getattr(config, "REGIME_STRATEGY_LOW_VOL",  "PULLBACK_ENTRY"),
                    "NORMAL":   getattr(config, "REGIME_STRATEGY_NORMAL",   "AUTO"),
                }
                strategy = regime_strategy_map.get(regime_state, "AUTO")
                if strategy == "AUTO": 
                    strategy = profile.get("strategy", "TREND_FOLLOWING")

                # --- Signal Check ---
                # Check both directions
                for direction in ["CALL", "PUT"]:
                    if direction not in profile.get("allowed_signals", ["CALL", "PUT"]):
                        continue
                        
                    # Pure Technical Trigger (Level 1)
                    score, _ = await TechnicalConfirmation.get_confirmation_score(None, asset, direction, df_slice)
                    if score >= 0.7:
                        # Full SmartTrader Check (Level 2)
                        should_enter, _, _ = await st.should_enter(None, asset, strategy, direction, confidence=score, df_1m=df_slice, asset_profile=profile)
                        
                        if should_enter:
                            entry_p = current_candle['close']
                            exit_p = next_candle['close']
                            is_win = (direction == "CALL" and exit_p > entry_p) or (direction == "PUT" and exit_p < entry_p)
                            
                            trades.append({
                                "time": datetime.datetime.fromtimestamp(current_candle['epoch']),
                                "strategy": strategy,
                                "direction": direction,
                                "regime": regime_state,
                                "result": "WIN" if is_win else "LOSS"
                            })
                            # Jump to next candle after trade
                            break 
            
            # Asset Report
            wins = sum(1 for t in trades if t["result"] == "WIN")
            total = len(trades)
            wr = (wins / total * 100) if total > 0 else 0
            
            # --- Consecutive Loss Calculation ---
            max_consecutive = 0
            current_consecutive = 0
            times_over_2 = 0
            
            for t in trades:
                if t["result"] == "LOSS":
                    current_consecutive += 1
                    if current_consecutive > max_consecutive:
                        max_consecutive = current_consecutive
                else:
                    if current_consecutive > 2:
                        times_over_2 += 1
                    current_consecutive = 0
            # Final check if last trade was part of a streak
            if current_consecutive > 2:
                times_over_2 += 1
                
            print(f"[Results] {asset} 7D Summary:")
            print(f"   Trades: {total} | Wins: {wins} | Win Rate: {wr:.2f}%")
            print(f"   Max Consecutive Losses: {max_consecutive}")
            print(f"   Times Lost > 2 in a row: {times_over_2}")
            report_data.append({"asset": asset, "trades": total, "wins": wins, "wr": wr, "max_loss": max_consecutive, "over_2": times_over_2})

        print("\n" + "="*50)
        print("FINAL 7-DAY BACKTEST SUMMARY")
        print("="*50)
        for r in report_data:
            print(f"{r['asset']:<10} | Trades: {r['trades']:<4} | Win Rate: {r['wr']:>5.1f}% | Max Loss: {r['max_loss']:<2} | Loss > 2: {r['over_2']}")
        print("="*50)

    finally:
        await api.disconnect()

if __name__ == "__main__":
    asyncio.run(run_backtest_7d())
