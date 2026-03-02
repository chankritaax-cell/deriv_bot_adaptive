import asyncio
import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from deriv_api import DerivAPI
# from dotenv import load_dotenv

# from dotenv import load_dotenv

APP_ID = 1089 
API_TOKEN = None

# Manual .env loading
try:
    with open(".env", "r") as f:
        for line in f:
            if line.startswith("DERIV_API_TOKEN="):
                API_TOKEN = line.strip().split("=")[1]
                break
except Exception:
    pass

if not API_TOKEN:
    # Try generic environ
    API_TOKEN = os.getenv("DERIV_API_TOKEN")

if not API_TOKEN:
    print("❌ API Token not found in environment!")
    exit(1)

async def check_stake():
    api = DerivAPI(app_id=APP_ID)
    try:
        authorize = await api.authorize(API_TOKEN)
        print(f"✅ Authorized: Balance {authorize['authorize']['balance']}")

        # Test 1: Float 1.5
        req_float = {
            "proposal": 1,
            "amount": 1.5,
            "basis": "stake",
            "contract_type": "CALL",
            "currency": "USD",
            "duration": 60,
            "duration_unit": "s",
            "symbol": "R_100"
        }
        print(f"\n🧪 Test 1: Sending Float 1.5")
        print(f"   Req: {req_float}")
        try:
            res1 = await api.proposal(req_float)
            p1 = res1.get("proposal")
            if p1:
                print(f"   👉 Ask Price: {p1['ask_price']} (Display: {p1['display_value']})")
                print(f"   📋 Full Resp: {p1}")
            else:
                print(f"   ❌ Error: {res1}")
        except Exception as e:
            print(f"   ❌ Exception: {e}")

        # Test 2: String "1.5"
        req_str = {
             "proposal": 1,
            "amount": "1.5",
            "basis": "stake",
            "contract_type": "CALL",
            "currency": "USD",
            "duration": 60,
            "duration_unit": "s",
            "symbol": "R_100"
        }
        print(f"\n🧪 Test 2: Sending String '1.5'")
        print(f"   Req: {req_str}")
        try:
            res2 = await api.proposal(req_str)
            p2 = res2.get("proposal")
            if p2:
                 print(f"   👉 Ask Price: {p2['ask_price']} (Display: {p2['display_value']})")
            else:
                print(f"   ❌ Error: {res2}")
        except Exception as e:
            print(f"   ❌ Exception: {e}")

        # Test 3: Float 2.5
        req_float2 = {
             "proposal": 1,
            "amount": 2.5,
            "basis": "stake",
            "contract_type": "CALL",
            "currency": "USD",
            "duration": 60,
            "duration_unit": "s",
            "symbol": "R_100"
        }
        print(f"\n🧪 Test 3: Sending Float 2.5")
        try:
            res3 = await api.proposal(req_float2)
            p3 = res3.get("proposal")
            if p3:
                 print(f"   👉 Ask Price: {p3['ask_price']} (Display: {p3['display_value']})")
        except Exception as e:
            print(f"   ❌ Exception: {e}")
            
        # Test 4: Payout 5
        req_payout = {
             "proposal": 1,
            "amount": 5,
            "basis": "payout",
            "contract_type": "CALL",
            "currency": "USD",
            "duration": 60,
            "duration_unit": "s",
            "symbol": "R_100"
        }
        print(f"\n🧪 Test 4: Sending Payout 5")
        try:
            res4 = await api.proposal(req_payout)
            p4 = res4.get("proposal")
            if p4:
                 print(f"   👉 Ask Price: {p4['ask_price']} (Display: {p4['display_value']}) Payout: {p4['payout']}")
        except Exception as e:
            print(f"   ❌ Exception: {e}")

        # Test 5: Two-Step Payout Strategy
        print(f"\n🧪 Test 5: Two-Step Payout Strategy for Stake 1.5")
        
        # Step 1: Get Reference Rate (Stake 1)
        req_ref = {
             "proposal": 1,
            "amount": 1,
            "basis": "stake",
            "contract_type": "CALL",
            "currency": "USD",
            "duration": 60,
            "duration_unit": "s",
            "symbol": "R_100"
        }
        ref_payout_val = 0
        try:
            res_ref = await api.proposal(req_ref)
            p_ref = res_ref.get("proposal")
            if p_ref:
                 ref_payout_val = float(p_ref['payout'])
                 ref_ask = float(p_ref['ask_price'])
                 print(f"   👉 Step 1 (Ref): Stake {ref_ask} -> Payout {ref_payout_val}")
            else:
                print(f"   ❌ Step 1 Error: {res_ref}")
        except Exception as e:
            print(f"   ❌ Step 1 Exception: {e}")
            
        if ref_payout_val > 0:
            # Step 2: Calculate Target Payout
            # Ratio = Payout / Stake. Since Stake is 1, Ratio = Payout.
            # Target Payout = Target Stake * Ratio
            target_stake = 1.5
            target_payout = target_stake * ref_payout_val
            
            req_calc = {
                 "proposal": 1,
                "amount": target_payout,
                "basis": "payout",
                "contract_type": "CALL",
                "currency": "USD",
                "duration": 60,
                "duration_unit": "s",
                "symbol": "R_100"
            }
            print(f"   👉 Step 2: Target Stake {target_stake} * Rate {ref_payout_val} = Req Payout {target_payout}")
            
            try:
                res_calc = await api.proposal(req_calc)
                p_calc = res_calc.get("proposal")
                if p_calc:
                     print(f"   👉 Result: Ask Price: {p_calc['ask_price']} (target ~1.5)")
            except Exception as e:
                print(f"   ❌ Step 2 Exception: {e}")
    
    except Exception as e:
        print(f"❌ Critical Error: {e}")
    finally:
        pass

if __name__ == "__main__":
    asyncio.run(check_stake())
