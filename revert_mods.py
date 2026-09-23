#!/usr/bin/env python3
"""revert_mods.py — ОТКАТ перевода мода(ов): вернуть оригинал EN из бэкапа
<имя>.mod.orig_<hash>.backup поверх текущего .mod (RU/переведённого).

Селекция — ТОТ ЖЕ контракты, что у translate_mods.py:
  • один мод по имени (частичный) или по Steam workshop ID (6+ цифр);
  • несколько модов — как аргументы;
  • --list-file файл.txt — список (по строке на мод, '#' — комментарий);
  • без аргументов — все Workshop-моды с подтверждением (y/N),
    как и при переводе;
  • моды из exclude.txt пропускаются (override: --include-excluded).

Безопасность (ничего не удаляется — всё обратимо):
  • текущий .mod (RU) → <имя>.mod.revert_<YYYYmmdd_HHMMSS>  (свой snapshot)
  • <имя>.mod.orig_<hash>.backup (EN) → <имя>.mod
  • если MD5 бэкапа == MD5 текущего .mod — считаем, что уже оригинал, skip
  • .translate.csv / .prev / state-кеш НЕ трогаем (для повторного перевода)

Возврат: 0 = ок/пропуск, 1 = ошибка, 2 = арг.ошибка, 3 = нет мода/бэкапа.
Проверка:
  python revert_mods.py --list                 # что можно откатить
  python revert_mods.py --dry-run <мод>         # показать, не трогая
  python revert_mods.py <мод>                   # откатить
  python revert_mods.py --list-file список.txt   # по списку
  python revert_mods.py                        # все (y/N)
"""
import os
import sys
import json
import shutil
import hashlib
import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# --- единый резолвер путей (как во всём проекте) ---
import kmt_paths
_resolve = kmt_paths.resolve
CFG = json.load(open(os.path.join(HERE, "config.json"), encoding="utf-8"))
P = CFG["paths"]
WORKSHOP = _resolve(P["workshop"])
STATE    = _resolve(P["state"])

# --- переиспользуем ТОТ ЖЕ выборку, что в translate_mods.py (без дублей) ---
import translate_mods as TM


def find_backup(target):
    """<имя>.mod.orig_<hash>.backup рядом с target. Возвращает путь или None."""
    if not target:
        return None
    d = os.path.dirname(target)
    base = os.path.basename(target)  # e.g. "Great Beak Things.mod"
    try:
        for f in os.listdir(d):
            if f.startswith(base + ".orig_") and f.endswith(".backup"):
                return os.path.join(d, f)
    except OSError:
        pass
    return None


def _md5(path):
    try:
        with open(path, "rb") as f:
            return hashlib.md5(f.read()).hexdigest()
    except OSError:
        return None


def _hash_from_backup(bak):
    """Якорь кеша h из имени бэкапа <имя>.mod.orig_<h>.backup (между .orig_ и .backup).

    Тот же h, что translate_mods.py кладёт в state\\{h}_entries.json / {h}_mapping.json.
    Возвращает None, если имя не похоже на наш бэкап.
    """
    name = os.path.basename(bak)
    i = name.find(".orig_")
    j = name.rfind(".backup")
    if i < 0 or j <= i + 6:
        return None
    return name[i + 6:j]


def clean_caches_for(target, bak, dry_run=False):
    """--clean: удалить кэш и CSV ОДНОГО мода (безопасно).

    Удаляется (если существует):
      • state\\{h}_entries.json, state\\{h}_mapping.json  (h — из имени бэкапа);
      • <папка>/<имя>.translate.csv                      (per-mod CSV, рядом с .mod).
    НЕ трогается (гарантированно):
      • <имя>.mod.orig_<h>.backup (EN-бэкап — нужен для отката);
      • *.revert_<ts> (RU-копии), legacy общий translate.csv (может делиться модами),
        другие моды, конфиг/код/DLL.
    Возвращает список путей, которые удалены (в dry-run — которые бы были удалены).
    """
    removed = []
    h = _hash_from_backup(bak)
    if h:
        for suf in ("_entries.json", "_mapping.json"):
            p = os.path.join(STATE, h + suf)
            if os.path.isfile(p):
                if not dry_run:
                    try:
                        os.remove(p)
                    except OSError:
                        pass
                removed.append(p)
    # per-mod CSV (только <имя>.translate.csv; общий translate.csv НЕ трогаем)
    d = os.path.dirname(target)
    b = os.path.basename(target)
    if b.lower().endswith(".mod"):
        b = b[:-4]
    csv_p = os.path.join(d, b + ".translate.csv")
    if os.path.isfile(csv_p):
        if not dry_run:
            try:
                os.remove(csv_p)
            except OSError:
                pass
        removed.append(csv_p)
    return removed


def revert_one(target, dry_run=False):
    """Один файл .mod. (status, detail): status in ok/skip/error."""
    bak = find_backup(target)
    if not bak:
        return "error", "нет оригинального бэкапа .orig_<hash>.backup (перевод не делался?)"
    # если уже оригинал — не дёргаем
    if _md5(target) == _md5(bak):
        return "skip", "уже оригинал (MD5 совпадает с бэкапом)"
    if dry_run:
        return "ok", "dry-run: будет восстановлен оригинал EN (бэкап: " + os.path.basename(bak) + ")"
    # 1) сохранить ТЕКУЩИЙ (RU) как snapshot — обратимо
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    snap = target + ".revert_" + ts
    shutil.copy2(target, snap)
    # 2) вернуть EN из бэкапа
    shutil.copy2(bak, target)
    # 3) подтвердить, что теперь == бэкапу
    if _md5(target) != _md5(bak):
        return "error", "после отката MD5 не совпал с бэкапом (проверь файлы!)"
    return "ok", "откат: EN восстановлен, текущий RU сохранён как " + os.path.basename(snap)


def list_orphan_dir(mod):
    """Что лежит в папке orphan-мода (без .mod)."""
    d = mod.get("dir") or ""
    try:
        files = sorted(os.listdir(d))
    except OSError:
        files = []
    return files


def clean_orphans(mods, dry_run=False):
    """Перенести orphan-папки (нет .mod, есть мусор) в <workshop>/_trash/<id>.

    Обратимо: в _trash/<id>/ остаётся всё как было. Возвращает список
    перенесённых id. Только папки с числовым id (косточки Workshop).
    """
    # _trash под workshop — не внутри Steam Workshop папки мода
    trash_root = os.path.join(os.path.dirname(WORKSHOP), "_kmt_orphan_trash")
    moved = []
    for m in mods:
        if not m.get("dir") or not m.get("modfile") is None:
            continue
        src_dir = m["dir"]
        dst_dir = os.path.join(trash_root, m["id"])
        if dry_run:
            print(f"  [dry-run] #{m['id']} {m['name']!r} → {os.path.basename(dst_dir)}")
        else:
            os.makedirs(trash_root, exist_ok=True)
            if os.path.exists(dst_dir):
                # если уже есть — не затираем
                print(f"  [skip] #{m['id']} {m['name']!r} — {os.path.basename(dst_dir)} уже в trash")
                continue
            shutil.move(src_dir, dst_dir)
            print(f"  [moved] #{m['id']} {m['name']!r} → _kmt_orphan_trash")
        moved.append(m["id"])
    return moved, trash_root


def main():
    args = [a for a in sys.argv[1:] if a]
    dry_run = "--dry-run" in args
    clean = "--clean" in args
    args = [a for a in args if a not in ("--dry-run", "--list", "--clean")]

    # --clean-orphans: перенести orphan-папки (без .mod) в trash (обратимо)
    if "--clean-orphans" in sys.argv:
        all_mods = TM.workshop_mods()
        orphans = [m for m in all_mods if not m.get("modfile")]
        if not orphans:
            print("Orphan-папок нет (всё Workshop-папки имеют .mod)")
            return 0
        print(f"Orphan-папок (нет .mod, только .backup/.info/.csv): {len(orphans)}")
        if dry_run:
            print("  [DRY-RUN — ничего не переносится]")
        for m in orphans:
            try:
                files = list_orphan_dir(m)
            except Exception:
                files = []
            print(f"  [#{m['id']}] {m['name'][:40] if m['name'] else '(нет имени)':42} {', '.join(files)}")
        if not dry_run:
            print()
            try:
                ans = input("Перенести все orphan-папки в _kmt_orphan_trash? [y/N]: ").strip().lower()
            except EOFError:
                ans = "n"
            if ans not in ("y", "yes", "д", "да"):
                print("прервано (ничего не перенесено)")
                return 1
            _, trash_root = clean_orphans(orphans, dry_run=False)
            print(f"\nDone. Trash: {trash_root}")
        return 0

    # --list: показать, какие моды можно откатить + orphan-секция
    if "--list" in sys.argv:
        all_mods = TM.workshop_mods() + getattr(TM, "game_mods", lambda: [])()
        ready = 0
        orphans = 0
        for m in all_mods:
            tgt = m["modfile"]
            if not tgt:
                orphans += 1
                try:
                    files = list_orphan_dir(m)
                except Exception:
                    files = []
                fdesc = ", ".join(files) if files else "(пусто)"
                print(f"  [ORPHAN #{m['id']}] {m['name'][:40] if m['name'] else '(нет имени)':42} — нет .mod; {fdesc}")
                continue
            bak = find_backup(tgt)
            if bak:
                already = " (УЖЕ оригинал)" if _md5(tgt) == _md5(bak) else ""
                print(f"  [#{m['id']}] {os.path.basename(tgt):42} бэкап: {os.path.basename(bak)}{already}")
                ready += 1
        print(f"\nГотовы к откату (есть бэкап EN): {ready}")
        if orphans:
            print(f"Осиротевшие (нет .mod, есть бэкап): {orphans} — очистка: --clean-orphans")
        return 0

    # --file <path>: revert a single .mod (kenshi\data\*.mod, kenshi\mods\<mod>\*.mod —
    # любой путь) — зеркало translate_mods.py --file.
    if "--file" in sys.argv:
        i = sys.argv.index("--file")
        if i + 1 >= len(sys.argv) or not sys.argv[i + 1]:
            print("revert: --file нужен путь к .mod")
            return 2
        path = sys.argv[i + 1]
        if not os.path.isfile(path) or not path.lower().endswith(".mod"):
            print(f"revert: --file: не найден .mod-файл: {path}")
            return 3
        if dry_run:
            print("Откат (dry-run): " + path)
            if clean:
                print("  + очистка кэша и CSV (dry-run: покажу, что бы было удалено)")
        status, detail = revert_one(path, dry_run=dry_run)
        print(f"  [{status}] {os.path.basename(path)} — {detail}")
        if clean and status in ("ok", "skip"):
            bak = find_backup(path)
            if bak:
                cleaned = clean_caches_for(path, bak, dry_run=dry_run)
                verb = "бы удалено" if dry_run else "удалено (кэш+CSV)"
                for p in cleaned:
                    print(f"    {verb}: {p}")
                if not cleaned:
                    print("    (кэш и CSV этого мода уже отсутствовали)")
            else:
                print("    [!] --clean: нет бэкапа — не могу определить якорь кеша (CSV удалён, если был)")
        return {"ok": 0, "skip": 0, "error": 1}[status]

    queries = []
    if "--list-file" in args:
        i = args.index("--list-file")
        if i + 1 >= len(args) or not args[i + 1]:
            print("revert: --list-file нужен путь к файлу")
            return 2
        queries = TM.parse_list_file(args[i + 1])
        args = args[:i] + args[i + 2:]
    args = [a for a in args if a not in ("--include-excluded",)]
    TM.INCLUDE_EXCLUDED = os.environ.get("KENSHI_INCLUDE_EXCLUDED") == "1" or "--include-excluded" in sys.argv
    queries += args

    all_mods = TM.workshop_mods() + getattr(TM, "game_mods", lambda: [])()
    mods, seen, skipped_excl = [], set(), []
    if queries:
        for q in queries:
            m = TM.resolve_mod(q, all_mods)
            if not m or not m.get("modfile"):
                print(f"revert: [!] не найден: {q}")
                continue
            if m["modfile"] in seen:
                continue
            if TM.is_excluded(m["name"], m["modfile"]) and not TM.INCLUDE_EXCLUDED:
                skipped_excl.append(m)
                continue
            seen.add(m["modfile"])
            mods.append(m)
    else:
        # без аргументов — все eligible (как в translate_mods)
        eligible = [m for m in all_mods if not TM.is_excluded(m["name"], m["modfile"])]
        skipped_excl = [m for m in all_mods if TM.is_excluded(m["name"], m["modfile"])]
        if not eligible:
            print("все Workshop-моды в исключениях — нечего откатывать")
            return 1
        try:
            ans = input(f"Откатить ВСЕ {len(eligible)} модов на оригинал EN? [y/N]: ").strip().lower()
        except EOFError:
            ans = "n"
        if ans not in ("y", "yes", "д", "да"):
            print("прервано (ничего не откатано)")
            return 1
        mods = eligible

    if skipped_excl and queries:
        print(f"[exclude] пропущено: {', '.join(m['name'] for m in skipped_excl[:8])}"
              + (f" …(+{len(skipped_excl)-8})" if len(skipped_excl) > 8 else "")
              + "  (override: --include-excluded)")
    # фильтруем папки Workshop БЕЗ .mod-файла (например, пустые папки — только бэкап)
    # и сообщаем о них
    no_mod = [m for m in mods if not m.get("modfile")]
    if no_mod:
        for m in no_mod:
            print(f"  [skip] #{m['id']} {m['name']} — нет .mod-файла (пропущено)")
        mods = [m for m in mods if m.get("modfile")]
        if not mods:
            print("revert: ни в одной папке нет .mod-файла — нечего откатывать")
            return 3

    if not mods:
        print("revert: нечего откатывать (моды не найдены или все в исключениях)")
        return 3

    print(f"Откат: {len(mods)} мод(ов)" + (" (+ очистка кэша и CSV: --clean)" if clean else "")
          + ("  [DRY-RUN — ничего не меняется]" if dry_run else ""))
    print(f"workshop: {WORKSHOP}")
    print()
    ok = fail = skip = 0
    n_cleaned_total = 0
    for i, m in enumerate(mods, 1):
        tgt = m["modfile"]
        if not tgt:
            skip += 1
            continue
        status, detail = revert_one(tgt, dry_run=dry_run)
        tag = {"ok": "OK  ", "skip": "SKIP", "error": "ERR "}[status]
        line = f"  [{i}/{len(mods)}] {tag} #{m['id']} {os.path.basename(tgt):42} — {detail}"
        if clean and status in ("ok", "skip"):
            bak = find_backup(tgt)
            if bak:
                cleaned = clean_caches_for(tgt, bak, dry_run=dry_run)
                n_cleaned_total += len(cleaned)
                if cleaned:
                    line += f"  | clean: {len(cleaned)} файл(а) " + ("было бы удалено" if dry_run else "удалено")
                    for p in cleaned:
                        print(f"         → {p}")
        print(line)
        if status == "ok":
            ok += 1
        elif status == "skip":
            skip += 1
        else:
            fail += 1
    print(f"\nИтого: откатано {ok}, пропущено {skip}, ошибок {fail}"
          + (f", кэш+CSV: {n_cleaned_total} файлов " + ("было бы удалено" if dry_run else "удалено") if clean else ""))
    if fail:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
