
import asyncio
import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from deriv_api import DerivAPI

LOG_FILE = "verify_stake_result.txt"

def log(msg):
    print(msg)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")

async def test_stake():
    if os.path.exists(LOG_FILE): os.remove(LOG_FILE)
    log("🚀 Verifying Stake Proposal Logic (Variations)...")
    
    api = DerivAPI(app_id=config.DERIV_APP_ID)
    
    try:
        authorize = await api.authorize(config.DERIV_API_TOKEN)
        log(f"✅ Authorized: {authorize['authorize']['loginid']}")
        
        amounts_to_test = [
            (0.75, "Float 0.75", "stake"),
            (1.00, "Float 1.00", "stake"),
            ("0.75", "String '0.75'", "stake"),
            (0.35, "Float 0.35", "stake"),
            (1.50, "Payout ~1.50 (Stake 0.75)", "payout"),
        ]
        
        asset = "R_75"
        
        for amt, desc, basis in amounts_to_test:
            log(f"\n--- Testing: {desc} (Basis: {basis}) ---")
            proposal_req = {
                "proposal": 1,
                "amount": amt, 
                "basis": basis,
                "contract_type": "CALL",
                "currency": config.CURRENCY,
                "duration": 60,
                "duration_unit": "s",
                "symbol": asset
            }
            
            log(f"🔄 Request: {proposal_req}")
            
            try:
                proposal = await api.proposal(proposal_req)
                if "error" in proposal:
                    log(f"❌ Error: {proposal['error']['message']}")
                else:
                    log(f"✅ Success! ID: {proposal['proposal']['id']}")
                    log(f"   Ask Price: {proposal['proposal']['ask_price']}")
                    log(f"   Payout: {proposal['proposal']['payout']}")
            except Exception as e:
                log(f"❌ Exception: {e}")
            
    except Exception as e:
        log(f"❌ Critical Exception: {e}")
    finally:
        # await api.disconnect()
        pass

if __name__ == "__main__":
    asyncio.run(test_stake())
