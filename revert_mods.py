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


def main():
    args = [a for a in sys.argv[1:] if a]
    dry_run = "--dry-run" in args
    args = [a for a in args if a not in ("--dry-run", "--list")]

    # --list: показать, какие моды можно откатить
    if "--list" in sys.argv:
        all_mods = TM.workshop_mods()
        print(f"Workshop-модов: {len(all_mods)}")
        ready = 0
        for m in all_mods:
            tgt = m["modfile"]
            if not tgt:
                continue
            bak = find_backup(tgt)
            if bak:
                already = " (УЖЕ оригинал)" if _md5(tgt) == _md5(bak) else ""
                print(f"  [#{m['id']}] {os.path.basename(tgt):42} бэкап: {os.path.basename(bak)}{already}")
                ready += 1
        print(f"\nГотовы к откату (есть бэкап EN): {ready}")
        return 0

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

    all_mods = TM.workshop_mods()
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
    if not mods:
        print("revert: нечего откатывать (моды не найдены или все в исключениях)")
        return 3

    print(f"Откат: {len(mods)} мод(ов)" + ("  [DRY-RUN — ничего не меняется]" if dry_run else ""))
    print(f"workshop: {WORKSHOP}")
    print()
    ok = fail = skip = 0
    for i, m in enumerate(mods, 1):
        tgt = m["modfile"]
        status, detail = revert_one(tgt, dry_run=dry_run)
        tag = {"ok": "OK  ", "skip": "SKIP", "error": "ERR "}[status]
        print(f"  [{i}/{len(mods)}] {tag} #{m['id']} {os.path.basename(tgt):42} — {detail}")
        if status == "ok":
            ok += 1
        elif status == "skip":
            skip += 1
        else:
            fail += 1
    print(f"\nИтого: откатано {ok}, пропущено {skip}, ошибок {fail}")
    if fail:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
