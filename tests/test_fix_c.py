import asyncio
import os
import sys
from unittest.mock import MagicMock, patch

# Add parent directory to path to import modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Mock modules to avoid real API calls
sys.modules['modules.market_engine'] = MagicMock()
sys.modules['modules.smart_trader'] = MagicMock()
sys.modules['modules.technical_analysis'] = MagicMock()

import config
from modules import ai_engine

# Mock config
config.USE_AI_ANALYST = True
config.USE_OLLAMA_TREND_FILTER = False # Skip trend filter

def mock_call_ai(prompt, task, timeout):
    print("\n📝 CAPTURED PROMPT:")
    print("-" * 40)
    print(prompt)
    print("-" * 40)
    return {"action": "HOLD", "confidence": 0.0, "reason": "Test"}

async def test():
    print("🚀 Testing AI Prompt Construction (Fix C)...")
    
    # Mock dependencies
    api = MagicMock()
    asset = "1HZ100V"
    
    # Mock Market Summary with Semantic Tags (Simulating Fix A output)
    market_summary = (
        "Asset: 1HZ100V, Close: 3450.5, Trend: UPTREND (Strong), "
        "RSI: 78.5 (Overbought ⚠️), MACD: -0.05 (Bearish/Weak), "
        "Stoch: K=85 (Overbought)"
    )
    
    df_1m = MagicMock()
    df_1m.__len__.return_value = 20
    
    # Patch call_ai_with_failover
    with patch('modules.ai_engine.call_ai_with_failover', side_effect=mock_call_ai):
        await ai_engine.analyze_and_decide(api, asset, market_summary, df_1m)

if __name__ == "__main__":
    asyncio.run(test())
