import sys
import re

def fix_mojibake(filename):
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            content = f.read()

        # This regex matches sequences of Latin-1 / CP1252 characters typically found in mojibake.
        # It specifically looks for characters in the range \u0080 to \u00FF.
        # These are the ones that were likely UTF-8 bytes treated as individual chars.
        
        def repair_sequence(match):
            seq = match.group(0)
            try:
                # Try to encode back to bytes using Windows-1252 (which covers the full mojibake range better than Latin-1)
                # then decode those bytes as UTF-8.
                return seq.encode('cp1252').decode('utf-8')
            except (UnicodeEncodeError, UnicodeDecodeError):
                # If we can't fix the whole sequence at once, try to fix it char-by-char or just return as is
                # Usually, if it's mojibake, the whole sequence needs to be collapsed.
                # If it fails, it might be a mix of valid UTF-8 and mojibake?
                # Let's try to be a bit more granular if it fails.
                result = []
                temp = ""
                for char in seq:
                    temp += char
                    try:
                        # If we have enough bytes for a valid UTF-8 char, append it.
                        candidate = temp.encode('cp1252').decode('utf-8')
                        result.append(candidate)
                        temp = ""
                    except UnicodeEncodeError:
                        # Character not in CP1252? Should be rare for mojibake.
                        result.append(temp)
                        temp = ""
                    except UnicodeDecodeError:
                        # Not enough bytes yet, or invalid UTF-8 sequence. Continue gathering.
                        if len(temp) > 4: # Thai/Emoji are max 4 bytes.
                            result.append(temp[0])
                            temp = temp[1:]
                return "".join(result) + temp

        # Match sequences of one or more non-ASCII characters in the Latin-1 range.
        fixed_content = re.sub(r'[\u0080-\u00FF]+', repair_sequence, content)

        # One more pass to fix some very specific garbled characters that might have been hit twice
        # or missed by the first pass if they contain non-Latin1 chars (rare but possible).
        
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(fixed_content)
        print(f"Repaired {filename}")
        
    except Exception as e:
        print(f"Error repairing {filename}: {e}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        fix_mojibake(sys.argv[1])
