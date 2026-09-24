"""untranslated.py — «сколько строк ещё непереведено» для каждого мода.

Источники «уже переведено» (строка считаем переведённой, если найдется ХОТЯ БЫ
один русский вариант в одном из этих мест):
  1. наш кэш    — <state>/<md5-мод>_mapping.json (ru непустое), точный индекс i;
  2. RU-близнец — mod переводa поставленный пользователем (Workshop/папка mods),
                 原名 ru_twins.find_twin(); строка совпадает по original/key;
  3. .po игры   — locale/<target> (prefilter.game_po_map, en_lower → ru);
  4. reuse-пул  — dict.json + state/* + po-модов (prefilter.lookup).

Остальное = «нужно перевести». Отчёт мемоизируется в
<state>/_untranslated_report.json: пересчёт, только когда что-то изменилось
(md5 мода / max mtime кэшей / dict.json).
"""
from __future__ import annotations

import glob
import hashlib
import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))

_REPORT_CACHE_SUFFIX = "_untranslated_report.json"


def _md5_file(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:12]


def _fingerprint(mods, state_dir):
    """Стабильный fingerprint: md5 каждого .mod + max mtime в state/ и dict.json.

    Если ничего не изменилось — отчёт из прошлого раза по-прежнему честный
    (каждый из 4 источников покрыт: кэш/state — mtime; мода — md5;
    dict.json/po — mtime; близнецы — это тоже state/вешки .mod).
    """
    parts = []
    for m in mods:
        if m.get("modfile") and os.path.exists(m["modfile"]):
            parts.append(_md5_file(m["modfile"]))
    ts = []
    if state_dir and os.path.isdir(state_dir):
        for f in glob.glob(os.path.join(state_dir, "*_entries.json")) + \
                 glob.glob(os.path.join(state_dir, "*_mapping.json")) + \
                 glob.glob(os.path.join(state_dir, "_reuse_pool_cache.json")):
            try:
                ts.append(os.path.getmtime(f))
            except OSError:
                pass
    here_dict = os.path.join(_HERE, "dict.json")
    if os.path.exists(here_dict):
        ts.append(os.path.getmtime(here_dict))
    return "|".join(parts) + "#" + ("%.3f" % max(ts) if ts else "0")


def untranslated_stats(mods, state_dir, verbose=None):
    """Для списка модов вернуть [(мод, total, untranslated), ...].

    mods — элементы cache.all_mods() (нужен modfile). Строки читаются из
    закешированных <state>/<md5>_entries.json (если кэша нет — extract C#-ом,
    кэш переживёт пересчёт).
    """
    # heavy imports лениво (translate_mods тянет prefilter + console)
    import cache as _cache
    from kmt_paths import resolve as _resolve
    _cfg = json.load(open(os.path.join(_HERE, "config.json"), encoding="utf-8"))
    _p = _cfg.get("paths", {})
    _target = _cfg.get("target_lang") or "ru_RU"
    _game = _resolve(_p.get("game", ""))
    _locale = _resolve(_p.get("locales_dir")) or os.path.join(_game, "locale", _target)
    _po_paths = [
        os.path.join(_locale, "gamedata.po"),
        os.path.join(_locale, "LC_MESSAGES", "main.po"),
    ]
    import prefilter
    prefilter.configure(os.path.join(_HERE, "dict.json"), _po_paths, state_dir)
    import ru_twins
    # 2026-09-24: единый ID-based предикат (совместно с translate_mods/search_mods)
    import game_localization as _glz
    _glz.configure(po_paths=_po_paths, game_dir=_game)
    _ign_desc = bool((_cfg.get("translate") or {}).get("ignore_mod_description", True))
    amods_all = _cache.all_mods()
    gpo = prefilter.game_po_map()  # memoized: {en_lower: ru} из .po игры
    log = verbose or (lambda *_a: None)
    out = []
    for m in mods:
        mf = m.get("modfile")
        total = untr = 0
        if not (mf and os.path.exists(mf)):
            out.append((m, 0, 0))
            continue
        # 2026-09-24: RU-оверлеи (<имя> RUS) — производные наших переводов:
        # их текст УЖЕ русский. В список «нужно перевести» они НЕ входят.
        if (m.get("name") or "").strip().lower().endswith(" rus"):
            out.append((m, 0, 0))
            continue
        h = _md5_file(mf)
        efile = os.path.join(state_dir, f"{h}_entries.json")
        mfile = os.path.join(state_dir, f"{h}_mapping.json")
        # (1) наш кэш перевода: индекс строки → RU
        own = {}
        if os.path.exists(mfile):
            try:
                own = {str(x["i"]): x["ru"]
                       for x in json.load(open(mfile, encoding="utf-8")) if x.get("ru")}
            except Exception:
                own = {}
        # строки входа из кэша (иначе — extract через C# один раз)
        entries = None
        if os.path.exists(efile):
            try:
                entries = json.load(open(efile, encoding="utf-8"))
            except Exception:
                entries = None
        if entries is None:
            try:
                import cli
                os.makedirs(state_dir, exist_ok=True)
                rc, _ = cli.run(["extract", mf, efile], timeout=300)
                if rc == 0 and os.path.exists(efile):
                    entries = json.load(open(efile, encoding="utf-8"))
            except Exception:
                log(f"  [!] extract не удался: {m.get('name')}")
                out.append((m, 0, 0))
                continue
        for e in entries:
            # 2026-09-24: единый ID-based предикат — совпадает с translate_mods
            # и search_mods. Строка, которую НЕ переводим (oписание-мод при
            # ignore_mod_description, game-локализация по object-ID) — НЕ
            # кандидат: НЕ в total (знаменатель!), НЕ в untr, НЕ в CSV, НЕ в
            # RUS-моде. Тогда инвариант: терминал == CSV == RUS-мод.
            if not _glz.should_translate(e, _ign_desc):
                continue  # не кандидат — вообще в счёте не участвует
            total += 1  # только переводимые строки — в знаменатель
            en = e.get("original") or ""
            if own.get(str(e.get("i"))):
                continue  # (1) наш кэш
            try:
                if ru_twins.lookup_pair(mf, e.get("key"), amods_all):
                    continue  # (2) RU-близнец
            except Exception:
                pass
            # (3) .po игры по тексту — ДЖОЙНТ с game_localizes: по object-ID уже
            # выше (should_translate); по тексту остаётся для записей без record-ключ
            if en and en.lower() in gpo:
                continue  # (3) .po игры
            if en and prefilter.lookup(en)[0]:
                continue  # (4) reuse-пул (dict/state/po)
            untr += 1
        out.append((m, total, untr))
    return out


def cached_report(mods, state_dir, refresh=False):
    """untranslated_stats() с файло-кэшем (быстрый повторный запуск)."""
    fp = _fingerprint(mods, state_dir)
    cfile = os.path.join(state_dir, _REPORT_CACHE_SUFFIX)
    if not refresh and os.path.exists(cfile):
        try:
            c = json.load(open(cfile, encoding="utf-8"))
            if c.get("fp") == fp:
                by_mod = {}
                for path, st in (c.get("mods") or {}).items():
                    by_mod[path] = st
                out = []
                for m in mods:
                    st = by_mod.get(os.path.abspath(m.get("modfile") or ""))
                    if st:
                        out.append((m, st.get("total", 0), st.get("untranslated", 0)))
                    else:
                        out.append((m, 0, 0))
                return out
        except Exception:
            pass
    out = untranslated_stats(mods, state_dir)
    try:
        c = {"fp": fp, "mods": {os.path.abspath(m.get("modfile") or ""):
                               {"total": t, "untranslated": u} for (m, t, u) in out}}
        os.makedirs(state_dir, exist_ok=True)
        tmp = cfile + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(c, f)
        os.replace(tmp, cfile)
    except Exception:
        pass
    return out
