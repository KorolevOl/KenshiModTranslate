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
        for m in mapping:
            i = str(m.get("i"))
            en = emap.get(i, "")
            ru = (m.get("r") or m.get("ru") or "")
            en_hit = want_en and nd in norm(en)
            ru_hit = want_ru and nd in norm(ru)
            if en_hit or ru_hit:
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
                    out.append((en, ru))
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


def _one_line(s, width=160):
    """Схлопнуть переносы в одну строку, при необходимости урезать."""
    s = re.sub(r"[\r\n\t ]+", " ", (s or "")).strip()
    if len(s) > width:
        s = s[: width - 1] + "…"
    return s


# ============================== TABLITSA (tabulate) ===========================
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


def render_table(rows, headers=("EN", "RU", "Мод"), cap=20, cell_width=60):
    """Таблица (EN | RU | Мод) через `tabulate`. rows: [(en, ru, name), ...].
    Возвращает текст таблицы; >cap — первые cap + пометка '(+N ещё)'.
    """
    if not rows:
        return "  (ничего не найдено)"
    from tabulate import tabulate  # лёгкий, уже в requirements.txt
    shown = rows[:cap]
    data = [[_clip(e or "", cell_width), _clip(ru or "", cell_width),
             _clip(m or "(кэш)", cell_width)] for (e, ru, m) in shown]
    txt = tabulate(data, headers=list(headers), tablefmt="fancy_grid")
    if len(rows) > cap:
        txt += f"\n  (+{len(rows) - cap} ещё — показаны первые {cap})"
    return txt


def _mod_name_for_path(path):
    """Имя мода из .mod-пути (basename без расширения)."""
    base = os.path.basename(path or "")
    return os.path.splitext(base)[0] or base


def layer_rows(hits, needle, cap=25):
    """Из .mod-hits собрать строки таблицы (EN, RU, Мод).
    Если у мода есть кэш — строки из кэша (EN/RU пары);
    иначе EN = фрагмент из файла, RU = ''. Dedupe по (EN, RU, mod)."""
    seen = {}
    for h in hits:
        p = h.get("path")
        if not p:
            continue
        name = _mod_name_for_path(p)
        for en, ru in (h.get("ru_rows") or [((h.get("snippet") or ""), "")]):
            key = (en, ru, name)
            seen.setdefault(key, name)
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


def _layer_table(hits, needle, cap=20):
    """Собирает (EN, RU, Мод) для .mod-слоя и превращает в таблицу."""
    # Кэш-столбец (если hit'ы уже с ru_rows) берём из него;
    # если кэша нет — EN=snippet, RU="".
    rows = layer_rows(hits, needle, cap=cap)
    return render_table(rows, headers=("EN", "RU", "Мод"), cap=cap)


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
    args = ap.parse_args()
    needle = args.phrase

    want_en = True if args.en else (False if args.ru else True)
    want_ru = True if args.ru else (False if args.en else True)
    if not (want_en or want_ru):
        want_en = want_ru = False

    print(f"=== Поиск: {needle!r} ===")
    print(f"workshop = {WORKSHOP}")
    print(f"game     = {GAME}")

    n_state_limit = 30  # cap on cache hits printed (state can have thousands)
    hits = search_all(
        needle=needle,
        want_en=want_en, want_ru=want_ru,
        include_files=not args.state_only,
        include_dll=args.dll,
    )

    rows_cache = []
    seen_c = set()
    for h in (hits["cache"] or []):
        mod = h.get("mod") or "(кэш)"
        if isinstance(mod, tuple):
            mod = mod[0] if mod else "(кэш)"
        en = (h.get("en") or "").strip()
        ru = (h.get("ru") or "").strip()
        key = (en, ru, mod)
        if key in seen_c:
            continue
        seen_c.add(key)
        rows_cache.append((en, ru, mod))
    if hits["cache"]:
        print(f"\n-- слой 1: кеш (state/) — {len(hits['cache'])} совпадений --")
        print(render_table(rows_cache, headers=("EN", "RU", "Мод"), cap=20))
    else:
        print(f"\n-- слой 1: кеш (state/) — 0 --")

    if hits["workshop"]:
        print(f"\n-- слой 2: .mod в Workshop — {len(hits['workshop'])} совпадений --")
        print(_layer_table(hits["workshop"], needle, cap=20))
    else:
        print(f"\n-- слой 2: .mod в Workshop — 0 --")

    if hits["game_data"]:
        print(f"\n-- слой 3: .mod в игре (data/) — {len(hits['game_data'])} совпадений --")
        print(_layer_table(hits["game_data"], needle, cap=20))
    else:
        print(f"\n-- слой 3: .mod в игре (data/) — 0 --")

    if hits["game_mods"]:
        print(f"\n-- слой 4: .mod в игре (mods\\) — {len(hits['game_mods'])} совпадений --")
        print(_layer_table(hits["game_mods"], needle, cap=20))
    else:
        print(f"\n-- слой 4: .mod в игре (mods\\) — 0 --")

    if hits["po"]:
        print(f"\n-- слой 5: .po RU-локализация — {len(hits['po'])} совпадений --")
        for h in hits["po"][:20]:
            rel = os.path.relpath(h["path"], GAME) if h["path"].startswith(GAME) else h["path"]
            print(f"  [PO] {rel}")
            print(f"       ...{h['snippet']}...")
        if len(hits["po"]) > 20:
            print(f"  ... (+{len(hits['po']) - 20} ещё)")
    else:
        print(f"\n-- слой 5: .po RU-локализация — 0 --")

    if hits["desc"]:
        print(f"\n-- слой 6: описания (.txt) — {len(hits['desc'])} совпадений --")
        for h in hits["desc"][:20]:
            wid = os.path.basename(os.path.dirname(h["path"]))
            print(f"  [DESC] {wid}/{os.path.basename(h['path'])}")
            print(f"       ...{h['snippet']}...")
        if len(hits["desc"]) > 20:
            print(f"  ... (+{len(hits['desc']) - 20} ещё)")
    else:
        print(f"\n-- слой 6: описания (.txt) — 0 --")

    if args.dll:
        if hits["dll"]:
            print(f"\n-- слой 7: .dll — {len(hits['dll'])} совпадений --")
            for h in hits["dll"][:20]:
                rel = os.path.relpath(h["path"], WORKSHOP)
                print(f"  [DLL/WS] {rel}")
                print(f"     ...{h['snippet']}...")
            if len(hits["dll"]) > 20:
                print(f"  ... (+{len(hits['dll']) - 20} ещё)")
        else:
            print(f"\n-- слой 7: .dll — 0 --")

    # Build translatable list: deduplicate by path (normcase); only .mod files
    seen = set()
    translatable = []
    for kind in ("workshop", "game_data", "game_mods"):
        for h in hits[kind]:
            p = h["path"]
            key = os.path.normcase(os.path.abspath(p))
            if key in seen:
                continue
            seen.add(key)
            translatable.append({
                "kind": kind,
                "label": f"[{kind}] {p}",
                "path": p,
                "n_snippets": sum(1 for x in hits[kind] if x["path"] == p),
            })

    n_total_hits = (len(hits["cache"]) + sum(len(hits[k]) for k in
        ("workshop", "game_data", "game_mods", "po", "desc", "dll")))
    print(f"\n=== ИТОГО: {n_total_hits} совпадений, из них {len(translatable)} файлов можно перевести ===")

    if not translatable or args.no_translate:
        if args.no_translate and translatable:
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
