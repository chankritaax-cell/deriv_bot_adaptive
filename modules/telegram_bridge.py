"""
Telegram Bridge (v3.12.4)
[v3.12.4] Bug Fixes & New Commands:
- Fix: _send_trade_alert had orphaned `entry` NameError — crashed every WIN/LOSS notification
- Fix: _send_council_alert was completely missing — notify_council crashed on every council event
- Fix: /status always showed WR "0%" — now calculates from total_wins/total_losses
- Fix: _send_command_async now uses atomic write (tmp + os.replace)
- New: /reset command — unban all assets + reset MG state to step 0
- Improve: /status now shows MG step, loss/win streak, regime, strategy
- Improve: /sumlog reads last 10000 chars (was 5000)
- Improve: /help shows full command list with descriptions
"""

import os
import time
import json
import asyncio
import logging
import html
import shutil
from datetime import datetime
import psutil
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, CallbackQueryHandler

import config
from .ai_providers import call_ai_raw_with_failover
from .utils import get_crypto_thb_rate

# Setup Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# [v5.5.x] Global lock for atomic/thread-safe checkpointing
checkpoint_lock = asyncio.Lock()

# [v3.11.25] Align with ROOT_DIR
ROOT = getattr(config, "ROOT_DIR", os.getcwd())
BRIDGE_LOCK_FILE = os.path.join(ROOT, "logs", ".bridge.lock")
DASHBOARD_STATE_FILE = os.path.join(ROOT, "logs", "dashboard", "dashboard_state.json")
COMMAND_FILE = os.path.join(ROOT, "logs", "commands.json")
PENDING_FILE = os.path.join(ROOT, "logs", "council", "pending_proposals.json")
BRIDGE_CHECKPOINT_FILE = os.path.join(ROOT, "logs", "bridge_checkpoint.json")

TRADE_LOG = os.path.join(ROOT, "logs", "trades", "trade_history.jsonl")
SUMMARY_LOG = os.path.join(ROOT, "logs", "dashboard", "summary_history.jsonl")
COUNCIL_LOG = os.path.join(ROOT, "logs", "council", "history.json")

# Inactivity tracking
LAST_TRADE_TIME = time.time()
LAST_INACTIVITY_REPORT = 0

def _html_escape(text):
    safe = html.escape("" if text is None else str(text))
    return safe.replace("_", "&#95;").replace("*", "&#42;")

async def _load_json_async(file_path):
    def _read():
        if os.path.exists(file_path):
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return None
    try: return await asyncio.to_thread(_read)
    except: return None

def _load_bridge_checkpoint():
    """Synchronous helper for loading checkpoint data."""
    if os.path.exists(BRIDGE_CHECKPOINT_FILE):
        try:
            with open(BRIDGE_CHECKPOINT_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict): return data
        except: pass
    return {"last_pos": 0, "last_ts": 0.0, "last_summary_count": 0}

async def _save_bridge_checkpoint(last_pos=None, last_ts=None, last_summary_count=None):
    async with checkpoint_lock:
        def _write():
            os.makedirs(os.path.dirname(BRIDGE_CHECKPOINT_FILE), exist_ok=True)
            data = _load_bridge_checkpoint()
            if last_pos is not None: data["last_pos"] = int(last_pos)
            if last_ts is not None: data["last_ts"] = float(last_ts)
            if last_summary_count is not None: data["last_summary_count"] = int(last_summary_count)
            tmp_file = BRIDGE_CHECKPOINT_FILE + ".tmp"
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_file, BRIDGE_CHECKPOINT_FILE)
        try: await asyncio.to_thread(_write)
        except Exception as e: logging.error(f"Checkpoint save error: {e}")

async def _send_command_async(cmd, payload=None):
    # [v5.6.3] Fix: use atomic write (tmp + os.replace) to prevent partial JSON reads
    def _write():
        data = {"command": cmd, "timestamp": time.time(), "source": "TELEGRAM"}
        if payload: data["payload"] = payload
        os.makedirs(os.path.dirname(COMMAND_FILE), exist_ok=True)
        tmp = COMMAND_FILE + ".tmp"
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, COMMAND_FILE)
    try: await asyncio.to_thread(_write)
    except Exception as e: logging.error(f"Command write error: {e}")

def _acquire_bridge_lock():
    try:
        os.makedirs(os.path.dirname(BRIDGE_LOCK_FILE), exist_ok=True)
        if os.path.exists(BRIDGE_LOCK_FILE):
            with open(BRIDGE_LOCK_FILE, "r") as f:
                try:
                    old_pid = int(f.read().strip())
                    if psutil.pid_exists(old_pid):
                        proc = psutil.Process(old_pid)
                        if "telegram_bridge" in " ".join(proc.cmdline()).lower():
                            print(f" Error: Telegram Bridge already running (PID {old_pid}).")
                            return False
                except: pass
        with open(BRIDGE_LOCK_FILE, "w") as f: f.write(str(os.getpid()))
        return True
    except: return True

def _release_bridge_lock():
    try:
        if os.path.exists(BRIDGE_LOCK_FILE): os.remove(BRIDGE_LOCK_FILE)
    except: pass

# --- HANDLERS ---

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_html(" Sending <b>START</b> command...")
    await _send_command_async("START")

async def stop_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_html(" Sending <b>STOP</b> command...")
    await _send_command_async("STOP")

async def status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = await _load_json_async(DASHBOARD_STATE_FILE)
    if not state:
        await update.message.reply_html("⚠️ Bot state currently unavailable.")
        return
    profit   = state.get("profit", 0.0)
    balance  = state.get("balance", 0.0)
    currency = getattr(config, "CURRENCY", "XRP")
    thb_rate = await asyncio.to_thread(get_crypto_thb_rate, currency) if getattr(config, "ENABLE_THB_CONVERSION", True) else 0.0
    def to_thb(v): return f" (฿{v*thb_rate:,.2f})" if thb_rate > 0 else ""

    # [v5.6.3] Fix: calculate WR from actual wins/losses (dashboard_state has no 'win_rate' key)
    w  = state.get("total_wins", 0)
    l  = state.get("total_losses", 0)
    wr = f"{w/(w+l)*100:.1f}% (W:{w}/L:{l})" if (w + l) > 0 else "N/A"

    # [v5.6.3] Add MG step, streaks, regime for actionable status
    mg_step      = state.get("martingale_level", 0)
    loss_streak  = state.get("loss_streak", 0)
    win_streak   = state.get("win_streak", 0)
    regime       = state.get("market_regime", state.get("ai_regime", "UNKNOWN"))
    strategy     = state.get("current_strategy", "-")
    bot_status   = state.get("status", "-")
    mg_icon      = "🟢" if mg_step == 0 else ("🟡" if mg_step == 1 else "🔴")
    streak_line  = f"🔥 Win: {win_streak}" if win_streak > 0 else f"❄️ Loss: {loss_streak}" if loss_streak > 0 else "➖ Streak: 0"

    msg = (
        f"📊 <b>Bot Status</b> ({state.get('account_type','demo').upper()})\n"
        f"🔹 Status: <code>{_html_escape(bot_status)}</code>\n"
        f"🎯 Asset: <code>{state.get('current_asset','-')}</code>  Strategy: <code>{strategy}</code>\n"
        f"📉 Regime: <code>{regime}</code>\n"
        f"─────────────────\n"
        f"💰 Balance: <code>{balance:.4f} {currency}</code>{to_thb(balance)}\n"
        f"📈 Profit: <code>{profit:+.4f} {currency}</code>{to_thb(profit)}\n"
        f"🏆 Win Rate: <code>{wr}</code>\n"
        f"─────────────────\n"
        f"{mg_icon} MG Step: <code>{mg_step}</code>  {streak_line}\n"
        f"🕐 Updated: {time.strftime('%H:%M:%S', time.localtime(state.get('updated_at', 0)))}"
    )
    await update.message.reply_html(msg)

async def tune_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    asset = " ".join(context.args).strip()
    if not asset:
        state = await _load_json_async(DASHBOARD_STATE_FILE)
        asset = state.get("current_asset", "") if state else ""
    if not asset:
        await update.message.reply_html(" Usage: /tune [asset]")
        return
    await update.message.reply_html(f" Analysis request sent for <b>{asset}</b>...")
    await _send_command_async("COUNCIL", payload=f"Analyze and optimize config for {asset} based on current chart.")

async def reset_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """[v5.6.3] New command: /reset — unban all assets + reset MG state to step 0."""
    def _do_reset():
        results = []
        # 1. Clear asset blacklist
        failed_path = os.path.join(ROOT, "logs", "market", "failed_assets.json")
        try:
            os.makedirs(os.path.dirname(failed_path), exist_ok=True)
            tmp = failed_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({}, f)
                f.flush(); os.fsync(f.fileno())
            os.replace(tmp, failed_path)
            results.append("✅ Asset blacklist cleared")
        except Exception as e:
            results.append(f"❌ Blacklist clear failed: {e}")
        # 2. Reset Martingale state
        trade_state_path = os.path.join(ROOT, "logs", "dashboard", "trade_state.json")
        try:
            os.makedirs(os.path.dirname(trade_state_path), exist_ok=True)
            state_data = {"mg_step": 0, "account_type": "real", "last_loss_timestamp": 0.0}
            tmp = trade_state_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(state_data, f)
                f.flush(); os.fsync(f.fileno())
            os.replace(tmp, trade_state_path)
            results.append("✅ MG state reset to Step 0")
        except Exception as e:
            results.append(f"❌ MG reset failed: {e}")
        return results
    await update.message.reply_html("🔄 Resetting bot state...")
    results = await asyncio.to_thread(_do_reset)
    msg = "🔧 <b>Reset Complete</b>\n" + "\n".join(results)
    await update.message.reply_html(msg)

async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "🤖 <b>Bot Commander</b>\n\n"
        "/status — แสดงสถานะ balance, WR, MG step\n"
        "/reset  — unban assets + reset MG step 0\n"
        "/tune   — ให้ AI Council วิเคราะห์ config\n"
        "/sumlog — สรุป log วันนี้ด้วย AI\n"
        "/logcon — แสดง 30 บรรทัดสุดท้ายของ log\n"
        "/logs   — ดาวน์โหลด log file\n"
        "/start  — ส่งคำสั่ง START bot\n"
        "/stop   — ส่งคำสั่ง STOP bot\n"
        "/help   — แสดงเมนูนี้"
    )
    await update.message.reply_html(msg)

async def sumlog_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_html("🧠 Generating AI Summary...")
    def _read():
        date_str = time.strftime("%Y-%m-%d")
        path = os.path.join(ROOT, "logs", "console", f"console_log_{date_str}.txt")
        if not os.path.exists(path): return None
        # [v5.6.3] Increased from 5000 → 10000 chars: busy days need more context
        with open(path, 'r', encoding='utf-8') as f: return f.read()[-10000:]
    log = await asyncio.to_thread(_read)
    if not log:
        await update.message.reply_html("⚠️ No logs found.")
        return
    summary = await asyncio.to_thread(call_ai_raw_with_failover, f"Summarize in Thai:\n{log}", "LOG_SUMMARY")
    await update.message.reply_html(f"📋 <b>Summary</b>\n\n{_html_escape(summary)}")

async def logcon_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    def _read():
        date_str = time.strftime("%Y-%m-%d")
        path = os.path.join(ROOT, "logs", "console", f"console_log_{date_str}.txt")
        if not os.path.exists(path): return "No logs found."
        with open(path, 'r', encoding='utf-8') as f: return "".join(f.readlines()[-30:])
    msg = await asyncio.to_thread(_read)
    await update.message.reply_html(f" <b>Recent Logs</b>\n<pre>{html.escape(msg[-3800:])}</pre>")

async def logs_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_dir = os.path.join(ROOT, "logs", "console")
    files = sorted([f for f in os.listdir(log_dir) if f.endswith(".txt")], reverse=True)[:10]
    keyboard = [[InlineKeyboardButton(f" {f}", callback_data=f"DL|{f}")] for f in files]
    await update.message.reply_html(" Choose log:", reply_markup=InlineKeyboardMarkup(keyboard))

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if "|" not in query.data: return
    action, prop_id = query.data.split("|", 1)
    if action == "DL":
        path = os.path.join(ROOT, "logs", "console", prop_id)
        if os.path.isfile(path) and ".." not in prop_id:
            with open(path, 'rb') as f: await query.message.reply_document(document=f, filename=prop_id)
    elif action == "APPROVE":
        await _send_command_async("APPROVE", payload=prop_id)
        await query.edit_message_text(text=f" Approved: <code>{prop_id}</code>", parse_mode='HTML')
    elif action == "REJECT":
        await _send_command_async("REJECT", payload=prop_id)
        await query.edit_message_text(text=f" Rejected: <code>{prop_id}</code>", parse_mode='HTML')

# --- TASKS ---

async def monitor_pending(application):
    last_ids = set()
    while True:
        try:
            pending = await _load_json_async(PENDING_FILE)
            if pending:
                new_ids = set(pending.keys()) - last_ids
                for pid in list(new_ids)[:3]:
                    prop = pending[pid].get("proposal", {})
                    msg = f" <b>NEW PROPOSAL</b>\nID: <code>{pid}</code>\nTitle: <code>{_html_escape(prop.get('title'))}</code>"
                    kb = [[InlineKeyboardButton(" Approve", callback_data=f"APPROVE|{pid}"), InlineKeyboardButton(" Reject", callback_data=f"REJECT|{pid}")]]
                    await application.bot.send_message(chat_id=config.TELEGRAM_CHAT_ID, text=msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')
                    await asyncio.sleep(1)
                last_ids = set(pending.keys())
        except: pass
        await asyncio.sleep(15)

async def notify_trades(application):
    global LAST_TRADE_TIME
    ckpt = await asyncio.to_thread(_load_bridge_checkpoint)
    last_pos = int(ckpt.get("last_pos", 0))
    if last_pos == 0 and os.path.exists(TRADE_LOG): 
        last_pos = os.path.getsize(TRADE_LOG)
        await _save_bridge_checkpoint(last_pos=last_pos)
    while True:
        try:
            if os.path.exists(TRADE_LOG):
                sz = os.path.getsize(TRADE_LOG)
                if sz < last_pos: last_pos = 0
                if sz > last_pos:
                    def _read():
                        with open(TRADE_LOG, "rb") as f:
                            f.seek(last_pos)
                            return f.read()
                    data = await asyncio.to_thread(_read)
                    if data:
                        lines = [l for l in data.split(b"\n") if l][:-1 if data[-1:] != b"\n" else None]
                        for line in lines[:5]:
                            try:
                                trade_data = json.loads(line.decode("utf-8"))
                                # --- [v5.7.6] Skip initial 'OPEN' alerts to prevent desync ---
                                if trade_data.get("result") == "OPEN":
                                    continue
                                    
                                await _send_trade_alert(application, trade_data)
                                LAST_TRADE_TIME = time.time()
                                await asyncio.sleep(1.5)
                            except: pass
                        last_pos += len(data)
                        await _save_bridge_checkpoint(last_pos=last_pos)
        except: pass
        await asyncio.sleep(5)

async def notify_council(application):
    ckpt = await asyncio.to_thread(_load_bridge_checkpoint)
    last_ts = float(ckpt.get("last_ts", 0.0))
    last_sz = 0
    while True:
        try:
            if os.path.exists(COUNCIL_LOG):
                sz = os.path.getsize(COUNCIL_LOG)
                if sz != last_sz:
                    data = await _load_json_async(COUNCIL_LOG)
                    history = data.get("history", []) if isinstance(data, dict) else data
                    updated = False
                    for e in history:
                        ts_raw = e.get("timestamp", 0)
                        ts = datetime.fromisoformat(ts_raw.replace('Z', '+00:00')).timestamp() if isinstance(ts_raw, str) else float(ts_raw)
                        if ts > last_ts:
                            await _send_council_alert(application, e)
                            last_ts = ts
                            updated = True
                            await asyncio.sleep(2)
                    if updated: await _save_bridge_checkpoint(last_ts=last_ts)
                    last_sz = sz
        except: pass
        await asyncio.sleep(10)

async def notify_summaries(application):
    ckpt = await asyncio.to_thread(_load_bridge_checkpoint)
    last_count = int(ckpt.get("last_summary_count", 0))
    while True:
        try:
            if os.path.exists(SUMMARY_LOG):
                def _read():
                    with open(SUMMARY_LOG, 'r', encoding='utf-8') as f: return f.readlines()
                lines = await asyncio.to_thread(_read)
                if len(lines) > last_count:
                    for line in lines[last_count:]:
                        try: await _send_summary_alert(application, json.loads(line))
                        except: pass
                    last_count = len(lines)
                    await _save_bridge_checkpoint(last_summary_count=last_count)
        except: pass
        await asyncio.sleep(30)

async def monitor_inactivity(application):
    global LAST_TRADE_TIME, LAST_INACTIVITY_REPORT
    while True:
        try:
            now = time.time()
            state = await _load_json_async(DASHBOARD_STATE_FILE)
            regime = str(state.get("market_regime", "NORMAL")).upper() if state else "NORMAL"
            threshold = 7200 if regime == "NORMAL" else 14400
            if (now - LAST_TRADE_TIME) >= threshold and (now - LAST_INACTIVITY_REPORT) >= threshold:
                LAST_INACTIVITY_REPORT = now
                await _send_command_async("COUNCIL", payload=f"Bot inactive {threshold//3600}h under {regime}.")
                await application.bot.send_message(chat_id=config.TELEGRAM_CHAT_ID, text=f" Inactive {threshold//3600}h ({regime}). Optimization triggered.", parse_mode='HTML')
        except: pass
        await asyncio.sleep(60)

async def _send_trade_alert(application, trade):
    res = trade.get("result", "UNKNOWN")
    icon = "✅ <b>WIN</b>" if res == "WIN" else "❌ <b>LOSS</b>" if res == "LOSS" else "ℹ️ <b>DRAW</b>"
    
    # [v5.7.6] Re-sync Prefix logic
    is_update = trade.get("is_update", False)
    res_prefix = "🏁 <b>[FINAL SETTLEMENT]</b>\n" if is_update else ""

    # Load current state for context
    state = await _load_json_async(DASHBOARD_STATE_FILE) or {}
    balance = state.get("balance", 0.0)
    today_profit = state.get("profit", 0.0)
    w = state.get("total_wins", 0)
    l = state.get("total_losses", 0)
    
    # Calculate accurate Win Rate on the fly
    total_trades = w + l
    wr = f"{(w / total_trades * 100):.1f}%" if total_trades > 0 else "0%"
    
    currency = getattr(config, "CURRENCY", "XRP")
    thb_rate = get_crypto_thb_rate(currency)
    
    def to_thb(val): return f" (฿{val*thb_rate:,.2f})" if thb_rate > 0 else ""

    msg = (
        f"{res_prefix}{icon}\n"
        f"📊 <b>Asset:</b> <code>{trade.get('asset')}</code>\n"
        f"🎯 <b>Strategy:</b> <code>{trade.get('strategy', 'N/A')}</code>\n"
        f"💰 <b>Profit/Loss:</b> <code>{trade.get('profit', 0):+.4f} {currency}</code>{to_thb(trade.get('profit', 0))}\n"
        f"🏦 <b>Balance:</b> <code>{balance:.4f} {currency}</code>\n"
        f"📈 <b>Today:</b> <code>{today_profit:+.4f} {currency}</code>{to_thb(today_profit)} | {wr} (W:{w}/L:{l})\n"
        f"🧠 <b>AI:</b> <i>{_html_escape(trade.get('analysis'))}</i>"
    )
    
    await application.bot.send_message(chat_id=config.TELEGRAM_CHAT_ID, text=msg, parse_mode='HTML')

async def _send_council_alert(application, entry):
    """[v5.6.3] Fixed: was missing entirely — notify_council was crashing on every council event."""
    try:
        e_type  = str(entry.get("type", "UPDATE"))
        title   = _html_escape(entry.get("title", entry.get("error_type", "AI Council Update")))
        result  = entry.get("result", {}) or {}
        applied = result.get("applied", False)
        message = _html_escape(result.get("message", ""))
        icon    = "✅" if applied else "💡"
        type_label = {
            "CONSECUTIVE_LOSS": "🔴 Consecutive Loss",
            "NO_TRADE_TIMEOUT": "⏳ No Trade Timeout",
            "CODE_ERROR":       "🐛 Code Error",
        }.get(e_type, f"ℹ️ {e_type}")
        msg = (
            f"🏛️ <b>AI Council</b> {icon}\n"
            f"Type: <code>{type_label}</code>\n"
            f"Title: <i>{title}</i>\n"
        )
        if message:
            msg += f"Result: {message[:300]}\n"
        if applied:
            files = result.get("files_changed", [])
            if files:
                msg += f"📝 Changed: <code>{', '.join(files)}</code>"
        await application.bot.send_message(chat_id=config.TELEGRAM_CHAT_ID, text=msg, parse_mode='HTML')
    except Exception as e:
        logging.error(f"_send_council_alert error: {e}")

async def _send_summary_alert(application, summary):
    # [v5.7.6] Route SYSTEM_ALERT away from Profit/WR summary formatting
    if summary.get("type") == "SYSTEM_ALERT":
        msg = f"⚠️ <b>SYSTEM ALERT</b>\n\n{_html_escape(summary.get('message', 'No content'))}"
        await application.bot.send_message(chat_id=config.TELEGRAM_CHAT_ID, text=msg, parse_mode='HTML')
        return

    msg = f" <b>Summary</b>\nProfit: <code>{summary.get('profit', 0):+.4f}</code>\nWR: <code>{summary.get('win_rate')}</code>"
    await application.bot.send_message(chat_id=config.TELEGRAM_CHAT_ID, text=msg, parse_mode='HTML')

# [v5.7.2] Implementation: sends trade notification to the bridge via dashboard log
def send_trade_notification(trade_info, balance=0, profit=0, is_update=False):
    """
    Called by bot.py to trigger a Telegram trade alert.
    Appends the trade info to the shared log which the bridge watcher monitors.
    """
    trade_info["is_update"] = is_update
    from .utils import dashboard_add_trade
    dashboard_add_trade(trade_info)

async def post_init(application):
    asyncio.create_task(monitor_pending(application))
    asyncio.create_task(notify_trades(application))
    asyncio.create_task(notify_council(application))
    asyncio.create_task(notify_summaries(application))
    asyncio.create_task(monitor_inactivity(application))

if __name__ == '__main__':
    if not config.TELEGRAM_BOT_TOKEN: exit(100)
    if not _acquire_bridge_lock(): exit(1)
    try:
        app = ApplicationBuilder().token(config.TELEGRAM_BOT_TOKEN).post_init(post_init).build()
        app.add_handler(CommandHandler('start', start_handler))
        app.add_handler(CommandHandler('stop', stop_handler))
        app.add_handler(CommandHandler('status', status_handler))
        app.add_handler(CommandHandler('sumlog', sumlog_handler))
        app.add_handler(CommandHandler('logcon', logcon_handler))
        app.add_handler(CommandHandler('logs', logs_command_handler))
        app.add_handler(CommandHandler('tune', tune_handler))
        app.add_handler(CommandHandler('reset', reset_handler))
        app.add_handler(CommandHandler('help', help_handler))
        app.add_handler(CallbackQueryHandler(button_callback))
        app.run_polling()
    finally: _release_bridge_lock()
