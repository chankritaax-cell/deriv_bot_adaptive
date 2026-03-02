import unittest
import pandas as pd
import sys
import os

# Add the project root to sys.path to import modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.market_engine import candles_to_df

class TestNewCandleDetection(unittest.TestCase):
    def test_candles_to_df_indexing(self):
        # Sample candles list
        sample_candles = [
            {"epoch": 1708391220, "open": "2100.5", "high": "2105.0", "low": "2100.0", "close": "2104.2"},
            {"epoch": 1708391280, "open": "2104.2", "high": "2106.5", "low": "2103.5", "close": "2105.8"},
        ]
        
        # Transform to DF
        df = candles_to_df(sample_candles)
        
        # 1. Assert "timestamp" column exists
        self.assertIn("timestamp", df.columns)
        
        # 2. Assert index is the timestamp
        self.assertEqual(df.index.name, "timestamp")
        
        # 3. Assert values are correct and types are correct
        last_ts = 1708391280
        self.assertEqual(int(df.index[-1]), last_ts)
        self.assertEqual(int(df["timestamp"].iloc[-1]), last_ts)
        
        # 4. Check values and presence
        self.assertEqual(int(df["timestamp"].iloc[-1]), last_ts)
        self.assertTrue(pd.api.types.is_numeric_dtype(df["close"]))
        self.assertTrue(pd.api.types.is_integer_dtype(df["timestamp"]))
        
    def test_empty_candles(self):
        df = candles_to_df([])
        self.assertTrue(df.empty)

if __name__ == "__main__":
    unittest.main()
