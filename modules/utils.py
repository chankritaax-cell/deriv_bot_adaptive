"""
🛠️ Utilities Module (Consolidated v2.5.0)
Contains: Logger, Dashboard Connector, News Filter
"""

import os
import json
import time
"""
🛠️ Utilities Module (v3.3.3)
Helper functions for logging, dashboard management, and system operations.
"""
import datetime
import requests
import tempfile
import config

# ============================================================
# 📊 DASHBOARD CONNECTOR
# ============================================================

# [v3.11.25] Align with ROOT_DIR
ROOT = getattr(config, "ROOT_DIR", os.getcwd())
DASHBOARD_STATE_FILE = os.path.join(ROOT, "logs", "dashboard", "dashboard_state.json")
DASHBOARD_LOG_BUFFER_SIZE = 50
TRADE_PERSISTENT_LOG = os.path.join(ROOT, "logs", "trades", "trade_history.jsonl")
SUMMARY_PERSISTENT_LOG = os.path.join(ROOT, "logs", "dashboard", "summary_history.jsonl")

# Global Dashboard State
_dashboard_state = {
    "status": "Starting",
    "updated_at": 0,
    "balance": 0.0,
    "start_balance": 0.0,
    "profit": 0.0,
    "current_asset": "Waiting...",
    "current_strategy": "None",
    "signal": "None",
    "signal_time": "",
    "win_streak": 0,
    "loss_streak": 0,
    "martingale_level": 0,
    "total_wins": 0,
    "total_losses": 0,
    "recent_logs": [],
    "trade_history": [],
    "ai_confidence": 0.0,
    "ai_regime": "UNKNOWN",
    "ai_provider": "---",
    "cooldown_until": 0,
    "cooldown_reason": "",
    "bot_start_ts": 0,
    "last_trade_ts": 0,
    "last_signal": "None",
    "account_type": "demo", # [v3.7.7] Track account type
    "version": config.BOT_VERSION + " (Metrics Logging)",
    "scan_countdown": "---",
    "intelligence": {
        "score": 0,
        "level_name": "Newborn",
        "level_emoji": "🐣",
        "description": "รอการคำนวณ...",
        "components": {},
        "timestamp": ""
    }
}

def safe_config_get(key, default=None):
    """
    [v3.11.28] Safely get a config value by dynamically importing config.
    Prevents NameError/Scope issues in deep modules or hot-reloads.
    """
    try:
        import importlib
        cfg = importlib.import_module("config")
        return getattr(cfg, key, default)
    except:
        # Fallback to already imported config if dynamic fails
        try:
            import config
            return getattr(config, key, default)
        except:
            return default

def dashboard_load_state():
    """Loads existing dashboard state from disk."""
    global _dashboard_state
    if os.path.exists(DASHBOARD_STATE_FILE):
        try:
            with open(DASHBOARD_STATE_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                _dashboard_state.update(saved)
            
            # 🔥 NEW: If trade_history is empty, try to restore from persistent log
            if not _dashboard_state.get("trade_history") or len(_dashboard_state["trade_history"]) == 0:
                print(f"⚠️  [Dashboard Load] trade_history empty, checking persistent log...")
                restored_trades = _restore_trades_from_log()
                if restored_trades:
                    _dashboard_state["trade_history"] = restored_trades[-20:]  # Keep last 20
                    print(f"♻️  [Dashboard Load] Restored {len(restored_trades)} trades from log")
                    
                    # Recalculate stats from restored trades
                    wins = sum(1 for t in restored_trades if t.get("result") == "WIN")
                    losses = len(restored_trades) - wins
                    _dashboard_state["total_wins"] = wins
                    _dashboard_state["total_losses"] = losses
                    print(f"♻️  [Dashboard Load] Recalculated: {wins}W / {losses}L")
            
            return True
        except Exception as e:
            print(f"❌ [Dashboard Load] Error: {e}")
            return False
    return False

def _restore_trades_from_log():
    """Restore trades from persistent append-only log"""
    trades = []
    if not os.path.exists(TRADE_PERSISTENT_LOG):
        return trades
    
    try:
        with open(TRADE_PERSISTENT_LOG, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        trade = json.loads(line)
                        trades.append(trade)
                    except:
                        pass
        print(f"📋 [Restore] Found {len(trades)} trades in persistent log")
    except Exception as e:
        print(f"⚠️  [Restore] Error reading log: {e}")
    
    return trades

def dashboard_init_state(current_balance=0.0):
    global _dashboard_state
    
    # 🔍 Debug: Log file status
    file_exists = os.path.exists(DASHBOARD_STATE_FILE)
    print(f"🔍 [Dashboard Init] State file exists: {file_exists}")
    if file_exists:
        try:
            file_size = os.path.getsize(DASHBOARD_STATE_FILE)
            print(f"🔍 [Dashboard Init] File size: {file_size} bytes")
        except:
            pass
    
    # [v3.11.53] Prefetch THB Rate for Logs
    currency = safe_config_get("CURRENCY", "XRP")
    thb_rate = get_crypto_thb_rate(currency) if safe_config_get("ENABLE_THB_CONVERSION", True) else 0.0
    thb_suffix = lambda val: f" (฿{val * thb_rate:,.2f})" if thb_rate > 0 else ""

    # Attempt to load previous state
    loaded = dashboard_load_state()
    print(f"🔍 [Dashboard Init] Loaded: {loaded}")
    
    if loaded:
        # State exists: Update current balance, but KEEP start_balance & stats
        old_balance = _dashboard_state.get("balance", 0)
        old_start = _dashboard_state.get("start_balance", 0)
        old_profit = _dashboard_state.get("profit", 0)
        trades_count = len(_dashboard_state.get("trade_history", []))
        
        print(f"🔍 [Dashboard Init] Restored state:")
        print(f"   - Old balance: {old_balance:.4f} {currency}{thb_suffix(old_balance)}")
        print(f"   - Start balance: {old_start:.4f} {currency}{thb_suffix(old_start)}")
        print(f"   - Old profit: {old_profit:.4f} {currency}{thb_suffix(old_profit)}")
        print(f"   - Trades count: {trades_count}")
        print(f"   - New API balance: {current_balance:.4f} {currency}{thb_suffix(current_balance)}")
        
        _dashboard_state["balance"] = current_balance
        
        # Ensure start_balance is valid (repair if missing)
        if _dashboard_state.get("start_balance", 0) == 0:
             print(f"⚠️  [Dashboard Init] start_balance was 0, setting to current")
             _dashboard_state["start_balance"] = current_balance
 
        # [v3.6.6] Feature: Override Start Balance with Configured Capital
        config_capital = getattr(config, "INITIAL_CAPITAL", 0)
        if config_capital > 0:
            print(f"💰 [Dashboard Init] Using Configured Capital: {config_capital} {currency}{thb_suffix(config_capital)}")
            _dashboard_state["start_balance"] = config_capital

        # Recalculate profit based on original start_balance
        _dashboard_state["profit"] = _dashboard_state["balance"] - _dashboard_state["start_balance"]
        
        print(f"✅ [Dashboard Init] Calculated profit: {_dashboard_state['profit']:.4f} {currency}{thb_suffix(_dashboard_state['profit'])}")
        
        # Log restoration (internal note)
        dashboard_add_log(f"♻️ Session Restored. Profit: {currency} {_dashboard_state['profit']:.4f}")
    else:
        print(f"🆕 [Dashboard Init] Creating new state")
        # New State
        config_capital = getattr(config, "INITIAL_CAPITAL", 0)
        if config_capital > 0:
            print(f"💰 [Dashboard Init] Start Balance set to Config: {config_capital} {currency}{thb_suffix(config_capital)}")
            _dashboard_state["start_balance"] = config_capital
        else:
            _dashboard_state["start_balance"] = current_balance
            
        _dashboard_state["balance"] = current_balance
        _dashboard_state["profit"] = _dashboard_state["balance"] - _dashboard_state["start_balance"]
        # Reset counters just in case
        _dashboard_state["total_wins"] = 0
        _dashboard_state["total_losses"] = 0
        _dashboard_state["win_streak"] = 0
        _dashboard_state["loss_streak"] = 0
        
    _dashboard_save_state()
    return loaded

def dashboard_update(key, value):
    global _dashboard_state
    _dashboard_state[key] = value
    _dashboard_state["updated_at"] = time.time()
    _dashboard_save_state()

def dashboard_add_log(message):
    global _dashboard_state
    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
    log_entry = f"[{timestamp}] {message}"
    _dashboard_state["recent_logs"].append(log_entry)
    if len(_dashboard_state["recent_logs"]) > DASHBOARD_LOG_BUFFER_SIZE:
        _dashboard_state["recent_logs"] = _dashboard_state["recent_logs"][-DASHBOARD_LOG_BUFFER_SIZE:]
    _dashboard_save_state()

def dashboard_add_trade(trade_rec):
    """Add a trade record to the history (max 20) + persistent log"""
    global _dashboard_state
    if "trade_history" not in _dashboard_state:
        _dashboard_state["trade_history"] = []
    
    # Add to in-memory state
    _dashboard_state["trade_history"].append(trade_rec)
    if len(_dashboard_state["trade_history"]) > 20:
        _dashboard_state["trade_history"] = _dashboard_state["trade_history"][-20:]
    
    # 🔥 NEW: Write to persistent append-only log
    try:
        os.makedirs(os.path.dirname(TRADE_PERSISTENT_LOG), exist_ok=True)
        with open(TRADE_PERSISTENT_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(trade_rec, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())  # Force write to disk NOW
        print(f"💾 [Trade Log] Saved to persistent log")
    except Exception as e:
        print(f"⚠️  [Trade Log] Failed to save: {e}")
    
    _dashboard_save_state()

def _dashboard_save_state():
    try:
        state_dir = os.path.dirname(DASHBOARD_STATE_FILE)
        os.makedirs(state_dir, exist_ok=True)
        temp_file = DASHBOARD_STATE_FILE + f".tmp.{os.getpid()}"
        
        # Clean up stale temp files from previous crashes
        try:
            for f in os.listdir(state_dir):
                if f.endswith(".tmp") or ".tmp." in f:
                    stale = os.path.join(state_dir, f)
                    try: os.remove(stale)
                    except: pass
        except: pass
        
        # Write to temp file
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(_dashboard_state, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        
        # Windows Atomic Replace Retry (with exponential backoff)
        replaced = False
        for attempt in range(5):
            try:
                os.replace(temp_file, DASHBOARD_STATE_FILE)
                replaced = True
                break
            except (PermissionError, OSError):
                time.sleep(0.05 * (2 ** attempt))
        
        # Fallback: direct write if atomic replace keeps failing
        if not replaced:
            try: os.remove(temp_file)
            except: pass
            with open(DASHBOARD_STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(_dashboard_state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Error saving dashboard state: {e}")
        # Last resort cleanup
        try: os.remove(temp_file)
        except: pass

def dashboard_get_state():
    """Returns the current internal dashboard state."""
    global _dashboard_state
    return _dashboard_state


# ============================================================
# 🕯️ CANDLE DATA FOR DASHBOARD CHART
# ============================================================

CANDLE_DATA_FILE = os.path.join(ROOT, "logs", "dashboard", "candle_data.json")
_candle_last_save = 0

def dashboard_save_candles(asset, candles_df):
    """Save candle OHLC data for dashboard chart (throttled: max once per 5s)."""
    global _candle_last_save
    now = time.time()
    if now - _candle_last_save < 5:
        return
    _candle_last_save = now
    
    try:
        if candles_df is None or len(candles_df) == 0:
            return
        
        # Convert DataFrame to lightweight-charts format
        records = []
        for _, row in candles_df.iterrows():
            records.append({
                "time": int(row.get("from", row.get("at", 0))),
                "open": round(float(row["open"]), 6),
                "high": round(float(row["max"]), 6),
                "low": round(float(row["min"]), 6),
                "close": round(float(row["close"]), 6),
            })
        
        # Keep last 100 candles
        records = records[-100:]
        
        payload = {
            "asset": asset,
            "updated_at": now,
            "candles": records
        }
        
        state_dir = os.path.dirname(CANDLE_DATA_FILE)
        os.makedirs(state_dir, exist_ok=True)
        temp_file = CANDLE_DATA_FILE + f".tmp.{os.getpid()}"
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        
        for attempt in range(3):
            try:
                os.replace(temp_file, CANDLE_DATA_FILE)
                break
            except (PermissionError, OSError):
                time.sleep(0.05 * (2 ** attempt))
        else:
            try: os.remove(temp_file)
            except: pass
    except Exception as e:
        pass

# ============================================================
# 📝 LOGGER
# ============================================================

def dashboard_add_summary(summary_data):
    """[v3.11.46] Appends a periodic performance summary to a persistent log for Telegram bridge."""
    try:
        os.makedirs(os.path.dirname(SUMMARY_PERSISTENT_LOG), exist_ok=True)
        summary_data["timestamp"] = time.time()
        with open(SUMMARY_PERSISTENT_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(summary_data) + "\n")
    except Exception as e:
        print(f"⚠️ Error logging summary: {e}")

def log_to_file(message):
    """บันทึกข้อความลงไฟล์ log แบบแยกวันที่"""
    now = datetime.datetime.now()
    timestamp = now.strftime("%Y-%m-%d %H:%M:%S")
    date_str = now.strftime("%Y-%m-%d")
    
    filename = f"trading_log_{date_str}.txt"
    log_dir = os.path.join(ROOT, "logs", "trading")
    filepath = os.path.join(log_dir, filename)
    os.makedirs(log_dir, exist_ok=True)
    log_msg = f"[{timestamp}] {message}"
    
    try:
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(log_msg + "\n")
            
        # Backup Log (if configured)
        if getattr(config, "BACKUP_LOG_PATH", ""):
            backup_dir = config.BACKUP_LOG_PATH
            if not os.path.exists(backup_dir):
                os.makedirs(backup_dir, exist_ok=True)
                
            backup_file = os.path.join(backup_dir, "trading", filename)
            os.makedirs(os.path.join(backup_dir, "trading"), exist_ok=True)
            with open(backup_file, "a", encoding="utf-8") as f_backup:
                f_backup.write(log_msg + "\n")
                
    except Exception as e:
        print(f"⚠️ Write log error: {e}")


def log_print(msg, end="\n", flush=False):
    """Print with timestamp + mirror to console log file + dashboard"""
    try:
        timestamp = datetime.datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
        formatted_msg = f"{timestamp} {msg}"
        print(formatted_msg, end=end, flush=flush)
        
        # Mirror to console log file
        date_str = datetime.datetime.now().strftime("%Y-%m-%d")
        filename = f"console_log_{date_str}.txt"
        log_dir = os.path.join(ROOT, "logs", "console")
        filepath_c = os.path.join(log_dir, filename)
        os.makedirs(log_dir, exist_ok=True)
        with open(filepath_c, "a", encoding="utf-8") as f:
            f.write(formatted_msg + end)
            
        # Hook to Dashboard
        dashboard_add_log(msg)
    except:
        pass



# ============================================================
# 📊 STRUCTURED METRICS LOGGER (JSONL)
# ============================================================

_METRICS_DEFAULT_PATH = os.path.join(ROOT, "logs", "metrics", "trade_metrics.jsonl")

def metrics_log(event: str, payload: dict, *, also_print: bool = False):
    """Append a structured record to JSONL for later winrate/feature analysis."""
    try:
        if not getattr(config, "ENABLE_METRICS_LOGGING", False):
            return

        path = getattr(config, "METRICS_LOG_PATH", _METRICS_DEFAULT_PATH)
        os.makedirs(os.path.dirname(path), exist_ok=True)

        record = {
            "ts": datetime.datetime.now().isoformat(timespec="seconds"),
            "event": str(event),
        }
        if isinstance(payload, dict):
            record.update(payload)

        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            f.flush()
            try:
                os.fsync(f.fileno())
            except Exception:
                pass

        if also_print:
            short_keys = ["event","asset","strategy","signal","price","rsi14","ema9","ema21","atr14","l2_confirmation","bet_mult","amount","contract_id","result","profit"]
            short = {k: record.get(k) for k in short_keys if k in record}
            log_print(f"   📊 [METRICS] {short}")

    except Exception:
        # never break trading loop because of logging
        pass


# ============================================================
# 📰 NEWS FILTER
# ============================================================

def check_news():
    """เช็คข่าวจาก ForexFactory ว่ามีข่าวแดงในช่วงนี้หรือไม่"""
    if not config.USE_NEWS_FILTER:
        return False, None

    try:
        url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                          'AppleWebKit/537.36 (KHTML, like Gecko) '
                          'Chrome/58.0.3029.110 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code != 200:
            log_print(f"⚠️ News Filter: API returned status {response.status_code} (Rate Limit or Down). Skipping...")
            return False, None

        news_list = response.json()
        now = datetime.datetime.now(datetime.timezone.utc)
        
        for item in news_list:
            if item['country'] not in config.NEWS_CURRENCIES: continue
            if item['impact'] not in config.NEWS_IMPACT_FILTER: continue
            
            try:
                news_time = datetime.datetime.fromisoformat(item['date'])
                if news_time.tzinfo is None:
                    news_time = news_time.replace(tzinfo=datetime.timezone.utc)
                else:
                    news_time = news_time.astimezone(datetime.timezone.utc)

                lower_bound = news_time - datetime.timedelta(minutes=config.NEWS_PAUSE_MINUTES_BEFORE)
                upper_bound = news_time + datetime.timedelta(minutes=config.NEWS_PAUSE_MINUTES_AFTER)
                
                if lower_bound <= now <= upper_bound:
                    return True, item['title']
                    
            except Exception:
                continue
                
    except Exception as e:
        log_print(f"⚠️ Check News Error: {e}")
        return False, None

    return False, None


# ============================================================
# 💹 CURRENCY CONVERSION (v3.11.52)
# ============================================================

_thb_rate_cache = {"rate": 0.0, "time": 0}

def get_crypto_thb_rate(symbol="XRP"):
    """
    Fetches real-time crypto/fiat to THB rate with 10-minute caching.
    Uses CoinGecko as the primary source.
    """
    global _thb_rate_cache
    now = time.time()
    
    # Check cache (10 mins)
    if _thb_rate_cache.get("symbol") == symbol and (now - _thb_rate_cache.get("time", 0) < 600):
        return _thb_rate_cache["rate"]

    # Mapping of symbol to CoinGecko ID
    cg_ids = {
        "XRP": "ripple",
        "USD": "usd-coin", # Proxy for USD
        "USDT": "tether"
    }
    cg_id = cg_ids.get(symbol.upper(), "ripple")
    
    fallback_key = f"{symbol.upper()}_THB_RATE_FALLBACK"
    fallback = safe_config_get(fallback_key, 20.0)
    
    if not safe_config_get("ENABLE_THB_CONVERSION", True):
        return fallback

    try:
        # CoinGecko Simple Price API
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={cg_id}&vs_currencies=thb"
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            data = response.json()
            rate = data.get(cg_id, {}).get("thb", 0)
            if rate > 0:
                _thb_rate_cache = {"rate": float(rate), "time": now, "symbol": symbol}
                return float(rate)
    except Exception as e:
        print(f"⚠️ Error fetching {symbol}/THB rate: {e}")

    return fallback

# ============================================================
# 💾 MARTINGALE STATE PERSISTENCE 
# ============================================================
TRADE_STATE_FILE = os.path.join(ROOT, "logs", "dashboard", "trade_state.json")

def load_martingale_state():
    """Load persistent Martingale state safely."""
    if os.path.exists(TRADE_STATE_FILE):
        try:
            with open(TRADE_STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                saved_acct = data.get("account_type", "demo")  # [v5.0 BUG-11 FIX]
                current_acct = getattr(config, "DERIV_ACCOUNT_TYPE", "demo")
                if saved_acct != current_acct:
                    log_print(f"⚠️ Martingale state account_type mismatch ({saved_acct} vs {current_acct}) — resetting")
                    return 0, getattr(config, "AMOUNT", 1.0)
                return data.get("mg_step", 0), data.get("current_stake", getattr(config, "AMOUNT", 1.0))
        except Exception as e:
            log_print(f"⚠️ Failed to load Martingale state: {e}")
    return 0, getattr(config, "AMOUNT", 1.0)

def save_martingale_state(mg_step, current_stake):
    """Save persistent Martingale state safely."""
    try:
        os.makedirs(os.path.dirname(TRADE_STATE_FILE), exist_ok=True)
        temp_file = TRADE_STATE_FILE + f".tmp.{os.getpid()}"
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump({  # [v5.0 BUG-11 FIX]
                "mg_step": mg_step,
                "current_stake": current_stake,
                "account_type": getattr(config, "DERIV_ACCOUNT_TYPE", "demo"),
            }, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        for attempt in range(3):
            try:
                os.replace(temp_file, TRADE_STATE_FILE)
                break
            except (PermissionError, OSError):
                time.sleep(0.05 * (2 ** attempt))
        else:
            try: os.remove(temp_file)
            except: pass
    except Exception as e:
         log_print(f"⚠️ Failed to save Martingale state: {e}")

def reset_martingale_state():
    """Reset persistent Martingale state to default."""
    save_martingale_state(0, getattr(config, "AMOUNT", 1.0))

# ============================================================
# 🛡️ ATOMIC JSON WRITER (V5.0 SAFEGUARD)
# ============================================================
def save_json_atomic(data: dict, path: str):
    """Save dictionary to JSON atomically to prevent corruption if process is killed mid-write."""
    try:
        dir_name = os.path.dirname(path)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)
            
        with tempfile.NamedTemporaryFile('w', dir=dir_name, delete=False, encoding='utf-8') as tf:
            json.dump(data, tf, ensure_ascii=False, indent=2)
            tf.flush()
            os.fsync(tf.fileno())  # [v5.0 BUG-10 FIX] guarantee disk write before atomic rename
            temp_name = tf.name
            
        # Windows atomic replace retry (exponential backoff)
        for attempt in range(5):
            try:
                os.replace(temp_name, path)
                break
            except (PermissionError, OSError):
                time.sleep(0.05 * (2 ** attempt))
        else:
            try: os.remove(temp_name)
            except: pass
    except Exception as e:
        log_print(f"⚠️ Failed atomic save to {path}: {e}")

def load_json_safe(path: str, default_schema: dict):
    """Load JSON from disk safely, recovering with a default schema if corrupted/missing."""
    if not os.path.exists(path):
        return default_schema
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data
    except (json.JSONDecodeError, FileNotFoundError) as e:
        log_print(f"⚠️ JSON load corrupted/missing {path}: {e}. Returning default schema.")
        return default_schema
    except Exception as e:
        log_print(f"⚠️ JSON load error {path}: {e}. Returning default schema.")
        return default_schema


def update_asset_profile_atomic(asset_name: str, new_settings: dict):
    """
    [v5.0] Atomic Asset Profile Update Engine.
    Securely updates asset_profiles.json with validation, backup, and crash-safety.
    """
    import shutil
    
    # 1. Validation Logic
    if not isinstance(new_settings, dict):
        log_print(f"❌ [Update Error] new_settings must be a dictionary for {asset_name}")
        return False
    
    mandatory_keys = ['strategy', 'rsi_bounds']
    missing_keys = [k for k in mandatory_keys if k not in new_settings]
    if missing_keys:
        log_print(f"❌ [Update Error] Missing mandatory keys {missing_keys} for profile: {asset_name}")
        return False

    profile_path = os.path.join(ROOT, "asset_profiles.json")
    backup_dir = os.path.join(ROOT, "logs", "backups")
    os.makedirs(backup_dir, exist_ok=True)
    
    # 2. Backup Current State
    if os.path.exists(profile_path):
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = os.path.join(backup_dir, f"asset_profiles_{ts}.json.bak")
        try:
            shutil.copy2(profile_path, backup_path)
            log_print(f"📦 [Backup] Current profiles backed up to: {os.path.basename(backup_path)}")
        except Exception as e:
            log_print(f"⚠️ [Backup Warning] Could not create backup: {e}")

    # 3. Process Update
    try:
        # Load existing data to merge or replace
        data = load_json_safe(profile_path, {})
        old_profile = data.get(asset_name, {})
        
        # Log Differences (Old vs. New)
        log_print(f"🔍 [Update Analysis] Reviewing changes for {asset_name}:")
        all_keys = set(list(old_profile.keys()) + list(new_settings.keys()))
        for key in sorted(all_keys):
            old_val = old_profile.get(key)
            new_val = new_settings.get(key)
            if old_val != new_val:
                log_print(f"   • {key}: {old_val} -> {new_val}")
        
        # Apply change
        data[asset_name] = new_settings
        
        # 4. Atomic Write Sequence
        dir_name = os.path.dirname(profile_path)
        with tempfile.NamedTemporaryFile('w', dir=dir_name, delete=False, encoding='utf-8', suffix='.tmp') as tf:
            json.dump(data, tf, ensure_ascii=False, indent=4)
            tf.flush()
            os.fsync(tf.fileno()) # Force physical write
            temp_name = tf.name

        # Permission/Retry Logic for Windows
        for attempt in range(5):
            try:
                os.replace(temp_name, profile_path)
                break
            except (PermissionError, OSError) as e:
                log_print(f"⚠️ [Write Retry] Lock detected on {asset_name}. Retry {attempt+1}/5...")
                time.sleep(0.1 * (2 ** attempt))
        else:
            raise OSError(f"Could not replace {profile_path} after 5 attempts.")

        log_print(f"✅ [Update Success] {asset_name} profile updated and verified atomically.")
        
        # 5. Hot Reload: Reload config to refresh cached ASSET_STRATEGY_MAP
        try:
            import importlib
            import config
            importlib.reload(config)
            log_print("🔄 [Hot Reload] config.ASSET_STRATEGY_MAP refreshed.")
        except Exception as e:
            log_print(f"⚠️ [Reload Warning] Failed to hot-reload config: {e}")
            
        return True

    except Exception as e:
        log_print(f"❌ [Critical Error] Atomic write failed for {asset_name}: {e}")
        if 'temp_name' in locals() and os.path.exists(temp_name):
            try: os.remove(temp_name)
            except: pass
        return False