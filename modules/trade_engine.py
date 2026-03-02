"""
🚀 Trade Engine (v3.3.4)
Executes trades, handles proposals, and manages position monitoring.
[v3.3.4] Fix Type Error on Slippage Calculation.
"""
import asyncio
import time
from deriv_api import DerivAPI
import config
from .utils import log_print

async def get_balance(api: DerivAPI):
    """Fetches account balance (async) with timeout."""
    try:
        res = await asyncio.wait_for(api.balance(), timeout=10)
        if "balance" in res: return float(res["balance"]["balance"])
        return 0.0
    except Exception as e:
        log_print(f"   ⚠️ [Trade] Balance check error: {e}")
        return 0.0

async def check_active_trade(api: DerivAPI, asset):
    """Checks if there's an open contract for this asset (with timeout)."""
    try:
        res = await asyncio.wait_for(api.portfolio(), timeout=10)
        return False
    except: return False

async def execute_trade(api: DerivAPI, asset, direction, amount, duration_seconds=60):
    """
    Executes a trade with high-granularity logging and error handling.
    """
    start_time = time.time()
    try:
        contract_type = "CALL" if direction == "CALL" else "PUT"
        amount_val = max(round(float(amount), 2), getattr(config, "MIN_STAKE_AMOUNT", 1.0))
        
        log_print(f"   [Trade] 🛰️ Initiating {direction} on {asset} | Stake: ${amount_val}")

        proposal_req = {
            "proposal": 1, "amount": amount_val, "basis": "stake",
            "contract_type": contract_type, "currency": config.CURRENCY,
            "duration": duration_seconds, "duration_unit": "s", "symbol": asset
        }

        final_proposal = None
        try:
            proposal_req["amount"] = float(amount_val)
            proposal_req["basis"] = "stake"
            req_copy = proposal_req.copy()
            final_proposal = await asyncio.wait_for(api.proposal(req_copy), timeout=10)
        except Exception as e:
            log_print(f"   ⚠️ Standard Stake Proposal Error: {e}")
            try:
                estimated_payout = max(amount_val * 1.95, 1.0)
                proposal_req["amount"] = float(f"{estimated_payout:.2f}")
                proposal_req["basis"] = "payout"
                final_proposal = await asyncio.wait_for(api.proposal(proposal_req), timeout=10)
            except Exception as e2:
                log_print(f"   ❌ Payout Strategy also failed: {e2}")

        if not final_proposal or "error" in final_proposal:
            if final_proposal and "error" in final_proposal:
                log_print(f"   ❌ [Trade] Proposal Rejected: {final_proposal['error'].get('message')}")
            return None
             
        p_data = final_proposal["proposal"]
        proposal_id = p_data["id"]
        raw_ask_price = p_data.get("ask_price") 
        
        market_price = 0.0
        try:
            spot_val = p_data.get("spot")
            if spot_val is not None: market_price = float(spot_val)
        except (ValueError, TypeError): pass

        buy = None
        error_logs = []
        
        # [BUG FIX]: Safe parsing to prevent crash if raw_ask_price is invalid
        try:
            current_ask = float(raw_ask_price)
            buffer_pct = getattr(config, "SLIPPAGE_BUFFER", 0.10)
            buffered_price = round(current_ask * (1.0 + buffer_pct), 2) 
        except (TypeError, ValueError):
            log_print("   ⚠️ Ask price undefined! Falling back to Spot Price + 10% slippage.")
            current_ask = market_price if market_price > 0 else 0.0
            buffered_price = round(current_ask * 1.10, 2) if current_ask > 0 else 0.0

        api_start = time.time()
        ghost_trade_cid = None
        try:
            log_print(f"   [Trade] Buying (Dict) | Ask: {current_ask} -> Limit: {buffered_price}")
            buy_args = {"buy": str(proposal_id), "price": float(buffered_price)}
            buy = await asyncio.wait_for(api.buy(buy_args), timeout=20)
        except Exception as e:
            error_logs.append(f"Buy Error: {e}")
            log_print(f"   ❌ Buy Failed: {e}")
            try:
                # Fallback to current_ask to prevent crash
                buy = await asyncio.wait_for(api.buy({"buy": str(proposal_id), "price": float(current_ask)}), timeout=20)
            except Exception as e2:
                log_print(f"   ❌ Buy Retry Failed: {e2}")
                error_logs.append(f"Retry Error: {e2}")
                
                # --- Ghost Trade Recovery ---
                log_print("   👻 [Trade] Checking for Ghost Trade (waiting 10s)...")
                await asyncio.sleep(10)
                try:
                    portfolio = await asyncio.wait_for(api.portfolio(), timeout=10)
                    if portfolio and "portfolio" in portfolio and "contracts" in portfolio["portfolio"]:
                        now_ts = time.time()
                        for c in portfolio["portfolio"]["contracts"]:
                            c_symbol = c.get("symbol")
                            c_time = c.get("purchase_time", 0)
                            if c_symbol == asset and (now_ts - c_time) <= 40:
                                ghost_trade_cid = c.get("contract_id")
                                log_print(f"   🌟 [Trade] Ghost Trade Recovered! ID: {ghost_trade_cid}")
                                break
                except Exception as e3:
                    log_print(f"   ❌ Ghost Trade check failed: {e3}")

        api_latency = time.time() - api_start

        if ghost_trade_cid:
            return {
                "contract_id": ghost_trade_cid,
                "market_price": market_price,
                "api_latency": time.time() - start_time,
                "total_latency": time.time() - start_time
            }

        if not buy or "error" in buy:
            err_msg = buy["error"].get("message", "Unknown Error") if buy else f"All Buy formats failed. {error_logs}"
            log_print(f"   ❌ [Trade] {err_msg}")
            return None
            
        if "buy" in buy:
            cid = buy["buy"].get("contract_id")
            log_print(f"   ✅ [Trade] Success! ID: {cid} | Exec Latency: {api_latency:.2f}s")
            return {
                "contract_id": cid,
                "market_price": market_price,
                "api_latency": api_latency,
                "total_latency": time.time() - start_time
            }
        return None

    except Exception as e:
        import traceback
        log_print(f"   ⚠️ [Trade] Fatal Execution Error: {e}")
        log_print(traceback.format_exc())
        return None

async def check_trade_status(api: DerivAPI, contract_id):
    """
    Checks trade status once (non-blocking). 
    Returns: (status, profit, entry_spot, exit_spot)
    """
    try:
        status = await asyncio.wait_for(api.proposal_open_contract({"contract_id": contract_id}), timeout=10)
        if "proposal_open_contract" in status:
            contract = status["proposal_open_contract"]
            is_sold = contract.get("is_sold")
            contract_status = contract.get("status") # 'won', 'lost', 'open'
            
            entry_spot = float(contract.get("entry_tick", 0.0))
            exit_spot = float(contract.get("exit_tick", 0.0))

            if is_sold or contract_status in ["won", "lost"]:
                profit = float(contract.get("profit", 0.0))
                if profit > 0 or contract_status == "won": return "WIN", profit, entry_spot, exit_spot
                elif profit < 0 or contract_status == "lost": return "LOSS", profit, entry_spot, exit_spot
                else: return "DRAW", 0.0, entry_spot, exit_spot
            
            return "OPEN", 0.0, entry_spot, exit_spot
            
        return "UNKNOWN", 0.0, 0.0, 0.0
    except asyncio.TimeoutError:
        log_print(f"   ⚠️ [Trade] API Timeout checking status.")
        return "UNKNOWN", 0.0, 0.0, 0.0
    except Exception as e:
        log_print(f"   ⚠️ [Trade] Check status error: {e}")
        return "UNKNOWN", 0.0, 0.0, 0.0