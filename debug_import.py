import sys
import os

print("Current sys.path:", sys.path)
print("Current CWD:", os.getcwd())

try:
    print("Attempting to import modules.ai_engine...")
    from modules import ai_engine
    print("Successfully imported modules.ai_engine")
except ImportError as e:
    print(f"Failed to import modules.ai_engine: {e}")
except Exception as e:
    print(f"An error occurred during import: {e}")
