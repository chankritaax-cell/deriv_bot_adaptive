"""
 AI Council  Auto-Fixer Module (v3.11.38)
Specialized for real-time error detection and automated/manual fixing.
[v3.11.38] Universal Safety Guard updates & Exhaustion awareness.
"""

import os
import re
import json
import time
import datetime
import traceback
import py_compile
import shutil
import glob
import importlib
import sys
from deriv_api import DerivAPI

import config
from . import ai_providers
from .utils import log_print, log_to_file
from .asset_selector import AssetSelector  # [v3.11.0]

# Paths
# [v3.11.25] Centralized Root
ROOT = getattr(config, "ROOT_DIR", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BASE_DIR = ROOT # [v3.11.28] Safe fallback
COUNCIL_LOG_DIR = os.path.join(ROOT, "logs", "council")
HISTORY_FILE = os.path.join(COUNCIL_LOG_DIR, "history.json")
PENDING_FILE = os.path.join(COUNCIL_LOG_DIR, "pending_proposals.json")

os.makedirs(COUNCIL_LOG_DIR, exist_ok=True)

# Safety: only allow editing project .py and .json files (v5.4.0)
EDITABLE_EXTENSIONS = {".py", ".json"}
PROTECTED_FILES = {"ai_council.py", "test_ai_council.py"}

def _get_history():
    if not os.path.exists(HISTORY_FILE): return []
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except: return []

def _save_history(history):
    limit = getattr(config, "COUNCIL_HISTORY_LIMIT", 50)
    history = history[-limit:]
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)

def _get_pending():
    if not os.path.exists(PENDING_FILE): return {}
    try:
        with open(PENDING_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except: return {}

def _save_pending(pending):
    with open(PENDING_FILE, "w", encoding="utf-8") as f:
        json.dump(pending, f, indent=2, ensure_ascii=False)

# ============================================================
# ENHANCED CONTEXT GATHERING (v3.4.3)
# ============================================================

def _get_relevant_history(error_type, error_msg, max_records=5):
    """
    Get relevant historical fixes to help AI learn from past decisions.
    Returns last N fixes, prioritizing similar error types.
    """
    history = _get_history()
    if not history:
        return []
    
    # Filter and score history by relevance
    scored_history = []
    for record in history:
        score = 0
        record_context = record.get("context", {})
        record_type = record_context.get("error_type", "")
        record_error = record_context.get("error", "")
        
        # Higher score for same error type
        if record_type == error_type:
            score += 10
        
        # Higher score for similar error messages
        if error_type == "CODE_ERROR":
            # For code errors, check if same file/line mentioned
            if record_error and error_msg:
                error_words = set(error_msg.lower().split())
                record_words = set(record_error.lower().split())
                overlap = len(error_words & record_words)
                score += overlap
        
        # Boost recent fixes
        try:
            timestamp = record.get("timestamp", "")
            dt = datetime.datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            age_hours = (datetime.datetime.now(datetime.timezone.utc) - dt).total_seconds() / 3600
            if age_hours < 24:
                score += 5  # Recent fix (< 24h)
            elif age_hours < 168:
                score += 2  # This week
        except:
            pass
        
        # Penalize failed fixes
        result = record.get("result", {})
        if not result.get("success", False):
            score -= 3
        
        scored_history.append((score, record))
    
    # Sort by score (descending) and take top N
    scored_history.sort(key=lambda x: x[0], reverse=True)
    relevant = [record for score, record in scored_history[:max_records]]
    
    # Format for AI consumption
    formatted = []
    for record in relevant:
        rec_context = record.get("context", {})
        rec_proposal = record.get("proposal", {})
        rec_result = record.get("result", {})
        
        formatted.append({
            "timestamp": record.get("timestamp", ""),
            "error_type": rec_context.get("error_type", ""),
            "error": rec_context.get("error", "")[:150],  # Truncate
            "fix_title": rec_proposal.get("title", ""),
            "files_changed": [c.get("file") for c in rec_proposal.get("changes", [])],
            "success": rec_result.get("success", False),
            "outcome": rec_result.get("message", "")
        })
    
    return formatted


def _get_trading_stats():
    """
    Get current trading performance stats from dashboard state.
    Helps AI understand severity and context of the issue.
    """
    try:
        # Import here to avoid circular dependency
        from .utils import dashboard_get_state
        
        state = dashboard_get_state()
        if not state:
            return {}
        
        wins = int(state.get("total_wins", 0) or 0)
        losses = int(state.get("total_losses", 0) or 0)
        win_streak = int(state.get("win_streak", 0) or 0)
        loss_streak = int(state.get("loss_streak", 0) or 0)
        
        return {
            "total_trades": wins + losses,
            "wins": wins,
            "losses": losses,
            "win_rate": float(str(state.get("win_rate", "0")).replace("%", "")),
            "profit": float(state.get("profit", 0.0) or 0.0),
            "balance": float(state.get("balance", 0.0) or 0.0),
            "current_streak": win_streak if win_streak > 0 else -loss_streak,
            "last_signal": str(state.get("signal", "None") or "None"),
            "session_duration_mins": (time.time() - float(state.get("bot_start_ts", time.time()) or time.time())) / 60
        }
    except Exception as e:
        log_print(f" [AI Council] Could not get trading stats: {e}")
        return {}

# ============================================================
# PROJECT CONTEXT BUILDER
# ============================================================

def _build_project_map():
    """Build a map of all project .py files in root, modules/, and scripts/."""
    project_files = []
    
    # [v3.7.0] Scan multiple directories for modular awareness
    target_dirs = {
        ".": ROOT,
        "modules": os.path.join(ROOT, "modules"),
        "scripts": os.path.join(ROOT, "scripts")
    }
    
    for label, dpath in target_dirs.items():
        if not os.path.exists(dpath): continue
        
        project_files.append(f"\n {label.upper()}/")
        for fname in sorted(os.listdir(dpath)):
            fpath = os.path.join(dpath, fname)
            if not os.path.isfile(fpath) or not fname.endswith(".py"):
                continue
            if fname.startswith("test_") or fname.startswith("__"):
                continue
            
            desc = ""
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    lines = f.readlines()[:10]
                for idx, line in enumerate(lines):
                    stripped = line.strip()
                    if stripped in ('"""', "'''"):
                        if idx + 1 < len(lines):
                            desc = lines[idx + 1].strip().strip('"').strip("'").strip()
                        break
                    elif stripped.startswith('"""') or stripped.startswith("'''"):
                        desc = stripped.strip('"').strip("'").strip()
                        break
                    elif stripped.startswith("#"):
                        desc = stripped.lstrip("#").strip()
                        break
            except: pass
            
            rel_path = fname if label == "." else f"{label}/{fname}"
            project_files.append(f"  - {rel_path}  {desc}")
            
    # [v5.4.0] Include asset_profiles.json for targeted configuration edits
    profile_path = os.path.join(ROOT, "asset_profiles.json")
    if os.path.exists(profile_path):
        project_files.append(f"\n DATA/")
        project_files.append(f"  - asset_profiles.json  Asset-specific strategy parameters")
            
    return "\n".join(project_files)


def _read_file_content(filepath, max_lines=300):
    """Read file content with line numbers."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            lines = f.readlines()
        total = len(lines)
        if total > max_lines:
            lines = lines[:max_lines]
        numbered = []
        for i, line in enumerate(lines, 1):
            numbered.append(f"{i:4d}| {line.rstrip()}")
        return "\n".join(numbered), total
    except Exception as e:
        return f"(Error reading file: {e})", 0


def _extract_error_files_from_traceback(tb_text):
    """Parse traceback to find (filename, full_path, lineno) from this project."""
    results = []
    pattern = r'File ["\']([^"\']+)["\'],\s*line\s+(\d+)'
    matches = re.findall(pattern, tb_text)
    seen = set()
    for fpath, lineno in matches:
        lineno = int(lineno)
        fname = os.path.basename(fpath)
        full_path = os.path.join(ROOT, fname)
        if os.path.exists(full_path) and fname not in seen:
            seen.add(fname)
            results.append((fname, full_path, lineno))
    return results


def _read_source_context(filepath, error_line, context_lines=30):
    """Read source code around an error line with markers."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            lines = f.readlines()
        total = len(lines)
        start = max(0, error_line - context_lines - 1)
        end = min(total, error_line + context_lines)
        numbered = []
        for i in range(start, end):
            marker = " >>>" if (i + 1) == error_line else "    "
            numbered.append(f"{marker} {i+1:4d}| {lines[i].rstrip()}")
        return "\n".join(numbered)
    except Exception as e:
        return f"(Error reading source: {e})"

def _locate_snippet(content, snippet):
    """
    Locates a snippet in content with fuzzy matching support.
    Returns the exact substring from 'content' that matches, or None.
    [v3.11.4] Enhanced: Normalizes quotes, spacing, and ignores comments during match.
    """
    if not snippet or not content: return None
    
    # 1. Exact match (fastest)
    if snippet in content:
        return snippet
        
    # Helper for fuzzy normalization
    def normalize(line):
        # 1. Remove comments (only if following whitespace to avoid # in strings like "#FFFFFF")
        line = re.sub(r'\s+#.*$', '', line)
        # 2. Uniform quotes
        line = line.replace("'", '"')
        # 3. Collapse whitespace
        line = " ".join(line.split())
        return line.strip()

    # 2. Normalized Line Search
    snippet_lines = [normalize(line) for line in snippet.splitlines() if normalize(line)]
    if not snippet_lines:
        return None
        
    content_lines = content.splitlines()
    n_snip = len(snippet_lines)
    n_cont = len(content_lines)
    
    # Brute-force sliding window (O(N*M))
    for i in range(n_cont - n_snip + 1):
        # Match the block
        k = 0 # snippet line index
        j = 0 # offset in content
        matched_indices = []
        match = True
        
        while k < n_snip and (i + j) < n_cont:
             raw_cont_line = content_lines[i + j]
             c_line = normalize(raw_cont_line)
             
             # Skip empty lines in content (allow sparse matching)
             if not c_line: 
                 j += 1
                 continue
                 
             if c_line == snippet_lines[k]:
                 matched_indices.append(i + j)
                 k += 1
                 j += 1
             else:
                 match = False
                 break
        
        if match and k == n_snip:
             # Success! Return the exact lines from the original content
             start_idx = matched_indices[0]
             end_idx = matched_indices[-1]
             return "\n".join(content_lines[start_idx : end_idx + 1])

    return None



    return None


def _classify_intent(command_text):
    """
    [v3.10.0] AI Intent Classification
    Uses a fast/cheap model (Gemini) to determine if the user wants:
    - CONSULTATION: Analysis, question, status check (No Code Changes)
    - CODE_CHANGE: Explicit request to modify code, fix bugs, or change settings.
    """
    provider = getattr(config, "COUNCIL_MODERATOR_PROVIDER", "GEMINI")
    if not ai_providers._check_daily_limit(provider):
        return "CONSULTATION" # Fallback to safe mode
        
    prompt = f"""
    CLASSIFY INTENT of this user command for a trading bot.
    Command: "{command_text}"
    
    Choose one:
    - CONSULTATION: User asks for analysis, status, advice, explanation, "why", "how", "trend", "forecast", "what is".
    - CODE_CHANGE: User clearly asks to CHANGE code, FIX a bug, MODIFY settings, ADD features.
    
    Return JSON: {{"intent": "CONSULTATION" | "CODE_CHANGE"}}
    """
    
    try:
        resp = ai_providers._call_provider(provider, prompt, temperature=0.1)
        data = ai_providers._extract_json_from_text(resp)
        if data and "intent" in data:
            return data["intent"]
    except:
        pass
        
    return "CONSULTATION" # Default safe mode


def _validate_proposal(proposal):
    """Pre-validate a proposal before attempting to apply.
    Returns (is_valid, error_message).
    """
    if not isinstance(proposal, dict):
        return False, "Proposal is not a valid JSON object"
    changes = proposal.get("changes", [])
    
    # [v3.7.8] Consultation Mode: Allow empty changes if it's just advice
    if not changes:
        return True, "Consultation (No changes)"

    if not isinstance(changes, list):
        return False, "Changes matches be a list"
    for i, change in enumerate(changes):
        if not isinstance(change, dict):
            return False, f"Change #{i} is not a dict"
        for field in ["file", "search_snippet", "replace_snippet"]:
            if field not in change or not change[field]:
                return False, f"Change #{i} missing required field: {field}"
        # [v3.8.2] Search in subdirectories if not found in root
        fname = change["file"]
        target_file = None
        
        # Check Root
        possible_path = os.path.join(ROOT, fname)
        if os.path.exists(possible_path):
            target_file = possible_path
        else:
            # Check modules/ and scripts/
            for subdir in ["modules", "scripts"]:
                possible_path = os.path.join(ROOT, subdir, fname)
                if os.path.exists(possible_path):
                    target_file = possible_path
                    break
        
        if not target_file:
            # Gather all available .py files for error message
            all_files = []
            for root, dirs, files in os.walk(ROOT):
                for f in files:
                    if f.endswith(".py") and not f.startswith("test_") and "site-packages" not in root:
                        all_files.append(f)
            return False, f"File not found: {fname}. Available: {', '.join(sorted(all_files)[:20])}..."
            
        change["_full_path"] = target_file # Cache for later use

        if fname in PROTECTED_FILES:
            return False, f"File is protected: {fname}"
        _, ext = os.path.splitext(fname)
        if ext not in EDITABLE_EXTENSIONS:
            return False, f"File type not editable: {fname}"
        try:
            with open(target_file, "r", encoding="utf-8") as f:
                content = f.read()
            # [v3.9.3] Fuzzy Match Support
            found_snip = _locate_snippet(content, change["search_snippet"])
            if not found_snip:
                log_print(f" [AI Council]  Validation Failed. Could not find snippet in {fname}:")
                log_print(f"   Searching for:\n{change['search_snippet'][:200]}...")
                return False, f"search_snippet not found in {fname}. The text must match the source code (allowing for whitespace differences)."
            
            # Cache the exact match for reference (though _apply_proposal will search again)
            change["_exact_search_snippet"] = found_snip
        except Exception as e:
            return False, f"Cannot read {fname}: {e}"
        
        # Check against replace snippet (using original strict or fuzzy?)
        # If fuzzy match found, we compare that.
        if found_snip and found_snip == change["replace_snippet"]:
            log_print(f"🏛️ [AI Council] ℹ️ Change #{i} in {fname} is already applied (identical). Skipping.")
            # We don't fail here anymore; we just skip this sub-change.
            # However, if there are NO other changes, it might still look like an "empty" fix later.
            continue
        
        # [v3.11.13] Significant Change Rule for config.py numerical values
        if fname == "config.py":
            # Extract numbers from search and replace to avoid "thrashing" with tiny tweaks
            # We look for lines that look like Variable = Value
            val_pattern = r'=\s*(\d+\.?\d*)'
            s_match = re.search(val_pattern, change["search_snippet"])
            r_match = re.search(val_pattern, change["replace_snippet"])
            
            if s_match and r_match:
                try:
                    s_val = float(s_match.group(1))
                    r_val = float(r_match.group(1))
                    diff = abs(s_val - r_val)
                    if 0 < diff < 2.0:
                        return False, f"Change #{i}: Numerical tweak too small ({diff:.2f}). Must be >= 2.0 to avoid thrashing."
                    
                    # [v3.11.20] RSI Protection Rule for REAL accounts
                    if getattr(config, "DERIV_ACCOUNT_TYPE", "demo") == "real":
                        # Check if this line modifies an RSI threshold
                        rsi_keys = ["RSI_CALL_MAX", "RSI_CALL_MIN", "RSI_PUT_MIN", "RSI_PUT_MAX", "RSI_OVERBOUGHT", "RSI_OVERSOLD"]
                        if any(key in change["search_snippet"] for key in rsi_keys):
                            return False, f"Change #{i}: Direct RSI modification in config.py is blocked on REAL accounts. Use asset_profiles.json instead."
                except: pass

        # [v5.6.5] Anti-Stupidity Check: Auto-correct impossible RSI boundaries
        if fname == "asset_profiles.json":
            try:
                r_text = change["replace_snippet"]
                
                # Helper to check and swap reversed pairs
                def fix_reversed_bounds(text, min_key, max_key):
                    min_m = re.search(f'"{min_key}":\\s*([0-9.]+)', text)
                    max_m = re.search(f'"{max_key}":\\s*([0-9.]+)', text)
                    if min_m and max_m:
                        v_min = float(min_m.group(1))
                        v_max = float(max_m.group(1))
                        if v_min > v_max:
                            log_print(f"🏛️ [AI Council] ⚠️ Auto-Correcting reversed {min_key}/{max_key} ({v_min} > {v_max}). Swapping values.")
                            # Simple string replacement for these specific values
                            text = text.replace(f'"{min_key}": {v_min}', f'"{min_key}": {v_max}')
                            text = text.replace(f'"{max_key}": {v_max}', f'"{max_key}": {v_min}')
                            # Handle cases with different spacing if replace failed
                            if f'"{min_key}": {v_max}' not in text:
                                text = re.sub(f'"{min_key}":\\s*{v_min}', f'"{min_key}": {v_max}', text)
                                text = re.sub(f'"{max_key}":\\s*{v_max}', f'"{max_key}": {v_min}', text)
                    return text

                # Apply to both call and put pairs
                new_r_text = fix_reversed_bounds(r_text, "call_min", "call_max")
                new_r_text = fix_reversed_bounds(new_r_text, "put_min", "put_max")
                
                if new_r_text != r_text:
                    change["replace_snippet"] = new_r_text
                    log_print("🏛️ [AI Council] ✅ Proposal auto-corrected and validated.")
            except Exception as e:
                log_print(f" [AI Council] RSI Correction Error: {e}")
    return True, "OK"


def validate_syntax(file_path):
    """Checks if a python file has syntax errors."""
    try:
        py_compile.compile(file_path, doraise=True)
        return True, "OK"
    except py_compile.PyCompileError as e:
        return False, str(e)
    except Exception as e:
        return False, str(e)

async def resolve_error(error_msg, tb_text):
    """
    Main entry point when an error occurs.
    1. Gathers context (project map + source code).
    2. Runs AI Council discussion with full context.
    3. Validates proposal.
    4. Decides: Auto-Fix (Practice) or Pending (Real).
    """
    if not getattr(config, "ENABLE_AI_COUNCIL", False):
        return None

    log_print(f" [AI Council] Emergency Session! Error: {error_msg[:100]}...")
    
    # [v3.11.13] Cooldown Guard
    cooldown_mins = getattr(config, "COUNCIL_COOLDOWN_MINS", 30)
    history = _get_history()
    if history:
        # Check for last successful or pending fix
        last_fix_time = None
        for record in reversed(history):
            if record.get("type") in ("AUTO_FIX", "USER_APPROVAL_REQUIRED"):
                try:
                    ts = datetime.datetime.fromisoformat(record.get("timestamp", "").replace('Z', '+00:00'))
                    # Convert to localized/UTC aware
                    now = datetime.datetime.now(datetime.timezone.utc)
                    if ts.tzinfo is None: ts = ts.replace(tzinfo=datetime.timezone.utc)
                    
                    diff = (now - ts).total_seconds() / 60
                    if diff < cooldown_mins:
                        log_print(f" [AI Council]  Cooldown Active: Last fix was {diff:.1f} mins ago (limit: {cooldown_mins}m). Skipping.")
                        return None
                except: continue
    
    # Determine error type
    error_lower = error_msg.lower()
    is_consecutive_loss = "consecutive" in error_lower and "loss" in error_lower
    is_no_trade = "no_trade_timeout" in error_lower or "no trade" in error_lower

    if is_no_trade:
        error_type = "NO_TRADE_TIMEOUT"
    elif is_consecutive_loss:
        error_type = "CONSECUTIVE_LOSS"
    else:
        error_type = "CODE_ERROR"

    # 1. Gather Context (Enhanced with History & Trading Data)
    context = {
        "error": error_msg,
        "traceback": tb_text,
        "error_type": error_type,
        "account_type": config.DERIV_ACCOUNT_TYPE,
        "timestamp": datetime.datetime.now().isoformat(),
        "active_asset": config.ACTIVE_ASSET,
        "active_profile": config.ACTIVE_PROFILE
    }
    
 # comment cleaned
    context["history"] = _get_relevant_history(error_type, error_msg)
    
 # comment cleaned
    context["trading_stats"] = _get_trading_stats()

    # 2. Run Council Huddle (with full project context)
    proposal = await _run_council_huddle(context)
    if not proposal:
        log_print(" [AI Council] Failed to reach consensus or no fix possible.")
        return None

    # 3. Validate Proposal BEFORE attempting to apply
    is_valid, val_msg = _validate_proposal(proposal)
    if not is_valid:
        log_print(f" [AI Council]  Proposal rejected by validation: {val_msg}")
        record = {
            "id": f"VAL-{int(time.time())}",
            "type": "VALIDATION_REJECTED",
            "context": context,
            "proposal": proposal,
            "result": {"success": False, "message": val_msg},
            "timestamp": context["timestamp"]
        }
        history = _get_history()
        history.append(record)
        _save_history(history)
        return None

    # 4. Decision Path
    if config.DERIV_ACCOUNT_TYPE == "demo" and getattr(config, "COUNCIL_AUTO_FIX_PRACTICE", True):
        log_print(" [AI Council] ACCOUNT=PRACTICE: Attempting Auto-Fix...")
        result = _apply_proposal(proposal)
        
        record = {
            "id": f"FIX-{int(time.time())}",
            "type": "AUTO_FIX",
            "context": context,
            "proposal": proposal,
            "result": result,
            "timestamp": context["timestamp"]
        }
        history = _get_history()
        history.append(record)
        _save_history(history)
        
        if result["success"]:
            log_print(f" [AI Council]  Auto-Fix APPLIED: {result['message']}")
            return "RESTART_REQUIRED"
        else:
            log_print(f" [AI Council]  Auto-Fix FAILED: {result['message']}")
            return None
    elif config.DERIV_ACCOUNT_TYPE == "real" and not getattr(config, "COUNCIL_REAL_ADVISORY_ONLY", True):
        log_print(" [AI Council] ACCOUNT=REAL (Autonomy ON): Attempting Auto-Fix...")
        result = _apply_proposal(proposal)
        
        record = {
            "id": f"FIX-REAL-{int(time.time())}",
            "type": "AUTO_FIX_REAL",
            "context": context,
            "proposal": proposal,
            "result": result,
            "timestamp": context["timestamp"]
        }
        history = _get_history()
        history.append(record)
        _save_history(history)
        
        if result["success"]:
            log_print(f" [AI Council]  REAL Auto-Fix APPLIED: {result['message']}")
            return "RESTART_REQUIRED"
        else:
            log_print(f" [AI Council]  REAL Auto-Fix FAILED: {result['message']}")
            return None
    else:
        if getattr(config, "COUNCIL_REAL_ADVISORY_ONLY", True):
            log_print(" [AI Council] REAL Account (Advisory Mode): Suggestion follows:")
            title = proposal.get("title", "No Title")
            analysis = proposal.get("analysis", "No analysis provided.")
            log_print(f"    {title}")
            log_print(f"    {analysis}")
            
            # Print specific changes if available
            changes = proposal.get("changes", [])
            for i, c in enumerate(changes, 1):
                file = c.get("file", "Unknown")
                log_print(f"    Change {i} [{file}]: {c.get('replace_snippet', '')[:50]}...")

            log_print(" [AI Council] REAL Account (Advisory Mode): Bot will not pause. Suggestion logged.")
            return "ADVICE_GIVEN"
        else:
            log_print(" [AI Council] ACCOUNT=REAL: Saving proposal for User Approval...")
            prop_id = f"REQ-{int(time.time())}"
            pending = _get_pending()
            pending[prop_id] = {
                "id": prop_id,
                "status": "PENDING",
                "context": context,
                "proposal": proposal,
                "timestamp": context["timestamp"]
            }
            _save_pending(pending)
            return "USER_APPROVAL_REQUIRED"

def _build_council_prompt(context):
    """Build the full prompt with project context for AI Council."""
    project_map = _build_project_map()
    
    # [v3.7.0] Use docs/ directory for AI Code Rules
    ai_rules_content = ""
    rules_path = os.path.join(ROOT, "docs", "AI_CODE_RULE_BASED.md")
    try:
        if os.path.exists(rules_path):
            with open(rules_path, "r", encoding="utf-8") as f:
                ai_rules_content = f.read()
    except Exception:
        ai_rules_content = "(Rules file not found  use best judgment)"
    
    # [v3.7.1] Load PROJECT_MAP.md for architectural context
    project_overview = ""
    map_path = os.path.join(ROOT, "docs", "PROJECT_MAP.md")
    try:
        if os.path.exists(map_path):
            with open(map_path, "r", encoding="utf-8") as f:
                project_overview = f.read()
    except Exception:
        project_overview = "(Project Map not found)"
    
    source_sections = []
    error_files = _extract_error_files_from_traceback(context["traceback"])
    
    if error_files:
        for fname, fpath, lineno in error_files:
            src = _read_source_context(fpath, lineno, context_lines=25)
            source_sections.append(f"### {fname} (error at line {lineno}):\n```python\n{src}\n```")
    
    error_type = context.get("error_type", "CODE_ERROR")
    is_config_only = error_type in ("CONSECUTIVE_LOSS", "NO_TRADE_TIMEOUT")
    
    if is_config_only or not error_files:
        config_content, _ = _read_file_content(os.path.join(ROOT, "config.py"), max_lines=200)
        source_sections.append(f"### config.py (full):\n```python\n{config_content}\n```")
        
        # [v3.7.5] Council Sandbox Instruction
        source_sections.append(
            " **STRATEGIC COMMAND: Council Sandbox (v3.7.5)**\n"
            "If you are tweaking trading parameters (AMOUNT, CONFIDENCE, etc.) to fix a streak of losses or no trades:\n"
            "1. ONLY modify values within the `TIER_COUNCIL` dictionary in `config.py`.\n"
            "2. Ensure `ACTIVE_PROFILE` is set to `'TIER_COUNCIL'`.\n"
            "3. DO NOT touch TIER_MICRO, TIER_1, or other golden profiles.\n"
            "4. [v3.11.13] Use `RSI_CALL_MAX` instead of `RSI_OVERBOUGHT` and `RSI_PUT_MIN` instead of `RSI_OVERSOLD`.\n"
            "   - RSI_CALL_MAX: Maximum RSI value allowed for a CALL trade (default 65).\n"
            "   - RSI_PUT_MIN: Minimum RSI value allowed for a PUT trade (default 35).\n"
            "5. SIGNIFICANT CHANGE RULE: Numerical value changes must be >= 2.0. Avoid tiny tweaks.\n"
            "This ensures manual settings remain safe while you optimize the sandbox."
        )
        
        if error_type == "CONSECUTIVE_LOSS":
            extra_files = ["smart_trader.py", "ai_engine.py"]
        elif error_type == "NO_TRADE_TIMEOUT":
            extra_files = ["ai_engine.py", "market_engine.py", "smart_trader.py"]
        else:
            extra_files = []
        for extra_file in extra_files:
            extra_path = os.path.join(ROOT, extra_file)
            if os.path.exists(extra_path):
                content, _ = _read_file_content(extra_path, max_lines=200)
                source_sections.append(f"### {extra_file}:\n```python\n{content}\n```")

    # [v5.4.0] Targeted Asset Profile Context Injection
    if error_type == "CONSECUTIVE_LOSS":
        asset = context.get("active_asset", "UNKNOWN")
        profile_path = os.path.join(ROOT, "asset_profiles.json")
        if os.path.exists(profile_path):
            try:
                with open(profile_path, "r", encoding="utf-8") as f:
                    profiles = json.load(f)
                asset_data = profiles.get(asset, {})
                if asset_data:
                    source_sections.append(
                        f"### {asset} PROFILE (Targeted Context):\n"
                        f"This is the current configuration for the asset that just lost. ONLY modify these parameters if fixing {asset} specifically.\n"
                        f"```json\n{json.dumps({asset: asset_data}, indent=2)}\n```"
                    )
            except: pass
    
    source_context = "\n\n".join(source_sections) if source_sections else "(No source code available)"
    
 # comment cleaned
    history_section = ""
    history_data = context.get("history", [])
    if history_data:
        history_lines = [""]
        history_lines.append(" PREVIOUS FIXES (Learn from past decisions):")
        history_lines.append("")
        for i, fix in enumerate(history_data, 1):
            success_icon = "" if fix.get("success") else ""
            history_lines.append(f"\n{i}. [{fix.get('error_type')}] {fix.get('fix_title')}")
            history_lines.append(f"   Time: {fix.get('timestamp', '')[:16]}")
            history_lines.append(f"   Error: {fix.get('error', 'N/A')[:100]}")
            history_lines.append(f"   Files Changed: {', '.join(fix.get('files_changed', []))}")
            history_lines.append(f"   {success_icon} Outcome: {fix.get('outcome', 'N/A')}")
        history_lines.append("\n OSCILLATION PROTECTION (v5.4.0):")
        history_lines.append("If a similar fix failed before OR was applied recently, do NOT revert to the previous state.")
        history_lines.append("Analyze why the previous tweak wasn't enough and propose a more significant or different change.")
        history_lines.append("Avoid 'solving' a problem by reverting to a state that caused the problem in the first place.")
        history_section = "\n".join(history_lines) + "\n\n"
    
 # comment cleaned
    stats_section = ""
    stats = context.get("trading_stats", {})
    if stats:
        total = int(stats.get("total_trades", 0) or 0)
        wins = int(stats.get("wins", 0) or 0)
        losses = int(stats.get("losses", 0) or 0)
        win_rate = float(stats.get("win_rate", 0.0) or 0.0)
        profit = float(stats.get("profit", 0.0) or 0.0)
        streak = int(stats.get("current_streak", 0) or 0)
        
        stats_lines = [""]
        stats_lines.append(" TRADING PERFORMANCE (Current Session):")
        stats_lines.append("")
        stats_lines.append(f"Total Trades: {total} | Wins: {wins} | Losses: {losses}")
        stats_lines.append(f"Win Rate: {win_rate:.1f}% | Profit: ${profit:.2f}")
        stats_lines.append(f"Current Streak: {streak} | Last Signal: {stats.get('last_signal', 'None')}")
        
        # Convert to float to avoid format error
        session_mins = float(stats.get('session_duration_mins', 0))
        stats_lines.append(f"Session Duration: {session_mins:.0f} mins")
        
        # Add context hints
        if error_type == "CONSECUTIVE_LOSS":
            stats_lines.append(f"\n Context: Bot has lost {abs(streak)} consecutive trades!")
            stats_lines.append(f"   This suggests current strategy/config is not working.")
        elif error_type == "NO_TRADE_TIMEOUT":
            stats_lines.append(f"\n Context: Bot has been idle for too long (last: {stats.get('last_signal')}).")
            stats_lines.append(f"   Config may be too restrictive (high thresholds, strict filters).")
        
        stats_section = "\n".join(stats_lines) + "\n\n"
    
    if error_type == "CONSECUTIVE_LOSS":
        change_rules = """CHANGE RESTRICTIONS (Consecutive Loss):
- You may change values in config.py (thresholds, amounts, flags) OR asset_profiles.json (RSI bounds, strategy parameters).
- For RSI tuning: Edit the asset's rsi_bounds in asset_profiles.json (keys: call_min, call_max, put_min, put_max). This is a JSON file  preserve valid JSON syntax.
- Do NOT modify logic in .py files for trading losses.
- Prefer safe changes: tighten RSI bounds, lower confidence thresholds, enable guards, switch strategies.
- NEVER increase risk (higher amounts, disabled guards, wider RSI windows, etc.)."""
    elif error_type == "NO_TRADE_TIMEOUT":
        change_rules = """CHANGE RESTRICTIONS (No Trade Timeout  bot has been idle too long):
- You may ONLY change values in config.py.
- The bot has not executed any trade for a long time despite asset scanning.
- Likely causes: AI_CONFIDENCE_THRESHOLD too high, TREND_FILTER blocking all signals, wrong ACTIVE_PROFILE.
- Preferred fixes (pick the most appropriate):
  * Lower AI_CONFIDENCE_THRESHOLD (e.g., 0.70  0.60)
  * Set USE_OLLAMA_TREND_FILTER = False (temporarily disable the filter)
  * Switch ACTIVE_PROFILE to a less restrictive tier
  * Adjust SAFETY_MIN_CONFIDENCE or SAFETY_BLOCK_THRESHOLD
- NEVER increase stake amount or disable critical safety guards.
- Keep changes conservative  the goal is to resume trading, not to increase risk."""
    elif error_type == "USER_COMMAND":
        change_rules = """CHANGE RESTRICTIONS (User Command):
- If the user asks for ANALYSIS, INSIGHT, or a QUESTION (e.g. "What is the trend?"):
  * DO NOT CHANGE ANY CODE.
  * Return "changes": [] and put your answer in the "analysis" field.
  * **IMPORTANT: Write the analysis/explanation in THAI ().**
  * This is called "Consultation Mode".
- If the user explicitly asks to MODIFY code (e.g. "Change X to Y"):
  * You may modify any .py file listed in PROJECT FILES.
  * The 'file' field MUST be just the filename (e.g., "bot.py"), NOT a path.
  * search_snippet MUST be an EXACT copy-paste from the source code shown above (including spaces/indentation).
  * replacement_snippet must implement the user's requested change.
- Follow ALL rules in DEVELOPMENT STANDARDS below."""
    else:
        change_rules = """CHANGE RESTRICTIONS (Code Error):
- You may fix code in any .py file listed in PROJECT FILES.
- The 'file' field MUST be just the filename (e.g., "bot.py"), NOT a path.
- search_snippet MUST be an EXACT copy-paste from the source code shown above (including spaces/indentation).
- replace_snippet must fix the bug without changing unrelated logic.
- Keep changes minimal  fix only the root cause."""

    # [v3.5.1] Adapt task description for user commands vs errors
    if error_type == "USER_COMMAND":
        task_line = f"Execute the following user command on the Deriv Trading Bot codebase."
        error_section = f"""
USER COMMAND:
{context['error']}

CONTEXT:
- Account: {context['account_type']}
- Asset: {context['active_asset']}
- Profile: {context['active_profile']}
"""
    else:
        task_line = f"Diagnose and fix an error in the Deriv Trading Bot."
        error_section = f"""
ERROR MESSAGE:
{context['error']}

TRACEBACK:
{context['traceback']}

CONTEXT:
- Account: {context['account_type']}
- Asset: {context['active_asset']}
- Profile: {context['active_profile']}
"""

    return f"""ACT AS: Senior Python Developer specializing in async trading bots.
TASK: {task_line}
LANGUAGE: THAI () for "analysis" and "explanation" fields. Keep technical terms/code in English.

ARCHITECTURE: Modular (since v3.6.0). 
- Root: Entry points and config.
- modules/: Core logic and engines.
- scripts/: Utility and diagnostic tools.
- docs/: Rules and documentation.

{error_section}

{history_section}{stats_section}PROJECT OVERVIEW:
{project_overview}

RECENT CONSOLE LOGS (Last 50 lines):
{context.get('console_tail', '(No logs available)')}

PROJECT FILES (these are the ONLY files that exist):
{project_map}


SOURCE CODE (from files involved in the error):

{source_context}



{change_rules}


 DEVELOPMENT STANDARDS (You MUST follow these rules):

{ai_rules_content}

CRITICAL RULES:
1. [v3.11.35] Use exact `search_snippet` from the PROVIDED SOURCE CODE below. MUST be copied EXACTLY (spaces/indent).
2. The 'file' field must be a filename from the PROJECT FILES list.
3. Do NOT invent filenames or code.
4. Keep replace_snippet minimal (only fix the specific bug).
5. SIGNIFICANT CHANGE RULE: Identical changes are FORBIDDEN. If code already has the proposed state, do NOT propose it. Propose a DIFFERENT improvement or mark as NO_CHANGE.
6. Follow ALL rules in DEVELOPMENT STANDARDS above (changelog, file safety, etc.).
7. If your fix changes logic, include comment tag: # [v<VERSION>] <description>

OUTPUT FORMAT (JSON only, no markdown fences, no explanation outside JSON):
{{
    "title": "Short title of fix",
    "analysis": "Root cause analysis (1-2 sentences)",
    "risk_level": "LOW|MEDIUM|HIGH",
    "changes": [
        {{
            "file": "exact_filename.py",
            "type": "CONFIG_CHANGE|CODE_FIX",
            "description": "Short description of change",
            "search_snippet": "Exact unique string to locate in file (MUST MATCH EXACTLY)",
            "replace_snippet": "New code to replace the search_snippet"
        }}
    ]
}}

CRITICAL RULES:
1. "search_snippet" MUST BE AN EXACT COPY of the code in the file. Do not change indentation or spacing.
2. If multiple files need changes, add multiple objects to "changes".
3. If fixing a bug, provide a brief "explanation".
4. If no code change is needed (e.g. analysis only), return "changes": [] and type "CONSULTATION".
"""


def _score_proposal(proposal, provider_name):
    """Score a proposal for Multi-Vote ranking. Higher = better.
    Returns (score, detail_string).
    """
    score = 0
    details = []
    
    # 1. Valid JSON structure (+10)
    if not isinstance(proposal, dict):
        return 0, "not a dict"
    score += 10
    details.append("valid_json")
    
    # 2. Has required top-level fields (+5 each)
    for field in ["title", "analysis", "risk_level", "changes", "explanation"]:
        if field in proposal and proposal[field]:
            score += 5
            details.append(field)
    
    # 3. Changes array quality
    changes = proposal.get("changes", [])
    
    # [v3.9.4] Consultation Mode Boost
    # If no changes but has analysis/explanation -> It's a valid Consultation.
    if not isinstance(changes, list) or len(changes) == 0:
        log_print(f"DEBUG SCORING: Provider={provider_name} Analysis='{str(proposal.get('analysis'))[:20]}' Explanation='{str(proposal.get('explanation'))[:20]}'")
        if proposal.get("analysis") or proposal.get("explanation"):
            score += 100  # Massive boost to compete with code changes
            return score, f"Consultation Mode (No Code Changes) | {' '.join(details)}"
        else:
            return score, f"no_changes | {' '.join(details)}"
    
    valid_changes = 0
    for change in changes:
        if not isinstance(change, dict):
            continue
        has_fields = all(change.get(f) for f in ["file", "search_snippet", "replace_snippet"])
        if not has_fields:
            continue
        
        # +15: change has all required fields
        score += 15
        
        # +20: file actually exists in project
        fname = os.path.basename(change.get("file", ""))
        target = None
        
        # Check Root
        possible = os.path.join(ROOT, fname)
        if os.path.exists(possible):
             target = possible
        else:
             # Check subdirectories
             for subdir in ["modules", "scripts"]:
                 possible = os.path.join(ROOT, subdir, fname)
                 if os.path.exists(possible):
                     target = possible
                     break
        
        if target:
            score += 20

            
            # +30: search_snippet actually found in file (CRITICAL)
            try:
                with open(target, "r", encoding="utf-8") as f:
                    content = f.read()
                if change["search_snippet"] in content:
                    score += 30
                    details.append(f"snippet_match({fname})")
                else:
                    details.append(f"snippet_MISS({fname})")
            except:
                pass
        else:
            details.append(f"file_MISS({fname})")
        
        # +5: search and replace are different (not a no-op)
        if change["search_snippet"] != change["replace_snippet"]:
            score += 5
        
        valid_changes += 1
    
    # 4. Risk level preference: LOW > MEDIUM > HIGH
    risk = proposal.get("risk_level", "HIGH").upper()
    if risk == "LOW":
        score += 10
    elif risk == "MEDIUM":
        score += 5
    # HIGH gets +0
    
    # 5. Fewer changes is better (more focused fix)
    if valid_changes == 1:
        score += 5
    
    detail_str = f"score={score} valid_changes={valid_changes} | {' '.join(details)}"
    return score, detail_str


async def _run_council_huddle(context):
    """Multi-AI Council: queries all available providers, scores proposals, picks the best.
    Falls back to single-provider mode if COUNCIL_MULTI_VOTE is disabled.
    """
    prompt = _build_council_prompt(context)
    
    # [v3.7.9] Direct Targeting (High Priority)
    target_provider = context.get("target_provider")
    if target_provider:
        log_print(f" [AI Council]  Direct Target Requested: {target_provider}")
        # Validate if provider exists/available
        norm_target = target_provider.lower().strip()
        chain = [norm_target] # Force single-item chain
    else:
        # Standard Logic
        task_name = getattr(config, "COUNCIL_TASK_NAME", "COUNCIL")
        chain = ai_providers._get_provider_chain(task_name)
    
    use_multi_vote = getattr(config, "COUNCIL_MULTI_VOTE", False)
    
    # [v3.8.0] Exclude Ollama from Multi-Vote (Too Slow) unless targeted
    if use_multi_vote and not target_provider:
        chain = [p for p in chain if p.upper() != "OLLAMA"]
        if not chain: # Fallback if Ollama was the only one
             chain = ai_providers._get_provider_chain(task_name)
    
    if not use_multi_vote:
        # Single-provider failover mode (original behavior)
        log_print(" [AI Council] Single-provider mode...")
        return _query_single_provider_chain(prompt, chain)
    
 # comment cleaned
    # MULTI-VOTE MODE: Query all available providers
 # comment cleaned
    candidate_proposals = []
    error_text = str(context.get("error", "")).lower()
    
    # [v3.11.0] NO_TRADE_TIMEOUT -> Auto-Backtest & Switch
    if "no_trade_timeout" in error_text:
        # Check Config
        if not getattr(config, "ENABLE_AUTO_BACKTEST", True):
             log_print(" [AI Council]  NO_TRADE_TIMEOUT Detected but ENABLE_AUTO_BACKTEST is False. Skipping scan.")
        else:
            log_print(" [AI Council]  NO_TRADE_TIMEOUT Detected. Initiating Asset Scan...")
            try:
                # Create a temporary API instance for scanning
                api = DerivAPI(app_id=config.DERIV_APP_ID)
                await api.authorize(config.DERIV_API_TOKEN)
                
                best_asset, best_wr, details = await AssetSelector.find_best_asset(api, lookback_hours=12)
                await api.disconnect()
                
                if best_asset:
                    current_asset = config.ACTIVE_ASSET
                    if best_asset != current_asset and best_wr > 55.0:
                        log_print(f" [AI Council]  Found better asset: {best_asset} (WR {best_wr:.1f}%) > {current_asset}")
                        
                        # Create SYSTEM PROPOSAL
                        sys_proposal = {
                            "title": f"Switch Asset to {best_asset} (WR {best_wr:.1f}%)",
                            "analysis": f"Bot has been idle on {current_asset}. Scanned market and found {best_asset} has {best_wr:.1f}% win rate in last 12h.",
                            "risk_level": "LOW",
                            "confidence_score": 95,
                            "changes": [
                                {
                                    "file": "config.py",
                                    "search_snippet": f'ACTIVE_ASSET = "{current_asset}"',
                                    "replace_snippet": f'ACTIVE_ASSET = "{best_asset}"',
                                    "_full_path": os.path.join(ROOT, "config.py") 
                                }
                            ]
                        }
                        # Return immediately as the "Winner"
                        log_print(f" [AI Council]  System Auto-Proposal: Switch to {best_asset}")
                        return sys_proposal
                    else:
                        log_print(f" [AI Council]  Best asset {best_asset} ({best_wr:.1f}%) not significantly better or same. Proceeding to Council Vote.")
                else:
                     log_print(" [AI Council]  Asset Scan failed or no valid assets found.")
                     
            except Exception as e:
                log_print(f" [AI Council]  Asset Scan Error: {e}")

    # [v3.9.5] Analysis Guard: Detect analysis requests and force Consultation Mode
    is_analysis_request = False
    error_text = str(context.get("error", "")).lower()
    
    # [v3.9.6] Enhanced Keyword List (including Thai & Typos)
    analysis_keywords = [
        # English
        "analyze", "analysis", "trend", "forecast", "predict", "outlook", "perspective", 
        "consultation", "why", "what", "how", "chart", 
        # Thai (Correct)
        "", "", "", "", "", "", "",
        # Thai (Common Typos/Informal)
        "", "", "", "", "", "", "", ""
    ]
    
    # [v3.10.0] AI Intent Analysis Guard
    # Check if the Intent Classifier already flagged this as CONSULTATION
    user_intent = context.get("user_intent", "CODE_CHANGE")
    
    # [v3.11.1] Priority Fix: If Intent is explicitly CODE_CHANGE, TRUST IT.
    # Only fall back to keywords if intent is UNCERTAIN or CONSULTATION.
    if user_intent == "CODE_CHANGE":
        is_analysis_request = False
        log_print(f" [AI Council]  Intent: CODE_CHANGE -> Bypassing Keyword Guard.")
    else:
        is_analysis_request = (user_intent == "CONSULTATION")
        
        # [v3.9.6] Enhanced Keyword List (Fallback if classifier fails)
        analysis_keywords = [
            # English
            "analyze", "analysis", "trend", "forecast", "predict", "outlook", "perspective", 
            "consultation", "why", "what", "how", "chart", 
            # Thai (Correct)
            "", "", "", "", "", "", "",
            # Thai (Common Typos/Informal)
            "", "", "", "", "", "", "", ""
        ]
        
        error_text = str(context.get("error", "")).lower()
        if any(k in error_text for k in analysis_keywords):
            is_analysis_request = True
            log_print(f" [AI Council]  Analysis Request Detected by KEYWORD ('{error_text[:20]}...').")
    
    if is_analysis_request:
        log_print(f" [AI Council]  Intent: CONSULTATION -> Forcing 'No Code Changes' Mode.")

    log_print(f" [AI Council]  Multi-Vote mode  querying {len(chain)} providers: {', '.join(chain)}")
    
    candidates = []  # List of (score, provider, proposal, detail)
    min_votes = getattr(config, "COUNCIL_MIN_VOTES", 2)
    
    for provider in chain:
        if not ai_providers._check_daily_limit(provider):
            log_print(f" [AI Council]     {provider}: daily limit reached, skip")
            continue
        
        log_print(f" [AI Council]     Asking {provider}...")
        try:
            resp_text = ai_providers._call_provider(provider, prompt, temperature=0.2, max_tokens=4096)
        except Exception as e:
            log_print(f" [AI Council]     {provider}: call failed  {e}")
            continue
        
        if not resp_text:
            log_print(f" [AI Council]     {provider}: empty response")
            continue
        
        # Parse JSON
        try:
            proposal = ai_providers._extract_json_from_text(resp_text)
        except Exception:
            proposal = None
        
        if not proposal or not isinstance(proposal, dict):
            log_print(f" [AI Council]     {provider}: JSON parse failed")
            log_print(f"       Raw (100 chars): {resp_text[:100]}...")
            continue
        
        # [v3.9.5] Analysis Guard Enforcement
        # If this is an analysis request, STRIP any code changes to force Consultation Mode.
        # [v5.5.x] EXCEPTION: Allow changes if it's a USER_COMMAND so /tune can actually propose optimizations.
        if is_analysis_request and proposal.get("changes") and context.get("error_type") != "USER_COMMAND":
            log_print(f" [AI Council]     Guard: Stripping code changes from {provider} (Analysis Request).")
            proposal["changes"] = [] # Force empty list
        
        # Score the proposal
        score, detail = _score_proposal(proposal, provider)
        proposal["_source_provider"] = provider  # Tag which AI proposed this
        candidates.append((score, provider, proposal, detail))
        log_print(f" [AI Council]     {provider}: {proposal.get('title', '?')}  {detail}")
    
    if not candidates:
        log_print(" [AI Council]  No valid proposals from any provider.")
        return None
    
    # Sort by score (highest first)
    candidates.sort(key=lambda x: x[0], reverse=True)
    
    # Log the vote result
    log_print(f" [AI Council]  Vote Results ({len(candidates)} proposals):")
    for rank, (score, provider, proposal, detail) in enumerate(candidates, 1):
        marker = "" if rank == 1 else "  "
        log_print(f"   {marker} #{rank}: {provider} (Score: {score}) - {proposal.get('title', '?')}")
    
    # Pick the winner
    best_score, best_provider, best_proposal, best_detail = candidates[0]
    
    if best_score < 30:
        log_print(f" [AI Council]  Best score too low ({best_score}). No confident fix.")
        return None
    
    log_print(f" [AI Council]  Winner: {best_provider} (score={best_score})")
    log_print(f"   Title: {best_proposal.get('title', '?')}")
    log_print(f"   Risk: {best_proposal.get('risk_level', '?')} | Changes: {len(best_proposal.get('changes', []))}")
    
    return best_proposal


def _query_single_provider_chain(prompt, chain):
    """Fallback: single-provider failover (original behavior)."""
    for provider in chain:
        if not ai_providers._check_daily_limit(provider):
            continue
        log_print(f" [AI Council] Trying {provider}...")
        resp_text = ai_providers._call_provider(provider, prompt, temperature=0.2, max_tokens=4096)
        if not resp_text:
            continue
        try:
            proposal = ai_providers._extract_json_from_text(resp_text)
            if proposal and isinstance(proposal, dict):
                log_print(f" [AI Council] Proposal from {provider}: {proposal.get('title', '?')}")
                return proposal
        except Exception:
            pass
    log_print(" [AI Council] No response from any AI provider.")
    return None

def _apply_proposal(proposal):
    """Executes the changes with backups and syntax checks.
    All changes are atomic  if any fails, all are rolled back.
    On success: bumps version and appends CHANGELOG entry.
    """
    changes = proposal.get("changes", [])
    if not changes: return {"success": False, "message": "No changes proposed"}

    current_version = getattr(config, "BOT_VERSION", "0.0.0")
    applied_files = []
    backup_map = {}
    
    try:
        for change in changes:
            # [v3.8.2] Support subdirectories via cached path or dynamic search
            target_file = change.get("_full_path")
            
            if not target_file:
                # Fallback: Check root
                target_file = os.path.join(ROOT, change["file"])
                if not os.path.exists(target_file):
                    # Fallback: Check subdirectories
                    for subdir in ["modules", "scripts"]:
                        possible = os.path.join(ROOT, subdir, change["file"])
                        if os.path.exists(possible):
                            target_file = possible
                            break

            if not os.path.exists(target_file):
                _rollback_all(backup_map)
                return {"success": False, "message": f"File not found: {change['file']}"}
            
            # 1. Backup
            backup_file = target_file + f".v{current_version}.bak"
            if os.path.exists(backup_file):
                counter = 1
                while os.path.exists(f"{target_file}.v{current_version}.{counter}.bak"):
                    counter += 1
                backup_file = f"{target_file}.v{current_version}.{counter}.bak"
            shutil.copy2(target_file, backup_file)
            backup_map[target_file] = backup_file
            log_print(f" [AI Council] Backup: {os.path.basename(backup_file)}")
            
            # 2. Read & Replace
            with open(target_file, "r", encoding="utf-8") as f:
                content = f.read()
            
            search = change["search_snippet"]
            replace = change["replace_snippet"]
            
            # [v3.9.3] Fuzzy Match Application
            # Use the helper to find the EXACT text in the file (handling whitespace differences)
            exact_search = _locate_snippet(content, search)
            
            if not exact_search:
                _rollback_all(backup_map)
                return {"success": False, "message": f"search_snippet not found in {change['file']} (fuzzy search failed)"}
            
            # Replace the ACTUAL found text with the new text
            new_content = content.replace(exact_search, replace, 1)
            
 # comment cleaned
            with open(target_file, "w", encoding="utf-8") as f:
                f.write(new_content)
                f.flush()  # Force flush to OS buffer
                os.fsync(f.fileno())  # Force OS to write to disk NOW
            
            # 4. Syntax Validation
            if target_file.endswith(".py"):
                ok, err = validate_syntax(target_file)
                if not ok:
                    _rollback_all(backup_map)
                    return {"success": False, "message": f"Syntax Error after fix in {change['file']}: {err}"}
            
            applied_files.append(change["file"])
            log_print(f" [AI Council]  Applied change to: {change['file']}")

 # comment cleaned
        _clear_python_cache(applied_files)
        
        # 6. Post-fix: Bump version + Update CHANGELOG
        new_version = _bump_patch_version(current_version)
        _update_version_in_config(current_version, new_version)
        _append_changelog(new_version, proposal, applied_files)
        log_print(f" [AI Council]  Version bumped: v{current_version}  v{new_version}")
        
        # 7. Determine if restart is required (e.g., if any .py files were changed)
        restart_required = any(f.endswith(".py") for f in applied_files)
        
        return {
            "success": True,
            "message": f"Applied changes to: {', '.join(applied_files)}",
            "files": applied_files,
            "old_version": current_version,
            "new_version": new_version,
            "restart_required": restart_required
        }

    except Exception as e:
        _rollback_all(backup_map)
        return {"success": False, "message": f"IO Error: {str(e)}"}

def _clear_python_cache(modified_files):
    """
    Clear Python bytecode cache for modified files.
    This ensures next import reads fresh .py files.
    
    Args:
        modified_files: List of filenames (e.g., ['config.py', 'ai_engine.py'])
    """
    """
    [v3.11.28] Explicit recursive pycache clearing + module reloading.
    """
    try:
        cleared_count = 0
        import glob
        import importlib
        
        # 1. Clear ALL pycache directories under ROOT for the specific modified modules
        for root_dir, dirs, files in os.walk(ROOT):
            if "__pycache__" in dirs:
                pyc_path = os.path.join(root_dir, "__pycache__")
                for filename in modified_files:
                    m_base = os.path.basename(filename).replace(".py", "")
                    # Match module name in pycache: name.cpython-*.pyc
                    for pyc in glob.glob(os.path.join(pyc_path, f"{m_base}.*.pyc")):
                        try:
                            os.remove(pyc)
                            cleared_count += 1
                        except: pass

        # 2. Smart Module Reload
        for filename in modified_files:
            if not filename.endswith('.py'): continue
            
            # Resolve module name: 'modules/utils.py' -> 'modules.utils'
            rel_path = os.path.relpath(filename, ROOT).replace("\\", "/")
            if ".." in rel_path: continue 
            
            mod_name = rel_path.replace(".py", "").replace("/", ".")
            if mod_name.startswith("."): mod_name = mod_name[1:]
            
            if mod_name in sys.modules:
                try:
                    importlib.reload(sys.modules[mod_name])
                    log_print(f"  Reloaded: {mod_name}")
                except Exception as e:
                    log_print(f"  Reload failed ({mod_name}): {e}")
            
            # Fallback for root modules (e.g. 'config')
            root_m = os.path.basename(filename).replace(".py", "")
            if root_m in sys.modules and root_m != mod_name:
                try:
                    importlib.reload(sys.modules[root_m])
                    log_print(f"  Reloaded root: {root_m}")
                except: pass

        log_print(f" [AI Council]  Cleared {cleared_count} cache file(s)")
    except Exception as e:
        log_print(f" [AI Council] Cache clear failed: {e}")

def _rollback_all(backup_map):
    """Rollback all files from their backups."""
    for original, backup in backup_map.items():
        try:
            if os.path.exists(backup):
                shutil.copy2(backup, original)
                log_print(f" [AI Council] Rolled back: {os.path.basename(original)}")
        except Exception as e:
            log_print(f" [AI Council]  Rollback failed for {original}: {e}")


# ============================================================
# VERSION & CHANGELOG MANAGEMENT
# ============================================================

def _bump_patch_version(version_str):
    """Bump patch version: '3.4.0' -> '3.4.1'."""
    try:
        parts = version_str.split(".")
        parts[-1] = str(int(parts[-1]) + 1)
        return ".".join(parts)
    except Exception:
        return version_str + ".1"


def _update_version_in_config(old_version, new_version):
    """Update BOT_VERSION in config.py (single source of truth)."""
    config_path = os.path.join(ROOT, "config.py")
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        old_line = f'BOT_VERSION = "{old_version}"'
        new_line = f'BOT_VERSION = "{new_version}"'
        
        if old_line in content:
            content = content.replace(old_line, new_line, 1)
            
 # comment cleaned
            with open(config_path, "w", encoding="utf-8") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            
            # Update runtime value
            config.BOT_VERSION = new_version
            
            log_print(f" [AI Council] Updated config.py: BOT_VERSION = \"{new_version}\"")
        else:
            log_print(f" [AI Council]  Could not find BOT_VERSION line in config.py")
    
    except Exception as e:
        log_print(f" [AI Council]  Failed to update config.py version: {e}")

def _append_changelog(new_version, proposal, applied_files):
    # [v3.9.2] Fix: CHANGELOG is now in docs/
    changelog_path = os.path.join(ROOT, "docs", "CHANGELOG.md")
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    
    # Build change descriptions from proposal
    change_lines = []
    for change in proposal.get("changes", []):
        desc = change.get("description", "Code fix")
        fname = change.get("file", "unknown")
        change_type = change.get("type", "CODE_FIX")
        change_lines.append(f"- **[{change_type}] {fname}:** {desc}")
    
    title = proposal.get("title", "AI Council Auto-Fix")
    analysis = proposal.get("analysis", "")
    
    entry = f"""
## [v{new_version}] - {today}
 # comment cleaned
- **{title}**
{chr(10).join(change_lines)}
- _Analysis: {analysis}_
- _Files: {', '.join(applied_files)}_
"""
    
    try:
        if os.path.exists(changelog_path):
            with open(changelog_path, "r", encoding="utf-8") as f:
                content = f.read()
 # comment cleaned
            header_end = content.find("\n## [")
            if header_end == -1:
                # No existing version entries, append at end
                content = content.rstrip() + "\n" + entry
            else:
                # Insert new entry before the first existing version entry
                content = content[:header_end] + "\n" + entry + content[header_end:]
            with open(changelog_path, "w", encoding="utf-8") as f:
                f.write(content)
        else:
            with open(changelog_path, "w", encoding="utf-8") as f:
                f.write(f"# Changelog (Deriv Bot)\n\n{entry}")
        
        log_print(f" [AI Council]  CHANGELOG.md updated with v{new_version} entry")
    except Exception as e:
        log_print(f" [AI Council]  Failed to update CHANGELOG.md: {e}")


def get_pending_proposals():
    return list(_get_pending().values())

def approve_proposal(prop_id):
    pending = _get_pending()
    if prop_id not in pending: return {"success": False, "message": "Proposal not found"}
    
    proposal_data = pending.pop(prop_id)
    
    # Re-validate before applying (source may have changed since proposal was created)
    is_valid, val_msg = _validate_proposal(proposal_data["proposal"])
    if not is_valid:
        _save_pending(pending)
        record = {
            "id": prop_id,
            "type": "APPROVAL_FAILED",
            "context": proposal_data["context"],
            "proposal": proposal_data["proposal"],
            "result": {"success": False, "message": f"Validation failed: {val_msg}"},
            "timestamp": datetime.datetime.now().isoformat()
        }
        history = _get_history()
        history.append(record)
        _save_history(history)
        return {"success": False, "message": f"Validation failed: {val_msg}"}
    
    result = _apply_proposal(proposal_data["proposal"])
    
    record = {
        "id": prop_id,
        "type": "USER_APPROVED",
        "context": proposal_data["context"],
        "proposal": proposal_data["proposal"],
        "result": result,
        "timestamp": datetime.datetime.now().isoformat()
    }
    history = _get_history()
    history.append(record)
    _save_history(history)
    _save_pending(pending)
    
    return result

def reject_proposal(prop_id):
    pending = _get_pending()
    if prop_id not in pending: return {"success": False, "message": "Proposal not found"}
    
    proposal_data = pending.pop(prop_id)
    record = {
        "id": prop_id,
        "type": "USER_REJECTED",
        "context": proposal_data["context"],
        "proposal": proposal_data["proposal"],
        "timestamp": datetime.datetime.now().isoformat()
    }
    history = _get_history()
    history.append(record)
    _save_history(history)
    _save_pending(pending)
    return {"success": True, "message": "Proposal rejected"}


# ============================================================
 # comment cleaned
# ============================================================

def execute_user_command(command_text):
    """
    Synchronous entry point for user commands (v3.7.4).
    Used by Dashboard server.
    """
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # If we're already in an async context (e.g., dashboard running in async loop), use bridge
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(
                    asyncio.run, execute_user_command_async(command_text)
                ).result(timeout=120)
        else:
            return loop.run_until_complete(execute_user_command_async(command_text))
    except Exception as e:
        log_print(f" [AI Council] Sync command bridge fail: {e}")
        return {"success": False, "message": f"Execution failed: {str(e)}"}

async def execute_user_command_async(command_text):
    """
    Execute a user command via AI Council.
    Always saves as pending for user approval (never auto-fix).
    Returns: dict with proposal info or error.
    """
    if not command_text or not command_text.strip():
        return {"success": False, "message": "Empty command"}
    
    log_print(f" [AI Council] User Command: {command_text[:100]}...")
    
    # [v3.10.0] Classify Intent
    user_intent = _classify_intent(command_text)
    log_print(f" [AI Council]  Intent Classifier: {user_intent}")
    
    # Build context (no traceback for user commands)
    context = {
        "error": command_text,
        "user_intent": user_intent,

        "traceback": f"User requested code change via Dashboard/Telegram:\n{command_text}",
        "error_type": "USER_COMMAND",
        "account_type": config.DERIV_ACCOUNT_TYPE,
        "timestamp": datetime.datetime.now().isoformat(),
        "active_asset": config.ACTIVE_ASSET,
        "active_profile": config.ACTIVE_PROFILE
    }
    
    # [v3.7.9] Check if command is a JSON payload (Targeted Command)
    target_provider = None
    try:
        if command_text.startswith("{") and "target" in command_text:
            payload = json.loads(command_text)
            command_text = payload.get("text", "")
            target_provider = payload.get("target")
            log_print(f" [AI Council]  Target Provider: {target_provider}")
            
            # Update context with cleaner command text
            context["error"] = command_text
            context["traceback"] = f"User requested code change via Dashboard/Telegram:\n{command_text}"
            context["target_provider"] = target_provider
    except:
        pass # Not a JSON payload, treat as raw text

    # Add trading stats for context
    context["trading_stats"] = _get_trading_stats()
    
    # [v3.7.8] Add Recent Console Logs (Last 50 lines) for "Check Logs" requests
    try:
        log_file = os.path.join(ROOT, "logs", "console", f"console_log_{datetime.date.today()}.txt")
        if os.path.exists(log_file):
            with open(log_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
                context["console_tail"] = "".join(lines[-50:])
    except Exception as e:
        log_print(f" [AI Council] Failed to read console log: {e}")
    
    # Run Council Huddle
    try:
        proposal = await _run_council_huddle(context)
    except Exception as e:
        log_print(f" [AI Council] Command execution error: {e}")
        return {"success": False, "message": f"AI Council error: {str(e)}"}
    
    if not proposal:
        return {"success": False, "message": "AI Council (or Target) could not generate a proposal."}
    
    # Validate proposal
    is_valid, val_msg = _validate_proposal(proposal)
    if not is_valid:
        log_print(f" [AI Council]  Command proposal rejected: {val_msg}")
        return {"success": False, "message": f"Proposal validation failed: {val_msg}"}
        
    prop_id = f"CMD-{int(time.time())}"

    # [v3.7.8] Detect Consultation Mode (No changes)
    if not proposal.get("changes"):
        log_print(" [AI Council]  Consultation Mode: Saving advice to history (no code change).")
        
        # Save directly to history as "CONSULTATION"
        record = {
            "id": prop_id,
            "type": "CONSULTATION",
            "context": context,
            "proposal": proposal,
            "result": {"success": True, "message": "Consultation provided"},
            "timestamp": datetime.datetime.now().isoformat()
        }
        
        history = _get_history()
        history.append(record)
        _save_history(history)
        
        return {
            "success": True, 
            "message": "Consultation provided",
            "proposal": proposal,
            "type": "CONSULTATION"
        }
    
    # Always save as pending for user approval
    pending = _get_pending()
    pending[prop_id] = {
        "id": prop_id,
        "status": "PENDING",
        "context": context,
        "proposal": proposal,
        "timestamp": context["timestamp"]
    }
    _save_pending(pending)
    
    log_print(f" [AI Council]  Command proposal saved: {prop_id}")
    return {
        "success": True,
        "message": f"Proposal created: {prop_id}",
        "proposal_id": prop_id,
        "proposal": proposal
    }

async def approve_proposal_async(prop_id):
    """Async wrapper for proposal approval."""
    pending = _get_pending()
    if prop_id not in pending: return {"success": False, "message": "Proposal not found"}
    
    proposal_data = pending.pop(prop_id)
    proposal = proposal_data["proposal"]
    
    log_print(f" [AI Council]  User Approved Proposal: {prop_id}")
    
    # Apply changes
    result = _apply_proposal(proposal)
    
    # Move to history
    record = {
        "id": prop_id,
        "type": "USER_APPROVED",
        "context": proposal_data["context"],
        "proposal": proposal_data["proposal"],
        "result": result,
        "timestamp": datetime.datetime.now().isoformat()
    }
    history = _get_history()
    history.append(record)
    _save_history(history)
    _save_pending(pending)
    
    return result

async def reject_proposal_async(prop_id):
    """Async wrapper for proposal rejection."""
    pending = _get_pending()
    if prop_id not in pending: return {"success": False, "message": "Proposal not found"}
    
    proposal_data = pending.pop(prop_id)
    record = {
        "id": prop_id,
        "type": "USER_REJECTED",
        "context": proposal_data["context"],
        "proposal": proposal_data["proposal"],
        "timestamp": datetime.datetime.now().isoformat()
    }
    history = _get_history()
    history.append(record)
    _save_history(history)
    _save_pending(pending)
    return {"success": True, "message": "Proposal rejected"}
