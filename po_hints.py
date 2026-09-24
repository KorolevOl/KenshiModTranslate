"""po_hints.py — динамические подсказки из официальной RU-локализации игры
под ТЕКУЩИЙ батч строк, уходящий в LLM.

Зачем отдельный слой (а не «всё в dict.json»):
  dict.json живёт в промпте ПОСТОЯННО (весь его объём). .po игры — тысячи пар.
  В dict занести всё = раздуть контекст каждого чанка. Тут же в промпт попадает
  ТОЛЬКО то, что пересекается с текущими строками батча — и только то, чего НЕТ
  в dict.json (уже в промпте — дублировать не нужно).

Источники (конфиг paths.game, locale/<target_lang>/, target_lang из config.json):
  gamedata.po            — названия объектов/рас/фракций/построек
  LC_MESSAGES/main.po    — UI, категории, диалоги

Ранжирование — по РЕДКОСТИ слова среди всех строк .po:
  чем РЕДЧЕ встречается слово в .po, тем более оно «именное/специфичное»
  (Gorillo, Fishman, Blackshifters = высоко; Water, Stone, Guard = низко).
  Плюс: точное совпадение полного msgid со строкой батча = максимум.
  Пара выдаётся, только если даёт хотя бы одно значимое (редкое) слово.
  Пары, уже в dict.json, не дублируются.
"""
import os
import re
from collections import Counter

# пара выдаётся подсказкой, только если в ней совпало хотя бы одно РЕДКОЕ слово
# (встречается во всех строках .po <= RARE_MAX раз). Частые (town/stone/guard/shek
# = 24/37/28/27) не дают вклада. 10 — померенный порог на реальном датасете .po (4302 пары).
RARE_MAX = 10

# 2026-09-21: .po pair parsing теперь из textutil (единый источник,
# было дублировано и в prefilter.py, и здесь по одному regex'у).
from textutil import PO_PAIR_RE, parse_po_file
_re_word = re.compile(r"[A-Za-z][A-Za-z'\-]*")
_re_strip = re.compile(r"[\-']")

# стоп-слова: служебные (не дают вклада в значимость)
_STOP = set((
    "the a an and or of to in for with from by at on is are was were be been being "
    "it its this that these those you your he she they his her their our we me my "
    "as not no yes but if then than so very just about over under out up down off "
    "into onto above below between through during before after each every some "
    "such only own same other another one two three new old good great big small "
    "long short high low can will would should could may might does did do have "
    "has had let lets get got make makes take takes need needs want wants see "
    "sees look looks here there where when how what who which why ill dont cant wont "
    "ll s t d m re ve n't".split()
))

_state = {"paths": None, "pairs": None, "freq": None}
_MIN_WORD = 4  # минимальная длина значимого слова (без стоп-слов)

# 2026-09-24: в официальном RU .po ~58 пар со сломаной печатью переводчика
# вида «Торгов/каец1/», «Башмачни/кца1/», «Мелк/аяий1/». Такие пары НЕ должны
# попадать в промпт (LLM подхватит мусор). Фильтруем только метки вида
# <кирилица/латиница>+<цифра> внутри «/…/» — обычные дроби (1/2, 2x3/4) не трогаем.
_BAD_MARK = re.compile(r"/[а-яёА-ЯЁa-zA-Z]+\d+")


def configure(paths):
    """Задать пути к .po (перезапустит парсинг при следующем обращении)."""
    _state["paths"] = tuple(paths)
    _state["pairs"] = None


def _norm(w):
    """lower + срез плюрального «es»/«s» (если остаток >=4) для сопоставления."""
    w = w.lower()
    for sfx in ("es", "s"):
        if w.endswith(sfx) and len(w) - len(sfx) >= 4:
            return w[:-len(sfx)]
    return w


def _sig_words(en, freq=None):
    """Набор значимых (нормализованных) слов строки; len >= MIN_WORD, без стоп-слов."""
    out = set()
    for w in _re_word.findall(en):
        core = _re_strip.sub("", w).lower()
        if len(core) >= _MIN_WORD and core not in _STOP:
            out.add(_norm(core))
    return out


def _load(paths):
    pairs = []
    seen = set()
    for p in paths:
        if not os.path.isfile(p):
            continue
        for en, ru in parse_po_file(p):
            if not en or not ru or en == ru or len(en) > 64:
                continue
            if _BAD_MARK.search(ru):
                continue  # сломанная печать переводчика в официальном .po
            k = en.lower()
            if k in seen:
                continue
            words = _sig_words(en)
            if words:
                seen.add(k)
                pairs.append((en, ru, words))

    # частота каждого значимого слова среди всех пар (= всех строк .po)
    freq = Counter()
    for _, _, words in pairs:
        freq.update(words)
    return pairs, freq


def _data():
    paths = _state["paths"]
    if not paths:
        return [], Counter()
    if _state["pairs"] is None or _state.get("_paths_used") != paths:
        pairs, freq = _load(paths)
        _state["pairs"], _state["freq"] = pairs, freq
        _state["_paths_used"] = paths
    return _state["pairs"], _state["freq"]


def hints_for(strings, dict_keys=None, max_hints=30):
    """Подобрать подсказки под батч.

    strings    — список EN-строк батча (что уходит в LLM)
    dict_keys  — EN-ключи dict.json (уже в промпте; дублируем не стоит)
    max_hints  — потолок строк подсказок
    Возвращает [(EN, RU), ...] по убыванию релевантности.

    Ключевое правило: пара считается релевантной, только если совпало
    хотя бы одно РЕДКОЕ слово (встречается во всех строках .po <= RARE_MAX
    раз). Частые слова (town/water/guard …) дают лишь маленький вклад.
    Это отсекает мусор вроде «Shek Warrior» под батч про «strongest warrior».
    """
    dict_keys = {k.lower() for k in (dict_keys or set())}
    pairs, freq = _data()
    if not pairs or not strings:
        return []

    # слова батча + частотные веса (редкие слова весомее)
    rows = set()
    batch_words = set()
    for s in strings:
        if not isinstance(s, str) or not s.strip():
            continue
        rows.add(s.lower())
        batch_words |= _sig_words(s)

    import math
    def weight(word):
        n = freq.get(word, 0)
        return 1.0 / math.log(2.0 + n)

    scored = []
    for en, ru, words in pairs:
        k = en.lower()
        if k in dict_keys:
            continue
        inter = words & batch_words
        if not inter:
            continue
        has_rare = any(freq.get(w, 0) <= RARE_MAX for w in inter)
        if not has_rare:
            continue  # только частые слова = шум
        score = sum(weight(w) for w in inter)
        if words <= batch_words:
            score += 3.0     # весь msgid есть в батче
        if k in rows:
            score += 100.0   # точное совпадение строки
        scored.append((score, en, ru))
    scored.sort(key=lambda x: (-x[0], x[1].lower()))

    out, seen = [], set()
    for score, en, ru in scored:
        key = en.lower()
        if key in seen or key in dict_keys:
            continue
        seen.add(key)
        out.append((en, ru))
        if len(out) >= max_hints:
            break
    return out


def hints_block(strings, dict_keys=None, max_hints=30):
    """Текст блока для вставки в system-промпт (пустая строка, если подсказок нет)."""
    hints = hints_for(strings, dict_keys=dict_keys, max_hints=max_hints)
    if not hints:
        return ""
    lines = [
        "ПОДСКАЗКИ ИЗ ОФИЦИАЛЬНОЙ РУСКОЙ ЛОКАЛИЗАЦИИ ИГРЫ — подобраны именно под "
        "этот набор строк (термин/название, встреченный в батче, и его официальный "
        "русский вариант). Если такой термин встречается в твоих строках — используй "
        "это написание (оно соответствует русскому изданию игры):"
    ]
    for en, ru in hints:
        lines.append(f'  "{en}" => "{ru}"')
    return "\n".join(lines)
