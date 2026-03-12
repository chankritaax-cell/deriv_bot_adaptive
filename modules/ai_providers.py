"""
🤖 AI Providers Module (v3.8.0)
Handles communication with various AI APIs (Gemini, ChatGPT, Claude, Ollama).
"""

import time
import json
import re
import requests
import config
from .utils import log_print

# Try importing Gemini
try:
    from google import genai
    from google.genai import types
    HAS_GEMINI = True
except ImportError:
    HAS_GEMINI = False
    genai = None

# ============================================================
# 1. SHARED STATE & HELPERS
# ============================================================

GEMINI_DISABLED_UNTIL = 0
_gemini_current_model_idx = 0
_gemini_last_request_ts = 0
_gemini_model_disabled_until = {}

CHATGPT_DISABLED_UNTIL = 0
_chatgpt_daily_calls = 0
_chatgpt_daily_reset_ts = 0

CLAUDE_DISABLED_UNTIL = 0

_ai_usage_stats = {}
_ai_usage_reset_ts = 0
_provider_cooldowns = {} # [v3.11.28] New: Track provider cooldowns (time.time() + duration)

def _is_on_cooldown(provider):
    """Check if provider is temporarily disabled due to errors/limits."""
    now = time.time()
    until = _provider_cooldowns.get(provider, 0)
    if now < until:
        rem = int((until - now) / 60)
        return True, rem
    return False, 0

def _set_cooldown(provider, minutes=15):
    """Disable provider for a specific duration."""
    log_print(f"⏳ [AI Providers] Setting {minutes}m cooldown for {provider}")
    _provider_cooldowns[provider] = time.time() + (minutes * 60)

def _track_ai_usage(provider, event="call"):
    """Track AI provider usage for cost monitoring."""
    global _ai_usage_stats, _ai_usage_reset_ts
    now = time.time()
    if now - _ai_usage_reset_ts > 86400:
        _ai_usage_stats = {}
        _ai_usage_reset_ts = now
    if provider not in _ai_usage_stats:
        _ai_usage_stats[provider] = {"calls": 0, "errors": 0, "first_call": now}
    _ai_usage_stats[provider]["calls" if event == "call" else "errors"] += 1

def get_ai_usage_stats():
    """Returns daily AI usage stats for dashboard."""
    return dict(_ai_usage_stats)

def _clean_json_raw(text):
    """Deep cleaning of raw string to fix common LLM JSON errors."""
    if not text: return ""
    # Fix trailing commas in objects/arrays: {"a":1,} -> {"a":1}
    text = re.sub(r',\s*([\}\]])', r'\1', text)
    # Fix unescaped newlines in strings (common in analysis fields)
    # This is tricky without a full parser, but we can fix simple cases
    return text

def _extract_json_from_text(text):
    """Robust JSON extraction from chatty AI responses."""
    if not text: return None
    
    # 0. Pre-clean (v3.11.3)
    text = text.strip()
    
    # 1. Try stripping markdown
    clean = text.replace("```json", "").replace("```", "").strip()
    try: return json.loads(clean)
    except: pass
    
    # 2. Find ALL JSON objects and try each (last valid wins — usually the final answer)
    try:
        # Standard balanced braces pattern (v3.11.3: recursive regex removed as Python 're' doesn't support it)
        # This handles objects with one or two levels of nesting (e.g., changes list of objects)
        matches = re.findall(r'(\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\})', text, re.DOTALL)
             
        for m in reversed(matches):
            try:
                # [v3.11.5] Try direct load first to avoid corrupting strings with cleanup
                return json.loads(m)
            except:
                try:
                    # Cleanup only on failure
                    m_cleaned = _clean_json_raw(m)
                    obj = json.loads(m_cleaned)
                    if isinstance(obj, dict) and len(obj) >= 2:
                        return obj
                except: continue
    except: pass
    
    # 3. Greedy Object (fallback)
    try:
        match = re.search(r"(\{.*\})", text, re.DOTALL)
        if match: 
            try:
                return json.loads(_clean_json_raw(match.group(1)))
            except: pass
    except: pass
    
    return None

def normalize_ai_result(raw_result, task_name="UNKNOWN"):
    default = {"asset": None, "strategy": None, "confidence": 0.0, "regime_trend": "UNKNOWN", "reason": "missing", "source": "UNKNOWN"}
    if not isinstance(raw_result, dict): return None
    normalized = default.copy()
    for k, v in raw_result.items():
        if v is not None: normalized[k] = v
    
    # Map aliases
    if "action" not in normalized and "decision" in normalized:
        normalized["action"] = normalized["decision"]
    if "action" not in normalized and "recommendation" in normalized:
        normalized["action"] = normalized["recommendation"]
        
    if normalized["asset"]:
        normalized["asset"] = normalized["asset"].upper().replace("/", "").replace(" ", "")
    if not normalized["regime_trend"]: normalized["regime_trend"] = "SIDEWAYS"
    return normalized

# ============================================================
# 2. GEMINI IMPLEMENTATION
# ============================================================

def _gemini_get_active_model():
    global _gemini_current_model_idx
    models = getattr(config, "GEMINI_FALLBACK_MODELS", [config.GEMINI_MODEL]) if hasattr(config, "GEMINI_FALLBACK_MODELS") else ["gemini-2.0-flash"]
    now = time.time()
    for i in range(len(models)):
        idx = (_gemini_current_model_idx + i) % len(models)
        model = models[idx]
        if now >= _gemini_model_disabled_until.get(model, 0):
            _gemini_current_model_idx = idx
            return model
    return None

def _gemini_smart_call(prompt, temperature=0.3, max_tokens=None):
    global GEMINI_DISABLED_UNTIL, _gemini_last_request_ts, _gemini_current_model_idx
    if not HAS_GEMINI:
        log_print("⚠️ Error: 'google-genai' library not found. Install via: pip install google-genai")
        return None
    if not getattr(config, "GEMINI_API_KEY", ""):
        log_print("⚠️ Error: GEMINI_API_KEY not found in config/env.")
        return None
        
    if time.time() < GEMINI_DISABLED_UNTIL:
        log_print(f"⏳ Gemini is on cooldown until {time.ctime(GEMINI_DISABLED_UNTIL)}")
        return None

    # Rate Limit
    min_interval = getattr(config, "GEMINI_MIN_REQUEST_INTERVAL", 2.0)
    elapsed = time.time() - _gemini_last_request_ts
    if elapsed < min_interval: time.sleep(min_interval - elapsed)

    models = getattr(config, "GEMINI_FALLBACK_MODELS", ["gemini-2.0-flash"])
    client = genai.Client(api_key=config.GEMINI_API_KEY)

    for _ in range(len(models)):
        model = _gemini_get_active_model()
        if not model:
            GEMINI_DISABLED_UNTIL = time.time() + 60
            return None
        
        try:
            _gemini_last_request_ts = time.time()
            response = client.models.generate_content(
                model=model, contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=temperature,
                    max_output_tokens=max_tokens,
                    response_mime_type="application/json"
                )
            )
            return response.text
        except Exception as e:
            err = str(e)
            if "429" in err or "quota" in err.lower():
                _gemini_model_disabled_until[model] = time.time() + 300
                _gemini_current_model_idx = (_gemini_current_model_idx + 1) % len(models)
                continue
            elif "404" in err:
                _gemini_model_disabled_until[model] = time.time() + 86400
                _gemini_current_model_idx = (_gemini_current_model_idx + 1) % len(models)
                continue
            else:
                log_print(f"⚠️ Gemini Error ({model}): {err}")
                return None
    
    GEMINI_DISABLED_UNTIL = time.time() + 60
    return None

# ============================================================
# 3. CHATGPT IMPLEMENTATION
# ============================================================

def _chatgpt_raw_call(prompt, temperature=0.3, max_tokens=None):
    """Raw ChatGPT call that returns text."""
    global CHATGPT_DISABLED_UNTIL, _chatgpt_daily_calls, _chatgpt_daily_reset_ts
    if not getattr(config, "OPENAI_API_KEY", ""):
        return None
    
    now = time.time()
    if now < CHATGPT_DISABLED_UNTIL:
        log_print(f"⏳ ChatGPT on cooldown until {time.ctime(CHATGPT_DISABLED_UNTIL)}")
        return None
    
    # Daily call limit
    if now - _chatgpt_daily_reset_ts > 86400:
        _chatgpt_daily_calls = 0
        _chatgpt_daily_reset_ts = now
    max_daily = getattr(config, "CHATGPT_MAX_CALLS_PER_DAY", 10)
    if _chatgpt_daily_calls >= max_daily:
        log_print(f"⏳ ChatGPT daily limit reached ({max_daily})")
        return None
    
    try:
        headers = {
            "Authorization": f"Bearer {config.OPENAI_API_KEY}",
            "Content-Type": "application/json"
        }
        data = {
            "model": getattr(config, "CHATGPT_MODEL", "gpt-4o"),
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens
        }
        base_url = getattr(config, "OPENAI_API_BASE", "https://api.openai.com/v1")
        timeout = getattr(config, "AI_PROVIDER_TIMEOUT_SECONDS", 20)
        resp = requests.post(f"{base_url}/chat/completions", headers=headers, json=data, timeout=timeout)
        
        if resp.status_code == 200:
            _chatgpt_daily_calls += 1
            _track_ai_usage("CHATGPT", "call")
            return resp.json()["choices"][0]["message"]["content"]
        elif resp.status_code == 429:
            CHATGPT_DISABLED_UNTIL = now + getattr(config, "CHATGPT_COOLDOWN_ON_ERROR", 1800)
            log_print(f"⚠️ ChatGPT Rate Limited. Cooldown {CHATGPT_DISABLED_UNTIL - now:.0f}s")
            _track_ai_usage("CHATGPT", "error")
            return None
        else:
            log_print(f"⚠️ ChatGPT Error: HTTP {resp.status_code}")
            _track_ai_usage("CHATGPT", "error")
            return None
    except Exception as e:
        log_print(f"⚠️ ChatGPT Exception: {e}")
        return None

# ============================================================
# 4. CLAUDE IMPLEMENTATION
# ============================================================

def _claude_raw_call(prompt, temperature=0.3, max_tokens=None):
    """Raw Claude call that returns text."""
    global CLAUDE_DISABLED_UNTIL
    if not getattr(config, "ANTHROPIC_API_KEY", ""):
        return None
    
    now = time.time()
    if now < CLAUDE_DISABLED_UNTIL:
        log_print(f"⏳ Claude on cooldown until {time.ctime(CLAUDE_DISABLED_UNTIL)}")
        return None
    
    try:
        headers = {
            "x-api-key": config.ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }
        data = {
            "model": getattr(config, "CLAUDE_MODEL", "claude-sonnet-4-5-20250929"),
            "max_tokens": max_tokens or 1024,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}]
        }
        timeout = getattr(config, "AI_PROVIDER_TIMEOUT_SECONDS", 20)
        resp = requests.post("https://api.anthropic.com/v1/messages", headers=headers, json=data, timeout=timeout)
        
        if resp.status_code == 200:
            _track_ai_usage("CLAUDE", "call")
            result = resp.json()
            # Claude returns content as array of blocks
            blocks = result.get("content", [])
            text_parts = [b["text"] for b in blocks if b.get("type") == "text"]
            return "\n".join(text_parts) if text_parts else None
        elif resp.status_code == 429:
            CLAUDE_DISABLED_UNTIL = now + 300
            log_print(f"⚠️ Claude Rate Limited. Cooldown 300s")
            _track_ai_usage("CLAUDE", "error")
            return None
        else:
            log_print(f"⚠️ Claude Error: HTTP {resp.status_code} {resp.text[:200]}")
            _track_ai_usage("CLAUDE", "error")
            return None
    except Exception as e:
        log_print(f"⚠️ Claude Exception: {e}")
        return None

# ============================================================
# 5. OLLAMA IMPLEMENTATION
# ============================================================

def _ollama_raw_call(prompt, temperature=0.3, max_tokens=None):
    """Raw Ollama (local LLM) call that returns text. FREE - no API cost."""
    host = getattr(config, "OLLAMA_HOST", "http://localhost:11434")
    model = getattr(config, "OLLAMA_MODEL", "qwen2.5:14b")
    if not host:
        return None
    
    try:
        data = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens
            }
        }
        # Use longer timeout for large prompts (e.g., AI Council)
        if len(prompt) > 2000:
            timeout = getattr(config, "OLLAMA_COUNCIL_TIMEOUT_SECONDS", 120)
        else:
            timeout = getattr(config, "OLLAMA_TIMEOUT_SECONDS", 60)
        resp = requests.post(f"{host}/api/generate", json=data, timeout=timeout)
        
        if resp.status_code == 200:
            _track_ai_usage("OLLAMA", "call")
            return resp.json().get("response", "")
        elif resp.status_code == 404:
            log_print(f"⚠️ Ollama Error (404): Model '{model}' not found. Run 'ollama pull {model}'")
            _track_ai_usage("OLLAMA", "error")
            return None
            log_print(f"⚠️ Ollama Error: HTTP {resp.status_code}")
            _track_ai_usage("OLLAMA", "error")
            return None
    except requests.exceptions.ConnectionError:
        log_print(f"⚠️ Ollama Connection Error: Is Ollama running at {host}?")
        return None
    except Exception as e:
        log_print(f"⚠️ Ollama Exception: {e}")
        return None

# ============================================================
# 6. ROUTING & FAILOVER
# ============================================================

_PROVIDER_CALL_MAP = {
    "GEMINI": _gemini_smart_call,
    "CHATGPT": _chatgpt_raw_call,
    "CLAUDE": _claude_raw_call,
    "OLLAMA": _ollama_raw_call,
}

def _get_provider_chain(task_name):
    """Get the ordered provider chain for a given task. Uses task routing if enabled, else legacy failover."""
    if getattr(config, "ENABLE_AI_TASK_ROUTING", False):
        routing = getattr(config, "AI_TASK_ROUTING", {})
        chain = routing.get(task_name, routing.get("GENERAL", ["GEMINI", "OLLAMA", "CHATGPT"]))
        return chain
    # Legacy failover
    return [
        getattr(config, "PRIMARY_AI_PROVIDER", "GEMINI"),
        getattr(config, "SECONDARY_AI_PROVIDER", "CHATGPT"),
        getattr(config, "TERTIARY_AI_PROVIDER", "OLLAMA"),
    ]

def _check_daily_limit(provider):
    """Check if provider has exceeded daily call limit."""
    limits = getattr(config, "AI_DAILY_LIMITS", {})
    max_calls = limits.get(provider, 9999)
    stats = _ai_usage_stats.get(provider, {})
    return stats.get("calls", 0) < max_calls

def _call_provider(provider, prompt, temperature=0.3, max_tokens=None):
    """Call a specific AI provider. Returns raw text or None."""
    call_fn = _PROVIDER_CALL_MAP.get(provider)
    if not call_fn:
        return None
    try:
        return call_fn(prompt, temperature, max_tokens)
    except Exception as e:
        log_print(f"⚠️ {provider} call failed: {e}")
        _track_ai_usage(provider, "error")
        return None

def call_ai_with_failover(prompt, task_name="GENERAL", temperature=0.3, max_tokens=None):
    """Smart AI call with task-based routing and multi-provider failover.
    
    Routes each task to the optimal AI model based on AI_TASK_ROUTING config.
    Falls through the chain until a provider returns valid JSON.
    """
    chain = _get_provider_chain(task_name)
    resp_text = None
    source = None
    
    for provider in chain:
        # 1. Check Daily Limit
        if not _check_daily_limit(provider):
            continue
            
        # 2. Check Cooldown [v3.11.28]
        on_cd, rem = _is_on_cooldown(provider)
        if on_cd:
            # Throttle log: don't print every time
            if time.time() % 30 < 1: # Only log every ~30 calls/seconds
                log_print(f"   ⏳ {provider} on COOLDOWN ({rem}m left)")
            continue
        
        log_print(f"🧠 [{task_name}] Trying {provider}...")
        resp_text = _call_provider(provider, prompt, temperature, max_tokens)
        
        if resp_text:
            source = provider
            break
        else:
            log_print(f"   ↳ {provider} failed/empty. Failover...")
            _set_cooldown(provider, 15) # Penalize failure with short cooldown
    
    if not resp_text:
        # Throttle total failure message
        if time.time() % 60 < 1:
            log_print(f"❌ [{task_name}] ALL PROVIDERS DOWN/COOLDOWN: {chain}")
        return None
    
    # Extract JSON from response
    try:
        data = _extract_json_from_text(resp_text)
        if not data: raise ValueError("JSON Extraction Failed")
        
        # Auto-Handle List Response (Pick Best)
        if isinstance(data, list):
            if not data: return None
            try:
                data.sort(key=lambda x: float(x.get("confidence", 0) if isinstance(x, dict) else 0), reverse=True)
                data = data[0]
            except: return None

        norm = normalize_ai_result(data, task_name)
        norm["source"] = source
        log_print(f"   ✅ [{task_name}] Response from {source}")
        return norm
    except Exception as e:
        log_print(f"⚠️ AI JSON Parse Error ({source}): {e}")
        if resp_text:
            log_print(f"   Raw Response: {resp_text[:300]}...")
        return None

def call_ai_raw_with_failover(prompt, task_name="GENERAL", temperature=0.3, max_tokens=None):
    """Like call_ai_with_failover but returns raw text (no JSON parsing).
    Useful for code review, summary, etc.
    """
    chain = _get_provider_chain(task_name)
    
    for provider in chain:
        if not _check_daily_limit(provider):
            continue
        
        log_print(f"🧠 [{task_name}] Trying {provider}...")
        resp_text = _call_provider(provider, prompt, temperature, max_tokens)
        
        if resp_text:
            log_print(f"   ✅ [{task_name}] Response from {provider}")
            return resp_text
    
    log_print(f"❌ [{task_name}] All providers failed: {chain}")
    return None
