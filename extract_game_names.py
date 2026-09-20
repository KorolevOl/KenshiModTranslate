#!/usr/bin/env python3
"""extract_game_names.py — из официального locale/ru_RU игры Kenshi
(gamedata.po + LC_MESSAGES/main.po) выгружает EN-ключ → RU-значение:

  1) НАЗВАНИЯ рас, фракций, банд/групп — блок ``#. Name: X`` где X == msgid
     (тип RACE / RACE_GROUP / FACTION), из gamedata.po;
  2) РАЗДЕЛЫ МЕНЮ ПОСТРОЙКИ/UI — строки, полностью в ВЕРХНЕМ РЕГИСТРЕ
     (WALLS, STORAGE, POWER, FOOD, DEFENCE, FARMING, TRAINING, CRAFTING,
     LIGHTS, TECH, BUILDINGS …) — переводчики пишут их капсом, как в меню игры,
     поэтому это и есть канонические RU-заголовки разделов.

Итог: game_names_ru.json (ключ = английская строка, значение = русская).
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

    data = {**names, **menu}
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "game_names_ru.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)

    print(f"[ok] блоков в .po: {len(rows)}")
    print(f"[ok] имена рас/фракций/групп: {sum(counts.values())} {counts}")
    print(f"[ok] разделы меню: {len(menu)}")
    print(f"[ok] итого: {len(data)} пар -> {out_path}")
    sample = dict(list(names.items())[:4] + list(menu.items())[:6])
    for en, ru in sample.items():
        print(f"     {en!r} -> {ru!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
