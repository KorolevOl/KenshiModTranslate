#!/usr/bin/env python3
"""
clean_caches.py — удалить все кэши перевода и файлы .translate.csv.

Что удаляется (только при --yes):
  1. СОДЕРЖИМОЕ state/   — *_entries.json, *_mapping.json, *_reuse_pool_cache.json,
                            .prev / .pre_optionA бэкапы и т.д. (весь кэш конвейера).
  2. *.translate.csv      — из Workshop, кенши (data\\, mods\\, корень) и папки проекта.

Что НЕ трогается (гарантированно):
  .mod файлы, .orig_<hash>.backup (EN-бэкапы/откат), *.revert_<ts> (RU-копии),
  config.json, dict.json, exclude.txt, код, dll.

После очистки перевод любого мода начнётся С НУЛЯ (без кэша):
  extract → LLM → apply — заново; старые RU-строки не подтянутся из кэша.

Использование:
  python clean_caches.py              # dry-run: показать, что будет удалено (ничего не трогает)
  python clean_caches.py --yes        # удалить (спросит подтверждение, если не --quiet)
  python clean_caches.py --state-only --yes   # только state/
  python clean_caches.py --csv-only  --yes    # только *.translate.csv
"""
import os
import sys
import time
import shutil
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import kmt_paths
from kmt_paths import resolve
CFG = __import__("json").load(open(os.path.join(HERE, "config.json"), encoding="utf-8"))
P = CFG["paths"]

WORKSHOP = resolve(P["workshop"])
GAME     = resolve(P["game"])
STATE    = resolve(P["state"])

# Запрещённые подстроки в ИМЕНИ файла — никогда не удаляем
PROTECTED = (".orig_", ".revert_", ".backup", ".mod", ".dll", ".exe",
             "config.json", "dict.json", "exclude.txt", ".po", ".pre_optionA.bak")


def is_protected(name):
    ln = name.lower()
    return any(p in ln for p in PROTECTED)


def collect_state():
    files = []
    if os.path.isdir(STATE):
        for root, _dirs, fs in os.walk(STATE):
            for f in fs:
                if not is_protected(f):
                    files.append(os.path.join(root, f))
    return sorted(files)


def collect_csv(roots):
    out = []
    seen = set()
    for base in roots:
        if not os.path.isdir(base):
            continue
        for root, _dirs, fs in os.walk(base):
            for f in fs:
                if f.lower().endswith(".translate.csv") and not is_protected(f):
                    p = os.path.normcase(os.path.abspath(root + os.sep + f))
                    if p not in seen:
                        seen.add(p)
                        out.append(os.path.join(root, f))
    return sorted(out)


def human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return (f"{int(n)} {unit}" if unit == "B" else f"{n:.1f} {unit}")
        n /= 1024.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--yes", action="store_true", help="реально удалить (без --yes — только показать)")
    ap.add_argument("--state-only", action="store_true", help="только state/")
    ap.add_argument("--csv-only", action="store_true", help="только *.translate.csv")
    ap.add_argument("--quiet", action="store_true", help="не спрашивать подтверждение при --yes")
    a = ap.parse_args()

    do_state = not a.csv_only
    do_csv = not a.state_only

    state_files = collect_state() if do_state else []
    csv_roots = [WORKSHOP, os.path.join(GAME, "data"), os.path.join(GAME, "mods"), GAME, HERE]
    csv_files = collect_csv(csv_roots) if do_csv else []

    n = len(state_files) + len(csv_files)
    sz_state = sum(os.path.getsize(f) for f in state_files)
    sz_csv = sum(os.path.getsize(f) for f in csv_files)
    sz = sz_state + sz_csv

    print("=" * 60)
    print(f"  clean_caches — {'удаление' if a.yes else 'dry-run (ничего не удаляется)'}")
    print("=" * 60)
    if do_state:
        print(f"\nstate/ ({os.path.abspath(STATE)}): {len(state_files)} файлов, {human(sz_state)}")
        for f in state_files[:8]:
            print(f"   {os.path.relpath(f, HERE)}  ({human(os.path.getsize(f))})")
        if len(state_files) > 8:
            print(f"   ... и ещё {len(state_files) - 8}")
    if do_csv:
        print(f"\n*.translate.csv: {len(csv_files)} файл(ов), {human(sz_csv)}")
        for f in csv_files:
            print(f"   {f}  ({human(os.path.getsize(f))})")

    print("\nНЕ тронуты: .mod, .orig_<hash>.backup (EN-откат), *.revert_<ts> (RU-копии), "
          "config.json, dict.json, код/DLL.")
    print(f"\nИТОГО: {n} файлов, {human(sz)}")

    if not a.yes:
        print("\n[DRY-RUN] Чтобы удалить, запустите:  python clean_caches.py --yes")
        return 0
    if n == 0:
        print("\nНечего удалять (всё чисто).")
        return 0
    if not a.quiet:
        ans = input(f"\nУдалить {n} файлов ({human(sz_state + sz_csv)})? [y/N] ").strip().lower()
        if ans not in ("y", "yes", "да"):
            print("Отменено — ничего не удалено.")
            return 1

    t0 = time.time()
    removed, failed = 0, []
    for f in state_files + csv_files:
        try:
            os.remove(f)
            removed += 1
        except Exception as ex:
            failed.append((f, str(ex)))
    # подчистить пустые подпапки в state/ (кроме самого state/)
    if do_state:
        for root, _dirs, fs in os.walk(STATE, topdown=False):
            if root != STATE and not fs and not os.listdir(root):
                try:
                    os.rmdir(root)
                except Exception:
                    pass
    print(f"\nУДАЛЕНО: {removed}/{n} за {time.time() - t0:.1f} c")
    if failed:
        print("ОШИБКИ:")
        for f, e in failed:
            print(f"   {f}: {e}")
        return 2
    print("Кэш очищен. Следующий перевод пойдёт с нуля (extract → LLM → apply).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
