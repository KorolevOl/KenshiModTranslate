"""prefilter.py — пред-LLM фильтр: не слать в LLM то, что можно не слать.

Два слоя (применяются до каждого батча, идущего в LLM):

  СЛОЙ 1 — «нечего переводить» (regex, как просил пользователь).
    Строка, из которой (ПОСЛЕ вычистки BBCode `[...]` и движковых слэш-тегов
    `/AAA/`) нельзя извлечь ХОТЯ БЫ ОДНУ латинскую букву, — это либо уже
    русский текст, либо чистые знаки/числа/CJK. В ней нечего «давать» LLM.
    Решение: passthrough (в .mod остаётся оригинал), строка НЕ входит в
    отправляемый в LLM батч. Ядро: re.search('[A-Za-z]', вычищенная строка).
    Важно: латынь ВНУТРИ тега/BBCode не считается контентом (`[h1]Привет[/h1]`
    — `h1` это тег, а `Привет` — уже русский, переводить нечего).

  СЛОЙ 2 — «уже переведено» (переиспользование готового RU, без LLM).
    Если EN-строка точно совпадает (без учёта регистра) с готовым RU из:
      (a) dict.json `exact`   — канон (build-меню, имён/фракций);
      (b) .po игры            — официальная RU-локализация кенши;
      (c) кеш ранее переведённых модов (state\\*_entries.json + _mapping.json);
    — подставляем тот RU и НЕ отправляем строку LLM (экономит токены/время и
    ДЕРЖИТ КОНСИСТЕНТНОЕ написание). Приоритет: dict.json > .по игры > моды.
    Эхо (RU==EN) и ГРЯЗНЫЙ RU (кириллица в `/.../`, BBCode-мусор) НЕ выдаём.

Почему безопасно: подставленный RU тот же, что бы дал LLM-перевод, и он всё
равно проходит apply/audit-pipeline. Строки, которые LLM «правомерно» не
переведёт (onomatopoeia/identifier), _needs_translation в translate_mods
отсекает раньше — сюда они не доходят.
"""
import os
import re
import json
import glob
from collections import Counter

_HERE = os.path.dirname(os.path.abspath(__file__))

# --- regex-инструменты ---------------------------------------------------
_HAS_LATIN  = re.compile(r"[A-Za-z]")
_PAIR_RE    = re.compile(r'msgid\s+"([^"\n]+)"\s*\nmsgstr\s+"([^"\n]+)"')
# BBCode/Kenshi теги [h1]...[/h1], [url=..], [b][/b] — латынь здесь = формат, не контент
_BBCODE     = re.compile(r"\[[^\[\]]*\]")
# движковой слэш-тег /AAA/ (латиница внутри) — подставляется движком, не контент
_SLASH_TAG  = re.compile(r"/[A-Za-z0-9_\-]{1,40}/")
# ГРЯЗЬ: кириллица ВНУТРИ слэш-тега «/кца1/» — артефакт, НЕ валидный RU/EN
_DIRTY_TAG  = re.compile(r"/[^/\s]*[\u0400-\u04FF\u0400-\u044F\u0410-\u042F][^/\s]*/")
_BBCODE_MU  = re.compile(r"\[[0-9]+\]")          # одиночные численные [1]-скобки (мусор)


def _clean(s):
    """Вычистить BBCode `[...]` и движковые слэш-теги `/AAA/` (конверсионные
    вставки, не переводимый контент) — перед проверкой «есть ли латынь»."""
    s = _BBCODE.sub(" ", s)
    s = _SLASH_TAG.sub(" ", s)
    return s


def nothing_to_translate(en):
    """СЛОЙ 1. True, если ПОСЛЕ чистки тегов в строке нет ни одной латинской
    буквы — т.е. это чистая кириллица (уже русское), знаки, числа, CJK, эмодзи.
    Такое не нужно LLM (passthrough). Пустая строка тоже True."""
    if not isinstance(en, str):
        return True
    if not en.strip():
        return True
    return not _HAS_LATIN.search(_clean(en))


def _ru_is_dirty(ru):
    """True, если RU-значение ЗАМЯЗАНО артефактами и его нельзя использовать:
    кириллица ВНУТРИ слэш-тега («Противни/кца1/ рабства» — 15 таких в .по игры),
    или одиночный численный BBCode «[1]» вне контекста. Чистый RU → False."""
    if not isinstance(ru, str) or not ru.strip():
        return True
    if _DIRTY_TAG.search(ru):
        return True
    # [1]-скобки, если рядом нет нормального BBCode (х1/url/b/i...) — мусор
    tags = _BBCODE.findall(ru)
    real_tag = [t for t in tags if re.search(r"[A-Za-z]", t)]
    if not real_tag:
        if _BBCODE_MU.search(ru):
            return True
    return False


def _po_paths():
    game = os.environ.get("KENSHI_GAME", r"E:\steamlibrary\steamapps\common\kenshi")
    d = os.path.join(game, "locale", "ru_RU")
    return [os.path.join(d, "gamedata.po"),
            os.path.join(d, "LC_MESSAGES", "main.po")]


def _load_po_pairs():
    out = []
    for p in _po_paths():
        if not os.path.isfile(p):
            continue
        try:
            txt = open(p, encoding="utf-8", errors="replace").read()
        except Exception:
            continue
        for m in _PAIR_RE.finditer(txt):
            en, ru = m.group(1).strip(), m.group(2).strip()
            if not en or en == ru:
                continue
            if _ru_is_dirty(ru):
                continue
            out.append((en, ru))
    return out


def _load_dict_exact():
    out = []
    for cand in (os.path.join(_HERE, "dict.json"), "dict.json"):
        if os.path.isfile(cand):
            try:
                d = json.load(open(cand, encoding="utf-8-sig"))
                for en, ru in (d.get("exact") or {}).items():
                    if en and ru and not _ru_is_dirty(ru):
                        out.append((en, ru))
                return out
            except Exception:
                pass
    return out


def _load_mod_pool(state_dir):
    """Кеш переведённых модев: en_lower -> Counter{ru: count}.
    Только чистые RU (не эхо, не грязные, в EN есть латынь — наш случай)."""
    pairs = {}
    if not state_dir or not os.path.isdir(state_dir):
        return pairs
    for f in glob.glob(os.path.join(state_dir, "*_entries.json")):
        base = f[: -len("_entries.json")]
        mf = base + "_mapping.json"
        if not os.path.exists(mf):
            continue
        try:
            entries = json.load(open(f, encoding="utf-8"))
            mapping = json.load(open(mf, encoding="utf-8"))
        except Exception:
            continue
        m = {str(x.get("i")): x.get("ru", "") for x in mapping}
        for e in entries:
            en = e.get("original") or ""
            ru = m.get(str(e.get("i")), "")
            if not en or not ru:
                continue
            if en.lower() == ru.lower():          # эхо
                continue
            if _ru_is_dirty(ru):                  # замутнённый RU
                continue
            if not _HAS_LATIN.search(_clean(en)):  # не наш (без латиницы)
                continue
            pairs.setdefault(en.lower(), Counter())[ru] += 1
    return pairs


_POOL_CACHE = None
_STATE_DIR = None

def set_state_dir(d):
    """Указать каталог state\\ (кеш модев) — вызывается из translate_mods.py."""
    global _STATE_DIR, _POOL_CACHE
    _STATE_DIR = d
    _POOL_CACHE = None


def _get_state_dir():
    return _STATE_DIR or os.path.join(_HERE, "state")


def build_pool():
    """Один раз: EN_lower -> (RU, source). Приоритет: dict.json > .по игры > моды."""
    out = {}
    for en, c in _load_mod_pool(_get_state_dir()).items():   # (c) моды
        if c:
            out.setdefault(en, (c.most_common(1)[0][0], "mods"))
    for en, ru in _load_po_pairs():                            # (b) .по
        out[en.lower()] = (ru, "game.po")
    for en, ru in _load_dict_exact():                          # (a) dict
        out[en.strip().lower()] = (ru, "dict.json")
    return out


def reuse_lookup(en):
    """СЛОЙ 2. Готовый (RU, source) для EN-строки или (None, None).
    Эхо (RU==EN, рег. не уч.) и грязный RU не выдаём."""
    global _POOL_CACHE
    if not isinstance(en, str) or not en.strip():
        return None, None
    key = en.strip().lower()
    if _POOL_CACHE is None:
        _POOL_CACHE = build_pool()
    hit = _POOL_CACHE.get(key)
    if not hit:
        return None, None
    ru, src = hit
    if not ru or ru.lower() == en.lower() or _ru_is_dirty(ru):
        return None, None
    return ru, src


def stats():
    global _POOL_CACHE
    if _POOL_CACHE is None:
        return {"pool_size": 0, "by_src": {}}
    by = Counter(src for _, src in _POOL_CACHE.values())
    return {"pool_size": len(_POOL_CACHE), "by_src": dict(by)}
