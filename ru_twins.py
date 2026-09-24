"""ru_twins.py — RU/RUS-близнец-моды (готовые переводы, поставленные пользователем из Workshop).

Ситуация: пользователь сам установил RU-перевод модa (обычно Workshop-мод с
суффиксом RU / RUS / Russian / Русский в имени, напр. "Animal Variations RUS").
Такой мод — копия оригинала, где тексты уже переведены на RU. Мы:
  1. НЕ переводим LLM-ом (строки готовы — берём из близнеца);
  2. показываем RU в поиске по фразе (search_mods), даже без нашего кэша.

Выравнивание: по КЛЮЧУ записи .mod (record<id>-<owner>_<поле> / description).
RU-близнец — копия того же .mod → совпадают ВСЕ ключи (114/118 в Animal
Variations: совпало всё, что переводимо).

API:
  ru_twins.is_ru_twin(name) -> bool
  ru_twins.base_name(name) -> str
  ru_twins.find_twin(target_modfile, all_mods) -> dict | None
      {name, modfile, id} RU-близнеца или None.
  ru_twins.twin_pairs(target_modfile, all_mods)
      -> list[(key, en_из_оригинала, ru_из_твина, имя_твина)]  (memoized)
  ru_twins.lookup_pair(target_modfile, entry_key, all_mods)
      -> (ru, en, twin_name) | None
"""
from __future__ import annotations
import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.dont_write_bytecode = True
import kmt_paths  # noqa: E402

# ---------------------------------------------------------------------------
# Распознавание RU/RUS-суффикса в имени мода
# ---------------------------------------------------------------------------

_RU_WORDS = r"(?:ru|rus|русский|рус)"
_RU_TWIN_RE = re.compile(
    # основной хвост: "X RUS", "X - RU", "X | RU", "X.RU", "X (RU)",
    #               "X RUSSIAN", "X RU patch", "X - RU (+)", "X [RU]"
    r"[\s\-\/\\.\|\[(:>]+\s*" + _RU_WORDS + r"(?:\s+patch)?\s*(?:\(\+\)?|\[[^\]]*\])?\s*[.\)\]:>]*\s*$"
    # RU в скобках/клямах в середине: "(RU)", "[RU]", "|RU|", ":RU"
    r"|" + r"[\s\-\/\\.\|\[(:]+\s*" + _RU_WORDS + r"\s*[\)\|\.:>]+"
    ,
    re.IGNORECASE,
)


def is_ru_twin(name: str) -> bool:
    """True, если имя содержит RU/RUS/Русский как маркер перевода."""
    if not name:
        return False
    n = name.strip()
    return bool(_RU_TWIN_RE.search(n))


def base_name(name: str) -> str:
    """Убирает RU-суффикс → базовое имя.
    "Animal Variations RUS"      → "Animal Variations"
    "The Wanderer of the Black Desert | RU" → "The Wanderer of the Black Desert"
    "Industrial Blade and Foreign Greatsword - RU (+)" → "Industrial Blade and Foreign Greatsword"
    """
    if not name:
        return ""
    n = name.strip()
    W = r"(?:ru|rus|русский|рус)"
    # 1) хвост: "X RUS" / "X - RU" / "X | RU" / "X.RU" / "X (RU)" / "X RU patch" / "X - RU (+)"
    n = re.sub(r"[\s\-_/\\.\|\[(:>]+\s*" + W + r"(?![a-zA-Zа-яё])"
               r"(?:\s+patch)?\s*(?:\(\+\)?|\[[^\]]*\])?\s*[.\)\]:>]*\s*$",
               "", n, flags=re.IGNORECASE)
    # 2) RU внутри скобок/клипов в середине: "(RU)", "[RU]", "|RU|"
    n = re.sub(r"[\s\-_/\\.\|\[(:]+\s*[(\[|.:" + r"]\s*" + W + r"(?![a-zA-Zа-яё])\s*[\)\]|\.:>]*",
               " ", n, flags=re.IGNORECASE)
    # 3) чистка
    n = re.sub(r"\s+", " ", n).strip()
    n = n.rstrip("-./ \t|:[](){}<>")
    n = re.sub(r"^\s*[-./|\[(:>]\s*", "", n).strip()
    return n


# ---------------------------------------------------------------------------
# Поиск RU-близнеца
# ---------------------------------------------------------------------------

def find_twin(target_modfile: str, all_mods: list[dict]) -> dict | None:
    """Находит RU-близнец для target_modfile (по имени).

    all_mods: list из cache.all_mods() (workshop+game).
    Возвращает {name, modfile, id} или None.
    """
    target_name = None
    for m in all_mods:
        if m.get("modfile") and m["modfile"].lower() == os.path.abspath(target_modfile).lower():
            target_name = (m.get("name") or "").strip()
            break
    if not target_name:
        return None
    tbase = base_name(target_name).lower()
    if not tbase:
        return None
    for m in all_mods:
        nm = (m.get("name") or "").strip()
        if not is_ru_twin(nm):
            continue
        if base_name(nm).lower() == tbase and m.get("modfile"):
            return {"name": nm, "modfile": m["modfile"], "id": m.get("id")}
    return None


# ---------------------------------------------------------------------------
# Extraction + memoize
# ---------------------------------------------------------------------------

_PAIRS_MEMO: dict[str, list] = {}
# key = normcase(target_modfile)


def _extract(modfile: str) -> list[dict]:
    """kenshi-modtranslate extract → list[{i,key,original}]. [] при ошибке."""
    try:
        import tempfile
        import cli  # local
        fd, tmp = tempfile.mkstemp(suffix=".json", prefix="_rtw_")
        os.close(fd)
        rc = 0
        try:
            rc, _ = cli.run(["extract", os.fspath(modfile), tmp], timeout=300)
        except Exception:
            rc = 1
        try:
            if rc != 0:
                return []
            with open(tmp, encoding="utf-8") as f:
                return json.load(f) or []
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass
    except Exception:
        return []


def _cyr(s: str) -> bool:
    return any("\u0400" <= c <= "\u04ff" for c in s)


def twin_pairs(target_modfile: str, all_mods: list[dict]) -> list[tuple[str, str, str, str]]:
    """Все пары EN->RU из RU-близнеца (по key). Memoized.

    Возврат: [(key_оригинала, en_из_оригинала, ru_из_твина, имя_твина), ...]
    Если близнец не найден или извлечение упало — [].
    """
    key = os.path.normcase(os.path.abspath(os.fspath(target_modfile)))
    if key in _PAIRS_MEMO:
        return _PAIRS_MEMO[key]

    twin = find_twin(target_modfile, all_mods)
    if not twin:
        _PAIRS_MEMO[key] = []
        return []

    te = _extract(twin["modfile"])        # entries RU-близнеца
    oe = _extract(target_modfile)         # entries оригинала
    if not te or not oe:
        _PAIRS_MEMO[key] = []
        return []

    om = {e["key"]: (e.get("original") or "") for e in oe}
    out: list[tuple[str, str, str, str]] = []
    for e in te:
        k = e.get("key") or ""
        ru = (e.get("original") or "").strip()
        en = om.get(k, "").strip()
        if not ru or not en:
            continue
        if not _cyr(ru):
            continue
        if ru.lower() == en.lower():
            continue
        out.append((k, en, ru, twin["name"]))

    _PAIRS_MEMO[key] = out
    return out


def lookup_pair(target_modfile: str, entry_key: str, all_mods: list[dict]) -> tuple[str, str, str] | None:
    """(ru, en, twin_name) для конкретного key записи оригинала, или None."""
    for k, en, ru, src in twin_pairs(target_modfile, all_mods):
        if k == entry_key:
            return ru, en, src
    return None


__all__ = ["is_ru_twin", "base_name", "find_twin", "twin_pairs", "lookup_pair"]
