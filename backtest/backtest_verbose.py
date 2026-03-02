import asyncio
import os
import pandas as pd
from deriv_api import DerivAPI
import config
import market_engine
from technical_analysis import TechnicalConfirmation

DEBUG_LOG = "backtest_debug.log"

def dbg_log(msg):
    with open(DEBUG_LOG, "a", encoding="utf-8") as f:
        f.write(msg + "\n")
    print(msg, flush=True)

async def run_backtest(asset="1HZ100V", days=1, initial_balance=1000.0):
    if os.path.exists(DEBUG_LOG): os.remove(DEBUG_LOG)
    dbg_log(f"📊 Starting Backtest for {asset}...")
    
    api = DerivAPI(app_id=config.DERIV_APP_ID)
    
    try:
        count = 100 
        dbg_log(f"📥 Calling get_candles_df for {count} candles...")
        df = await market_engine.get_candles_df(api, asset, count, 60)
        
        if df is None or df.empty:
            dbg_log("❌ No data returned.")
            return

        dbg_log(f"✅ Loaded {len(df)} candles. Start Loop...")
        
        balance = initial_balance
        wins = 0
        losses = 0
        
        start_idx = 40
        for i in range(start_idx, len(df)-1):
            dbg_log(f"➡️ Step {i}/{len(df)}...")
            df_slice = df.iloc[:i+1]
            
            dbg_log(f"   Calculating Scores for step {i}...")
            # Use await since we are in async, though score calc is mostly sync
            score_call, _ = await TechnicalConfirmation.get_confirmation_score(None, asset, "CALL", df_slice)
            score_put, _ = await TechnicalConfirmation.get_confirmation_score(None, asset, "PUT", df_slice)
            dbg_log(f"   Scores: CALL={score_call}, PUT={score_put}")
            
            signal = None
            if score_call >= 0.6: signal = "CALL"
            elif score_put >= 0.6: signal = "PUT"
            
            if signal:
                dbg_log(f"   ⚡ Signal: {signal}")
                next_candle = df.iloc[i+1]
                entry = df.iloc[i]["close"]
                exit = next_candle["close"]
                
                win = False
                if signal == "CALL" and exit > entry: win = True
                if signal == "PUT" and exit < entry: win = True
                
                if win:
                    wins += 1
                    balance += 9.5
                    dbg_log(f"      WIN (+9.5) Bal: {balance}")
                else:
                    losses += 1
                    balance -= 10.0
                    dbg_log(f"      LOSS (-10.0) Bal: {balance}")

        dbg_log("\n🏁 FINAL RESULTS")
        dbg_log(f"Trades: {wins+losses}")
        dbg_log(f"Win Rate: {(wins/(wins+losses)*100) if wins+losses > 0 else 0}%")
        dbg_log(f"Balance: {balance}")
        
    except Exception as e:
        dbg_log(f"❌ ERROR: {e}")
    finally:
        dbg_log("--- Done ---")

if __name__ == "__main__":
    asyncio.run(run_backtest())
