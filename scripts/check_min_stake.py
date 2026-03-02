import asyncio
import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Hack to make it finding deriv_api
from deriv_api import DerivAPI
import config
import json

# Ensure API ID IS set
if not os.environ.get("DERIV_APP_ID"):
    os.environ["DERIV_APP_ID"] = "1089"

async def check_min_stake():
    api = DerivAPI(app_id=config.DERIV_APP_ID)
    
    try:
        symbol = "R_100" # 1HZ100V
        print(f"I: Checking Contract Limits for {symbol}...")
        
        # [Verifying by Error]
        # Since contracts_for didn't give us the number, let's hit the endpoint with a tiny stake
        # and see what the API yells at us. This is the source of truth.
        print("\nI: Verification by intentionally sending too small stake (0.01)...")
        try:
             prop = await api.proposal({
                "proposal": 1,
                "amount": 0.01,
                "basis": "stake",
                "contract_type": "CALL",
                "currency": "USD",
                "duration": 60,
                "duration_unit": "s",
                "symbol": symbol
             })
             print(f"I: Proposal Check Result: {prop}")
        except Exception as e:
             print(f"I: PROVEN LIMIT -> {e}")
            
    except Exception as e:
        print(f"E: Error: {e}")
    finally:
        await api.disconnect()

if __name__ == "__main__":
    asyncio.run(check_min_stake())
