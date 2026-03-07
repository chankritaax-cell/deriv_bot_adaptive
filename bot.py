import os
import sys

# ============================================================
# 🚨 V5.0 CRITICAL SAFEGUARD: Prevent Real Account Execution
# ============================================================
DERIV_ACCOUNT_TYPE = os.environ.get("DERIV_ACCOUNT_TYPE", "demo").lower()
APP_ID = str(os.environ.get("DERIV_APP_ID", ""))

_KNOWN_REAL_APP_IDS = set()  # add private real app_ids here e.g. {"36544"}

_abort_reason = None
if DERIV_ACCOUNT_TYPE == "real":
    _abort_reason = f"DERIV_ACCOUNT_TYPE=real in environment"
if APP_ID in _KNOWN_REAL_APP_IDS:
    _abort_reason = f"Real account APP_ID ({APP_ID}) detected"

if _abort_reason:
    print("\n" + "🛑" * 30)
    print("CRITICAL ALERT: Bot V5.0 is running with a NON-DEMO account profile!")
    print(f"Reason: {_abort_reason}")
    print(f"DERIV_ACCOUNT_TYPE: {DERIV_ACCOUNT_TYPE}")
    print("Set DERIV_ACCOUNT_TYPE=demo in your .env file.")
    print("🛑" * 30 + "\n")
    sys.exit(1) # [v5.0 BUG-02 FIX]

import shutil  # [v5.0 BUG-13 FIX] 🔥 CRITICAL: Clear Python cache BEFORE importing config
# This ensures fresh config values are loaded on every bot restart
pycache_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "__pycache__")
if os.path.exists(pycache_dir):
    try:
        shutil.rmtree(pycache_dir)
        print("🗑️  Cleared __pycache__ directory (loading fresh config)")
    except Exception as e:
        print(f"⚠️  Warning: Could not clear cache: {e}")


import asyncio
import os
import sys
import json
import datetime
import time
import signal
import traceback # [v3.11.28] For detailed error logging
import hashlib # [v3.11.28] For system audit
from deriv_api import DerivAPI
from modules.smart_trader import _SMART_TRADER # [v3.6.0] For Scanner Awareness logic
import pandas as pd
import config
from modules import market_engine
from modules.market_engine import market_status_summary
from modules import trade_engine
from modules import ai_engine 
from modules import ai_council
from modules import telegram_bridge as telegram # [v3.9.0] Fix NameError
from modules.utils import log_print, log_to_file, dashboard_update, dashboard_add_trade, dashboard_add_summary, dashboard_save_candles, dashboard_init_state, dashboard_get_state, get_crypto_thb_rate, ROOT, load_martingale_state, save_martingale_state, reset_martingale_state # [v3.11.28] Add ROOT & state
from modules.stream_manager import DerivStreamManager # [v4.0.0] New Streaming Manager
COMMAND_FILE = os.path.join(ROOT, "commands.json") # [v3.11.28] Define COMMAND_FILE using ROOT

def check_tick_velocity(stream_mgr, current_atr):
    """
    [v4.1.2] Tick Velocity Guard / Micro-Spike Prevention (Stream-Based)
    Reads directly from stream_manager.latest_ticks deque — zero REST API latency.
    Falls back to (False, 0, 0) if stream data is unavailable (e.g. polling mode).
    """
    try:
        if stream_mgr is None or not hasattr(stream_mgr, 'latest_ticks'):
            return False, 0.0, 0.0
        
        ticks = list(stream_mgr.latest_ticks)
        if len(ticks) < 2:
            return False, 0.0, 0.0
        
        latest_tick = ticks[-1]
        oldest_tick = ticks[0]
        
        # Freshness Check: reject if latest tick is stale (>5s old)
        if (time.time() - latest_tick['received_at']) > 5:
            log_print(f"   ⚠️ Tick Velocity: Stale tick data ({time.time() - latest_tick['received_at']:.1f}s old). Skipping guard.")
            return False, 0.0, 0.0
        
        spike_size = abs(latest_tick['price'] - oldest_tick['price'])
        limit = current_atr * getattr(config, "MAX_TICK_VELOCITY_ATR_PCT", 0.5)
        is_spike = spike_size > limit
        return is_spike, spike_size, limit
    except Exception as e:
        log_print(f"   ⚠️ Tick Velocity Check Error: {e}")
        return False, 0.0, 0.0

async def send_telegram_alert(message):
    """
    [v3.11.57] Sends a generic alert message to Telegram via the summary log.
    This allows the bot to send notifications without direct bot token access in this process.
    """
    try:
        summary = {
            "type": "SYSTEM_ALERT",
            "message": message,
            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        dashboard_add_summary(summary)
        log_print(f"📡 [Telegram] Alert Queued: {message}")
    except Exception as e:
        log_print(f"⚠️ [Telegram] Alert queue failed: {message} | Error: {e}")

async def check_global_stop_loss(current_profit):
    """
    [v4.1.2] Strict Global Stop-Loss Guard.
    Halts the bot immediately if the daily loss limit is reached.
    """
    stop_loss_limit = (getattr(config, "INITIAL_CAPITAL", 14.15) * getattr(config, "MAX_DAILY_LOSS_PERCENT", 20.0)) / 100.0
    if current_profit <= -stop_loss_limit:
        log_print("")
        log_print("🛑" + "="*60)
        log_print(f"🛑 CRITICAL ALERT: Daily Stop Loss Reached!")
        log_print(f"🛑 Profit: {current_profit:.2f} <= Limit: -{stop_loss_limit:.2f}")
        log_print("🛑 Halting all operations to protect capital.")
        log_print("🛑" + "="*60)
        log_print("")
        await send_telegram_alert(f"🛑 CRITICAL: Daily Stop Loss Reached! Profit: {current_profit:.2f}. Bot Halted.")
        await asyncio.sleep(2) # Allow Telegram time to log/send
        os._exit(42)

def run_startup_audit():
    """[v3.11.28] System self-check: log paths, versions, and hashes to prevent environment conflicts."""
    log_print("🔍 [System Audit] Starting self-check...")
    log_print(f"   🏠 Root Path: {os.path.abspath(ROOT)}")
    log_print(f"   🐍 Python Exec: {sys.executable}")
    log_print(f"   📄 Main File: {os.path.abspath(__file__)}")
    
    # Audit critical modules
    for mod_name in ['config', 'modules.ai_engine', 'modules.market_engine']:
        try:
            mod = sys.modules.get(mod_name)
            if mod and hasattr(mod, '__file__'):
                fpath = mod.__file__
                # Calculate simple hash for version tracking
                with open(fpath, "rb") as f:
                    file_hash = hashlib.md5(f.read()).hexdigest()[:8]
                log_print(f"   📦 {mod_name:18} -> {fpath} ({file_hash})")
        except: pass
    log_print("✅ [System Audit] Completed.")

async def run_streaming_bot(api, thb_suffix):
    """
    [v4.0.0] New Streaming Logic (Part 4 - Full Trading Loop)
    Handles data assembly, AI analysis, and trade execution.
    """
    asset = config.ACTIVE_ASSET
    global last_activity_time
    log_print(f"📡 Entering STREAMING Mode for {asset}...")

    # State Variables
    last_trade_time = time.time() - 3600
    last_trade_result = "UNKNOWN"
    last_notified_cd_candle = None
    last_ai_signal = "None"
    last_scan_time = 0  # [v4.1.0] Asset Rotation Scanner — Start at 0 to trigger scan immediately on boot
    
    # 1. Initial Bulk Fetch (300 candles)
    log_print(f"   📥 Performing initial fetch of 300 candles for {asset}...")
    df = await market_engine.get_candles_df(api, asset, 300, 60)
    
    if df is None or df.empty:
        log_print("   ❌ Startup Error: Failed to fetch initial candles. Exiting.")
        return

    log_print(f"   ✅ Synchronized: {len(df)} candles loaded.")

    # 2. Initialize and Start Stream Manager
    stream_manager = DerivStreamManager(api, asset)
    await stream_manager.start_streams()

    # 3. Infinite Consumer Loop
    while True:
        try:
            # --- [v4.1.5] Safe Exit on Fatal API Error ---
            if stream_manager.api_failed:
                log_print(f"   💀 Fatal API Error detected by stream manager. Exiting stream loop to reconnect...")
                break # Break to outer loop, which will kill and restart the script

            # Wait for a fully closed candle from the stream (90s timeout for soft-reconnect)
            try:
                closed_candle = await asyncio.wait_for(stream_manager.candle_queue.get(), timeout=90.0)
            except asyncio.TimeoutError:
                closed_candle = None  # No candle — scanner can still fire
                if stream_manager.api_failed:
                    log_print(f"   💀 Fatal API Error detected post-timeout. Exiting stream loop to reconnect...")
                    break
                else:
                    # [v5.1.1] Network Resilience: Soft Auto-Reconnect on Silent Drop
                    log_print(f"   ⚠️ Stream timeout (90s without new candle). Attempting soft reconnect...")
                    dashboard_update("status", "♻️ Stream Reconnecting...")
                    try:
                        await stream_manager.stop()
                    except Exception as e:
                        log_print(f"   ⚠️ Error stopping stream manager: {e}")
                    
                    # Recreate stream manager to force fresh websocket subscriptions
                    stream_manager = DerivStreamManager(api, asset)
                    await stream_manager.start_streams()
                    log_print(f"   ✅ Soft reconnect complete. Waiting for fresh data...")
                    continue

            # --- [v4.1.0] Asset Rotation Scanner ---
            _sleeping, _sleep_secs = market_engine.is_sleep_mode()
            if _sleeping:
                log_print(f"   😴 [Sleep Mode] All council assets banned. Sleeping {_sleep_secs/60:.0f}m...")
                await asyncio.sleep(min(60, _sleep_secs))
                continue  # [v5.0 BUG-08 FIX]
            
            needs_forced_scan = market_engine.is_blacklisted(asset)
            if getattr(config, "ENABLE_ASSET_ROTATION", False) or needs_forced_scan:
                now_scan = time.time()
                base_scan_interval = getattr(config, "ASSET_SCAN_INTERVAL_MINS", 60) * 60
                inactive_interval = getattr(config, "ASSET_SCAN_INTERVAL_NO_TRADE_MINS", 15) * 60
                
                time_since_trade = now_scan - last_trade_time
                time_since_scan = now_scan - last_scan_time
                
                # Trigger scanner if we hit the normal interval OR if we've been inactive for too long and haven't scanned recently
                is_inactive_trigger = time_since_trade > inactive_interval and time_since_scan > inactive_interval
                is_normal_trigger = time_since_scan > base_scan_interval
                
                if is_inactive_trigger or is_normal_trigger or needs_forced_scan:
                    last_scan_time = now_scan
                    reason = "Forced" if needs_forced_scan else f"Inactive: {time_since_trade/60:.0f}m ago"
                    log_print(f"\n🔍 [AI Scanner] Streaming mode scan ({reason})...")
                    try:
                        best = None
                        asset_symbols = []
                        if getattr(config, "ACTIVE_PROFILE", "") == "TIER_COUNCIL":
                            from modules.asset_selector import AssetSelector
                            log_print("   🔍 [TIER_COUNCIL] Running Deep Simulation Scan for best asset...")
                            best_selector, wr_selector, _ = await AssetSelector.find_best_asset(api, lookback_hours=12, min_trades=30)
                            
                            if best_selector and wr_selector > 50.0:
                                best = best_selector
                                asset_symbols = [best]
                                log_print(f"   🎯 TIER_COUNCIL Best Asset: {best} (WR: {wr_selector:.1f}%)")
                            else:
                                log_print("   ⚠️ No TIER_COUNCIL asset met criteria (>30 trades, >50% WR).")
                        else:
                            assets = await market_engine.scan_open_assets(api, smart_trader_instance=_SMART_TRADER)
                            # Exclude current asset if inactive
                            if is_inactive_trigger:
                                assets = [a for a in assets if a[0] != asset]
                                log_print(f"   🚫 Excluding {asset} due to inactivity.")
    
                            summaries = {}
                            for sym, payout in assets[:8]:
                                summary = await market_engine.get_market_summary_for_ai(api, sym)
                                if summary:
                                    summaries[sym] = summary
    
                            best = await ai_engine.choose_best_asset(api, summaries)
                            asset_symbols = [a[0] for a in assets]

                        if best and best in asset_symbols and best != asset:
                            old_asset = asset
                            log_print(f"   🔄 Switching Active Asset: {old_asset} -> {best}")

                            # 1. Stop current streams safely
                            await stream_manager.stop()

                            # 2. Update asset
                            asset = best
                            config.ACTIVE_ASSET = best
                            dashboard_update("current_asset", market_engine.get_asset_name(best))

                            # 3. Re-fetch candles for new asset
                            log_print(f"   📥 Fetching 300 candles for {asset}...")
                            df = await market_engine.get_candles_df(api, asset, 300, 60)
                            if df is None or df.empty:
                                log_print(f"   ❌ Failed to fetch candles for {asset}. Reverting to {old_asset}.")
                                asset = old_asset
                                config.ACTIVE_ASSET = old_asset
                                df = await market_engine.get_candles_df(api, asset, 300, 60)

                            # 4. Start new streams
                            stream_manager = DerivStreamManager(api, asset)
                            await stream_manager.start_streams()
                            log_print(f"   ✅ Now streaming: {asset}")

                            # 5. Reset state
                            last_notified_cd_candle = None
                            last_ai_signal = "None"
                            continue  # Restart loop with new asset
                        elif best == asset:
                            log_print(f"   ✅ Current asset {asset} is still the best choice.")
                        else:
                            if needs_forced_scan:
                                log_print(f"   💤 Fallback Guard: {asset} is banned and no valid alternative in TIER_COUNCIL found. Sleeping 10m...")
                                dashboard_update("status", "Sleeping (10m Fallback)")
                                await asyncio.sleep(600)
                            else:
                                log_print(f"   ℹ️ No better asset found. Staying on {asset}.")
                    except Exception as e:
                        log_print(f"   ⚠️ Scanner Error: {e}")

            # If no candle arrived (timeout), skip trading logic
            # [v4.1.4] Do NOT reset last_activity_time here — dead streams must trigger watchdog
            if closed_candle is None:
                continue
                
            if market_engine.is_blacklisted(asset):
                log_print(f"   🚫 {asset} is BLACKLISTED. Skipping candle update and waiting for scanner to switch...")
                continue

            # 4. Update DataFrame (Rolling Window of 300)
            new_row_df = market_engine.candles_to_df([closed_candle])
            df = pd.concat([df, new_row_df])
            
            # [Fix] Deduplicate index to prevent corrupted overlaps between initial fetch and stream
            df = df[~df.index.duplicated(keep='last')]
            
            if len(df) > 300:
                df = df.iloc[-300:]
            df.sort_index(inplace=True)
            
            # Update Dashboard
            last_activity_time = time.time()
            dashboard_save_candles(market_engine.get_asset_name(asset), df)
            
            # --- 5. Trading Logic Start ---
            current_epoch = closed_candle['epoch']
            human_time = datetime.datetime.fromtimestamp(current_epoch, tz=datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            
            # Cooldown Management
            now = time.time()
            cd_any = getattr(config, "COOLDOWN_ANY_TRADE_MINS", 5)
            cd_loss = getattr(config, "COOLDOWN_LOSS_TRADE_MINS", 10)
            required_minutes = cd_loss if last_trade_result == "LOSS" else cd_any
            
            elapsed_mins = (now - last_trade_time) / 60
            if elapsed_mins < required_minutes:
                if last_notified_cd_candle != current_epoch:
                    rem = int(required_minutes - elapsed_mins)
                    log_print(f"   ⏳ Cooldown Active: {rem}m remaining (Last Trade: {last_trade_result})")
                    last_notified_cd_candle = current_epoch
                continue

            # --- 6. Pre-AI Analysis ---
            log_print(f"\n🔎 Analyzing {asset} (Closed Candle: {current_epoch} - {human_time})...")
            market_summary = market_engine.get_market_summary_from_df(df)
            
            # 7. AI Analysis & Guards (Internal to analyze_and_decide)
            decision = await ai_engine.analyze_and_decide(api, asset, market_summary, df)

            if not decision:
                # --- [v5.1.2] Sideways Guard: Force asset rescan after N consecutive SIDEWAYS candles ---
                if ai_engine.get_sideways_rescan_needed(asset):
                    log_print(f"   🔄 [Sideways Guard] {asset} stuck in SIDEWAYS for {ai_engine.SIDEWAYS_RESCAN_THRESHOLD}+ candles. Banning for 30m & forcing rescan.")
                    ai_engine.reset_sideways_counter(asset)
                    market_engine.blacklist_asset(asset, duration_secs=1800, reason="Sideways Exhaustion")
                    last_scan_time = 0  # Force immediate scanner trigger on next loop iteration
                continue
            
            direction = decision.get("action")
            strategy_name = decision.get("strategy", "UNKNOWN")
            details = decision.get("details", {})
            
            if direction not in ["CALL", "PUT"]:
                reason_str = ", ".join(map(str, details.get('reasons', ['Skip signal'])))
                log_print(f"   ℹ️ AI Decision: {direction} ({strategy_name}) | Reason: {reason_str}")
                dashboard_update("status", f"Skip ({direction})")
                last_ai_signal = direction
                continue

            # --- 8. Post-AI Veto (Tick Velocity Guard) ---
            if getattr(config, "ENABLE_TICK_VELOCITY_GUARD", True):
                current_atr = details.get("snapshot", {}).get("atr", 0.0)
                if current_atr > 0 and len(stream_manager.latest_ticks) >= 2:
                    # Calculate spike from the live deque
                    ticks = list(stream_manager.latest_ticks)
                    latest_tick = ticks[-1]
                    oldest_tick = ticks[0]
                    
                    # Freshness Check: If the latest tick is older than 5 seconds, the stream might be dead
                    if (time.time() - latest_tick['received_at']) > 5:
                        log_print(f"   ⚠️ STREAM VETO: Trade rejected. Tick data is STALE (Last tick {time.time() - latest_tick['received_at']:.1f}s ago).")
                        dashboard_update("status", "Skip (Stale Feed)")
                        continue

                    spike_size = abs(latest_tick['price'] - oldest_tick['price'])
                    limit = current_atr * getattr(config, "MAX_TICK_VELOCITY_ATR_PCT", 0.5)
                    
                    if spike_size > limit:
                        log_print(f"   🛑 STREAM VETO: Trade rejected. Extreme Velocity (Spike: {spike_size:.4f} > Limit: {limit:.4f})")
                        dashboard_update("status", "Skip (Spike Veto)")
                        continue

            # --- 9. Execution ---
            ds = dashboard_get_state()
            loss_streak = ds.get("loss_streak", 0)
            
            # --- [v4.1.0] Persistent Martingale Memory ---
            mg_step, current_stake = load_martingale_state()
            
            smart = ai_engine.get_smart_trader()
            
            # --- [v4.1.1] Strict Martingale ---
            # Ignore AI amount_multiplier (bet_mult) and Defensive resets to enforce exact MG progression
            mg_mult = smart.perf.get_martingale_multiplier(mg_step)
            final_multiplier = mg_mult
            
            amount = max(config.AMOUNT * final_multiplier, getattr(config, "MIN_STAKE_AMOUNT", 1.0))
            
            # Stake Cap
            max_stake = getattr(config, "MAX_STAKE_AMOUNT", 0.0)
            if max_stake > 0 and amount > max_stake:
                log_print(f"   ⚠️ Risk Guard: Stake ${amount:.2f} exceeds Max ${max_stake}. Capping.")
                amount = max_stake

            reason_str = ", ".join(map(str, details.get('reasons', [])))
            log_print(f"   ⚡ Signal: {direction} ({strategy_name}) | Strict MG x{final_multiplier:.2f}")
            log_print(f"   📝 Stake: ${amount:.2f} | Reasoning: {reason_str}")
            
            # Sync Dashboard BEFORE execution
            dashboard_update("martingale_level", min(mg_step, getattr(config, "MAX_MARTINGALE_STEPS", 0)))
            dashboard_update("current_strategy", strategy_name)
            dashboard_update("signal", direction)
            dashboard_update("signal_time", datetime.datetime.now().strftime("%H:%M:%S"))
            dashboard_update("ai_confidence", details.get("confidence", 0.0))

            # Execute Trade
            trade_exec_data = await trade_engine.execute_trade(api, asset, direction, amount, 60)
            
            if trade_exec_data:
                contract_id = trade_exec_data.get("contract_id")
                last_trade_time = time.time()
                log_print(f"   ⏳ Waiting 65s for trade execution... ({contract_id})")
                
                # Heartbeat Loop: Update last_activity_time every second to prevent watchdog kill
                for _ in range(65):
                    last_activity_time = time.time()
                    await asyncio.sleep(1)
                
                # Result Processing (with retry for delayed settlement)
                result = "OPEN"
                profit = 0.0
                entry_spot = 0.0
                exit_spot = 0.0
                
                for _ in range(3): # Try up to 3 times (15s total extra buffer)
                    result, profit, entry_spot, exit_spot = await trade_engine.check_trade_status(api, contract_id)
                    if result != "OPEN":
                        break
                    log_print(f"   ⏳ Trade still OPEN. Waiting 5s for broker settlement...")
                    for _ in range(5):
                        last_activity_time = time.time()
                        await asyncio.sleep(1)
                        
                last_trade_result = result
                
                # Log result
                log_print(f"   🏁 Trade Finished: {result} | Profit: ${profit:.2f} (Entry: {entry_spot}, Exit: {exit_spot})")
                
                if result != "UNKNOWN":
                    # Record for AI intelligence
                    is_override = details.get("is_override", False)
                    ai_engine.record_trade_result(asset, strategy_name, direction, result, profit, details.get("confidence", 0.0), is_override=is_override)
                    
                    # Update Persistance and Dashboard
                    new_balance = await trade_engine.get_balance(api)
                    ds = dashboard_get_state()
                    dashboard_update("balance", new_balance)
                    current_profit = new_balance - ds.get("start_balance", new_balance)
                    dashboard_update("profit", current_profit)
                    await check_global_stop_loss(current_profit)
                    
                    trade_info = {
                        "time": datetime.datetime.now().strftime("%H:%M:%S"),
                        "asset": asset,
                        "strategy": strategy_name,
                        "direction": direction,
                        "amount": amount,
                        "result": result,
                        "profit": profit,
                        "entry_spot": entry_spot,
                        "exit_spot": exit_spot,
                        "timestamp": time.time()
                    }
                    dashboard_add_trade(trade_info)
                    
                    # Handle Win/Loss Streaks
                    if result == "WIN":
                        dashboard_update("total_wins", ds.get("total_wins", 0) + 1)
                        dashboard_update("win_streak", ds.get("win_streak", 0) + 1)
                        dashboard_update("loss_streak", 0)
                        reset_martingale_state() # [v4.1.0] Reset MG Memory
                        telegram.send_trade_notification(trade_info, ds.get("balance", 0), ds.get("profit", 0))
                    elif result == "LOSS":
                        dashboard_update("total_losses", ds.get("total_losses", 0) + 1)
                        dashboard_update("loss_streak", ds.get("loss_streak", 0) + 1)
                        dashboard_update("win_streak", 0)
                        
                        # --- [v4.1.0] Persistent Martingale Memory ---
                        next_mg_step = mg_step + 1
                        if next_mg_step > getattr(config, "MAX_MARTINGALE_STEPS", 0):
                            log_print(f"   🛑 Reached Max Martingale Steps ({getattr(config, 'MAX_MARTINGALE_STEPS', 0)}). Resetting stake.")
                            reset_martingale_state()
                        else:
                            save_martingale_state(next_mg_step, amount)
                            log_print(f"   💾 Saved Martingale State: Step {next_mg_step} carried to next trade.")
                            
                        # --- [v4.1.6] Cut and Run Logic ---
                        log_print(f"   ✂️ CUT AND RUN: 1 Loss detected. Banning {asset} for 1 hour.")
                        market_engine.blacklist_asset(asset)
                        last_scan_time = 0 # Force immediate scan to switch assets
                    elif result == "DRAW":
                        log_print(f"   🔘 DRAW: No changes to streak or martingale.")
                        telegram.send_trade_notification(trade_info, ds.get("balance", 0), ds.get("profit", 0))
                    else: # OPEN or UNKNOWN — Broker delayed settlement
                        log_print(f"   ⏳ UNRESOLVED TRADE ({result}): Entering definitive wait loop for contract {contract_id}...")
                        while True:
                            for _ in range(5):  # 5s heartbeat to prevent watchdog kill
                                last_activity_time = time.time()
                                await asyncio.sleep(1)
                            result, profit, entry_spot, exit_spot = await trade_engine.check_trade_status(api, contract_id)
                            if result in ["WIN", "LOSS", "DRAW"]:
                                log_print(f"   ✅ Definitive result received: {result} | Profit: ${profit:.2f}")
                                last_trade_result = result
                                
                                # Re-record with correct result
                                ai_engine.record_trade_result(asset, strategy_name, direction, result, profit, details.get("confidence", 0.0), is_override=is_override)
                                
                                # Update balance/dashboard
                                new_balance = await trade_engine.get_balance(api)
                                ds = dashboard_get_state()
                                dashboard_update("balance", new_balance)
                                current_profit = new_balance - ds.get("start_balance", new_balance)
                                dashboard_update("profit", current_profit)
                                
                                # Update trade_info with definitive result
                                trade_info["result"] = result
                                trade_info["profit"] = profit
                                trade_info["entry_spot"] = entry_spot
                                trade_info["exit_spot"] = exit_spot
                                dashboard_add_trade(trade_info)
                                
                                # Process WIN/LOSS/DRAW
                                if result == "WIN":
                                    dashboard_update("total_wins", ds.get("total_wins", 0) + 1)
                                    dashboard_update("win_streak", ds.get("win_streak", 0) + 1)
                                    dashboard_update("loss_streak", 0)
                                    reset_martingale_state()
                                    telegram.send_trade_notification(trade_info, ds.get("balance", 0), ds.get("profit", 0))
                                elif result == "LOSS":
                                    dashboard_update("total_losses", ds.get("total_losses", 0) + 1)
                                    dashboard_update("loss_streak", ds.get("loss_streak", 0) + 1)
                                    dashboard_update("win_streak", 0)
                                    next_mg_step = mg_step + 1
                                    if next_mg_step > getattr(config, "MAX_MARTINGALE_STEPS", 0):
                                        log_print(f"   🛑 Reached Max Martingale Steps. Resetting stake.")
                                        reset_martingale_state()
                                    else:
                                        save_martingale_state(next_mg_step, amount)
                                        log_print(f"   💾 Saved Martingale State: Step {next_mg_step} carried to next trade.")
                                    log_print(f"   ✂️ CUT AND RUN: 1 Loss detected. Banning {asset} for 1 hour.")
                                    market_engine.blacklist_asset(asset)
                                    last_scan_time = 0
                                else:  # DRAW
                                    telegram.send_trade_notification(trade_info, ds.get("balance", 0), ds.get("profit", 0))
                                break  # Exit the infinite wait loop
                            else:
                                log_print(f"   ⏳ Still {result}. Retrying in 5s... (contract: {contract_id})")
                    # AI Loss Analysis
                    if result == "LOSS":
                        current_streak = ds.get("loss_streak", 0) + 1
                        if getattr(config, "USE_AI_ANALYST", True):
                            try:
                                log_print("   📉 Analyzing Loss with AI...")
                                mkt_context = market_engine.get_market_summary_from_df(df)
                                await ai_engine.analyze_trade_loss(
                                    asset=asset, strategy=strategy_name, signal=direction,
                                    profit=profit, confidence=details.get("confidence", 0.0),
                                    market_data_summary=mkt_context, details=details,
                                    loss_streak=current_streak
                                )
                            except: pass
            
        except Exception as e:
            log_print(f"   ❌ Streaming Loop Error: {e}")
            import traceback
            log_print(traceback.format_exc())
            await asyncio.sleep(2)

async def run_polling_bot(api, thb_suffix, thb_rate):
    """
    [v4.0.0] Existing Polling Logic (Refactored)
    """
    # 2. Main Loop
    # Initialize last_candle_time to None initially, but we will sync it in the loop
    last_candle_time = 0      
    is_first_run = True 
    last_scan_time = 0 
    last_trade_time = time.time() - 3600 
    last_trade_result = "UNKNOWN"
    last_notified_cd_candle = None 
    no_trade_council_triggered = False  
    last_summary_time = time.time()  # [v3.11.45] Performance summary tracking
    last_daily_summary_date = ""      # [v3.11.46] Track date of last 06:00 report
    global last_activity_time
    last_activity_time = time.time()

    # --- [v4.1.0] Institutional Circuit Breaker State ---
    asset_pause_until = {}       # {asset: unix_timestamp} - when the pause expires
    asset_first_loss_time = {}   # {asset: unix_timestamp} - time of the 1st loss in the window
    circuit_breaker_last_log = {} # {asset: unix_timestamp} - throttle log spam to once per 5 min

    # --- Network backoff / reconnect state ---
    # Prevent rapid scan loops when the websocket/API becomes unstable (e.g. 1011 keepalive ping timeout).
    network_failures = 0
    network_retry_until = 0.0
    backoff_log_next_ts = 0.0
    last_reconnect_ts = 0.0

    def _calc_backoff_seconds(n: int, base: int = 10, max_sec: int = 300) -> int:
        n = max(1, int(n))
        return int(min(max_sec, base * (2 ** (n - 1))))

    async def _reconnect_deriv_api():
        nonlocal api, last_reconnect_ts
        # Best-effort close (depends on DerivAPI implementation)
        try:
            if hasattr(api, "disconnect"):
                await api.disconnect()
            elif hasattr(api, "close"):
                res = api.close()
                if asyncio.iscoroutine(res):
                    await res
        except Exception:
            pass

        api = DerivAPI(app_id=config.DERIV_APP_ID)
        await api.authorize(config.DERIV_API_TOKEN)
        try:
            market_engine.reset_asset_cache()
        except Exception:
            pass
        last_reconnect_ts = time.time()
        log_print("🔌 [Market] Reconnected to Deriv API.")

    # Telegram Bridge State
    paused = False
    COMMAND_FILE = os.path.join("logs", "commands.json")

    while True:
        last_activity_time = time.time()
        last_ai_signal = dashboard_get_state().get("signal", "None") # [v3.2.14] Track last signal

        # --- 0. Check for External Commands (Telegram) ---
        if os.path.exists(COMMAND_FILE):
            try:
                with open(COMMAND_FILE, 'r', encoding='utf-8') as f:
                    cmd_data = json.load(f)
                
                cmd = cmd_data.get("command", "").upper()
                src = cmd_data.get("source", "UNKNOWN")
                
                if cmd == "STOP":
                    paused = True
                    log_print(f"🛑 Received STOP command from {src}. Pausing...")
                    dashboard_update("status", "Paused (User)")
                elif cmd == "START":
                    paused = False
                    log_print(f"🚀 Received START command from {src}. Resuming...")
                    dashboard_update("status", "Running")
                elif cmd == "COUNCIL":
                    # [v3.7.4] User requested action via AI Council
                    payload = cmd_data.get("payload", "")
                    log_print(f"🏛️ Telegram -> AI Council: {payload[:50]}...")
                    await ai_council.execute_user_command_async(payload)
                elif cmd == "APPROVE":
                    # [v3.7.4] User approved a proposal via Telegram
                    prop_id = cmd_data.get("payload", "")
                    log_print(f"🏛️ Telegram -> Approve: {prop_id}")
                    res = await ai_council.approve_proposal_async(prop_id)
                    if res.get("restart_required"):
                        log_print("🔄 Restart required to apply AI Council changes. Exiting...")
                        os._exit(1)
                elif cmd == "REJECT":
                    # [v3.7.4] User rejected a proposal via Telegram
                    prop_id = cmd_data.get("payload", "")
                    log_print(f"🏛️ Telegram -> Reject: {prop_id}")
                    await ai_council.reject_proposal_async(prop_id)
                
                # Delete file after processing
                os.remove(COMMAND_FILE)
            except Exception as e:
                log_print(f"⚠️ Command Read Error: {e}")

        if paused:
            sys.stdout.write(f"\r   💤 Bot is PAUSED by User...     ")
            sys.stdout.flush()
            await asyncio.sleep(2)
            continue

        # --- Network Backoff (prevents rapid loops on ws issues) ---
        now_ts = time.time()
        if now_ts < network_retry_until:
            remaining = int(network_retry_until - now_ts)
            if now_ts >= backoff_log_next_ts:
                log_print(f"⏳ [Market] Network unstable. Retrying in {remaining}s...")
                backoff_log_next_ts = now_ts + min(30, max(5, remaining))
                dashboard_update("status", f"Network backoff ({remaining}s)")
            await asyncio.sleep(min(10, max(1, remaining)))
            continue
        
        # --- AI ASSET SCANNER (Periodic Rotation) ---
        _sleeping, _sleep_secs = market_engine.is_sleep_mode()
        if _sleeping:
            log_print(f"   😴 [Sleep Mode] All council assets banned. Sleeping {_sleep_secs/60:.0f}m...")
            await asyncio.sleep(min(60, _sleep_secs))
            continue  # [v5.0 BUG-08 FIX]
            
        needs_forced_scan = market_engine.is_blacklisted(config.ACTIVE_ASSET)
        if getattr(config, "ENABLE_ASSET_ROTATION", False) or needs_forced_scan:
            now = time.time()
            time_since_trade = now - last_trade_time
            current_interval = config.ASSET_SCAN_INTERVAL_MINS * 60
            excluded_asset = None
            
            if time_since_trade > getattr(config, "ASSET_SCAN_INTERVAL_NO_TRADE_MINS", 15) * 60:
                current_interval = getattr(config, "ASSET_SCAN_INTERVAL_NO_TRADE_MINS", 15) * 60
                excluded_asset = config.ACTIVE_ASSET
            
            if (now - last_scan_time > current_interval) or needs_forced_scan:
                if excluded_asset and not needs_forced_scan:
                    log_print(f"\n   ⏳ Inactivity detected ({time_since_trade/60:.0f}m). Auto-Scan initiating...")
                    for i in range(5, 0, -1):
                        sys.stdout.write(f"\r   ⏱️ Scanning in {i}s...      ")
                        sys.stdout.flush()
                        await asyncio.sleep(1)
                    print("") # Newline

                reason = "Forced" if needs_forced_scan else f"Interval: {current_interval/60:.0f}m, Last Trade: {time_since_trade/60:.0f}m ago"
                log_print(f"\n🔍 [AI Scanner] Starting scan ({reason})...")
                if excluded_asset and not needs_forced_scan:
                     log_print(f"   🚫 Temporarily excluding {excluded_asset} due to inactivity.")

                last_scan_time = now
                
                try:
                    best = None
                    asset_symbols = []
                    if getattr(config, "ACTIVE_PROFILE", "") == "TIER_COUNCIL":
                        from modules.asset_selector import AssetSelector
                        log_print("   🔍 [TIER_COUNCIL] Running Deep Simulation Scan for best asset...")
                        best_selector, wr_selector, _ = await AssetSelector.find_best_asset(api, lookback_hours=12, min_trades=30)
                        
                        if best_selector and wr_selector > 50.0:
                            best = best_selector
                            asset_symbols = [best]
                            log_print(f"   🎯 TIER_COUNCIL Best Asset: {best} (WR: {wr_selector:.1f}%)")
                        else:
                            log_print("   ⚠️ No TIER_COUNCIL asset met criteria (>30 trades, >50% WR).")
                    else:
                        assets = await market_engine.scan_open_assets(api, smart_trader_instance=_SMART_TRADER)
                        if excluded_asset:
                            assets = [a for a in assets if a[0] != excluded_asset]
                        
                        summaries = {}
                        for sym, payout in assets[:8]:
                            summary = await market_engine.get_market_summary_for_ai(api, sym)
                            if summary:
                                summaries[sym] = summary
                        
                        best = await ai_engine.choose_best_asset(api, summaries)
                        asset_symbols = [a[0] for a in assets]
                    
                    if best and best in asset_symbols:
                        best_name = market_engine.get_asset_name(best)
                        if best != config.ACTIVE_ASSET:
                            log_print(f"   🔄 Switching Active Asset: {config.ACTIVE_ASSET} -> {best}")
                            config.ACTIVE_ASSET = best
                            dashboard_update("current_asset", best_name)
                            last_candle_time = 0 # Reset new candle check
                        else:
                            log_print(f"   ✅ Current Asset {best} is still the best choice.")
                    else:
                        if needs_forced_scan:
                            log_print(f"   💤 Fallback Guard: {config.ACTIVE_ASSET} is banned and no valid alternative found. Sleeping 10m...")
                            dashboard_update("status", "Sleeping (10m Fallback)")
                            await asyncio.sleep(600)
                        else:
                            log_print(f"   ℹ️ No better asset found. Staying on {config.ACTIVE_ASSET}.")
                            
                except Exception as e:
                    log_print(f"   ⚠️ Scanner Error: {e}")
        
        asset = config.ACTIVE_ASSET

        # --- [v4.1.0] Circuit Breaker Pre-Scan Guard ---
        if time.time() < asset_pause_until.get(asset, 0):
            remaining_secs = asset_pause_until[asset] - time.time()
            now_cb = time.time()
            if now_cb >= circuit_breaker_last_log.get(asset, 0):
                remaining_mins = int(remaining_secs / 60)
                log_print(f"   ⏳ [Circuit Breaker] {asset} is PAUSED for another {remaining_mins}m")
                circuit_breaker_last_log[asset] = now_cb + 300  # Log again in 5 minutes
            await asyncio.sleep(2)
            continue
        
        # Fetch Candles (Async)
        df = await market_engine.get_candles_df(api, asset, 300, 60) # 60s candles
        if df is None:
            err = market_engine.get_last_error()
            if err.get("type") == "network":
                network_failures += 1
                wait_s = _calc_backoff_seconds(network_failures)
                network_retry_until = time.time() + wait_s
                backoff_log_next_ts = 0.0
                log_print(f"   🌐 [Market] Network issue: {err.get('message','')} -> backoff {wait_s}s (#{network_failures})")
                dashboard_update("status", f"Network backoff ({wait_s}s)")

                if network_failures >= 2 and (time.time() - last_reconnect_ts) > 10:
                    try:
                        log_print("   🔄 [Market] Attempting API reconnect...")
                        await _reconnect_deriv_api()
                        market_engine.clear_last_error()
                        network_failures = 0
                        network_retry_until = 0.0
                        dashboard_update("status", "Running")
                    except Exception as e:
                        log_print(f"   ⚠️ [Market] Reconnect failed: {e}")
                await asyncio.sleep(1)
                continue

            if market_engine.is_blacklisted(asset):
                log_print(f"   🚫 Active asset {asset} is BLACKLISTED due to errors.")
                log_print("   🔄 Forcing immediate scanner run to find new asset...")
                last_scan_time = 0
                await asyncio.sleep(10)
                continue

            await asyncio.sleep(2)
            continue

        network_failures = 0
        if df is not None:
            last_activity_time = time.time()
            dashboard_save_candles(market_engine.get_asset_name(asset), df)
        else:
            last_activity_time = time.time()
        
        if df is not None and not df.empty:
            try:
                if "timestamp" in df.columns:
                    current_candle_time = int(df["timestamp"].iloc[-1])
                else:
                    current_candle_time = int(df.index[-1])
            except (ValueError, TypeError, IndexError) as e:
                log_print(f"   ⚠️ Candle Sync Error: {e}")
                await asyncio.sleep(1)
                continue
            
            try:
                cur_ts = int(current_candle_time or 0)
                last_ts = int(last_candle_time or 0)
                
                if cur_ts > last_ts or (cur_ts > 0 and last_ts == 0):
                    is_new_candle = (cur_ts > last_ts)
                    now = time.time()
                    cd_any = getattr(config, "COOLDOWN_ANY_TRADE_MINS", 5)
                    cd_loss = getattr(config, "COOLDOWN_LOSS_TRADE_MINS", 10)
                    required_minutes = cd_loss if last_trade_result == "LOSS" else cd_any
                    
                    elapsed_mins = (now - last_trade_time) / 60
                    if elapsed_mins < required_minutes:
                        if last_notified_cd_candle != current_candle_time:
                            rem = int(required_minutes - elapsed_mins)
                            log_print(f"   ⏳ Cooldown Active: {rem}m remaining (Last Trade: {last_trade_result})")
                            last_notified_cd_candle = current_candle_time
                        continue

                    human_time = datetime.datetime.fromtimestamp(current_candle_time, tz=datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

                    if is_first_run:
                        last_candle_time = current_candle_time
                        is_first_run = False
                        log_print(f"   ⏳ Startup: Synchronizing with market... Waiting for next candle {current_candle_time} ({human_time})")
                        continue

                    last_candle_time = current_candle_time
                    asset_name = market_engine.get_asset_name(asset)
                    log_print(f"\n🔎 Analyzing {asset_name} ({asset}) (New Candle: {current_candle_time} - {human_time})...")
                    current_price = df['close'].iloc[-1]
                    log_print(f"   Price: {current_price}")
                    
                    market_summary = await market_engine.get_market_summary_for_ai(api, asset)
                    decision = await ai_engine.analyze_and_decide(api, asset, market_summary, df)

                    # --- [v5.1.2] Sideways Guard: Force asset rescan after N consecutive SIDEWAYS candles ---
                    if not decision and ai_engine.get_sideways_rescan_needed(asset):
                        log_print(f"   🔄 [Sideways Guard] {asset} stuck in SIDEWAYS for {ai_engine.SIDEWAYS_RESCAN_THRESHOLD}+ candles. Banning for 30m & forcing rescan.")
                        ai_engine.reset_sideways_counter(asset)
                        market_engine.blacklist_asset(asset, duration_secs=1800, reason="Sideways Exhaustion")
                        last_scan_time = 0  # Force immediate scanner trigger on next loop iteration

                    if decision:
                        direction = decision.get("action")
                        ds = dashboard_get_state()
                        loss_streak = ds.get("loss_streak", 0)
                        
                        # --- [v4.1.0] Persistent Martingale Memory ---
                        mg_step, current_stake = load_martingale_state()
                        
                        smart = ai_engine.get_smart_trader()
                        
                        # --- [v4.1.1] Strict Martingale ---
                        # Ignore AI amount_multiplier (bet_mult) and Defensive resets to enforce exact MG progression
                        mg_mult = smart.perf.get_martingale_multiplier(mg_step)
                        final_multiplier = mg_mult
                        
                        amount = max(config.AMOUNT * final_multiplier, getattr(config, "MIN_STAKE_AMOUNT", 1.0))
                        max_stake = getattr(config, "MAX_STAKE_AMOUNT", 0.0)
                        if max_stake > 0 and amount > max_stake:
                            log_print(f"   ⚠️ Risk Guard: Stake ${amount:.2f} exceeds Max ${max_stake}. Capping.")
                            amount = max_stake
                        
                        details = decision.get("details", {})
                        snapshot = details.get("snapshot", {})
                        log_print(f"   📊 [Snapshot] RSI: {snapshot.get('rsi', 0.0):.2f} | MA_Slope: {snapshot.get('slope', 0.0):.4f}% | ATR: {snapshot.get('atr_pct', 0.0):.4f}% | MACD_Hist: {snapshot.get('macd_hist', 0.0):.4f}")
                        
                        strategy_name = decision.get("strategy", "UNKNOWN")
                        
                        if direction not in ["CALL", "PUT"]:
                            reason_str = ", ".join(map(str, details.get('reasons', ['Skip signal'])))
                            log_print(f"   ℹ️ AI Decision: {direction} ({strategy_name}) | Reason: {reason_str}")
                            dashboard_update("status", f"Skip ({direction})")
                            continue

                        reason_str = ", ".join(map(str, details.get('reasons', [])))
                        log_print(f"   ⚡ Signal: {direction} ({strategy_name}) | Strict MG x{final_multiplier:.2f}")
                        log_print(f"   📝 Stake: ${amount:.2f} | Reasoning: {reason_str}")
                        
                        dashboard_update("martingale_level", min(mg_step, getattr(config, "MAX_MARTINGALE_STEPS", 0)))
                        dashboard_update("current_strategy", strategy_name)
                        dashboard_update("signal", direction)
                        dashboard_update("signal_time", datetime.datetime.now().strftime("%H:%M:%S"))
                        dashboard_update("ai_confidence", details.get("confidence", 0.0))
                        
                        if getattr(config, "ENABLE_TICK_VELOCITY_GUARD", True):
                            current_atr = details.get("snapshot", {}).get("atr", 0.0)
                            if current_atr > 0:
                                is_spike, spike_size, limit = check_tick_velocity(None, current_atr)
                                if is_spike:
                                    log_print(f"   🛑 POST-AI BLOCK: Trade rejected. Extreme Tick Velocity detected (Spike: {spike_size:.4f} > Limit: {limit:.4f})")
                                    dashboard_update("status", "Skip (Spike)")
                                    continue

                        trade_exec_data = await trade_engine.execute_trade(api, asset, direction, amount, 60)
                        
                        if trade_exec_data:
                            contract_id = trade_exec_data.get("contract_id")
                            market_price_pre = trade_exec_data.get("market_price", 0.0)
                            analyst_lat = details.get("analyst_latency", 0.0)
                            gate_lat = details.get("gate_latency", 0.0)
                            exec_lat = trade_exec_data.get("api_latency", 0.0)
                            
                            log_print(f"   ⏱️ [Latency] AI Analyst: {analyst_lat:.2f}s | Bet Gate: {gate_lat:.2f}s | API Exec: {exec_lat:.1f}s")
                            
                            last_trade_time = time.time()
                            no_trade_council_triggered = False
                            
                            log_print("   ⏳ Waiting for trade result...")
                            result = "UNKNOWN"
                            profit = 0.0
                            entry_spot = 0.0
                            exit_spot = 0.0
                            
                            for _ in range(130):
                                status, profit_val, entry, exit = await trade_engine.check_trade_status(api, contract_id)
                                last_activity_time = time.time()
                                
                                if status != "UNKNOWN" and status != "OPEN":
                                    result = status
                                    profit = profit_val
                                    entry_spot = entry
                                    exit_spot = exit
                                    break
                                await asyncio.sleep(1)
                            
                            slippage = entry_spot - market_price_pre if entry_spot > 0 and market_price_pre > 0 else 0.0
                            price_diff = exit_spot - entry_spot if entry_spot > 0 and exit_spot > 0 else 0.0
                            
                            log_print(f"   📉 [Trade] Entry Spot: {entry_spot} | Mkt Price: {market_price_pre} (Slippage: {slippage:.2f})")
                            log_print(f"   🏆 Result: {result} (${profit}) | Exit: {exit_spot} (Diff: {price_diff:.2f})")
                            
                            last_trade_result = result
                            
                            if result != "UNKNOWN":
                                is_override = details.get("is_override", False)
                                ai_engine.record_trade_result(asset, strategy_name, direction, result, profit, details.get("confidence", 0.0), is_override=is_override)
                                
                                new_balance = await trade_engine.get_balance(api)
                                ds = dashboard_get_state()
                                dashboard_update("balance", new_balance)
                                current_profit = new_balance - ds.get("start_balance", new_balance)
                                dashboard_update("profit", current_profit)
                                await check_global_stop_loss(current_profit)
                                
                                trade_rec = {
                                    "time": datetime.datetime.now().strftime("%H:%M:%S"),
                                    "asset": asset,
                                    "strategy": strategy_name,
                                    "direction": direction,
                                    "amount": amount,
                                    "result": result,
                                    "profit": profit,
                                    "entry_spot": entry_spot,
                                    "exit_spot": exit_spot,
                                    "latency_summary": f"AI:{analyst_lat:.1f}s, Gate:{gate_lat:.1f}s, API:{exec_lat:.1f}s"
                                }
                                
                                if result == "WIN":
                                    dashboard_update("total_wins", ds.get("total_wins", 0) + 1)
                                    dashboard_update("win_streak", ds.get("win_streak", 0) + 1)
                                    dashboard_update("loss_streak", 0)
                                    reset_martingale_state() # [v4.1.0] Reset MG Memory
                                    dashboard_add_trade(trade_rec)
                                    telegram.send_trade_notification(trade_rec, ds.get("balance", 0), ds.get("profit", 0))
                                    
                                elif result == "LOSS":
                                    dashboard_update("total_losses", ds.get("total_losses", 0) + 1)
                                    dashboard_update("loss_streak", ds.get("loss_streak", 0) + 1)
                                    dashboard_update("win_streak", 0)
                                    
                                    # --- [v4.1.0] Persistent Martingale Memory ---
                                    next_mg_step = mg_step + 1
                                    if next_mg_step > getattr(config, "MAX_MARTINGALE_STEPS", 0):
                                        log_print(f"   🛑 Reached Max Martingale Steps ({getattr(config, 'MAX_MARTINGALE_STEPS', 0)}). Resetting stake.")
                                        reset_martingale_state()
                                    else:
                                        save_martingale_state(next_mg_step, amount)
                                        log_print(f"   💾 Saved Martingale State: Step {next_mg_step} carried to next trade.")
                                        
                                    # --- [v4.1.0] Cut and Run Logic ---
                                    log_print(f"   ✂️ CUT AND RUN: 1 Loss detected. Banning {asset} for 1 hour.")
                                    market_engine.blacklist_asset(asset)
                                    last_scan_time = 0 # Force immediate scan to switch assets
                                    
                                    current_loss_streak = ds.get("loss_streak", 0)
                                    loss_limit = getattr(config, "MAX_CONSECUTIVE_LOSS_LIMIT", 3)

                                    # --- [v4.1.6] Institutional Circuit Breaker Logic ---
                                    if current_loss_streak == 1:
                                        # First loss: start the 1-hour observation window
                                        asset_first_loss_time[asset] = time.time()
                                    elif current_loss_streak >= 2:
                                        # Second consecutive loss: check if within 1-hour window
                                        time_since_first_loss = time.time() - asset_first_loss_time.get(asset, 0)
                                        if time_since_first_loss <= 3600:
                                            # 🛑 CIRCUIT BREAKER TRIGGERED
                                            asset_pause_until[asset] = time.time() + 3600
                                            resume_time = datetime.datetime.fromtimestamp(asset_pause_until[asset]).strftime("%H:%M:%S")
                                            log_print("")
                                            log_print("🛑" + "="*60)
                                            log_print(f"🛑 CIRCUIT BREAKER TRIGGERED!")
                                            log_print(f"🛑 2 Losses within 1hr on {asset}. Pausing for 2 hours.")
                                            log_print(f"🛑 Resume Time: {resume_time}")
                                            log_print("🛑" + "="*60)
                                            log_print("")
                                            # Using create_task to prevent blocking the event loop on network issues
                                            asyncio.create_task(send_telegram_alert(f"🛑 CIRCUIT BREAKER: {asset} paused for 2 hours (2 losses within 1hr). Resume at {resume_time}."))
                                            dashboard_update("loss_streak", 0)
                                            dashboard_update("status", f"Circuit Breaker ({asset})")
                                            asset_first_loss_time.pop(asset, None)  # Reset the window
                                        else:
                                            # 2nd loss happened AFTER the 1-hour window: start a new window
                                            asset_first_loss_time[asset] = time.time()
                                    
                                    if getattr(config, "USE_AI_ANALYST", True) and current_loss_streak < loss_limit:
                                        log_print("   📉 Analyzing Loss with AI...")
                                        try:
                                            market_context = await market_engine.get_market_summary_for_ai(api, asset)
                                            analysis_details = decision.get("details", {}).copy()
                                            analysis_result = await ai_engine.analyze_trade_loss(
                                                asset=asset, strategy=strategy_name, signal=direction,
                                                profit=profit, confidence=decision.get("details", {}).get("confidence", 0.0),
                                                market_data_summary=market_context, details=analysis_details,
                                                loss_streak=current_loss_streak
                                            )
                                            if analysis_result:
                                                trade_rec["analysis"] = analysis_result.get("analysis")
                                        except Exception as e:
                                            log_print(f"⚠️ Analysis failed: {e}")

                                    dashboard_add_trade(trade_rec)
                                    
                                    if current_loss_streak >= loss_limit:
                                        log_print(f"🏛️ [AI Council] Consecutive Loss Limit Reached ({current_loss_streak}/{loss_limit})")
                                        msg = f"Consecutive Losses Detected: The bot has lost {current_loss_streak} trades in a row."
                                        res_council = await ai_council.resolve_error(msg, f"Market Alert: {asset} showing consistent losses.")
                                        
                                        if res_council == "USER_APPROVAL_REQUIRED":
                                             paused = True
                                             dashboard_update("status", "Paused (Council Review)")
                                        elif res_council == "ADVICE_GIVEN":
                                             await send_telegram_alert(f"📉 Consecutive Loss Advisory: Bot reached limit on {asset}.")
                                             dashboard_update("loss_streak", 0)
                                             last_trade_time = time.time()
                                        elif res_council == "RESTART_REQUIRED":
                                             os._exit(1)

                                smart = ai_engine.get_smart_trader()
                                wr = smart.perf.get_win_rate()
                                intel = smart.calculate_intelligence_level()
                                dashboard_update("win_rate", f"{wr*100:.1f}%")
                                dashboard_update("intelligence", intel)
            except Exception as e:
                log_print(f"⚠️ Candle logic error: {e}")

        if time.time() - last_summary_time > 3600:
            last_summary_time = time.time()
            ds = dashboard_get_state()
            log_print(f"\n📊 [Hourly Summary] Win: {ds.get('total_wins', 0)} | Loss: {ds.get('total_losses', 0)} | PNL: ${ds.get('profit', 0.0):.2f}")

        now_local = datetime.datetime.now()
        today_str = now_local.strftime("%Y-%m-%d")
        if now_local.hour == 6 and last_daily_summary_date != today_str:
            last_daily_summary_date = today_str
            ds = dashboard_get_state()
            dashboard_add_summary({"type": "DAILY_REPORT", "wins": ds.get('total_wins', 0), "losses": ds.get('total_losses', 0)})

        time_until_scan = (min(last_scan_time + getattr(config, "ASSET_SCAN_INTERVAL_MINS", 60) * 60, last_trade_time + getattr(config, "ASSET_SCAN_INTERVAL_NO_TRADE_MINS", 10) * 60)) - time.time()
        
        icons = ["◐", "◓", "◑", "◒"]
        icon = icons[int(time.time() * 2) % len(icons)]
        status_text = f"📡 [{config.ACTIVE_ASSET}] {config.ACTIVE_PROFILE}"
        
        if df is None:
            status_text += " | ⚠️ Reconnecting..."
        else:
            try:
                current_price = df['close'].iloc[-1]
                status_text += f" | {current_price:.2f}"
            except: pass
            if time_until_scan > 0:
                mins, secs = int(time_until_scan // 60), int(time_until_scan % 60)
                status_text += f" | ⏳ {mins}m {secs}s..."
            else:
                status_text += " | 🔎 Scanning..."

        sys.stdout.write(f"\r   {status_text} {icon}   ")
        sys.stdout.flush()
        await asyncio.sleep(2)

async def main():
    # [v3.11.52] Prefetch THB Rate for Banner
    thb_rate = get_crypto_thb_rate(config.CURRENCY) if getattr(config, "ENABLE_THB_CONVERSION", True) else 0.0
    thb_suffix = lambda val: f" (฿{val * thb_rate:,.2f})" if thb_rate > 0 else ""

    # --- Startup Banner ---
    print("\n" + "="*50)
    log_print(f"🔥 DERIV AI TRADING BOT (V{config.BOT_VERSION})")
    print("="*50)
    log_print(f"   👤 Account: {config.DERIV_ACCOUNT_TYPE.upper()} (App ID: {config.DERIV_APP_ID})")
    log_print(f"   📉 Asset: {config.ACTIVE_ASSET}")
    log_print(f"   🧠 AI Provider: {config.AI_PROVIDER} (Routing: {config.ENABLE_AI_TASK_ROUTING})")
    log_print(f"   ⚙️  Profile: {config.ACTIVE_PROFILE}")
    log_print(f"   💰 Stake: {config.AMOUNT} {config.CURRENCY}{thb_suffix(config.AMOUNT)} (Stop Loss: {config.MAX_DAILY_LOSS_PERCENT}%)")
    if getattr(config, "INITIAL_CAPITAL", 0) > 0:
        log_print(f"   🏦 Capital: {config.INITIAL_CAPITAL} {config.CURRENCY}{thb_suffix(config.INITIAL_CAPITAL)} (Profit Tracking Base)")
    log_print(f"   🏷️  Status: v{config.BOT_VERSION} (AI Council Auto-Fixer)")
    print("="*50 + "\n")
    
    api = DerivAPI(app_id=config.DERIV_APP_ID)
    
    try:
        # [v3.11.28] Run Startup Audit
        run_startup_audit()
        
        # [v3.11.31] Run AI Logic Self-Audit
        ai_engine.run_logic_self_audit()

        # 1. Authorize with enhanced error handling
        log_print("🔐 Attempting API authorization...")
        
        # Validate token format first
        if not config.DERIV_API_TOKEN or len(config.DERIV_API_TOKEN) < 10:
            log_print("❌ Invalid API token format. Please check your DERIV_API_TOKEN in .env")
            return
            
        authorize = await api.authorize(config.DERIV_API_TOKEN)
        if "error" in authorize:
            log_print(f"❌ Authorization Failed: {authorize['error']['message']}")
            if authorize['error']['code'] == 'InvalidToken':
                log_print("   ⚠️ Please check your DERIV_API_TOKEN in .env")
                log_print("   ℹ️ The bot cannot proceed without a valid token.")
                return
            return
            
        log_print(f"✅ Authorized. Balance: {authorize['authorize']['balance']} {config.CURRENCY}{thb_suffix(float(authorize['authorize']['balance']))}")
    except Exception as e:
        if "ResponseError" in str(type(e)):
            log_print(f"❌ API Response Error: {str(e)}")
            log_print("   💡 Possible causes:")
            log_print("   • Invalid or expired API token")
            log_print("   • Network connectivity issues")
            log_print("   • Deriv server maintenance")
            log_print("   • Rate limiting or API quota exceeded")
            log_print("   ℹ️ Please verify your token and try again later")
        else:
            log_print(f"❌ Unexpected error during authorization: {str(e)}")
        return
    
    try:
        balance = float(authorize['authorize']['balance'])
        is_restored = dashboard_init_state(balance)
        if is_restored:
            restored_profit = dashboard_get_state()['profit']
            log_print(f"♻️  Session RESTORED (Profit: {restored_profit:.4f} {config.CURRENCY}{thb_suffix(restored_profit)})")
            await check_global_stop_loss(restored_profit)
        else:
            log_print(f"🆕  New Session Started")
        dashboard_update("status", "Running")
        dashboard_update("ai_provider", config.AI_PROVIDER)
        dashboard_update("account_type", config.DERIV_ACCOUNT_TYPE) # [v3.7.7]
        dashboard_update("bot_start_ts", time.time())
        # Initial Dashboard Asset Name
        initial_asset_name = market_engine.get_asset_name(config.ACTIVE_ASSET)
        dashboard_update("current_asset", initial_asset_name)
        
        # 2. Main Logic Routing
        global last_activity_time
        last_activity_time = time.time()
        asyncio.create_task(watchdog_task())

        if config.DATA_MODE == "POLLING":
            await run_polling_bot(api, thb_suffix, thb_rate)
        elif config.DATA_MODE == "STREAMING":
            await run_streaming_bot(api, thb_suffix)

        return # Exit main after bot completion

    except Exception as e:
        log_print(f"❌ Critical error in main loop: {e}")
        import traceback
        traceback_print = traceback.format_exc()
        log_to_file(traceback_print)
        
        # Trigger AI Council if enabled
        if getattr(config, "ENABLE_AI_COUNCIL", True):
            log_print("🏛️ AI Council: Diagnosing critical error...")
            try:
                await ai_council.resolve_error(str(e), traceback_print)
            except Exception as council_err:
                log_print(f"   ⚠️ AI Council failed: {council_err}")
        
        await asyncio.sleep(5)
last_activity_time = 0

async def watchdog_task():
    """[v4.1.4] Monitors the main loop. If stuck for >240s, kills the process."""
    global last_activity_time
    log_print("   🐕 Watchdog started (timeout: 240s).")
    while True:
        await asyncio.sleep(10)
        if time.time() - last_activity_time > 240:
            msg = "💀 Watchdog: Main loop FROZEN for 240s. No real data received. Killing process to trigger auto-restart."
            log_print(msg)
            log_to_file(msg)
            # Force Kill Process (Auto-restart via run.bat loop)
            os._exit(1) 

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log_print("🛑 Bot Stopped by User")