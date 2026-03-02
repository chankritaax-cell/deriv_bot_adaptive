import unittest
import os
import sys
import json
import time

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.utils import log_print

class TestUtils(unittest.TestCase):
    def test_log_print(self):
        # We just want to ensure it doesn't crash
        try:
            log_print("Test message")
        except Exception as e:
            self.fail(f"log_print raised Exception: {e}")

if __name__ == "__main__":
    unittest.main()
