#!/usr/bin/env python3
"""csv_mod.py — экспорт/импорт перевода мода через <имя-мода>.translate.csv (разделитель |,
столбец 1 = оригинал EN, столбец 2 = перевод RU). Команды: export <мод> [моды...] — выгрузить <имя-мода>.translate.csv в папку мода (без LLM-перевода); import <мод> [моды...] — собрать .mod из CSV (ручная правка; старые translate.csv читаются как fallback). Выходной: 0 — ок; 1 — ошибка (мод не найден, нет маппинга и т.п.).

ИМПОРТ не меняет порядок строк .mod: apply переписывает строки по ПОЗИЦИИ,
поэтому перстановка идёт по точному тексту оригинала (idx_by_orig), не по i."""
import sys, os, re, csv, json, argparse
sys.dont_write_bytecode = True
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

def _tm():
    try:
        import translate_mods as m
        return m
    except Exception as e:
        print("[!] не удалось загрузить translate_mods.py:", e)
        sys.exit(1)

def list_all(TM):
    # 2026-09-23: workshop + встроенные моды игры (kenshi\data\*.mod, kenshi\mods\*)
    mods = list(TM.workshop_mods())
    try:
        mods += list(TM.game_mods())
    except Exception:
        pass
    return mods

def resolve(target_arg, TM):
    all_mods = list_all(TM)
    # по id (цифры 6+) — прямое попадание
    info = None
    if re.fullmatch(r"\d{6,}", target_arg.strip()):
        info = [m for m in all_mods if m.get("id") == target_arg.strip()]
        info = info[0] if len(info) == 1 else None
    if info is None:
        info = TM.resolve_mod(target_arg, all_mods)
    if not (info and info.get("modfile")):
        print(f"[!] мод не найден: {target_arg}")
        print("    список: python csv_mod.py --list")
        return None
    target = info["modfile"]
    m = os.path.dirname(target)
    backup = None
    # как в translate_one: base = ИМЯ с .mod, файл бэкапа = <base>.orig_<h>.backup
    base = os.path.basename(target)
    for f in os.listdir(m):
        if f.startswith(base + ".orig_") and f.endswith(".backup"):
            backup = os.path.join(m, f)
            h = f[len(base) + 6:-len(".backup")]
            break
    if not h:
        import hashlib
        h = hashlib.md5(open(target, "rb").read()).hexdigest()[:12]
    efile = os.path.join(TM.STATE, h + "_entries.json")
    mfile = os.path.join(TM.STATE, h + "_mapping.json")
    ok = False
    if os.path.exists(efile) and os.path.getsize(efile) > 0:
        try:
            json.load(open(efile, encoding="utf-8")); ok = True
        except Exception:
            pass
    if not ok:
        src = backup if (backup and os.path.isfile(backup)) else target
        TM.run_dotnet(["extract", src, efile])
    entries = json.load(open(efile, encoding="utf-8"))
    return dict(target=target, mfile=mfile, efile=efile, h=h, entries=entries, modname=info["name"])

def export_csv(tgt_dir, entries, mfile, target, log):
    TM = _tm()
    from validate_translation import finished_row
    done = {}
    if os.path.exists(mfile) and os.path.getsize(mfile) > 0:
        mm = json.load(open(mfile, encoding="utf-8"))
        done = {str(r.get("i")): (r.get("ru") or "") for r in mm if isinstance(r, dict)}
    out_path = csv_write_path(tgt_dir, target)   # ВСЕГДА <имя-мода>.translate.csv
    n_filled = 0
    n_skipped = 0
    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter="|", quoting=csv.QUOTE_MINIMAL)
        for e in entries:
            i = str(e.get("i")); orig = (e.get("original") or "").strip()
            ru = (done.get(i) or "").strip()
            # 2026-09-22: unified predicate — a row is written to the CSV if it's a real
            # translation or an empty translatable one (for editing in Excel);
            # system / non-translatable rows are excluded.
            if not finished_row(orig, ru or None):
                n_skipped += 1
                continue
            w.writerow([orig, ru]); n_filled += (ru != "")
    log(f"[export] {out_path}")
    log(f"[export] rows: {n_filled} translated, {n_skipped} system/non-translatable skipped")
    return True
def csv_write_path(tgt_dir, target):
    """Для ЗАПИСИ: всегда <папка>/<имя-мода>.translate.csv.
    Никогда не трогает общий legacy translate.csv — в папке с несколькими .mod
    (kenshi\\data\\: rebirth/Dialogue/Newwworld) он был бы общим и затираемым."""
    base = os.path.basename(target)
    if base.lower().endswith(".mod"):
        base = base[:-4]
    return os.path.join(tgt_dir, base + ".translate.csv")

def csv_read_path(tgt_dir, target):
    """Для ЧТЕНИЯ (импорт): сначала <имя-мода>.translate.csv,
    затем legacy translate.csv (назад-совместимость с старыми правками)."""
    new = csv_write_path(tgt_dir, target)
    if os.path.isfile(new):
        return new
    old = os.path.join(tgt_dir, "translate.csv")
    if os.path.isfile(old):
        return old
    return new

def import_csv(tgt_dir, entries, mfile, target, log):
    TM = _tm()
    csv_path = csv_read_path(tgt_dir, target)
    if not os.path.isfile(csv_path):
        # пробуем и старое имя на всякий
        old = os.path.join(tgt_dir, "translate.csv")
        if os.path.isfile(old):
            csv_path = old
        else:
            log(f"[!] нет CSV-файла мода: {csv_path}"); return False
    pairs = []
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        for row in csv.reader(f, delimiter="|"):
            if not row or not any((c or "").strip() for c in row): continue
            orig = (row[0] or "").strip(); ru = (row[1]).strip() if len(row) > 1 else ""
            pairs.append((orig, ru))
    if not pairs:
        log(f"[!] {os.path.basename(csv_path)} пуст"); return False
    # индекс строка -> i по TOЧНОМУ тексту оригинала
    idx_by_orig = {}
    for e in entries:
        o = (e.get("original") or "").strip()
        if o and o not in idx_by_orig:
            idx_by_orig[o] = str(e.get("i"))
    # собираем mapping; ПУСТЫЕ правки = строка НЕ переводится (пусто в apply -> не трогаем)
    # дедупликация по i: дубликат в CSV (одна и та же строка дважды) — оставляем ПОСЛЕДНЮЮ (та, которую правили)
    mapping, filled, unmatched = [], 0, []
    by_i = {}  # i -> {i, ru}
    order = []
    for orig, ru in pairs:
        if not ru: continue
        i = idx_by_orig.get(orig)
        if i is None: unmatched.append(orig); continue
        if i not in by_i: order.append(i)
        by_i[i] = {"i": int(i), "ru": ru}
        filled += 1
    mapping = [by_i[i] for i in order]
    if unmatched:
        log(f"[csv] ! {len(unmatched)} строк НЕ найдено среди извлечённых — исключено из сборки:")
        for u in unmatched[:8]: log(f"     {u[:80]!r}")
    if not mapping: log("[csv] нет ни одной валидной пары — не применяю"); return False
    if os.path.exists(mfile):
        import shutil; shutil.copy2(mfile, mfile + ".prev")
    with open(mfile, "w", encoding="utf-8") as f: json.dump(mapping, f, ensure_ascii=False)
    log(f"[csv] маппинг собран: {filled}/{len(pairs)} строк -> {os.path.basename(mfile)}")
    # применяем .mod (как в translate_one): target.new + кириллическая проверка
    TM.run_dotnet(["apply", target, mfile, target + ".new"])
    newf = target + ".new"; oldf = target
    data = open(newf, "rb").read()
    if not re.search(rb"[\xD0-\xD4][\x80-\xBF]", data):
        data_o = open(oldf, "rb").read()
        if not re.search(rb"[\xD0-\xD4][\x80-\xBF]", data_o):
            log(f"[csv] apply: в .new нет кириллицы, в исходном .mod тоже нет — возможно, нечего переводить"); 
        else:
            os.remove(newf); log(f"[csv] apply: откат (в .new нет кириллицы, в исходник был есть)"); return False
    os.replace(newf, oldf)
    log(f"[csv] [OK] RU-мод записан: {target}")
    return True

def main(argv):
    TM = _tm()
    ap = argparse.ArgumentParser(prog="csv_mod.py", description="Экспорт/импорт translate.csv (оригинал|перевод) для .mod в Steam/Workshop.")
    ap.add_argument("cmd", choices=["export", "import"])
    ap.add_argument("mods", nargs="*", help="имя мода или id (несколько); --list не требуется")
    ap.add_argument("--list", action="store_true", help="показать все моды (id + имя) и выйти")
    a = ap.parse_args(argv)
    if a.cmd == "list" or (a.cmd in ("export","import") and not a.mods and a.list):
        for m in list_all(TM):
            print(f"{m.get('id','')}\t{m.get('name','')}\t{os.path.basename(m.get('modfile') or '')}")
        return 0
    if not a.mods and not a.list:
        print("usage: csv_mod.py <export|import> <mod-имя-или-id> [моды...]" )
        print("       csv_mod.py <export|import> --list")
        return 2
    rc = 0
    mods = a.mods
    for i, name in enumerate(mods, 1):
        info = resolve(name, TM)
        if not info: rc = 1; continue
        print(f"мод: {name}")
        print(f"папка: {os.path.dirname(info['target'])}")
        print(f".mod: {info['target']}")
        print(f"кеш: hash={info['h']}  entries={len(info['entries'])}")
        tgt_dir = os.path.dirname(info["target"])
        ok = export_csv(tgt_dir, info["entries"], info["mfile"], info["target"], print) if a.cmd == "export" else import_csv(tgt_dir, info["entries"], info["mfile"], info["target"], print)
        if not ok: rc = 1
        if i < len(mods): print("-" * 50)
    return rc

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
