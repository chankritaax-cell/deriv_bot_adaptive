import sys
import os
import asyncio
# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from deriv_api import DerivAPI
from modules import market_engine
# import ai_engine # Uncomment to test AI logic

async def test():
    print("🔥 Testing Deriv Connection...")
    print(f"   App ID: {config.DERIV_APP_ID}")
    print(f"   Token: {config.DERIV_API_TOKEN[:5]}...")
    
    api = DerivAPI(app_id=config.DERIV_APP_ID)
    
    try:
        # 1. Authorize
        print("\n🔐 Authorizing...")
        authorize = await api.authorize(config.DERIV_API_TOKEN)
        if "error" in authorize:
            print(f"   ❌ Failed: {authorize['error']['message']}")
            return
        print(f"   ✅ Success. Balance: {authorize['authorize']['balance']} {authorize['authorize']['currency']}")
        
        # 2. Scan Assets
        print("\n🔎 Scanning Assets (Market Engine)...")
        assets = await market_engine.scan_open_assets(api)
        print(f"   ✅ Found {len(assets)} assets: {assets}")
        
        if assets:
            asset = assets[0][0]
            print(f"\n🕯️ Fetching Candles for {asset}...")
            df = await market_engine.get_candles_df(api, asset, 50, 60)
            if df is not None:
                print(f"   ✅ Got {len(df)} candles.")
                print(f"   Last Close: {df.iloc[-1]['close']}")
                
                # Test Analysis
                print("\n🧠 Testing AI Analysis Summary...")
                summary = await market_engine.get_market_summary_for_ai(api, asset)
                print(f"   ✅ Summary: {summary}")
            else:
                print("   ❌ Failed to get candles.")
                
    except Exception as e:
        print(f"❌ Exception: {e}")
    finally:
        # await api.disconnect()
        pass

if __name__ == "__main__":
    try:
        asyncio.run(test())
    except KeyboardInterrupt:
        pass
