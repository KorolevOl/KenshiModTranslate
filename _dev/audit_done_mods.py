"""Какие уже переведённые моды содержат непереведённые (эхо) строки.

Сводит hash из state/ к имени мода в workshop, показывает долю эха.
"""
import json, os, glob, re, sys
sys.path.insert(0, r"H:\KenshiModTranslate")
os.chdir(r"H:\KenshiModTranslate")

# --- injected by move_to_dev: let us import core modules from parent ---
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
# --- end injected prologue ---

import validate_translation as v

# map hash -> mod name via workshop
workshop = r"E:\steamlibrary\steamapps\workshop\content\233860"
mod_by_hash = {}
for d in os.listdir(workshop):
    p = os.path.join(workshop, d)
    if not d.isdigit() or not os.path.isdir(p):
        continue
    for f in os.listdir(p):
        if f.lower().endswith(".mod"):
            full = os.path.join(p, f)
            if not os.path.isfile(full):
                continue
            import hashlib
            h = hashlib.md5(open(full, "rb").read()).hexdigest()[:12]
            name = None
            info = [x for x in os.listdir(p) if x.startswith("_") and x.endswith(".info")]
            if info:
                m = re.search(r"<name>(.*?)</name>", open(os.path.join(p, info[0]), encoding="utf-8", errors="replace").read(), re.DOTALL)
                if m: name = m.group(1).strip()
            mod_by_hash[h] = (name or f[:-4], d)

rows = []
for efile in glob.glob(r"state\*_entries.json"):
    h = os.path.basename(efile).split("_entries")[0]
    mfile = os.path.join("state", h + "_mapping.json")
    if not os.path.exists(mfile): continue
    entries = json.load(open(efile, encoding="utf-8"))
    done = {str(x["i"]): x["ru"] for x in json.load(open(mfile, encoding="utf-8"))}
    a = v.audit_map(entries, done)
    if a["echo"] or a["latin"] or a["empty"]:
        name, wid = mod_by_hash.get(h, ("?", "?"))
        rows.append((name, wid, len(entries), a["echo"], a["latin"], a["empty"]))

rows.sort(key=lambda r: -(r[3] + r[4] + r[5]))
print(f"{'mod':44} {'wid':>11} {'tot':>5} {'эхо':>4} {'латынь':>7} {'пусто':>6}")
for name, wid, tot, echo, latin, empty in rows[:25]:
    print(f"{name[:44]:44} {wid:>11} {tot:>5} {echo:>4} {latin:>7} {empty:>6}")
print(f"\nвсего модов с несоответствием: {len(rows)}")
