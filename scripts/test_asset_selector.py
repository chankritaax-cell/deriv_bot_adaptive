
import asyncio
import os
import sys

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from deriv_api import DerivAPI
from modules.asset_selector import AssetSelector

async def test_selector():
    print("🚀 Starting Asset Selector Test...")
    
    api = DerivAPI(app_id=config.DERIV_APP_ID)
    
    try:
        print("🔐 Authorizing...")
        await api.authorize(config.DERIV_API_TOKEN)
        
        print("🔍 Scanning Assets (Last 12h)...")
        best_asset, best_wr, details = await AssetSelector.find_best_asset(api, lookback_hours=12, min_trades=5)
        
        print("\n" + "="*40)
        print(f"🏆 Best Asset: {best_asset}")
        print(f"📈 Win Rate:   {best_wr:.1f}%")
        print("="*40)
        
        print("\nAll Candidates:")
        for c in details:
            print(f" - {c['asset']}: {c['wr']:.1f}% ({c['trades']} trades)")
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await api.disconnect()

if __name__ == "__main__":
    asyncio.run(test_selector())
