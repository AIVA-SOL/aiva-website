import ast
import os

base = r'C:\tmp_aiva\aiva_bot'
files = ['config.py', 'database.py', 'solana_data.py', 'messages.py', 'main.py']
all_ok = True
for f in files:
    path = os.path.join(base, f)
    try:
        with open(path, encoding='utf-8') as fh:
            ast.parse(fh.read())
        print(f"OK  {f}")
    except SyntaxError as e:
        print(f"ERR {f}: {e}")
        all_ok = False

if all_ok:
    print("\nAll files passed syntax check!")
else:
    print("\nSome files have syntax errors")
