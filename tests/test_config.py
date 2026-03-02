import unittest
import os
import sys

# Add parent directory to path to import modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config

class TestConfig(unittest.TestCase):
    def test_load_env_file(self):
        # Create a dummy .env file
        with open("test.env", "w") as f:
            f.write("TEST_KEY=12345\n")
        
        # Mocking the path in config might be hard without dependency injection,
        # but we can test if the function runs without error
        try:
            config.load_env_file()
        except Exception as e:
            self.fail(f"load_env_file raised Exception: {e}")
        finally:
            if os.path.exists("test.env"):
                os.remove("test.env")

    def test_tiered_profiles(self):
        self.assertIn("TIER_1", config.PROFILES)
        self.assertIn("TIER_2", config.PROFILES)
        self.assertIn("TIER_MICRO", config.PROFILES)
        
        micro = config.PROFILES["TIER_MICRO"]
        self.assertEqual(micro["MARTINGALE_MULTIPLIER"], 1.0)
        
    def test_assets_list(self):
        self.assertTrue(len(config.ASSETS_VOLATILITY) > 0)
        self.assertIn("1HZ100V", config.ASSETS_VOLATILITY)

if __name__ == "__main__":
    unittest.main()
