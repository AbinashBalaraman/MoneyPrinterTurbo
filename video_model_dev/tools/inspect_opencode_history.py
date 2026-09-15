import sqlite3
import json
from pathlib import Path

db = Path(r"C:\Users\SATHYA TRADERS\.local\share\opencode\opencode.db")
con = sqlite3.connect(db)
cur = con.cursor()

for row in cur.execute("SELECT id, session_id, data FROM part WHERE data LIKE '%jump_run%' ORDER BY id DESC LIMIT 15"):
    raw = row[2]
    try:
        obj = json.loads(raw)
        text = str(obj)
    except:
        text = raw
    print(f"=== PART {row[0]} SESSION {row[1]} ===")
    for line in text.splitlines():
        if any(k in line.lower() for k in ["jump_run", "out_file", "render_stage", "choreographer", "python"]):
            print("  ", line[:150])
