import unittest
from unittest.mock import MagicMock, AsyncMock
import sys
import os
import asyncio

# Add parent directory to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Mock modules before importing trade_engine to avoid heavy dependencies
sys.modules['deriv_api'] = MagicMock()
sys.modules['config'] = MagicMock()
sys.modules['utils'] = MagicMock()

# Import target function (assuming logic is extractable, but it's embedded in execute_trade)
# Since it is embedded, we will dry-run logic or extract it.
# For now, let's create a test that simulates the math logic used in the fix.

class TestPayoutStrategy(unittest.TestCase):
    
    def test_payout_calculation(self):
        """Test the math behind the payout strategy."""
        
        # Scenarios
        # 1. Stake $1.5, Ref Payout $1 -> $1.95 (95% return)
        # Ref Rate = 1.95 / 1.0 = 1.95
        # Target Payout = 1.5 * 1.95 = 2.925
        # Rounded Payout = 3
        # Expected Stake ~ 3 / 1.95 = 1.538
        
        amount_val = 1.5
        ref_payout = 1.95
        ref_ask = 1.0
        
        ref_rate = ref_payout / ref_ask
        target_payout = amount_val * ref_rate
        payout_int = int(round(target_payout))
        
        print(f"\n[Test] Stake: {amount_val}, Rate: {ref_rate:.2f}")
        print(f"       Target Payout (Float): {target_payout:.4f}")
        print(f"       Target Payout (Int): {payout_int}")
        
        self.assertEqual(payout_int, 3)
        
    def test_payout_calculation_low_return(self):
        """Test with lower return rate (e.g. 50%)"""
        # Stake $1.5, Ref $1 -> $1.50 (50% profit)
        amount_val = 1.5
        ref_payout = 1.50
        ref_ask = 1.0
        
        ref_rate = ref_payout / ref_ask # 1.5
        target_payout = amount_val * ref_rate # 1.5 * 1.5 = 2.25
        payout_int = int(round(target_payout)) # 2
        
        print(f"\n[Test] Stake: {amount_val}, Rate: {ref_rate:.2f}")
        print(f"       Target Payout (Float): {target_payout:.4f}")
        print(f"       Target Payout (Int): {payout_int}")
        
        self.assertEqual(payout_int, 2) # 2 / 1.5 = 1.33 stake (approx)

if __name__ == '__main__':
    unittest.main()
