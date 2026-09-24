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
# 2026-09-24 (найдено по коду BEEP saveLoadOrder/readModsCfg + Steam-тред + 2/2 живая
# корреляция 4 RUS-оверлеев): РЕАЛЬНАЯ включённость + порядок загрузки живут в
# data\\mods.cfg (строки вида "<Имя>.mod", CRLF). __mods.list — это авто-каталог
# Workshop ("disabled appear only in _mods.list", Steam) — туда вставать мало.
MODS_CFG   = os.path.join(GAME, "data", "mods.cfg")
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


# ---------------- data/mods.cfg — РЕАЛЬНАЯ включённость (найдено 2026-09-24) ----------------
# Модель (код BEEP: readModsCfg -> active, saveLoadOrder -> write):
#   включён  = строка "<Имя>.mod" есть в data\\mods.cfg;
#   порядок  = позиция строки (поздний выигрывает, как и в __mods.list);
#   выключен = в __mods.list виден, в mods.cfg НЕ виден.
# Формат: CRLF, каждая строка заканчивается ".mod" (проверено по живой файлу).
def _cfg_lines():
    """Строки mods.cfg (без BOM/пустых). Файла нет -> []."""
    if not os.path.exists(MODS_CFG):
        return []
    data = open(MODS_CFG, "rb").read()
    return [l.decode("utf-8", "replace").strip() for l in data.replace(b"\r\n", b"\n").split(b"\n") if l.strip()]


def _cfg_write(lines):
    """Атомарная запись mods.cfg (CRLF, UTF-8 — BEEP пишет utf8, имена модов кириллицей)."""
    tmp = MODS_CFG + ".tmp"
    open(tmp, "wb").write(("\r\n".join(lines) + "\r\n").encode("utf-8"))
    os.replace(tmp, MODS_CFG)


def backup_cfg(tag="install"):
    """Бэкап mods.cfg РЯДОМ С ФАЙЛОМ (как у BEEP: mods.cfg.backup + у нас датируемый)."""
    if not os.path.exists(MODS_CFG):
        return None
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = "mods.cfg.%s.%s.bak" % (ts, tag)
    shutil.copy2(MODS_CFG, os.path.join(os.path.dirname(MODS_CFG), bak))
    return bak


def enable_in_cfg(ru_name, orig_name):
    """Включает оверлей: строка '<ru_name>.mod' СРАЗУ ПОСЛЕ строки оригинала в mods.cfg.
    Idempotent (уже есть — просто репозиционирует/проверяет). Возвращает (ok, msg)."""
    if not os.path.exists(MODS_CFG):
        return False, "data/mods.cfg не существует — не вношу включённость"
    bak = backup_cfg("enable")
    lines = _cfg_lines()
    ru_line = ru_name + ".mod"
    def norm(x):
        b = x[:-4] if x.lower().endswith(".mod") else x
        return (b + ".mod").lower()
    have_ru = any(norm(l) == norm(ru_line) for l in lines)
    if have_ru:
        # уже включён — проверяем/исправляем позицию относительно оригинала
        idxs = [i for i, l in enumerate(lines) if norm(l) == norm(ru_line)]
        i_ru = idxs[0]
        i_o = next((i for i, l in enumerate(lines) if norm(l) == norm(orig_name + ".mod")), None)
        if i_o is not None and (i_ru != i_o + 1):
            rest = [l for l in lines if not (norm(l) == norm(ru_line))]
            i2 = next(i for i, l in enumerate(rest) if norm(l) == norm(orig_name + ".mod"))
            rest.insert(i2 + 1, ru_line)
            _cfg_write(rest)
            return True, "уже в mods.cfg; позиция откорректирована сразу после оригинала"
        return True, "уже в mods.cfg"
    # вставляем сразу после оригинала; оригинала нет — в конец
    out, seen = [], False
    for l in lines:
        out.append(l)
        if not seen and norm(l) == norm(orig_name + ".mod"):
            out.append(ru_line); seen = True
    if not seen:
        out.append(ru_line)
    _cfg_write(out)
    # read-back verification
    vb = _cfg_lines()
    ok = norm(ru_line) in [norm(l) for l in vb]
    msg = ("'+%s%s' в mods.cfg" % (ru_line, " (после оригинала)" if seen else " (оригинала нет — в конец)"))
    if bak:
        msg += "; БЭКАП: %s" % os.path.basename(bak)
    return ok, msg


def disable_in_cfg(ru_name):
    """Выключает оверлей: убирает строку из mods.cfg (оставляет в __mods.list как каталог).
    Возвращает (removed, bak|None)."""
    if not os.path.exists(MODS_CFG):
        return False, None
    bak = backup_cfg("disable")
    lines = _cfg_lines()
    def norm(x):
        b = x[:-4] if x.lower().endswith(".mod") else x
        return (b + ".mod").lower()
    target = norm(ru_name)
    new = [l for l in lines if norm(l) != target]
    if len(new) == len(lines):
        return False, None
    _cfg_write(new)
    return True, bak


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
    # 2026-09-24: РЕАЛЬНАЯ включённость = data\mods.cfg (BEEP: readModsCfg->active)
    ok_c, msg_c = enable_in_cfg(ru_name, name)
    print("   " + msg_c)

    print("\nГОТОВО. Запусти игру — '%s' должен быть включён (строки в __mods.list И в data\\mods.cfg)," % ru_name)
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
    # 2026-09-24: выключить из data/mods.cfg (реальная включённость)
    try:
        removed, cbak = disable_in_cfg(ru_name)
        if removed:
            print("mods.cfg: '-%s.mod' (бэкап: %s)" % (ru_name, os.path.basename(cbak) if cbak else "—"))
        else:
            print("mods.cfg: строки '%s.mod' не было" % ru_name)
    except Exception as ex:
        print("mods.cfg: не смог выключить: %s" % ex)
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
    # 2026-09-24: реальная включённость = data/mods.cfg (BEEP: readModsCfg -> active)
    cfgset = set(l.lower() for l in _cfg_lines()) if os.path.exists(MODS_CFG) else set()
    found = 0
    for f in sorted(os.listdir(MODS_DIR)):
        if f.endswith(" RUS") and os.path.isdir(os.path.join(MODS_DIR, f)):
            modf = [x for x in os.listdir(os.path.join(MODS_DIR, f)) if x.endswith(".mod")]
            enabled = any(l.lower() in ((f + ".mod").lower(), f.lower()) for l in cfgset)
            seen = f in inlist
            if enabled:
                st = "вкл"
            elif seen:
                st = "виден/не вкл"
            else:
                st = "невидим"
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
