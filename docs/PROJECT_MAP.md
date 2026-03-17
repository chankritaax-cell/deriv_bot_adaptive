# 🗺️ Project Map (Deriv Bot v5.1.5)

## 📂 Root Directory (`deriv_bot/`)

### 🤖 Core Bot
*   **`bot.py`**: The main entry point. Runs the **Streaming Event Loop**, handles real-time data assembly, and executes trades.
*   **`config.py`**: Central configuration for assets, risk management, and AI keys.
*   **`asset_profiles.json`**: [NEW] Per-asset performance intelligence and strategy overrides.
*   **`.env`**: Private environment variables (API Tokens, AI Keys, ASSET lists).

### 🍱 Modules (`modules/`)
*   **`stream_manager.py`**: WebSocket Stream Handler with 30s auto-reconnect for real-time Ticks and Candles.
*   **`ai_engine.py`**: Core AI analysis orchestrator with Adaptive Volatility logic, Sniper Recovery, and Stochastic Guard.
*   **`smart_trader.py`**: Strategy stack (Trend Following, Pullback Entry) and RL logic.
*   **`market_engine.py`**: Data fetching and technical indicator snapshot builder.
*   **`technical_analysis.py`**: Core TA indicators (EMA, ATR, RSI, MACD, Stochastic).
*   **`trade_engine.py`**: Execution logic, ghost trade recovery, and balance management.
*   **`asset_selector.py`**: [v5.0 FIX] Dynamic best-asset scanner with profile-aware filtering.
*   **`ai_providers.py`**: Unified interface for Gemini, ChatGPT, Claude, and Ollama.
*   **`ai_council.py`**: AI Multi-Vote Multi-Agent logic for diagnosis and auto-fixes.
*   **`telegram_bridge.py`**: Notification system for trades and AI Council alerts.
*   **`utils.py`**: Dashboard state management and advanced logging.

### 🛠️ Scripts (`scripts/`)
*   **`backtest_7d.py`**: [NEW] 7-Day Performance stress-test for V5.0 Adaptive Engine.
*   **`backtest_7h.py`**: Strategy testing script (Short-term).
*   **`check_deriv_stake.py`**: Utility to verify stake limits.
*   **`compare_prices.py`**: Price feed latency check.

### 💻 Dashboard
*   **`dashboard_server.py`**: Flask server for real-time web monitoring (Port 5001).
*   **`templates/`**: UI components for the web interface.

### 📝 Documentation (`docs/`)
*   **`README.md`**: Setup and usage guide.
*   **`CHANGELOG.md`**: Detailed version history.
*   **`FEATURES.md`**: Core capabilities overview including Adaptive Volatility.
*   **`PROJECT_MAP.md`**: This file.
*   **`AI_CODE_RULE_BASED.md`**: Development and AI Coding rules.

### 📦 Meta
*   **`requirements.txt`**: Project dependencies.
*   **`logs/`**: Structured logs for trades and AI Council history.
