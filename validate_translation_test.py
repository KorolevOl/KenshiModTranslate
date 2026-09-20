"""Юнит-тесты детерминированных проверок перевода (без LLM, без сети).

Запуск:  python validate_translation_test.py
"""
import validate_translation as v

CASES = [
    # (en, ru, expected_level)
    ("Smithing", "Кузнечное дело", "ok"),                                   # чистый перевод
    ("Crossbows: Tooth Pick", "Арбалеты: Зубочистка", "ok"),                # название предмета
    ("A cheap weapon %s", "Дешёвое оружие %s", "ok"),                        # плейсхолдер сохранён
    ("{0} hit for {1} dmg", "Попадание {0} урона {1}", "ok"),              # позиционные
    ("", "", "ok"),                                                       # обе пустые
    ("%s", "%s", "ok"),                                                     # только плейсхолдер, сохранён
    ("T34", "T34", "ok"),                                                  # one token containing digits: identifier, passthrough is the norm
    ("MkII", "MkII", "warn"),                                              # one-token passthrough (no digits) — остаётся warn (1 слово, легитимный код)
    ("wood_dex_dummy_pole", "wood_dex_dummy_pole", "ok"),                  # asset name, leave as is
    ("house03-base", "house03-base", "ok"),                                # asset name (with hyphen)
    ("Smithing", "", "error"),                                             # пустой перевод
    ("Smithing", "   ", "error"),                                          # только пробелы
    ("Smithing", "!!!", "error"),                                          # нет букв
    ("A cheap weapon %s", "Дешёвое оружие", "error"),                       # потерял %s
    ("%s", "", "error"),                                                   # потерял единственный плейсхолдер
    ("Spring Bat", "Spring Bat", "echo"),                                  # эхо (2 слова)
    ("Old World Blueprints", "Old World Blueprints", "echo"),              # полное эхо
    ("Some English Sentence", "Some Latin Text Here", "error"),            # нет кириллицы, не эхо (2026-09-19: latin>=2слова -> error, фиксер обязан браковать)
    ("Crossbows: Oldworld Bow MKII", "Арбалеты: Старосветский лук MkII", "ok"),  # частичное passthrough ОК
    # --- реальные ложные-эхо из production (log fix_translations 2026-09-18) ---
    ("@Shopping -fluff", "@Shopping -fluff", "ok"),               # AI-behavior flag, не переводится
    ("@Patrol -fluff", "@Patrol -fluff", "ok"),                   # AI-behavior flag
    ("MarketStall Grouped01_Mask", "MarketStall Grouped01_Mask", "ok"),        # имя меша
    ("MarketStall Grouped01A_Mask", "MarketStall Grouped01A_Mask", "ok"),      # имя меша
    # --- ложные-эхо второго класса (запуск More Bounties 2026-09-19) ---
    ("!!!", "!!!", "ok"),                                          # только знаки — нечего переводить
    ("...", "...", "ok"),                                          # только знаки
    ("B.T.P.", "B.T.P.", "ok"),                                    # аббревиатура — оставляем
    ("Wall Level 01_METAL-FENCE 01", "Wall Level 01_METAL-FENCE 01", "ok"),    # имя меша 6 слов
    ("Wall Level 01_METAL-FENCE 02", "Wall Level 01_METAL-FENCE 02", "ok"),    # имя меша 6 слов
    ("Простинкий мод на нижнее бельё.\r\n14 типов белья и с кучей расцветок.\r\n-----------------------------------------\r\nThis mod in Russian language\r\nA simple mod for underwear.",
     "Простинкий мод на нижнее бельё.\r\n14 типов белья и с кучей расцветок.\r\n-----------------------------------------\r\nThis mod in Russian language\r\nA simple mod for underwear.",
     "ok"),                                                        # двуязычное описание: RU уже есть
    # --- регрессия: НАСТОЯЩИЙ эхо всё ещё ловится ---
    ("Sell food at higher prices", "Sell food at higher prices", "echo"),     # обычная фраза
    ("Give that back!", "!!!", "error"),                                     # слова пропали
    # --- mixed: в русском переводе «ролeвают» латинские буквы/иероглифы ---
    ("Bandit group", "Бандитa рота", "error"),                               # латин. 'a' в русском слове (2026-09-19: mixed -> error, не warn; фиксер обязан браковать)
    ("Help the injured", "Пomощь рaненым", "error"),                         # опечатки-латиница в русском (mixed -> error)
    ("Attack at dawn", "Нaступaй на зaхaтe", "error"),                       # много латинских букв-вкраплений (mixed -> error)
    ("Ancient ruins", "Древние рyины китaйской кyльтyры", "error"),          # лат. вкрапления + кириллица (mixed -> error)
    ("Ancient ruins", "Китайскиe руины", "error"),                           # лат. 'e' в конце + 'Китайскиe' (mixed -> error)
    # --- контроль: чистые лат./RU без вкраплений НЕ 'mixed' ---
    ("Attack at dawn", "Атакуй при рассвете", "ok"),                         # чистый русский
    ("Ancient ruins", "Китайские руины", "ok"),                              # чистый русский (кириллица)
    # --- markup-ложные-«mixed»: тег [M]/[h1]/[b]/[url] приклеен к русскому слову = ОК ---
    # (реальные строки из HatedMekkr 'Маска ниндзя [M][Чёрная]' и Tents changelog;
    #  до 2026-09-19 детектор ругался 'mixed' на корректном переводе -> зря пере-перевод.)
    ("Black Ninja Mask", "Маска ниндзя [M][Чёрная]", "ok"),                  # [M][Чёрная] — НЕ опечатка
    ("About this mod", "ОБО ЭТОМ МОДИФИКЕ", "ok"),                           # текст без вкраплений
    ("Update header", "ОБНОВЛЕНИЕ 2 - 15 СЕНТЯБРЯ", "ok"),                  # дата/заголовок
    ("[h1]Title[/h1] body RU", "[h1]ОБО МОДИФИКЕ[/h1] тело", "ok"),         # BBCode-тег + русский
    ("See changelog", "См. [url=https://x.y/z]Примечания[/url]", "ok"),      # url + кириллица
    # --- СЛЭШ-ТЕГИ ДВИЖКА /TAG/ (2026-09-20): НИКОГДА не переводить, ни терять ---
    ("My /FAVORITE/ /PATRON/!", "Мой /FAVORITE/ /PATRON/!", "ok"),            # тег сохранён
    ("My /FAVORITE/ /PATRON/!", "Мой /ЛУБЯЩЕЕ/ /КЛИЕНТ/!", "error"),          # (а) кириллица внутри тега
    ("My /FAVORITE/ /PATRON/!", "Мой любимый клиент!", "error"),              # (б) тег из EN пропал
    ("/DISGUISEDNAME/, you're back!", "Наконец-то, ты вернулся!", "error"),  # тег вырезан
    ("/DISGUISEDNAME/, you're back!", "", "error"),                           # RU пустое, тег в EN
    # контроль: АВТОРСКИЕ скобки в готовом рус. тексте — НЕ движок, НЕ чинить
    ("Может быть, я не уверен/а1/...", "Может быть, я не уверен/а1/...", "ok"),  # /а1/ — не тег движка
    ("200 кат, уважаем/аяый/.", "200 кат, уважаем/аяый/.", "ok"),            # авторское склонение
    # --- онотопоэзия / «звуки»: LLM правду не переводит — НЕ 'empty', НЕ чинить ---
    ("SOOOO!", "", "ok"),                                                   # чистый звук
    ("why- WHY- wHY- wh- wh- WHYYyyyyYYYYY!!!??", "", "ok"),                # WHYYYY — звук
    ("ssss ssSStttOOOOOPPppppp...", "", "ok"),                              # звуковой стон
    ("Aaargh!", "Aaargh!", "ok"),                                            # короткое возду: ok=фиксер НЕ пере-переводит (onomatopoeia, ≤5 букв + растянутая буква). 2026-09-19: было warn, стало ok (метка точнее, поведение то же — не в BAD_FIX_LEVELS)
    # контроль: реальные фразы с 'empty' по-прежнему чиним
    ("It's not over yet", "", "error"),                                      # реальная фраза
    ("Attack at dawn", "", "error"),                                         # реальная фраза
    ("Old World", "Old World", "echo"),                                       # echo не mixed
]

def main():
    fails = 0
    for en, ru, want in CASES:
        got = v.check_row(en, ru)
        ok = (got == want)
        print(f"[{'OK ' if ok else 'FAIL'}] en={en!r:42} ru={ru!r:40} -> {got:6} (want {want})")
        if not ok:
            fails += 1

    # validate_batch: clean
    rep = v.validate_batch(["Smithing", "A cheap weapon %s"], ["Кузнечное дело", "Дешёвое оружие %s"])
    assert not rep["hard"], rep
    print("[OK ] batch clean -> hard=False")

    # validate_batch: one hard error
    rep = v.validate_batch(["Smithing", "Ok text"], ["", "Дешёвое оружие"])
    assert rep["hard"] and rep["error"] == 1, rep
    print("[OK ] batch 1 error -> hard=True")

    # validate_batch: all-echo -> hard (model didn't translate)
    rep = v.validate_batch(["One Two", "Three Four"], ["One Two", "Three Four"])
    assert rep["hard"] and rep["echo"] == 2, rep
    print("[OK ] batch all-echo -> hard=True")

    # validate_batch: few legit echoes among good rows (1/4 = 25% < 50%) -> NOT hard
    rep = v.validate_batch(
        ["Spring Bat", "Old World", "Hello friend", "A long description text here"],
        ["Spring Bat", "Old World", "Привет друг", "Длинное описание текста"])
    assert not rep["hard"] and rep["echo"] == 2, rep
    print("[OK ] batch few echoes (2/4, 50%) -> hard=False")

    # validate_batch: majority echo (3/4, 75% > 50%) -> hard (model didn't translate)
    rep = v.validate_batch(
        ["One Two Three", "Four Five Six", "Seven Eight Nine", "Real sentence here"],
        ["One Two Three", "Four Five Six", "Seven Eight Nine", "Real sentence here"])
    assert rep["hard"] and rep["echo"] == 4, rep
    print("[OK ] batch 100% echoes -> hard=True")

    # validate_batch: non-list / length mismatch
    rep = v.validate_batch(["a"], None)
    assert rep["hard"]
    rep = v.validate_batch(["a", "b"], ["x"])
    assert rep["hard"]
    print("[OK ] batch None / len-mismatch -> hard=True")

    # audit_map — filled = VALID only (ok + already_ru + identifier);
    # echo/latin/ph_lost/empty are separate non-overlapping problem classes.
    entries = [{"i": 0, "original": "Some description text"},
               {"i": 1, "original": "Old World Bow"},
               {"i": 2, "original": "T34"}]
    done = {0: "Описание", 1: "Old World Bow", 2: "T34"}
    a = v.audit_map(entries, {str(k): val for k, val in done.items()})
    print(f"[INFO] audit_map: {a}")
    # 0 -> ok (translated), 1 -> echo (ru==en, 2 words), 2 -> identifier (T34 w/ digit)
    assert a["echo"] == 1 and a["filled"] == 2, a   # filled excludes echo
    assert a["identifiers"] == 1, a
    print("[OK ] audit_map: filled=valid, echo/identifier separated")

    print(f"\n{fails} row-level case(s) failed")
    return 1 if fails else 0

if __name__ == "__main__":
    raise SystemExit(main())
