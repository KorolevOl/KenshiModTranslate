"""prompt.py — LLM prompt-логика + dictionary (dict.json).

Вынесено из translate_mods.py (2026-09-24), чтобы:
  * чистую `apply_dict` можно было тестировать без тяжёлого графа translate_mods
    (который тянет prefilter, po_hints, progress, validate_translation);
  * единый DICT / SYS_PROMPT / USER_PROMPT_TMPL / DICT_PATH — один источник.

API:
  prompt.SYS_PROMPT          # str, без {{DICT}}
  prompt.USER_PROMPT_TMPL    # str, шаблон user (с плейсхолдеров)
  prompt.DICT                # {"exact": {en.lower(): ru}, "words": set(en.lower())}
  prompt.DICT_PATH           # abs path к dict.json
  prompt.apply_dict(en, ru)  # str — канон RU для en (exact), иначе word-boundary (words)
  prompt.dict_block_for_prompt()  # str — JSON-блок для {{DICT}}
  prompt.load_prompt()       # (system, user) — parse на лету

Зависимость: kmt_paths. Без prefilter / po_hints / progress.
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
_resolve = kmt_paths.resolve

_CFG = json.load(open(os.path.join(_HERE, "config.json"), encoding="utf-8"))
T = _CFG.get("translate", {})


# ----------------------------------------------------------------- prompt file

def load_prompt():
    """Парсит prompt.txt (2 секции [SYSTEM]/[USER]) → (system, user_template)."""
    prompt_file = T.get("prompt_file", "prompt.txt")
    if not os.path.isabs(prompt_file):
        prompt_file = os.path.join(_HERE, prompt_file)
    txt = open(prompt_file, encoding="utf-8").read()
    marker = "\n[USER]\n"
    idx = txt.find(marker)
    if idx < 0:
        raise RuntimeError(f"prompt file missing [USER] section: {prompt_file}")
    system = txt[:idx].replace("[SYSTEM]", "").strip()
    user = txt[idx + len(marker):].strip()

    def _strip_comments(s: str) -> str:
        out = []
        for line in s.splitlines():
            if line.lstrip().startswith("#"):
                continue
            out.append(line)
        return "\n".join(out)

    return _strip_comments(system), _strip_comments(user)


SYS_PROMPT, USER_PROMPT_TMPL = load_prompt()


# -------------------------------------------------------------------- dictionary

DICT_PATH = T.get("dict", "dict.json")
if not os.path.isabs(DICT_PATH):
    DICT_PATH = os.path.join(_HERE, DICT_PATH)

DICT = {"exact": {}, "words": set()}
if os.path.isfile(DICT_PATH):
    _d = json.load(open(DICT_PATH, encoding="utf-8-sig"))
    DICT["exact"] = {k.lower().strip(): v for k, v in (_d.get("exact") or {}).items()}
    raw_words = _d.get("words")
    if isinstance(raw_words, dict):
        DICT["words"] = {k.lower().strip() for k in raw_words}
    elif isinstance(raw_words, list):
        DICT["words"] = {w.lower().strip() for w in raw_words if isinstance(w, str)}


def apply_dict(en_original, ru_translated):
    """Post-fix: enforce dictionary so UI keys/categories stay consistent.
    (Код перенесён из translate_mods.py без изменений — 2026-09-24.)

    1) exact: цела EN-строка = ключу -> вернуть каноническое RU (guaranteed).
    2) words (безопасное подмножество): термин ВНУТРИ EN-строки -> если LLM
       оставила EN-literал в переводе, подставить канон из exact (safety-net).
    Короткие ambiguous-слова (food/power/human...) НЕ в words -> НЕ
    word-boundary, чтобы слепая замена «power» во фразе не искажала смысл.
    """
    low = en_original.strip().lower()
    if low in DICT["exact"]:
        return DICT["exact"][low]
    out = ru_translated
    # Детерминированный порядок: ДЛИННЕЕ фразы первыми (longest-match wins),
    # иначе 'skeleton' подставится раньше 'skeleton p4mkii' и оставит мусор.
    for en in sorted(DICT["words"], key=lambda k: (len(k), k), reverse=True):
        if not en:
            continue
        ru = DICT["exact"].get(en)
        if not ru:
            continue
        pat = re.compile(r"(?<![A-Za-z])" + re.escape(en) + r"(?![A-Za-z])", re.IGNORECASE)
        out = pat.sub(ru, out)
    return out


def dict_block_for_prompt():
    """Словарь в промпте: ОБЪЕДИНЕНИЕ exact ∪ words, каждый ключ — ОДИН раз.
    words ⊆ exact (whitelist имён), поэтому union == exact: N строк,
    без повторов. Значения — всегда из exact (единый источник).

    Формат: человекочитаемый список "en" => "ru" (НЕ JSON) — LLM читает
    его как документ, а не как структуру. (Дословно из translate_mods.py.)
    """
    merged = {}
    for en in DICT["words"]:
        if en in DICT["exact"]:
            merged[en] = DICT["exact"][en]
    for en, ru in (DICT.get("exact") or {}).items():
        merged[en.lower().strip()] = ru
    if not merged:
        return "(пусто)"
    lines = ["КАНОНИЧЕСКАЯ ЛОКАЛИЗАЦИЯ (EN => RU), каждое имя/раздел меню — РОВНО так, без учёта регистра EN. "
             "Если EN-строка входа равна ключу — русское значение должно быть ровно это значение (целиком). "
             "Если ключ — термин ВНУТРИ длинной фразы — используй в переводе именно это каноническое слово/фразу для этого термина (не придумывай синоним):"]
    for en in sorted(merged):
        lines.append(f'  "{en}" => "{merged[en]}"')
    return "\n".join(lines)
