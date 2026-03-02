import asyncio
import os
from deriv_api import DerivAPI
from deriv_bot import config

# Ensure API ID is set
if not os.environ.get("DERIV_APP_ID"):
    os.environ["DERIV_APP_ID"] = "1089"

async def check_min_stake():
    api = DerivAPI(app_id=config.DERIV_APP_ID)
    
    try:
        symbol = "1HZ100V" # R_100
        print(f"I: Checking Contract Limits for {symbol}...")
        
        # Fetch contracts for the symbol
        contracts = await api.contracts_for({
            "contracts_for": symbol,
            "currency": "USD",
            "landing_company": "svg", # best guess for demo/general
            "product_type": "basic"
        })
        
        if "contracts_for" in contracts:
            available = contracts["contracts_for"]["available"]
            print(f"I: Found {len(available)} contract types.")
            
            for c in available:
                # We are interested in CALL/PUT (rise/fall)
                if c["contract_category"] == "callput":
                    c_type = c["contract_type"]
                    name = c["contract_display"]
                    min_stake = c.get("min_contract_measure", "N/A")
                    min_duration = c.get("min_contract_duration", "N/A")
                    
                    # Some responses might have 'min_stake' directly or inside a limit structure
                    # Let's print the whole relevant dict for the first match to be sure
                    if c_type == "CALL":
                         print(f"\n--- {name} ({c_type}) ---")
                         print(c)
        
        else:
            print("E: No contracts returned.")
            
    except Exception as e:
        print(f"E: Error: {e}")
    finally:
        await api.disconnect()

if __name__ == "__main__":
    asyncio.run(check_min_stake())
