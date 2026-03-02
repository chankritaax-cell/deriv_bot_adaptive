import asyncio
import os
import pandas as pd
from deriv_api import DerivAPI
# Add project root to sys.path so we can import config & modules
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from modules import market_engine
from modules.technical_analysis import TechnicalConfirmation
from modules.utils import log_print
from modules.smart_trader import SmartTrader

async def run_backtest(asset="1HZ100V", days=1, initial_balance=1000.0):
    log_print(f"📊 Starting Full-Strategy Backtest for {asset}...")
    
    api = DerivAPI(app_id=config.DERIV_APP_ID)
    smart = SmartTrader() 
    
    # Reset Backtest stats for a clean run
    if "1HZ100V|BACKTEST_STRATEGY" in smart.perf.data["combo_stats"]:
        del smart.perf.data["combo_stats"]["1HZ100V|BACKTEST_STRATEGY"]
    
    try:
        count = 500 
        log_print(f"   📥 Fetching {count} candles...")
        df = await market_engine.get_candles_df(api, asset, count, 60)
        
        if df is None or df.empty:
            log_print("   ❌ No data returned.")
            return

        log_print(f"   ✅ Data Loaded. Starting Multi-Layer Simulation (L1+L2+L3)...")
        log_print(f"      - L1: Performance Guard (Win Rate Filter)")
        log_print(f"      - L2: Technical Confirmation (MACD/Stoch)")
        log_print(f"      - L3: RL Decision Engine (Learning from experience)")
        
        balance = initial_balance
        wins = 0
        losses = 0
        trades_count = 0
        
        start_idx = 50 
        for i in range(start_idx, len(df)-1):
            if i % 50 == 0:
                log_print(f"   ⏳ Processing candle {i}/{len(df)}...")
            df_slice = df.iloc[:i+1]
            current_close = df.iloc[i]["close"]
            
            # --- PHASE 1: Strategy Signal ---
            # Technical Score proxies the Strategy Signal
            score_call, _ = await TechnicalConfirmation.get_confirmation_score(None, asset, "CALL", df_slice)
            score_put, _ = await TechnicalConfirmation.get_confirmation_score(None, asset, "PUT", df_slice)
            
            signal = "HOLD"
            confidence = 0.0
            threshold = config.AI_CONFIDENCE_THRESHOLD
            
            if score_call >= threshold: 
                signal, confidence = "CALL", score_call
            elif score_put >= threshold: 
                signal, confidence = "PUT", score_put
            
            if signal == "HOLD": continue
            
            # --- PHASE 2: Full SmartTrader Stack (L1, L2, L3) ---
            # This uses the EXACT SAME logic as the live bot
            should_enter, bet_mult, details = await smart.should_enter(
                api=None,
                asset=asset,
                strategy="BACKTEST_STRATEGY",
                signal=signal,
                confidence=confidence,
                df_1m=df_slice
            )
            
            if should_enter:
                trades_count += 1
                entry = current_close
                exit = df.iloc[i+1]["close"]
                
                win = False
                if signal == "CALL" and exit > entry: win = True
                if signal == "PUT" and exit < entry: win = True
                
                profit = 0
                if win:
                    wins += 1
                    profit = 10.0 * 0.95 * bet_mult
                else:
                    losses += 1
                    profit = -10.0 * bet_mult
                
                balance += profit
                
                # Record result for SmartTrader's internal RL and Perf tracking
                smart.perf.record_trade(asset, "BACKTEST_STRATEGY", signal, "WIN" if win else "LOSS", profit, confidence=confidence)
                smart.rl.update(asset, "BACKTEST_STRATEGY", confidence, "ENTER", 1.0 if win else -1.0)
                
                if trades_count % 10 == 0:
                    log_print(f"   💰 Trade {trades_count}: {signal} | Result: {'WIN' if win else 'LOSS'} | Bal: ${balance:.2f}")
            else:
                pass

        # Report
        win_rate = (wins / trades_count * 100) if trades_count > 0 else 0
        
        report = f"\n" + "="*40 + "\n"
        report += f"🏁 Backtest Results (L1+L2+L3 Strategy): {asset}\n"
        report += "="*40 + "\n"
        report += f"   Trades Executed: {trades_count}\n"
        report += f"   Wins: {wins} | Losses: {losses}\n"
        report += f"   Win Rate: {win_rate:.2f}%\n"
        report += f"   Final Balance: ${balance:.2f} (Net: ${balance - initial_balance:.2f})\n"
        report += "="*40 + "\n"
        log_print(report)
        
    except Exception as e:
        log_print(f"❌ Backtest error: {e}")
    finally:
        pass

if __name__ == "__main__":
    try:
        asyncio.run(run_backtest())
    except KeyboardInterrupt:
        pass
