from flask import Flask, render_template, jsonify, request
import json
import os
import time
import requests
import datetime
# Try optional Google GenAI import
try:
    from google import genai
    from google.genai import types
    HAS_GEMINI = True
except ImportError:
    HAS_GEMINI = False

# Load Config for Keys
import config
import re
import psutil
import subprocess
import signal
from modules import ai_engine # 🕵️ AI Engine (Includes Code Reviewer)
from modules import ai_editor # 🛠️ AI Editor (Health Monitor + Proposals)
from modules import ai_council # 🏛️ AI Council (v3.3.0)

# Try Anthropic
try:
    import anthropic
    HAS_CLAUDE = True
except ImportError:
    HAS_CLAUDE = False

app = Flask(__name__)
STATE_FILE = os.path.join("logs", "dashboard", "dashboard_state.json")
REVIEW_HISTORY_FILE = os.path.join("logs", "review", "review_history.json")
SUMMARY_HISTORY_FILE = os.path.join("logs", "ai", "ai_trade_summary_history.json")

# --- v1.8.6: CONFIG EDITOR & BOT RESTART ---

@app.route("/api/config", methods=["GET"])
def get_bot_config():
    """Retrieve current editable config values."""
    try:
        with open("config.py", "r", encoding="utf-8") as f:
            content = f.read()
            
        balance_type = re.search(r'BALANCE_TYPE\s*=\s*"([^"]+)"', content)
        active_profile = re.search(r'ACTIVE_PROFILE\s*=\s*"([^"]+)"', content)
        profit_target = re.search(r'PROFIT_TARGET_FOR_PAUSE\s*=\s*([\d\.]+)', content)
        
        # [v3.2.11] Added AI Config Support
        ai_provider = re.search(r'AI_PROVIDER\s*=\s*"([^"]+)"', content)
        ai_routing = re.search(r'ENABLE_AI_TASK_ROUTING\s*=\s*(True|False)', content)
        
        # [v3.2.12] AI Task Routing extraction
        # We look for the AI_TASK_ROUTING dict. This regex is a bit greedy.
        routing_match = re.search(r'AI_TASK_ROUTING\s*=\s*(\{.*?\})', content, re.DOTALL)
        ai_task_routing = {}
        if routing_match:
            try:
                # Basic string to dict conversion (unsafe if not formatted well, but we control the file)
                # Clean up the string to be valid JSON-ish or just eval (risky but common in these local bots)
                raw_routing = routing_match.group(1)
                # Convert Python dict string to JSON compatible string
                json_routing = raw_routing.replace("'", '"')
                json_routing = re.sub(r'#.*?\n', '\n', json_routing) # Remove comments
                json_routing = re.sub(r',\s*\}', '}', json_routing) # Remove trailing commas
                ai_task_routing = json.loads(json_routing)
            except:
                # Fallback if regex/json fails
                ai_task_routing = getattr(config, "AI_TASK_ROUTING", {})

        # [v3.4.1] Extract new config params
        min_stake = re.search(r'MIN_STAKE_AMOUNT\s*=\s*([\d\.]+)', content)
        l2_threshold = re.search(r'L2_MIN_CONFIRMATION\s*=\s*([\d\.]+)', content)
        allow_put = re.search(r'ALLOW_PUT_SIGNALS\s*=\s*(True|False)', content)
        scan_interval = re.search(r'ASSET_SCAN_INTERVAL_NO_TRADE_MINS\s*=\s*(\d+)', content)

        return jsonify({
            "balance_type": balance_type.group(1) if balance_type else "PRACTICE",
            "active_profile": active_profile.group(1) if active_profile else "TIER_1",
            "profit_target": float(profit_target.group(1)) if profit_target else 5.0,
            "ai_provider": ai_provider.group(1) if ai_provider else "openai",
            "ai_routing": ai_routing.group(1) == "True" if ai_routing else False,
            "ai_task_routing": ai_task_routing,
            "ENABLE_DASHBOARD_CHART": getattr(config, "ENABLE_DASHBOARD_CHART", True),
            "min_stake": float(min_stake.group(1)) if min_stake else 1.0,
            "l2_threshold": float(l2_threshold.group(1)) if l2_threshold else 0.35,
            "allow_put": allow_put.group(1) == "True" if allow_put else True,
            "scan_interval": int(scan_interval.group(1)) if scan_interval else 20
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/config/update", methods=["POST"])
def update_bot_config():
    """Update config.py and RESTART the bot."""
    data = request.json
    balance_type = data.get("balance_type")
    active_profile = data.get("active_profile")
    profit_target = data.get("profit_target")
    
    # [v3.2.11] AI Config
    ai_provider = data.get("ai_provider")
    ai_routing = data.get("ai_routing") 
    
    if not balance_type or not active_profile or profit_target is None:
        return jsonify({"error": "Missing parameters"}), 400

    try:
        # 1. Update config.py
        with open("config.py", "r", encoding="utf-8") as f:
            content = f.read()
            
        content = re.sub(r'(BALANCE_TYPE\s*=\s*")[^"]+(")', rf'\1{balance_type}\2', content)
        content = re.sub(r'(ACTIVE_PROFILE\s*=\s*")[^"]+(")', rf'\1{active_profile}\2', content)
        content = re.sub(r'(PROFIT_TARGET_FOR_PAUSE\s*=\s*)[\d\.]+', rf'\1{profit_target}', content)
        
        # [v3.2.11] Update AI Settings
        if ai_provider:
             content = re.sub(r'(AI_PROVIDER\s*=\s*")[^"]+(")', rf'\1{ai_provider}\2', content)
        
        if ai_routing is not None:
             content = re.sub(r'(ENABLE_AI_TASK_ROUTING\s*=\s*)(True|False)', rf'\1{str(ai_routing)}', content)
        
        # [v3.4.1] Update new config params
        if data.get("min_stake") is not None:
            content = re.sub(r'(MIN_STAKE_AMOUNT\s*=\s*)[\d\.]+', rf'\g<1>{data["min_stake"]}', content)
        if data.get("l2_threshold") is not None:
            content = re.sub(r'(L2_MIN_CONFIRMATION\s*=\s*)[\d\.]+', rf'\g<1>{data["l2_threshold"]}', content)
        if data.get("allow_put") is not None:
            content = re.sub(r'(ALLOW_PUT_SIGNALS\s*=\s*)(True|False)', rf'\g<1>{data["allow_put"]}', content)
        if data.get("scan_interval") is not None:
            content = re.sub(r'(ASSET_SCAN_INTERVAL_NO_TRADE_MINS\s*=\s*)\d+', rf'\g<1>{data["scan_interval"]}', content)

        # [v3.2.12] Update AI Task Routing
        ai_task_routing = data.get("ai_task_routing")
        if ai_task_routing:
             # Convert dict back to formatted Python string
             routing_str = "AI_TASK_ROUTING = {\n"
             for task, providers in ai_task_routing.items():
                 providers_str = json.dumps(providers).replace('"', "'")
                 routing_str += f'    "{task}": {providers_str},\n'
             routing_str += "}"
             content = re.sub(r'AI_TASK_ROUTING\s*=\s*\{.*?\}', routing_str, content, flags=re.DOTALL)

        with open("config.py", "w", encoding="utf-8") as f:
            f.write(content)
            
        # 2. Kill existing bot.py processes
        process_killed = False
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                cmdline = proc.info.get('cmdline')
                if cmdline and 'bot.py' in " ".join(cmdline):
                    proc.terminate()
                    process_killed = True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        
        # 3. Start new bot.py in a new console window (Windows specific)
        # Use 'start cmd /k' to open a new window that stays open
        subprocess.Popen(['start', 'cmd', '/k', 'python', 'bot.py'], shell=True)
        
        return jsonify({
            "status": "success", 
            "message": "Config updated and Bot restarted in a new window!",
            "killed_old": process_killed
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def get_state():
    for _ in range(5): # Retry up to 5 times
        if not os.path.exists(STATE_FILE):
            return {}
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            time.sleep(0.05)
    return {}

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/state")
def api_state():
    return jsonify(get_state())

@app.route("/api/candles")
def api_candles():
    """Serve candle OHLC data for dashboard chart."""
    # Check if chart is disabled in config
    if not getattr(config, 'ENABLE_DASHBOARD_CHART', True):
        return jsonify({"asset": "", "candles": []})
    
    candle_file = os.path.join("logs", "dashboard", "candle_data.json")
    if not os.path.exists(candle_file):
        return jsonify({"asset": "", "candles": []})
    try:
        with open(candle_file, "r", encoding="utf-8") as f:
            return jsonify(json.load(f))
    except:
        return jsonify({"asset": "", "candles": []})

@app.route("/api/logs/list")
def api_logs_list():
    # List all .txt files starting with console_log or trading_log
    all_files = []
    trading_dir = os.path.join("logs", "trading")
    console_dir = os.path.join("logs", "console")
    if os.path.isdir(trading_dir):
        all_files += [f for f in os.listdir(trading_dir) if f.endswith(".txt") and f.startswith("trading_log")]
    if os.path.isdir(console_dir):
        all_files += [f for f in os.listdir(console_dir) if f.endswith(".txt") and f.startswith("console_log")]
    all_files.sort(reverse=True)
    return jsonify(all_files)

@app.route("/api/logs/read/<filename>")
def api_logs_read(filename):
    # Security check: only allow current directory files
    if os.path.sep in filename or ".." in filename:
        return jsonify({"error": "Invalid filename"}), 400
    
    # Resolve to correct subdirectory
    if filename.startswith("trading_log"):
        filepath = os.path.join("logs", "trading", filename)
    elif filename.startswith("console_log"):
        filepath = os.path.join("logs", "console", filename)
    else:
        filepath = filename
    
    if not os.path.exists(filepath):
        return jsonify({"error": "File not found"}), 404
        
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        return jsonify({"content": content})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/docs/<filename>")
def api_get_docs(filename):
    """Retrieve markdown content for specific documentation files."""
    allowed = ["README.md", "FEATURES.md", "CHANGELOG.md", "PROJECT_MAP.md"]
    if filename not in allowed:
        return jsonify({"error": "Unauthorized"}), 403
    
    if not os.path.exists(filename):
        return jsonify({"error": "File not found"}), 404
        
    try:
        with open(filename, "r", encoding="utf-8") as f:
            content = f.read()
        return jsonify({"content": content})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/history")
def api_history():
    # Read today's trading log
    date_str = time.strftime("%Y-%m-%d")
    filename = f"trading_log_{date_str}.txt"
    filepath = os.path.join("logs", "trading", filename)
    lines = []
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            lines = f.readlines()
    return jsonify({"log": lines})

@app.route("/api/ai_summary/<int:hours>", methods=["POST"])
def api_ai_summary(hours):
    """
    Reads recent logs (Console + Trade) for the last N hours,
    filters relevant info, and asks AI to summarize performance & next steps.
    """
    try:
        # 1. Gather Logs
        lines_to_analyze = []
        
        # Read Console Log (Today)
        date_str = datetime.datetime.now().strftime("%Y-%m-%d")
        console_file = os.path.join("logs", "console", f"console_log_{date_str}.txt")
        
        if os.path.exists(console_file):
            with open(console_file, "r", encoding="utf-8") as f:
                # Read last 2000 lines max to prevent token overflow
                lines = f.readlines()[-2000:] 
                lines_to_analyze.extend(lines)
                
        # Filter by time (Simple string check for now, or just send last N lines)
        # For simplicity, we send the tail of the log which usually corresponds to recent time.
        
        if not lines_to_analyze:
             return jsonify({"error": "No logs found for today."}), 404
             
        # Compact content
        text_content = "".join(lines_to_analyze)
        
        # 2. Build Prompt
        prompt = f"""
        Analyze this trading bot log (Last {hours} hours).
        
        Log Extract:
        {text_content[-10000:]} 
        
        Task:
        1. Summarize Performance (Wins/Losses, Profit) in Thai.
        2. Identify Key Events (Errors, AI Switching, Market Regime) in Thai.
        3. Recommend Adjustments (Stop, Continue, Change Strategy) in Thai.
        
        Reply in Markdown format (Use bold, lists, and spacing). Keep it concise.
        IMPORTANT: 
        - Reply in Thai Language only (ภาษาไทย).
        - DO NOT wrap your response in triple backticks (```). Just plain markdown text.
        """
        
        # 3. Call AI (Gemini First, then ChatGPT)
        ai_response = "AI Service Unavailable"
        
        # Try Gemini
        if HAS_GEMINI and getattr(config, "GEMINI_API_KEY", ""):
            try:
                client = genai.Client(api_key=config.GEMINI_API_KEY)
                resp = client.models.generate_content(
                    model=config.GEMINI_MODEL,
                    contents=prompt
                )
                ai_response = resp.text
            except Exception as e:
                ai_response = f"Gemini Error: {e}"
        
        # Try ChatGPT if Gemini failed or not avail
        elif getattr(config, "OPENAI_API_KEY", ""):
            try:
                url = "https://api.openai.com/v1/chat/completions"
                headers = {"Authorization": f"Bearer {config.OPENAI_API_KEY}", "Content-Type": "application/json"}
                payload = {
                    "model": config.CHATGPT_MODEL,
                    "messages": [{"role": "user", "content": prompt}]
                }
                resp = requests.post(url, headers=headers, json=payload, timeout=30)
                if resp.status_code == 200:
                    ai_response = resp.json()['choices'][0]['message']['content']
                else:
                    ai_response = f"ChatGPT Error: {resp.text}"
            except Exception as e:
                ai_response = f"ChatGPT Exception: {e}"
        else:
             return jsonify({"error": "No AI API Keys configured."}), 500

        result = {"summary": ai_response, "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        
        # Save to History
        history = []
        if os.path.exists(SUMMARY_HISTORY_FILE):
            try:
                with open(SUMMARY_HISTORY_FILE, "r", encoding="utf-8") as f:
                    history = json.load(f)
            except:
                history = []
        
        history.append(result)
        if len(history) > 50: # Keep last 50
            history = history[-50:]
            
        os.makedirs(os.path.dirname(SUMMARY_HISTORY_FILE), exist_ok=True)
        with open(SUMMARY_HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=4, ensure_ascii=False)

        return jsonify(result)

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/ai_summary/history")
def api_ai_summary_history():
    """Returns the history of AI Trading Summaries"""
    if os.path.exists(SUMMARY_HISTORY_FILE):
        try:
            with open(SUMMARY_HISTORY_FILE, "r", encoding="utf-8") as f:
                return jsonify(json.load(f))
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    else:
        return jsonify([])

@app.route("/api/intelligence")
def api_intelligence():
    """Returns the bot's current intelligence level from dashboard state."""
    state = get_state()
    intel = state.get("intelligence", {})
    if intel and intel.get("score", 0) > 0:
        return jsonify(intel)
    # Fallback: compute live from smart_trader
    try:
        from ai_engine import get_smart_trader
        smart = get_smart_trader()
        result = smart.calculate_intelligence_level()
        return jsonify(result)
    except Exception as e:
        return jsonify({"score": 0, "level_name": "Newborn", "level_emoji": "🐣", 
                        "description": f"Error: {e}", "components": {}})

@app.route("/api/ai_review")
def api_ai_review():
    """Returns the latest AI Code Review result"""
    review_file = os.path.join("logs", "review", "review_status.json")
    if os.path.exists(review_file):
        try:
            with open(review_file, "r", encoding="utf-8") as f:
                return jsonify(json.load(f))
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    else:
        return jsonify({"score": 0, "status": "Waiting...", "summary_thai": "รอการตรวจสอบรอบแรก..."})

@app.route("/api/ai_review/history")
def api_ai_review_history():
    """Returns the history of AI Code Reviews"""
    history_file = REVIEW_HISTORY_FILE
    if os.path.exists(history_file):
        try:
            with open(history_file, "r", encoding="utf-8") as f:
                return jsonify(json.load(f))
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    else:
        return jsonify([])

@app.route("/api/ai_review/run", methods=["POST"])
def api_run_ai_review():
    """Manually triggers the AI Code Review"""
    try:
        # Run the review synchronously (might take 10-20s)
        result = ai_engine.run_ai_code_review()
        if result:
            return jsonify(result)
        else:
            return jsonify({"error": "AI Review returned no result."}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ---------------------------------------------------
# 🛠️ AI CODE FIXER & AUTO-DOCS
# ---------------------------------------------------

def append_changelog(msg):
    """Appends an entry to CHANGELOG.md"""
    try:
        date_str = datetime.datetime.now().strftime("%Y-%m-%d")
        new_entry = f"- **AI Fix:** {msg} ({date_str})"
        
        content = ""
        with open("CHANGELOG.md", "r", encoding="utf-8") as f:
            content = f.read()
            
        # Insert under the first "### Added" or "### Fixed" or just top level
        if "### Fixed" in content:
            content = content.replace("### Fixed", f"### Fixed\n{new_entry}", 1)
        else:
            # Fallback: Append to end of version block or top
            content = content.replace("## [", f"{new_entry}\n\n## [", 1)
            
        with open("CHANGELOG.md", "w", encoding="utf-8") as f:
            f.write(content)
        return True
    except Exception as e:
        print(f"❌ Changelog Update Failed: {e}")
        return False

def update_readme(msg):
    """Appends a note to README.md"""
    try:
        with open("README.md", "a", encoding="utf-8") as f:
            f.write(f"\n- 🤖 **AI Auto-Fix ({datetime.datetime.now().strftime('%Y-%m-%d')}):** {msg}")
        return True
    except:
        return False

@app.route("/api/ai_fix", methods=["POST"])
def api_ai_fix():
    """Reads bot.py, applies AI fix, updates Docs."""
    data = request.json
    instruction = data.get("instruction", "")
    model_choice = data.get("model", "chatgpt")
    target_file = "bot.py" # Default target

    if not instruction:
        return jsonify({"error": "No instruction provided"}), 400

    try:
        # 1. Read Target File
        with open(target_file, "r", encoding="utf-8") as f:
            code_content = f.read()

        # 2. Prepare Prompt
        prompt = f"""
        Act as a Senior Python Expert.
        
        TASK:
        {instruction}
        
        TARGET CODE ({target_file}):
        ```python
        {code_content}
        ```
        
        REQUIREMENTS:
        1. Return ONLY the complete, fixed Python code.
        2. DO NOT wrap with markdown code blocks (```python ... ```).
        3. NO explanations. Just code.
        4. Keep existing logic intact, only apply the requested fix.
        """
        
        fixed_code = ""
        
        # 3. Call AI
        if model_choice == "claude":
            if not HAS_CLAUDE or not config.ANTHROPIC_API_KEY:
                return jsonify({"error": "Claude API not configured (install 'anthropic' pip package & set Key)"}), 500
                
            client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
            message = client.messages.create(
                model=config.CLAUDE_MODEL,
                max_tokens=4000,
                temperature=0,
                messages=[{"role": "user", "content": prompt}]
            )
            fixed_code = message.content[0].text
            
        else: # ChatGPT
            if not config.OPENAI_API_KEY:
                return jsonify({"error": "OpenAI API Key missing"}), 500
                
            url = "https://api.openai.com/v1/chat/completions"
            headers = {"Authorization": f"Bearer {config.OPENAI_API_KEY}", "Content-Type": "application/json"}
            payload = {
                "model": config.CHATGPT_MODEL,
                "messages": [{"role": "user", "content": prompt}]
            }
            resp = requests.post(url, headers=headers, json=payload, timeout=60)
            if resp.status_code == 200:
                fixed_code = resp.json()['choices'][0]['message']['content']
            else:
                 return jsonify({"error": f"OpenAI Error: {resp.text}"}), 500

        # 4. Sanitation & Apply
        # Remove markdown fences if AI ignored instructions
        fixed_code = fixed_code.replace("```python", "").replace("```", "").strip()
        
        if not fixed_code:
             return jsonify({"error": "AI returned empty code"}), 500
             
        # Create Backup
        backup_name = f"{target_file}.bak"
        with open(backup_name, "w", encoding="utf-8") as f:
            f.write(code_content)
            
        # Overwrite
        with open(target_file, "w", encoding="utf-8") as f:
            f.write(fixed_code)
            
        # 5. Auto-Docs
        append_changelog(instruction)
        update_readme(instruction)
        
        return jsonify({
            "status": "success", 
            "message": f"Fixed {target_file}, Updated Docs. Backup saved as {backup_name}.",
            "changelog_updated": True
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/test_ai", methods=["POST"])
def api_test_ai():
    """Test AI connectivity."""
    try:
        results = ai_engine.test_ai_connectivity()
        return jsonify(results)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ==========================================
# 🛠️ AI EDITOR — Dashboard API (v2.5.0)
# ==========================================

@app.route("/api/ai-editor/status")
def api_ai_editor_status():
    """Get AI Editor current health status."""
    try:
        status = ai_editor.get_editor_status()
        return jsonify(status)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/ai-editor/proposals")
def api_ai_editor_proposals():
    """Get all proposals (newest first)."""
    try:
        proposals = ai_editor.get_pending_proposals()
        return jsonify({"proposals": proposals, "count": len(proposals)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/ai-editor/proposals/<proposal_id>/apply", methods=["POST"])
def api_ai_editor_apply(proposal_id):
    """Apply a pending proposal (config changes only in SAFE mode)."""
    try:
        result = ai_editor.apply_proposal(proposal_id)
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/ai-editor/proposals/<proposal_id>/reject", methods=["POST"])
def api_ai_editor_reject(proposal_id):
    """Reject a pending proposal."""
    try:
        result = ai_editor.reject_proposal(proposal_id)
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/ai-editor/scan", methods=["POST"])
def api_ai_editor_force_scan():
    """Force an immediate AI Editor health scan cycle."""
    try:
        result = ai_editor.run_editor_cycle(force=True)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# --- 🏛️ AI COUNCIL ENDPOINTS (v3.3.0) ---

@app.route("/api/council/history", methods=["GET"])
def get_council_history():
    """Get history of AI Council interventions."""
    try:
        if not os.path.exists(ai_council.HISTORY_FILE):
            return jsonify({"history": []})
        with open(ai_council.HISTORY_FILE, "r", encoding="utf-8") as f:
            history = json.load(f)
        return jsonify({"history": history[::-1]}) # Newest first
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/council/pending", methods=["GET"])
def get_council_pending():
    """Get pending AI Council proposals."""
    try:
        pending = ai_council.get_pending_proposals()
        return jsonify({"pending": pending})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/council/approve", methods=["POST"])
def approve_council_proposal():
    """Approve a pending AI Council proposal."""
    try:
        data = request.json
        prop_id = data.get("id")
        if not prop_id:
            return jsonify({"success": False, "message": "Missing ID"}), 400
        
        result = ai_council.approve_proposal(prop_id)
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route("/api/council/reject", methods=["POST"])
def reject_council_proposal():
    """Reject a pending AI Council proposal."""
    try:
        data = request.json
        prop_id = data.get("id")
        if not prop_id:
            return jsonify({"success": False, "message": "Missing ID"}), 400
        
        result = ai_council.reject_proposal(prop_id)
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route("/api/council/command", methods=["POST"])
def council_user_command():
    """Execute a user command via AI Council. [v3.5.1]"""
    try:
        data = request.json
        command = data.get("command", "").strip()
        if not command:
            return jsonify({"success": False, "message": "No command provided"}), 400
        
        result = ai_council.execute_user_command(command)
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

if __name__ == "__main__":
    import socket
    
    # Get all local IPs
    def get_ip_addresses():
        ip_list = []
        try:
            hostname = socket.gethostname()
            # Standard lookup
            ip_list.append(socket.gethostbyname(hostname))
            
            # Advanced lookup for all interfaces
            addrs = socket.getaddrinfo(hostname, None)
            for addr in addrs:
                ip = addr[4][0]
                if not ip.startswith("127.") and ":" not in ip and ip not in ip_list:
                    ip_list.append(ip)
        except:
            pass
        return ip_list

    print(f"\n🚀 Dashboard running locally:  http://127.0.0.1:5001")
    
    ips = get_ip_addresses()
    if ips:
        print(f"🌍 Available Network Links:")
        for ip in ips:
            if ip.startswith("100."): # Common Tailscale Range
                print(f"   🔹 Tailscale/VPN: http://{ip}:5001  <-- (Use this for Remote Access)")
            else:
                print(f"   🔸 LAN / WiFi:    http://{ip}:5001")
    else:
        print(f"🌍 Dashboard visible on LAN IPs (Check 'ipconfig')")

    print(f"\n   (If not accessible, check Windows Firewall whitelist for Python/Port 5001)")
    
    app.run(host="0.0.0.0", debug=True, use_reloader=True, port=5001)
