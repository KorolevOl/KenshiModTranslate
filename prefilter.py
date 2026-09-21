"""prefilter.py — pre-LLM filter: don't ship to the LLM what we don't need to.

Applies to a chunk of entries BEFORE it goes to the LLM (both in the main
translation pass and in the fix/dopereiod pass of translate_mods.py):

  LAYER 1 — nothing_to_translate(en)
      The string has NOTHING to translate. A string "has translatable
      content" only if, after stripping its engine tags ([..] BBCode and
      /TAG/ slash-tags), it still contains at least one Latin letter (a real
      English word). Pure Cyrillic (already Russian), pure punctuation /
      symbols, pure numbers, or empty → nothing to translate → do NOT ask the
      LLM. Passthrough: the original stays as the "translation" (the auditors
      already accept such rows as ok / already_ru — they are genuinely not
      translatable).

  LAYER 2 — lookup(en)  (reuse an existing translation)
      Exact (case-insensitive) match of the EN string against:
        (a) dict.json `exact`          — canonical, highest priority;
        (b) the game's RU locale .po   — official EN->RU pairs;
        (c) already-translated mods    — state\\*_entries.json+_mapping.json
            (mode of the RU values when several translations exist).
      Returns (ru, source) or (None, None). Safety: rejects echoes (ru==en)
      and rejects a reuse that would drop a placeholder the EN had.

Why this is safe:
  - LAYER 1 passthrough sets ru = the original; classify_row accepts that
    (already_ru / ok) — no ABORT, and zero tokens wasted asking the LLM about
    a line that has no English to translate.
  - LAYER 2 reuse only fires on EXACT string identity, so it cannot attach a
    translation meant for a different line; placeholder containment is
    double-checked; the result still passes the usual apply_dict / audit.

Pure module: no translate_mods imports, so it is unit-testable on its own.
translate_mods builds the pool once per process (configure) and calls lookup().
"""
import os
import re
import json
import glob
from collections import Counter

# --- LAYER 1: is there anything to translate? -------------------------------
# Engine/BBCode tags may carry Latin that is NOT translatable content:
#   [h1]..[/h1], [b], [url=..], /OI/, /PROCESSORSOUND/, /HOLYGREET/ ...
_TAG_RE = re.compile(r"\[[^\[\]]*\]|/[A-Za-z0-9_\-\.\u0400-\u04FF]{1,48}/")

def nothing_to_translate(en):
    """True if the string has nothing to translate — no Latin word left after
    stripping engine tags. Covers: already-Russian text, pure punctuation /
    symbols, pure numbers, empty/whitespace. Such lines must not be sent to
    the LLM (passthrough: the original is kept as the 'translation')."""
    if not isinstance(en, str) or not en.strip():
        return True
    cleaned = _TAG_RE.sub(" ", en)
    return not re.search(r"[A-Za-z]", cleaned)

# --- placeholder containment (safety for reuse) -----------------------------
# 2026-09-21: PLACEHOLDER_RE теперь из textutil (единый источник).
from textutil import PLACEHOLDER_RE as _PH_RE, PO_PAIR_RE, parse_po_file

def _ph(s):
    return set(_PH_RE.findall(s or ""))

def _ru_is_dirty(ru):
    """True, если RU-значение ЗАМЯЗАНО артефактами и его нельзя использовать как
    готовый перевод: кириллица ВНУТРИ слэш-тега («Противни/кца1/ рабства» — 15
    таких пар в .po игры), одиночные численные BBCode-скобки вне контекста,
    пустое. Чистый RU → False."""
    if not isinstance(ru, str) or not ru.strip():
        return True
    # кириллица в /.../ — артефакт
    if re.search(r"/[^\s/]*[\u0400-\u04FF][^\s/]*/", ru):
        return True
    # одиночные численные [N]-скобки, если рядом нет нормального BBCode
    # 2026-09-21: исправлен баг `\[[0-9+]\]` → `\[0-9+\]` (прежний искал
    # буквально "0+" внутри скобок, а не число).
    tags = re.findall(r"\[[^\[\]]*\]", ru)
    real = [t for t in tags if re.search(r"[A-Za-z]", t)]
    if not real and re.search(r"\[0-9+\]", ru):
        return True
    return False

# --- .po pair parsing (объединён с po_hints через textutil) ----------------
def _pairs_from_po(paths):
    out, seen = [], set()
    for p in paths:
        for en, ru in parse_po_file(p):
            k = en.lower()
            if k in seen:
                continue
            seen.add(k)
            out.append((en, ru))
    return out


class ReusePool:
    """Exact EN->RU reuse pool: build once, query many.

    Priority (lowest first): mods < game .po < dict.json exact.
    """
    def __init__(self):
        self._map = {}   # en_lower -> (ru, source)

    @classmethod
    def build(cls, dict_path=None, po_paths=None, state_dir=None):
        pool = cls()
        # (a) mods: mode of the RU values across all translated mods
        if state_dir and os.path.isdir(state_dir):
            counts = {}
            for f in glob.glob(os.path.join(state_dir, "*_entries.json")):
                mf = f[: -len("_entries.json")] + "_mapping.json"
                if not os.path.isfile(mf):
                    continue
                try:
                    entries = json.load(open(f, encoding="utf-8"))
                    mapping = {str(x.get("i")): x.get("ru")
                               for x in json.load(open(mf, encoding="utf-8"))}
                except Exception:
                    continue
                for e in entries:
                    en = e.get("original") or ""
                    ru = mapping.get(str(e.get("i")))
                    if not en or not ru:
                        continue
                    k = en.lower()
                    if k == ru.lower():          # echo — not a real translation
                        continue
                    if _ru_is_dirty(ru):         # мусор (кирил. в /.../ и т.п.)
                        continue
                    counts.setdefault(k, Counter())[ru] += 1
            for k, c in counts.items():
                pool._map.setdefault(k, (c.most_common(1)[0][0], "mods"))
        # (b) game .po (overrides mods on conflict)
        for en, ru in _pairs_from_po(po_paths or []):
            k = en.lower()
            if k == ru.lower():
                continue
            if _ru_is_dirty(ru):
                continue
            pool._map[k] = (ru, "game.po")
        # (c) dict.json exact — canonical, overrides all
        if dict_path and os.path.isfile(dict_path):
            try:
                d = json.load(open(dict_path, encoding="utf-8-sig"))
                for en, ru in (d.get("exact") or {}).items():
                    k = (en or "").strip().lower()
                    if not k or not ru or k == ru.lower():
                        continue
                    pool._map[k] = (ru, "dict.json")
            except Exception:
                pass
        return pool

    def lookup(self, en):
        """(ru, source) for an exact (case-insens.) EN match, or (None, None).
        Refuses: no match, echo (ru==en), or a placeholder the EN had that the
        reused ru dropped."""
        if not isinstance(en, str) or not en.strip():
            return None, None
        hit = self._map.get(en.strip().lower())
        if not hit:
            return None, None
        ru, src = hit
        if not ru or ru.lower() == en.lower():
            return None, None
        if _ru_is_dirty(ru):
            return None, None
        if not (_ph(en) <= _ph(ru)):   # reuse must not drop a placeholder
            return None, None
        return ru, src

    def __len__(self):
        return len(self._map)


_default_pool = None
_POOL_CACHE_SUFFIX = "_reuse_pool_cache.json"


def _pool_fingerprint(state_dir, dict_path, po_paths):
    """Stable fingerprint of ALL pool inputs = max mtime across them.

    The pool is a pure function of (state files, dict.json, .po files). If the
    max mtime of those is unchanged since a cache was written, the cached pool
    is byte-for-byte still correct and we can skip re-reading 500+ JSON files.
    Returns a string, or None when there is no cacheable source at all.
    """
    ts = []
    if state_dir and os.path.isdir(state_dir):
        for f in (glob.glob(os.path.join(state_dir, "*_entries.json"))
                  + glob.glob(os.path.join(state_dir, "*_mapping.json"))):
            try:
                ts.append(os.path.getmtime(f))
            except OSError:
                pass
    if dict_path and os.path.isfile(dict_path):
        ts.append(os.path.getmtime(dict_path))
    for p in (po_paths or []):
        if p and os.path.isfile(p):
            ts.append(os.path.getmtime(p))
    return ("%.6f" % max(ts)) if ts else None


def _pool_cache_file(state_dir):
    return os.path.join(state_dir, _POOL_CACHE_SUFFIX) if state_dir else None


def configure(dict_path=None, po_paths=None, state_dir=None):
    """Build (or rebuild) the default reuse pool. Returns the pool.

    Memoized: the built pool is cached in <state_dir>/_reuse_pool_cache.json
    keyed by a fingerprint of every input. A later run with unchanged inputs
    loads the cache instead of re-reading the whole state/ tree (223+ mods).
    Cache is best-effort — any read/write failure falls through to a fresh build.
    """
    global _default_pool
    cache_file = _pool_cache_file(state_dir)
    fp = _pool_fingerprint(state_dir, dict_path, po_paths)
    if cache_file and fp and os.path.isfile(cache_file):
        try:
            c = json.load(open(cache_file, encoding="utf-8"))
            if c.get("fingerprint") == fp and isinstance(c.get("map"), dict):
                pool = ReusePool()
                pool._map = {k: (v[0], v[1]) for k, v in c["map"].items()}
                _default_pool = pool
                return pool
        except Exception:
            pass  # stale/corrupt cache -> rebuild below
    pool = ReusePool.build(dict_path, po_paths, state_dir)
    if cache_file and fp:
        try:
            os.makedirs(state_dir, exist_ok=True)
            tmp = cache_file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"fingerprint": fp, "map": pool._map}, f)
            os.replace(tmp, cache_file)
        except Exception:
            pass  # never fail the build over a cache write
    _default_pool = pool
    return pool

def lookup(en):
    """Reuse an existing translation if the EN string matches exactly, else
    (None, None). Builds an empty pool on first use if not yet configured."""
    global _default_pool
    if _default_pool is None:
        _default_pool = ReusePool()
    return _default_pool.lookup(en)

def pool_size():
    return 0 if _default_pool is None else len(_default_pool)
