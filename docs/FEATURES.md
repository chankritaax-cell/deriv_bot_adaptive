# ✨ Features & Capabilities

## 🧠 AI Intelligence (The Brain)
*   **Multi-Model Support:** Seamlessly switches between **ChatGPT**, **Gemini**, and **Claude**.
*   **AI Analyst:** Scans the market for the best asset and strategy every 5 minutes.

### 🧠 Hybrid AI Engine (v4.0.0)
The system now uses a **multi-tier AI architecture**:
1.  **Event-Driven Streaming (v4.0.0)**: Real-time WebSocket subscriptions for Ticks and Candles, replacing old polling loops.
2.  **AI Council (v4.0.0)**: Multi-Vote system querying all 4 AI providers to diagnose and fix errors autonomously.
3.  **Ollama (Local)**: Primary "Trend Filter" and "Asset Scanner". Checks market conditions every minute for free.
3.  **Google Gemini 2.0 Flash**: Primary "Market Analyst". Called only when Ollama confirms a trend.
4.  **OpenAI ChatGPT**: "Bet Gate" bouncer. Double-checks high-confidence signals.
5.  **Anthropic Claude**: "Risk Manager". Adjusts position sizing dynamically.

### 🏛️ AI Council (v3.4.0)
Autonomous error resolution system with 3 trigger types:
- **CODE_ERROR**: Bot crash/exception → can fix any `.py` file.
- **CONSECUTIVE_LOSS**: Lost N trades in a row → adjusts `config.py` only.
- **NO_TRADE_TIMEOUT**: Idle 45 min → adjusts `config.py` only (lower thresholds, switch profile).
- **Multi-Vote**: All 4 providers propose fixes; scored by snippet match, file existence, and risk level.
- **Intent Classifier (v3.10.0):** AI-powered gatekeeper distinguishes between "Consultation" (Questions) and "Action" (Code Changes).
- **Thai Language Support (v3.10.1):** Native Thai responses for analysis and explanations.
- **Auto-Backtest & Switch (v3.11.0):** Self-optimizing mechanism that backtests all assets during downtimes and switches to the highest-performing one automatically.
- **Safety**: Version-based backups, syntax validation, auto rollback on failure.

### 📈 Strategy Optimization (v3.5.1)
- **RSI Guard:** Automatically blocks "Buying the Top" (Overbought > 75) and "Selling the Bottom" (Oversold < 25).
- **Pullback Focus:** AI is instructed to prioritize "Dip Buying" in strong uptrends rather than chasing breakouts.
- **Enriched AI Summary (v3.5.1):** AI Analyst now receives RSI, MACD Histogram, ATR%, Stochastic K/D, and SMA Gap — not just trend direction. Backtest shows 62% loss avoidance rate.
- **Stochastic Scoring Fix (v3.5.1):** Neutral Stochastic no longer inflates L2 confirmation score (+0.4 → 0.0).
- **Min Stake Safety:** Enforces `MIN_STAKE_AMOUNT` ($1.0) to prevent sub-dollar stakes rejected by Deriv API.
- **PUT Signal Filter:** Configurable `ALLOW_PUT_SIGNALS` flag to block PUT trades when historical win rate is low.
- **L2 Configurable Threshold:** `L2_MIN_CONFIRMATION` in config (default 0.35) controls SmartTrader tech confirmation strictness.
- **Hard Rules Mechanism (v3.5.2):** Code-based failsafe that overrides AI decisions if technical indicators show clear danger (MACD Reversal, RSI Extreme, Dead Market). *Now Configurable via `ENABLE_HARD_RULES` (v3.5.3).*
- **Post-AI Mathematical Guards (v3.11.56):**
    - **MACD Momentum Exhaustion:** Vetoes CALLs if momentum is shrinking; vetoes PUTs if momentum is rising.
    - **Tick Velocity Guard:** Real-time spike protection (5-tick move > 50% ATR).

## 📊 V5.0 Adaptive Volatility Regimes (NEW)
*   **Sticky Regime State Machine**: Uses EMA 20 ATR with a 3-candle confirmation to detect `NORMAL`, `HIGH_VOL`, and `LOW_VOL` market conditions. Prevents rapid switching (flickering) in choppy markets.
*   **Dynamic Parameter Overrides**: Automatically adjusts RSI Call/Put boundaries and Bounce Limits based on volatility.
*   **Regime-Driven Strategy Selection**: Automatically switches between `TREND_FOLLOWING` (High Vol) and `PULLBACK_ENTRY` (Low Vol) to maximize edge in any market environment.
*   **Profile Intelligence**: Reads per-asset specific configuration (Pullback Zones, Slope Thresholds) from `asset_profiles.json`.

### 📊 Structured Metrics Logging (v3.4.14)
- Logs key entry/exit metrics to a JSONL file for later winrate analysis.
- Captures: **RSI(14), EMA(9/21), ATR(14), L2 confirmation score, bet multiplier, amount, price, contract_id, result, profit**.
- Default output: `logs/metrics/trade_metrics.jsonl` (override with `METRICS_LOG_PATH`).
- Optional console echo: set `METRICS_LOG_CONSOLE=1`.


### 🛡️ Smart Failover
- If **Ollama** is down -> Falls back to **Gemini**.
- If **Gemini** is rate-limited -> Falls back to **ChatGPT**.
- Ensures 24/7 uptime without manual intervention.
*   **Bet Gate:** "The Bouncer" - Determines if a signal is worth taking based on confidence and market context.
*   **Risk Manager:** Adapts bet size and stops trading during "bad market" conditions.

## ⚡ Performance (The Core)
*   **AsyncIO Architecture:** Non-blocking operations allow the bot to scan, analyze, and trade multiple assets simultaneously.
*   **WebSocket Streaming:** Direct connection to Deriv's API for millisecond-latency data.
*   **Smart Caching:** Reduces API calls by caching candle data and asset lists.

## 📊 Market & Assets
*   **Volatility Indices:** Optimized for 24/7 synthetic markets (100, 75, 50, 25, 10).
*   **Payout Scanning:** Automatically rotates to assets with the highest payouts.
*   **Indicators:** Built-in standard indicators (RSI, Bollinger Bands, MACD, Stochastic).

## 🛡️ Risk Management & Stability
*   **L1-L4 Decision Stack:** Multi-layer filtering (Performance History → Technical Indicators → RL Optimizer → AI Confidence Scaling).
*   **Anti-Martingale:** Smart recovery logic that doesn't blindly double down.
*   **Heartbeat Watchdog:** Internal monitor that kills and restarts the bot if the main loop freezes > 60s.
*   **Auto-Recovery Window:** `bot_launcher.bat` handles automatic process respawning and UTF-8 encoding fix.
*   **AI Council Auto-Fixer (v3.4.0):** Autonomous Multi-Vote detection and resolution of runtime errors, consecutive losses, and idle timeouts. Mandatory user approval for real accounts.
*   **No-Trade Timeout (v3.4.0):** Triggers AI Council if bot is idle for 45 minutes (`NO_TRADE_TIMEOUT_MINS`).
*   **Max Daily Loss:** Hard stop triggered by percentage or absolute amount.

## 💻 Dashboard & Tools
*   **Full-Strategy Backtest:** Simulate the complete L1+L2+L3 stack against historical data to verify strategy viability.
*   **Web Interface:** Real-time view of account balance, active trades, and AI decisions.
*   **Verbose Logging:** Strategy names and detailed technical reasons displayed in real-time.
*   **UTF-8 Terminal:** Optimized for Windows with full Emoji and Thai character support.
