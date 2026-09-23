#!/usr/bin/env python3
"""
search_mods.py — поиск фразы по модам Kenshi и по встроенным файлам игры.

Слои (по порядку):
  1) state-кеш: EN-исходники + RU-переводы (state/*_entries.json, state/*_mapping.json)
  2) .mod в Workshop
  3) .mod в игре (kenshi/data/*.mod — базовая локализация: rebirth.mod, Dialogue.mod и др.)
  4) .mod в папке kenshi/mods/<mod>/ (ручные моды, не из Workshop)
  5) .po RU-локализация игры (kenshi/locale/*.po и kenshi/mods/<mod>/locale/*.po)
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

CFG = json.load(open(os.path.join(BASE, "config.json"), encoding="utf-8"))
P   = CFG["paths"]
ST        = kmt_paths.resolve(P["state"])
WORKSHOP  = kmt_paths.resolve(P["workshop"])
GAME      = kmt_paths.resolve(P["game"])

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
    out = []
    main = os.path.join(GAME, "locale")
    if os.path.isdir(main):
        for dirpath, dirnames, filenames in os.walk(main):
            for f in filenames:
                if f.lower().endswith(".po"):
                    out.append(os.path.join(dirpath, f))
    mods_root = os.path.join(GAME, "mods")
    if os.path.isdir(mods_root):
        for dirpath, dirnames, filenames in os.walk(mods_root):
            for f in filenames:
                if f.lower().endswith(".po"):
                    out.append(os.path.join(dirpath, f))
    return out


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
    """Якорь кеша мода: из соседнего .orig_<h>.backup, иначе md5(файла)."""
    key = os.path.normcase(os.path.abspath(path))
    if key in _HASH_MEMO:
        return _HASH_MEMO[key]
    import hashlib
    base = os.path.basename(path)
    h = None
    try:
        for f in os.listdir(os.path.dirname(path)):
            if f.startswith(base + ".orig_") and f.endswith(".backup"):
                h = f[len(base) + 6:-len(".backup")]
                break
    except Exception:
        pass
    if not h:
        try:
            h = hashlib.md5(open(path, "rb").read()).hexdigest()[:12]
        except Exception:
            h = None
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
                    out.append((en, ru, _short_key(e.get("key") or "")))
    out.sort(key=lambda t: len(t[0]))  # короткие (специфичные) строки выше
    _RUROWS_MEMO[key] = out
    return out


def _attach_ru(hits, needle):
    """Для hits в .mod-файлах приписать 'ru_rows' — перевод найденной строки из кеша."""
    by_path = {}
    for h in hits:
        p = h.get("path")
        if not p or os.path.splitext(p)[1].lower() != ".mod":
            continue
        if p not in by_path:
            chash = _hash_for_mod(p)
            by_path[p] = ru_rows_for_needle(chash, needle) if chash else []
        h["ru_rows"] = by_path[p]


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
        shown = [r for r in rows if not (r[1] and r[1].strip())]
        n_hidden = len(rows) - len(shown)
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
    _print_layer("слой 5: .po RU-локализация", len(hits["po"]),
                 snippet_rows(hits["po"]), cap=cap)
    _print_layer("слой 6: описания (.txt)", len(hits["desc"]),
                 snippet_rows(hits["desc"]), cap=cap)
    if args.dll:
        _print_layer("слой 7: .dll", len(hits["dll"]),
                     snippet_rows(hits["dll"]), cap=cap)

    # Build translatable list: deduplicate by path (normcase); only .mod files
    # По умолчанию включаем ТОЛЬКО файлы, где есть НЕРЕВЕДЁННЫЕ строки (RU пустая).
    # С --all — все файлы, как раньше.
    def _has_untranslated(hits_kind):
        """True, если в hits есть хотя бы одна строка без RU."""
        for h in hits_kind:
            rows = h.get("ru_rows") or []
            if rows:
                for row in rows:
                    if not (row[1] and row[1].strip()):
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
