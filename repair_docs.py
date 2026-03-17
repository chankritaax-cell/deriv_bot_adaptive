import sys
import re

def fix_mixed_mojibake(filename):
    try:
        # Read the file as UTF-8
        with open(filename, 'r', encoding='utf-8') as f:
            content = f.read()

        # Regex to find mojibake patterns specifically seen in the logs:
        # à¸ followed by other characters that indicate mis-encoded Thai
        # Thai range in UTF-8 starts with 0xE0 0xB8... which in latin-1 is à¸
        
        def repair_match(match):
            mojibake = match.group(0)
            try:
                # Convert the mojibake string back to bytes as if it was latin-1
                # then decode those bytes as UTF-8 to get the real Thai
                return mojibake.encode('latin-1').decode('utf-8')
            except:
                return mojibake

        # This regex looks for sequences starting with à¸ or à¹ (Thai common prefixes in mojibake)
        # followed by other characters that usually accompany it.
        # Thai UTF-8 is 3-byte. In latin-1:
        # 0xE0 = à
        # 0xB8 = ¸
        # 0xB9 = ¹
        fixed_content = re.sub(r'à¸[^\s]+|à¹[^\s]+', repair_match, content)

        with open(filename, 'w', encoding='utf-8') as f:
            f.write(fixed_content)
        print(f"Repaired {filename}")
        
    except Exception as e:
        print(f"Error repairing {filename}: {e}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        fix_mixed_mojibake(sys.argv[1])
