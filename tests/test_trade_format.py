import sys
# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    print("⚠️ python-dotenv not found, skipping load_dotenv()")

from deriv_api import DerivAPI

APP_ID = os.getenv("DERIV_APP_ID", "1089")
TOKEN = os.getenv("DERIV_API_TOKEN")

async def test():
    if not TOKEN:
        print("❌ No Token found in .env")
        return

    api = DerivAPI(app_id=APP_ID)
    try:
        await api.authorize(TOKEN)
        print("✅ Authorized")

        asset = "R_100" # Use a very common one
        
        # 1. Try Proposal
        req = {
            "proposal": 1,
            "amount": 0.5,
            "basis": "stake",
            "contract_type": "CALL",
            "currency": "USD",
            "duration": 60,
            "duration_unit": "s",
            "symbol": asset
        }
        print(f"📡 Sending Proposal: {req}")
        res = await api.proposal(req)
        
        if "error" in res:
            print(f"❌ Proposal Error: {res['error']['message']}")
            return

        p_id = res["proposal"]["id"]
        ask_price = res["proposal"]["ask_price"]
        print(f"✅ Proposal Success: ID={p_id}, Price={ask_price}")

        # 2. Test BUY formats
        print("\n--- Test 1: Dictionary Format ---")
        try:
            buy_res = await api.buy({"buy": p_id, "price": ask_price})
            print(f"Result: {buy_res}")
        except Exception as e:
            print(f"Caught Exception: {type(e).__name__}: {e}")

        print("\n--- Test 2: Positional Format ---")
        try:
            buy_res = await api.buy(p_id, ask_price)
            print(f"Result: {buy_res}")
        except Exception as e:
            print(f"Caught Exception: {type(e).__name__}: {e}")

    finally:
        await api.disconnect()

if __name__ == "__main__":
    asyncio.run(test())
