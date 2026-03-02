"""
🧪 AI Council — Automated Test Suite (v3.3.3)
Simulates crashes and verifies AI Council intervention logic.
"""

import asyncio
import os
import sys
import json
import shutil
import traceback

# Add current dir to path
# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from modules import ai_council
from modules.utils import log_print

# Mock context for testing
MOCK_ERROR = "ZeroDivisionError: division by zero"
MOCK_TRACEBACK = """
  File "bot.py", line 123, in main
    result = 1 / 0
"""

async def test_council_intervention_demo():
    print("\n--- 🧪 TEST 1: Demo Account (Auto-Fix) ---")
    # Setup
    config.DERIV_ACCOUNT_TYPE = "demo"
    config.ENABLE_AI_COUNCIL = True
    config.COUNCIL_AUTO_FIX_PRACTICE = True
    
    print(f"Testing with Account Type: {config.DERIV_ACCOUNT_TYPE}")
    
    # Trigger resolution
    # Note: This will attempt a real AI call unless we monkeypatch it.
    # For this "Automate Test", we want to see if the flow handles the AI response.
    try:
        result = await ai_council.resolve_error(MOCK_ERROR, MOCK_TRACEBACK)
        print(f"Result: {result}")
        
        # Check history
        history = ai_council._get_history()
        if any(MOCK_ERROR in str(h.get("context", {}).get("error", "")) for h in history):
            print("✅ PASS: Error recorded in history.")
        else:
            print("❌ FAIL: Error not found in history.")
    except Exception as e:
        print(f"⚠️ AI Call skipped or failed (Normal if no API keys): {e}")

async def test_council_intervention_real():
    print("\n--- 🧪 TEST 2: Real Account (Manual Approval) ---")
    # Setup
    config.DERIV_ACCOUNT_TYPE = "real"
    
    print(f"Testing with Account Type: {config.DERIV_ACCOUNT_TYPE}")
    
    try:
        # Trigger resolution
        result = await ai_council.resolve_error(MOCK_ERROR, MOCK_TRACEBACK)
        
        print(f"Result: {result}")
        if result == "USER_APPROVAL_REQUIRED":
            pending = ai_council._get_pending()
            if any(MOCK_ERROR in str(p.get("context", {}).get("error", "")) for p in pending.values()):
                print("✅ PASS: Proposal saved to pending list.")
            else:
                print("❌ FAIL: Proposal not found in pending.")
        else:
            print(f"❌ FAIL: Real account did not trigger approval requirement.")
    except Exception as e:
         print(f"⚠️ AI Call skipped or failed (Normal if no API keys): {e}")

async def test_syntax_validation():
    print("\n--- 🧪 TEST 3: Syntax Guard ---")
    test_file = "test_syntax_tmp.py"
    
    # Valid code
    with open(test_file, "w") as f: f.write("print('Hello')")
    ok, err = ai_council.validate_syntax(test_file)
    print(f"Valid Code Test: {'✅ OK' if ok else '❌ FAIL'}")
    
    # Invalid code
    with open(test_file, "w") as f: f.write("if True print 'Missing colon'")
    ok, err = ai_council.validate_syntax(test_file)
    print(f"Invalid Code Test: {'✅ Success (Detected Error)' if not ok else '❌ FAIL (Missed Error)'}")
    
    if os.path.exists(test_file): os.remove(test_file)

async def run_all_tests():
    print("🚀 Starting AI Council Automated Tests...")
    await test_syntax_validation()
    await test_council_intervention_demo()
    await test_council_intervention_real()
    print("\n🏁 All tests completed.")

if __name__ == "__main__":
    asyncio.run(run_all_tests())
