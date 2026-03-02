
import asyncio
import os
import datetime
import pandas as pd
from deriv_api import DerivAPI
import config
import technical_analysis

# Assets seen in trade history today
ASSETS = ["R_25", "1HZ25V", "R_75", "1HZ75V", "1HZ50V", "1HZ100V", "R_50", "1HZ10V"]
# Backtest duration: Last 24 hours (1440 minutes)
LOOKBACK_CANDLES = 1440 

async def run_backtest():
    print(f"🚀 Starting Pure Technical Backtest (Today's Data)")
    print(f"📅 Period: Last 24 Hours")
    print(f"📊 Assets: {ASSETS}")
    print("="*60)

    api = DerivAPI(app_id=config.DERIV_APP_ID)
    
    try:
        # Authorize
        auth = await api.authorize(config.DERIV_API_TOKEN)
        if "error" in auth:
            print(f"❌ Auth Failed: {auth['error']['message']}")
            return

        total_signals = 0
        total_wins = 0
        total_losses = 0
        results_by_asset = {}

        for asset in ASSETS:
            print(f"\n🔎 Analyzing {asset}...")
            
            # Fetch candles (1 minute)
            # count=LOOKBACK_CANDLES + 50 (buffer for indicators)
            candles = await api.ticks_history(
                {"ticks_history": asset, "style": "candles", "granularity": 60, "count": LOOKBACK_CANDLES + 50, "end": "latest"}
            )
            
            if "error" in candles:
                print(f"   ⚠️ Error fetching data: {candles['error']['message']}")
                continue
                
            history = candles.get("candles")
            if not history:
                print("   ⚠️ No candle data.")
                continue

            # Convert to DataFrame
            df = pd.DataFrame(history)
            df['time'] = pd.to_datetime(df['epoch'], unit='s')
            df.set_index('time', inplace=True)
            df['close'] = df['close'].astype(float)
            df['open'] = df['open'].astype(float)
            df['high'] = df['high'].astype(float)
            df['low'] = df['low'].astype(float)
            
            # Simulate Trading
            # We iterate from the 50th candle to the end-1 (to check result on next candle)
            asset_signals = 0
            asset_wins = 0
            
            # Cache for efficiency
            # We need a rolling window for technical analysis
            # To be efficient, we'll calculate indicators on the full DF first? 
            # technical_analysis module usually takes a slice. Let's just loop and slice.
            
            print(f"   Processing {len(df)} candles...")
            
            # Pre-calculate indicators on full DF to speed up? 
            # No, technical_analysis.get_confirmation_score calculates internal indicators.
            # We will adhere to the implementation: pass the recent slice.
            
            # Scan every candle (simulating per-minute check)
            for i in range(50, len(df) - 1):
                # Current slice: up to index i (inclusive)
                current_slice = df.iloc[i-50:i+1]
                future_candle = df.iloc[i+1]
                
                # Check for Signal
                # score, details = technical_analysis.get_confirmation_score(current_slice)
                # But wait, technical_analysis might be slow if we call it 1400 times per asset.
                # Let's try.
                
                # Check BOTH directions (CALL/PUT)
                # Pass api=None to skip MTF checks (too slow for loop backtest)
                # We want to see if the 1M chart indicators alone provide good signals
                
                best_signal = None
                best_score = 0.0
                
                try:
                    # Check CALL
                    score_c, _ = await technical_analysis.TechnicalConfirmation.get_confirmation_score(None, asset, "CALL", current_slice)
                    if score_c >= 0.7:
                        best_signal = "CALL"
                        best_score = score_c
                    
                    # Check PUT (if enabled)
                    if getattr(config, "ALLOW_PUT_SIGNALS", True):
                        score_p, _ = await technical_analysis.TechnicalConfirmation.get_confirmation_score(None, asset, "PUT", current_slice)
                        if score_p >= 0.7 and score_p > best_score:
                            best_signal = "PUT"
                            best_score = score_p
                            
                except Exception as e:
                    # print(f"Error: {e}")
                    continue

                if best_signal:
                    asset_signals += 1
                    
                    # Check Result (Next Candle Close vs Current Close)
                    entry_price = current_slice.iloc[-1]['close']
                    exit_price = future_candle['close']
                    
                    outcome = "LOSS"
                    if best_signal == "CALL" and exit_price > entry_price:
                        outcome = "WIN"
                    elif best_signal == "PUT" and exit_price < entry_price:
                        outcome = "WIN"
                    elif exit_price == entry_price:
                        outcome = "TIE" 
                    
                    if outcome == "WIN":
                        asset_wins += 1
                        
                    # print(f"      {current_slice.index[-1]} {best_signal} (Score {best_score:.2f}) -> {outcome}")

            total_signals += asset_signals
            total_wins += asset_wins
            total_losses += (asset_signals - asset_wins)
            
            win_rate = (asset_wins / asset_signals * 100) if asset_signals > 0 else 0
            results_by_asset[asset] = {"signals": asset_signals, "wins": asset_wins, "rate": win_rate}
            
            print(f"   👉 Signals: {asset_signals}, Wins: {asset_wins} ({win_rate:.1f}%)")

        print("\n" + "="*60)
        print("📊 SUMMARY (Pure Technical Analysis - Today)")
        print("="*60)
        print(f"Total Signals: {total_signals}")
        print(f"Total Wins:    {total_wins}")
        print(f"Total Losses:  {total_losses}")
        overall_rate = (total_wins / total_signals * 100) if total_signals > 0 else 0
        print(f"Win Rate:      {overall_rate:.2f}%")
        print("-" * 60)
        print("By Asset:")
        for asset, res in results_by_asset.items():
            print(f"  {asset:<10} : {res['signals']:3} Signals | {res['wins']:3} Wins | {res['rate']:.1f}%")
        print("="*60)
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Clean shutdown
        # DerivAPI doesn't have explicit close in some versions, but we'll let context manager handle or just exit
        await api.disconnect()

if __name__ == "__main__":
    asyncio.run(run_backtest())
