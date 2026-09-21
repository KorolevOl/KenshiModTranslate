#!/usr/bin/env python3
"""extract_game_names.py — из официального locale/ru_RU игры Kenshi
(gamedata.po + LC_MESSAGES/main.po) извлекает канонические RU-названия
и СЛИВАЕТ ИХ в dict.json (источник для LLM + пост-фиксер):

  * exact: ВСЕ имена рас/фракций/групп + все разделы build-меню.
           Строка целиком = ключу (без учёта регистра EN) → канонический RU как есть.
           Важно: регистр RU-значения СООТВЕТСТВУЕТ меню (STORAGE→ХРАНЕНИЕ и т.д.),
           иначе игра создаст дубль-категорию.
  * words: только МНОГОСЛОВНЫЕ имена (>=2 слова, безопасные для подстановки).
           Одинословные (Bull, Spiders, …) НЕ льётся — слишком общие, спалливают.

Действующие точные-ключи dict.json, НЕ входящие в игровой набор, сохраняются.
Запуск:  python extract_game_names.py
"""
import json
import os
import re
import sys

GAME = r"E:\steamlibrary\steamapps\common\kenshi"
GAMEDATA_PO = os.path.join(GAME, "locale", "ru_RU", "gamedata.po")
MAIN_PO = os.path.join(GAME, "locale", "ru_RU", "LC_MESSAGES", "main.po")
WANT_TYPES = ("FACTION", "RACE", "RACE_GROUP")

# Канонические РАЗДЕЛЫ МЕНЮ ПОСТРОЙКИ (вкладки build-меню Kenshi).
# RU-значения ищем в .po: сначала в верхнем регистре (как в меню игры), потом mixed-case.
BUILD_MENU = [
    "Furniture", "Storage", "Weapons", "Defence", "Research", "Power",
    "Water", "Food", "Farming", "Mining", "Military", "Trade", "Training",
    "Walls", "Crafting", "Lighting", "Turrets", "Buildings", "Exterior",
    "Interior", "Camping",
]
# алиасы: категория → как она реально именуется в .po (капс-метка build-меню)
MENU_ALIASES = {"Lighting": "LIGHTS"}


def unesc(s):
    """Раскодить экранирование .po (\", \\, \\n, \\t) — без двойного перекодирования."""
    return (s.replace('\\"', '"').replace("\\n", "\n")
             .replace("\\t", "\t").replace("\\\\", "\\"))


def parse_po(path):
    txt = open(path, encoding="utf-8").read()
    blocks = re.split(r"\n(?=#\. Type:)", txt)
    out = []
    for b in blocks:
        m_type = re.search(r"#\. Type:\s*(\w+)", b)
        m_name = re.search(r"#\. Name:\s*(.+)", b)
        head = b.split("\nmsgstr")[0]
        m_id = re.search(r'msgid\s+"((?:[^"\\]|\\.)*)"\s*$', head, re.M)
        tail = b.split("\nmsgstr", 1)[1]
        m_str = re.search(r'"((?:[^"\\]|\\.)*)"', tail)
        if not (m_type and m_id and m_str):
            continue
        en = unesc(m_id.group(1)).strip()
        ru = unesc(m_str.group(1)).strip()
        comment_name = m_name.group(1).strip() if m_name else en
        out.append({"type": m_type.group(1), "name": comment_name,
                    "en": en, "ru": ru, "is_name": comment_name == en and bool(en)})
    return out


def flat_pairs(path):
    """Плоские (EN, RU) пары из .po: msgid → msgstr, без типа/имени."""
    txt = open(path, encoding="utf-8").read()
    res = {}
    for m in re.finditer(r'msgid\s+"([^"\n]+)"\s*\nmsgstr\s+"([^"\n]+)"', txt):
        en, ru = unesc(m.group(1)).strip(), unesc(m.group(2)).strip()
        if en and ru and en != ru:
            res.setdefault(en, ru)
    return res


def build_menu(pairs_gd, pairs_m):
    """RU-значения для категорий build-меню из .po.

    Приоритет на каждую категорию:
      1) caps-ключ в gamedata.po  (WALLS→СТЕНЫ, POWER→ЭЛЕКТРИЧЕСТВО …) —
         именно их игра рендерит в меню постройки;
      2) caps-ключ в main.po      (запасной GUI);
      3) mixed-case ключ в main/ gamedata (Furniture→Мебель, Weapons→Оружие …).
    Алиас: Lighting → LIGHTS (так называется секция света в .po).
    """
    def pick(keys):
        for en, ru in pairs_gd.items():
            if en in keys and en.isupper() and en.replace(" ", "").isalpha():
                return ru
        for en, ru in pairs_m.items():
            if en in keys and en.isupper() and en.replace(" ", "").isalpha():
                return ru
        for en, ru in {**pairs_m, **pairs_gd}.items():  # mixed: GUI важнее
            if en in keys:
                return ru
        return None

    d = {}
    for bm in BUILD_MENU:
        keys = {bm, bm.upper(), bm.lower()}
        if bm in MENU_ALIASES:
            keys |= {MENU_ALIASES[bm], MENU_ALIASES[bm].upper(), MENU_ALIASES[bm].lower()}
        ru = pick(keys)
        if ru:
            d[bm] = ru
    return d


def main():
    if not (os.path.isfile(GAMEDATA_PO) and os.path.isfile(MAIN_PO)):
        print("[!] нет .po в папке игры:", GAME, file=sys.stderr)
        return 1

    # 1) имена рас/фракций/групп
    rows = parse_po(GAMEDATA_PO)
    ok_en = re.compile(r"^[A-Za-z0-9][A-Za-z0-9()\-''/ ]{1,80}$")
    names, counts = {}, {t: 0 for t in WANT_TYPES}
    for r in rows:
        if r["type"] not in WANT_TYPES or not r["is_name"]:
            continue
        en, ru = r["en"], r["ru"]
        if not ru or not ok_en.match(en) or ru == en:
            continue
        if en not in names:
            names[en] = ru
            counts[r["type"]] += 1

    # 2) разделы меню постройки (канонический список BUILD_MENU, RU из .po)
    pairs_m = flat_pairs(MAIN_PO)
    pairs_gd = flat_pairs(GAMEDATA_PO)
    menu = build_menu(pairs_gd, pairs_m)

    # --- сливаем в dict.json ---
    dict_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dict.json")
    if os.path.isfile(dict_path):
        cur = json.load(open(dict_path, encoding="utf-8-sig"))
    else:
        cur = {"_comment": "", "exact": {}, "words": {}}

    exact = {k.lower().strip(): v for k, v in (cur.get("exact") or {}).items()}
    for k, v in {**names, **menu}.items():
        exact[k.lower().strip()] = v  # игровой набор перетирает (это и есть канон)

    words = {k.lower().strip(): v
             for k, v in names.items()
             if len(k.split()) >= 2 or (len(k.split()) == 1 and len(k) >= 8)}
    # ручные words (не из игрового набора) — сохраняем
    for k, v in (cur.get("words") or {}).items():
        words.setdefault(k.lower().strip(), v)

    cur["exact"] = exact
    cur["words"] = words
    with open(dict_path, "w", encoding="utf-8") as f:
        json.dump(cur, f, ensure_ascii=False, indent=2)

    print(f"[ok] блоков в .po: {len(rows)}")
    print(f"[ok] имена рас/фракций/групп: {sum(counts.values())} {counts}")
    print(f"[ok] разделы меню: {len(menu)}")
    print(f"[ok] dict.json: exact={len(exact)}, words={len(words)} -> {dict_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
