#!/usr/bin/env python3
"""
search_mods.py — поиск фразы по ВСЕМ переведённым модам Kenshi.

Ищет в 4 слоях:
  1) state-кеш: EN-исходники (*_entries.json) и RU-переводы (*_mapping.json)
  2) .mod-файлы в Workshop (UTF-8 / UTF-16)
  3) описания модов (desc.txt / *.txt в корневой папке мода / v17-метаданные)
  4) .dll (бинарный поиск)

Аргументы:
  search_mods.py <фраза> [--en] [--ru] [--mods-only] [--desc-only] [--dll]
  --en/--ru — ограничить слой кеша (по умолчанию оба)
  Примеры:
    python search_mods.py "little help"
    python search_mods.py "a little" --en
    python search_mods.py "помощь" --ru
  Фраза ищется как подстрока, регистронезависимо, с нормализацией пробелов.
"""
import os, sys, json, re, glob, argparse

BASE = os.path.dirname(os.path.abspath(__file__))
ST = os.path.join(BASE, "state")
ROOT = r"E:\steamlibrary\steamapps\workshop\content\233860"

def norm(s: str) -> str:
    s = re.sub(r"\[/?[^\]]*\]", " ", s)      # bbcode
    s = re.sub(r"\s+", " ", s)
    return s.lower()

def encodings_text(data: bytes):
    if data.startswith(b"\xff\xfe"):
        return data[2:].decode("utf-16-le", errors="replace")
    try:
        return data.decode("utf-8", errors="replace")
    except Exception:
        return None

def load_name_map():
    try:
        sys.path.insert(0, BASE)
        import verify_translations as VT
        return VT.build_name_map()
    except Exception as e:
        print(f"  (имена модов недоступны: {e})", file=sys.stderr)
        return {}

def show(snip, hit_start, phrase_len, label):
    s = max(0, hit_start - 40)
    e = min(len(snip), hit_start + phrase_len + 40)
    frag = snip[s:e].replace("\r\n", "\\n").replace("\r", "\\n")
    print(f"    {label}...{frag}...")

def search_state(needle, want_en, want_ru, names):
    nd = norm(needle)
    n_hits = 0
    mods_seen = {}
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
                n_hits += 1
                modname = names.get(h, h)
                mods_seen.setdefault(modname, 0)
                mods_seen[modname] += 1
                print(f"  [КЕШ] {modname}  (row {i})")
                if en_hit:
                    show(" ".join(en.split()), " ".join(en.split()).lower().find(nd), len(nd), "     EN")
                if ru_hit:
                    show(" ".join(ru.split()), " ".join(ru.split()).lower().find(nd), len(nd), "     RU")
    return n_hits, len(mods_seen)

def search_files(needle, layer, names=None):
    nd = norm(needle)
    n_hits = 0
    files = []
    if layer == "mod":
        files = glob.glob(f"{ROOT}\\**\\*.mod", recursive=True)
    elif layer == "desc":
        for d in glob.glob(f"{ROOT}\\*"):
            if not os.path.isdir(d):
                continue
            files += [os.path.join(d, f) for f in os.listdir(d)
                      if f.lower().endswith((".txt", ".desc")) and "changelog" not in f.lower()]
    elif layer == "dll":
        files = glob.glob(f"{ROOT}\\**\\*.dll", recursive=True)
    for f in files:
        try:
            data = open(f, "rb").read()
        except Exception:
            continue
        txt = encodings_text(data) if layer != "dll" else data.decode("latin-1", errors="ignore")
        if txt is None:
            continue
        ntxt = " ".join(txt.split())
        low = ntxt.lower()
        pos = low.find(nd)
        if pos < 0:
            continue
        n_hits += 1
        wid = os.path.basename(os.path.dirname(f))
        name = os.path.basename(f)
        print(f"  [{layer.upper()}] mod-id {wid}: {name}")
        s = max(0, pos - 40)
        e = min(len(ntxt), pos + len(nd) + 40)
        print(f"     ...{ntxt[s:e].replace(chr(10),' ')}...")
    return n_hits

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("phrase")
    ap.add_argument("--en", action="store_true", default=None, help="только EN-кеш")
    ap.add_argument("--ru", action="store_true", default=None, help="только RU-кеш")
    ap.add_argument("--state-only", action="store_true", help="только кеш (без файлов)")
    ap.add_argument("--dll", action="store_true", help="искать и в .dll (медленно)")
    args = ap.parse_args()
    needle = args.phrase
    want_en = True if args.en else (False if args.ru else True)
    want_ru = True if args.ru else (False if args.en else True)

    if not (want_en or want_ru):
        want_en = want_ru = False

    print(f"=== Поиск: {needle!r} ===")
    total = 0
    mods_count = 0
    if want_en or want_ru:
        names = load_name_map()
        print("\n-- слой 1: кеш переводов (state/) --")
        h, m = search_state(needle, want_en, want_ru, names)
        total += h
        mods_count = m
        if not h:
            print("  (ничего не найдено)")

    if not args.state_only:
        print("\n-- слой 2: .mod-файлы (Workshop) --")
        h2 = search_files(needle, "mod")
        total += h2
        if not h2:
            print("  (ничего не найдено)")
        print("\n-- слой 3: описания (.txt) --")
        h3 = search_files(needle, "desc")
        total += h3
        if not h3:
            print("  (ничего не найдено)")
        if args.dll:
            print("\n-- слой 4: .dll (бинарный) --")
            h4 = search_files(needle, "dll")
            total += h4

    print(f"\n=== ИТОГО: {total} совпадений "
          + (f"в {mods_count} модах (кеш)" if (want_en or want_ru) else "") + " ===")

if __name__ == "__main__":
    main()
