import os
import re

directories = ['apps/', 'erp_lacteo/']
files_to_visit = ['manage.py']

for d in directories:
    for root, _, files in os.walk(d):
        for file in files:
            if file.endswith('.py'):
                files_to_visit.append(os.path.join(root, file))

for path in files_to_visit:
    if not os.path.exists(path):
        continue
    with open(path, 'r', encoding='latin-1') as f:
        content = f.read()
    
    # Check if the text contains non-ascii characters
    has_non_ascii = any(ord(c) > 127 for c in content)
    
    # Check if it already has the encoding declaration
    lines = content.split('\n')
    has_encoding = False
    if len(lines) > 0 and 'coding: utf-8' in lines[0].lower():
        has_encoding = True
    elif len(lines) > 1 and 'coding: utf-8' in lines[1].lower():
        has_encoding = True
        
    if has_non_ascii and not has_encoding:
        content = '# -*- coding: utf-8 -*-\n' + content
        
    # Write it back as utf-8
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
        
print("Conversion complete.")

# Update settings
settings_path = 'erp_lacteo/settings/base.py'
with open(settings_path, 'r', encoding='utf-8') as f:
    content = f.read()
    
if 'DEFAULT_CHARSET' not in content:
    content += "\nDEFAULT_CHARSET = 'utf-8'\n"
    with open(settings_path, 'w', encoding='utf-8') as f:
        f.write(content)
        
print("Settings updated.")
