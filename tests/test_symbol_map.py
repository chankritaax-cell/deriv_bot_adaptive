import asyncio
import os
from deriv_api import DerivAPI
from dotenv import load_dotenv

load_dotenv()

APP_ID = os.getenv("DERIV_APP_ID", "1089")

async def test():
    api = DerivAPI(app_id=APP_ID)
    try:
        print("Fetching Active Symbols...")
        req = {"active_symbols": "brief", "product_type": "basic"}
        res = await api.active_symbols(req)
        
        symbols = res.get("active_symbols", [])
        print(f"Found {len(symbols)} symbols.")
        
        # Check a few examples
        targets = ["R_100", "1HZ10V", "R_50"]
        for s in symbols:
            if s["symbol"] in targets:
                print(f"Symbol: {s['symbol']} -> Display: {s.get('display_name', 'N/A')}")
                
    finally:
        await api.disconnect()

if __name__ == "__main__":
    asyncio.run(test())
