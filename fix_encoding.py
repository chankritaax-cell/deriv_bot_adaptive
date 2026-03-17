import sys

def fix_mojibake(filename):
    try:
        with open(filename, 'rb') as f:
            content = f.read()
        
        # Try to decode as latin-1 (which preserves bytes) and encode as utf-8 if it was originally utf-8 but read wrong
        # However, usually the file on disk IS utf-8 but has been double encoded or something.
        # Let's try to detect if it's currently utf-8 but contains mojibake.
        
        # If it's already utf-8, but the characters are like 'à¸ à¸²à¸£', 
        # that means the bytes for Thai (e.g., 0xE0 0xB8 0x81) were treated as individual chars.
        
        text = content.decode('utf-8')
        # Standard mojibake fix: text.encode('latin-1').decode('utf-8')
        fixed = text.encode('latin-1').decode('utf-8')
        
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(fixed)
        print(f"Fixed {filename}")
    except Exception as e:
        print(f"Error fixing {filename}: {e}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        fix_mojibake(sys.argv[1])
