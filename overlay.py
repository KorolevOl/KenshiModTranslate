#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
overlay.py — ядро алгоритма «RU-оверлей поверх Workshop-мода».

Механика (проверена в игре 2026-09-24 на Medieval_Crossbows):
  * RU-оверлей = отдельный маленький .mod в kenshi\\mods\\<Имя> RUS\\<Имя> RUS.mod
    (эталонный паттерн Nude Mod HD Rus: имя строки = имя папки = имя файла).
  * Внутри — ТОЛЬКО собственные объекты мода (CLI apply 4-й arg = keepOnly),
    чужие базовые записи (gamedata.base / rebirth и т.п.) не копируются.
  * Строка оверлея вставляется в data\__mods.list СРАЗУ ПОСЛЕ строки оригинала
    (поздний в списке выигрывает по object-ID). Перед правкой — автобэкап
    __mods.list РЯДОМ С ИГРОЙ (kenshi\data\<ts>.bak) — T: это RAM-диск.
  * Исходный EN-.mod НЕ трогаем: авторское обновление меняет .mod, оверлей
    живёт отдельно и продолжает действовать — перевод не слетает.

CLI:
  python overlay.py install <имя|id> [--mapping файл] [--dry-run]
  python overlay.py uninstall <имя|id>
  python overlay.py list
"""
import os, sys, re, shutil, subprocess, datetime, json

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.dont_write_bytecode = True
import kmt_paths
_resolve = kmt_paths.resolve
import cli  # единый CLI wrapper + find_mod + mod_hash
CFG = json.load(open(os.path.join(HERE, "config.json"), encoding="utf-8"))
P = CFG["paths"]
GAME     = _resolve(P["game"])
WORKSHOP = _resolve(P["workshop"])
DOTNET   = _resolve(P["dotnet"])
CLI      = _resolve(P["modtranslate_cli"])
STATE    = _resolve(P["state"])
MODS_DIR   = os.path.join(GAME, "mods")
MODS_LIST  = os.path.join(GAME, "data", "__mods.list")
TSCRATCH   = r"T:"


# --- re-export из cli.py (единый источник, дубли убраны 2026-09-24) ---
find_mod = cli.find_mod
# overlay: строгий режим — только .orig_<h>.backup рядом; md5-fallback ВКЛЮЧАЕТСЯ
# search_mods (там это легитимно). Для overlay: без fallback (ключ кэша — ТОЛЬКО
# hash из .orig-бэкапа), иначе state/<md5>_mapping.json — неверный ключ.
mod_hash = lambda modfile: cli.mod_hash(modfile, fallback_md5=False)
run_cli  = lambda args, timeout=180: cli.run(args, timeout)


def backup_list(tag):
    """Бэкап __mods.list РЯДОМ С ИГРОЙ (kenshi\\data\). T: это RAM-диск —
    на нём бэкап ненадёжен (перезагрузка = утрата)."""
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = "__mods.list.%s.%s.bak" % (ts, tag)
    shutil.copy2(MODS_LIST, os.path.join(os.path.dirname(MODS_LIST), bak))
    return os.path.basename(bak)


def read_lines():
    return [l.rstrip().decode("latin-1") for l in open(MODS_LIST, "rb").read().split(b"\r\n") if l.strip()]


def write_lines(lines):
    """Атомарно: сначала temp-файл, потом replace (защита от обрыва посреди записи)."""
    tmp = MODS_LIST + ".tmp"
    open(tmp, "wb").write(("\r\n".join(lines) + "\r\n").encode("latin-1", "replace"))
    os.replace(tmp, MODS_LIST)


def install(query, mapping_file=None, dry_run=False):
    cands = find_mod(query)
    if not cands:
        print("мод не найден в Workshop: %r" % query); return 1
    if len(cands) > 1:
        print("несколько совпадений:")
        for appid, d, name, mf in cands:
            print("   %s  (id %s)" % (name, appid))
        return 1
    appid, mdir, name, modfile = cands[0]
    if name.lower().endswith("rus"):
        print("имя мода уже заканчивается 'RUS' — вероятно, это оверлей. Отказ."); return 1

    ru_name = name + " RUS"
    h = mod_hash(modfile)
    mapping = mapping_file or (os.path.join(STATE, "%s_mapping.json" % h) if h else None)
    if not mapping or not os.path.exists(mapping):
        print("нет RU-кэша: %s" % (mapping or "<не найден>"))
        print("сначала переведи: python translate_mods.py %s" % name)
        return 1
    n_map = len(json.load(open(mapping, encoding="utf-8")))
    work = os.path.join(TSCRATCH, ".overlay_%s" % name)
    out_mod = os.path.join(work, ru_name + ".mod")
    vjson = os.path.join(work, "v.json")

    print("мод:         %s (id %s)" % (name, appid))
    print("EN-источник: %s  (НЕ будет тронут)" % os.path.basename(modfile))
    print("RU-кэш:      %s  (%d строк)" % (os.path.basename(mapping), n_map))
    print("оверлей:     mods\\%s\\%s.mod" % (ru_name, ru_name))
    if dry_run:
        print("[dry-run] дальше: apply -> verify -> install -> __mods.list (с бэкапом)"); return 0

    os.makedirs(work, exist_ok=True)
    for old in (out_mod, vjson):
        if os.path.exists(old):
            os.remove(old)

    # 1) apply: EN-мод + RU-маппинг + keepOnly=name -> маленький оверлей-мод
    rc, log = run_cli(["apply", modfile, mapping, out_mod, name])
    if rc != 0 or not os.path.exists(out_mod):
        print("apply СБОЙ:\n" + log); return 1
    for line in log.splitlines():
        if "keepOnly" in line or "осталось" in line:
            print("   " + line.strip())

    # 2) verify: round-trip extract — только собственные записи + кириллица
    rc, log = run_cli(["extract", out_mod, vjson])
    if rc != 0:
        print("verify extract СБОЙ:\n" + log); return 1
    v = json.load(open(vjson, encoding="utf-8"))
    own = [e for e in v if name.lower() in (e.get("key") or "").lower()]
    cyr = [e for e in own if re.search(r"[\u0400-\u04ff]", e.get("original") or "")]
    if not own or not cyr:
        print("verify СБОЙ: собственных=%d, с кириллицей=%d" % (len(own), len(cyr))); return 1
    print("   verify: собственных %d, переведено %d (ok)" % (len(own), len(cyr)))

    # 3) install: каталог-оверлей по эталонному паттерну
    tgt_dir = os.path.join(MODS_DIR, ru_name)
    if os.path.exists(tgt_dir):
        bak = ".old_%s_%s" % (name, datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
        # старая версия оверлея — рядом с игрой (НЕ на T: — там RAM-диск)
        shutil.move(tgt_dir, os.path.join(GAME, bak))
        print("   старая версия оверлея: %s" % os.path.join(GAME, bak))
    os.makedirs(tgt_dir, exist_ok=True)
    tgt = os.path.join(tgt_dir, ru_name + ".mod")
    shutil.copy2(out_mod, tgt)
    print("   установлен: %s (%d B)" % (tgt, os.path.getsize(tgt)))

    # 4) __mods.list: бэкап + строка оверлея СРАЗУ ПОСЛЕ оригинала
    lines = read_lines()
    if ru_name in [l.strip() for l in lines]:
        print("   строка уже есть в __mods.list (повторная установка)")
    else:
        bak = backup_list("install")   # рядом с игрой: kenshi\data\__mods.list.<ts>.install.bak
        out, done = [], False
        for l in lines:
            out.append(l)
            if not done and l.strip() == name:
                out.append(ru_name); done = True
        if not done:
            print("   ВНИМАНИЕ: строка оригинала '%s' НЕ найдена в __mods.list." % name)
            print("   Игра при валидации УДАЛЯЕТ строку, которой нет соответствующий .mod.")
            print("   Если оригинал включён под другим именем (Workshop title != файл),")
            print("   строку надо вписать ВРУЧНУЮ после этого имени.")
        write_lines(out)
        print("   __mods.list: +'%s'%s; БЭКАП: %s"
              % (ru_name, " (после оригинала)" if done else " (В КОНЕЦ!)", bak))

    print("\nГОТОВО. Запусти игру — '%s' должен быть включён (строка в списке = включён), и" % ru_name)
    print("имена объектов мода теперь на русском. Откат: python overlay.py uninstall %s" % name)
    return 0


def uninstall(query):
    cands = find_mod(query)
    if not cands:
        print("мод не найден: %r" % query); return 1
    name = cands[0][2]
    ru_name = name + " RUS"
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = backup_list("uninstall")
    lines = read_lines()
    new = [l for l in lines if l.strip() != ru_name]
    if len(new) == len(lines):
        print("строки '%s' в списке не было" % ru_name)
    else:
        write_lines(new)
        print("__mods.list: '-%s' (бэкап: %s)" % (ru_name, bak))
    tgt = os.path.join(MODS_DIR, ru_name)
    if os.path.isdir(tgt):
        d = os.path.join(GAME, ".old_%s_%s" % (name, ts))
        shutil.move(tgt, d)
        print("каталог оверлея: %s" % d)
    else:
        print("каталога оверлея не было")
    print("ОТКАТ выполнен. Возврат: python overlay.py install %s" % name)
    return 0


def list_installed():
    if not os.path.isdir(MODS_DIR):
        print("каталога mods/ нет"); return 0
    inlist = [l.strip() for l in read_lines()]
    found = 0
    for f in sorted(os.listdir(MODS_DIR)):
        if f.endswith(" RUS") and os.path.isdir(os.path.join(MODS_DIR, f)):
            modf = [x for x in os.listdir(os.path.join(MODS_DIR, f)) if x.endswith(".mod")]
            st = "вкл" if f in inlist else "выкл"
            found += 1
            print("  [%s] %-40s %s" % (st, f, modf[0] if modf else "(нет .mod)"))
    if not found:
        print("RU-оверлеев в mods/ не найдено")
    return 0


def main():
    a = sys.argv[1:]
    if not a:
        print(__doc__); return 1
    cmd = a[0]
    if cmd == "list":
        return list_installed()
    if cmd == "uninstall":
        if len(a) < 2:
            print("нужно имя мода"); return 1
        return uninstall(a[1])
    if cmd == "install":
        mapping, dry, q = None, False, None
        i = 1
        while i < len(a):
            if a[i] == "--mapping" and i + 1 < len(a):
                mapping = a[i + 1]; i += 2
            elif a[i] == "--dry-run":
                dry = True; i += 1
            else:
                q = a[i]; i += 1
        if not q:
            print(__doc__); return 1
        return install(q, mapping_file=mapping, dry_run=dry)
    print("неизвестная команда: %s" % cmd); print(__doc__); return 1


if __name__ == "__main__":
    sys.exit(main())
