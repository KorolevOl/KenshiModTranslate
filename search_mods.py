#!/usr/bin/env python3
"""
search_mods.py — поиск фразы по модам Kenshi и по встроенным файлам игры.

Слои (по порядку):
  1) state-кеш: EN-исходники + RU-переводы (state/*_entries.json, state/*_mapping.json)
  2) .mod в Workshop
  3) .mod в игре (kenshi/data/*.mod — базовая локализация: rebirth.mod, Dialogue.mod и др.)
  4) .mod в папке kenshi/mods/<mod>/ (ручные моды, не из Workshop)
  5) .po локализация ЦЕЛЕВОГО языка (config "target_lang", дефолт ru_RU):
     kenshi/locale/<lang>/*.po, kenshi/mods/<mod>/locale/*.po, locale Workshop-модов
  6) описания модов (desc.txt / *.txt в корневой папке мода, Workshop)
  7) .dll (бинарный поиск, --dll)

Таблицы: EN | RU | Поле | Мод. «Поле» — имя поля .mod-записи
(description / name / building category / text0 / …): 'name'-подобные —
имена-ключи рекордов (переводить нельзя), остальное — отображаемый текст.
Имя поля достаётся из кеша (key записи) либо C#-парсером .mod
(kenshi-modtranslate extract) для чистых (откатанных) модов.

Каждый найденный .mod-файл получает номер. После выдачи результатов —
пользователь вводит номера через запятую или пробел (или 'a' = все, 'q' = выход)
и перевод запускается прямо из search_mods.py (subprocess translate_mods.py --file).

Примеры:
    python search_mods.py "I only deal with members."
    python search_mods.py "помощь" --ru
    python search_mods.py "little help" --yes --force      # без ввода (авто-все)
    python search_mods.py "a little" --en --no-translate   # только поиск
"""
import os, sys, json, re, glob, argparse, subprocess

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import kmt_paths  # resolve paths (config.json-driven)
import textutil  # parse_po_file: единый парсер .po

CFG = json.load(open(os.path.join(BASE, "config.json"), encoding="utf-8"))
P   = CFG["paths"]

# 2026-09-24: ЕДИНЫЙ предикат «нужен ли перевод / покажет ли игра сама» —
# game_localization (по OBJECT-ID, не по тексту). Подхватываем его здесь,
# чтобы таблицы и меню выбора корректно считали игровые записи и
# описания модов (ignore_mod_description, default ON).
import game_localization as glz
_g_game  = P.get("game", "")
_g_lang  = CFG.get("target_lang", "ru_RU")
glz.configure([os.path.join(_g_game, "locale", _g_lang, "gamedata.po"),
               os.path.join(_g_game, "locale", _g_lang, "LC_MESSAGES", "main.po")])
_IGNORE_MOD_DESC = bool(CFG.get("translate", {}).get("ignore_mod_description", True))


def _glz_flag(key):
    """2026-09-24: метка для таблицы search_mods:
    • 'ИГРА' — запись локализует сама игра (её (objectID, owner) ∈ #: .po);
    • 'ОПИС' — описание самого МОДА (ignore_mod_description, default ON).
    Пустая строка, если строка НАДО переводить (своя).
    """
    if not key:
        return ""
    # игровое: только у записей с record-ID (описания не имеют record)
    try:
        if glz.game_localizes(key):
            return "ИГРА"
    except Exception:
        pass
    if _IGNORE_MOD_DESC and glz.is_mod_description(key):
        return "ОПИС"
    return ""
ST        = kmt_paths.resolve(P["state"])
WORKSHOP  = kmt_paths.resolve(P["workshop"])
GAME      = kmt_paths.resolve(P["game"])
TARGET_LANG = (CFG.get("target_lang") or P.get("target_lang") or "ru_RU").lower()
# Целевой язык локализации: слой .po и RU-фолбэк берут переводы ТОЛЬКО из
# этого языка (по умолчанию ru_RU). Меняется в config.json: "target_lang".

TRANSLATABLE_KINDS = ("workshop", "game_data", "game_mods")

# ---------------------------------------------------------------- helpers --

def norm(s: str) -> str:
    """Нормализация: убрать bbcode-ссылки [link=...], схлопнуть whitespace, нижний регистр."""
    s = re.sub(r"\[/?[^\]]*\]", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.lower()

def encodings_text(data: bytes):
    if data.startswith(b"\xff\xfe"):
        return data[2:].decode("utf-16-le", errors="replace")
    try:
        return data.decode("utf-8", errors="replace")
    except Exception:
        return None

def make_snippet(text: str, pos: int, needle_len: int, window: int = 80) -> str:
    s = max(0, pos - window)
    e = min(len(text), pos + needle_len + window)
    frag = text[s:e]
    # Убираем null-байты и прочие невидимки (бинарные .mod / .dll)
    frag = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", frag)
    return frag.replace("\r\n", "\\n").replace("\r", "\\n").replace("\n", "\\n")


# ---------------------------------------------------------------- layers --

def _iter_hits_in(path, needle, kind, want_en=True, want_ru=True, is_po=False, is_dll=False):
    """Yield one hit dict per occurrence of needle in the given file."""
    nd = norm(needle)
    try:
        data = open(path, "rb").read()
    except Exception:
        return
    if is_dll:
        try:
            txt = data.decode("latin-1", errors="ignore")
        except Exception:
            return
    else:
        txt = encodings_text(data)
        if txt is None:
            return
    ntxt = " ".join(txt.split())
    low = ntxt.lower()
    start = 0
    count = 0
    while True:
        pos = low.find(nd, start)
        if pos < 0:
            break
        count += 1
        if count > 200:  # cap per file — huge files can match thousands of times
            break
        yield {
            "kind": kind,
            "path": path,
            "snippet": make_snippet(ntxt, pos, len(nd)),
        }
        start = pos + max(1, len(nd))


def iter_state_hits(needle, want_en, want_ru):
    """Yield hits from state cache."""
    nd = norm(needle)
    names = {}
    try:
        import verify_translations as VT
        names = VT.build_name_map()
    except Exception:
        pass
    if not os.path.isdir(ST):
        return
    for base in sorted(os.listdir(ST)):
        if not base.endswith("_entries.json"):
            continue
        h = base[: -len("_entries.json")]
        ep = os.path.join(ST, base)
        mp = os.path.join(ST, h + "_mapping.json")
        if not (os.path.exists(ep) and os.path.exists(mp)):
            continue
        try:
            entries = json.load(open(ep, encoding="utf-8"))
            mapping = json.load(open(mp, encoding="utf-8"))
        except Exception:
            continue
        emap = {str(e.get("i")): (e.get("original") or e.get("t") or "") for e in entries}
        ekeys = {str(e.get("i")): (e.get("key") or "") for e in entries}
        for m in mapping:
            i = str(m.get("i"))
            en = emap.get(i, "")
            ru = (m.get("r") or m.get("ru") or "")
            en_hit = want_en and nd in norm(en)
            ru_hit = want_ru and nd in norm(ru)
            if en_hit or ru_hit:
                _entry_key = ekeys.get(i, "")
                txt = en if en_hit else ru
                t = " ".join((txt or "").split())
                pos = t.lower().find(nd)
                yield {
                    "kind": "cache",
                    "path": None,
                    "mod": names.get(h, h),
                    "hash": h,
                    "row": i,
                    "en": en,
                    "ru": ru,
                    "field": _short_key(_entry_key),
                    "snippet": make_snippet(t, pos, len(nd)),
                }


def find_mod_files_under(root):
    if not os.path.isdir(root):
        return []
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        for f in filenames:
            if f.lower().endswith(".mod"):
                out.append(os.path.join(dirpath, f))
    return out


def find_po_files():
    """.po-файлы ЦЕЛЕВОГО языка (config 'target_lang') в game/locale,
    kenshi\mods и Workshop-модах (locale/**)."""
    def _collect(root):
        out = []
        if not os.path.isdir(root):
            return out
        for dirpath, dirnames, filenames in os.walk(root):
            for f in filenames:
                if f.lower().endswith(".po"):
                    p = os.path.join(dirpath, f)
                    if po_file_lang(p) == TARGET_LANG:
                        out.append(p)
        return out
    out = _collect(os.path.join(GAME, "locale")) \
       + _collect(os.path.join(GAME, "RE_Kenshi", "locale")) \
       + _collect(os.path.join(GAME, "mods"))
    if os.path.isdir(WORKSHOP):
        for moddir in os.listdir(WORKSHOP):
            out += _collect(os.path.join(WORKSHOP, moddir, "locale"))
    seen, uniq = set(), []
    for p in out:
        q = os.path.normcase(p)
        if q not in seen:
            seen.add(q)
            uniq.append(p)
    return uniq


def find_desc_files_under(root):
    if not os.path.isdir(root):
        return []
    out = []
    for d in glob.glob(os.path.join(root, "*")):
        if not os.path.isdir(d):
            continue
        try:
            for f in os.listdir(d):
                if f.lower().endswith((".txt", ".desc")) and "changelog" not in f.lower():
                    out.append(os.path.join(d, f))
        except Exception:
            pass
    return out


def find_dll_files_under(root):
    if not os.path.isdir(root):
        return []
    return [os.path.join(dp, f) for dp, dn, fn in os.walk(root) for f in fn if f.lower().endswith(".dll")]


# ------------------------------------ cache lookup: EN строка -> RU перевод --
_HASH_MEMO = {}
_CACHE_MEMO = {}
_RUROWS_MEMO = {}


def _hash_for_mod(path):
    """Якорь кеша мода: из соседнего .orig_<h>.backup, иначе md5(файла).

    2026-09-24: логика вынесена в cli.mod_hash (единый источник с overlay.py,
    rebuild_mods.py). Здесь только memo, чтобы не перечитывать файлы в горячих циклах.
    """
    key = os.path.normcase(os.path.abspath(path))
    if key in _HASH_MEMO:
        return _HASH_MEMO[key]
    import cli
    h = cli.mod_hash(path)  # md5-fallback по умолчанию (совместимо со старым поведением)
    _HASH_MEMO[key] = h
    return h


def _load_cache(h):
    """(entries, mapping i->ru) кеша мода; (None, {}) если кеша нет."""
    if h in _CACHE_MEMO:
        return _CACHE_MEMO[h]
    entries, mapping = None, {}
    ep = os.path.join(ST, h + "_entries.json")
    mp = os.path.join(ST, h + "_mapping.json")
    try:
        if os.path.isfile(ep):
            entries = json.load(open(ep, encoding="utf-8"))
        if os.path.isfile(mp):
            mapping = {str(x.get("i")): (x.get("ru") or "")
                       for x in json.load(open(mp, encoding="utf-8"))}
    except Exception:
        entries, mapping = None, {}
    _CACHE_MEMO[h] = (entries, mapping)
    return _CACHE_MEMO[h]


def ru_rows_for_needle(h, needle):
    """Список (EN-строка, RU-перевод) из кеша мода, где needle встречается
    в EN-исходнике ИЛИ в RU-переводе строки. Вывод: (EN, RU) парой — всегда видно
    и оригинал, и перевод, независимо от того, по какой стороне искали."""
    key = (h, norm(needle))
    if key in _RUROWS_MEMO:
        return _RUROWS_MEMO[key]
    out = []
    if h:
        entries, mapping = _load_cache(h)
        if entries:
            nd = norm(needle)
            for e in entries:
                i = str(e.get("i"))
                en = e.get("original") or e.get("t") or ""
                ru = mapping.get(i, "") or ""
                if not en:
                    continue
                if nd in norm(en) or (ru and nd in norm(ru)):
                    fld = _short_key(e.get("key") or "")
                    # 2026-09-24: пометка игнорируемых (игра локализует /
                    # описание мода) — они «обслуживаются», а не «не переведены».
                    _f = _glz_flag(e.get("key") or "")
                    if _f:
                        fld = (fld + " ·" + _f) if fld else _f
                    out.append((en, ru, fld))
    out.sort(key=lambda t: len(t[0]))  # короткие (специфичные) строки выше
    _RUROWS_MEMO[key] = out
    return out


def _attach_ru(hits, needle):
    """Для .mod-hits приписать 'ru_rows' (EN, RU, Поле):
    1) наш кеш (state/), если есть — + пустые RU заполняем из .po локации;
    2) нет кеша — EN из C#-парсера (чистый текст, не бинарный мусор) +
       RU из .po локации (свой .po мода, затем .po игры);
    3) RU-близнец (2026-09-24) — если мод имеет "RU/RUS/Русский"-близнеца
       (пользователь установил перевод сам из Workshop), берём RU оттуда."""
    by_path = {}
    # Lazy-load RU-twin index (раз на процесс)
    try:
        import ru_twins as _rt
        import cache as _cache_for_twin
        _rt_all_mods = _cache_for_twin.all_mods()
    except Exception:
        _rt = None

    def resolve(p):
        if p in by_path:
            return by_path[p]
        rows = []
        chash = _hash_for_mod(p)
        if chash:
            rows = ru_rows_for_needle(chash, needle)
        po_idx = _po_index_for_mod(p)
        if po_idx and rows:
            rows = [(en, (ru or po_idx.get(_po_norm(en)) or ""), fld)
                    for en, ru, fld in rows]
        if not rows and po_idx:
            nd = _po_norm(needle)
            if nd:
                fm = _field_map_for_mod(p)
                for en, fld in sorted(fm.items(), key=lambda kv: len(kv[0])):
                    if nd in en:
                        _f = _glz_flag(fld)  # fld здесь = имя поля .mod
                        if _f:
                            fld = (fld + " ·" + _f) if fld else _f
                        rows.append((en, po_idx.get(_po_norm(en), ""), fld))
        # RU-близнец: заполняем пустые RU
        try:
            _rt2 = _rt
            if _rt2:
                # Используем twin_pairs (memoized, разовое вычисление)
                ap = os.path.abspath(p)
                tp = _rt2.twin_pairs(ap, _rt_all_mods)
                if tp:
                    _tw = {(ten or "").strip().lower(): (tru or "").strip()
                           for tk, ten, tru, tsrc in tp}
                    new_rows = []
                    changed = False
                    for en, ru, fld in rows:
                        nru = (ru or "").strip()
                        if not nru:
                            hit = _tw.get((en or "").strip().lower())
                            if hit:
                                nru = hit
                                changed = True
                        new_rows.append((en, nru, fld))
                    rows = new_rows
        except Exception:
            pass
        by_path[p] = rows
        return rows

    for h in hits:
        p = h.get("path")
        if not p or os.path.splitext(p)[1].lower() != ".mod":
            continue
        h["ru_rows"] = resolve(p)


_CSHARP_CACHE = {}   # path(normcase) -> {norm_orig: короткое_имя_поля}

def _short_key(raw_key):
    """Короткое имя поля из key записи. Два формата key:
       NEW (C#):   record{ID}_<поле>                    → <поле>
                    record102_name                      → name
                    record102_building category         → building category
       OLD (кеш):  record{ID}-<owner>.<поле>             → <поле>
                    record1886-gamedata.base_name        → name
                    record1531904-BuryYourTreasure.mod_building category → building category
    """
    k = (raw_key or "").strip()
    if not k:
        return ""
    if k == "description":
        return "description"
    if not k.startswith("record"):
        return k
    # OLD (кеш): record{ID}-<мод>.mod_<поле> / record{ID}-<owner>.<поле>
    #   маркер — дефис после ID; поле = фрагмент после ПОСЛЕДНЕГО _
    if "-" in k:
        tail = k[k.find("-") + 1:]
        if "_" in tail:
            tail = tail.rsplit("_", 1)[1]
    # NEW (C#-парсер): record{ID}_<поле> — поле после ПЕРВОГО _
    elif "_" in k:
        tail = k.split("_", 1)[1]
    else:
        return k
    if tail.startswith("base_"):
        tail = tail[5:]
    return tail


def _field_map_for_mod(path):
    """{norm(EN-текст): имя_поля} из C#-парсера (kenshi-modtranslate extract).
    Кэшируется по файлу; один вызов на файл (~0.1-0.2 c)."""
    key = os.path.normcase(os.path.abspath(os.fspath(path)))
    if key in _CSHARP_CACHE:
        return _CSHARP_CACHE[key]
    m = {}
    try:
        import time
        cfg = json.load(open(os.path.join(BASE, "config.json"), encoding="utf-8"))
        DOTNET = kmt_paths.resolve(cfg["paths"]["dotnet"])
        CLI = kmt_paths.resolve(cfg["paths"]["modtranslate_cli"])
        import tempfile
        fd, tmp = tempfile.mkstemp(suffix=".json", prefix="_kmt_keys_")
        os.close(fd)
        r = subprocess.run([DOTNET, CLI, "extract", os.fspath(path), tmp],
                           capture_output=True, timeout=30)
        if r.returncode == 0:
            data = json.load(open(tmp, encoding="utf-8"))
            for e in data:
                orig = (e.get("original") or "").strip()
                if not orig:
                    continue
                nm = orig.lower()
                if nm not in m:
                    m[nm] = _short_key(e.get("key") or "")
    except Exception:
        m = {}
    _CSHARP_CACHE[key] = m
    return m


def _field_for_hit(path, needle):
    """Имя поля строки в .mod (через C#-парсер кеша или новый extract).
    1) точное совпадение: needle = целому EN-тексту записи → его поле;
    2) иначе — самая КОРОтКАЯ запись, содержащая needle (чем короче строка,
       тем конкретнее поле: 'Beak Thing' попадает в name='Beak Thing', а не
       в длинный description). Пусто — если ни одна запись не содержит."""
    m = _field_map_for_mod(path)
    if not m:
        return ""
    nd = norm(needle)
    if not nd:
        return ""
    if nd in m:
        return m[nd] or ""
    best = None  # (len(orig), field)
    for orig, field in m.items():
        if not field or nd not in orig:
            continue
        if best is None or len(orig) < best[0]:
            best = (len(orig), field)
    return best[1] if best else ""


# ============================== .po (gettext) lookup ==========================
# Парсинг .po: textutil.parse_po_file (единый источник, используется и
# po_hints, и prefilter). Здесь только мемоизация + index для lookup.
_POIDX_MEMO = {}      # mod-path -> {norm(msgid) -> ru}
_PO_PAIRS_MEMO = {}   # po-path -> [(en, ru)]

def _po_norm(s):
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


_LOCALE_SEG_RE = re.compile(r"[A-Za-z]{2}_[A-Z]{2}")
_PO_LANG_MEMO = {}

def po_file_lang(path):
    """Язык .po-файла: сегмент xx_YY в пути (locale/ru_RU/…), а если его нет —
    из хедера "Language: xx_YY". Мемоизировано. Возвращает 'xx_yy' в нижнем
    регистре или '' (не удалось определить)."""
    key = os.path.normcase(os.path.abspath(os.fspath(path)))
    if key in _PO_LANG_MEMO:
        return _PO_LANG_MEMO[key]
    lang = ""
    m = None
    for seg in re.split(r"[\\/]", path or ""):
        m = _LOCALE_SEG_RE.fullmatch(seg or "")
        if m:
            lang = seg.lower()
            break
    if not lang:
        try:
            head = open(path, encoding="utf-8", errors="replace").read(4096)
            m = re.search(r'^"Language:\s*([A-Za-z]{2}_[A-Z]{2})"', head, re.M) or \
                re.search(r"Language:\s*([A-Za-z]{2}_[A-Z]{2})", head)
            if m:
                lang = m.group(1).lower()
        except Exception:
            lang = ""
    _PO_LANG_MEMO[key] = lang
    return lang


def _po_pairs(path):
    """[(en, ru)] пар из файла .po (только с непустым RU), мемоизировано."""
    key = os.path.normcase(os.path.abspath(os.fspath(path)))
    if key in _PO_PAIRS_MEMO:
        return _PO_PAIRS_MEMO[key]
    try:
        pairs = list(textutil.parse_po_file(path))
    except Exception:
        pairs = []
    _PO_PAIRS_MEMO[key] = pairs
    return pairs


def _po_indexes(roots):
    """{norm(msgid): ru} по .po целевого языка (config "target_lang")."""
    files = []
    for root in roots:
        if not root or not os.path.isdir(root):
            continue
        for dp, dn, fn in os.walk(root):
            for f in fn:
                p = os.path.join(dp, f)
                if not f.lower().endswith(".po"):
                    continue
                if po_file_lang(p) != TARGET_LANG:
                    continue  # не целевой язык — не берём вообще
                files.append(p)
    files.sort(key=lambda p: p.lower())
    idx = {}
    for p in files:
        for en, ru in _po_pairs(p):
            if not en or not ru:
                continue
            e = _po_norm(en)
            if e and e not in idx:
                idx[e] = ru
    return idx


def _po_index_for_mod(mod_path):
    """RU-индекс для .mod: свой locale/ (Workshop-мод) + locale игры (fallback)."""
    key = os.path.normcase(os.path.abspath(os.fspath(mod_path)))
    if key in _POIDX_MEMO:
        return _POIDX_MEMO[key]
    ws = os.path.normcase(os.path.abspath(WORKSHOP))
    game_roots = [os.path.join(GAME, "locale"),
                  os.path.join(GAME, "RE_Kenshi", "locale"),
                  os.path.join(GAME, "mods")]
    d = os.path.dirname(mod_path)
    if key.startswith(ws + os.sep):
        roots = [d] + game_roots
    else:
        roots = game_roots + [d]
    idx = _po_indexes(roots)
    _POIDX_MEMO[key] = idx
    return idx


def po_rows(hits, needle, cap=200):
    """Слой 5 (.po): чистые пары EN->RU, где needle в msgid или msgstr."""
    nd = _po_norm(needle)
    files, seen_f = [], set()
    for h in hits:
        p = h.get("path")
        if not p:
            continue
        q = os.path.normcase(p)
        if q not in seen_f:
            seen_f.add(q)
            files.append(p)
    # Для слоя 5 хотим видеть ВСЕ строки (с RU и без) — используем
    # textutil.parse_po_file_all. Только ЦЕЛЕВОЙ язык (config "target_lang").
    rows, seen = [], set()
    for p in files:
        if po_file_lang(p) != TARGET_LANG:
            continue
        name = _mod_name_for_path(p)
        try:
            pairs = list(textutil.parse_po_file_all(p))
        except Exception:
            continue
        for en, ru in pairs:
            if not en or not nd:
                continue
            if nd not in _po_norm(en) and nd not in _po_norm(ru):
                continue
            key = (en, ru, name)
            if key in seen:
                continue
            seen.add(key)
            rows.append((en, ru, "", name))
            if len(rows) >= cap:
                return rows
    rows.sort(key=lambda t: _cwidth(t[0]))
    return rows


def _one_line(s, width=160):
    """Схлопнуть переносы в одну строку, при необходимости урезать."""
    s = re.sub(r"[\r\n\t ]+", " ", (s or "")).strip()
    if len(s) > width:
        s = s[: width - 1] + "…"
    return s


# ============================== ТАБЛИЦА (tabulate) ===========================
def _cwidth(s):
    """Display-width: ASCII/кириллица = 1, CJK = 2 (для сортировки)."""
    s = s or ""
    w = 0
    for ch in s:
        o = ord(ch)
        if (
            0x1100 <= o <= 0x115F or 0x2E80 <= o <= 0xA4CF
            or 0xAC00 <= o <= 0xD7A3 or 0xF900 <= o <= 0xFAFF
            or 0xFE30 <= o <= 0xFE4F or 0xFF00 <= o <= 0xFF60
            or 0xFFE0 <= o <= 0xFFE6 or 0x20000 <= o <= 0x2FFFF
        ):
            w += 2
        else:
            w += 1
    return w


def _clip(s, width):
    s = _one_line(s)
    return s if _cwidth(s) <= width else s[: width - 1] + "…"


def render_table(rows, headers=("EN", "RU", "Поле", "Мод"), cap=20, cell_width=60):
    """Таблица (EN | RU | Поле | Мод) через `tabulate`.
    rows: [(en, ru, поле, имя), ...]; >cap — первые cap + '(+N ещё)'."""
    if not rows:
        return "  (ничего не найдено)"
    from tabulate import tabulate  # лёгкий, уже в requirements.txt
    shown = rows[:cap]
    data = [[_clip(e or "", cell_width), _clip(ru or "", cell_width),
             _clip(f or "", 24), _clip(m or "(кэш)", cell_width)]
            for (e, ru, f, m) in shown]
    txt = tabulate(data, headers=list(headers), tablefmt="fancy_grid",
                   colalign=("left", "left", "left", "left"))
    if len(rows) > cap:
        txt += f"\n  (+{len(rows) - cap} ещё — показаны первые {cap})"
    return txt


def _mod_name_for_path(path):
    """Идентификатор в колонке 'Мод'.
    .mod → имя файла без расширения.
    .po/.txt/.dll → локали (xx_YY) из пути, если есть, иначе имя файла.
    Чтобы в .po-слое не сливались все языки в одно 'main'.
    """
    base = os.path.basename(path or "")
    name = os.path.splitext(base)[0] or base
    ext = os.path.splitext(base)[1].lower()
    if ext in (".po", ".txt", ".dll"):
        for seg in re.split(r"[\\/]", path or ""):
            if re.fullmatch(r"[A-Za-z]{2}_[A-Z]{2}", seg or ""):
                return f"{seg}/{name}"
    return name


def layer_rows(hits, needle, cap=25):
    """(EN, RU, ПОЛЕ, Мод) из .mod-hits.
    Поле: из кеша (ru_rows, точный key), а для .mod без кеша — из C#-парсера
    (kenshi-modtranslate extract: exact match → короткая строка с needle).
    Для .po/.desc/.dll Поле = '' (там нет .mod-полей)."""
    seen = {}
    for h in hits:
        p = h.get("path")
        if not p:
            continue
        name = _mod_name_for_path(p)
        rows_of_hit = h.get("ru_rows")
        if rows_of_hit:
            for en, ru, fld in rows_of_hit:
                seen.setdefault((en, ru, fld, name), name)
        else:
            sn = (h.get("snippet") or "")
            if os.path.splitext(p)[1].lower() == ".mod":
                fld = _field_for_hit(p, needle)
            else:
                fld = ""
            seen.setdefault((sn, "", fld, name), name)
    rows = list(seen.keys())
    rows.sort(key=lambda t: (_cwidth(t[0]), _cwidth(t[1]), _cwidth(t[2])))
    return rows


# ---------------------------------------------------------------- search --

def search_all(needle, want_en, want_ru, include_files, include_dll):
    hits = {"cache": [], "workshop": [], "game_data": [], "game_mods": [],
            "po": [], "desc": [], "dll": []}
    if not os.path.isdir(ST):
        pass
    else:
        for h in iter_state_hits(needle, want_en, want_ru):
            hits["cache"].append(h)
    if include_files:
        ws_mods = find_mod_files_under(WORKSHOP)
        for h in _iter_hits_in_all_files(ws_mods, needle, "workshop"):
            hits["workshop"].append(h)
        _attach_ru(hits["workshop"], needle)
        gd = [os.path.join(GAME, "data", f)
              for f in (os.listdir(os.path.join(GAME, "data")) if os.path.isdir(os.path.join(GAME, "data")) else [])
              if f.lower().endswith(".mod")]
        for h in _iter_hits_in_all_files(gd, needle, "game_data"):
            hits["game_data"].append(h)
        _attach_ru(hits["game_data"], needle)
        gm = find_mod_files_under(os.path.join(GAME, "mods"))
        for h in _iter_hits_in_all_files(gm, needle, "game_mods"):
            hits["game_mods"].append(h)
        _attach_ru(hits["game_mods"], needle)
        for h in _iter_hits_in_all_files(find_po_files(), needle, "po", is_po=True):
            hits["po"].append(h)
        for h in _iter_hits_in_all_files(find_desc_files_under(WORKSHOP), needle, "desc"):
            hits["desc"].append(h)
    if include_dll:
        for h in _iter_hits_in_all_files(find_dll_files_under(WORKSHOP), needle, "dll", is_dll=True):
            hits["dll"].append(h)
    return hits


def _iter_hits_in_all_files(files, needle, kind, is_po=False, is_dll=False):
    for f in files:
        yield from _iter_hits_in(f, needle, kind, is_po=is_po, is_dll=is_dll)


# ---------------------------------------------------------------- main --

def norm_ignoring_ws(s):
    return norm(s)


def cache_rows(hits):
    """(EN, RU, Поле, Мод) из кэш-слоя, дедуп + сортировка."""
    out, seen = [], set()
    for h in hits:
        mod = h.get("mod") or "(кэш)"
        if isinstance(mod, tuple):
            mod = mod[0] if mod else "(кэш)"
        en = (h.get("en") or "").strip()
        ru = (h.get("ru") or "").strip()
        fld = (h.get("field") or "").strip()
        key = (en, ru, fld, mod)
        if key in seen:
            continue
        seen.add(key)
        out.append((en, ru, fld, mod))
    out.sort(key=lambda t: (_cwidth(t[0]), _cwidth(t[1]), _cwidth(t[2])))
    return out


def snippet_rows(hits):
    """(EN=фрагмент, RU='', Мод) для вспомогательных слоёв (.po/.desc/.dll)."""
    out, seen = [], set()
    for h in hits:
        sn = (h.get("snippet") or "").strip()
        if not sn:
            continue
        name = _mod_name_for_path(h.get("path") or "")
        key = (sn, "", "", name)
        if key in seen:
            continue
        seen.add(key)
        out.append(key)
    out.sort(key=lambda t: (_cwidth(t[0]), _cwidth(t[1]), _cwidth(t[2])))
    return out


def _print_layer(title, n_hits, rows, show_all=False, cap=20):
    """Една печать для слоя: таблица EN|RU|Мод.
    show_all=False (дефолт) — скрывает строки с непустым RU (уже переведено)
    + пометка '(скрыто N — --all, чтобы показать)'.
    show_all=True — все строки."""
    if not rows:
        print(f"\n-- {title} — {n_hits} совпадений --")
        if n_hits:
            print("  (все совпадения уже переведены — --all, чтобы показать)")
        else:
            print("  (ничего не найдено)")
        return
    if show_all:
        shown, n_hidden = rows, 0
    else:
        # По умолчанию: скрываем УЖЕ переведённые + игнорируемые
        # (·ИГРА — игра отрисует сама по OBJECT-ID; ·ОПИС — описание мода).
        # --all — все строки.
        _hidden = 0
        _shown = []
        for r in rows:
            fld = r[2] if len(r) > 2 else ""
            if (r[1] and str(r[1]).strip()):
                _hidden += 1
                continue
            if "ИГРА" in str(fld) or "ОПИС" in str(fld):
                _hidden += 1
                continue
            _shown.append(r)
        shown = _shown
        n_hidden = _hidden
    print(f"\n-- {title} — {n_hits} совпадений --")
    if not shown:
        print(f"  (все {n_hidden} совпадений уже переведены — --all, чтобы показать)")
    else:
        print(render_table(shown, cap=cap))
        if n_hidden:
            print(f"  (скрыто {n_hidden} уже перевед. строк — --all, чтобы показать)")


def main():
    ap = argparse.ArgumentParser(description="Поиск фразы по модам Kenshi и по встроенным файлам игры.")
    ap.add_argument("phrase", help="Фраза (подстрока, регистронезависимая, пробелы нормализуются)")
    ap.add_argument("--en", action="store_true", default=None, help="искать только EN (в кеше)")
    ap.add_argument("--ru", action="store_true", default=None, help="искать только RU (в кеше)")
    ap.add_argument("--state-only", action="store_true", help="только кеш (без файлов)")
    ap.add_argument("--dll", action="store_true", help="искать и в .dll (медленно)")
    ap.add_argument("--no-translate", action="store_true", help="не предлагать запустить перевод")
    ap.add_argument("--yes", action="store_true", help="авто-'все' (запустить перевод без ввода)")
    ap.add_argument("--force", action="store_true", help="пере-перевести всё заново (передаётся через --force)")
    ap.add_argument("--all", action="store_true", help="показывать ВСЕ совпадения, включая уже переведённые (по умолчанию они скрыты)")
    ap.add_argument("--cap", type=int, default=20, help="сколько строк печатать в таблице (default: 20)")
    args = ap.parse_args()
    needle = args.phrase
    cap = max(1, args.cap)

    want_en = True if args.en else (False if args.ru else True)
    want_ru = True if args.ru else (False if args.en else True)
    if not (want_en or want_ru):
        want_en = want_ru = False

    print(f"=== Поиск: {needle!r} ===")
    print(f"workshop = {WORKSHOP}")
    print(f"game     = {GAME}")

    hits = search_all(
        needle=needle,
        want_en=want_en, want_ru=want_ru,
        include_files=not args.state_only,
        include_dll=args.dll,
    )

    # --- слой 1: кеш (state/) ---
    # Там лежат ТОЛЬКО переведённые строки (mapping = переведённые, непереведённые
    # туда не попадают). В режиме «искать непереведённое» (по умолчанию) слой
    # бесполезен, поэтому СКРЫТ целиком — виден только с --all.
    if hits["cache"] and not args.all:
        print(f"\n-- слой 1: кеш (state/) — {len(hits['cache'])} совпадений — скрыт по умолчанию --")
        print("  (там только уже переведённые строки — --all, чтобы показать)")
    else:
        _print_layer("слой 1: кеш (state/)", len(hits["cache"]),
                     cache_rows(hits["cache"]), show_all=True, cap=cap)

    # --- слои 2-4: .mod (Workshop / data / mods) ---
    for key, label in (("workshop", "слой 2: .mod в Workshop"),
                       ("game_data", "слой 3: .mod в игре (data/)"),
                       ("game_mods", "слой 4: .mod в игре (mods\\)")):
        _print_layer(label, len(hits[key]),
                     layer_rows(hits[key], needle),
                     show_all=args.all, cap=cap)

    # --- слои 5-6-7: вспомогательные (.po / .desc / .dll) — тоже таблицей ---
    _print_layer(f"слой 5: .po локализация ({TARGET_LANG})", len(hits["po"]),
                 po_rows(hits["po"], needle), show_all=args.all, cap=cap)
    _print_layer("слой 6: описания (.txt)", len(hits["desc"]),
                 snippet_rows(hits["desc"]), cap=cap)
    if args.dll:
        _print_layer("слой 7: .dll", len(hits["dll"]),
                     snippet_rows(hits["dll"]), cap=cap)

    # Build translatable list: deduplicate by path (normcase); only .mod files
    # По умолчанию включаем ТОЛЬКО файлы, где есть НЕРЕВЕДЁННЫЕ строки (RU пустая).
    # С --all — все файлы, как раньше.
    def _has_untranslated(hits_kind):
        """True, если в hits есть хотя бы одна РЕАЛЬНО непереведённая (своя) строка
        без RU. Строки, помеченные 'ИГРА' (игра отрисует сама) или 'ОПИС'
        (игнор описания мода), НЕ считаются непереведёнными — они
        игнорируются по OBJECT-ID / ignore_mod_description по умолчанию."""
        for h in hits_kind:
            rows = h.get("ru_rows") or []
            if rows:
                for row in rows:
                    # row = (en, ru, field); field может содержать пометку ·ИГРА / ·ОПИС
                    fld = row[2] if len(row) > 2 and row[2] else ""
                    if "ИГРА" in str(fld) or "ОПИС" in str(fld):
                        continue  # игнорируем (игра / описание мода)
                    if not (row[1] and str(row[1]).strip()):
                        return True
            elif h.get("snippet"):
                return True  # нет кэша — значит есть непереведённые
        return False

    seen = set()
    translatable = []
    excluded = []
    for kind in ("workshop", "game_data", "game_mods"):
        file_hit_groups = {}
        for h in hits[kind]:
            key = os.path.normcase(os.path.abspath(h["path"]))
            file_hit_groups.setdefault(key, []).append(h)
        for key, group in file_hit_groups.items():
            p = group[0]["path"]
            needs = _has_untranslated(group)
            if not args.all and not needs:
                excluded.append(p)
                continue
            if key in seen:
                continue
            seen.add(key)
            translatable.append({
                "kind": kind,
                "label": f"[{kind}] {p}",
                "path": p,
                "n_snippets": len(group),
                "untranslated": needs,
            })

    n_total_hits = (len(hits["cache"]) + sum(len(hits[k]) for k in
        ("workshop", "game_data", "game_mods", "po", "desc", "dll")))
    print(f"\n=== ИТОГО: {n_total_hits} совпадений, из них {len(translatable)} файлов можно перевести ===")

    if not args.all and excluded:
        print(f"(исключено {len(excluded)} файл(ов), где всё уже переведено — --all, чтобы включить)")

    if not translatable:
        if args.no_translate:
            print(f"\n(--no-translate: перевод не запускается)")
        else:
            print("\n(все найденные файлы уже переведены — нечего переводить; --all для показа всего)")
        return

    if args.no_translate:
        print(f"\n(--no-translate: перевод не запускается)")
        return

    # Show numbered list
    print("\nПереводимые файлы:")
    for i, t in enumerate(translatable, 1):
        print(f"   {i:>3}. [{t['kind']}]  {t['path']}")
        print(f"        ({t['n_snippets']} совпадений во файле)")

    # Parse user selection
    if args.yes:
        sel = list(range(1, len(translatable) + 1))
    else:
        try:
            raw = input("\nНомера (запятая/пробел), 'a' = все, 'q' = выход: ").strip()
        except EOFError:
            print("\n(EOF — ввод недоступен)")
            return
        if not raw or raw.lower() in ("q", "quit", "x", "exit", "выход"):
            print("отменено")
            return
        if raw.lower() == "a":
            sel = list(range(1, len(translatable) + 1))
        else:
            sel = []
            for tok in re.split(r"[,\s]+", raw):
                if not tok:
                    continue
                if not tok.isdigit():
                    print(f"  [!] '{tok}' — пропущено (нужно число)")
                    continue
                n = int(tok)
                if 1 <= n <= len(translatable):
                    sel.append(n)
                else:
                    print(f"  [!] {n} — вне диапазона 1..{len(translatable)}")
            sel = sorted(set(sel))
            if not sel:
                print("  ничего не выбрано")
                return

    # Launch translation for each selected file
    py_exec = sys.executable
    cmd_base = [py_exec, os.path.join(BASE, "translate_mods.py")]
    if args.force:
        cmd_base.append("--force")

    n_ok = 0
    n_fail = 0
    for n in sel:
        t = translatable[n - 1]
        print(f"\n=== Перевод #{n}: {t['label']} ===")
        cmd = cmd_base + ["--file", t["path"]]
        r = subprocess.run(cmd, cwd=BASE)
        if r.returncode == 0:
            n_ok += 1
        else:
            n_fail += 1
            print(f"  [!] код выхода {r.returncode}")

    print(f"\n=== Готово: переведено {n_ok} файл(ов), ошибок {n_fail} ===")


if __name__ == "__main__":
    main()
