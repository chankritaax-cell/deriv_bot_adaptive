import os
import re

def clean_file(filepath):
    if not os.path.exists(filepath):
        print(f"File not found: {filepath}")
        return
        
    with open(filepath, 'rb') as f:
        content = f.read()
    
    lines = content.splitlines()
    new_lines = []
    
    for line in lines:
        try:
            decoded = line.decode('utf-8')
            if '#' in decoded:
                base, comment = decoded.split('#', 1)
                if any(ord(c) > 127 for c in comment):
                    v_match = re.search(r'\[v\d+\.\d+\.\d+\]', comment)
                    cleaned_comment = ""
                    if v_match:
                        cleaned_comment = v_match.group(0) + " cleaned"
                    else:
                        cleaned_comment = "comment cleaned"
                    new_lines.append(f"{base.rstrip()} # {cleaned_comment}".encode('utf-8'))
                else:
                    new_lines.append(line)
            else:
                if any(ord(c) > 127 for c in decoded):
                    cleaned_line = "".join([c if ord(c) < 128 else '' for c in decoded])
                    new_lines.append(cleaned_line.encode('utf-8'))
                else:
                    new_lines.append(line)
        except:
            new_lines.append(b'# [Removed corrupted line]')
            
    with open(filepath, 'wb') as f:
        f.write(b'\n'.join(new_lines) + b'\n')
    print(f"Deep Cleaned: {filepath}")

files_to_clean = [
    r'd:\SpProject\deriv_bot_v5_dev\config.py',
    r'd:\SpProject\deriv_bot_v5_dev\bot.py',
    r'd:\SpProject\deriv_bot_v5_dev\modules\ai_council.py',
    r'd:\SpProject\deriv_bot_v5_dev\modules\telegram_bridge.py',
    r'd:\SpProject\deriv_bot_v5_dev\modules\ai_engine.py'
]

for f in files_to_clean:
    clean_file(f)
