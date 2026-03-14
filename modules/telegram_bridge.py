"""
ðŸ“± Telegram Bridge (v3.7.9)
Bridging the gap between you and your Deriv Bot.
"""

import os
import time
import json
import asyncio
import logging
import html
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, CallbackQueryHandler
import config
from .ai_providers import call_ai_raw_with_failover # [v3.7.2] For /sumlog summary
from .utils import get_crypto_thb_rate # [v3.11.52] Real-time conversion

# Setup Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

import psutil # [v3.11.33] To check if PID is still alive

# [v3.11.25] Align with ROOT_DIR
ROOT = getattr(config, "ROOT_DIR", os.getcwd())
BRIDGE_LOCK_FILE = os.path.join(ROOT, "logs", ".bridge.lock")
DASHBOARD_STATE_FILE = os.path.join(ROOT, "logs", "dashboard", "dashboard_state.json")
COMMAND_FILE = os.path.join(ROOT, "logs", "commands.json")
PENDING_FILE = os.path.join(ROOT, "logs", "council", "pending_proposals.json")
BRIDGE_CHECKPOINT_FILE = os.path.join(ROOT, "logs", "bridge_checkpoint.json")

def _html_escape(text):
    safe = html.escape("" if text is None else str(text))
    # Defensive escapes for Telegram HTML parse stability
    safe = safe.replace("_", "&#95;").replace("*", "&#42;")
    return safe

def _load_bridge_checkpoint():
    try:
        if os.path.exists(BRIDGE_CHECKPOINT_FILE):
            with open(BRIDGE_CHECKPOINT_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
    except Exception:
        pass
    return {"last_pos": 0, "last_ts": 0.0}

def _save_bridge_checkpoint(last_pos=None, last_ts=None):
    try:
        os.makedirs(os.path.dirname(BRIDGE_CHECKPOINT_FILE), exist_ok=True)
        data = _load_bridge_checkpoint()
        if last_pos is not None:
            data["last_pos"] = int(last_pos)
        if last_ts is not None:
            data["last_ts"] = float(last_ts)
        with open(BRIDGE_CHECKPOINT_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def _acquire_bridge_lock():
    """Ensures only one instance of the bridge is running (PID lock)."""
    try:
        os.makedirs(os.path.dirname(BRIDGE_LOCK_FILE), exist_ok=True)
        if os.path.exists(BRIDGE_LOCK_FILE):
            with open(BRIDGE_LOCK_FILE, "r") as f:
                try:
                    old_pid = int(f.read().strip())
                    if psutil.pid_exists(old_pid):
                        try:
                            proc = psutil.Process(old_pid)
                            name = (proc.name() or "").lower()
                            cmdline = " ".join(proc.cmdline()).lower()
                            is_python = ("python" in name) or ("python" in cmdline)
                            is_bridge = "telegram_bridge" in cmdline
                            if is_python and is_bridge:
                                print(f"âŒ Error: Telegram Bridge already running (PID {old_pid}). Exiting.")
                                return False
                        except Exception:
                            # If we can't inspect the process, be conservative and avoid double-run
                            print(f"âŒ Error: Telegram Bridge already running (PID {old_pid}). Exiting.")
                            return False
                except:
                    pass
        
        # Write current PID
        with open(BRIDGE_LOCK_FILE, "w") as f:
            f.write(str(os.getpid()))
        return True
    except Exception as e:
        print(f"âš ï¸ Lock warning: {e}")
        return True # Fallback to continue if we can't write lock

def _release_bridge_lock():
    """Cleans up the lock file on exit."""
    try:
        if os.path.exists(BRIDGE_LOCK_FILE):
            os.remove(BRIDGE_LOCK_FILE)
    except: pass

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/start command: Resume bot."""
    await update.message.reply_text("ðŸš€ Sending START command to bot...")
    _send_command("START")

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/stop command: Pause bot."""
    await update.message.reply_text("ðŸ›‘ Sending STOP command to bot...")
    _send_command("STOP")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/status command: Show bot status."""
    try:
        if not os.path.exists(DASHBOARD_STATE_FILE):
            await update.message.reply_text("âš ï¸ Dashboard state file not found. Is the bot running?")
            return

        with open(DASHBOARD_STATE_FILE, 'r', encoding='utf-8') as f:
            state = json.load(f)

        profit = state.get("profit", 0.0)
        balance = state.get("balance", 0.0)
        win_rate = state.get("win_rate", "0%")
        asset = state.get("current_asset", "Unknown")
        intel = state.get("intelligence", {}).get("level_name", "Unknown")
        acc_type = state.get("account_type", "demo").upper()
        
        icon = "ðŸ’°" if acc_type == "REAL" else "ðŸ§ª"
        
        # [v3.11.52] Currency Formatting (XRP to THB)
        currency = getattr(config, "CURRENCY", "XRP")
        if getattr(config, "ENABLE_THB_CONVERSION", True):
            thb_rate = await asyncio.to_thread(get_crypto_thb_rate, currency)
        else:
            thb_rate = 0.0
        
        balance_thb_str = f" (à¸¿{(balance * thb_rate):,.2f})" if thb_rate > 0 else ""
        profit_thb_str = f" (à¸¿{(profit * thb_rate):,.2f})" if thb_rate > 0 else ""

        msg = (
            f"ðŸ¤– **Deriv Bot Status** ({icon} `{acc_type}`)\n"
            f"Target: `{asset}`\n"
            f"Balance: `{balance:.4f} {currency}`{balance_thb_str}\n"
            f"Profit Today: `{profit:+.4f} {currency}`{profit_thb_str} ({'âœ…' if profit >= 0 else 'âŒ'})\n"
            f"Win Rate: `{win_rate}`\n"
            f"Brain: {intel}\n"
            f"Last Update: {time.ctime(state.get('updated_at', 0))}"
        )
        await update.message.reply_markdown(msg)

    except Exception as e:
        await update.message.reply_text(f"âŒ Error reading status: {e}")

async def logcon(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/logcon command: Show last 30 lines of console log."""
    try:
        date_str = time.strftime("%Y-%m-%d")
        log_file = os.path.join(ROOT, "logs", "console", f"console_log_{date_str}.txt")
        
        if not os.path.exists(log_file):
            await update.message.reply_text("âš ï¸ Console log not found for today.")
            return

        with open(log_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            last_lines = lines[-30:] # Last 30 lines
        
        msg = "".join(last_lines)
        # Split message if too long for Telegram (4096 chars)
        if len(msg) > 4000:
            msg = "..." + msg[-4000:]
            
        await update.message.reply_text(f"ðŸ“‘ **Console Logs (Last 30 lines):**\n```\n{msg}\n```", parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f"âŒ Error reading logs: {e}")

async def sumlog(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/sumlog command: Summarize latest console logs using AI."""
    await update.message.reply_text("ðŸ” Reading and summarizing latest logs... Please wait.")
    
    try:
        log_content = _get_latest_run_log()
        if not log_content:
            await update.message.reply_text("âš ï¸ No recent logs found for the current run.")
            return
            
        # [v3.7.2] Define Prompt for AI Summary
        prompt = f"""
        Extract key events from the following Deriv Trading Bot console logs.
        Focus on:
        1. Startup status (Login, Balance, etc.)
        2. Signal detections and AI Confidence scores.
        3. Trade results (Profit/Loss).
        4. Any errors, warnings, or AI Council interventions.

        LOGS:
        {log_content}

        Summarize in Thai language using bullet points and emojis. Keep it concise.
        """
        
        summary = call_ai_raw_with_failover(prompt, task_name="LOG_SUMMARY")
        
        if not summary:
            await update.message.reply_text("âŒ Failed to generate log summary using AI.")
            return

        await update.message.reply_markdown(f"ðŸ“‹ **à¸ªà¸£à¸¸à¸›à¸à¸²à¸£à¸—à¸³à¸‡à¸²à¸™à¸¥à¹ˆà¸²à¸ªà¸¸à¸” (Log Summary)**\n\n{summary}")

    except Exception as e:
        await update.message.reply_text(f"âŒ Error during /sumlog: {e}")

async def council_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/council command: Send instruction to AI Council."""
    if not context.args:
        await update.message.reply_text("ðŸ›ï¸ Please provide a command, e.g., `/council change stake to 1.0`", parse_mode='Markdown')
        return
    
    cmd_text = " ".join(context.args)
    
    # [v3.7.9] Direct AI Provider Targeting (e.g., /council @gemini analyze)
    target_provider = None
    if cmd_text.startswith("@"):
        parts = cmd_text.split(" ", 1)
        potential_target = parts[0][1:] # Remove @
        if potential_target:
            target_provider = potential_target
            cmd_text = parts[1] if len(parts) > 1 else ""
    
    if target_provider:
        payload = json.dumps({"text": cmd_text, "target": target_provider})
        await update.message.reply_text(f"ðŸ›ï¸ Forwarding to **{target_provider}**: `{cmd_text}`", parse_mode='Markdown')
        _send_command("COUNCIL", payload=payload)
    else:
        await update.message.reply_text(f"ðŸ›ï¸ Forwarding to AI Council: `{cmd_text}`", parse_mode='Markdown')
        _send_command("COUNCIL", payload=cmd_text)

async def logs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/logs command: List log files in logs/console for download."""
    try:
        log_dir = os.path.join(ROOT, "logs", "console")
        if not os.path.isdir(log_dir):
            await update.message.reply_text("âš ï¸ Log directory not found.")
            return

        files = sorted(
            [f for f in os.listdir(log_dir) if f.endswith(".txt")],
            reverse=True  # newest first
        )

        if not files:
            await update.message.reply_text("âš ï¸ No log files found.")
            return

        # Build inline keyboard (1 button per row, max 10 files)
        keyboard = []
        for f in files[:10]:
            size_bytes = os.path.getsize(os.path.join(log_dir, f))
            if size_bytes >= 1024 * 1024:
                size_str = f"{size_bytes / (1024*1024):.1f}MB"
            else:
                size_str = f"{size_bytes / 1024:.0f}KB"
            keyboard.append([InlineKeyboardButton(f"ðŸ“„ {f} ({size_str})", callback_data=f"DL|{f}")])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("ðŸ“‚ **à¹€à¸¥à¸·à¸­à¸à¹„à¸Ÿà¸¥à¹Œ log à¸—à¸µà¹ˆà¸•à¹‰à¸­à¸‡à¸à¸²à¸£ download:**", reply_markup=reply_markup, parse_mode='Markdown')

    except Exception as e:
        await update.message.reply_text(f"âŒ Error listing logs: {e}")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle approval/rejection/download button clicks."""
    query = update.callback_query
    await query.answer()
    
    data = query.data # format: "APPROVE|prop_id" or "REJECT|prop_id" or "DL|filename"
    if "|" not in data: return
    
    action, prop_id = data.split("|", 1)
    
    if action == "DL":
        # --- Download log file ---
        filename = prop_id
        # Security: prevent path traversal
        if ".." in filename or "/" in filename or "\\" in filename:
            await query.edit_message_text(text="âŒ Invalid filename.")
            return
        file_path = os.path.join(ROOT, "logs", "console", filename)
        if not os.path.isfile(file_path):
            await query.edit_message_text(text=f"âš ï¸ File not found: `{filename}`", parse_mode='Markdown')
            return
        try:
            await query.edit_message_text(text=f"ðŸ“¤ Sending `{filename}`...", parse_mode='Markdown')
            with open(file_path, 'rb') as f:
                await query.message.reply_document(document=f, filename=filename)
        except Exception as e:
            await query.message.reply_text(f"âŒ Failed to send file: {e}")
        return
    elif action == "APPROVE":
        _send_command("APPROVE", payload=prop_id)
        await query.edit_message_text(text=f"âœ… **Approved Proposal:** `{prop_id}`\nProcessing...", parse_mode='Markdown')
    elif action == "REJECT":
        _send_command("REJECT", payload=prop_id)
        await query.edit_message_text(text=f"âŒ **Rejected Proposal:** `{prop_id}`", parse_mode='Markdown')

def _get_latest_run_log():
    """Finds current day console log and extracts the latest run session."""
    try:
        date_str = time.strftime("%Y-%m-%d")
        log_file = os.path.join("logs", "console", f"console_log_{date_str}.txt")
        
        if not os.path.exists(log_file):
            return None

        with open(log_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # Find the last "Startup Banner" occurrence
        # The banner in bot.py contains "ðŸ”¥ DERIV AI TRADING BOT"
        marker = "ðŸ”¥ DERIV AI TRADING BOT"
        sessions = content.split(marker)
        
        if len(sessions) < 2:
            return content[-2000:] # Fallback to last 2000 chars if no marker found

        latest_run = sessions[-1]
        
        # [v3.7.3] Include tail of previous session if current session is short OR to see restart reason
        prev_context = ""
        if len(sessions) >= 2:
            prev_context = f"\n--- [CONTEXT FROM PREVIOUS RUN (Restart Reason?)] ---\n...{sessions[-2][-2000:]}\n\n"
            
        full_session = prev_context + marker + latest_run
        return full_session[-6000:] # Increased limit for better context awareness
        
    except Exception as e:
        logging.error(f"Error in _get_latest_run_log: {e}")
        return None

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "ðŸ› ï¸ **Telegram Commander**\n"
        "/start - Resume trading\n"
        "/stop - Pause trading\n"
        "/status - Check bot health\n"
        "/sumlog - Summarize recent logs (AI)\n"
        "/logcon - See raw console logs\n"
        "/logs - Download log files\n"
        "/council <cmd> - Command AI Council\n"
        "/help - Show this menu"
    )
    await update.message.reply_markdown(msg)

def _send_command(cmd, payload=None):
    """Writes command to shared file."""
    try:
        data = {"command": cmd, "timestamp": time.time(), "source": "TELEGRAM"}
        if payload:
            data["payload"] = payload
        with open(COMMAND_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f)
    except Exception as e:
        logging.error(f"Failed to write command: {e}")

TRADE_LOG = os.path.join(ROOT, "logs", "trades", "trade_history.jsonl")
SUMMARY_LOG = os.path.join(ROOT, "logs", "dashboard", "summary_history.jsonl")
COUNCIL_LOG = os.path.join(ROOT, "logs", "council", "history.json")

# Inactivity tracking
LAST_TRADE_TIME = time.time()
LAST_INACTIVITY_REPORT = 0

async def monitor_pending(application):
    """Background task to monitor pending proposals and alert user with buttons."""
    if not getattr(config, "ENABLE_TELEGRAM_NOTIFICATIONS", False) or not config.TELEGRAM_CHAT_ID:
        return

    last_known_pending = set()
    # Sync to current pending to avoid spamming old history on restart
    if os.path.exists(PENDING_FILE):
        try:
            with open(PENDING_FILE, 'r', encoding='utf-8') as f:
                last_known_pending = set(json.load(f).keys())
        except: pass

    logging.info(f"ðŸ›ï¸ Pending monitor loop started (Initial: {len(last_known_pending)})")

    while True:
        try:
            if os.path.exists(PENDING_FILE):
                with open(PENDING_FILE, 'r', encoding='utf-8') as f:
                    pending = json.load(f)
                
                current_ids = set(pending.keys())
                new_ids = current_ids - last_known_pending
                
                for pid in new_ids:
                    prop_data = pending[pid]
                    proposal = prop_data.get("proposal", {})
                    title = proposal.get("title", "No Title")
                    expl = proposal.get("explanation", "No explanation")
                    
                    keyboard = [
                        [
                            InlineKeyboardButton("âœ… Approve", callback_data=f"APPROVE|{pid}"),
                            InlineKeyboardButton("âŒ Reject", callback_data=f"REJECT|{pid}")
                        ]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    msg = (
                        f"ðŸ›ï¸ **AI Council: NEW PROPOSAL PENDING**\n"
                        f"ðŸ†” **ID:** `{pid}`\n"
                        f"ðŸ“ **Title:** `{title}`\n\n"
                        f"ðŸ’¡ **Explanation:** {expl}\n\n"
                        f"âš ï¸ *Review carefully before approving.*"
                    )
                    
                    await application.bot.send_message(
                        chat_id=config.TELEGRAM_CHAT_ID,
                        text=msg,
                        reply_markup=reply_markup,
                        parse_mode='Markdown'
                    )
                
                last_known_pending = current_ids
            else:
                last_known_pending = set()
        except Exception as e:
            logging.error(f"Error in monitor_pending: {e}")
            
        await asyncio.sleep(15)

async def notify_trades(application):
    """Background task to monitor trade log and notify user."""
    global LAST_TRADE_TIME
    if not getattr(config, "ENABLE_TELEGRAM_NOTIFICATIONS", False) or not config.TELEGRAM_CHAT_ID:
        logging.info("ðŸ“¢ Trade notifications disabled or Chat ID missing.")
        return

    checkpoint = _load_bridge_checkpoint()
    last_pos = int(checkpoint.get("last_pos", 0) or 0)
    if last_pos < 0:
        last_pos = 0
    # If starting fresh, sync to end to avoid spamming old history
    if last_pos == 0 and os.path.exists(TRADE_LOG):
        try:
            with open(TRADE_LOG, "rb") as f:
                f.seek(0, os.SEEK_END)
                last_pos = f.tell()
            _save_bridge_checkpoint(last_pos=last_pos)
        except Exception:
            last_pos = 0
    
    logging.info(f"ðŸ”” Trade notification loop started. Monitoring {TRADE_LOG} (Initial pos: {last_pos})")
    
    while True:
        try:
            if os.path.exists(TRADE_LOG):
                try:
                    file_size = os.path.getsize(TRADE_LOG)
                except Exception:
                    file_size = last_pos

                if file_size < last_pos:
                    # Log rotated or truncated
                    last_pos = 0
                    _save_bridge_checkpoint(last_pos=last_pos)

                if file_size > last_pos:
                    # Small delay to allow bot.py to finish writing/augmenting the line
                    await asyncio.sleep(3)

                    with open(TRADE_LOG, "rb") as f:
                        f.seek(last_pos)
                        data = f.read()

                    if data:
                        lines = data.split(b"\n")
                        processed_bytes = 0
                        processed_any = False

                        # If the last chunk is incomplete (no trailing newline), keep for next round
                        if data[-1:] != b"\n":
                            lines = lines[:-1]

                        for line in lines:
                            if not line:
                                processed_bytes += 1  # newline
                                continue
                            try:
                                trade = json.loads(line.decode("utf-8"))
                                await _send_trade_alert(application, trade)
                                processed_any = True
                                processed_bytes += len(line) + 1
                            except Exception as e:
                                logging.error(f"Error parsing trade line: {e}")
                                # Skip bad line and continue to avoid getting stuck
                                processed_bytes += len(line) + 1
                                continue

                        if processed_bytes > 0:
                            last_pos += processed_bytes
                            _save_bridge_checkpoint(last_pos=last_pos)
                        if processed_any:
                            LAST_TRADE_TIME = time.time()
        except Exception as e:
            logging.error(f"Error in notify_trades: {e}")
            
        await asyncio.sleep(5) # Poll every 5s

async def notify_council(application):
    """Background task to monitor AI Council history and notify user."""
    if not getattr(config, "ENABLE_AI_COUNCIL_NOTIFICATIONS", False) or not config.TELEGRAM_CHAT_ID:
        logging.info("ðŸ“¢ AI Council notifications disabled or Chat ID missing.")
        return

    if not getattr(config, "ENABLE_TELEGRAM_NOTIFICATIONS", False) or not config.TELEGRAM_CHAT_ID:
        return

    checkpoint = _load_bridge_checkpoint()
    last_ts = float(checkpoint.get("last_ts", 0.0) or 0.0)
    if last_ts < 0:
        last_ts = 0.0
    # Initialize to the latest entry to avoid missing events at startup
    if last_ts <= 0.0:
        try:
            if os.path.exists(COUNCIL_LOG):
                with open(COUNCIL_LOG, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    history = data.get("history", []) if isinstance(data, dict) else data
                    if isinstance(history, list) and history:
                        def _ts(entry):
                            ts_raw = entry.get("timestamp", 0)
                            if isinstance(ts_raw, str):
                                try:
                                    return datetime.fromisoformat(ts_raw.replace('Z', '+00:00')).timestamp()
                                except:
                                    return 0.0
                            try:
                                return float(ts_raw)
                            except:
                                return 0.0
                        last_ts = max(_ts(e) for e in history)
                        _save_bridge_checkpoint(last_ts=last_ts)
        except Exception:
            last_ts = 0.0
    logging.info(f"ðŸ›ï¸ Council notification loop started.")
    
    while True:
        try:
            if os.path.exists(COUNCIL_LOG):
                with open(COUNCIL_LOG, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # [v3.11.55] Fix: Handle both dict/list formats
                    history = data.get("history", []) if isinstance(data, dict) else data
                    if not isinstance(history, list): history = []
                    
                    updated = False
                    for entry in history:
                        ts_raw = entry.get("timestamp", 0)
                        
                        # [v3.11.55] Robust Timestamp Parsing (ISO or Float)
                        if isinstance(ts_raw, str):
                            try:
                                ts = datetime.fromisoformat(ts_raw.replace('Z', '+00:00')).timestamp()
                            except:
                                ts = 0
                        else:
                            ts = float(ts_raw)

                        if ts > last_ts:
                            await _send_council_alert(application, entry)
                            last_ts = ts
                            updated = True
                    if updated:
                        _save_bridge_checkpoint(last_ts=last_ts)
        except Exception as e:
            logging.error(f"Error in notify_council: {e}")
            
        await asyncio.sleep(10)

async def notify_summaries(application):
    """[v3.11.46] Background task to monitor summary log and notify user."""
    if not getattr(config, "ENABLE_TELEGRAM_NOTIFICATIONS", False) or not config.TELEGRAM_CHAT_ID:
        return

    last_count = 0
    if os.path.exists(SUMMARY_LOG):
        with open(SUMMARY_LOG, 'r', encoding='utf-8') as f:
            last_count = sum(1 for _ in f)
    
    logging.info(f"ðŸ“Š Summary notification loop started. Monitoring {SUMMARY_LOG} (Initial count: {last_count})")
    
    while True:
        try:
            if os.path.exists(SUMMARY_LOG):
                with open(SUMMARY_LOG, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                    if len(lines) > last_count:
                        new_summaries = lines[last_count:]
                        for line in new_summaries:
                            try:
                                summary = json.loads(line)
                                await _send_summary_alert(application, summary)
                            except Exception as e:
                                logging.error(f"Error parsing summary line: {e}")
                        last_count = len(lines)
        except Exception as e:
            logging.error(f"Error in notify_summaries: {e}")
            
        await asyncio.sleep(30) # Poll summaries every 30s

async def monitor_inactivity(application):
    """Trigger AI Council if no trades executed past a regime-based threshold and notify user."""
    global LAST_TRADE_TIME, LAST_INACTIVITY_REPORT

    if not getattr(config, "ENABLE_TELEGRAM_NOTIFICATIONS", False) or not config.TELEGRAM_CHAT_ID:
        logging.info("Inactivity monitor disabled or Chat ID missing.")
        return

    while True:
        try:
            now = time.time()
            # Read current regime from dashboard state (best-effort, safe under frequent writes)
            regime = "UNKNOWN"
            bot_status = ""
            try:
                if os.path.exists(DASHBOARD_STATE_FILE):
                    with open(DASHBOARD_STATE_FILE, "r", encoding="utf-8") as f:
                        state = json.load(f)
                    regime = str(state.get("ai_regime", state.get("regime", state.get("market_regime", "UNKNOWN")))).upper()
                    bot_status = str(state.get("status", "")).upper()
            except Exception:
                regime = "UNKNOWN"
                bot_status = ""

            # If bot is stopped, reset inactivity timer and skip optimization
            if bot_status == "STOPPED":
                LAST_TRADE_TIME = now
                await asyncio.sleep(60)
                continue

            # Dynamic inactivity threshold based on regime
            if regime == "NORMAL":
                inactivity_threshold = 7200
            elif regime == "HIGH_VOL":
                inactivity_threshold = 14400
            elif regime == "CHOPPY":
                inactivity_threshold = 21600
            else:
                inactivity_threshold = 14400

            if (now - LAST_TRADE_TIME) >= inactivity_threshold and (now - LAST_INACTIVITY_REPORT) >= inactivity_threshold:
                hours = int(inactivity_threshold // 3600)
                cmd_text = (
                    f"The bot has been inactive for {hours} hours under {regime} conditions. "
                    "Perform a Deep Simulation Scan. If volatility has decreased and trends are becoming predictable, "
                    "relax the RSI bounds in 'asset_profiles.json'. If the market remains unstable, maintain current "
                    "strictness to protect capital."
                )
                _send_command("COUNCIL", payload=cmd_text)

                await application.bot.send_message(
                    chat_id=config.TELEGRAM_CHAT_ID,
                    text=(
                        f"ðŸ“‰ Current Regime: {regime}\n"
                        f"â³ Threshold Applied: {hours}h based on market risk\n"
                        "ðŸ›ï¸ Action: AI Council session triggered for Dynamic Optimization."
                    ),
                    parse_mode="HTML"
                )
                LAST_INACTIVITY_REPORT = now
        except Exception as e:
            logging.error(f"Error in monitor_inactivity: {e}")

        await asyncio.sleep(60)

async def _send_summary_alert(application, summary):
    """[v3.11.46] Formats and sends the periodic summary report."""
    try:
        chat_id = config.TELEGRAM_CHAT_ID
        stype = summary.get("type", "REPORT")

        # [v3.11.57] Handle generic system alerts
        if stype == "SYSTEM_ALERT":
            msg = _html_escape(summary.get("message", "Empty Alert"))
            await application.bot.send_message(chat_id=chat_id, text=f"ðŸ›ï¸ **AI Council Alert**\n\n{msg}", parse_mode='HTML')
            return

        wins = summary.get("wins", 0)
        losses = summary.get("losses", 0)
        profit = summary.get("profit", 0.0)
        balance = summary.get("balance", 0.0)
        wr = summary.get("win_rate", "0%")
        
        icon = "ðŸ“ˆ" if profit >= 0 else "ðŸ“‰"
        title = "ðŸ“Š **Daily Performance Report**" if stype == "DAILY_REPORT" else "ðŸ“Š **Periodic Summary**"
        
        # [v3.11.52] Currency Formatting
        currency = getattr(config, "CURRENCY", "XRP")
        if getattr(config, "ENABLE_THB_CONVERSION", True):
            thb_rate = await asyncio.to_thread(get_crypto_thb_rate, currency)
        else:
            thb_rate = 0.0
        
        profit_thb_str = f" (à¸¿{(profit * thb_rate):,.2f})" if thb_rate > 0 else ""
        balance_thb_str = f" (à¸¿{(balance * thb_rate):,.2f})" if thb_rate > 0 else ""

        msg = (
            f"{title}\n"
            f"â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n"
            f"ðŸ’° Result: `{icon} {profit:+.4f} {currency}`{profit_thb_str}\n"
            f"ðŸ¦ Balance: `{balance:.4f} {currency}`{balance_thb_str}\n"
            f"âœ… Wins: `{wins}`\n"
            f"âŒ Losses: `{losses}`\n"
            f"ðŸŽ¯ Win Rate: `{wr}`\n"
            f"â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”"
        )
        await application.bot.send_message(chat_id=chat_id, text=msg, parse_mode='HTML')
    except Exception as e:
        logging.error(f"Failed to send summary alert: {e}")

async def _send_council_alert(application, fix_entry):
    """Formats and sends the AI Council intervention result."""
    fix_type = _html_escape(fix_entry.get("type", "UNKNOWN"))
    ctx = fix_entry.get("context", {})
    error_msg = _html_escape(ctx.get("error", "No error details"))
    
    prop = fix_entry.get("proposal", {})
    title = _html_escape(prop.get("title", "Untitled Fix"))
    explanation = _html_escape(prop.get("explanation", ""))
    
    res = fix_entry.get("result", {})
    success = res.get("success", False)
    res_msg = _html_escape(res.get("message", ""))
    
    if fix_type == "CONSULTATION":
        icon = "ðŸ’¡ **AI Council: Advisory/Advice**"
        msg = (
            f"{icon}\n"
            f"â“ **Question:** `{error_msg}`\n"
            f"ðŸ§  **Analysis:** {_html_escape(prop.get('analysis', 'No analysis'))}\n\n"
            f"ðŸ“ **Advice:** {explanation}\n"
        )
    else:
        icon = "ðŸ›ï¸ **AI Council: System Fix Completed**"
        status_emoji = "âœ…" if success else "âŒ"
        
        msg = (
            f"{icon}\n"
            f"ðŸ› ï¸ **Type:** `{fix_type}`\n"
            f"ðŸ†˜ **Issue:** `{error_msg}`\n"
            f"ðŸ“ **Title:** `{title}`\n"
            f"{status_emoji} **Result:** {res_msg}\n\n"
            f"*Note: {explanation}*"
        )
    
    try:
        await application.bot.send_message(
            chat_id=config.TELEGRAM_CHAT_ID,
            text=msg,
            parse_mode='HTML'
        )
    except Exception as e:
        logging.error(f"Failed to send Council Telegram alert: {e}")

async def _send_trade_alert(application, trade):
    """
    [v3.9.0] Formats and sends the trade result message.
    Includes AI Actionable Insights if present in trade record.
    """
    result = trade.get("result", "UNKNOWN")
    
    if result == "WIN":
        icon = "âœ… WIN"
    elif result == "LOSS":
        icon = "âŒ LOSS"
    elif result == "DRAW":
        icon = "ðŸ”˜ DRAW"
    else:
        icon = f"â³ {result}"
    asset = _html_escape(trade.get("asset", "Unknown"))
    strategy = _html_escape(trade.get("strategy", "Unknown"))
    trade_profit = trade.get("profit", 0.0)
    
    # [v3.9.0] Extract AI Analysis from trade record (enriched by bot.py)
    analysis = trade.get("analysis")
    actionable = trade.get("actionable", False)
    fix_suggestion = _html_escape(trade.get("fix_suggestion", "N/A"))
    
    # Get stats from dashboard state file (Robust method)
    total_wins = 0
    total_losses = 0
    win_rate = "0%"
    balance = 0.0
    profit_today = 0.0
    
    if os.path.exists(DASHBOARD_STATE_FILE):
        try:
            with open(DASHBOARD_STATE_FILE, 'r', encoding='utf-8') as f:
                state = json.load(f)
                total_wins = state.get("total_wins", 0)
                total_losses = state.get("total_losses", 0)
                win_rate = state.get("win_rate", "0%")
                balance = state.get("balance", 0.0)
                profit_today = state.get("profit", 0.0)
        except Exception as e:
            logging.error(f"Error reading dashboard state: {e}")

    # [v3.11.52] Currency Formatting
    currency = getattr(config, "CURRENCY", "XRP")
    if getattr(config, "ENABLE_THB_CONVERSION", True):
        thb_rate = await asyncio.to_thread(get_crypto_thb_rate, currency)
    else:
        thb_rate = 0.0
    
    trade_thb_str = f" (à¸¿{(trade_profit * thb_rate):,.2f})" if thb_rate > 0 else ""
    profit_today_thb_str = f" (à¸¿{(profit_today * thb_rate):,.2f})" if thb_rate > 0 else ""

    msg = (
        f"**{icon}**\n"
        f"ðŸ“Š **Asset:** `{asset}`\n"
        f"ðŸŽ¯ **Strategy:** `{strategy}`\n"
        f"ðŸ’° **Profit/Loss:** `{trade_profit:+.4f} {currency}`{trade_thb_str}\n"
        f"ðŸ¦ **Balance:** `{balance:.4f} {currency}`\n"
        f"ðŸ“ˆ **Today:** `{profit_today:+.4f} {currency}`{profit_today_thb_str} | {win_rate} (W:{total_wins}/L:{total_losses})"
    )
    
    if analysis:
        # Actionable insight icon
        action_icon = "ðŸ”§ Fixable" if actionable else "ðŸ¤· Unavoidable"
        
        msg += f"\n\nðŸ§  **AI Post-Mortem:**\n"
        msg += f"> {_html_escape(analysis)}\n"
        msg += f"**Status:** {action_icon}\n"
        
        if actionable:
            if fix_suggestion != "N/A":
                msg += f"\nðŸš€ **Auto-Fix Triggered:** AI Council is reviewing `{fix_suggestion}`..."
            else:
                msg += f"\nðŸ’¡ **Suggestion:** {fix_suggestion}"
                
    try:
        chat_id = getattr(config, "TELEGRAM_CHAT_ID", None)
        if chat_id:
            await application.bot.send_message(
                chat_id=chat_id,
                text=msg,
                parse_mode='HTML'
            )
    except Exception as e:
        logging.error(f"Failed to send Telegram alert: {e}")

# [v3.9.0] Sync Wrapper for Bot
def send_trade_notification(trade, balance, profit_today, analysis=None, actionable=False, fix_suggestion="N/A"):
    # Since bot.py and bridge are separate processes mostly, this function is a placeholder
    # if bot.py imports telegram_bridge as a library.
    # However, if they share the same process, we need to schedule the async task.
    # But for now, bot.py relies on writing to TRADE_LOG.
    # We should update the trade record in TRADE_LOG to include analysis.
    pass

async def post_init(application):
    """Starts the background notification tasks."""
    asyncio.create_task(notify_trades(application))
    asyncio.create_task(notify_council(application))
    asyncio.create_task(notify_summaries(application)) # [v3.11.46]
    asyncio.create_task(monitor_pending(application))
    asyncio.create_task(monitor_inactivity(application))

if __name__ == '__main__':
    if not config.TELEGRAM_BOT_TOKEN:
        print("âŒ Error: TELEGRAM_BOT_TOKEN not found in config/env. Bridge disabled.")
        exit(100)

    # [v3.11.33] Singleton Lock Check
    if not _acquire_bridge_lock():
        exit(1)

    try:
        print(f"ðŸ“± Telegram Bridge Started (v{config.BOT_VERSION})...")
        application = ApplicationBuilder().token(config.TELEGRAM_BOT_TOKEN).post_init(post_init).build()
        
        application.add_handler(CommandHandler('start', start))
        application.add_handler(CommandHandler('stop', stop))
        application.add_handler(CommandHandler('status', status))
        application.add_handler(CommandHandler('sumlog', sumlog))
        application.add_handler(CommandHandler('logcon', logcon))
        application.add_handler(CommandHandler('logs', logs_command))
        application.add_handler(CommandHandler('council', council_command))
        application.add_handler(CommandHandler('help', help_command))
        
        # Callback Handlers for buttons
        application.add_handler(CallbackQueryHandler(button_callback))
        
        application.run_polling()
    finally:
        _release_bridge_lock()

