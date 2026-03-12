import os

settings_path = 'erp_lacteo/settings/base.py'
with open(settings_path, 'r', encoding='utf-8') as f:
    text = f.read()

if '"apps.bancos"' not in text:
    text = text.replace('"apps.produccion",', '"apps.produccion",\n    "apps.bancos",')
    with open(settings_path, 'w', encoding='utf-8') as f:
        f.write(text)
    print("Added apps.bancos to settings")
