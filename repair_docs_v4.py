import sys

def fix_doubled_prefix(filename):
    try:
        with open(filename, 'rb') as f:
            raw = f.read()

        # Phase 1: If it's already UTF-8 with mojibake characters, 
        # we need to convert it to the "raw" byte stream.
        # Characters like 'à' (U+00E0) should be treated as byte 0xE0.
        # Characters like 'ก' (U+0E01) should be treated as their UTF-8 bytes (E0 B8 81).
        
        text = raw.decode('utf-8', errors='replace')
        
        reconstructed = bytearray()
        for char in text:
            cp = ord(char)
            if cp <= 255:
                reconstructed.append(cp)
            else:
                # This char is already decoded (Thai, Emoji, etc.)
                # Encode it back to UTF-8 bytes
                reconstructed.extend(char.encode('utf-8'))

        # Phase 2: De-duplicate the Thai UTF-8 prefixes (E0 B8 and E0 B9)
        # This fixes cases where 'ก' (E0 B8 81) became 'à¸ ก' (E0 B8 E0 B8 81)
        
        # We look for E0 B8 E0 B8 and replace with E0 B8
        # We look for E0 B9 E0 B9 and replace with E0 B9
        
        def deduplicate(data):
            i = 0
            result = bytearray()
            while i < len(data):
                # Check for E0 B8 E0 B8
                if i + 3 < len(data) and data[i] == 0xE0 and data[i+1] == 0xB8 and data[i+2] == 0xE0 and data[i+3] == 0xB8:
                    result.append(0xE0)
                    result.append(0xB8)
                    i += 4
                # Check for E0 B9 E0 B9
                elif i + 3 < len(data) and data[i] == 0xE0 and data[i+1] == 0xB9 and data[i+2] == 0xE0 and data[i+3] == 0xB9:
                    result.append(0xE0)
                    result.append(0xB9)
                    i += 4
                # Check for E0 B8 E0 B9 (mixed, usually first one is redundant)
                elif i + 3 < len(data) and data[i] == 0xE0 and data[i+1] == 0xB8 and data[i+2] == 0xE0 and data[i+3] == 0xB9:
                    result.append(0xE0)
                    result.append(0xB9)
                    i += 4
                else:
                    result.append(data[i])
                    i += 1
            return result

        # Apply de-duplication twice to catch triple encoding if any
        processed = deduplicate(reconstructed)
        processed = deduplicate(processed)
        
        final_text = processed.decode('utf-8', errors='replace')
        
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(final_text)
        print(f"Fixed {filename}")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        fix_doubled_prefix(sys.argv[1])
