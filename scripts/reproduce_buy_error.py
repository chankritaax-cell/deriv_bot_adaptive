import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from deriv_api import DerivAPI

API_TOKEN = config.DERIV_API_TOKEN
APP_ID = config.DERIV_APP_ID

async def main():
    api = DerivAPI(app_id=APP_ID)
    
    print("--- Authenticating ---")
    auth = await api.authorize(API_TOKEN)
    print(f"Authorized: {auth['authorize']['email']}")
    
    # 1. Inspect api.buy
    print("\n--- Inspecting api.buy ---")
    try:
        print(f"Type: {type(api.buy)}")
        print(f"Doc: {api.buy.__doc__}")
        print(f"Args: {api.buy.__code__.co_varnames}")
    except Exception as e:
        print(f"Could not inspect api.buy: {e}")

    # 2. Get Proposal
    print("\n--- Getting Proposal ---")
    proposal_req = {
        "proposal": 1,
        "amount": 5, # Payout 5 (approx cost 2.5)
        "basis": "payout",
        "contract_type": "CALL",
        "currency": "USD",
        "duration": 1,
        "duration_unit": "m",
        "symbol": "R_50"
    }
    
    res = await api.proposal(proposal_req)
    prop = res.get("proposal")
    
    if not prop:
        print("Failed to get proposal")
        return

    prop_id = prop['id']
    ask_price = float(prop['ask_price'])
    print(f"Proposal ID: {prop_id}")
    print(f"Ask Price: {ask_price}")
    
    # 3. Try Buy with Dict and Huge Buffer
    print("\n--- Attempting Buy with Dict (Price=100) ---")
    try:
        # Buffer = 100.0 (Huge) -> Should definitely succeed if parameter is accepted
        buy_req = {"buy": prop_id, "price": 100.0}
        print(f"Sending: {buy_req}")
        
        buy_res = await api.buy(buy_req)
        print(f"Buy Result: {buy_res}")
    except Exception as e:
        print(f"Buy Failed (Dict): {e}")

    # 4. Try Buy with Positional (if above failed)
    # Get new proposal first
    print("\n--- Getting New Proposal for Positional Test ---")
    res = await api.proposal(proposal_req)
    prop = res.get("proposal")
    prop_id = prop['id']
    
    print("\n--- Attempting Buy with Positional (ID, 100) ---")
    try:
        # api.buy(id, price) ?
        buy_res = await api.buy(prop_id, 100.0)
        print(f"Buy Result: {buy_res}")
    except Exception as e:
        print(f"Buy Failed (Positional): {e}")

    await api.clear()

if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(main())
