
import asyncio
import datetime
import pandas as pd
import config
from modules.smart_trader import SmartTrader
from modules.technical_analysis import TechnicalConfirmation
from modules.utils import log_print

class AssetSelector:
    """
    [v3.11.0] Handles dynamic asset selection based on recent performance.
    Runs a mini-backtest on available assets to find the one with highest win rate.
    """

    @staticmethod
    async def find_best_asset(api, lookback_hours=12, min_trades=10):
        """
        Scans all volatility assets in config.ASSETS_VOLATILITY.
        Returns: (best_asset, win_rate, details_dict)
        """
        now = datetime.datetime.now()
        start_dt = now - datetime.timedelta(hours=lookback_hours)
        start_epoch = int(start_dt.timestamp())
        end_epoch = int(now.timestamp())
        
        candidates = []
        # Use only Volatility Indices for now (exclude weak ones if needed, but scan all for discovery)
        assets_to_scan = config.ASSETS_VOLATILITY 
        
        log_print(f"🕵️ [Asset Selector] Scanning {len(assets_to_scan)} assets (Last {lookback_hours}h)...")
        
        for asset in assets_to_scan:
            try:
                # [v5.0 FIX-A] Skip disabled assets BEFORE fetching history
                # Prevents wasting API calls + AI calls on assets with enabled=false
                _profile_check = config.get_asset_profile(asset)
                if _profile_check.get("_disabled", False):
                    log_print(f"   ⏭️ [Asset Selector] {asset} skipped — disabled in profile ({_profile_check.get('_disabled_reason', 'no reason')})")
                    continue

                # 1. Fetch History
                # We need enough candles for indicators (50) + backtest range
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
                
                # 2. Run Simulation
                # Use a fresh SmartTrader instance to not pollute global stats
                st = SmartTrader() 
                if "strategy_stats" not in st.perf.data:
                    st.perf.data["strategy_stats"] = {}
                
                signals = 0
                wins = 0
                
                # Iterate through history
                # Ensure we have enough data for indicators (start from index 50)
                for i in range(50, len(df) - 1):
                    ts = df.index[i]
                    if ts.timestamp() < start_epoch: continue
                    
                    sl = df.iloc[i-50:i+1]
                    future = df.iloc[i+1]
                    
                    for direction in ["CALL", "PUT"]:
                        if direction == "PUT" and not getattr(config, "ALLOW_PUT_SIGNALS", True): continue
                        
                        try:
                            # Use class directly to avoid import issues
                            score, _ = await TechnicalConfirmation.get_confirmation_score(None, asset, direction, sl)
                        except Exception:  # [v5.0 FIX] bare except causes Python 3.12 UnboundLocalError
                            continue
                            
                        if score >= 0.7:
                             # Simulate Entry check
                            strategy = "AI_MOMENTUM"
                            # [v3.11.3] Pass api=None to disable network-heavy MTF checks during simulation
                            should_enter, _, details = await st.should_enter(None, asset, strategy, direction, confidence=score, df_1m=sl)
                            
                            if should_enter:
                                signals += 1
                                entry = sl.iloc[-1]['close']
                                exit_p = future['close']
                                is_win = (direction == "CALL" and exit_p > entry) or \
                                         (direction == "PUT" and exit_p < entry)
                                
                                if is_win: wins += 1
                
                # 3. Calculate Stats
                wr = (wins / signals * 100) if signals > 0 else 0
                
                if signals >= min_trades:
                    candidates.append({
                        "asset": asset,
                        "wr": wr,
                        "trades": signals
                    })
                    log_print(f"   📊 {asset}: {wr:.1f}% WR ({signals} trades)")
                else:
                     # Log low volume assets debug only
                     pass

            except Exception as e:
                log_print(f"   ⚠️ Error scanning {asset}: {e}")
                continue

        # 4. Rank Candidates
        if not candidates:
            return None, 0, "No valid assets found"
            
        # Sort by Win Rate desc, then Trades desc
        candidates.sort(key=lambda x: (x["wr"], x["trades"]), reverse=True)
        best = candidates[0]
        
        return best["asset"], best["wr"], candidates

