import os

def clean_file(filepath):
    with open(filepath, 'rb') as f:
        content = f.read()
    
    lines = content.splitlines()
    new_lines = []
    
    for line in lines:
        try:
            decoded = line.decode('utf-8')
            if '#' in decoded:
                base, comment = decoded.split('#', 1)
                # Check if comment has non-ascii
                if any(ord(c) > 127 for c in comment):
                    # Clean the comment: keep only parts that look like version tags or common english
                    # Or just strip it if it's mostly garbled
                    # Let's try to keep useful version tags [vX.X.X]
                    import re
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
                # For non-comment lines, if they have garbled characters, we should probably keep the code but clean the garbled part
                if any(ord(c) > 127 for c in decoded):
                    cleaned_line = "".join([c if ord(c) < 128 else '' for c in decoded])
                    new_lines.append(cleaned_line.encode('utf-8'))
                else:
                    new_lines.append(line)
        except:
            new_lines.append(b'# [Removed corrupted line]')
            
    with open(filepath, 'wb') as f:
        f.write(b'\n'.join(new_lines) + b'\n')

clean_file(r'd:\SpProject\deriv_bot_v5_dev\config.py')
print("Deep Cleaned config.py")
