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
# Одна регулярка на парсер, не два. Используется и prefilter (reuse pool),
# и po_hints (динамич. подсказки).
PO_PAIR_RE = re.compile(r'msgid\s+"([^"\n]+)"\s*\nmsgstr\s+"([^"\n]*)"')

def parse_po_file(path):
    """Read a .po file, yield (en, ru) pairs (first msgid/msgstr per entry)."""
    try:
        txt = open(path, encoding="utf-8", errors="replace").read()
    except Exception:
        return
    seen = set()
    for m in PO_PAIR_RE.finditer(txt):
        en, ru = m.group(1).strip(), m.group(2).strip()
        if not en or not ru:
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
