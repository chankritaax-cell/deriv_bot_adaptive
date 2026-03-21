# CLAUDE.md — Deriv Bot v5 Dev Guide

> This file gives Claude Code full context about the project architecture, invariants, and conventions.
> Read this before making any changes to the codebase.

---

## Project Overview

**Deriv Bot v5** is an autonomous algorithmic trading bot for Deriv binary options (1-minute contracts).
It uses a multi-layer AI pipeline (Gemini → ChatGPT → Claude → Ollama fallback) combined with
deterministic technical analysis guards to decide CALL/PUT entries on Volatility Index assets.

- **Entry point:** `bot.py`
- **Current version:** `config.BOT_VERSION` (defined at top of `config.py`)
- **Runtime mode:** `STREAMING` (default) — candle-by-candle via WebSocket
- **Assets traded:** R_75, R_100, R_50, R_25, R_10, 1HZ50V, 1HZ100V, 1HZ75V, 1HZ25V, 1HZ10V

---

## Module Map

```
bot.py                      ← Main entry point. run_streaming_bot() / run_polling_bot()
config.py                   ← All constants. Read via getattr(config, "KEY", default) pattern
.env                        ← Secrets (API keys, tokens). Loaded by config.py at startup
asset_profiles.json         ← Per-asset RSI bounds, strategy, bounce_limit, ma_slope_min
contract_info.json          ← Deriv contract metadata (payout %, duration)

modules/
  ai_engine.py              ← Brain. analyze_and_decide() is the main async decision function
  ai_providers.py           ← LLM failover router (Gemini → ChatGPT → Claude → Ollama)
  ai_council.py             ← Autonomous self-repair system. Triggered on loss_streak >= 3
  ai_editor.py              ← File editor used by AI Council to write code/config changes
  smart_trader.py           ← Strategy selector + hard rule enforcement (L1.5 layer)
  technical_analysis.py     ← TechnicalConfirmation class (RSI, MACD, Stoch, ATR, etc.)
  market_engine.py          ← Market data fetching, candle assembly, asset blacklist
  trade_engine.py           ← Deriv API buy/sell execution + result polling
  asset_selector.py         ← Asset rotation scanner (picks best asset each cycle)
  stream_manager.py         ← WebSocket stream lifecycle management
  telegram_bridge.py        ← Telegram bot commands + trade/council notifications
  shadow_tracker.py         ← Virtual trading of blocked signals (logs/shadow_trades.csv)
  utils.py                  ← Shared helpers: log_print, dashboard_*, martingale state I/O

logs/
  dashboard/trade_state.json    ← Martingale step persistence (mg_step, amount, streak)
  dashboard/dashboard_state.json← Live bot state (balance, wins, losses, streaks)
  market/failed_assets.json     ← CUT AND RUN ban list { asset: expiry_timestamp }
  council/history.json          ← AI Council action log
  shadow_trades.csv             ← Virtual trade results for blocked signal analysis
```

---

## Decision Pipeline (analyze_and_decide)

Every closed candle flows through these gates in order. Any gate returning `None` skips the trade.

```
1. PRE-AI SKIP: Low Vol / High Vol / Whipsaw Guard (ATR-based)
2. PRE-AI SKIP: RSI Guard  (UPTREND→CALL RSI check, DOWNTREND→PUT RSI check, SIDEWAYS+RSI>55→quasi-UPTREND, SIDEWAYS+RSI<45→quasi-DOWNTREND, else skip)
3. PRE-AI SKIP: Stoch Guard [v5.6.9] (overbought UPTREND / oversold DOWNTREND → skip before API call)
4. LLM CALL: unified_ai_decision_engine() → Gemini 2.0 Flash (+ failover chain)
5. LOCAL VETO: calculate_local_risk_score() < 0.55 → override AI APPROVE to VETO
6. POST-AI BLOCK: RSI hard bounds (is_rsi_valid_for_signal)
7. POST-AI BLOCK: Stoch Strict (PUT K<20 / CALL K>80) — fallback/edge-case safety net
8. POST-AI BLOCK: Sniper Guard (confidence < required_conf based on mg_step)
9. SMART TRADER: strategy selection (PULLBACK_ENTRY / TREND_FOLLOWING)
10. HARD RULES: check_hard_rules() in technical_analysis.py (MACD cross, exhaustion, RSI, Stoch, ATR)
11. TRADE EXECUTION: trade_engine.place_trade()
```

---

## Critical Invariants — NEVER Break These

### 1. Sniper Guard math
```python
if confidence < required_conf:   # check is < not <=
```
`CONFIDENCE_MG_STEP_1 = 0.85` allows `conf=0.85` to pass because `0.85 < 0.85 = False`.
**Do not change to `<=` or raise to 0.86.**

### 2. AI Council trigger threshold
```python
if loss_streak >= 3:   # was 5, lowered to 3 in v5.7.1 (safe: anti-overfit prompt added in v5.7.0)
```
**Safe floor is >= 3.** The anti-overfit Post-Mortem prompt (v5.7.0) prevents RSI-narrowing suggestions regardless of Council frequency.
**Never lower below 3** — triggering on streak < 3 creates false-positive Council activations on normal variance.

### 3. asset_profiles.json R_75 RSI bounds
The `pullback_*` keys and `call_*/put_*` keys are SEPARATE and serve different code paths:
- `call_min/call_max` + `put_min/put_max` → used by `check_hard_rules()` and `is_rsi_valid_for_signal()`
- `pullback_call_lo/hi/min` + `pullback_put_lo/hi/max` → used only in PULLBACK_ENTRY strategy

**Never change pullback bounds when targeting trend-following RSI windows and vice versa.**

### 4. failed_assets.json format
```json
{ "R_75": 1741968000.0 }
```
Value is `time.time() + duration_secs` (Unix epoch expiry). Bot checks `time.time() < expiry`.
**Stale entries persist across restarts.** Use `/reset` Telegram command or clear manually.

### 5. trade_state.json atomic writes
All writes use `tmp file + os.replace()` pattern. Never use `open(..., 'w')` directly on state files.

### 6. Shadow Tracker — fire-and-forget only
```python
asyncio.create_task(shadow_tracker.track_virtual_trade(...))
```
**Never await** `track_virtual_trade()` in the main loop. It must not block the WebSocket stream.

### 7. Post-Loss Cooldown scope
`_loss_cooldowns = {}` is module-level in `bot.py` (not inside `run_streaming_bot`).
Session-scoped vars reset on asset rotation. The module-level dict survives rotation.

### 8. MACD Exhaustion Cooldown scope
`TechnicalConfirmation._exhaustion_cooldowns` is a class variable.
Cooldown is only set/checked when `asset != ""` (scanner + backtest callers pass empty string, immune by design).

---

## Key Config Variables

| Variable | Default | Purpose |
|---|---|---|
| `ACTIVE_ASSET` | R_75 | Current trading asset (overridden by asset rotation) |
| `MAX_MARTINGALE_STEPS` | 0 | 0 = MG disabled. Raise for recovery staking |
| `CONFIDENCE_BASE` | 0.75 | Min AI confidence at MG step 0 |
| `CONFIDENCE_MG_STEP_1` | 0.85 | Min AI confidence at MG step 1 (check is `<`, not `<=`) |
| `STOCH_PUT_STRICT` | 20 | PRE-AI + POST-AI stoch gate for PUT |
| `STOCH_CALL_STRICT` | 80 | PRE-AI + POST-AI stoch gate for CALL |
| `ENABLE_MACD_MOMENTUM_GUARD` | True | MACD exhaustion guard (28% decay threshold) |
| `COOLDOWN_ANY_TRADE_MINS` | 5 | Global candle cooldown after any trade |
| `COOLDOWN_LOSS_TRADE_MINS` | 10 | Global candle cooldown after a LOSS |
| `USE_AI_ANALYST` | True | Enable/disable LLM calls |
| `REGIME_STRATEGY_HIGH_VOL` | TREND_FOLLOWING | Tier 2 fallback strategy in HIGH_VOL regime (changed from PULLBACK_ENTRY in v5.7.2) |

All variables are read as `getattr(config, "KEY", default)` — safe even if absent from `.env`.

---

## Asset Profiles (asset_profiles.json)

Each profile key corresponds to an asset or asset+regime combo (`R_75`, `R_75_HIGH_VOL`, `DEFAULT`).

**R_75 current bounds (as of v5.7.2):**
```json
"strategy": "TREND_FOLLOWING",
"call_min": 55.0, "call_max": 68.0,
"put_min":  35.0, "put_max":  45.0,
"pullback_call_lo": 38.0, "pullback_call_hi": 55.0, "pullback_call_min": 28.0,
"pullback_put_lo":  45.0, "pullback_put_hi":  62.0, "pullback_put_max":  72.0
```
Strategy changed from PULLBACK_ENTRY → TREND_FOLLOWING. Bounds widened (was call 61–65, put 37–39.5).

**AI Council is FORBIDDEN from narrowing these bounds** (loss_streak gate + anti-overfit post-mortem prompt).
If AI Council writes to this file, check `logs/council/history.json` for the action.

---

## Martingale State

Stored in `logs/dashboard/trade_state.json`:
```json
{ "mg_step": 0, "amount": 1.0, "last_result": "LOSS" }
```

- `mg_step = 0` → base stake, no recovery
- `mg_step >= 1` → recovery mode (CUT AND RUN also active at step >= 1)
- Auto-repaired on corrupt/empty file via `save_martingale_state(0)` in `load_martingale_state()`

**Post-Loss Cooldown skips when `mg_step > 0`** — MG recovery trades must not be blocked.

---

## CUT AND RUN

Triggered on LOSS when `mg_step >= 1` (already in recovery). Bans asset for 1 hour.
```python
market_engine.blacklist_asset(asset)  # writes to logs/market/failed_assets.json
```
Step 0 losses do NOT trigger a ban ("normal variance, letting MG handle").

---

## LLM Prompt Architecture

### Trade Decision Prompt (`unified_ai_decision_engine`)
- Located in `ai_engine.py` around `prompt = f"""Role: Act as CIO...`
- Output JSON: `{"decision": "APPROVE"|"VETO", "confidence": float, "signal": "CALL"|"PUT"|"SKIP", "reason": "Thai"}`
- **Confidence SCORING MATRIX** (v5.7.2): 4-5 aligned → 0.90-0.95; 3 aligned + 1 neutral → 0.78-0.85; 2-3 + 1 conflict → 0.65-0.75; 1-2 + 2+ conflicts → 0.50-0.60. Deduct 0.05/conflict; cap 0.82 if conflicting_signals present.
- Temperature: 0.3 (deterministic)

### Post-Mortem Prompt (`analyze_trade_loss`)
- Located in `ai_engine.py` → `analyze_trade_loss()`
- Output JSON: `{"analysis": "Thai", "actionable": bool, "fix_suggestion": str}`
- **Anti-overfit rules** (v5.7.0): FORBIDDEN from suggesting RSI/Stoch/MACD threshold changes
- `actionable: true` only for macro trend violation or extreme-volatility asset pause
- Temperature: 0.7 (analytical)
- AI Council auto-fix only fires when `actionable=True AND loss_streak >= 3`

---

## Telegram Commands

| Command | Action |
|---|---|
| `/status` | Balance, WR, MG step, streaks, regime |
| `/reset` | Clears `failed_assets.json` + resets MG to step 0 (atomic writes) |
| `/pause` | Pauses bot trading loop |
| `/resume` | Resumes bot trading loop |
| `/sumlog` | Last 10,000 chars of log file |
| `/help` | Full command list with Thai descriptions |

---

## Versioning Convention

```python
# config.py
BOT_VERSION = "5.7.7"   # [v5.7.7] Definitive wait increased (120s) + Sync [v5.7.6] Pending Result Note
```

Increment: `5.6.x → 5.6.(x+1)` for fixes/features within a milestone.
Increment minor: `5.6.x → 5.7.0` for a significant architectural change.

**Always update both:**
1. `config.py` → `BOT_VERSION`
2. `docs/CHANGELOG.md` → new `## [vX.X.X] - YYYY-MM-DD` section at the top

---

## CHANGELOG Format

```markdown
## [v5.X.X] - YYYY-MM-DD
### 🔧 Short Title

- **[NEW/FIX/IMPROVE]** `file.py`: Description
  - _Root cause: ..._
  - _Files: ..._
```

---

## Common Tasks

### Add a new hard block rule
→ Edit `modules/technical_analysis.py` → `check_hard_rules()`
→ Return `(False, "Hard Block: ... 🛑")`
→ If per-asset cooldown needed, set `TechnicalConfirmation._exhaustion_cooldowns[f"{asset}_{signal}"]`

### Add a new PRE-AI skip
→ Edit `modules/ai_engine.py` → `analyze_and_decide()`, before line `await unified_ai_decision_engine(context)`
→ Use `_perf_metrics["pre_ai_skip_cycles"] += 1` and `return None`

### Adjust per-asset RSI windows
→ Edit `asset_profiles.json` — target `call_min/call_max/put_min/put_max` only
→ Never touch `pullback_*` keys unless changing the pullback strategy bounds specifically

### Clear asset bans
→ Telegram `/reset` command, OR manually set `logs/market/failed_assets.json` to `{}`

### Debug a no-trade session
Check in order:
1. `logs/market/failed_assets.json` — stale bans?
2. `logs/dashboard/trade_state.json` — mg_step stuck?
3. Bot log for `PRE-AI SKIP` flood — ATR too low/high? RSI out of window?
4. `_loss_cooldowns` — post-loss cooldown active? (3 min after each loss at step 0)
5. `config.CONFIDENCE_MG_STEP_1` — is it 0.85 exactly? (check is `<` not `<=`)

---

## Safety Rules

1. **Never run with `DERIV_ACCOUNT_TYPE=real`** — bot.py aborts at startup if detected
2. **Never commit `.env`** — contains live API keys and Deriv token
3. **Never `await` shadow_tracker** calls — fire-and-forget only (`asyncio.create_task`)
4. **Never lower AI Council trigger below loss_streak >= 3** — safe floor since v5.7.1 (anti-overfit prompt prevents RSI-narrowing)
5. **Never narrow RSI bounds based on a single session's losses** — curve-fitting
6. **Always use atomic writes for state files** — `tmp + os.replace()` pattern
7. **Always bump `BOT_VERSION` + `CHANGELOG.md`** when making functional changes
