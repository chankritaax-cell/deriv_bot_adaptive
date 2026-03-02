import asyncio
import os
import sys
# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time

# Manually parse .env for Token
API_TOKEN = None
try:
    with open(".env", "r") as f:
        for line in f:
            if line.strip().startswith("DERIV_API_TOKEN"):
                parts = line.split("=", 1)
                if len(parts) == 2:
                    API_TOKEN = parts[1].strip().strip('"').strip("'")
                    break
except Exception as e:
    print(f"Error reading .env: {e}")

if not API_TOKEN:
    API_TOKEN = os.getenv("DERIV_API_TOKEN")

APP_ID = 1089

async def run_test_trade(api, i):
    print(f"\n--- 🚀 Trade #{i+1} Starting ---")
    
    # 1. Get Proposal (1HZ50V CALL) - Fast Market!
    proposal_req = {
        "proposal": 1,
        "amount": 2, 
        "basis": "payout",
        "contract_type": "CALL",
        "currency": "USD",
        "duration": 1,
        "duration_unit": "m",
        "symbol": "1HZ50V" 
    }
    
    try:
        print("1. Requesting Proposal (Payout 2, 1HZ50V)...")
        res = await asyncio.wait_for(api.proposal(proposal_req), timeout=10)
        prop = res.get("proposal")
        
        if not prop:
            print(f"❌ Trade #{i+1} Failed: No proposal returned.")
            return False

        prop_id = prop['id']
        raw_ask = float(prop['ask_price'])
        print(f"   ✅ Proposal ID: {prop_id}")
        print(f"   ✅ Ask Price: {raw_ask}")
        
        # 2. Calculate Slippage (Exact Logic from trade_engine.py)
        # Using 10% buffer as per latest fix
        buffered_price = round(raw_ask * 1.10, 2)
        print(f"2. Calculating Buffer: {raw_ask} * 1.10 = {raw_ask*1.10:.4f} -> Round: {buffered_price}")
        
        # 3. Execute Buy
        print(f"3. Executing Buy (Dict format)...")
        start_t = time.time()
        buy_req = {"buy": prop_id, "price": buffered_price}
        
        buy_res = await asyncio.wait_for(api.buy(buy_req), timeout=20)
        
        if "buy" in buy_res:
             print(f"   ✅ SUCCESS! Contract ID: {buy_res['buy']['contract_id']}")
             print(f"   PLEASE CHECK TRANSACTION LOG. Cost: {buy_res['buy']['buy_price']}")
             return True
        else:
             print(f"   ❌ FAILED Response: {buy_res}")
             return False
             
    except Exception as e:
        print(f"   ❌ EXCEPTION: {e}")
        return False

async def main():
    if not API_TOKEN:
        print("❌ Error: No API Token found.")
        return

    api = DerivAPI(app_id=APP_ID)
    
    print("--- 🔐 Authenticating ---")
    try:
        auth = await api.authorize(API_TOKEN)
        print(f"✅ Authorized: {auth['authorize']['email']} (Balance: {auth['authorize']['balance']})")
    except Exception as e:
        print(f"❌ Auth Failed: {e}")
        return

    success_count = 0
    total_trades = 3
    
    for i in range(total_trades):
        if await run_test_trade(api, i):
            success_count += 1
        
        if i < total_trades - 1:
            print("⏳ Waiting 3s before next trade...")
            await asyncio.sleep(3)

    print("\n" + "="*30)
    print(f"🏁 TEST SUMMARY: {success_count}/{total_trades} TRADES SUCCEEDED")
    print("="*30)
    
    await api.clear()

if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(main())
