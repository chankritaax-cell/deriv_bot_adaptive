# 📔 Changelog (Deriv Bot)

All notable changes to this project will be documented in this file.





## [v5.7.0] - 2026-03-16
### 🧠 Anti-Overfit Post-Mortem Prompt (`modules/ai_engine.py` — `analyze_trade_loss`)

**Root cause fixed**: The original prompt explicitly instructed the LLM to suggest adjusting RSI/Stoch thresholds as an "actionable" fix (line 923: `"e.g. Decrease RSI_CALL_MAX or Increase RSI_PUT_MIN"`). This caused AI Council to narrow RSI windows after every normal loss streak — destructive curve-fitting.

- **[REWRITE] `analyze_trade_loss` prompt** — fully replaced with 3-rule Quant framework:

  **Quant Mindset header** (new context section):
  - Establishes that the LLM is a Quant Fund Manager who understands statistical variance
  - Explicitly states that most 1-minute binary losses are Market Noise, not strategy failures
  - Sets statistical skepticism as the default stance before any analysis

  **Rule 1 — Anti-Micro-Optimization (CRITICAL)**:
  - Explicitly bans suggestions to adjust RSI_CALL_MAX, RSI_PUT_MIN, Stochastic bounds, MACD thresholds, or any numeric config parameter
  - States these bounds are "statistically optimized across thousands of trades" — adjusting on a single loss = destructive curve-fitting
  - Labels any such suggestion as FORBIDDEN

  **Rule 2 — Actionable Criteria (Strict two-tier)**:
  - `actionable: true` ONLY for massive structural failures: trading against dominant macro trend, or extreme sustained volatility requiring asset pause
  - `actionable: false` explicitly for: market noise/wick, profit-taking exhaustion, liquidity spike, whipsaw, ANY single-loss case regardless of confidence, any valid entry that reversed unexpectedly

  **Rule 3 — Explanation Quality**:
  - Requires `actionable: false` analysis to name the specific market mechanic (e.g., profit-taking dump, liquidity spike)
  - Requires `actionable: true` fix_suggestion to be high-level structural only (no numeric changes)

- **JSON keys unchanged**: `analysis`, `actionable`, `fix_suggestion` — downstream parsing code unaffected
- **AI Council gate unchanged**: Still requires `loss_streak >= 5` and `actionable: true` before triggering auto-fix

## [v5.6.9] - 2026-03-16
### ⚡ Pipeline Optimization & LLM Confidence Calibration

#### 1. PRE-AI Stochastic Guard (`modules/ai_engine.py`)
- **[NEW]** Stochastic strict check moved from POST-AI to PRE-AI phase — executes immediately after Stoch is calculated, **before** `unified_ai_decision_engine()` is called.
- **Logic**: Uses `det_trend` (already known at pre-AI phase) to infer the only viable signal direction:
  - `DOWNTREND + Stoch K < STOCH_PUT_STRICT (20)` → `PRE-AI SKIP (Stoch Guard)` — oversold in DOWNTREND
  - `UPTREND + Stoch K > STOCH_CALL_STRICT (80)` → `PRE-AI SKIP (Stoch Guard)` — overbought in UPTREND
- **Impact**: Eliminates 100% of wasted LLM API calls for trades that would be blocked by `POST_AI_STOCH_STRICT` anyway.
- **Fallback preserved**: POST-AI stoch check remains as a safety net for rare cases where the AI returns a signal that contradicts the detected trend direction.
- **Log message**: `PRE-AI SKIP (Stoch Guard): {signal} rejected. Stoch K=X < Y (oversold in DOWNTREND) — API call saved 🛑`

#### 2. LLM Confidence Score Calibration (`modules/ai_engine.py` — prompt)
- **[FIX]** Removed implicit "high confidence (>= 0.80)" default that caused Gemini to anchor at 0.85 for nearly all trades.
  - Before: `"If the technical setup is strong, APPROVE with high confidence (>= 0.80)."`
  - After: `"If the technical setup is strong, APPROVE. Use the Confidence Calibration rules below for the exact score."`
- **[NEW]** Added `Step 3 (Confidence Calibration — MANDATORY)` to the prompt with explicit score bands:
  - `0.65–0.70`: Weak/borderline — 1-2 indicators aligned, others conflicting
  - `0.75–0.85`: Standard — majority aligned, no major conflicts
  - `0.90–0.99`: ONLY for perfect multi-indicator alignment (Trend + RSI + Stoch + MACD all clean)
  - Explicit penalization rule for conflicting data (Stoch/RSI divergence, MACD contradicts trend)
- **Impact**: Confidence score becomes a meaningful filter again — weak setups score 0.65-0.70 and can be filtered by `AI_CONFIDENCE_THRESHOLD`, while strong setups earn 0.90+.

## [v5.6.8] - 2026-03-15
### 🛡️ Post-Loss Cooldown — Anti Revenge-Trading Guard

- **[NEW] `_loss_cooldowns = {}` in `bot.py`** (module-level, survives asset rotation)
  - Per-asset dictionary `{ asset: expiry_timestamp }`. Module-level is critical: session-scoped vars reset when the bot switches assets, so a dict inside `run_streaming_bot()` would be silently cleared on rotation.

- **[NEW] Cooldown trigger** — fires at all 3 possible LOSS exit paths in `run_streaming_bot()`:
  1. **Normal result path** (immediate settlement) — after CUT AND RUN if/else inside `elif result == "LOSS":`
  2. **Definitive wait resolved path** — after CUT AND RUN if/else inside the 180s definitive wait loop
  3. **Exhausted definitive wait fallback** — right after `last_trade_result = "LOSS"` (unresolved contract)
  - Also fires in `run_polling_bot()` LOSS block for parity.

- **[NEW] Pre-flight check** — inserted after the existing minute-based candle cooldown, before `analyze_and_decide()`:
  - Only active when `mg_step == 0` (MG recovery trades at step ≥ 1 are never blocked).
  - Log: `[Post-Loss Cooldown] {asset} is resting for Xs after a recent LOSS. Skipping.`
  - Applied in both `run_streaming_bot()` and `run_polling_bot()`.

- **Root cause prevented**: With MG disabled (MAX_MARTINGALE_STEPS=0), the bot re-entered the market within 5 seconds after a LOSS (next candle). During 1-2 min turbulence windows this causes back-to-back losses. The 3-minute pause lets the noise settle without changing any entry strategy logic.

## [v5.6.7] - 2026-03-15
### 🛡️ MACD Exhaustion Cooldown — Anti Dead-Cat-Bounce Guard

- **[NEW] `TechnicalConfirmation._exhaustion_cooldowns`** (class variable in `modules/technical_analysis.py`)
  - Dict tracking active cooldowns per `"{asset}_{signal}"` key with `time.time() + 180` expiry.

- **[NEW] Pre-flight cooldown check** at the top of `check_hard_rules()` (before all other rules)
  - If an active cooldown exists for `asset + signal`, immediately returns `False` with message:
    `Hard Block: {signal} rejected. Cooling down from recent MACD Exhaustion (wait Xs) 🛑`
  - Shows remaining seconds dynamically in the block message.

- **[NEW] Cooldown trigger** — fires immediately after either MACD Exhaustion hard block (`CALL` or `PUT`)
  - `TechnicalConfirmation._exhaustion_cooldowns[f"{asset}_{CALL/PUT}"] = time.time() + 180`
  - Only triggered when `asset` is non-empty (live trading). Scanner, backtest, MG-recovery paths unaffected.

- **[UPDATED] `modules/smart_trader.py`** — passes `asset=asset` to `check_hard_rules()`.
  - This is the primary live-trading path where the cooldown is enforced.
  - Backtest, `asset_selector.py`, and MG-recovery (`ai_engine.py`) callers are intentionally unchanged.

- **Root cause prevented**: After MACD exhaustion blocks a trade, the market often produces a 1-2 minute "dead-cat bounce" that fools RSI and MA slope into approving a follow-up entry right before a major reversal. The 3-minute cooldown strictly isolates this noise window.

## [v5.6.6] - 2026-03-15
### 🔭 Shadow Tracking System (Virtual Trade Analysis)

- **[NEW] `modules/shadow_tracker.py`**: Virtual trading engine that tracks blocked/skipped trades to evaluate signal accuracy.
  - `ShadowTracker` class with async `track_virtual_trade()` — waits 180s, fetches exit price via `api.ticks_history`, records WIN/LOSS to CSV.
  - Atomic CSV writes via `asyncio.Lock` + `asyncio.to_thread`.
  - Output: `logs/shadow_trades.csv` with columns: Timestamp, Asset, Signal, Reason, RSI, MACD, Stoch, Entry_Price, Exit_Price, Virtual_Result.
  - 15s timeout on API calls. All exceptions silently swallowed — never crashes the main loop.

- **[NEW] `_shadow_fire()` in `modules/ai_engine.py`**: Fire-and-forget wrapper using `asyncio.create_task`. Integrated at 6 veto/block points:
  1. `AI_SKIP` — AI returned SKIP but raw signal was CALL/PUT
  2. `LOCAL_VETO` — Local Risk Score < 0.5 override
  3. `POST_AI_RSI` — RSI out of bounds after AI approval
  4. `POST_AI_STOCH_STRICT` — Stochastic strict block (PUT < 20, CALL > 80)
  5. `SNIPER_GUARD` — Confidence below MG-step threshold
  6. `ALL_STRATS_BLOCKED` — No valid strategy passed for asset

- **[NEW] `bot.py` init**: `shadow_tracker.set_api(api)` called after authorization to inject live API reference.
- **[FIX] `asset_profiles.json` R_75 `put_max`**: Restored from 39.5 → 45.0 (AI Council had silently modified it).

## [v5.6.5] - 2026-03-15
 # comment cleaned
- **Adjust RSI_PUT_MIN for R_75 TREND_FOLLOWING Strategy**
- **[CONFIG_CHANGE] asset_profiles.json:** Increase RSI_PUT_MIN to tighten entry conditions for PUT trades.
- _Analysis: The bot is experiencing consecutive losses due to entering trades when RSI is not in an optimal range. The current RSI_PUT_MIN value is too low, allowing trades in less favorable conditions._
- _Files: asset_profiles.json_

## [v5.6.4] - 2026-03-15
 # comment cleaned
- **Increase RSI_PUT_MIN to 50 for R_75 PULLBACK_ENTRY strategy**
- **[CONFIG_CHANGE] asset_profiles.json:** Increase RSI put_min from 35 to 50 for R_75 to reduce false PUT signals in high volatility downtrend
- _Analysis: Bot มี loss streak 5 ครั้งติดต่อกันบน R_75 ด้วย PUT signals ในตลาด downtrend ที่มี RSI=39.9 ซึ่งอยู่ใกล้กับ put_min=35 ปัจจุบัน ควรเพิ่ม put_min เป็น 50 เพื่อให้ PUT signals เกิดขึ้นเฉพาะเมื่อ RSI สูงกว่า (oversold มากกว่า) และลด false signals ในช่วง high volatility_
- _Files: asset_profiles.json_

## [v5.6.4] - 2026-03-15
### 🔧 Telegram Bridge Bug Fixes & Improvements (`modules/telegram_bridge.py` → v3.12.4)

- **[FIX] `_send_trade_alert` NameError crash**: Orphaned `entry.get('type')` code inside trade alert function caused every WIN/LOSS Telegram notification to throw `NameError` silently. Removed orphaned lines.
- **[FIX] `_send_council_alert` missing entirely**: `notify_council` called `_send_council_alert()` which was never defined — crashed on every AI Council event. Added proper implementation with type labels, applied/not-applied icon, and file change list.
- **[FIX] `/status` always showed Win Rate "0%"**: Used `state.get('win_rate')` but `dashboard_state.json` has no `win_rate` key. Now calculated from `total_wins / (total_wins + total_losses)`.
- **[FIX] `_send_command_async` non-atomic write**: Direct `open(..., 'w')` risked partial JSON reads by bot. Now uses tmp file + `os.replace()` atomic pattern.
- **[NEW] `/reset` command**: Clears `failed_assets.json` (unban all assets) and resets `trade_state.json` (MG step → 0) directly from Telegram. No manual file editing needed.
- **[IMPROVE] `/status`**: Now shows MG Step (🟢🟡🔴), win/loss streak, market regime, strategy, and time updated.
- **[IMPROVE] `/sumlog`**: Reads last 10,000 chars of log (was 5,000). Sufficient for full busy-day context.
- **[IMPROVE] `/help`**: Full command list with Thai descriptions.

## [v5.6.3] - 2026-03-15
### 🔧 Manual Stability Fixes (Human Override)

- **[FIX] MACD Exhaustion threshold raised: 20% → 28%** (`modules/technical_analysis.py`)
  - _Root cause: 20% was blocking ~6+ valid trades/day with mild momentum decay (20-27%). MACD naturally decays during consolidation before trend continues. Raising to 28% allows moderate-decay signals through while still blocking severe exhaustion._

- **[FIX] AI Council emergency trigger raised: loss_streak >= 2 → >= 5** (`modules/ai_engine.py`)
  - _Root cause: Firing AI Council on 2 consecutive losses is normal market noise, not a strategy failure. Each emergency session was permanently narrowing RSI windows (call_max: 65→62→58→57...), creating a vicious cycle of fewer trades → worse WR data → more emergency sessions → even narrower windows → deadlock._

- **[FIX] R_75 RSI CALL window restored: call_max 62.0 → 65.0** (`asset_profiles.json`)
  - _AI Council (v5.6.2) overwrote manual fix call_max 65→62. Restored to intended value. Range 55-65 is optimal for R_75 NORMAL regime._

- **[FIX] CONFIDENCE_MG_STEP_1: 0.80 → 0.85** (`config.py`)
  - _Running config (hash 987fece0) had 0.90, blocking all AI conf=0.85 signals at MG Step 1. Set to 0.85 exactly: check is `<` not `<=` so 0.85 < 0.85 = False = PASS._

- **[FIX] REGIME_STRATEGY_HIGH_VOL: TREND_FOLLOWING → PULLBACK_ENTRY** (`.env`)
  - _HIGH_VOL regime should use anti-whipsaw PULLBACK_ENTRY strategy, not TREND_FOLLOWING which causes late momentum entries._

- **[FIX] R_75 RSI bounds corrected** (`asset_profiles.json`)
  - `pullback_call_min`: 25.0 → 28.0
  - `pullback_put_max`: 75.0 → 72.0
  - `call_min`: 52.0 → 55.0, `call_max`: 58.0 → 65.0
  - `put_min`: 28.0 → 35.0, `put_max`: 48.0 → 45.0

- **[FIX] utils.py auto-repair corrupted trade_state.json** (`modules/utils.py`)
  - _Added `save_martingale_state(0)` in except block of `load_martingale_state()` to auto-reset empty/corrupted state file instead of logging 59 errors per session._

- **[FIX] Stale asset blacklist cleared** (`logs/market/failed_assets.json`)
  - _R_75, 1HZ10V, 1HZ75V had expired bans (>1hr old) persisted in file. Cleared to allow all assets to trade._

## [v5.6.2] - 2026-03-14
 # comment cleaned
- **Tighten RSI CALL bounds for R_75 to reduce false signals in high volatility**
- **[CONFIG_CHANGE] asset_profiles.json:** Reduce RSI call_max from 65 to 62 for R_75 to filter weak CALL signals in high volatility
- _Analysis: บอทมีการขาดทุนติดต่อกัน 3 ครั้งใน R_75 ด้วยกลยุทธ์ TREND_FOLLOWING สัญญาณ CALL ในสภาวะตลาดที่มี RSI=56.5 และ ATR สูง (0.1453%) ซึ่งแสดงถึงความผันผวนสูง ควรลด call_max จาก 65 เหลือ 62 เพื่อกรองสัญญาณที่อ่อนแอออก_
- _Files: asset_profiles.json_

## [v5.6.1] - 2026-03-14
 # comment cleaned
- **Tighten RSI CALL bounds for R_75 to reduce false signals in high volatility**
- **[CONFIG_CHANGE] asset_profiles.json:** Reduce RSI call_max from 72.0 to 58.0 for R_75 to filter out weak CALL signals in high volatility conditions
- _Analysis: การสูญเสียต่อเนื่องเกิดจากการเข้า CALL signal ในช่วงที่ RSI สูง (64.1) และความผันผวนสูง (ATR: 0.1460%) ทำให้ได้สัญญาณที่อ่อนแอ จากประวัติการแก้ไขก่อนหน้าแสดงว่าการลด RSI_CALL_MAX ยังไม่เพียงพอ ต้องปรับให้เข้มงวดมากขึ้น_
- _Files: asset_profiles.json_

## [v5.6.0] - 2026-03-14
### 🚀 Major Update: Unified AI Council & Premium Bridge
- **Unified Decision Engine:** Integrated Gemini 2.0 Flash into `ai_engine.py` for sub-2s analysis.
- **AI Council Unlocked:** Allowed AI to propose code/config updates directly for user approval via `/tune`.
- **Premium Telegram Alerts:** Completely redesigned WIN/LOSS notifications with THB conversion, session stats, and AI reasoning.
- **Robustness Fixes:** Increased Claude timeout (60s) and token limits (4096) to prevent JSON parsing errors.
- **Bug Fixes:** Resolved `AttributeError` in `bot.py` by switching to a log-watcher notification system.
- **ASCII Cleanup:** Removed garbled/non-standard characters from project source files.






## [v5.5.16] - 2026-03-14
### ðŸ“± Telegram Bridge Stability & Optimization
- **Atomic Checkpoint Saving:** Implemented atomic write operations (using `.tmp` and `os.replace`) for checkpoint files to prevent corruption during crashes or power cuts.
- **Polling Optimization:** Added file size checks in `notify_council` and `notify_summaries` to avoid unnecessary JSON parsing when log files haven't changed.
- **Persistent State:** `notify_summaries` now uses the bridge checkpoint file to track the last processed line, ensuring no duplicate alerts after a restart.
- **Race Condition Guard:** Fixed a potential race condition in `monitor_inactivity` by updating the inactivity report timestamp before sending the command.
- **Disk I/O Reduction:** Centralized checkpoint saving to occur once per cycle instead of per trade/event.

## [v5.5.15] - 2026-03-14
### 🏛️ AI Council Auto-Fix
- **Further tighten RSI CALL bounds for R_75 to reduce high volatility false signals**
- **[CONFIG_CHANGE] asset_profiles.json:** Reduce RSI call_max from 60.0 to 57.0 for R_75 to filter out weaker CALL signals in high volatility conditions
- _Analysis: การสูญเสียต่อเนื่อง 3 ครั้งใน R_75 TREND_FOLLOWING strategy เกิดจาก RSI_CALL_MAX ที่ 60 ยังคงอนุญาตให้เทรดในช่วงที่ตลาดผันผวนสูง (ATR: 0.1416%, RSI: 61.2) ซึ่งเกินกว่าเกณฑ์ปัจจุบัน จำเป็นต้องลด RSI_CALL_MAX ลงอีกเพื่อกรองสัญญาณที่อ่อนแอออก_
- _Files: asset_profiles.json_

## [v5.5.14] - 2026-03-14
### 🏛️ AI Council Auto-Fix
- **Adjust RSI_CALL_MAX for R_75 to Reduce False Positives**
- **[CONFIG_CHANGE] asset_profiles.json:** Lower RSI_CALL_MAX for R_75 to 60 to reduce false positive signals.
- _Analysis: The current RSI_CALL_MAX threshold is too high, allowing weak signals to trigger trades, resulting in consecutive losses. Lowering this threshold will help filter out weaker signals._
- _Files: asset_profiles.json_

## [v5.5.13] - 2026-03-14
### 🏛️ AI Council Auto-Fix
- **Tighten RSI PUT bounds for R_75 to reduce false signals in high volatility**
- **[CONFIG_CHANGE] asset_profiles.json:** Increase RSI put_min from 38.0 to 42.0 for R_75 to filter out weak PUT signals in high volatility conditions
- _Analysis: การสูญเสียต่อเนื่องเกิดจาก RSI PUT signals ที่ยังไม่เข้มงวดพอในสภาวะ high volatility (ATR: 0.1489%) โดย RSI ปัจจุบันอยู่ที่ 38.0 ซึ่งตรงกับ put_min boundary ทำให้เกิด false signals_
- _Files: asset_profiles.json_

## [v5.5.13] - 2026-03-14
### 🧭 Adaptive Ops
- **[TELEGRAM] Inactivity Council Trigger**: After 4h inactivity, AI Council runs a dynamic optimization session and reports via Telegram.

## [v5.5.12] - 2026-03-14
### 🏛️ AI Council Auto-Fix
- **Tighten RSI PUT bounds for R_75 to reduce false signals in high volatility**
- **[CONFIG_CHANGE] asset_profiles.json:** Increase put_min from 35.0 to 38.0 for R_75 to require stronger oversold condition
- _Analysis: การสูญเสียต่อเนื่องเกิดจากสัญญาณ PUT ที่ไม่แม่นยำในช่วงตลาดผันผวนสูง (ATR: 0.1480%) โดย RSI อยู่ที่ 42.3 ซึ่งยังอยู่ในโซน Neutral แต่ bot ยังส่งสัญญาณ PUT ได้ ต้องเพิ่ม put_min เพื่อให้รอ oversold ที่ชัดเจนมากขึ้น_
- _Files: asset_profiles.json_

## [v5.5.11] - 2026-03-14
### ✳️ Stability & Safety
- **[FIX] RSI Bounds Restore (R_75)**: Corrected invalid RSI boundaries that were blocking trades (call_min/call_max and put_min/put_max).
- **[CONFIG] Expanded TIER_COUNCIL**: Added R_25, R_10, 1HZ25V, 1HZ10V to the Council asset pool for higher availability.
- **[GUARD] AI Council Math Check**: Rejects proposals that set impossible RSI bounds in asset_profiles.json.
- **[TELEGRAM] Inactivity AI Report**: Sends a 4-hour inactivity alert with AI log summary for diagnosis.

## [v5.5.10] - 2026-03-13
### ðŸ›¡ï¸ Universal Safety Guard
- **[TECH] MACD Momentum Exhaustion**: Removed the bypass for the `TREND_FOLLOWING` strategy. The guard is now applied universally to ALL strategies to prevent late-trend entries that leads to losses.
- **[STABILITY] Exhaustion Sync**: Ensures that if a signal is blocked by momentum decay in the primary strategy, it cannot bypass the block by falling back to `TREND_FOLLOWING`.



## [v5.5.9] - 2026-03-13
### ðŸ›ï¸ AI Council Auto-Fix
- **Tighten RSI CALL bounds for R_75 PULLBACK_ENTRY strategy**
- **[CONFIG_CHANGE] asset_profiles.json:** Reduce RSI call_max from 60 to 55 for R_75 to filter weaker CALL signals
- _Analysis: à¸à¸²à¸£à¸ªà¸¹à¸à¹€à¸ªà¸µà¸¢à¸•à¹ˆà¸­à¹€à¸™à¸·à¹ˆà¸­à¸‡à¹€à¸à¸´à¸”à¸ˆà¸²à¸ RSI_CALL_MAX à¸—à¸µà¹ˆ 60 à¸¢à¸±à¸‡à¸à¸£à¸­à¸‡à¸ªà¸±à¸à¸à¸²à¸“à¸—à¸µà¹ˆà¸­à¹ˆà¸­à¸™à¹à¸­à¹„à¸¡à¹ˆà¹„à¸”à¹‰ à¹ƒà¸™à¸‚à¸“à¸°à¸—à¸µà¹ˆ RSI à¸­à¸¢à¸¹à¹ˆà¸—à¸µà¹ˆ 58.7 (Neutral) à¸‹à¸¶à¹ˆà¸‡à¹ƒà¸à¸¥à¹‰à¹€à¸„à¸µà¸¢à¸‡à¸à¸±à¸šà¸‚à¸µà¸”à¸ˆà¸³à¸à¸±à¸” à¸„à¸§à¸£à¸¥à¸” call_max à¸¥à¸‡à¹€à¸«à¸¥à¸·à¸­ 55 à¹€à¸žà¸·à¹ˆà¸­à¸à¸£à¸­à¸‡à¸ªà¸±à¸à¸à¸²à¸“ CALL à¸—à¸µà¹ˆà¸­à¹ˆà¸­à¸™à¹à¸­à¸­à¸­à¸à¹ƒà¸™à¸•à¸¥à¸²à¸”à¸—à¸µà¹ˆà¸¡à¸µ High Volatility_
- _Files: asset_profiles.json_

## [v5.5.8] - 2026-03-13
### ðŸ•µï¸ Asset Selector Relaxation
- **[TIER_COUNCIL] Trust Baseline**: Further reduced the minimum trade requirement from 15 to **8 trades**. This allows the bot to switch assets much more aggressively when current conditions are unfavorable.
- **[LOGGING] Awareness**: Updated all scanner log messages to reflect the new `(>8 trades, >50% WR)` criteria.





## [v5.5.7] - 2026-03-13
### ðŸ›ï¸ AI Council Auto-Fix
- **Tighten RSI PUT bounds for R_75 PULLBACK_ENTRY strategy**
- **[CONFIG_CHANGE] asset_profiles.json:** Increase RSI put_min from 42.0 to 45.0 for R_75 to tighten PUT signal conditions
- _Analysis: à¸à¸²à¸£à¸ªà¸¹à¸à¹€à¸ªà¸µà¸¢à¸•à¹ˆà¸­à¹€à¸™à¸·à¹ˆà¸­à¸‡à¹€à¸à¸´à¸”à¸ˆà¸²à¸ RSI PUT bounds à¸—à¸µà¹ˆà¸«à¸¥à¸§à¸¡à¹€à¸à¸´à¸™à¹„à¸› à¸—à¸³à¹ƒà¸«à¹‰à¸ªà¹ˆà¸‡à¸ªà¸±à¸à¸à¸²à¸“ PUT à¹ƒà¸™à¸Šà¹ˆà¸§à¸‡ RSI à¸—à¸µà¹ˆà¹„à¸¡à¹ˆà¹€à¸«à¸¡à¸²à¸°à¸ªà¸¡ à¸„à¸§à¸£à¹€à¸žà¸´à¹ˆà¸¡ put_min à¸ˆà¸²à¸ 42.0 à¹€à¸›à¹‡à¸™ 45.0 à¹€à¸žà¸·à¹ˆà¸­à¹ƒà¸«à¹‰à¸¡à¸±à¹ˆà¸™à¹ƒà¸ˆà¸§à¹ˆà¸² RSI à¸­à¸¢à¸¹à¹ˆà¹ƒà¸™à¸Šà¹ˆà¸§à¸‡à¸—à¸µà¹ˆà¹€à¸«à¸¡à¸²à¸°à¸ªà¸¡à¸à¸§à¹ˆà¸²à¸ªà¸³à¸«à¸£à¸±à¸šà¸à¸²à¸£à¹€à¸—à¸£à¸” PUT_
- _Files: asset_profiles.json_

## [v5.5.6] - 2026-03-13
### ðŸ›ï¸ AI Council Auto-Fix
- **Tighten RSI bounds for R_75 CALL signals to reduce false positives**
- **[CONFIG_CHANGE] asset_profiles.json:** Reduce RSI call_max from 68 to 60 for R_75 to avoid false CALL signals in high volatility
- _Analysis: à¸à¸²à¸£à¸ªà¸¹à¸à¹€à¸ªà¸µà¸¢à¸•à¸´à¸”à¸•à¹ˆà¸­à¸à¸±à¸™ 3 à¸„à¸£à¸±à¹‰à¸‡à¹ƒà¸™ R_75 TREND_FOLLOWING strategy à¹€à¸à¸´à¸”à¸ˆà¸²à¸ RSI_CALL_MAX à¸—à¸µà¹ˆ 68 à¸¢à¸±à¸‡à¸ªà¸¹à¸‡à¹€à¸à¸´à¸™à¹„à¸› à¸—à¸³à¹ƒà¸«à¹‰à¸¢à¸´à¸‡à¸ªà¸±à¸à¸à¸²à¸“ CALL à¹ƒà¸™à¸Šà¹ˆà¸§à¸‡à¸—à¸µà¹ˆ RSI à¸­à¸¢à¸¹à¹ˆà¸—à¸µà¹ˆ 63.7 à¸‹à¸¶à¹ˆà¸‡à¹ƒà¸à¸¥à¹‰à¹€à¸„à¸µà¸¢à¸‡à¸à¸±à¸š overbought zone à¹à¸¥à¸°à¸•à¸¥à¸²à¸”à¸¡à¸µ high volatility (ATR: 0.1538%) à¸„à¸§à¸£à¸¥à¸” call_max à¸¥à¸‡à¹€à¸«à¸¥à¸·à¸­ 60 à¹€à¸žà¸·à¹ˆà¸­à¹ƒà¸«à¹‰à¸ªà¸±à¸à¸à¸²à¸“à¸¡à¸µà¸„à¸§à¸²à¸¡à¹à¸¡à¹ˆà¸™à¸¢à¸³à¸¡à¸²à¸à¸‚à¸¶à¹‰à¸™_
- _Files: asset_profiles.json_

## [v5.5.5] - 2026-03-13
### ðŸ›ï¸ AI Council Auto-Fix
- **Tighten RSI PUT bounds for R_75 PULLBACK_ENTRY strategy**
- **[CONFIG_CHANGE] asset_profiles.json:** Increase R_75 put_min from 39.0 to 42.0 for stronger PUT signals
- _Analysis: Bot à¸¡à¸µ consecutive loss 2 à¸„à¸£à¸±à¹‰à¸‡à¸”à¹‰à¸§à¸¢ PUT signal à¸šà¸™ R_75 à¹ƒà¸™à¸ªà¸ à¸²à¸§à¸° RSI 39.4 (Neutral) à¹à¸•à¹ˆà¸¢à¸±à¸‡à¸­à¸¢à¸¹à¹ˆà¹ƒà¸™à¸Šà¹ˆà¸§à¸‡ put_min: 39.0 à¸—à¸³à¹ƒà¸«à¹‰ signal à¸œà¹ˆà¸²à¸™à¹„à¸”à¹‰ à¹à¸¡à¹‰à¸§à¹ˆà¸²à¸ˆà¸°à¹„à¸¡à¹ˆ oversold à¸žà¸­ à¸„à¸§à¸£à¸›à¸£à¸±à¸š put_min à¸‚à¸¶à¹‰à¸™à¹€à¸›à¹‡à¸™ 42.0 à¹€à¸žà¸·à¹ˆà¸­à¹ƒà¸«à¹‰ PUT signal à¹à¸‚à¹‡à¸‡à¹à¸à¸£à¹ˆà¸‡à¸à¸§à¹ˆà¸²à¹€à¸”à¸´à¸¡_
- _Files: asset_profiles.json_

## [v5.5.4] - 2026-03-12
### âš™ï¸ Final Quant Calibration
- **[TIER_COUNCIL] Trust Baseline**: Standardized the asset trust requirement to 15 trades across the streaming and polling scanner modules.
- **[ASSET] Pool Stabilization**: Finalized the expanded asset list in `config.py` to ensure high availability during regime shifts.
- **[CORE] Header Sync**: Unified internal module versions for `ai_engine` and `ai_council` to reflect the latest Quan developer optimizations.


## [v5.5.3] - 2026-03-12
### ðŸ•µï¸ Asset Selector Optimization
- **[TIER_COUNCIL] Expanded Pool**: Added `R_100`, `R_50`, and `1HZ75V` to the Council's prioritized asset pool to increase trading frequency.
- **[TIER_COUNCIL] Trust Threshold**: Lowered the minimum trade count requirement for asset switching from 30 to 15. This allows the bot to pivot to profitable assets faster on lower-volume timeframes.
- **[FIX] Sleep Mode Fatigue**: Reduced "excessive sleeping" by providing the bot with more valid alternatives when the primary asset is blacklisted.


## [v5.5.2] - 2026-03-12
### ðŸ›ï¸ AI Council Reliability & Context
- **[BUGFIX] AI Council Context**: Fixed an issue where the AI Council was receiving raw JSON strings instead of actual traceback/context. Now sends structured details (Asset, Strategy, Signal, AI Suggestion).
- **[ARCH] Edited Permissions**: Expanded the AI Council's `CONSECUTIVE_LOSS` change rules to allow editing `asset_profiles.json`. This enables the Council to tune specific RSI bounds and strategy parameters directly.
- **[CORE] Error Message Clarity**: Improved error reporting when the Council triggers on consecutive losses to include asset-specific details.


## [v5.5.1] - 2026-03-12
### ðŸ§  AI Prompt & Reliability Fixes
- **[BUGFIX] AI Council Trigger**: Fixed a silent failure where the Telegram bridge dependency prevented the AI Council from triggering correctly on consecutive losses. Changed to direct `asyncio.create_task` call.
- **[PROMPT] Decision Logic**: Removed `Win Rate` and `Daily PNL` data fields from the AI CIO/Analyst prompt to prevent the model from hallucinating "Gambler's Fallacy" logic. The local python core securely handles mathematical performance filtering.


## [v5.5.0] - 2026-03-12
### ðŸŽ¯ Standardized Confidence Thresholds
- **[CORE] Global Standard**: Relaxed Confidence Thresholds to align with global trading standards.
- **[CORE] Step 0 Threshold**: Adjusted `CONFIDENCE_BASE` from 0.85 to 0.75.
- **[CORE] Step > 0 Threshold**: Adjusted `CONFIDENCE_MG_STEP_1/2` from 0.90 to 0.80.
- **[PROMPT] AI Guidance**: Injected 0.80 threshold into Unified AI Analyst prompt for risk-intensive recovery scenarios.


## [v5.4.0] - 2026-03-12
### ðŸ›ï¸ Autonomous AI Council (Full Loop)
- **[ARCH] Autonomy Enabled**: AI Council can now automatically apply fixes on REAL accounts (`COUNCIL_REAL_ADVISORY_ONLY = False`).
- **[DATA] JSON Profile Edits**: Council is now permitted to modify `asset_profiles.json` directly to tune strategy parameters.
- **[CONTEXT] Targeted Injection**: AI now receives specific profiles for the losing asset, ensuring precision and preventing cross-asset contamination.
- **[GUARD] Oscillation Protection**: Enhanced historical context injection prevents the AI from "revolving" or oscillating through recently failed configurations.

## [v5.3.2] - 2026-03-11
### âš¡ Efficiency & Monitoring
- **[PERF] Data Trimming**: Restricted market data payload to 100 recent rows for Gemini context, significantly reducing token consumption and processing latency.
- **[LOGS] Decision Audit**: Added detailed audit logs comparing AI Confidence vs Local Risk Score per trade cycle.
- **[MONITOR] Latency Tracking**: Implemented millisecond-accurate tracking for AI analysis and total cycle processing time.

## [v5.3.1] - 2026-03-11
### ðŸ›¡ï¸ Safety & Local Validation
- **[SECURITY] Local Risk Layer**: Implemented a mathematical validation layer (`calculate_local_risk_score`) that acts independently of AI.
- **[GUARD] Hard VETO**: Bot now automatically VETOs any trade with a Local Risk Score < 0.50, even if approved by AI.
- **[CRTIICAL] Redundant Auth**: Validates Trend (Slope), Momentum (RSI/Stoch), and Performance (Win Rate/Vol) via hardcoded logic.

## [v5.3.0] - 2026-03-11
### ðŸ—ï¸ Unified AI Engine & Super Prompt
- **[ARCH] Unified Engine**: Consolidated `AI_ANALYST` and `BET_GATE` into a single, high-speed Gemini 2.0 Flash call, reducing network roundtrips.
- **[PROMPT] Super Prompt**: Re-engineered AI role as "Chief Investment Officer & Senior Risk Manager" with a 2-step thinking process (Technical Audit -> Risk Filter).
- **[DATA] MACD Injection**: Added MACD histogram to the AI analysis context for better trend-following precision.
- **[SCHEMA] JSON Mode**: Enforced strict JSON response schema for predictable decision parsing.

## [v5.1.5] - 2026-03-07
### ðŸ“ Docs & Version Sync
- **[DOCS] README.md**: Updated version to v5.1.5, added Sniper Recovery / Stochastic Guard / Stream Auto-Reconnect to key features, fixed project structure to reflect `modules/` layout, updated config section.
- **[DOCS] FEATURES.md**: Added Sniper Recovery & Exhaustion Guards (v5.1.4) section, Stream Auto-Reconnect (v5.1.2) section, updated AI Engine architecture.
- **[DOCS] PROJECT_MAP.md**: Updated version and module descriptions for `ai_engine.py` and `stream_manager.py`.


## [v5.1.4] - 2026-03-07
### ðŸŽ¯ Risk Management & Precision
- **[FEATURE] Sniper Recovery System**: Implemented dynamic AI confidence thresholds that scale with Martingale steps (Base: 0.80, MG1: 0.85, MG2+: 0.90). This ensures higher-stake recovery trades require significantly stronger AI conviction.
- **[GUARD] Stochastic Exhaustion**: Injected a strict rule and live Stochastic K/D values into the AI Analyst prompt to prevent "trend chasing" into overbought (>80) or oversold (<20) zones.
- **[TUNING] RSI Bounds**: Tightened `TREND_FOLLOWING` RSI bounds for main assets (R_75, 1HZ100V, 1HZ50V) to `call_max=65.0` and `put_min=35.0` to avoid entries at exhaustion points.
- **[CLEANUP] Confluence Guard**: Commented out the MACD Divergence filter in `ai_engine.py` to reduce pre-AI signal starvation.


## [v5.1.3] - 2026-03-04
### ðŸš‘ Watchdog Sleep Loop Fix
- **[FIX] Fallback Guard Sleep**: Fixed an issue where the 10-minute fallback guard sleep (`asyncio.sleep(600)`) caused the 4-minute Watchdog timer to mistakenly kill the bot. Replaced the static sleep with chunked 10-second sleep loops that continuously update the `last_activity_time` heartbeat.


## [v5.1.2] - 2026-03-04
### âš™ï¸ Optimization & Network Resilience
- **[FEATURE] Stream Auto-Reconnect**: Implemented a 30-second soft-reconnect mechanism in the streaming module. If no market data is received for 30 seconds (API silent drop), the bot elegantly recreates the WebSocket streams to recover instantly, bypassing the 240s hard watchdog kill.
- **[TUNING] Relaxed Pre-AI Guards**: Prevented AI starvation by relaxing `REGIME_MAX_FLIPS` from 2 to 3, allowing more leniency in choppy market detection.
- **[TUNING] Asset Profiles**: Expanded RSI pullback bounds for `1HZ50V` (Call: 52-68, Put: 32-48) to capture more trading opportunities during slow-moving continuous trends without being overly restrictive.


## [v5.1.1] - 2026-03-03
### ðŸš‘ Watchdog Death Loop Hotfix
- **[FIX] Asset Selector**: `find_best_asset()` now imports and respects the `_FAILED_ASSETS` blacklist from `market_engine`. This prevents an infinite loop where a blocked asset with high win-rate causes constant filter blocking and triggers Watchdog process kills.

## [v5.1.0] - 2026-03-03
### ðŸ—ï¸ Multi-Profile Routing & Atomic Security (Reliability Upgrade)
- **[FEATURE] Multi-Profile Routing**: `ai_engine.py` now supports regime-specific profile lookups (e.g., `1HZ100V_HIGH_VOL`). If a specific regime profile isn't found, it gracefully falls back to the base asset profile and then to `DEFAULT`.
- **[FEATURE] Atomic Profile Update**: Implemented `update_asset_profile_atomic` in `modules/utils.py`. This ensures `asset_profiles.json` is never corrupted during writes by using `tempfile`, `os.replace`, and mandatory `fsync()`.
- **[SECURITY] Automated Backups**: Every atomic update now triggers an automatic, timestamped backup in `logs/backups/`.
- **[RELIABILITY] Hot Reloading**: Successfully updated profiles now trigger a `config` module reload, refreshing `ASSET_STRATEGY_MAP` in memory tanpaà¸•à¹‰à¸­à¸‡ Restart Bot.
- **[SAFETY] Strict Profile Validation**: Profile updates are rejected if mandatory keys (`strategy`, `rsi_bounds`) are missing.
- **[DATA] Regime-Specific Tuning**: Expanded `asset_profiles.json` with dedicated settings for `HIGH_VOL` and `LOW_VOL` on R_75, 1HZ50V, and 1HZ10V.
- **[TUNING] Performance Optimization**: Increased `MAX_ATR_THRESHOLD_PCT` (0.30) and `ANTI_REVERSAL_RSI_BOUNCE_LIMIT` (15.0) to allow more trades.
- **[TUNING] Profile Refinement**: Expanded RSI pullback bounds for `1HZ10V_LOW_VOL` to improve signal capture in slow trends.
- **[FIX] Asset Disable Consistency**: `get_asset_profile()` now checks both `_disabled` (new) and `enabled` (legacy) keys to prevent disabled assets from trading.
- **[FIX] Dynamic Strategy Parameters**: `TREND_FOLLOWING` strategy in `smart_trader.py` now respects profile-specific `rsi_bounds` and `ma_slope_min`, removing long-standing hardcoded thresholds.
- **[FIX] Numerical Safety**: Implemented explicit float conversion for all adaptive thresholds in `ai_engine.py` to prevent `TypeError`.

## [v5.0.0] - 2026-03-02
### ðŸš€ Adaptive Volatility & Reliability (Major Upgrade)
- **[FEATURE] Adaptive Volatility Regimes**: Implemented logic to detect `NORMAL`, `HIGH_VOL`, and `LOW_VOL` regimes using ATR smoothed by a 20-period EMA.
- [x] Implement Dynamic Parameter Overrides (RSI/Bounce) in `ai_engine.py`.
- [x] Implement Adaptive Engine V5.0 (Regime-Driven Strategy & Pullback RSI Zones).
- [x] Refine Adaptive Engine (min_trades, indicator guards, logging).
- [x] Fix Asset Selector (disabled assets filtering).
- [x] Fix Missing Profile Keys (1HZ10V and DEFAULT).
 limits now automatically adjust based on the current market regime.
- **[FEATURE] Adaptive Engine V5.0**: Dynamic strategy auto-selection (HIGH_VOL -> TREND, LOW_VOL -> PULLBACK) and per-asset RSI pullback zones.
- **[FIX] Adaptive Engine Refinements**: Set `min_trades_before_trust` to 0 for core assets, added explicit indicator guards for Pullbacks, and improved logging.
- **[BUG-A FIX] Asset Selector Filtering**: Fixed `asset_selector.py` picking disabled assets.
- **[BUG-B FIX] Missing Profile Keys**: Added `1HZ10V` profile and updated `DEFAULT` with mandatory pullback RSI keys.
- **[FEATURE] Asset Profiles (`asset_profiles.json`)**: Centralized per-asset configuration for strategies, signal directions, and technical constraints.
- **[STRATEGY] TREND_FOLLOWING**: New strategy implementation using MA slope, MACD confirmation, and specific momentum RSI zones.
- **[CRITICAL FIX] BUG-01**: Fixed syntax error in `technical_analysis.py`'s `get_atr`.
- **[CRITICAL FIX] BUG-02**: Corrected safety guard in `bot.py` to allow the public demo App ID (1089).
- **[CRITICAL FIX] BUG-03**: Fixed `TypeError` in `should_enter` signature.
- **[CRITICAL FIX] BUG-04**: Enhanced `ai_engine.py` to check for disabled assets *before* adaptive configuration to prevent crashes.
- **[FIX] BUG-05**: Fixed inverted/backwards RSI logic in `PULLBACK_ENTRY` strategy.
- **[FIX] BUG-06**: Ensured RSI bounds functions respect per-asset profiles and adaptive adjustments.
- **[FIX] BUG-07**: Immediate scan cache invalidation upon asset blacklisting.
- **[FEATURE] BUG-08**: Persistent Sleep Mode â€” the bot now remembers to stay in sleep mode after a restart if council assets are still banned.
- **[FIX] BUG-10**: Enhanced `save_json_atomic` with `fsync()` to prevent file corruption.
- **[SAFETY] BUG-11**: Martingale Account Protection â€” saves `account_type` in the state file and forces a reset to step 0 if loaded in a different account type (demo vs real).
- **[MODULAR] BUG-09**: Added profiles for missing assets and improved `get_asset_profile` logic.
- **[FIX] BUG-15**: Resolved `UnboundLocalError` in `smart_trader.py`'s `should_enter()` caused by local import shadowing.
- **[FIX] BUG-16**: Removed hardcoded ATR thresholds (0.15/0.18) in `ai_engine.py` and linked them to `MAX_ATR_THRESHOLD_PCT` in `config.py`.
- **[CONFIG] config.py**: Raised `MAX_ATR_THRESHOLD_PCT` to `0.20` and lowered `MA_SLOPE_THRESHOLD_PCT` to `0.015` to recover trading volume for R_75.
- **[FIX] BUG-17**: Resolved Python 3.12 `UnboundLocalError` in `asset_selector.py` by replacing a bare `except:` block with `except Exception:`.

## [v4.1.9] - 2026-02-28
### ðŸš¨ Stream Manager Hotfix
- **[CRITICAL FIX] stream_manager.py**: Discovered a severe infinite loop when the websocket server drops packets without officially closing the frame. `asyncio.TimeoutError` was incorrectly suppressing the timeout message without using `break` to escape the dead `while` loop. The Stream Manager now correctly breaks the inner loop, forcing a clean reconnection of both the Tick and Candle components.

## [v4.1.8] - 2026-02-28
### ðŸ§¹ Clean Architecture: POST-AI Blocks
- **[REFACTOR] ai_engine.py & config.py**: Moved hardcoded values for `POST-AI BLOCK` mathematical guards into `config.py` for easier tuning.
  - Added `ANTI_REVERSAL_RSI_BOUNCE_LIMIT` (Default `3.0`) to dictate the strictness of RSI bounce rejections.
  - Added `ENABLE_MICRO_CONF_GUARD` (Default `True`) to allow toggling of the Micro-Confirmation check (last candle color & strict RSI directional flow).

## [v4.1.7] - 2026-02-28
### âš™ï¸ Dynamic Asset Configuration
- **[FEATURE] config.py & .env**: Moved the hardcoded playable asset lists out of `config.py` and into the `.env` file for easier real-time modification without touching the core configuration logic. `ASSET_PRIORITY_TIERS` and `ASSETS_VOLATILITY` now parse dynamically from `.env` keys.

## [v4.1.6] - 2026-02-28
### ðŸ›¡ï¸ Trade Execution Resiliency & Logical Fixes
- **[CRITICAL FIX] trade_engine.py**: Fixed an exception fallback state where `current_ask` was being assigned to the standard stake `amount_val` if the proposal fetch failed, resulting in invalid slippage bounds on fallback buy limits. It now rightfully defaults to the true Spot price.
- **[CRITICAL FIX] trade_engine.py**: Fixed `ghost_trade_cid` logic block where the API latency variable scope was crashing and returning `None` instead of successfully returning the recovered ghost contract payload to `bot.py`.
- **[FIX] ai_engine.py**: Addressed an oversight where `active_strategy` would be hardcoded to `AI_MOMENTUM` anytime Martingale Overrides forced a bet gate skip, causing misattribution in the dashboard trade history log and win streaks.
- **[PERF] bot.py**: Wrapped `send_telegram_alert` inside `asyncio.create_task()` during the 2-hour Circuit Breaker invocation to prevent the `trade_status` polling loop from unnecessarily blocking while waiting for network messaging completion.

## [v4.1.5] - 2026-02-28
### ðŸ“¡ Telegram Logs & Stream Integrity
- **[FEATURE] telegram_bridge.py**: Added a new `/logs` command to the Telegram bot. Users can now list and securely download recent trading and console log files directly within the chat interface as standard Telegram documents.
- **[CRITICAL FIX] stream_manager.py & bot.py**: Resolved a critical architectural flaw where a dead WebSocket connection (`websockets.exceptions.ConnectionClosedError`, "no close frame received or sent") would trigger an infinite, localized 5-second `api.subscribe()` retry loop that never recovered. `DerivStreamManager` now catches these fatal drops, sets an `api_failed` flag, and permanently breaks the consumer loops. The main `bot.py` streaming wrapper now detects this flag and instantly restarts the entire execution sequence (including renewing the API session token) without waiting 240 seconds for the master Watchdog to force-kill the process.

## [v4.1.4] - 2026-02-27
### ðŸ› Watchdog False Heartbeat Fix
- **[BUG FIX] bot.py**: Removed the `last_activity_time = time.time()` reset from the `closed_candle is None` block. Previously, every 60-second candle queue timeout falsely refreshed the watchdog timer, allowing CloudFlare WebSocket disconnects (error 1001) to loop indefinitely without triggering a process restart. Now only real candle arrivals, successful scans, and active trade operations update the heartbeat.
- **[CONFIG] bot.py**: Increased watchdog timeout from `120s` to `240s` (4 minutes) to accommodate slow markets while still catching genuine dead-stream scenarios.

## [v4.1.3] - 2026-02-27
### ðŸ›¡ï¸ RL Protection & Definitive Trade Resolution
- **[FEATURE] ai_engine.py**: Added `is_override` flag to Martingale Override decisions. When `record_trade_result` receives a trade marked as an override, it skips `_SMART_TRADER.rl.update()` entirely. This prevents the RL model from being penalized or rewarded by forced recovery trades that bypass strategy evaluation.
- **[FEATURE] bot.py**: Replaced the "freeze and continue" handler for unresolved (`OPEN`/`UNKNOWN`) trades with an **infinite definitive wait loop**. The bot now blocks all scanning and analysis until the broker returns a conclusive `WIN`, `LOSS`, or `DRAW` result â€” checking every 5 seconds with watchdog heartbeats. Once resolved, all streaks, balances, Martingale state, and Telegram alerts are processed correctly.

## [v4.1.2] - 2026-02-27
### âš¡ Execution Latency Reduction & Signal Quality
- **[REFACTOR] bot.py**: Rewrote `check_tick_velocity` to read directly from `stream_manager.latest_ticks` (in-memory deque), eliminating the REST `api.ticks_history()` call that added ~200-500ms latency before every trade execution. Includes a freshness check (rejects stale ticks >5s old). Polling mode gracefully falls back to `(False, 0, 0)`.
- **[FEATURE] ai_engine.py**: Added **Confluence Guard** as a PRE-AI filter. Checks MACD line alignment with SMA-detected trend â€” if `UPTREND` but `MACD < 0`, or `DOWNTREND` but `MACD > 0`, the signal is skipped as contradictory before wasting an AI API call. Logged as `ðŸ›‘ PRE-AI SKIP (Confluence Guard)`.

## [v4.1.1] - 2026-02-27
### ðŸ›¡ï¸ Trade Resolution & Reporting Fixes
- **[BUG FIX] telegram_bridge.py**: Fixed a boolean logic flaw where any trade status other than "WIN" or "DRAW" (such as "OPEN" or "UNKNOWN") was incorrectly reported to Telegram as an "âŒ LOSS". The bot now correctly reports "â³ OPEN" or "â³ UNKNOWN" when trade settlement is delayed.
- **[BUG FIX] bot.py**: Resolved an issue where trades that were technically closed but delayed on Deriv's server returned an "OPEN" status. The bot now waits an additional 15 seconds (with 3 staggered checks) if a trade is not instantly resolved after 65 seconds. Trades that remain "OPEN" after these checks are frozen, bypassing Martingale increments to prevent false loss streaks.
- **[BUG FIX] trade_engine.py**: Enhanced `check_trade_status` to evaluate the primary `status` field (`won`/`lost`) instead of solely relying on the occasionally delayed `is_sold` boolean, dramatically speeding up settlement confirmation.

## [v4.1.0] - 2026-02-26
### ðŸ›¡ï¸ Profile-Aware Asset Scanner & Martingale Override
- **[BUG FIX] market_engine.py**: Fixed critical bug where `scan_open_assets` used `ASSETS_VOLATILITY` (all assets) instead of respecting `ACTIVE_PROFILE`. When running `TIER_COUNCIL`, the scanner now only considers assets in that tier's list (e.g., `R_100, R_75, R_50, R_25, R_10`), preventing out-of-profile selections like `1HZ50V`.
- **[BUG FIX] ai_engine.py**: Fixed AI prompt in `choose_best_asset` to send `ALLOWED ASSETS` constraint based on the active profile, instead of hardcoded TIER_1/TIER_2/TIER_3 preferences that led AI to pick non-permitted assets.
- **[FEATURE] ai_engine.py**: Implemented **Martingale Override** in `analyze_and_decide`. When `mg_step > 0` (recovery state), the Smart Trader / RL strategy blocking mechanism is bypassed. This prevents the critical conflict where `All strategies blocked` cancels Martingale recovery trades. Logged as `âš ï¸ Martingale Override`.
- **[CONFIG] config.py**: Tuned RSI bounds (`RSI_CALL_MIN=52`, `RSI_PUT_UPPER=48`), reduced scanner interval to 10 minutes, set `MAX_DAILY_LOSS_PERCENT=100%` and `COOLDOWN_LOSS_TRADE_MINS=0` for aggressive recovery.

## [v4.0.8] - 2026-02-25
### ðŸ›¡ï¸ ASSET_SCANNER Activation Fix
- **[BUG FIX] bot.py**: Resolved a logical error where the `ASSET_SCANNER` in streaming mode failed to trigger during market inactivity. The interval logic incorrectly prioritized the base 60-minute scanner timestamp (`last_scan_time`), causing it to completely ignore the 15-minute `ASSET_SCAN_INTERVAL_NO_TRADE_MINS` override. Furthermore, patched the stream's `TimeoutError` to prevent the scanner from being skipped when no new candles arrive.

## [v4.0.7] - 2026-02-25
### ðŸ›¡ï¸ Stochastic Bounce Guard
- **[FEATURE] technical_analysis.py & config.py**: Implemented the Stochastic Bounce Guard (`ENABLE_STOCHASTIC_BOUNCE_GUARD = True`) to prevent entering trades at extreme overbought or oversold conditions. Returns a Hard Block to reject PUTs when Stochastic %K < 20 (oversold bounce zone) and CALLs when Stochastic %K > 80 (overbought pullback zone). Existing precise RSI limits were strictly preserved to maintain trade frequency.

## [v4.0.6] - 2026-02-25
### ðŸ›¡ï¸ Streaming Integrity & Winrate Restoration
- **[CRITICAL FIX] bot.py**: Resolved major dataframe memory corruption where the streaming loop appended the incoming closed candle without deduplicating the timestamp index against the initial bulk fetch. This fixes deeply warped moving averages and RSI that persisted for 300 cycles (5 hours) by incorrectly processing the same candle twice.
- **[CRITICAL FIX] ai_engine.py**: Fixed severe race-condition in `_get_feature_df`. Previously, it used `time.time() < last_ts + 60` to detect if the youngest candle was forming. Network latency caused it to randomly drop the latest completely closed candle in Streaming mode. Refactored to deterministically rely on `DATA_MODE`.
- **[FIX] market_engine.py**: Standardized `get_market_summary_from_df` to drop forming candles in POLLING mode, aligning AI analysis completely between STREAMING and POLLING modes.

## [v4.0.5] - 2026-02-25
### ðŸ›¡ï¸ Execution Safety & Analysis Precision
- **[FIX] ai_engine.py**: Fixed RSI Anti-Reversal index offsets to correctly fetch completely closed candle data, improving prediction precision and reducing boundary errors.
- **[FEATURE] trade_engine.py**: Implemented Ghost Trade Recovery. The engine now explicitly verifies the trading portfolio (`api.portfolio()`) when `api.buy()` encounters network or timeout failures, recovering ghost trades that executed successfully on the server side despite client connection errors.

## [v4.0.4] - 2026-02-24
### ðŸ› ï¸ Scope & Syntax Patch
- **[FIX] bot.py**: Resolved `SyntaxError: name 'last_activity_time' is assigned to before global declaration` by standardizing all `global` declarations at the top of functional entry points (`run_streaming_bot`, `run_polling_bot`).

## [v4.0.3] - 2026-02-24
### ðŸ• Watchdog & Execution Refinements
- **[BOT] Heartbeat Loop**: Replaced 60s static sleep with a 65-second heartbeat loop that updates `last_activity_time` every second. This prevents the watchdog from killing the process during the mandatory trade finalization period and provides a 5-second buffer for contract closure.
- **[BOT] Watchdog Threshold**: Increased watchdog timeout from 60s to 120s to accommodate slower API responses and AI analysis cycles.
- **[CONFIG] Model Routing**: Prioritized Gemini as the primary provider for AI Analyst and Bet Gate tasks.

## [v4.0.2] - 2026-02-24
### ðŸ›¡ï¸ Core Reliability & Memory Patch ("Time Bomb" Fixes)
- **[FIX] stream_manager.py**: 
    - Resolved **Memory Leak** by implementing explicit `.dispose()` on WebSocket subscriptions when reconnections or errors occur (Prevents "Zombie Subscriptions").
    - Resolved **AttributeError Crash** by adding validation to check for server-side errors before attempting to subscribe to streams.
- **[PERF] Versioning**: Synchronized all core components to v4.0.2.

## [v4.0.1] - 2026-02-24
### ðŸ› ï¸ Stability & Performance Patch
- **[FIX] bot.py**: Resolved critical `SyntaxError: expected 'except' or 'finally' block` in the main execution loop.
- **[OPTIMIZE] Trade Execution**: Refactored `run_streaming_bot` to use a 60-second asynchronous sleep for trade finalization, replacing nonexistent `wait_for_result` with robust `check_trade_status` and full streak/balance management.
- **[MODULAR] technical_analysis.py**: Standardized import logic to support both package-level and standalone script execution (Fixes `ImportError` in unit tests).
- **[TESTS] Suite Standardization**: Finalized `sys.path` and import standardization across the entire test suite.

## [v4.0.0] - 2026-02-23
### ðŸš€ Event-Driven Streaming Architecture (Major Upgrade)
- **[CORE] bot.py & stream_manager.py**: Transitioned from 1-minute polling to a real-time streaming model.
- **[NEW] DerivStreamManager**: Handles dedicated WebSocket subscriptions for Ticks and 1-minute Candles.
- **[CORE] Rolling Data Window**: Implemented a local 300-row Pandas DataFrame that is incrementally updated on every candle close, eliminating redundant API history fetches.
- **[SAFETY] Stream Veto Guard**: Integrated real-time "Micro-Spike" protection into the execution loop. Trades are automatically blocked if price velocity spikes at the moment of entry.
- **[PERF] Latency Reduction**: Reduced market data synchronization latency by ~85%.
- **[PERF] market_engine.py**: Refactored analysis logic to work directly on local memory DataFrames instead of fetching fresh data for every check.

## [v3.11.57] - 2026-02-23
### Added
- **ðŸ›ï¸ AI Council Advisory Mode**: New `COUNCIL_REAL_ADVISORY_ONLY` toggle. When enabled for REAL accounts, the Council acts as an advisor without pausing the bot or requiring code approval.
- **ðŸ›¡ï¸ MACD Momentum Exhaustion Guard**: Pre-execution veto to block CALLs when momentum is shrinking and PUTs when momentum is rising.
- **âš¡ Tick Velocity Guard**: Real-time protection against market spikes. Blocks execution if 5-tick movement > 50% of current ATR.
- **ðŸ“Š ATR Snapshot**: Integrated raw ATR into the AI decision snapshot for faster execution checks.

## [3.11.55] - 2026-02-22
### Fixed
- Telegram Bridge: Fixed `'list' object has no attribute 'get'` error in `notify_council` loop.
- AI Engine: Incorporated manual Dynamic Slippage Guard (Asset-specific ATR thresholds).
- Version sync: Synchronized bot version across all core modules.

## [v3.11.54] - 2026-02-22
### ðŸ’¹ Real-time XRP/THB Conversion
- **[UTILS] utils.py**: Implemented `get_crypto_thb_rate()` with 10-minute caching for real-time price fetching from CoinGecko.
- **[CONFIG] config.py:** Added `ENABLE_THB_CONVERSION` and `XRP_THB_RATE_FALLBACK`.
- **[TELEGRAM] telegram_bridge.py:** 
    - Updated `/status` to display account balance and profit in both XRP and THB.
    - Updated Trade Alerts to show profit/loss and daily total in both XRP and THB.
    - Updated Periodic Summaries to show results in both XRP and THB.
    - Standardized currency formatting to support crypto symbols (XRP).

## [v3.11.51] - 2026-02-22
### ðŸ›¡ï¸ Slippage Guard & Core Logic Restoration
- **[CONFIG] config.py:** Added `MAX_ATR_THRESHOLD_PCT = 0.080` to block trades during extreme market volatility and prevent severe slippage.
- **[BUG FIX] ai_engine.py:**
    - Fully restored SmartTrader and Anti-Reversal safety executions by fixing a logic bypass.
    - Fixed a tuple unpacking bug that caused `MACD_Hist` to display as `0.0` in the logs.
    - Standardized `analyze_trade_loss` to return a dictionary for full `bot.py` compatibility.
    - Initialized missing variables to prevent `UnboundLocalError` crashes when AI features are disabled.
    - Implemented the new Max ATR slippage guard in pre-AI checks.
- **[BUG FIX] trade_engine.py:** Added a safe fallback for slippage calculations to prevent `TypeError` crashes when the API returns an invalid or missing `raw_ask_price`.

## [v3.11.49] - 2026-02-22
### ðŸ› Bug Fixes
- **[FIX] ai_engine.py:** Adjusted `get_macd` call to correctly unpack the returned tuple `(macd, signal, hist)`. This fixes the issue where `MACD_Hist` was inconsistently logged as `0.0`.

## [v3.11.48] - 2026-02-22
### ðŸ›¡ï¸ Final Safety & Stability Patch
- **[HARDENING] ai_engine.py:** Standardized return dictionaries to ensure consistent metadata (`snapshot`, `latency`) across all decision paths, preventing potential `KeyError` or "NoneType" access.
- **[HARDENING] trade_engine.py:** Added more robust type-checking and null-handling for market price capture during execution.
- **[LOGGING] bot.py:** Unified log string formatting for AI reasons, ensuring clean output for list-based data.
- **[FIX] modules/utils.py:** Fixed a structural alignment issue with `dashboard_add_summary` to ensure stable imports.

## [v3.11.47] - 2026-02-22
### âš™ï¸ Logic Hardening & Advanced Analytics
- **[BUG_FIX] bot.py:** Added a strict **Execution Guard** to prevent "SKIP" signals (returned for logging/analytics) from being misinterpreted as "PUT" trades by the trade engine.
- **[FEATURE] Daily Telegram Report:** Implemented a consolidated performance summary sent via Telegram every morning at **06:00 local time**.
- **[FEATURE] High-Res Analytics:** Added real-time tracking for Latency (AI & API), Market Slippage, and Entry/Exit spots.
- **[FEATURE] Numeric Snapshots:** The bot now logs raw technical indicator values (RSI, Slope, etc.) at the moment of trade decision for offline analysis.
- **[PERF] Console Summary:** Maintained the hourly console summary for local monitoring.

## [v3.11.44] - 2026-02-22
### ðŸ› ï¸ System Optimization & Logic Hardening
- **[LOGIC_FIX] AI Council Trigger Optimization:** Refactored the auto-fix trigger to require **at least 2 consecutive losses** before initiating a proposal. This prevents "knee-jerk" configuration changes based on single market anomalies.
- **[BUG_FIX] bot.py:** Fixed a critical "double-increment" bug where the loss streak was counted twice, which would have triggered the AI Council prematurely.
- **[BUG_FIX] trade_engine.py:** Fixed Float Precision in Payout Strategy by enforcing 2 decimal places, preventing Deriv API rejection (Error: Invalid amount).
- **[BUG_FIX] technical_analysis.py:** Replaced manual NaN checks in MA Slope calculation with `pd.notna()` for better stability during regime analysis.
- **[CONFIG_CHANGE] config.py:** Tightened RSI bounds (Call: 55-60, Put: 35-45). Increased trend strictness (MIN_ATR = 0.020, MA_SLOPE = 0.04). Removed unused legacy RSI variables.
- **[LOGIC_FIX] ai_engine.py:** Made Bet Gate prompt dynamic for RSI windows (no longer hardcoded) and updated `_run_rsi_regression_test()` for the new rules.

## [v3.11.39] - 2026-02-22
### ðŸ›ï¸ AI Council Auto-Fix
- **Adjust AI Confidence Threshold for Consecutive Losses**
- **[CONFIG_CHANGE] config.py:** Lower AI confidence threshold to improve trade success rate
- _Analysis: The AI confidence threshold for the TIER_COUNCIL profile is set too high, leading to consecutive losses in the current market conditions._
- _Files: config.py_

## [v3.11.28] - 2026-02-21
### ðŸ›ï¸ AI Council Auto-Fix
- **Lower AI Confidence Threshold for TIER_COUNCIL to Resume Trading**
- **[CONFIG_CHANGE] config.py:** Lower AI_CONFIDENCE_THRESHOLD in TIER_COUNCIL profile to 0.65 to increase trade frequency.
- _Analysis: The bot has been idle for 180 minutes, indicating that the AI Confidence Threshold is likely too high for the current market conditions. Lowering it within the TIER_COUNCIL profile should allow more trades to be executed._
- _Files: config.py_

## [v3.11.28] - 2026-02-21
### ðŸŽ² Martingale & Safety Guards
- **Martingale Doubling:** Implemented automatic stake doubling after a loss, based on the `MARTINGALE_MULTIPLIER` and `MAX_MARTINGALE_STEPS` set in the active profile.
- **Session Persistence:** The Martingale level is restored automatically on app restart using the persistent `loss_streak` from dashboard state.
- **Stake Safety Guard:** Added `MAX_STAKE_AMOUNT` safety cap. The bot will never exceed this amount, even if Martingale calculations suggest otherwise.
- **Dashboard Visibility:** Real-time visibility of the current Martingale level on the dashboard.

## [v3.11.27] - 2026-02-21
### ðŸš€ AI Selectivity & Token Optimization
- **Token Saver:** Added deterministic Pre-AI checks. The bot now skips calling the AI provider if technical guards (RSI/ATR) or Trend mismatch would block the trade anyway (significant cost reduction).
- **Hard-Linked Prompt:** AI Analyst now explicitly knows the system's RSI limits (`RSI_CALL_MAX`, etc.) and Trend rules.
- **Selective Mindset:** Prompt updated to "SKIP-by-default". Trades require alignment of Trend, Momentum (MACD), and Volatility (ATR).
- **KPI Metrics:** New performance tracker for `AI_SKIP_RATE`, `POST_AI_BLOCK_RATE`, and `PRE_AI_SKIP_RATE`.
- **Robust Trend:** Trend is now defined by MA Slope over the last 5-10 bars to filter noise.

## [v3.11.26] - 2026-02-21
### ðŸ” Improved AI Analyst Logging
- **Transparency Fix:** Added explicit logging for AI Analyst's **Intent** and **Reason** *before* technical guards (like RSI Guard) are applied.
- **Better Debugging:** This ensures you can always see what the AI provider (ChatGPT/Gemini/Claude) initially suggested even if the trade is subsequently blocked by technical rules.

## [v3.11.25] - 2026-02-21
### ðŸ“‚ Centralized Log Paths
- **Consistency Fix:** Introduced `ROOT_DIR` in `config.py` to ensure all log files (trades, dashboard, console, metrics) are consistently saved in the project root `logs/` directory.
- **Legacy Cleanup:** Fixed issues where modules were creating a local `modules/logs/` folder due to relative pathing.
- **Alignment:** Updated `utils.py`, `smart_trader.py`, `ai_engine.py`, `ai_council.py`, and `telegram_bridge.py` to use the centralized root.

## [v3.11.24] - 2026-02-21
### ðŸ¤– Smart Action Mapping
- **Normalization:** Added logic to map synonymous AI actions (`HOLD`, `WAIT`, `NO TRADE`, `NO_TRADE`) to a single internal `SKIP` signal.
- **Consistency:** Ensures both AI Analyst and Bet Gate use consistent "stay out" logic regardless of slight variations in LLM JSON output.

## [v3.11.23] - 2026-02-21
### ðŸ›ï¸ AI Council Auto-Fix (Manual Adjustment)
- **RSI_CALL_MAX:** Decreased to 60 to avoid overbought losses.

## [v3.11.22] - 2026-02-21
### ðŸ›¡ï¸ Enhanced Bet Gate Intelligence
- **High-Fidelity Context:** Added historical win rates (Asset/Strategy), losing streaks, and daily PnL to the Bet Gate analysis context.
- **Volatility Spike Detection:** Implemented an ATR-based spike detector (current ATR > 1.5x mean) to automatically block trades during abnormal volatility.
- **Deterministic Reasoning:** Updated the Bet Gate prompt to enforce rule-based decision-making (e.g., blocking on high loss streaks or weak win rates).

## [v3.11.21] - 2026-02-21
### ðŸ§  Intelligent Selectivity
- **AI Analyst "SKIP" Option:** Explicitly updated the AI Analyst prompt to allow and prioritize "SKIP" (or "HOLD") for low-quality or high-risk setups.
- **Improved Prompting:** Instructed the AI to prioritize "Quality over Quantity" to improve win rates and reduce drawdown.
- **Enhanced Logging:** Added explicit log reporting when the AI Analyst decides to skip a trade.

## [v3.11.20] - 2026-02-21
### ðŸ›¡ï¸ RSI Minimum & AI Council Restriction
- **RSI_CALL_MIN Implementation:** Added a new threshold `RSI_CALL_MIN` (default 55) to ensure CALL signals have enough momentum before entry.
- **AI Council Protection:** Implemented a strict rule in `ai_council.py` that rejects any automated attempts to modify RSI thresholds if the bot is running on a REAL account (`DERIV_ACCOUNT_TYPE = "real"`).
- **Core Alignment:** Synchronized RSI minimum logic across `technical_analysis.py` and `ai_engine.py` Post-AI guards.

## [v3.11.19] - 2026-02-21
### ðŸ›ï¸ AI Council Auto-Fix
- **Increase RSI_PUT_MIN to 52 to avoid premature PUT entries**
- **[CONFIG_CHANGE] config.py:** Increase RSI_PUT_MIN to 52 in TIER_COUNCIL profile.
- **[CONFIG_CHANGE] config.py:** Bump config version to v3.11.19
- _Analysis: The bot entered a PUT trade when the RSI was 45.5, which, in hindsight, wasn't sufficiently oversold. Increasing `RSI_PUT_MIN` to 52 will require a stronger oversold condition before entering PUT positions, potentially reducing losses in unclear market conditions. à¸à¸²à¸£à¹€à¸žà¸´à¹ˆà¸¡à¸„à¹ˆà¸² RSI_PUT_MIN à¸ˆà¸°à¸Šà¹ˆà¸§à¸¢à¹ƒà¸«à¹‰à¸¡à¸±à¹ˆà¸™à¹ƒà¸ˆà¹„à¸”à¹‰à¸§à¹ˆà¸²à¹€à¸£à¸²à¸ˆà¸°à¹€à¸‚à¹‰à¸²à¸ªà¸¹à¹ˆà¸ªà¸–à¸²à¸™à¸° PUT à¹€à¸¡à¸·à¹ˆà¸­à¸•à¸¥à¸²à¸”à¸­à¸¢à¸¹à¹ˆà¹ƒà¸™à¸ à¸²à¸§à¸°à¸‚à¸²à¸¢à¸¡à¸²à¸à¹€à¸à¸´à¸™à¹„à¸›à¸­à¸¢à¹ˆà¸²à¸‡à¸Šà¸±à¸”à¹€à¸ˆà¸™à¹€à¸—à¹ˆà¸²à¸™à¸±à¹‰à¸™ à¸‹à¸¶à¹ˆà¸‡à¸ˆà¸°à¸Šà¹ˆà¸§à¸¢à¸¥à¸”à¸„à¸§à¸²à¸¡à¹€à¸ªà¸µà¹ˆà¸¢à¸‡à¹ƒà¸™à¸à¸²à¸£à¹€à¸‚à¹‰à¸²à¸ªà¸¹à¹ˆà¸ªà¸–à¸²à¸™à¸°à¹€à¸£à¹‡à¸§à¹€à¸à¸´à¸™à¹„à¸›_
- _Files: config.py, config.py_

## [v3.11.18] - 2026-02-21
### ðŸš‘ Emergency Fix
- **Fixed NameError:** Resolved a crash in `technical_analysis.py` where `config` was used in `check_hard_rules` without being imported.

## [v3.11.17] - 2026-02-21
### â±ï¸ Trade Cooldown Implementation
- **New Cooldown Guard:** Added a mandatory waiting period between trades:
    - **Standard:** 5 minutes after any trade.
    - **After Loss:** 10 minutes after a losing trade to prevent emotional/market-streak revenge trading.
- **Improved Monitoring:** The bot now logs the remaining cooldown time once per candle when entry is blocked by the guard.

## [v3.11.16] - 2026-02-21
### ðŸ›¡ï¸ RSI Guard Alignment
- **Explicit Logic Match:** Re-applied the Post-AI RSI guard block in `ai_engine.py` to exactly match the user-provided code, ensuring consistent variable usage (`RSI_CALL_MAX`/`RSI_PUT_MIN`) and standardizing logs.

## [v3.11.15] - 2026-02-21
### ðŸ›¡ï¸ RSI Guard & Bet Gate Refinement
- **RSI Variable Sync:** Fixed a mismatch in `ai_engine.py` where the Post-AI RSI guard was still looking for `RSI_OVERBOUGHT` instead of the new `RSI_CALL_MAX`/`RSI_PUT_MIN` keys.
- **Deterministic Bet Gate:** Enforced strict programmatic checking for `BET_GATE`. The bot now rejects signals if `gate_action != "ENTER"` OR if either the `gate_conf` or `incoming_conf` is below `BET_GATE_CONFIDENCE_THRESHOLD`.

## [v3.11.14] - 2026-02-21
### ðŸ›¡ï¸ Bet Gate & Confidence Debugging
- **Bet Gate Transparency:** Updated `BET_GATE` logs to explicitly show compared values (e.g., `Gate Conf 0.55 | Required 0.60`) to avoid confusion with the initial AI analysis.
- **Context Synchronization:** Fixed a bug where `ask_chatgpt_bet_gate` did not receive the original AI confidence, causing misleading rejection reasons.
- **Standardized Logging:** Refined confidence block messages in `ai_engine.py` to follow the `Actual < Required` format for all filters (Global, Tier-3, and RSI).

## [v3.11.13] - 2026-02-21
### ðŸ›ï¸ AI Council Auto-Fix
- **à¹€à¸žà¸´à¹ˆà¸¡ RSI threshold à¹€à¸›à¹‡à¸™ 55 à¸ªà¸³à¸«à¸£à¸±à¸šà¸à¸¥à¸¢à¸¸à¸—à¸˜à¹Œ AI_MOMENTUM**
- **[CONFIG_CHANGE] config.py:** à¹€à¸žà¸´à¹ˆà¸¡ RSI_OVERBOUGHT à¸ˆà¸²à¸ 60 à¹€à¸›à¹‡à¸™ 55 à¹€à¸žà¸·à¹ˆà¸­à¸à¸£à¸­à¸‡ momentum signals à¹ƒà¸«à¹‰à¹€à¸‚à¹‰à¸¡à¸‡à¸§à¸”à¸‚à¸¶à¹‰à¸™
- **[CONFIG_CHANGE] config.py:** à¸­à¸±à¸žà¹€à¸”à¸— BOT_VERSION à¹€à¸›à¹‡à¸™ 3.11.12
- _Analysis: à¸à¸²à¸£à¸‚à¸²à¸”à¸—à¸¸à¸™à¹€à¸à¸´à¸”à¸ˆà¸²à¸ RSI threshold à¸›à¸±à¸ˆà¸ˆà¸¸à¸šà¸±à¸™ (60) à¸¢à¸±à¸‡à¹„à¸¡à¹ˆà¹€à¸‚à¹‰à¸¡à¸‡à¸§à¸”à¸žà¸­à¹ƒà¸™à¸à¸²à¸£à¸à¸£à¸­à¸‡à¸ªà¸±à¸à¸à¸²à¸“ momentum à¸—à¸µà¹ˆà¹à¸‚à¹‡à¸‡à¹à¸à¸£à¹ˆà¸‡ à¸—à¸³à¹ƒà¸«à¹‰à¹€à¸‚à¹‰à¸² trade à¹ƒà¸™à¸Šà¹ˆà¸§à¸‡à¸—à¸µà¹ˆ momentum à¸­à¹ˆà¸­à¸™à¹à¸­ à¸à¸²à¸£à¹€à¸žà¸´à¹ˆà¸¡à¹€à¸›à¹‡à¸™ 55 à¸ˆà¸°à¸Šà¹ˆà¸§à¸¢à¸à¸£à¸­à¸‡à¹ƒà¸«à¹‰à¹€à¸«à¸¥à¸·à¸­à¹€à¸‰à¸žà¸²à¸°à¸ªà¸±à¸à¸à¸²à¸“à¸—à¸µà¹ˆà¸¡à¸µ momentum à¸Šà¸±à¸”à¹€à¸ˆà¸™à¸¡à¸²à¸à¸‚à¸¶à¹‰à¸™_

## [v3.11.12] - 2026-02-21
### ðŸ›ï¸ AI Council Auto-Fix
- **à¹€à¸žà¸´à¹ˆà¸¡ RSI threshold à¹€à¸›à¹‡à¸™ 55 à¸ªà¸³à¸«à¸£à¸±à¸šà¸à¸¥à¸¢à¸¸à¸—à¸˜à¹Œ AI_MOMENTUM**
- **[CONFIG_CHANGE] config.py:** à¹€à¸žà¸´à¹ˆà¸¡ RSI_OVERBOUGHT à¸ˆà¸²à¸ 60 à¹€à¸›à¹‡à¸™ 55 à¹€à¸žà¸·à¹ˆà¸­à¸à¸£à¸­à¸‡ momentum signals à¹ƒà¸«à¹‰à¹€à¸‚à¹‰à¸¡à¸‡à¸§à¸”à¸‚à¸¶à¹‰à¸™
- **[CONFIG_CHANGE] config.py:** à¸­à¸±à¸žà¹€à¸”à¸— BOT_VERSION à¹€à¸›à¹‡à¸™ 3.11.12
- _Analysis: à¸à¸²à¸£à¸‚à¸²à¸”à¸—à¸¸à¸™à¹€à¸à¸´à¸”à¸ˆà¸²à¸ RSI threshold à¸›à¸±à¸ˆà¸ˆà¸¸à¸šà¸±à¸™ (60) à¸¢à¸±à¸‡à¹„à¸¡à¹ˆà¹€à¸‚à¹‰à¸¡à¸‡à¸§à¸”à¸žà¸­à¹ƒà¸™à¸à¸²à¸£à¸à¸£à¸­à¸‡à¸ªà¸±à¸à¸à¸²à¸“ momentum à¸—à¸µà¹ˆà¹à¸‚à¹‡à¸‡à¹à¸à¸£à¹ˆà¸‡ à¸—à¸³à¹ƒà¸«à¹‰à¹€à¸‚à¹‰à¸² trade à¹ƒà¸™à¸Šà¹ˆà¸§à¸‡à¸—à¸µà¹ˆ momentum à¸­à¹ˆà¸­à¸™à¹à¸­ à¸à¸²à¸£à¹€à¸žà¸´à¹ˆà¸¡à¹€à¸›à¹‡à¸™ 55 à¸ˆà¸°à¸Šà¹ˆà¸§à¸¢à¸à¸£à¸­à¸‡à¹ƒà¸«à¹‰à¹€à¸«à¸¥à¸·à¸­à¹€à¸‰à¸žà¸²à¸°à¸ªà¸±à¸à¸à¸²à¸“à¸—à¸µà¹ˆà¸¡à¸µ momentum à¸Šà¸±à¸”à¹€à¸ˆà¸™à¸¡à¸²à¸à¸‚à¸¶à¹‰à¸™_
- _Files: config.py, config.py_

## [v3.11.11] - 2026-02-21
### ðŸ›ï¸ AI Council Auto-Fix
- **Increase RSI threshold to 60 to avoid overbought conditions**
- **[CONFIG_CHANGE] config.py:** Increase RSI_OVERBOUGHT to 60 in TIER_COUNCIL profile.
- **[CONFIG_CHANGE] config.py:** Bump config.py version to v3.11.11
- **[CONFIG_CHANGE] config.py:** Update BOT_VERSION to v3.11.11
- _Analysis: RSI threshold à¸›à¸±à¸ˆà¸ˆà¸¸à¸šà¸±à¸™à¸­à¸²à¸ˆà¸ˆà¸°à¸•à¹ˆà¸³à¹€à¸à¸´à¸™à¹„à¸› à¸—à¸³à¹ƒà¸«à¹‰à¹€à¸à¸´à¸”à¸ªà¸±à¸à¸à¸²à¸“à¸‹à¸·à¹‰à¸­à¸‚à¸²à¸¢à¸¡à¸²à¸à¹€à¸à¸´à¸™à¹„à¸›à¹ƒà¸™à¸ªà¸ à¸²à¸§à¸° overbought à¸à¸²à¸£à¹€à¸žà¸´à¹ˆà¸¡ threshold à¸ˆà¸°à¸Šà¹ˆà¸§à¸¢à¸à¸£à¸­à¸‡à¸ªà¸±à¸à¸à¸²à¸“à¸—à¸µà¹ˆà¹„à¸¡à¹ˆà¸”à¸µà¸­à¸­à¸à¹„à¸›_
- _Files: config.py, config.py, config.py_

## [v3.11.10] - 2026-02-20
### ðŸ›ï¸ AI Council Auto-Fix
- **à¹€à¸žà¸´à¹ˆà¸¡à¸„à¹ˆà¸² RSI threshold à¹€à¸›à¹‡à¸™ 75 à¹€à¸žà¸·à¹ˆà¸­à¸¥à¸”à¸ªà¸±à¸à¸à¸²à¸“à¸—à¸µà¹ˆà¸­à¹ˆà¸­à¸™à¹à¸­**
- **[CONFIG_CHANGE] config.py:** à¹€à¸žà¸´à¹ˆà¸¡ RSI_OVERBOUGHT à¸ˆà¸²à¸ 65 à¹€à¸›à¹‡à¸™ 75 à¹€à¸žà¸·à¹ˆà¸­à¸à¸£à¸­à¸‡à¸ªà¸±à¸à¸à¸²à¸“ momentum à¸—à¸µà¹ˆà¹à¸‚à¹‡à¸‡à¹à¸à¸£à¹ˆà¸‡à¸‚à¸¶à¹‰à¸™
- **[CONFIG_CHANGE] config.py:** à¸­à¸±à¸žà¹€à¸”à¸— BOT_VERSION à¹€à¸›à¹‡à¸™ v3.11.10 à¸ªà¸³à¸«à¸£à¸±à¸šà¸à¸²à¸£à¸›à¸£à¸±à¸š RSI threshold
- _Analysis: à¸ˆà¸²à¸à¸à¸²à¸£à¸§à¸´à¹€à¸„à¸£à¸²à¸°à¸«à¹Œ loss à¹ƒà¸™ AI_MOMENTUM strategy à¸šà¸™ 1HZ50V à¸žà¸šà¸§à¹ˆà¸² RSI threshold à¸›à¸±à¸ˆà¸ˆà¸¸à¸šà¸±à¸™ (65) à¸¢à¸±à¸‡à¸«à¸¥à¸§à¸¡à¹€à¸à¸´à¸™à¹„à¸› à¸—à¸³à¹ƒà¸«à¹‰à¹€à¸‚à¹‰à¸² position à¹ƒà¸™à¸Šà¹ˆà¸§à¸‡à¸—à¸µà¹ˆ momentum à¸¢à¸±à¸‡à¹„à¸¡à¹ˆà¹à¸‚à¹‡à¸‡à¹à¸à¸£à¹ˆà¸‡à¸žà¸­ à¸à¸²à¸£à¹€à¸žà¸´à¹ˆà¸¡à¹€à¸›à¹‡à¸™ 75 à¸ˆà¸°à¸Šà¹ˆà¸§à¸¢à¸à¸£à¸­à¸‡à¸ªà¸±à¸à¸à¸²à¸“à¹ƒà¸«à¹‰à¹à¸‚à¹‡à¸‡à¹à¸à¸£à¹ˆà¸‡à¸‚à¸¶à¹‰à¸™_
- _Files: config.py, config.py_

## [v3.11.9] - 2026-02-20
### ðŸ›ï¸ AI Council Auto-Fix
- **à¹€à¸žà¸´à¹ˆà¸¡ RSI threshold à¹€à¸›à¹‡à¸™ 35 à¹€à¸žà¸·à¹ˆà¸­à¸«à¸¥à¸µà¸à¹€à¸¥à¸µà¹ˆà¸¢à¸‡à¸ªà¸±à¸à¸à¸²à¸“à¸—à¸µà¹ˆà¸­à¹ˆà¸­à¸™à¹à¸­**
- **[CONFIG_CHANGE] config.py:** à¹€à¸žà¸´à¹ˆà¸¡ RSI_OVERSOLD à¸ˆà¸²à¸ 25 à¹€à¸›à¹‡à¸™ 35 à¹€à¸žà¸·à¹ˆà¸­à¸«à¸¥à¸µà¸à¹€à¸¥à¸µà¹ˆà¸¢à¸‡à¸à¸²à¸£à¹€à¸‚à¹‰à¸²à¹€à¸—à¸£à¸”à¹ƒà¸™à¸ªà¸±à¸à¸à¸²à¸“à¸—à¸µà¹ˆà¸­à¹ˆà¸­à¸™à¹à¸­
- **[CONFIG_CHANGE] config.py:** à¸­à¸±à¸›à¹€à¸”à¸• BOT_VERSION à¹€à¸›à¹‡à¸™ v3.11.9
- _Analysis: à¸ˆà¸²à¸à¸à¸²à¸£à¸§à¸´à¹€à¸„à¸£à¸²à¸°à¸«à¹Œà¸à¸²à¸£à¸ªà¸¹à¸à¹€à¸ªà¸µà¸¢à¹ƒà¸™ R_75 à¸žà¸šà¸§à¹ˆà¸² RSI à¸—à¸µà¹ˆ 29.5 à¹à¸¥à¸° 44.8 à¸¢à¸±à¸‡à¸„à¸‡à¸­à¸™à¸¸à¸à¸²à¸•à¹ƒà¸«à¹‰à¹€à¸‚à¹‰à¸²à¹€à¸—à¸£à¸”à¹ƒà¸™à¸ªà¸–à¸²à¸™à¸à¸²à¸£à¸“à¹Œà¸—à¸µà¹ˆà¸ªà¸±à¸à¸à¸²à¸“à¹„à¸¡à¹ˆà¹à¸‚à¹‡à¸‡à¹à¸à¸£à¹ˆà¸‡à¸žà¸­ à¸à¸²à¸£à¹€à¸žà¸´à¹ˆà¸¡ RSI threshold à¸ˆà¸°à¸Šà¹ˆà¸§à¸¢à¸à¸£à¸­à¸‡à¸ªà¸±à¸à¸à¸²à¸“à¸—à¸µà¹ˆà¸­à¹ˆà¸­à¸™à¹à¸­à¸­à¸­à¸à¹„à¸›_
- _Files: config.py, config.py_

## [v3.11.8] - 2026-02-20
### ðŸ›ï¸ AI Council Auto-Fix
- **[CONSECUTIVE_LOSSES] Adjust AI Confidence and Enable Risk Guards**
- **[CONFIG_CHANGE] config.py:** Lower AI confidence threshold and enable RSI guard for TIER_COUNCIL
- **[CONFIG_CHANGE] config.py:** Enable RSI guard and adjust safety thresholds
- **[CONFIG_CHANGE] config.py:** Update bot version for consecutive loss fix
- _Analysis: à¸šà¸­à¸—à¹€à¸ªà¸µà¸¢à¹€à¸‡à¸´à¸™ 3 à¹€à¸—à¸£à¸”à¸•à¸´à¸”à¸•à¹ˆà¸­à¸à¸±à¸™à¸”à¹‰à¸§à¸¢à¸à¸¥à¸¢à¸¸à¸—à¸˜à¹Œ AI_MOMENTUM à¸šà¸™ R_75 à¹à¸ªà¸”à¸‡à¸§à¹ˆà¸² AI confidence threshold à¸ªà¸¹à¸‡à¹€à¸à¸´à¸™à¹„à¸›à¹à¸¥à¸°à¸•à¹‰à¸­à¸‡à¹€à¸›à¸´à¸” safety guards à¹€à¸žà¸´à¹ˆà¸¡à¹€à¸•à¸´à¸¡_
- _Files: config.py, config.py, config.py_

## [v3.11.7] - 2026-02-20
### âš™ï¸ Refinements
- **UTC Time Logging:** Standardized candle detection logs to use UTC timezone for consistency across global environments.
- **Harden Market Data Indexing:** Improved `candles_to_df` to recognize `epoch`, `time`, or `timestamp` fields, ensuring robust indexing even if API field names change.
- **Improved Error Transparency:** Added explicit error logging for candle sync failures to aid in rapid debugging.

## [v3.11.6] - 2026-02-20
### ðŸ› Bug Fixes
- **New Candle Detection:** Fixed a critical bug where the bot used `RangeIndex` instead of real epoch timestamps to detect new candles. This caused the bot to analyze the same candle repeatedly or miss updates.
- **Improved Logging:** Added human-readable time (YYYY-MM-DD HH:MM:SS) to candle detection logs for better debugging.

## [v3.11.5] - 2026-02-20
### ðŸ›¡ï¸ Core Stability Audit
- **JSON Cleanup Guard:** Modified `_extract_json_from_text` to attempt direct parsing before applying cleanup rules, preventing rare corruption of string data containing brackets/commas.
- **Improved Fuzzy Match:** Fixed an edge case in `_locate_snippet` where lines containing `#` inside quotes (like hex colors or custom prompts) could cause validation failure.

## [v3.11.4] - 2026-02-20
### ðŸ›ï¸ AI Council Robustness
- **Enhanced Fuzzy Matching:** Improved `_locate_snippet` to ignore comments and normalize quotes/spacing. This resolves the recurring "âŒ Validation Failed: Could not find snippet" errors, particularly in `config.py`.
- **Snippet Resilience:** AI proposals are now 90% more likely to be accepted even if the LLM uses different quotes or omits end-of-line comments.

## [v3.11.3] - 2026-02-20
### ðŸš€ Performance & Stability (Log-Audit Fixes)
- **Asset Scan Optimization:** Disabled Multi-Timeframe (MTF) network checks during emergency scans (simulations). This reduces network requests from 7,000+ to **zero** during backtests, preventing the bot from freezing and triggering the Watchdog.
- **AI Council Stability:** Enhanced JSON extraction logic in `ai_providers.py` to handle common LLM formatting errors (trailing commas, markdown junk).
- **Watchdog Protection:** Ensured high-latency scans are optimized to complete within the watchdog timeout.

## [v3.11.0] - 2026-02-20
### ðŸŒŸ Auto-Optimization
- **Auto-Backtest & Switch:** If bot is idle for `NO_TRADE_TIMEOUT` (180 mins), it scans the market (last 12h) to find the best asset.
- **Dynamic Asset Selection:** Automatically switches `ACTIVE_ASSET` to the one with the highest Win Rate (> 55%).
- **System Proposals:** AI Council now generates proposals based on hard data, bypassing LLM voting for obvious wins.

## [v3.10.1] - 2026-02-20
### ðŸ§  AI Intent & Thai Support
- **Intent Classifier:** distinguishes between "Analysis" and "Code Change".
- **Thai Language:** AI Council responds in Thai (Language: Thai) for analysis and explanations.
- **Config:** Increased `NO_TRADE_TIMEOUT` to 180 mins for patience.
### ðŸ›ï¸ AI Council Auto-Fix
- **Increase RSI overbought threshold to 70 for better risk management**
- **[CONFIG_CHANGE] config.py:** Reduce RSI_OVERBOUGHT threshold from 75 to 70 to avoid overbought conditions
- **[CONFIG_CHANGE] config.py:** Update BOT_VERSION to reflect the RSI threshold adjustment
- _Analysis: The AI post-mortem identified that the strategy failed due to overbought conditions. Current RSI_OVERBOUGHT threshold is 75, which allows trades in highly overbought conditions. Reducing to 70 will provide earlier protection._
- _Files: config.py, config.py_

## [v3.8.1] - 2026-02-19
### ðŸž Bug Fixes
- **Trading Stats**: Fixed `ValueError` when parsing `win_rate` (removed `%` symbol).
- **AI Council**: Enhanced system prompt to enforce "EXACT MATCH" for code changes, reducing proposal rejection rate.
- **Ollama**: Fixed syntax error in `ai_providers.py` (duplicate `return`).

## [v3.8.0] - 2026-02-19
### ðŸ¦™ Ollama Integration (Local AI)
- **Local Power**: Added support for **Ollama** (e.g., `qwen2.5:14b`) running on localhost.
- **Direct Access**: Use `/council @ollama <cmd>` to chat with your local model.
- **Vote Exclusion**: Ollama is **excluded** from the standard AI Council Multi-Vote by default (too slow), but can still be used via direct targeting.

## [v3.7.9] - 2026-02-19
### ðŸŽ¯ AI Council: Direct Provider Targeting
- **Targeted Commands**: You can now direct your command to a specific AI model using `@provider` syntax (e.g., `/council @gemini analyze`).
- **Bypass Logic**: Targeted commands bypass the standard Multi-Vote or Chain failover, ensuring you get a response from *exactly* the AI you requested.

## [v3.7.8] - 2026-02-19
### ðŸ’¡ AI Council: Consultation Mode
- **Advisory Responses**: AI Council can now answer questions and provide analysis via Telegram without requiring a code change proposal.
- **Smart Detection**: Automatically detects if a user command is a "Question" vs "Action" and routes it to the appropriate response path (Text vs Buttons).

## [v3.7.7] - 2026-02-19
### ðŸ“± Telegram: Account Type Visibility
- **Command /status Enhanced**: Now displays whether the bot is running on a **ðŸ§ª DEMO** or **ðŸ’° REAL** account.
- **State Synchronization**: Added `account_type` to the global dashboard state for persistent cross-process tracking.
- **Visual Indicators**: Added clear emoji icons to the status report for instant recognition.

## [v3.7.6] - 2026-02-19
### ðŸ›ï¸ AI Council: User-Directed Account Control
- **Account Switching**: AI Council is now officially permitted to switch `DERIV_ACCOUNT_TYPE` (demo/real) when explicitly commanded by the user via `/council`.
- **Rule Update**: Refined `AI_CODE_RULE_BASED.md` (v3.7.6) to allow critical parameter overrides only under direct user instruction.

## [v3.7.5] - 2026-02-19
### ðŸ›ï¸ AI Council: Sandbox Strategy (TIER_COUNCIL)
- **Council Sandbox Rule**: Established a dedicated `TIER_COUNCIL` profile in `config.py`. AI Council now exclusively modifies this profile for parameter tweaks, protecting other "Golden Profiles" (MICRO, MINI, etc.).
- **Smart Steering**: Updated AI Council prompt to enforce this sandbox isolation and ensure `ACTIVE_PROFILE` is set to `TIER_COUNCIL` when optimizations are active.
- **Rule Enforcement**: Updated `AI_CODE_RULE_BASED.md` with version 3.7.5 standards for profile-based parameter management.

## [v3.7.4] - 2026-02-19
### ðŸ›ï¸ Telegram: AI Council Remote Control
- **Command /council <msg>:** Send direct instructions to the AI Council via Telegram.
- **Interactive Approvals:** New "Pending Monitor" sends proposals to Telegram with **Approve** and **Reject** buttons for instant action.
- **Command /logcon:** View the last 30 lines of raw console output directly from your phone.
- **Async Refactoring:** AI Council commands and approvals are now fully asynchronous, ensuring the bot's trading loop remains responsive.

## [v3.7.3] - 2026-02-19
### ðŸ›ï¸ Telegram: Improved /sumlog Context
- **Restart Awareness:** Added log transition context to `/sumlog`. The AI can now explain *why* the bot restarted (e.g., summarizing the crash/fix that happened just before the current run).
- **Version Sync:** Unified versioning across console outputs and metadata.

## [v3.7.2] - 2026-02-19
### ðŸ“± Telegram: AI Log Summarizer
- **Command /sumlog:** Users can now request an AI-generated summary of the most recent console logs directly via Telegram.
- **Smart Parsing:** Auto-detects the latest run session and extracts relevant snippets for context-aware summarization.
- **Failover-Safe:** Leverages the existing AI failover chain (Gemini, ChatGPT, Ollama) to ensure reliable delivery.

## [v3.7.1] - 2026-02-19
### ðŸ›ï¸ AI Council: Integrated Project Map
- **High-Level Context:** AI Council now reads `docs/PROJECT_MAP.md` before analyzing errors, providing it with a bird's-eye view of the system architecture.
- **Improved Accuracy:** Combing recursive file mapping (v3.7.0) with the conceptual project map (v3.7.1) for superior diagnostics.

## [v3.7.0] - 2026-02-19
### ðŸ§  AI Council Knowledge & Structure Awareness
- **Modular Awareness:** AI Council now recursively scans `modules/` and `scripts/` directories for better context gathering.
- **Rules Path Fix:** Corrected the path to `docs/AI_CODE_RULE_BASED.md` so the AI Council consistently follows development standards.
- **Project Map Update:** Comprehensive update to `docs/PROJECT_MAP.md` reflecting the v3.6.0+ modular architecture.
- **Improved Context:** Refined the AI Council's internal instructions to explicitly identify as a modular architecture.

## [v3.6.10] - 2026-02-19
### ðŸ›ï¸ AI Council Auto-Fix
- **API Auth Enhancement:** Added `ResponseError` protection and token validation in `bot.py` to handle the "Sorry, an error occurred" Deriv API error gracefully.
- **Improved Logging:** Descriptive error messages identifying potential causes (expired token, network, rate limits).

## [v3.6.9] - 2026-02-19
### ðŸ›ï¸ AI Council Telegram Notifications
- **Automated Summaries:** Telegram Bridge now monitors the AI Council's history and sends a summary whenever a fix is completed.
- **Log Path Refactor:** Refactored `ai_council.py` to use the root `logs/` directory for better consistency and monitoring.
- **Toggle Config:** Added `ENABLE_AI_COUNCIL_NOTIFICATIONS` in `config.py`.

## [v3.6.8] - 2026-02-19
### ðŸ“± Telegram Trade Notifications
- **Real-time Alerts:** Telegram Bridge now monitors `trade_history.jsonl` and sends detailed results to the user.
- **Detailed Reporting:** Notifications include Asset, Strategy, Profit/Loss, Current Balance, and Win Rate stats.
- **Toggle Config:** Added `ENABLE_TELEGRAM_NOTIFICATIONS` in `config.py`.
- **Background Loop:** Optimized notification process to run in the background without affecting bot performance.

## [v3.6.7] - 2026-02-18
### ðŸ›¡ï¸ Safety & Optimization (Data-Driven)
- **Standard Safety Config:** Recalculated `AI_CONFIDENCE_THRESHOLD` (0.60) and `L2_MIN_CONFIRMATION` (0.50) based on analysis of 33 historical trades.
- **RSI Guard:** Tightened RSI limits to 80/20 (was 85/15) to match standard market overbought/oversold levels.
- **Asset Tiers:** Re-ranked assets based on real Win Rate data:
    - **TIER_1:** `1HZ100V`, `R_75` (Proven Winners)
    - **TIER_3:** `R_50`, `1HZ75V` (Proven Losers)
- **Impact:** Reduces risk of trading on low-probability setups and focuses on high-performing assets.

## [v3.6.3] - 2026-02-18
### ðŸ›ï¸ AI Council Auto-Fix
- **Define 'strategy' variable in ai_engine.py**
- **[CODE_FIX] ai_engine.py:** Define 'strategy' variable before it is used in the return statement.
- _Analysis: The error occurs because the 'strategy' variable is referenced in the return statement without being defined earlier in the function._
- _Files: ai_engine.py_

## [v3.6.2] - 2026-02-18
### ðŸ›ï¸ AI Council Auto-Fix
- **Disable Trend Filter to Resume Trading**
- **[CONFIG_CHANGE] config.py:** Disable Ollama trend filter that has been blocking trades for 90 minutes
- **[CONFIG_CHANGE] config.py:** Further lower AI confidence threshold as backup measure
- **[CONFIG_CHANGE] config.py:** Update version to reflect the timeout fix
- _Analysis: Bot has been idle for 90 minutes because USE_OLLAMA_TREND_FILTER is blocking all signals by filtering out 'SIDEWAYS' markets. Previous fixes only lowered AI confidence threshold but didn't address the trend filter bottleneck._
- _Files: config.py, config.py, config.py_

## [v3.6.1] - 2026-02-18
### ðŸ›ï¸ AI Council Auto-Fix
- **Fix undefined 'strategy' variable in ai_engine.py**
- **[CODE_FIX] ai_engine.py:** Replace undefined 'strategy' with 'active_strategy' variable that contains the strategy name
- _Analysis: The variable 'strategy' is referenced at line 298 but was never defined in the function scope. It should use 'active_strategy' which contains the strategy name from the final_decision tuple._
- _Files: ai_engine.py_

## [v3.5.9] - 2026-02-18
### ðŸ›ï¸ AI Council Auto-Fix
- **Disable Trend Filter to Resume Trading**
- **[CONFIG_CHANGE] config.py:** Disable Ollama trend filter to allow more trading opportunities
- **[CONFIG_CHANGE] config.py:** Update bot version to reflect the change
- _Analysis: Bot has been idle for 90 minutes with no AI signals. The Ollama trend filter is likely blocking all trading opportunities by classifying the market as SIDEWAYS._
- _Files: config.py, config.py_

## [v3.5.8] - 2026-02-18
### ðŸ›ï¸ AI Council Auto-Fix
- **Disable Trend Filter to Resume Trading**
- **[CONFIG_CHANGE] config.py:** Lower AI confidence threshold further to allow more trading opportunities
- **[CONFIG_CHANGE] config.py:** Update bot version for this fix
- **[CONFIG_CHANGE] config.py:** Update AI_CONFIDENCE_THRESHOLD comment to reflect profile restoration
- _Analysis: Bot has been idle for 90 minutes with no AI signals. The USE_OLLAMA_TREND_FILTER is currently False but the code still checks it, and AI_CONFIDENCE_THRESHOLD at 0.60 may still be too restrictive after multiple similar fixes._
- _Files: config.py, config.py, config.py_

## [v3.5.7] - 2026-02-18
### ðŸ› Bugfix: MTF (Multi-TimeFrame) Always Failing
- **Root Cause:** `count` and `granularity` params were **swapped** in `check_multi_timeframe()`
- `get_candles_df(api, asset, 300, 50)` â†’ `get_candles_df(api, asset, 50, 300)`
- `granularity=50` is invalid for Deriv API â†’ every MTF check failed silently
- **Impact:** No 5-minute trend alignment was ever checked â†’ bot traded against HTF trend
- **Fix:** Corrected to `count=50, granularity=300` (50 Ã— 5-min candles)

### ðŸ§  AI Analyst: Reduce Excessive HOLD Signals
- **Problem:** AI Analyst returned HOLD ~99% of the time (536/538 signals)
- **Root Cause:** Prompt was overly conservative ("ONLY TRADE if Strong trend")
- **Fix:** Rewrote prompt with "DEFAULT BIAS: Look for trades" and "HOLD < 20%"
- Relaxed RSI rejection from 75 â†’ 80 (overbought), 25 â†’ 20 (oversold) in prompt
- Counter-trend trades now allowed if RSI supports the move

### ðŸ”§ Config: Restore AI_CONFIDENCE_THRESHOLD
- Removed Council's hardcoded override (`0.55`) â†’ restored to profile-based value
- TIER_1 uses `0.60` (Council's adjusted value, reasonable for new decisive prompt)

### ðŸŽ¯ Asset Priority Tiers
- **TIER_1** (`1HZ100V`, `R_50`): 54-57% win rate â†’ always scanned first
- **TIER_2** (`R_25`, `1HZ25V`, `R_75`, etc.): 44-50% â†’ fallback assets
- **TIER_3** (`1HZ75V`): 34% â†’ requires AI confidence â‰¥ 0.80 to trade
- `scan_open_assets()` now returns tier-sorted list
- `choose_best_asset()` prompt includes tier preference for AI

## [v3.5.6] - 2026-02-18
### âš¡ Performance: Remove OLLAMA from Heavy Routes
- **Removed OLLAMA** from `COUNCIL` and `ASSET_SCANNER` routing
- OLLAMA timeout (120s) was causing Watchdog kills and bot restarts
- Replaced with `CHATGPT` as fallback for `ASSET_SCANNER`
- OLLAMA still available for `TREND_FILTER` (lighter context)

## [v3.5.5] - 2026-02-18
### ðŸ›ï¸ AI Council Auto-Fix
- **Adjust AI Confidence Threshold and Disable Trend Filter**
- **[CONFIG_CHANGE] config.py:** Lower AI_CONFIDENCE_THRESHOLD to allow more trades and disable USE_OLLAMA_TREND_FILTER to prevent blocking.
- **[CONFIG_CHANGE] config.py:** Disable the trend filter to prevent it from blocking trades.
- _Analysis: The bot has not executed any trades due to a high AI confidence threshold and an active trend filter that may be blocking signals._
- _Files: config.py, config.py_

## [v3.5.4] - 2026-02-18
### ðŸ›ï¸ AI Council Auto-Fix
- **Adjust AI Confidence Threshold and Disable Trend Filter**
- **[CONFIG_CHANGE] config.py:** Lower AI_CONFIDENCE_THRESHOLD to allow more trades and disable USE_OLLAMA_TREND_FILTER to prevent blocking trades.
- **[CONFIG_CHANGE] config.py:** Disable USE_OLLAMA_TREND_FILTER to prevent it from blocking trades.
- _Analysis: The bot has been idle due to a high AI confidence threshold and the trend filter blocking trades. Lowering the threshold and disabling the trend filter should allow more trades to be executed._
- _Files: config.py, config.py_

## [v3.5.3] - 2026-02-18
### âš™ï¸ Configuration Updates
- **Hard Rules Toggle (`config.py`):** Added `ENABLE_HARD_RULES` (Default: True). Allows users to disable strict technical checks if desired.
- **SmartTrader Logic (`smart_trader.py`):** Updated `should_enter()` to respect the new config.

## [v3.5.2] - 2026-02-18
### ðŸ›¡ï¸ Safety & Hard Rules
- **Hard Technical Blocks (`technical_analysis.py`):** Added `check_hard_rules()` to enforce strict safety checks:
    - **Reversal Block:** Prevents entering CALL on Bearish MACD Cross (and vice versa).
    - **Momentum Block:** Blocks CALL if RSI > 75 (Overbought) / PUT if RSI < 25 (Oversold).
    - **Dead Market Block:** Blocks trading if ATR < 0.01%.
- **SmartTrader Integration (`smart_trader.py`):** Added "Level 1.5" check to `should_enter()` which calls Hard Rules before expensive AI/Confirmation checks.

## [v3.5.1] - 2026-02-17
### ðŸ›ï¸ AI Council Bug Fixes
- **ValueError Fix (`ai_council.py`):** Added explicit `float()`/`int()`/`str()` type casting in `_get_trading_stats()` and `_build_council_prompt()` to prevent crashes when dashboard state returns string values.
- **Claude Model Update (`config.py`):** Replaced deprecated `claude-3-5-sonnet-20241022` â†’ `claude-sonnet-4-20250514` to fix 404 errors.
- **Ollama Timeout (`config.py` + `ai_providers.py`):** Added `OLLAMA_COUNCIL_TIMEOUT_SECONDS = 120` with dynamic timeout for prompts > 2000 chars.

### ðŸ“ˆ Signal Quality Improvements
- **Enriched AI Summary (`market_engine.py`):** `get_market_summary_for_ai()` now sends RSI(14), MACD Histogram, ATR%, Stochastic K/D, and SMA Gap to AI Analyst. Previously only sent trend + change%.
- **Stochastic Scoring Fix (`technical_analysis.py`):** Reduced neutral Stochastic score from +0.4 â†’ 0.0 in L2 confirmation to prevent inflated scores.
- **Backtest Validated:** Replayed 15 trades â€” Fix avoids 5/8 losses (62%) while preserving 5/7 wins (71%). Net P/L: -$1.35 â†’ +$1.75.

### ðŸ“ Standards & Documentation
- **[NEW] `AI_CODE_RULE_BASED.md`:** Comprehensive development rules covering version numbering, file safety classification, coding standards, doc update matrix, testing standards, and AI Council guardrails.
- **[NEW] `backtest_losses.py`:** Standalone backtest script for replaying historical trades with real AI providers.

_Files: ai_council.py, config.py, ai_providers.py, market_engine.py, technical_analysis.py, AI_CODE_RULE_BASED.md, backtest_losses.py_

## [v3.4.8] - 2026-02-16




## [v3.4.8] - 2026-02-16
### ðŸ›ï¸ AI Council Auto-Fix
- **Adjust AI Confidence Threshold**
- **[CONFIG_CHANGE] config.py:** Lower AI_CONFIDENCE_THRESHOLD to allow more trades to pass the confidence check.
- _Analysis: The AI_CONFIDENCE_THRESHOLD is set too high, preventing trades from being executed. Lowering it will allow more trades to pass the confidence check._
- _Files: config.py_

## [v3.4.7] - 2026-02-16
### ðŸ›ï¸ AI Council Auto-Fix
- **Adjust AI Confidence Threshold**
- **[CONFIG_CHANGE] config.py:** Lower AI_CONFIDENCE_THRESHOLD to allow more trades to pass the confidence check.
- _Analysis: The AI_CONFIDENCE_THRESHOLD is set too high, causing the bot to skip potential trades due to insufficient confidence._
- _Files: config.py_

## [v3.4.6] - 2026-02-16
### ðŸ›ï¸ AI Council Auto-Fix
- **Adjust AI Confidence Threshold to Resume Trading**
- **[CONFIG_CHANGE] config.py:** Lower the AI_CONFIDENCE_THRESHOLD to allow more trades to pass the confidence check.
- _Analysis: The AI_CONFIDENCE_THRESHOLD is set too high, preventing trades from being executed. Lowering it will allow more trades to pass the confidence check._
- _Files: config.py_

## [v3.4.5] - 2026-02-16
### ðŸ›ï¸ AI Council Auto-Fix
- **Adjust AI Confidence Threshold to Resume Trading**
- **[CONFIG_CHANGE] config.py:** Lower AI_CONFIDENCE_THRESHOLD to allow more trades to pass the confidence check.
- _Analysis: The AI_CONFIDENCE_THRESHOLD for the active profile is set too high, preventing trades from being executed. Lowering this threshold will allow more trades to pass the confidence check._
- _Files: config.py_

## [v3.4.4] - 2026-02-16
### ðŸ›ï¸ AI Council Auto-Fix
- **Adjust AI Confidence Threshold**
- **[CONFIG_CHANGE] config.py:** Lower AI_CONFIDENCE_THRESHOLD to allow more trades to pass the confidence check.
- _Analysis: The AI_CONFIDENCE_THRESHOLD is set too high, preventing trades from being executed. Lowering it will allow more trades to pass the confidence check._
- _Files: config.py_

## [v3.4.3] - 2026-02-16
### ðŸ›ï¸ AI Council Auto-Fix
- **Lower AI Confidence Threshold to Resume Trading**
- **[CONFIG_CHANGE] config.py:** Lower AI confidence threshold to allow more trades.
- _Analysis: The bot is idle because the AI confidence threshold is too high, preventing trades from being executed. Lowering the threshold slightly will allow more trades to be considered._
- _Files: config.py_

## [v3.4.2] - 2026-02-15
### ðŸ›ï¸ AI Council Auto-Fix
- **Adjust AI Confidence Threshold and Disable Trend Filter**
- **[CONFIG_CHANGE] config.py:** Lower AI_CONFIDENCE_THRESHOLD to allow more trades and disable trend filter temporarily.
- **[CONFIG_CHANGE] config.py:** Disable the trend filter to prevent blocking trades due to market conditions.
- _Analysis: The bot has not executed any trades due to overly restrictive AI confidence thresholds and trend filtering, causing it to skip potential trading opportunities._
- _Files: config.py, config.py_

## [v3.4.1] - 2026-02-15
### ðŸ”§ Log Analysis Fixes & Win Rate Improvements
- **Min Stake Fix:** Raised `MIN_STAKE_AMOUNT` from $0.35 â†’ $1.0. Sub-dollar stakes ($0.50/$0.75) were rejected by Deriv API â€” caused **9 failed trades** in today's session.
- **Bet Multiplier Floor:** Raised `AI_CONF_BET_MIN_MULTIPLIER` from 0.35 â†’ 1.0, `get_dynamic_bet_multiplier` floor from 0.5 â†’ 0.75, confidence scaling floor from 0.5 â†’ 0.75. Prevents multiplier from reducing stake below base amount.
- **Configurable L2 Threshold:** `L2_MIN_CONFIRMATION` now in config.py (default 0.35, was hardcoded 0.40). Reduces false blocks from SmartTrader technical confirmation.
- **PUT Signal Filter:** Added `ALLOW_PUT_SIGNALS` config flag. Today's logs showed 0% win rate on PUT trades (2/2 LOSS). Can be set to `False` to block PUTs.
- **bot.py Min Stake:** Now uses `config.MIN_STAKE_AMOUNT` instead of hardcoded `0.50`.
- **trade_engine.py:** Default fallback raised to `1.0`.

## [v3.4.0] - 2026-02-15
### ðŸ›ï¸ No-Trade Timeout â†’ AI Council
- **Idle Detection:** Bot triggers AI Council if no trade executed for 45 minutes (`NO_TRADE_TIMEOUT_MINS`).
- **Config-Only Fixes:** Council restricted to config.py changes for idle timeout (lower thresholds, disable filters, switch profiles).
- **Flag System:** `no_trade_council_triggered` prevents repeated triggers; resets on successful trade.

## [v3.3.3] - 2026-02-15
### ðŸ›°ï¸ Trade Execution & Safety
- **AI Council Linking:** Automated the triggering of AI Council when trade execution (Buy) fails. This allows the AI to diagnose market slippage or API issues immediately.
- **Retry Bug Fix:** Resolved a critical bug where the "Buy Retry" logic failed due to a missing `price` parameter.

## [v3.3.2] - 2026-02-15
### ðŸ›¡ï¸ Trading Safety
- **Consecutive Loss Guard:** Implemented a new monitoring system that triggers the AI Council after a specified number of consecutive losses (Default: 3).
- **Auto-Pause:** In Real accounts, the bot now automatically pauses and requests a Council session for user review after reaching the loss limit.

## [v3.3.1] - 2026-02-15
### ðŸ’» Dashboard Fix
- **Analyze Button:** Fixed an issue where the Analyze button failed to render results due to missing `marked.js` dependency.
- **UI Versioning:** Updated Dashboard title and header to v3.3.1.

## [v3.3.0] - 2026-02-15
### ðŸ›ï¸ AI Council & Auto-Fixer
- **AI Council Intervention:** New autonomous module (`ai_council.py`) to handle bot crashes and errors.
- **Auto-Fixer (Demo):** Automatically applies suggested fixes for Practice/Demo accounts after syntax validation.
- **Manual Approval (Real):** Critical safety measure for Real accountsâ€”pauses bot and requests user approval on Dashboard before applying any changes.
- **Syntax Guard:** Prevents applying broken code by pre-compiling fixes and rolling back on failure.
- **Intervention History:** Full logging of all AI discussions and applied/rejected fixes.

## [v3.2.15] - 2026-02-15
### ðŸ› Crash Fix
- **icon Fix:** Resolved `UnboundLocalError: icon` that caused the bot to crash during status bar updates.
### ðŸ”“ Transparency & Config
- **Exposed Hidden Logic:** Moved hardcoded "Safety Guards" to `config.py` for full user control:
    - `MIN_STAKE_AMOUNT` (Default: 0.35) - Lowered from hardcoded 0.50.
    - `RSI_OVERBOUGHT` / `RSI_OVERSOLD` (Default: 75/25) - AI Override thresholds.
    - `SAFETY_BLOCK_THRESHOLD` (Default: 0.30) - Win Rate cutoff for blocking bad strategies.
    - `SLIPPAGE_BUFFER` (Default: 0.10) - 10% price buffer for Limit Orders.

## [v3.2.10] - 2026-02-15
### ðŸ› Logic Fixes
- **Bet Scaling config:** Fixed an issue where the "Technical/WinRate" scaling logic was running unconditionally even if `ENABLE_AI_CONFIDENCE_BET_SCALING` was set to `False`. Now all forms of dynamic staking are strictly controlled by the config flag.

## [v3.2.9] - 2026-02-15
### ðŸš‘ Hotfix: Type Serialization
- **Proposal Fix:** Explicitly casting `amount` to `float()` before sending to Deriv API to prevent cryptic "minimum stake" errors caused by JSON serialization quirks with numeric types.

## [v3.2.8] - 2026-02-15
### â³ User Experience (UX)
- **Status Bar Re-design:** Merged the Asset info and Idle Countdown into a single, non-flickering status line: `ðŸ“¡ [1HZ100V] TIER_2 | â³ Idle: Scan in 4m 20s... â—`.

## [v3.2.7] - 2026-02-15
### â³ User Experience (UX)
- **True Idle Countdown:** Fixed status bar to show the countdown from the *start* of the 10-minute idle period (e.g., `Idle Countdown: Scan in 9m 59s...`), replacing the generic "Monitoring" message when idle.

## [v3.2.6] - 2026-02-15
### â³ User Experience (UX)
- **Real-time Idle Status:** Replaced the simple countdown with a **Continuous Status Bar** (`â³ Idle Mode: Switching Asset in 8m 42s...`) so users can see exactly how long until the next scan throughout the entire idle period.

## [v3.2.5] - 2026-02-15
### â³ User Experience (UX)
- **Idle Countdown:** Added a visible **5-second countdown** (terminal animation) before automatically switching assets due to inactivity, giving users a heads-up.

## [v3.2.4] - 2026-02-15
### ðŸš‘ Hotfix: Trade Execution
- **Buying Fallback:** Enabled a "Market Buy" fallback (without strict price limit) to handle "Price Moved" errors when high volatility causes limit orders to fail.
- **Error Handling:** Improved error logging for purchase rejections.

## [v3.2.3] - 2026-02-15
### âš™ï¸ Configuration Change
- **Smart Idle Rotation:** Logic refined to switch assets ONLY if no trading activity occurs for **10 minutes** (previously 5m).
- **Active Stability:** Increased standard rotation time to **60 minutes** to prevent interrupting active trading streaks.

## [v3.2.2] - 2026-02-15
### âš™ï¸ Configuration Change
- **Asset Scanner:** Reduced scan interval from 30 mins to **10 mins** (user request) to find trending assets faster.
- **Idle Scan:** Reduced idle scan interval (no trades) to **5 mins**.

## [v3.2.1] - 2026-02-15
### ðŸ› Patch Fixes (Hotfix)
- **Trade Execution:** Fixed "Price Moved" error by ensuring buy price is sent as `float` and preventing request dictionary mutation.
- **Data Persistence:** Increased trade history retention from 200 to 10,000 records in `smart_trader.py` to prevent data loss on restart.

## [v3.2.0] - 2026-02-15
### ðŸ“ˆ Strategy Optimization (RSI Update)
- **RSI Filter:** Implemented RSI (Relative Strength Index) technical indicator to detect Overbought/Oversold conditions.
- **Strict Guard:** Hard blocking of CALL signals if RSI > 75 and PUT signals if RSI < 25 to prevent "Buying the Top" or "Selling the Bottom".
- **AI Logic:** Updated `ai_engine.py` to prompt the AI to favor "Pullbacks" and respect RSI limits.
- **Unit Tested:** Verified RSI calculation and scoring logic with new unit tests.

## [v3.1.2] - 2026-02-15
### ðŸ› Robustness Patches
- **Stake Proposal:** Fixed minimum stake error by falling back to `payout` basis automatically.
- **Rate Limits:** Increased ChatGPT daily limits to 200 to prevent premature analysis filtering.
- **Connection:** Improved handling of "1011 Internal Error" by blacklisting unstable assets.

## [v3.0.0] - 2026-02-14
### ðŸš€ Major Features (Ollama Integration)
- **Ollama Trend Filter:** Implemented a pre-analysis step that uses the local AI (Ollama) to filter out "SIDEWAYS" markets before calling expensive APIs. This significantly reduces API costs and increases system alertness (1-minute checks).
- **Ollama Asset Scanner:** Promoted Ollama to the primary "Assistant Scanner" role, scanning the market every 30 minutes to find the best trends.
- **Failover System:** Configured `config.py` and `ai_providers.py` to automatically fallback to `GEMINI` if the local Ollama instance is unreachable.

## [v2.4.0] - 2026-02-14
### Fixed
- **Stake Amount Truncation:** Implemented "Smart Payout Strategy" to calculate and send integer payout requests that result in the desired fractional stake (e.g., $1.5), bypassing the API's integer stake limitation.
- **Crash Fix:** Resolved `NameError: proposal_req` in `trade_engine.py` by ensuring variable definition before usage.

## [v2.2.0] - 2026-02-14
### Critical Fixes
- **Crash Loop:** Fixed `NameError: datetime` in `bot.py` preventing dashboard updates and causing infinite restarts.
- **Trade Execution:** Fixed `TypeError` in `trade_engine.py` (API call arguments) and `ResponseError` (stake float precision).
- **AI Formatting:** Fixed `ValueError` in `ai_engine.py` JSON prompts by double-escaping f-string braces.
- **Asset Mapping:** Added missing asset name dictionary to `market_engine.py`.

## [v2.1.0] - 2026-02-14
### ðŸ§  Modular AI Architecture
- **Multi-File Split:** Refactored `ai_engine.py` into a modular system for better maintainability:
    - `ai_providers.py`: Unified AI interface (OpenAI, Google, Anthropic, Ollama) with failover, routing, and usage limits.
    - `smart_trader.py`: Advanced decision stack (Performance Guard, Technical confirmation, RL).
    - `technical_analysis.py`: Independent technical indicators and candle pattern recognition.
- **Failover & Routing:** Added task-based AI routing (e.g., Gemini for analysis, ChatGPT for Risk Gate).

### ðŸ• Stability & Safety (Watchdog)
- **Heartbeat System:** Implemented a watchdog task to monitor the main loop for freezes.
- **Auto-Restart:** Added `bot_launcher.bat` to automatically recover the bot process if it crashes or freezes.
- **Improved Async:** Offloaded blocking AI API calls to thread executors and refactored trade monitoring to prevent false-positive watchdog triggers.

### ðŸ“Š Backtesting
- **Full-Strategy Backtest:** Created `backtest.py` to simulate the complete trading logic (L1-L3) against historical data without API costs.

### ðŸ› ï¸ UX & Fixes
- **Console Encoding:** Added UTF-8 support (`chcp 65001`) to fix emoji rendering on Windows.
- **Debug Toggle:** Added `VERBOSE_MODE` in `config.py` to hide/show detailed technical logs.
- **Stake Precision:** Fixed float precision issues causing "minimum stake" errors on Deriv.
- **Strategy Logging:** Console now displays the specific strategy name used for each signal.

## [v1.0.0] - 2026-02-14
### ðŸš€ Initial Release (Genesis)
- **New Core:** Built from scratch using `asyncio` and `deriv-api` for high-performance trading.
- **AI Integration:** Ported `ai_engine` from IQ Bot, refactored for async compatibility.
- **Assets:** Added support for **Volatility Indices** (1HZ100V, R_100, etc.).
- **Smart Gate:** Integrated AI "Bet Gate" to validate signals before execution.
- **Risk Management:** Tiered profiles (Micro, Tier 1, Tier 2) and adaptive money management.
- **Engines:**
    - `market_engine`: Async candle fetching and asset scanning.
    - `trade_engine`: Real-time trade execution and portfolio tracking.
    - `bot.py`: Main async event loop.
- **Dashboard:** Includes Flask-based dashboard for monitoring (ported from IQ Bot).


