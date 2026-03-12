# 🤖 Deriv AI Bot (Streaming Architecture)

> **v5.5.2 (Adaptive)** | A high-performance, asynchronous trading bot designed specifically for **Deriv.com** (Volatility Indices) using **Python (asyncio)**, **WebSocket Streaming**, and **Adaptive Volatility Profiles**.

## 🌟 Key Features

*   **⚡ Event-Driven Core:** Transitioned to a real-time WebSocket streaming model for millisecond data synchronization.
*   🧠 **Hybrid AI Engine (v5.5.2)**: Combines **Google Gemini 2.0** (Analysis), **OpenAI ChatGPT** (Bet Gate), **Claude** (Risk Manager/Council), and **Adaptive Volatility Regimes** for maximum intelligence.
*   **📊 V5.0 Adaptive Volatility Regimes**: Sticky Regime State Machine (ATR EMA 20) with 3-candle confirmation to detect `NORMAL`, `HIGH_VOL`, and `LOW_VOL`.
*   **🎯 Sniper Recovery System (v5.5.2)**: Dynamic AI confidence thresholds that scale with Martingale steps (Base: 0.75, MG1: 0.80, MG2+: 0.80).
*   **🛡️ Stochastic Exhaustion Guard (v5.1.4)**: Prevents trend-chasing into overbought/oversold zones using live Stochastic K/D.
*   **📡 Stream Auto-Reconnect (v5.1.2)**: 30-second soft-reconnect on API silent drops, bypassing hard watchdog kills.
*   **🎚️ Dynamic Parameter Overrides**: RSI boundaries and bounce limits automatically adjust based on the current market regime.
*   **🏛️ AI Council (v4.0.0)**: Multi-Vote system querying 4 AI providers to auto-diagnose and fix bot crashes, consecutive losses, and idle timeouts.
*   **🛡️ Post-AI Mathematical Guards**: **MACD Momentum Exhaustion**, **Tick Velocity** (Micro-Spike), and **Sniper Confidence** protection.
*   **📈 Strategy Optimization**: Refined RSI Filter, ATR Dynamic thresholds, and hard technical rules to prevent late-trend entries.
*   **🔥 ChatGPT Credit Burn Mode**: Special mode to utilize paid OpenAI credits for **Asset Scanning**, **Trend Filtering**, and **Analysis** simultaneously.
*   **🏠 Local AI First**: Uses local Ollama instance to filter market noise and scan assets (when Burn Mode is OFF).
*   **🛡️ Multi-Level Failover**: Automatically switches to backup providers (e.g., Gemini) if local AI or primary APIs fail.
*   **⚡ High-Frequency Logic**: Async architecture with 1-second decision loops and real-time WebSocket data.
*   **🛡️ Smart Gate (Bet Gate)**: AI "Risk Manager" (ChatGPT) verifies every signal before execution using independent reasoning.
*   **📉 Risk Management:** L1-L4 decision stack (Performance Guard, Technical confirmation, RL, AI Confidence Scaling).
*   **🎚️ TIER Profiles Active (NEW):** Each profile now enforces **AI confidence gate**, **daily loss stop (percent/absolute)**, and **martingale (loss streak)** with stake caps.
*   **🐕 Watchdog:** Built-in heartbeat monitoring and auto-restart capability for 24/7 stability.
*   **📊 Structured Metrics Logging (NEW):** Saves EMA/ATR/RSI + L2 confirmation + bet multiplier at entry/exit into a JSONL file for winrate tuning.

## 📂 Project Structure

```
deriv_bot/
├── bot.py                 # Main Async Loop (Heartbeat/Watchdog active)
├── config.py              # Settings (Assets, Money Mgmt, AI Keys, Profiles)
├── asset_profiles.json    # Per-asset strategy & RSI profiles
├── run.bat                # Auto-Restart Launcher (Windows)
├── modules/
│   ├── ai_engine.py           # Orchestrator for AI Providers & SmartTrader
│   ├── ai_providers.py        # AI Multi-Model Interface & Routing
│   ├── ai_council.py          # AI Council — Multi-Vote diagnosis & auto-fix
│   ├── smart_trader.py        # Smart Trader Decision Stack (L1-L4)
│   ├── technical_analysis.py  # Indicators & Candle Pattern Recognition
│   ├── market_engine.py       # Async Market Data & Asset Scanning
│   ├── stream_manager.py      # WebSocket Stream Handler (Auto-Reconnect)
│   ├── trade_engine.py        # Async Execution & Portfolio Mgmt
│   ├── asset_selector.py      # Dynamic best-asset scanner
│   ├── telegram_bridge.py     # Telegram notifications
│   └── utils.py               # Dashboard state & logging utilities
├── dashboard_server.py    # Web Dashboard (Flask)
├── requirements.txt       # Dependencies
└── .env                   # Secrets (API Tokens)
```

## 🚀 Installation

1.  **Install Python 3.10+**
2.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```
3.  **Configure Strings:**
    *   Rename `.env.example` to `.env` (if available) or create one.
    *   Add your Deriv API Token and App ID.

    ```ini
    DERIV_APP_ID=1089
    DERIV_API_TOKEN=your_deriv_token_here
    OPENAI_API_KEY=sk-...
    ```

## ⚡ Usage

### 1. Backtest (Short-term)
Simulate your current strategy on 500 candles.
```bash
python backtest.py
```

### 2. 7-Day Performance Test (V5.0 Recommended)
Stress test the V5.0 Adaptive Engine over 10,000+ historical candles across 7 days.
```bash
python scripts/backtest_7d.py
```

### 3. Test Connection
Verify that your token works and the bot can fetch candles.
```bash
python test_deriv_connection.py
```

### 2. Run Bot & Dashboard
Start the bot and dashboard simultaneously.

**Windows:**
Double-click `run.bat` or run:
```bash
run.bat
```
(This opens two new windows: one for the Bot, one for the Dashboard)

**Linux/Mac:**
```bash
python bot.py & python dashboard_server.py
```

### 3. Access Dashboard
View live stats at: http://localhost:5001

## ⚙️ Configuration (`config.py`)

*   **`ACTIVE_ASSET`**: Default asset to trade (e.g., `"R_75"` for Volatility 75).
*   **`ACTIVE_PROFILE`**: Trading profile (`TIER_COUNCIL`, `TIER_1`, `TIER_2`, `TIER_MICRO`).
*   **`AI_PROVIDER`**: Choose `"CHATGPT"`, `"GEMINI"`, or `"CLAUDE"`.
*   **`MIN_STAKE_AMOUNT`**: Minimum stake per trade (default `1.0`).
*   **`CONFIDENCE_BASE` / `CONFIDENCE_MG_STEP_1` / `CONFIDENCE_MG_STEP_2`**: Sniper Recovery thresholds.

## ⚠️ Risk Warning

Trading Volatility Indices involves significant risk. This bot is a tool, not a guarantee of profit.
*   **Testing:** Always test on **Demo Account** first.
*   **Monitoring:** Do not leave the bot running unmonitored for long periods.

---
*Built with ❤️ by AI Agent*
