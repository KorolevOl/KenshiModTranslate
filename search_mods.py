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
        gd = [os.path.join(GAME, "data", f)
              for f in (os.listdir(os.path.join(GAME, "data")) if os.path.isdir(os.path.join(GAME, "data")) else [])
              if f.lower().endswith(".mod")]
        for h in _iter_hits_in_all_files(gd, needle, "game_data"):
            hits["game_data"].append(h)
        gm = find_mod_files_under(os.path.join(GAME, "mods"))
        for h in _iter_hits_in_all_files(gm, needle, "game_mods"):
            hits["game_mods"].append(h)
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

def print_hits(label, hits):
    for h in hits:
        if h.get("kind") == "cache":
            mark = "EN" if (h.get("en") and norm_ignoring_ws(h.get("en", ""))) else "RU"
            # mark by which one matched
            print(f"  [КЕШ] {h['mod']}  (row {h['row']} {mark})")
        else:
            path = h["path"]
            if os.path.normcase(os.path.abspath(path)).startswith(os.path.normcase(os.path.abspath(WORKSHOP)) + os.sep):
                rel = os.path.relpath(path, WORKSHOP)
            elif os.path.normcase(os.path.abspath(path)).startswith(os.path.normcase(os.path.abspath(GAME)) + os.sep):
                rel = os.path.relpath(path, GAME)
            else:
                rel = path
            print(f"  [{label}] {rel}")
        print(f"     ...{h['snippet']}...")


def norm_ignoring_ws(s):
    return norm(s)


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

    print(f"\n-- слой 1: кеш (state/) — {len(hits['cache'])} совпадений --")
    for h in hits["cache"][:n_state_limit]:
        mark = "EN+RU" if (h.get("en") and h.get("ru") and norm(needle) in norm(h["en"]) and norm(needle) in norm(h["ru"])) else (
            "EN" if (h.get("en") and norm(needle) in norm(h["en"])) else "RU")
        print(f"  [КЕШ] {h['mod']}  (row {h['row']} {mark})")
        print(f"       ...{h['snippet']}...")
    if len(hits["cache"]) > n_state_limit:
        print(f"  ... (+{len(hits['cache']) - n_state_limit} ещё, обрезано для вывода)")
    if not hits["cache"]:
        print("  (ничего не найдено)")

    if hits["workshop"]:
        print(f"\n-- слой 2: .mod в Workshop — {len(hits['workshop'])} совпадений --")
        print_hits("MOD/WS", hits["workshop"])
    else:
        print(f"\n-- слой 2: .mod в Workshop — 0 --")

    if hits["game_data"]:
        print(f"\n-- слой 3: .mod в игре (data/) — {len(hits['game_data'])} совпадений --")
        print_hits("GAME", hits["game_data"])
    else:
        print(f"\n-- слой 3: .mod в игре (data/) — 0 --")

    if hits["game_mods"]:
        print(f"\n-- слой 4: .mod в игре (mods\\) — {len(hits['game_mods'])} совпадений --")
        print_hits("GAME/MODS", hits["game_mods"])
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
            print_hits("DLL", hits["dll"])
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
