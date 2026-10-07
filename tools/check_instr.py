import re
with open(r"C:\Users\frank\Documents\Projekte\pc bediener\src\pcbediener\mcp_server.py", "r", encoding="utf-8") as f:
    txt = f.read()
m = re.search(r'INSTRUCTIONS\s*=\s*"""(.*?)(""")', txt, re.DOTALL)
if m:
    block = m.group(1)
    for i, line in enumerate(block.split("\n"), 1):
        print(f"{i:3}|{line}|")
else:
    print("NICHT GEFUNDEN")
