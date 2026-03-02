import asyncio
import os
import sys
# Add parent directory to path to import modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from deriv_api import DerivAPI
import config
from modules import market_engine

async def test():
    print("🚀 Testing market_engine.get_market_summary_for_ai()...")
    api = DerivAPI(app_id=config.DERIV_APP_ID)
    
    try:
        auth = await api.authorize(config.DERIV_API_TOKEN)
        if "error" in auth:
            print(f"❌ Auth Error: {auth['error']['message']}")
            return

        # Pick an active asset
        asset = "1HZ10V" 
        print(f"🔎 Asset: {asset}")
        
        summary = await market_engine.get_market_summary_for_ai(api, asset)
        print("\n📝 Result Summary String:")
        print("-" * 40)
        print(summary)
        print("-" * 40)
        
        if "RSI" in summary and "N/A" not in summary:
            print("✅ Indicators verified present and calculated.")
        else:
            print("⚠️ Indicators missing or N/A.")
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await api.disconnect()

if __name__ == "__main__":
    asyncio.run(test())
