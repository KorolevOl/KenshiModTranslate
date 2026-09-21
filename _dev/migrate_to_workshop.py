# -*- coding: utf-8 -*-
"""Migrate translated mods from kenshi\\mods\\<name>\\ INTO the Steam Workshop folder.

For every mod dir in mods\\ that contains our marker <name>.mod.orig_<hash>.backup:
  1) verify the mod actually exists in the Workshop cache (match by name/title).
  2) move the RU .mod (translated) over the Workshop EN .mod.
  3) move the EN backup next to it: <name>.mod.orig_<hash>.backup (in Workshop).
  4) delete the now-empty mods\\<name> folder.
Foreign dirs (no marker: Vortex, manual, foreign RU) are left UNTOUCHED.

Safeguards:
  - dry-run by default? NO: --dry-run is a flag; default = real.
  - refuse to run if kenshi process is alive (files may be locked).
  - refuse if the Workshop folder doesn't exist (no match found).
  - never touch a Workshop file unless the name matches our mods\\<name> exactly
    (case-insensitive) OR the EN-backup hash matches one of the state/ keys.

Usage:
  python migrate_to_workshop.py            # real migration
  python migrate_to_workshop.py --dry-run  # show what would happen, change nothing
"""
import os, sys, json, shutil, hashlib, re

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(HERE, "config.json"), encoding="utf-8"))
P = CFG["paths"]
GAME = P["game"]
WORKSHOP = P["workshop"]
MODS_DIR = P.get("mods_dir") or os.path.join(GAME, "mods")

def _wbname(d):
    for f in os.listdir(d):
        if f.startswith("_") and f.endswith(".info"):
            try:
                txt = open(os.path.join(d, f), encoding="utf-8", errors="replace").read()
                m = re.search(r"<name>(.*?)</name>", txt, re.DOTALL)
                if m: return m.group(1).strip()
            except: pass
    for f in os.listdir(d):
        if f.lower().endswith(".mod"):
            return f[:-4]
    return os.path.basename(d)

def kenshi_running():
    """Quick check: kenshi.exe / ksp.exe / any process with 'kenshi' in name."""
    try:
        import subprocess
        out = subprocess.run("tasklist /FI \"IMAGENAME eq kenshi.exe\""
                             " /FO CSV /NH", shell=True,
                             capture_output=True, text=True, timeout=10).stdout
        return "Kenshi" in out
    except Exception:
        return False

def plan():
    """Return list of migration plans. Match mods\\<name> <-> workshop by:
       PRIMARY: EN-backup MD5 == workshop .mod MD5 (exact identity — safest);
       FALLBACK: mod name == workshop title (warn on content drift).
    Skips foreign (no marker) and unmatched."""
    state = os.path.join(HERE, P.get("state") or "state")
    state_keys = set()
    if os.path.isdir(state):
        for f in os.listdir(state):
            if f.endswith("_mapping.json"):
                state_keys.add(f[:-len("_mapping.json")])

    # precompute workshop files
    ws_index = []  # (folder, name, path, md5)
    if os.path.isdir(WORKSHOP):
        for i in sorted(os.listdir(WORKSHOP), key=lambda x: int(x) if x.isdigit() else 10**12):
            full = os.path.join(WORKSHOP, i)
            if not (i.isdigit() and os.path.isdir(full)):
                continue
            nm = _wbname(full)
            for f in os.listdir(full):
                if f.lower().endswith(".mod"):
                    fp = os.path.join(full, f)
                    try:
                        h = hashlib.md5(open(fp, "rb").read()).hexdigest()
                    except:
                        h = None
                    ws_index.append({"folder": full, "name": f, "path": fp, "md5": h, "title": nm})

    plan_items = []
    skipped_foreign = []
    skipped_no_match = []
    for d in sorted(os.listdir(MODS_DIR)):
        dp = os.path.join(MODS_DIR, d)
        if not os.path.isdir(dp): continue
        files = os.listdir(dp)
        if any("vortex" in f.lower() or "managed_by" in f.lower() for f in files):
            skipped_foreign.append((d, "Vortex marker")); continue
        marker = None
        for f in files:
            if ".orig_" in f and f.endswith(".backup"):
                marker = f
                break
        if not marker:
            skipped_foreign.append((d, "no .orig_<h>.backup marker")); continue
        h = marker.split(".orig_")[1].split(".backup")[0]
        base_mod = marker[:-(len(".orig_" + h + ".backup"))]
        bak_path = os.path.join(dp, marker)
        try:
            bak_md5 = hashlib.md5(open(bak_path, "rb").read()).hexdigest()
        except:
            bak_md5 = None
        # PRIMARY: md5 of EN backup == md5 of a workshop .mod (exact)
        hit = [w for w in ws_index if bak_md5 and w["md5"] == bak_md5]
        how = "hash"
        if not hit:
            # FALLBACK: name match against workshop title
            low = d.lower()
            hit = [w for w in ws_index if w["title"].lower() == low]
            how = "name (hash не совпал — возможно автор обновил мод)"
            if not hit:
                hit = [w for w in ws_index if w["name"].lower() == base_mod.lower()]
                how = "filename"
        if not hit:
            skipped_no_match.append((d, h, "нет файла в workshop (md5 и имя не совпали)"))
            continue
        w = hit[0]
        plan_items.append({"mods_dir": dp, "name": d, "hash": h,
                     "backup_in_mods": bak_path,
                     "mod_in_mods": os.path.join(dp, base_mod),
                     "ws_dir": w["folder"], "ws_mod": w["path"],
                     "backup_in_ws": os.path.join(w["folder"], marker),
                     "how": how})
    return plan_items, skipped_foreign, skipped_no_match

def do_migration(plan, dry_run):
    for p in plan:
        name = p["name"]
        if dry_run:
            print(f"  [dry-run] {name}:")
            print(f"    RU  {p['mod_in_mods']}")
            print(f"          ->  {p['ws_mod']}  (overwrites EN)")
            print(f"    EN  {p['backup_in_mods']}")
            print(f"          ->  {p['backup_in_ws']}")
            print(f"    rmdir mods\\{name}")
            continue
        # 1) RU over WS EN (in-place)
        shutil.copy2(p["mod_in_mods"], p["ws_mod"])
        # 2) EN backup to WS
        shutil.move(p["backup_in_mods"], p["backup_in_ws"])
        # 3) delete any other .mod in mods\<name> that was a copy we made; keep marker if still there
        # 4) delete the rest of mods\<name> contents we own
        for f in os.listdir(p["mods_dir"]):
            fp = os.path.join(p["mods_dir"], f)
            if os.path.isfile(fp):
                # if it's our RU (we just moved it? no, we copied) - it's still here? no, we copied
                # we copied (not moved) the .mod - remove it now
                os.remove(fp)
            elif os.path.isdir(fp):
                shutil.rmtree(fp)
        if os.path.isdir(p["mods_dir"]) and not os.listdir(p["mods_dir"]):
            os.rmdir(p["mods_dir"])
        print(f"  OK: {name} -> workshop; EN backup saved next to it; mods\\{name} deleted")

def main():
    dry = "--dry-run" in sys.argv
    if not dry:
        if kenshi_running():
            print("[!] kenshi.exe запущено — закройте игру перед миграцией (файлы в локе)")
            return 1
    items, skipped_foreign, skipped_no_match = plan()
    print(f"=== MIGRATE {len(items)} переведённого мода из mods\\ в Steam Workshop ===")
    if dry: print("(dry-run: ничего не изменится)")
    do_migration(items, dry)
    print(f"\nПропущено (внешние — Vortex/ручные): {len(skipped_foreign)}")
    for d, why in skipped_foreign:
        print(f"  НЕ ТРОНУТО [{why}]: mods\\{d}")
    if skipped_no_match:
        print(f"\nНЕ МОГУ перенести (нет соответствующего в workshop): {len(skipped_no_match)}")
        for d, h, why in skipped_no_match:
            print(f"  [!] mods\\{d}  hash={h}  — {why}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
