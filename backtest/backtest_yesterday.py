
import asyncio
import os
import datetime
import pandas as pd
from deriv_api import DerivAPI
import config
import technical_analysis

# Assets to test
ASSETS = ["1HZ100V"] # Optimized for speed

async def run_backtest():
    # 1. Calculate Yesterday's Range
    now = datetime.datetime.now()
    yesterday = now - datetime.timedelta(days=1)
    
    start_dt = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
    end_dt = yesterday.replace(hour=23, minute=59, second=59, microsecond=999999)
    
    start_epoch = int(start_dt.timestamp())
    end_epoch = int(end_dt.timestamp())
    
    print(f"🚀 Starting Backtest for YESTERDAY ({start_dt.strftime('%Y-%m-%d')})")
    print(f"⏰ Range: {start_dt} to {end_dt}")
    print(f"📊 Assets: {ASSETS}")
    print(f"🛡️  Hard Rules: {'ENABLED' if getattr(config, 'ENABLE_HARD_RULES', True) else 'DISABLED'}")
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
            
            # Fetch candles for yesterday
            # We add some buffer before start_epoch to have indicator data
            fetch_start = start_epoch - 3600 # 1 hour buffer
            
            try:
                candles_resp = await api.ticks_history(
                    {
                        "ticks_history": asset, 
                        "style": "candles", 
                        "granularity": 60, 
                        "start": fetch_start, 
                        "end": end_epoch,
                        "count": 2000 # Should cover 24h + buffer
                    }
                )
            except Exception as e:
                print(f"   ⚠️ Error fetching data: {e}")
                continue
            
            if "error" in candles_resp:
                print(f"   ⚠️ API Error: {candles_resp['error']['message']}")
                continue
                
            history = candles_resp.get("candles")
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
            df['macd_hist'] = 0.0 # Initialize for safety if needed by some checks
            
            # Filter main loop to yesterday only
            # df includes buffer, so we slice data that falls within start_dt and end_dt
            # But the simulation loop must cover strictly yesterday
            
            asset_signals = 0
            asset_wins = 0
            
            print(f"   Fetched {len(df)} candles. Simulating...")
            
            for i in range(50, len(df) - 1):
                if i % 100 == 0: print(f"      Processing candle {i}/{len(df)}...", end='\r')
                timestamp = df.index[i]
                if timestamp.timestamp() < start_epoch or timestamp.timestamp() > end_epoch:
                    continue
                    
                current_slice = df.iloc[i-50:i+1]
                future_candle = df.iloc[i+1]
                
                best_signal = None
                best_reason = ""
                
                # Check CALL
                # 1. Hard Rules First
                safe_c, reason_c = technical_analysis.TechnicalConfirmation.check_hard_rules(current_slice, "CALL")
                if safe_c:
                    # 2. Tech Score (using async method synchronously? No, verify awaits)
                    score_c, details_c = await technical_analysis.TechnicalConfirmation.get_confirmation_score(None, asset, "CALL", current_slice)
                    if score_c >= 0.7:
                        best_signal = "CALL"
                        best_reason = f"Score {score_c:.2f}"
                
                # Check PUT
                if not best_signal and getattr(config, "ALLOW_PUT_SIGNALS", True):
                    safe_p, reason_p = technical_analysis.TechnicalConfirmation.check_hard_rules(current_slice, "PUT")
                    if safe_p:
                        score_p, details_p = await technical_analysis.TechnicalConfirmation.get_confirmation_score(None, asset, "PUT", current_slice)
                        if score_p >= 0.7:
                             best_signal = "PUT"
                             best_reason = f"Score {score_p:.2f}"

                if best_signal:
                    asset_signals += 1
                    
                    # Verify Result
                    entry = current_slice.iloc[-1]['close']
                    exit_price = future_candle['close']
                    outcome = "LOSS"
                    
                    if best_signal == "CALL" and exit_price > entry: outcome = "WIN"
                    elif best_signal == "PUT" and exit_price < entry: outcome = "WIN"
                    elif exit_price == entry: outcome = "TIE"
                    
                    if outcome == "WIN": asset_wins += 1
                    # print(f"      {timestamp} {best_signal} ({best_reason}) -> {outcome}")

            total_signals += asset_signals
            total_wins += asset_wins
            total_losses += (asset_signals - asset_wins)
            
            rate = (asset_wins/asset_signals*100) if asset_signals>0 else 0
            results_by_asset[asset] = {"avg": rate, "ct": asset_signals}
            print(f"   👉 Signals: {asset_signals}, Wins: {asset_wins} ({rate:.1f}%)")

        print("\n" + "="*60)
        print("📊 SUMMARY (Yesterday)")
        print(f"Total Signals: {total_signals}")
        print(f"Total Wins:    {total_wins}")
        print(f"Win Rate:      {(total_wins/total_signals*100) if total_signals>0 else 0:.2f}%")
        print("="*60)
            
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await api.disconnect()

if __name__ == "__main__":
    asyncio.run(run_backtest())
