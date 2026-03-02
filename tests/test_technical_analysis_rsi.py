
import unittest
import pandas as pd
import sys
import os
import asyncio

# Add parent directory to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from modules.technical_analysis import TechnicalConfirmation

class TestRSI(unittest.TestCase):
    
    def test_rsi_calculation(self):
        """Test RSI calculation with known data."""
        # simple uptrend data
        data = [10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25]
        df = pd.DataFrame({'close': data})
        
        rsi = TechnicalConfirmation.get_rsi(df, period=14)
        print(f"DEBUG: RSI (Uptrend) = {rsi}")
        if rsi is None:
            print("FAILURE: RSI is None")
        elif not (rsi > 70):
            print(f"FAILURE: RSI {rsi} is not > 70")
        self.assertTrue(rsi is not None and rsi > 70, f"RSI should be high in straight uptrend, got {rsi}")

        # simple downtrend data
        data_down = [25, 24, 23, 22, 21, 20, 19, 18, 17, 16, 15, 14, 13, 12, 11, 10]
        df_down = pd.DataFrame({'close': data_down})
        rsi_down = TechnicalConfirmation.get_rsi(df_down, period=14)
        print(f"RSI (Downtrend): {rsi_down}")
        if not (rsi_down < 30):
             print(f"FAILURE: RSI {rsi_down} is not < 30")
        self.assertTrue(rsi_down < 30, f"RSI should be low in straight downtrend, got {rsi_down}")

    def test_confirmation_penalty(self):
        """Test that get_confirmation_score penalizes overbought conditions."""
        # Create Overbought DataFrame (Mocking API)
        data = [10 + i for i in range(50)] # Steady climb
        df = pd.DataFrame({'close': data, 'open': data, 'high': data, 'low': data}) 
        
        rsi = TechnicalConfirmation.get_rsi(df, period=14)
        print(f"RSI (Steady Climb): {rsi}")

        # Test CALL on Overbought
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        score, details = loop.run_until_complete(
            TechnicalConfirmation.get_confirmation_score(None, "MOCK", "CALL", df_1m=df)
        )
        print(f"\n[Overbought CALL] Score: {score}, Details: {details}")
        
        # Should be penalized (score 0.0 or low) because RSI > 75
        self.assertTrue(score == 0.0, f"Score should be 0.0 for Overbought CALL, got {score}")
        self.assertIn("RSI Overbought", str(details))
        
        # Test PUT on Overbought (Should be rewarded)
        score_put, details_put = loop.run_until_complete(
            TechnicalConfirmation.get_confirmation_score(None, "MOCK", "PUT", df_1m=df)
        )
        print(f"[Overbought PUT] Score: {score_put}, Details: {details_put}")
        self.assertTrue(score_put > 0.0, f"Score should be > 0.0 for Overbought PUT, got {score_put}")
        loop.close()

if __name__ == '__main__':
    unittest.main()
