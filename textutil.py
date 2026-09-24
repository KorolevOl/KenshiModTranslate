"""textutil.py — общие текст-утилиты (shared constants + helpers).

Цель: единый источник правды для регулярных выражений, которые раньше были
дублированы в prefilter.py и validate_translation.py:
  * PLACEHOLDER_RE  — %(printf) и %-форматирование (одна копия, не две)
  * SLASH_TAG_RE    — строгий ASCII-тег движка Kenshi: /[A-Za-z0-9_-]+/
  * SLASH_TAG_LOOSE — любой /.../ (включая авторские кириллические)
  * PO_PAIR_RE      — msgid/msgstr-пара .po (общий парсер, не две копии)

Модуль НЕ имеет внешних зависимостей (только re) и НЕ импортирует
validate_translation / prefilter — безопасен для unit-тестов.
"""
import re

# ---------- ПЛЕЙСХОЛДЕРЫ (printf + format) ---------------------------------
# Совпадает 1-в-1 с прежним PLACEHOLDER_RE в validate_translation.py и
# _PH_RE в prefilter.py. ВАЖНО: НЕ считаем "90% chance" плейсхолдером
# (флаг [+-0#] БЕСПРОБЕЛЬНЫЙ, иначе ложный "потерян %s").
PLACEHOLDER_RE = re.compile(
    r"%\d+\$[+-0#]*\d*(?:\.\d+)?[diouxXeEfFgGcs]"   # positional: %1$s, %2$0.3f
    r"|%[+-0#]*\d*(?:\.\d+)?[diouxXeEfFgGcs%]"      # printf: %s, %d, %.2f
    r"|\{[0-9]+\}"                                    # format: {0} {1}
)

# Быстрая проверка «есть ли хотя бы один плейсхолдер в строке» (без аллоков):
def has_placeholder(s):
    """True если в s есть хотя бы один printf/format-плейсхолдер."""
    if not s:
        return False
    return bool(PLACEHOLDER_RE.search(s))

# ---------- ТЕГИ ДВИЖКА KENSHI: /TAG/ ---------------------------------------
# Строгий ASCII-тег движка: только латиница/цифры/__/ - внутри. Это ТОСамый
# токен, который подставляет движок (имя NPC, приветствие, профессия…).
# LLM переводил /TAG/ → /RU-ТЕКСТ/, и движок переставал распознавать.
SLASH_TAG_ASCII = re.compile(r"/[A-Za-z0-9_\-]+/")

# Любой слэш-тег (включая авторские кириллические: /а1/, /аяыей/).
SLASH_TAG_LOOSE = re.compile(r"/[^\s/]+/")

def ascii_slash_tags(s):
    """Множество строгих ASCII-тегов движка (нижний регистр)."""
    if not s:
        return frozenset()
    return frozenset(t.lower() for t in SLASH_TAG_ASCII.findall(s))

def cyrillic_slash_tags(s):
    """Список слэш-тегов, которые НЕ чистые ASCII (брак LLM-перевода)."""
    if not s:
        return []
    out = []
    for m in SLASH_TAG_LOOSE.finditer(s):
        t = m.group()
        if re.search(r"[\u0400-\u04FF\u3040-\u9FFF\uAC00-\uD7AF]", t):
            out.append(t)
    return out

# ---------- .PO (локализация): msgid/msgstr ---------------------------------
# Единый источник парсинга .po. Используется prefilter (reuse pool),
# po_hints (динамич. подсказки), search_mods (слой 5 + RU-фолбэк .mod-слоёв).
#
# PO_PAIR_RE — ЛЕГКАЯ регулярка только для ОДНОСТРОЧНЫХ пар (backward-compat);
# для полных пар (многолинейные msgid/msgstr) — parse_po_file.
PO_PAIR_RE = re.compile(r'msgid\s+"([^"\n]+)"\s*\nmsgstr\s+"([^"\n]*)"')

def _po_unquote(v):
    """Убирает внешние кавычки и разворачивает gettext-escape-ы в пробелы."""
    v = (v or "").strip()
    if len(v) >= 2 and v[0] == '"' and v[-1] == '"':
        v = v[1:-1]
    v = v.replace('\\n', ' ').replace('\\t', ' ').replace('\\"', '"')
    v = re.sub(r"\s+", " ", v).strip()
    return v


def _parse_po_lines(lines):
    """State-machine парсер .po: yield (msgid, msgstr) пар.
    Поддерживает: msgctxt, многолинейные "..."-продолжения msgid/мs str,
    msgstr[N] (берём [0]), комментарии # / #. / #: / #| игнорирует,
    пустой msgid ('' заголовок) пропускает.
    Возвращает только пары, у которых НЕ пустые msgid и msgstr.
    """
    out = []
    cur_id = None
    cur_str = None
    last_field = None  # 'id' | 'str' | None

    def flush():
        nonlocal cur_id, cur_str
        if cur_id is not None and cur_id.strip():
            out.append((cur_id.strip(), (cur_str or "").strip()))
        cur_id = None
        cur_str = None

    for raw in lines:
        ln = raw.strip()
        if not ln:
            continue
        if ln.startswith("#"):
            continue  # комментарии любого вида: #, #., #:, #|
        if ln.startswith('"'):
            if last_field == "id" and cur_id is not None:
                cur_id += " " + _po_unquote(ln)
            elif last_field == "str" and cur_str is not None:
                cur_str = ((cur_str or "") + " " + _po_unquote(ln)).strip()
            continue
        if ln.startswith("msgid"):
            flush()
            rest = ln[5:].strip()
            cur_id = _po_unquote(rest) if rest and rest != '""' else ""
            cur_str = None
            last_field = "id"
            continue
        if ln.startswith("msgstr"):
            if ln.startswith("msgstr["):
                if cur_str not in (None, ""):
                    continue  # есть msgstr[0], плюрал не трогаем
                rest = (ln.split("]", 1)[1] if "]" in ln else "").strip()
            else:
                rest = ln[6:].strip()
            cur_str = _po_unquote(rest) if rest and rest != '""' else ""
            last_field = "str"
            continue
    flush()
    return out


def parse_po_file(path):
    """Read a .po file, yield (en, ru) pairs. ПОЛНЫЙ парсер:
    - многострочные msgid/msgstr (продолжения через "..."-строки)
    - msgstr[N] (берём [0])
    - пропускает пустые msgid (заголовок) и msgid==msgstr (нет перевода)
    Возвращает только пары с непустым RU."""
    try:
        txt = open(path, encoding="utf-8", errors="replace").read()
    except Exception:
        return
    out = _parse_po_lines(txt.splitlines())
    seen = set()
    for en, ru in out:
        if not en or not ru:
            continue
        k = en.lower()
        if k in seen:
            continue
        seen.add(k)
        yield en, ru


def parse_po_refs(path):
    """Множество record-ссылок «id-module» из ``#:``-строк .po.

    Игра локализует объекты по OBJECT-ID (не по тексту!):
    ``#: 4029-gamedata.base`` значит «перевод этой msgid относится к записи
    4029 из gamedata.base» — и НЕ к записи 50606-BeakThingEggFoods.mod с
    таким же текстом. Строки вида ``#: 1234-mod.mod:0`` (пустые msgid /
    поля) нормализуем к ``1234-mod.mod``. Возвращает множество записей."""
    refs = set()
    try:
        fh = open(path, encoding="utf-8", errors="replace")
    except Exception:
        return refs
    with fh:
        for ln in fh:
            ln = ln.strip()
            if not ln.startswith("#:"):
                continue
            for tok in ln[2:].split():
                m = re.match(r"^(\d+)-([A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*)(?::\d+)?$", tok)
                if m:
                    refs.add("%s-%s" % (m.group(1), m.group(2)))
    return refs


def parse_po_file_all(path):
    """Как parse_po_file, но ВСЕ пары (включая msgid==msgstr) для ранжирования.
    Используйте, когда нужно видеть, что строка ВСТРЕЧАЕТСЯ в .po, даже
    если в .po нет русского перевода (важно для prefilter «уже в .po»)."""
    try:
        txt = open(path, encoding="utf-8", errors="replace").read()
    except Exception:
        return
    out = _parse_po_lines(txt.splitlines())
    seen = set()
    for en, ru in out:
        if not en:
            continue
        k = en.lower()
        if k in seen:
            continue
        seen.add(k)
        yield en, ru

# ---------- КИРИЛЛИЦА / ЛАТИНИЦА -------------------------------------------
CYRILLIC_CHAR_RE  = re.compile("[\u0400-\u04FF\u0410-\u042f\u0401\u0451\u04e0-\u04f5]")
CYRILLIC_WORD_RE  = re.compile("[\u0400-\u04FF\u0410-\u042f\u0401\u0451\u04e0-\u04f5]{2,}")
LATIN_WORD_RE     = re.compile("[A-Za-z]+")

def has_cyrillic(s):
    """True если s содержит хотя бы один кириллический символ."""
    return bool(s) and bool(CYRILLIC_CHAR_RE.search(s))

def cyrillic_word_count(s):
    """Число русских слов (>=2 кириллич. буквы подряд)."""
    if not s:
        return 0
    return len(CYRILLIC_WORD_RE.findall(s))
