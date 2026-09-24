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
ПОЛНАЯ ОЧИСТКА (2026-09-24, расширено 2026-09-25):
  python revert_mods.py --full-clean              # revert ВСЕХ модов + RUS-оверлеи +
                                                  # CSV (новый+legacy) + state/ (весь
                                                  # кэш, включая .prev) + УДАЛЕНИЕ
                                                  # EN-бэкапов .orig_*.backup
  python revert_mods.py --full-clean --keep-backups  # то же, но .orig_*.backup ОСТАТЬ
  python revert_mods.py --full-clean --dry-run    # показать, что будет удалено/перенесено
  python revert_mods.py --full-clean --yes        # без подтверждения (batch)
Проверка:
  python revert_mods.py --list                 # что можно откатить
  python revert_mods.py --dry-run <мод>         # показать, не трогая
  python revert_mods.py <мод>                   # откатить
  python revert_mods.py --list-file список.txt   # по списку
  python revert_mods.py --full-clean             # полная очистка (+ бэкапы, если без keep)
  python revert_mods.py                          # все (y/N)
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


def full_clean(dry_run=False, assume_yes=False, keep_backups=False):
    """--full-clean: ПОЛНАЯ ОЧИСТКА — «чистый стол» перед новым переводом.

    Делает ВСЁ, что накопилось при переводе, одним движением:
      A) revert всех модов, у которых есть EN-бэкап (в-place .mod → оригинал);
      B) все RUS-оверлеи в kenshi\\mods\\<имя> RUS — выключить из
         data\\__mods.list И data\\mods.cfg, каталоги перенести в единый
         контейнер kenshi\\_kmt_full_clean_<ts> (обратимо, НЕ mdel);
      C) все CSV нового формата <мод>.translate.csv (workshop + кenshi);
      D) все legacy CSV translate.csv (стараго формата, б/ имени мода);
      E) state/ — ВСЁ (_entries/_mapping/_reuse_pool/_untranslated/
         .prev-бэкапы кэшей + ЛЮБЫЕ другие сгенерированные файлы —
         чтобы старые легаси-записи не попали в новый перевод через resume);
      F) УДАЛЕНИЕ EN-бэкапов <имя>.mod.orig_<hash>.backup — ПОСЛЕ того как
         EN-оригинал восстановлен в .mod (A) и проверен (MD5), бэкап
         становится лишней копией → мdel. Невозвратимо; чтобы ОСТАВИТЬ,
         передайте --keep-backups.

    Возврат A–E: контейнер + .fullclean_<ts>.bak на registry-файлах.
    F) необратимо (EN уже в .mod — бэкап redundant).
    """
    import kmt_paths as kp
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    GAME = kp.resolve(CFG["paths"]["game"])
    MODS_DIR = os.path.join(GAME, "mods")
    GAME_LIST = os.path.join(GAME, "data", "__mods.list")
    MODS_CFG = os.path.join(GAME, "data", "mods.cfg")
    container = os.path.join(GAME, "_kmt_full_clean_" + ts)

    n_revert = n_overlay = n_csv = n_state = 0
    removed_csv, removed_state, moved_overlays = [], [], []

    # ---------- A) revert модов (EN original из бэкапа) ----------
    all_mods = list(TM.workshop_mods()) + list(getattr(TM, "game_mods", lambda: [])())
    backups_to_remove = []   # F) удаляЕМ ТОЛЬКО бэкапы, где EN-оригинал
                             #   гарантированно уже в .mod (revert ok ИЛИ
                             #   .mod уже == бэкапу). Остальные — НЕ трогаем:
                             #   там EN ещё не восстановлен, бэкап — последнее.
    for m in all_mods:
        tgt = m.get("modfile")
        if not tgt or not os.path.isfile(tgt):
            continue
        bak = find_backup(tgt)
        if not bak:
            continue
        if _md5(tgt) == _md5(bak):
            # уже оригинал — бэкап redundant, можно выкинуть в F
            if not keep_backups:
                backups_to_remove.append(bak)
                if dry_run:
                    print(f"  [dry-run] bak-del (already EN): {bak}")
            continue
        if dry_run:
            print(f"  [dry-run] revert: {tgt}")
            n_revert += 1
            if not keep_backups:
                print(f"  [dry-run] bak-del: {bak}")
            continue
        status, detail = revert_one(tgt)
        n_revert += 1
        print(f"  [{'OK ' if status == 'ok' else 'ERR'}] revert: {os.path.basename(tgt)} — {detail}")
        if status == "ok" and not keep_backups:
            backups_to_remove.append(bak)
        # status != ok → backup оставляем (EN не восстановлен)

    # ---------- B) RUS-оверлеи: registry + каталоги ----------
    rus_dirs = []
    if os.path.isdir(MODS_DIR):
        rus_dirs = [d for d in sorted(os.listdir(MODS_DIR))
                    if d.lower().rstrip().endswith(" rus")
                    and os.path.isdir(os.path.join(MODS_DIR, d))]
    if not rus_dirs:
        print("  оверлеев RUS не найдено (B) — пропускаю")
    else:
        # --- B.1 __mods.list ---
        list_lines = []
        if os.path.isfile(GAME_LIST):
            with open(GAME_LIST, "r", encoding="utf-8-sig") as f:
                list_lines = [l.rstrip("\r\n") for l in f]
        keep = [l for l in list_lines
                if not any(l.strip().lower() in (d.lower(), d.lower() + ".mod") for d in rus_dirs)]
        dropped_list = len(list_lines) - len(keep)
        if os.path.isfile(GAME_LIST) and dropped_list and not dry_run:
            with open(GAME_LIST + f".fullclean_{ts}.bak", "w", encoding="utf-8") as f:
                f.write("\n".join(list_lines) + "\n")
            with open(GAME_LIST, "w", encoding="utf-8") as f:
                f.write("\n".join(keep) + "\n")
        print(f"  [B.1] __mods.list: {dropped_list} строк ' RUS' "
              + ("would be removed" if dry_run else "удалено (бэкап рядом)"))
        # --- B.2 mods.cfg ---
        cfg_lines = []
        if os.path.isfile(MODS_CFG):
            with open(MODS_CFG, "r", encoding="utf-8-sig") as f:
                cfg_lines = [l.rstrip("\r\n") for l in f]
        def _cfg_dropped(line):
            s = line.strip().lower()
            if not s:
                return False
            for d in rus_dirs:
                if s == d.lower() or s == d.lower() + ".mod":
                    return True
            return False
        cfg_keep = [l for l in cfg_lines if not _cfg_dropped(l)]
        dropped_cfg = len(cfg_lines) - len(cfg_keep)
        if os.path.isfile(MODS_CFG) and dropped_cfg and not dry_run:
            with open(MODS_CFG + f".fullclean_{ts}.bak", "w", encoding="utf-8") as f:
                f.write("\n".join(cfg_lines) + "\n")
            with open(MODS_CFG, "w", encoding="utf-8") as f:
                f.write("\n".join(cfg_keep) + "\n")
        print(f"  [B.2] mods.cfg: {dropped_cfg} строк ' RUS' "
              + ("would be removed" if dry_run else "удалено (бэкап рядом)"))
        # --- B.3 каталоги → контейнер ---
        for d in rus_dirs:
            src = os.path.join(MODS_DIR, d)
            if dry_run:
                print(f"  [dry-run] overlay: {d} → {os.path.basename(container)}")
            else:
                os.makedirs(container, exist_ok=True)
                dst = os.path.join(container, d)
                if os.path.exists(dst):
                    dst = dst + f"_{int(datetime.datetime.now().timestamp())}"
                shutil.move(src, dst)
                print(f"  [MOVED] overlay: {d} → {os.path.basename(container)}")
            moved_overlays.append(d)
            n_overlay += 1

    # ---------- C+D) CSV (новый + legacy без имени) ----------
    search_roots = [os.path.dirname(WORKSHOP), GAME]  # workshop + kenshi
    csv_removed = []
    for root in search_roots:
        if not os.path.isdir(root):
            continue
        for dirpath, dirs, files in os.walk(root):
            # не залезаем в контейнер и бэкап-папки
            if container in dirpath:
                continue
            for fn in files:
                fl = fn.lower()
                if fn.lower() == "translate.csv" or fl.endswith(".translate.csv"):
                    p = os.path.join(dirpath, fn)
                    if any(p.startswith(b) for b in (container,)):
                        continue
                    csv_removed.append(p)
    for p in csv_removed:
        if not dry_run:
            try:
                os.remove(p)
            except OSError:
                pass
        print(("  [dry-run] " if dry_run else "  [CSV] ") + p)
    n_csv = len(csv_removed)

    # ---------- E) state/ — wipe ----------
    state_removed = []
    if os.path.isdir(STATE):
        for fn in sorted(os.listdir(STATE)):
            p = os.path.join(STATE, fn)
            state_removed.append(p)
            if not dry_run:
                try:
                    if os.path.isdir(p):
                        shutil.rmtree(p, ignore_errors=True)
                    else:
                        os.remove(p)
                except OSError:
                    pass
    n_state = len(state_removed)
    if state_removed:
        print(f"  [{'dry-run ' if dry_run else ''}]state: {n_state} файлов "
              + ("would be deleted" if dry_run else "удалено (весь кэш)"))
        for p in (state_removed[:8] if state_removed and not dry_run else []):
            print(f"    → {p}")
        if len(state_removed) > 8:
            print(f"    …(+{len(state_removed)-8})")

    # ---------- F) EN-бэкапы .orig_*.backup + .revert_* — ПОСЛЕ restore ----------
    # EN-оригинал уже в .mod (проверен MD5 в revert_one); бэкап — лишняя копия.
    # .revert_<ts> — старые snapshots переводов из раннего in-place режима;
    #   после restore EN они уже не нужны. Удаляем оба типа, ПОСЛЕ того
    #   как EN восстановлен. Невозвратимо; чтобы ОСТАВИТЬ: --keep-backups.
    bak_removed = 0
    revert_snaps_removed = 0
    if not keep_backups:
        for bak in backups_to_remove:
            if not dry_run:
                try:
                    os.remove(bak)
                    bak_removed += 1
                except OSError:
                    continue
            print(("  [dry-run] " if dry_run else "  [BakDel] ") + bak)
        # .revert_* — рядом с .mod (те же папки)
        for m in all_mods:
            tgt = m.get("modfile")
            if not tgt or not os.path.isfile(tgt):
                continue
            d = os.path.dirname(tgt)
            base = os.path.basename(tgt)
            try:
                for fn in sorted(os.listdir(d)):
                    if fn.startswith(base + ".revert_"):
                        p = os.path.join(d, fn)
                        if not dry_run:
                            try:
                                os.remove(p); revert_snaps_removed += 1
                            except OSError:
                                continue
                        print(("  [dry-run] " if dry_run else "  [SnapDel] ") + fn)
            except OSError:
                pass
    elif backups_to_remove:
        print(f"  [keep-backups] {len(backups_to_remove)} бэкап(ов) сохранено")

    print(f"\n=== FULL-CLEAN {'DRY-RUN' if dry_run else 'DONE'} ===")
    print(f"  revert:      {n_revert} мод(ов)")
    print(f"  overlay:     {n_overlay} (контейнер: {os.path.basename(container)})")
    print(f"  csv:         {n_csv} (новый+legacy)")
    print(f"  state:       {n_state} файло (полный кэш: _entries/_mapping/.prev/поулы)")
    print(f"  backups:     {bak_removed if not dry_run else len(backups_to_remove)} .orig_*.backup "
          + ("удалено" if (not dry_run and not keep_backups) else
             ("удалится" if dry_run and not keep_backups else "сохранено (--keep-backups)")))
    if revert_snaps_removed:
        print(f"  snapshots:   {revert_snaps_removed} .revert_* (старые in-place) удалено")
    if not dry_run and (n_overlay or n_csv or n_state):
        print(f"  бэкапы: registry .fullclean_{ts}.bak рядом с __mods.list/mods.cfg;")
        print(f"          оверлеи в {container}")
    return 0


def main():
    args = [a for a in sys.argv[1:] if a]
    dry_run = "--dry-run" in args
    clean = "--clean" in args
    full = "--full-clean" in args
    keep_backups = "--keep-backups" in args
    assume_yes = "--yes" in args or os.environ.get("KENSHI_YES") == "1"
    args = [a for a in args if a not in ("--dry-run", "--list", "--clean", "--full-clean", "--yes", "--keep-backups")]

    if full:
        if not dry_run and not assume_yes:
            try:
                ans = input("ПОЛНАЯ очистка: revert всех модов + удалить все RUS-оверлеи/"
                            "CSV/кэш + УДАЛИТЬ EN-бэкапы .orig_*.backup? "
                            "[y/N] (бэкапы оставить: --keep-backups): ").strip().lower()
            except EOFError:
                ans = "n"
            if ans not in ("y", "yes", "д", "да"):
                print("прервано (ничего не изменено)")
                return 1
        return full_clean(dry_run=dry_run, assume_yes=assume_yes, keep_backups=keep_backups)

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
    import exclude as _excl
    _excl.set_include_excluded(os.environ.get("KENSHI_INCLUDE_EXCLUDED") == "1" or "--include-excluded" in sys.argv)
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
            if TM.is_excluded(m["name"], m["modfile"]) and not _excl.INCLUDE_EXCLUDED:
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
