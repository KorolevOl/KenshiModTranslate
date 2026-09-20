#!/usr/bin/env python3
"""
rebuild_mods.py — пересборка .mod из готовых кешей (state/).
Пути читает из config.json (общий резолвер kmt_paths): работает из любого CWD.
Не нужен LLM: берутся RU-переводы из state/<hash>_mapping.json и применяются
к ТЕКУЩЕМУ .mod (через DoApply → SaveModFile).

Использование:
  python rebuild_mods.py                  # все моды (в порядке Workshop)
  python rebuild_mods.py <mod_id>          # один мод по Steam workshop ID
  python rebuild_mods.py <mod_name>        # один мод по имени (частичный поиск)
  python rebuild_mods.py --dry-run         # показать, что будет сделано
  python rebuild_mods.py --list            # список доступных модов + статус
"""
import os, sys, json, re, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import kmt_paths
_resolve = kmt_paths.resolve
CFG = json.load(open(os.path.join(HERE, "config.json"), encoding="utf-8"))
P = CFG["paths"]
WORKSHOP = _resolve(P["workshop"])
DOTNET   = _resolve(P["dotnet"])
CLI      = _resolve(P["modtranslate_cli"])
STATE    = _resolve(P["state"])

def find_hash_for_mod(d):
    """Найти hash из .orig_<hash>.backup в папке мода."""
    for f in os.listdir(d):
        m = re.match(r"^.+\.orig_([a-f0-9]+)\.backup$", f)
        if m:
            return m.group(1)
    return None

def find_mod_file(d):
    """Главный .mod файл папки (кратчайшее имя с .mod)."""
    mods = [f for f in os.listdir(d)
            if f.endswith(".mod") and not f.startswith(".")]
    if not mods:
        return None
    return sorted(mods, key=len)[0]

def collect_mods(query=None):
    """Список (appid, mod_dir, mod_path, hash, mapping_path).
    query — фильтр: id или имя (partial)."""
    results = []
    for appid in sorted(os.listdir(WORKSHOP), key=lambda x: int(x) if x.isdigit() else 0):
        d = os.path.join(WORKSHOP, appid)
        if not os.path.isdir(d):
            continue
        if query:
            q = query.lower()
            if appid != query and q not in appid:
                # check mod filename
                mf = find_mod_file(d)
                if not mf or q not in mf.lower():
                    continue
        hash_ = find_hash_for_mod(d)
        if not hash_:
            continue
        mf = find_mod_file(d)
        if not mf:
            continue
        mod_path = os.path.join(d, mf)
        mapping_path = os.path.join(STATE, f"{hash_}_mapping.json")
        if not os.path.exists(mapping_path):
            continue
        results.append((appid, d, mod_path, mf, hash_, mapping_path))
    return results

def do_rebuild(appid, mod_path, mapping_path):
    """Apply mapping → current .mod. Возвращает (applied, total) или None."""
    out = mod_path + ".rebuild"
    r = subprocess.run([DOTNET, CLI, "apply", mod_path, mapping_path, out],
                       capture_output=True, text=True, timeout=120)
    applied = total = 0
    for line in (r.stderr or "").split("\n"):
        m = re.search(r"applied:\s*(\d+)\s*/\s*(\d+)", line)
        if m:
            applied, total = int(m.group(1)), int(m.group(2))
            break
    if not os.path.exists(out):
        return None, r.stderr.strip()
    # check if there's Cyrillic in the output (sanity)
    new_txt = open(out, "rb").read().decode("utf-8", "ignore")
    if not any('\u0400' <= c <= '\u04ff' for c in new_txt):
        os.remove(out)
        return None, "no Cyrillic in output"
    # compare with original
    old_txt = open(mod_path, "rb").read().decode("utf-8", "ignore")
    old_cyr = sum(1 for c in old_txt if '\u0400' <= c <= '\u04ff')
    new_cyr = sum(1 for c in new_txt if '\u0400' <= c <= '\u04ff')
    # always replace (rebuild = trust the mapping)
    os.replace(out, mod_path)
    return (applied, total), f"кириллица {old_cyr}→{new_cyr}"

def main():
    dry_run = "--dry-run" in sys.argv
    query   = None
    for a in sys.argv[1:]:
        if a not in ("--dry-run", "--list"):
            query = a

    if "--list" in sys.argv:
        mods = collect_mods(query)
        print(f"Доступно модов с кешем: {len(mods)}")
        for appid, d, mp, mf, hash_, mpath in mods:
            raw = json.load(open(mpath, encoding="utf-8"))
            filled = sum(1 for x in raw if x.get("ru"))
            print(f"  [{appid}] {mf:45} {filled}/{len(raw)} переводов  ({hash_})")
        return

    mods = collect_mods(query)
    if not mods:
        print(f"НЕ найдено модов{f' по запросу {query!r}' if query else ''} с готовым кешем.")
        if query:
            print("Попробуй --list для списка доступных.")
        return 1

    if dry_run:
        print(f"DRY-RUN: {len(mods)} модов будет пересобран:")
        for appid, d, mp, mf, hash_, mpath in mods:
            raw = json.load(open(mpath, encoding="utf-8"))
            print(f"  [{appid}] {mf}  ({len(raw)} записей, {sum(1 for x in raw if x.get('ru'))} с RU)")
        return

    print(f"Пересборка {len(mods)} модов из кеша:\n")
    ok = fail = skip = 0
    for i, (appid, d, mp, mf, hash_, mpath) in enumerate(mods, 1):
        sys.stdout.write(f"\r  [{i}/{len(mods)}] [{appid}] {mf}")
        sys.stdout.flush()
        res, info = do_rebuild(appid, mp, mpath)
        if res:
            applied, total = res
            ok += 1
            print(f"\r  ✓ [{i:2}/{len(mods):2}] [{appid}] {mf:45} {applied:>3}/{total}  {info}")
        else:
            skip += 1
            print(f"\r  ✗ [{i:2}/{len(mods):2}] [{appid}] {mf:45} {info}")
    print(f"\nИтого: пересобрано {ok}, пропущено {skip}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
