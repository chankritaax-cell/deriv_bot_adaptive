import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

# Force settings for repro
os.environ["DERIV_APP_ID"] = "1089"
config.CURRENCY = "USD"
API_TOKEN = getattr(config, "DERIV_API_TOKEN", None)

async def test_r75():
    api = DerivAPI(app_id=config.DERIV_APP_ID)
    
    try:
        # 1. Authorize
        if API_TOKEN:
            print("🔐 Authorizing...")
            auth = await api.authorize(API_TOKEN)
            print(f"✅ Authorized. Currency: {auth['authorize']['currency']}")
        else:
            print("⚠️ No Token found. Running anonymous (might be the issue).")

        # 2. Test Loop
        amounts = [0.95, 0.9, 0.8, 0.6, 0.4]
        
        for amt in amounts:
            print(f"\n--- Testing Stake: {amt} ---")
            req = {
                "proposal": 1,
                "amount": amt,
                "basis": "stake",
                "contract_type": "CALL",
                "currency": "USD",
                "duration": 60,
                "duration_unit": "s",
                "symbol": "R_75"
            }
            try:
                res = await api.proposal(req)
                print(f"✅ Stake {amt} Success!")
            except Exception as e:
                print(f"❌ Stake {amt} Failed: {e}")

        # 3. Test Payout Basis (Boundary Check)
        payouts = [0.9, 0.95, 0.99, 1.0, 1.05]
        for pay in payouts:
           print(f"\n--- Testing Payout: {pay} ---")
           req = {
               "proposal": 1,
               "amount": pay,
               "basis": "payout",
               "contract_type": "CALL",
               "currency": "USD",
               "duration": 60,
               "duration_unit": "s",
               "symbol": "R_75"
           }
           try:
               res = await api.proposal(req)
               print(f"✅ Payout {pay} Success! Ask (Stake): {res['proposal']['ask_price']}")
           except Exception as e:
               print(f"❌ Payout {pay} Failed: {e}")

    except Exception as e:
        print(f"❌ Fatal Error: {e}")
        
    await api.disconnect()

if __name__ == "__main__":
    asyncio.run(test_r75())
