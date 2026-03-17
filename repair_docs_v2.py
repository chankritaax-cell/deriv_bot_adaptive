import sys

def fix_mixed_content(filename):
    try:
        # Read raw bytes
        with open(filename, 'rb') as f:
            raw = f.read()

        # If it was double-encoded:
        # Original Thai (3 bytes) -> Decoded as latin-1 -> Encoded as UTF-8 (6 bytes)
        # We want to go back to 3 bytes.
        
        # Method: Attempt to decode as UTF-8. 
        # Then, for all characters that look like start of Thai mojibake,
        # try to re-collapse them.
        
        text = raw.decode('utf-8')
        
        # Standard Mojibake Pattern: 
        # à (0xE0) + ¸ (0xB8) + char -> Should have been 3-byte Thai char
        # This is a very common pattern where CP1252/Latin1 was used.
        
        # Let's try to encode the whole string into bytes as latin-1, 
        # but skip characters that can't be encoded. (This recovers the original bytes for mojibake)
        # Then decode those bytes as UTF-8.
        
        fixed_bytes = bytearray()
        i = 0
        while i < len(text):
            char = text[i]
            # If the character is in the range of mojibake sources (à¸ à¸²à¸£...)
            # or if it's the detector character 'à' (0xE0)
            if ord(char) < 256:
                fixed_bytes.append(ord(char))
                i += 1
            else:
                # This character is likely a correctly decoded multi-byte char (like Emoji)
                # We should encode it as UTF-8 directly and append it.
                fixed_bytes.extend(char.encode('utf-8'))
                i += 1
        
        # Now fixed_bytes contains the "raw" bytes. 
        # If it was double encoded, these bytes will decode back to the original UTF-8.
        # If it was triple encoded (rare), we might need another pass.
        
        # Try to decode the resulting bytes as UTF-8.
        final_text = fixed_bytes.decode('utf-8', errors='replace')
        
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(final_text)
        print(f"Fixed {filename}")

    except Exception as e:
        print(f"Error repairing {filename}: {e}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        fix_mixed_content(sys.argv[1])
