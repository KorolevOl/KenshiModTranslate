#!/usr/bin/env python3
"""extract_game_names.py — из официального locale/ru_RU/gamedata.po (в папке игры)
выгружает НАЗВАНИЯ рас, фракций, банд/групп (EN-ключ → RU-значение) в JSON.

Критерий «название» (а не описание): комментарий блока ``#. Name: X`` совпадает с
``msgid`` — именно так движок помечает display-имя записи. Типы:
  RACE, RACE_GROUP — расы и группы рас;  FACTION — фракции/банды.
Остальные (описания, кампании) исключаются. Мусор-строки (-----edad) — тоже.
"""
import json
import os
import re
import sys

GAME = r"E:\steamlibrary\steamapps\common\kenshi"
PO = os.path.join(GAME, "locale", "ru_RU", "gamedata.po")
WANT_TYPES = ("FACTION", "RACE", "RACE_GROUP")


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


def main():
    if not os.path.isfile(PO):
        print("[!] нет", PO, file=sys.stderr)
        return 1
    rows = parse_po(PO)
    # названия: нужный тип + имя (name==msgid) + валидный EN + не-эхо + не-пусто
    ok_en = re.compile(r"^[A-Za-z0-9][A-Za-z0-9()\-'/ ]{1,80}$")
    result = {}
    counts = {t: 0 for t in WANT_TYPES}
    for r in rows:
        if r["type"] not in WANT_TYPES or not r["is_name"]:
            continue
        en, ru = r["en"], r["ru"]
        if not ru or not ok_en.match(en):
            continue
        if ru == en:  # эхо — не переведено, пропускаем
            continue
        if en not in result:
            result[en] = ru
            counts[r["type"]] += 1
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "game_names_ru.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, sort_keys=True)
    total = sum(counts.values())
    print(f"[ok] блоков в .po: {len(rows)}; названий: {total} {counts}")
    print(f"[ok] файл: {out_path}")
    for en, ru in list(result.items())[:10]:
        print(f"     {en!r} -> {ru!r}")
    if total == 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
