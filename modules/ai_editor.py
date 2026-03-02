"""
🛠️ AI Editor — SAFE Mode (v2.5.0)
Automated Health Monitoring + AI Consensus + Code Proposal System.

3 Levels:
  L1: Health Scanner — Hourly log scan for anomalies
  L2: AI Consensus   — Multi-AI vote on detected issues
  L3: Proposal       — Generate fix proposal → save to file → notify

SAFE Mode: Never auto-applies logic changes. Human must approve via Dashboard.
"""

import os
import re
import json
import time
import datetime
import glob
import requests
import traceback

import config
from . import ai_engine
from .utils import log_print, log_to_file

# ============================================================
# PATHS & CONSTANTS
# ============================================================

# [v3.11.25] Centralized Root
ROOT = getattr(config, "ROOT_DIR", os.getcwd())
LOG_DIR = os.path.join(ROOT, "logs")
EDITOR_LOG_DIR = os.path.join(LOG_DIR, "ai_editor")
PROPOSALS_DIR = os.path.join(EDITOR_LOG_DIR, "proposals")
HEALTH_LOG_DIR = os.path.join(EDITOR_LOG_DIR, "health")

os.makedirs(PROPOSALS_DIR, exist_ok=True)
os.makedirs(HEALTH_LOG_DIR, exist_ok=True)

# Status file for dashboard
EDITOR_STATUS_FILE = os.path.join(EDITOR_LOG_DIR, "editor_status.json")

# ============================================================
# L1: HEALTH SCANNER
# ============================================================

# Anomaly patterns to detect in console logs
ANOMALY_PATTERNS = [
    {"pattern": r"❌.*Error|ERROR|Traceback|Exception", "category": "ERROR", "severity": "high"},
    {"pattern": r"AI JSON Parse Error", "category": "AI_PARSE_ERROR", "severity": "medium"},
    {"pattern": r"All providers failed", "category": "AI_ALL_FAIL", "severity": "high"},
    {"pattern": r"DAILY MAX LOSS HIT", "category": "MAX_LOSS", "severity": "critical"},
    {"pattern": r"No valid open assets found", "category": "NO_ASSETS", "severity": "low"},
    {"pattern": r"Connection lost|Reconnecting", "category": "CONNECTION", "severity": "medium"},
    {"pattern": r"LOSS\.\.", "category": "TRADE_LOSS", "severity": "info"},
    {"pattern": r"WIN!!", "category": "TRADE_WIN", "severity": "info"},
    {"pattern": r"SESSION PAUSE", "category": "SESSION_PAUSE", "severity": "medium"},
    {"pattern": r"Loss Streak Cooldown", "category": "LOSS_STREAK", "severity": "medium"},
    {"pattern": r"HARD STOP", "category": "HARD_STOP", "severity": "critical"},
    {"pattern": r"Execution Failed", "category": "EXEC_FAIL", "severity": "high"},
    {"pattern": r"GPT says HOLD", "category": "GPT_HOLD", "severity": "low"},
    {"pattern": r"STRICT GATE.*BLOCK", "category": "GATE_BLOCK", "severity": "info"},
    {"pattern": r"SMART SKIP", "category": "SMART_SKIP", "severity": "info"},
    {"pattern": r"missing.*API.*KEY|GEMINI_API_KEY|OPENAI_API_KEY", "category": "MISSING_KEY", "severity": "high"},
]


def _get_latest_console_log():
    """Find the latest console log file."""
    pattern = os.path.join(LOG_DIR, "console", "console_log_*.txt")
    files = glob.glob(pattern)
    if not files:
        return None
    return max(files, key=os.path.getmtime)


def _get_performance_data():
    """Load performance.json."""
    # [v3.11.25] Align with smart_trader.py path
    perf_file = os.path.join(ROOT, "logs", "smart_data", "performance.json")
    if not os.path.exists(perf_file):
        return None
    try:
        with open(perf_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return None


def _read_recent_log_lines(filepath, max_lines=500):
    """Read last N lines from a log file efficiently."""
    if not filepath or not os.path.exists(filepath):
        return []
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        return lines[-max_lines:]
    except:
        return []


def scan_health(hours_back=1):
    """
    L1: Health Scanner — Analyze recent logs for anomalies.
    
    Returns:
        dict: Health report with anomalies, stats, and overall status
    """
    log_print("🔍 [AI Editor L1] Health Scanner running...")
    
    report = {
        "timestamp": datetime.datetime.now().isoformat(),
        "scan_hours": hours_back,
        "status": "HEALTHY",  # HEALTHY, WARNING, CRITICAL
        "anomalies": [],
        "stats": {
            "total_lines_scanned": 0,
            "errors": 0,
            "warnings": 0,
            "trades_won": 0,
            "trades_lost": 0,
            "win_rate": 0.0,
            "ai_failures": 0,
            "gate_blocks": 0,
            "smart_skips": 0,
        },
        "issues": [],  # Summarized issues for L2
    }
    
    # 1. Scan Console Log
    log_file = _get_latest_console_log()
    if not log_file:
        report["issues"].append({"type": "NO_LOG", "message": "No console log file found", "severity": "medium"})
        report["status"] = "WARNING"
        _save_health_report(report)
        return report
    
    lines = _read_recent_log_lines(log_file, max_lines=1000)
    report["stats"]["total_lines_scanned"] = len(lines)
    
    # Filter to recent hours
    cutoff = datetime.datetime.now() - datetime.timedelta(hours=hours_back)
    recent_lines = []
    for line in lines:
        # Try to extract timestamp from log line
        ts_match = re.match(r"\[(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})", line)
        if ts_match:
            try:
                line_ts = datetime.datetime.strptime(ts_match.group(1), "%Y-%m-%d %H:%M:%S")
                if line_ts >= cutoff:
                    recent_lines.append(line)
            except:
                recent_lines.append(line)  # Include if can't parse
        else:
            recent_lines.append(line)  # Include non-timestamped lines
    
    if not recent_lines:
        recent_lines = lines[-200:]  # Fallback: use last 200 lines
    
    # 2. Pattern matching for anomalies
    anomaly_counts = {}
    for line in recent_lines:
        for pattern_def in ANOMALY_PATTERNS:
            if re.search(pattern_def["pattern"], line, re.IGNORECASE):
                cat = pattern_def["category"]
                anomaly_counts[cat] = anomaly_counts.get(cat, 0) + 1
                
                # Track specifics
                if cat == "TRADE_WIN":
                    report["stats"]["trades_won"] += 1
                elif cat == "TRADE_LOSS":
                    report["stats"]["trades_lost"] += 1
                elif cat in ("AI_PARSE_ERROR", "AI_ALL_FAIL"):
                    report["stats"]["ai_failures"] += 1
                elif cat in ("ERROR", "EXEC_FAIL", "MISSING_KEY"):
                    report["stats"]["errors"] += 1
                elif cat in ("SESSION_PAUSE", "LOSS_STREAK", "CONNECTION"):
                    report["stats"]["warnings"] += 1
                elif cat == "GATE_BLOCK":
                    report["stats"]["gate_blocks"] += 1
                elif cat == "SMART_SKIP":
                    report["stats"]["smart_skips"] += 1
    
    report["anomalies"] = [{"category": k, "count": v} for k, v in anomaly_counts.items()]
    
    # 3. Calculate win rate
    total_trades = report["stats"]["trades_won"] + report["stats"]["trades_lost"]
    if total_trades > 0:
        report["stats"]["win_rate"] = round(report["stats"]["trades_won"] / total_trades * 100, 1)
    
    # 4. Performance data analysis
    perf = _get_performance_data()
    if perf and "trades" in perf:
        recent_trades = perf["trades"][-20:]  # Last 20 trades
        if recent_trades:
            wins = sum(1 for t in recent_trades if t.get("result") == "WIN")
            losses = sum(1 for t in recent_trades if t.get("result") == "LOSS")
            if wins + losses > 0:
                report["stats"]["recent_20_wr"] = round(wins / (wins + losses) * 100, 1)
    
    # 5. Generate issues list for L2
    issues = []
    
    # High error rate
    if report["stats"]["errors"] >= 5:
        issues.append({
            "type": "HIGH_ERROR_RATE",
            "message": f"Found {report['stats']['errors']} errors in last {hours_back}h",
            "severity": "high",
            "details": {k: v for k, v in anomaly_counts.items() if k in ("ERROR", "EXEC_FAIL", "MISSING_KEY")}
        })
    
    # AI failures
    if report["stats"]["ai_failures"] >= 3:
        issues.append({
            "type": "AI_FAILURE_RATE",
            "message": f"AI failures: {report['stats']['ai_failures']} in last {hours_back}h",
            "severity": "medium",
            "details": {k: v for k, v in anomaly_counts.items() if k in ("AI_PARSE_ERROR", "AI_ALL_FAIL")}
        })
    
    # Low win rate
    if total_trades >= 3 and report["stats"]["win_rate"] < 35:
        issues.append({
            "type": "LOW_WIN_RATE",
            "message": f"Win rate {report['stats']['win_rate']}% ({report['stats']['trades_won']}W/{report['stats']['trades_lost']}L) in last {hours_back}h",
            "severity": "high",
            "details": {"win_rate": report["stats"]["win_rate"], "trades": total_trades}
        })
    
    # Too many gate blocks (no trades getting through)
    if report["stats"]["gate_blocks"] >= 10 and total_trades == 0:
        issues.append({
            "type": "GATE_BLOCKING_ALL",
            "message": f"Gate blocked {report['stats']['gate_blocks']} trades, 0 executed in last {hours_back}h",
            "severity": "high",
            "details": {"gate_blocks": report["stats"]["gate_blocks"]}
        })
    
    # Too many smart skips
    if report["stats"]["smart_skips"] >= 15 and total_trades <= 1:
        issues.append({
            "type": "SMART_SKIP_EXCESSIVE",
            "message": f"Smart Trader skipped {report['stats']['smart_skips']} signals, only {total_trades} trades in last {hours_back}h",
            "severity": "medium",
            "details": {"smart_skips": report["stats"]["smart_skips"]}
        })
    
    # Critical events
    for cat in ("MAX_LOSS", "HARD_STOP"):
        if anomaly_counts.get(cat, 0) > 0:
            issues.append({
                "type": cat,
                "message": f"Critical event: {cat} detected",
                "severity": "critical"
            })
    
    # No trades at all
    if total_trades == 0 and len(recent_lines) > 50:
        issues.append({
            "type": "NO_TRADES",
            "message": f"No trades executed in last {hours_back}h despite {len(recent_lines)} log lines",
            "severity": "medium"
        })
    
    report["issues"] = issues
    
    # 6. Determine overall status
    severities = [i["severity"] for i in issues]
    if "critical" in severities:
        report["status"] = "CRITICAL"
    elif "high" in severities:
        report["status"] = "WARNING"
    elif len(issues) >= 3:
        report["status"] = "WARNING"
    else:
        report["status"] = "HEALTHY"
    
    _save_health_report(report)
    
    status_emoji = {"HEALTHY": "✅", "WARNING": "⚠️", "CRITICAL": "🚨"}.get(report["status"], "❓")
    log_print(f"🔍 [AI Editor L1] Scan Complete: {status_emoji} {report['status']} | "
              f"Issues: {len(issues)} | Trades: {total_trades} (WR: {report['stats']['win_rate']}%)")
    
    return report


def _save_health_report(report):
    """Save health report to file."""
    try:
        # Save latest status
        with open(EDITOR_STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        
        # Append to daily history
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        history_file = os.path.join(HEALTH_LOG_DIR, f"health_{today}.jsonl")
        with open(history_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(report, ensure_ascii=False) + "\n")
    except Exception as e:
        log_print(f"❌ [AI Editor] Failed to save health report: {e}")


# ============================================================
# L2: AI CONSENSUS
# ============================================================

def request_ai_consensus(issues):
    """
    L2: AI Consensus — Ask multiple AIs to vote on detected issues.
    
    Each AI votes: FIX_NOW / MONITOR / IGNORE with a reason.
    Requires ≥2 AIs to agree on FIX_NOW to escalate to L3.
    
    Args:
        issues: List of issue dicts from L1
        
    Returns:
        dict: Consensus result with votes and final decision
    """
    if not issues:
        return {"decision": "NO_ISSUES", "votes": []}
    
    log_print(f"🗳️ [AI Editor L2] Requesting AI Consensus on {len(issues)} issues...")
    
    # Build prompt
    issues_text = "\n".join([
        f"  {i+1}. [{iss['severity'].upper()}] {iss['type']}: {iss['message']}"
        for i, iss in enumerate(issues)
    ])
    
    prompt = f"""ACT AS: Trading Bot Health Analyst.
TASK: Evaluate these bot issues and vote on each.

DETECTED ISSUES:
{issues_text}

BOT CONTEXT:
- Binary Options trading bot (IQ Option)
- Strategies: TREND_FOLLOWING, MEAN_REVERSION, MOMENTUM
- AI-powered with Pre-Gate, Bet Gate, Smart Trader filters
- Running on OTC pairs

For each issue, vote:
- FIX_NOW: This needs immediate code/config change
- MONITOR: Watch it, but don't change code yet
- IGNORE: Normal behavior or false positive

OUTPUT JSON:
{{
    "votes": [
        {{"issue": "issue_type", "vote": "FIX_NOW|MONITOR|IGNORE", "reason": "brief explanation", "suggested_fix": "what to change (if FIX_NOW)"}}
    ],
    "overall_assessment": "brief summary of bot health",
    "urgency": "HIGH|MEDIUM|LOW"
}}
"""
    
    # Ask multiple AIs
    votes_by_provider = {}
    providers_to_ask = _get_consensus_providers()
    
    for provider in providers_to_ask:
        try:
            log_print(f"   🧠 [L2] Asking {provider}...")
            response = _call_single_provider(provider, prompt)
            if response:
                parsed = ai_engine._extract_json_from_text(response)
                if parsed and isinstance(parsed, dict):
                    votes_by_provider[provider] = parsed
                    log_print(f"   ✅ [L2] {provider} voted: urgency={parsed.get('urgency', '?')}")
                else:
                    log_print(f"   ⚠️ [L2] {provider} returned invalid JSON")
            else:
                log_print(f"   ⚠️ [L2] {provider} no response")
        except Exception as e:
            log_print(f"   ❌ [L2] {provider} error: {e}")
    
    if not votes_by_provider:
        log_print("❌ [AI Editor L2] No AI responses received!")
        return {"decision": "NO_VOTES", "votes": {}, "providers_asked": providers_to_ask}
    
    # Tally votes per issue
    consensus = _tally_votes(issues, votes_by_provider)
    
    log_print(f"🗳️ [AI Editor L2] Consensus: {consensus['decision']} "
              f"(FIX_NOW: {consensus['fix_now_count']}, MONITOR: {consensus['monitor_count']}, "
              f"AI responses: {len(votes_by_provider)}/{len(providers_to_ask)})")
    
    return consensus


def _get_consensus_providers():
    """Get list of available AI providers for consensus voting."""
    providers = []
    
    # Check which providers are configured
    if getattr(config, "GEMINI_API_KEY", ""):
        providers.append("GEMINI")
    if getattr(config, "OPENAI_API_KEY", ""):
        providers.append("CHATGPT")
    if getattr(config, "ANTHROPIC_API_KEY", ""):
        providers.append("CLAUDE")
    
    # Ollama (local, always try)
    ollama_host = getattr(config, "OLLAMA_HOST", "http://localhost:11434")
    if ollama_host:
        try:
            resp = requests.get(f"{ollama_host}/api/tags", timeout=2)
            if resp.status_code == 200:
                providers.append("OLLAMA")
        except:
            pass
    
    return providers


def _call_single_provider(provider, prompt, temperature=0.3):
    """Call a single AI provider and return raw text response."""
    try:
        return ai_engine._call_provider(provider, prompt, temperature)
    except Exception as e:
        log_print(f"   ❌ Provider {provider} failed: {e}")
        return None


def _tally_votes(issues, votes_by_provider):
    """Tally votes from multiple AIs and determine consensus."""
    issue_votes = {}
    
    for issue in issues:
        issue_type = issue["type"]
        issue_votes[issue_type] = {"FIX_NOW": 0, "MONITOR": 0, "IGNORE": 0, "details": []}
    
    for provider, ai_response in votes_by_provider.items():
        for vote in ai_response.get("votes", []):
            issue_type = vote.get("issue", "")
            vote_action = vote.get("vote", "MONITOR").upper()
            
            # Match issue type (fuzzy)
            matched_type = _match_issue_type(issue_type, [i["type"] for i in issues])
            if matched_type and matched_type in issue_votes:
                if vote_action in ("FIX_NOW", "MONITOR", "IGNORE"):
                    issue_votes[matched_type][vote_action] += 1
                    issue_votes[matched_type]["details"].append({
                        "provider": provider,
                        "vote": vote_action,
                        "reason": vote.get("reason", ""),
                        "suggested_fix": vote.get("suggested_fix", "")
                    })
    
    # Determine which issues have consensus for FIX_NOW (≥2 votes)
    min_votes_for_fix = getattr(config, "AI_EDITOR_MIN_CONSENSUS", 2)
    fix_now_issues = []
    monitor_issues = []
    
    total_fix_now = 0
    total_monitor = 0
    
    for issue_type, tallies in issue_votes.items():
        total_fix_now += tallies["FIX_NOW"]
        total_monitor += tallies["MONITOR"]
        
        if tallies["FIX_NOW"] >= min_votes_for_fix:
            fix_now_issues.append({
                "type": issue_type,
                "votes": tallies,
                "original": next((i for i in issues if i["type"] == issue_type), {})
            })
        elif tallies["FIX_NOW"] > 0 or tallies["MONITOR"] > 0:
            monitor_issues.append({
                "type": issue_type,
                "votes": tallies,
                "original": next((i for i in issues if i["type"] == issue_type), {})
            })
    
    decision = "FIX_NOW" if fix_now_issues else ("MONITOR" if monitor_issues else "HEALTHY")
    
    return {
        "decision": decision,
        "fix_now_issues": fix_now_issues,
        "monitor_issues": monitor_issues,
        "fix_now_count": total_fix_now,
        "monitor_count": total_monitor,
        "all_votes": issue_votes,
        "providers_responded": list(votes_by_provider.keys()),
        "raw_responses": votes_by_provider,
        "timestamp": datetime.datetime.now().isoformat(),
    }


def _match_issue_type(ai_type, valid_types):
    """Fuzzy match AI's issue type string to our valid types."""
    if not ai_type:
        return None
    ai_upper = ai_type.upper().replace(" ", "_").replace("-", "_")
    
    # Exact match
    if ai_upper in valid_types:
        return ai_upper
    
    # Partial match
    for vt in valid_types:
        if vt in ai_upper or ai_upper in vt:
            return vt
    
    # First valid type as fallback (for single-issue cases)
    if len(valid_types) == 1:
        return valid_types[0]
    
    return None


# ============================================================
# L3: PROPOSAL GENERATOR
# ============================================================

def generate_proposal(consensus_result, health_report):
    """
    L3: Generate a code fix proposal based on AI consensus.
    
    Creates a proposal file with:
    - Problem description
    - AI votes and reasoning
    - Suggested code changes
    - Files to modify
    
    Returns:
        dict: Proposal metadata (saved to file)
    """
    fix_issues = consensus_result.get("fix_now_issues", [])
    if not fix_issues:
        log_print("📝 [AI Editor L3] No FIX_NOW issues. Skipping proposal.")
        return None
    
    log_print(f"📝 [AI Editor L3] Generating proposal for {len(fix_issues)} issues...")
    
    # Gather all suggested fixes from AI votes
    fix_suggestions = []
    for issue in fix_issues:
        for detail in issue.get("votes", {}).get("details", []):
            if detail.get("suggested_fix"):
                fix_suggestions.append({
                    "issue": issue["type"],
                    "provider": detail["provider"],
                    "fix": detail["suggested_fix"],
                    "reason": detail["reason"]
                })
    
    # Ask AI for a detailed code proposal
    issues_text = "\n".join([
        f"  - [{i['type']}] {i.get('original', {}).get('message', 'Unknown')}"
        for i in fix_issues
    ])
    suggestions_text = "\n".join([
        f"  - {s['provider']}: {s['fix']}"
        for s in fix_suggestions
    ])
    
    prompt = f"""ACT AS: Expert Python developer for a trading bot.
TASK: Generate a specific code fix proposal.

ISSUES TO FIX:
{issues_text}

AI SUGGESTIONS:
{suggestions_text}

BOT HEALTH:
- Status: {health_report.get('status')}
- Win Rate: {health_report.get('stats', {}).get('win_rate', '?')}%
- Errors: {health_report.get('stats', {}).get('errors', 0)}
- AI Failures: {health_report.get('stats', {}).get('ai_failures', 0)}

RULES:
1. Only suggest config.py value changes OR minimal logic fixes
2. Never change core trading execution flow
3. Be specific: exact variable names, exact old→new values
4. Prefer config changes over code changes
5. Each fix must be independently safe to apply

OUTPUT JSON:
{{
    "title": "Brief title for this proposal",
    "risk_level": "LOW|MEDIUM|HIGH",
    "changes": [
        {{
            "file": "config.py or market_engine.py etc",
            "type": "CONFIG_CHANGE|LOGIC_FIX|ADD_GUARD",
            "description": "What this change does",
            "old_value": "current value or code",
            "new_value": "proposed value or code",
            "variable": "variable name if config change"
        }}
    ],
    "expected_impact": "What improvement this should cause",
    "rollback_plan": "How to undo if it makes things worse"
}}
"""
    
    response = ai_engine.call_ai_raw_with_failover(prompt, task_name="CODE_REVIEW", temperature=0.2)
    
    if not response:
        log_print("❌ [AI Editor L3] Failed to generate proposal (no AI response)")
        return None
    
    parsed = ai_engine._extract_json_from_text(response)
    if not parsed or not isinstance(parsed, dict):
        log_print("❌ [AI Editor L3] Failed to parse proposal JSON")
        return None
    
    # Build proposal
    proposal = {
        "id": f"PROP-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}",
        "timestamp": datetime.datetime.now().isoformat(),
        "status": "PENDING",  # PENDING, APPROVED, REJECTED, APPLIED
        "health_status": health_report.get("status"),
        "issues": [i["type"] for i in fix_issues],
        "consensus": {
            "providers": consensus_result.get("providers_responded", []),
            "fix_now_count": consensus_result.get("fix_now_count", 0),
        },
        "proposal": parsed,
        "applied_at": None,
        "applied_by": None,
    }
    
    # Save proposal
    proposal_file = os.path.join(PROPOSALS_DIR, f"{proposal['id']}.json")
    try:
        with open(proposal_file, "w", encoding="utf-8") as f:
            json.dump(proposal, f, indent=2, ensure_ascii=False)
        log_print(f"📝 [AI Editor L3] Proposal saved: {proposal['id']}")
        log_print(f"   📄 Title: {parsed.get('title', 'Untitled')}")
        log_print(f"   ⚠️ Risk: {parsed.get('risk_level', '?')}")
        log_print(f"   📁 Changes: {len(parsed.get('changes', []))} files")
    except Exception as e:
        log_print(f"❌ [AI Editor L3] Failed to save proposal: {e}")
        return None
    
    # Send notification
    _notify_proposal(proposal)
    
    return proposal


# ============================================================
# NOTIFICATION
# ============================================================

def _notify_proposal(proposal):
    """Send notification about new proposal via Telegram (if configured)."""
    telegram_token = getattr(config, "AI_EDITOR_TELEGRAM_TOKEN", "") or os.getenv("TELEGRAM_BOT_TOKEN", "")
    telegram_chat_id = getattr(config, "AI_EDITOR_TELEGRAM_CHAT_ID", "") or os.getenv("TELEGRAM_CHAT_ID", "")
    
    if not telegram_token or not telegram_chat_id:
        log_print("   📢 [AI Editor] Telegram not configured. Proposal visible on Dashboard only.")
        return
    
    try:
        title = proposal.get("proposal", {}).get("title", "Untitled")
        risk = proposal.get("proposal", {}).get("risk_level", "?")
        changes = len(proposal.get("proposal", {}).get("changes", []))
        issues = ", ".join(proposal.get("issues", []))
        
        message = (
            f"🛠️ *AI Editor Proposal*\n"
            f"ID: `{proposal['id']}`\n"
            f"Status: {proposal['health_status']}\n"
            f"Title: {title}\n"
            f"Risk: {risk}\n"
            f"Changes: {changes} files\n"
            f"Issues: {issues}\n\n"
            f"👉 Review on Dashboard → AI Editor tab"
        )
        
        url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
        requests.post(url, json={
            "chat_id": telegram_chat_id,
            "text": message,
            "parse_mode": "Markdown"
        }, timeout=5)
        
        log_print(f"   📢 [AI Editor] Telegram notification sent!")
    except Exception as e:
        log_print(f"   ⚠️ [AI Editor] Telegram notify failed: {e}")


# ============================================================
# PROPOSAL MANAGEMENT (for Dashboard)
# ============================================================

def get_pending_proposals():
    """Get all pending proposals for dashboard display."""
    proposals = []
    if not os.path.exists(PROPOSALS_DIR):
        return proposals
    
    for filename in sorted(os.listdir(PROPOSALS_DIR), reverse=True):
        if filename.endswith(".json"):
            filepath = os.path.join(PROPOSALS_DIR, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    prop = json.load(f)
                proposals.append(prop)
            except:
                pass
    
    return proposals


def get_editor_status():
    """Get current editor status for dashboard."""
    if os.path.exists(EDITOR_STATUS_FILE):
        try:
            with open(EDITOR_STATUS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {"status": "NO_DATA", "timestamp": None}


def apply_proposal(proposal_id):
    """
    Apply a proposal's CONFIG changes only (SAFE mode).
    Logic changes are displayed but not auto-applied.
    
    Returns:
        dict: Result of apply attempt
    """
    proposal_file = os.path.join(PROPOSALS_DIR, f"{proposal_id}.json")
    if not os.path.exists(proposal_file):
        return {"success": False, "error": "Proposal not found"}
    
    try:
        with open(proposal_file, "r", encoding="utf-8") as f:
            proposal = json.load(f)
    except:
        return {"success": False, "error": "Failed to read proposal"}
    
    if proposal.get("status") != "PENDING":
        return {"success": False, "error": f"Proposal status is {proposal.get('status')}, not PENDING"}
    
    changes = proposal.get("proposal", {}).get("changes", [])
    applied = []
    skipped = []
    
    for change in changes:
        change_type = change.get("type", "")
        
        if change_type == "CONFIG_CHANGE":
            # SAFE: Config changes can be auto-applied
            result = _apply_config_change(change)
            if result["success"]:
                applied.append(change)
            else:
                skipped.append({"change": change, "reason": result["error"]})
        else:
            # SAFE mode: Logic changes are NOT auto-applied
            skipped.append({"change": change, "reason": "SAFE mode: logic changes require manual apply"})
    
    # Update proposal status
    proposal["status"] = "APPLIED" if applied else "REJECTED"
    proposal["applied_at"] = datetime.datetime.now().isoformat()
    proposal["applied_by"] = "DASHBOARD_USER"
    proposal["apply_result"] = {"applied": len(applied), "skipped": len(skipped), "details": skipped}
    
    with open(proposal_file, "w", encoding="utf-8") as f:
        json.dump(proposal, f, indent=2, ensure_ascii=False)
    
    log_print(f"📝 [AI Editor] Proposal {proposal_id}: Applied {len(applied)}, Skipped {len(skipped)}")
    
    return {"success": True, "applied": len(applied), "skipped": len(skipped), "details": skipped}


def reject_proposal(proposal_id):
    """Reject a proposal."""
    proposal_file = os.path.join(PROPOSALS_DIR, f"{proposal_id}.json")
    if not os.path.exists(proposal_file):
        return {"success": False, "error": "Proposal not found"}
    
    try:
        with open(proposal_file, "r", encoding="utf-8") as f:
            proposal = json.load(f)
        proposal["status"] = "REJECTED"
        proposal["applied_at"] = datetime.datetime.now().isoformat()
        proposal["applied_by"] = "DASHBOARD_USER"
        with open(proposal_file, "w", encoding="utf-8") as f:
            json.dump(proposal, f, indent=2, ensure_ascii=False)
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _apply_config_change(change):
    """Apply a single config.py value change with backup."""
    variable = change.get("variable", "")
    new_value = change.get("new_value", "")
    
    if not variable:
        return {"success": False, "error": "No variable specified"}
    
    config_path = os.path.join(ROOT, "config.py")
    
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            original_content = f.read()
        
        # Find the variable assignment
        pattern = rf"^({re.escape(variable)}\s*=\s*)(.+?)(\s*#.*)?$"
        match = re.search(pattern, original_content, re.MULTILINE)
        
        if not match:
            return {"success": False, "error": f"Variable {variable} not found in config.py"}
        
        old_line = match.group(0)
        
        # Build new line
        new_line = f"{match.group(1)}{new_value}  # AI Editor auto-changed ({datetime.datetime.now().strftime('%Y-%m-%d %H:%M')})"
        
        new_content = original_content.replace(old_line, new_line, 1)
        
        # Backup ORIGINAL content before any write
        backup_dir = os.path.join(EDITOR_LOG_DIR, "backups")
        os.makedirs(backup_dir, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = os.path.join(backup_dir, f"config.py.{ts}.bak")
        with open(backup_path, "w", encoding="utf-8") as f:
            f.write(original_content)
        
        # Write the modified config
        with open(config_path, "w", encoding="utf-8") as f:
            f.write(new_content)
        
        log_print(f"   ✅ [AI Editor] Config changed: {variable} = {new_value} (backup: {backup_path})")
        return {"success": True, "backup": backup_path}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ============================================================
# MAIN ORCHESTRATOR (called from bot.py)
# ============================================================

# Track last run time
_last_editor_run = 0


def run_editor_cycle(force=False):
    """
    Main entry point — Run one full AI Editor cycle.
    Called from bot.py main loop every hour.
    
    Flow: L1 Scan → Issues? → L2 Consensus → FIX_NOW? → L3 Proposal → Notify
    
    Returns:
        dict: Cycle result summary
    """
    global _last_editor_run
    
    # Check if enabled
    if not getattr(config, "ENABLE_AI_EDITOR", False):
        return {"status": "DISABLED"}
    
    # Check interval (default: 1 hour)
    interval = getattr(config, "AI_EDITOR_INTERVAL_MINUTES", 60) * 60
    if not force and (time.time() - _last_editor_run) < interval:
        return {"status": "COOLDOWN"}
    
    _last_editor_run = time.time()
    
    log_print("\n" + "=" * 50)
    log_print("🛠️ [AI Editor] Starting Health Check Cycle...")
    log_print("=" * 50)
    
    try:
        # L1: Health Scan
        health = scan_health(hours_back=1)
        
        if health["status"] == "HEALTHY" and not health["issues"]:
            log_print("✅ [AI Editor] Bot is healthy. No action needed.")
            return {"status": "HEALTHY", "issues": 0}
        
        # L2: AI Consensus (only if issues found)
        if health["issues"]:
            consensus = request_ai_consensus(health["issues"])
            
            if consensus.get("decision") == "FIX_NOW":
                # L3: Generate Proposal
                proposal = generate_proposal(consensus, health)
                
                log_print(f"🛠️ [AI Editor] Cycle Complete: Proposal generated → Check Dashboard")
                return {
                    "status": "PROPOSAL_CREATED",
                    "proposal_id": proposal["id"] if proposal else None,
                    "issues": len(health["issues"]),
                }
            else:
                log_print(f"🛠️ [AI Editor] Cycle Complete: Issues found but AI says MONITOR")
                return {
                    "status": "MONITORING",
                    "issues": len(health["issues"]),
                    "consensus": consensus.get("decision"),
                }
        
        return {"status": "CHECKED", "issues": 0}
        
    except Exception as e:
        log_print(f"❌ [AI Editor] Cycle Error: {e}")
        traceback.print_exc()
        return {"status": "ERROR", "error": str(e)}
