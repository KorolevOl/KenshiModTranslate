"""Детерминистические проверки ответа LLM (ЧИСТО КОДОМ, без LLM/сети).

Цель: убедиться, что модель ДЕЙСТВИТЕЛЬНО перевела, а не отдала пустые строки,
мусор, или просто эхом вернула вход (частый баг reasoning-моделей).

Уровня по строке (check_row):
  ok     — нормальный перевод
  echo   — перевод ПОБУКВОВО совпадает с оригиналом (>=2 слова) -> не переведено
  warn   — нет кириллицы (>=2 слова) / однословный passthrough — может быть легитимно
  error  — настоящий баг: НЕ строка / пустой перевод / потерянный плейсхолдер

Правила отбраковки в validate_batch:
  * любая строка уровня error   -> отбраковать чанк (ретраи/деление в llm_call)
  * >50% строк уровня echo      -> отбраковать чанк (модель просто эхом вернула вход)
  * warn                        -> не отбраковывают (легитимные имена, коды), только лог
"""
import re
from collections import Counter

# Плейсхолдеры, которые модель ДОЛЖНА сохранить: %s %d %1$s %.2f {0} {1}.
# ВАЖНО: НЕ считаем обычным плейсхолдером ПРОЦЕНТ в тексте ("90% chance") —
# раньше флаг-пробел в [- 0+#]* жрал зазор и подбирал случайную букву, давая
# ложные "потерян %s". Правило: сразу за % должен идти флаг из [+-0#] (без
# пробела!), ширина/точность, затем конверсионная буква. "% chance" не match.
PLACEHOLDER_RE = re.compile(
    r"%\d+\$[+-0#]*\d*(?:\.\d+)?[diouxXeEfFgGcs]"   # positional: %1$s, %2$0.3f
    r"|%[+-0#]*\d*(?:\.\d+)?[diouxXeEfFgGcs%]"       # printf: %s, %d, %.2f (no space flag)
    r"|\{[0-9]+\}"                                    # format: {0} {1}
)
WORD_RE = re.compile(r"[A-Za-zА-Яа-яЁё]+")
CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")
CYRILLIC_WORD_RE = re.compile(r"[А-Яа-яЁё]{2,}")

# ЕДИНЫЙ ИСТОЧНИК (2026-09-19): какие уровни classify_row считаются «плохо»
# и подлежат пере-переводу. Используют И verify_translations (audit),
# И translate_mods (приём/отбраковка LLM-ответов), И validate_batch (hard).
# Раньше каждый модуль имел СВОЙ список — отсюда «находит ошибки, но не чинит».
BAD_FIX_LEVELS = ("empty", "echo", "ph_lost", "latin", "mixed", "tag_break")

def words(s):
    """Значимые «слова» строки: >=1 буква (киррлица/латиница) + цифры.
    Используется для проверки «есть ли в строке хоть одна буква».
    Плейсхолдеры срезаем сначала — иначе "%s" посчитается словом "s"."""
    if not isinstance(s, str):
        return []
    s = PLACEHOLDER_RE.sub(" ", s or "")
    return [w for w in WORD_RE.findall(s) if any(ch.isalpha() for ch in w)]


def is_identifier(s):
    """Идентификатор/имя ассета: строка, которую НУЖНО оставить как есть.

    Варианты (все — не переводимый код/имена):
      1) ОДИН токен с underscore/дефис/цифрой: wood_dex_dummy_pole, house03-base, T34
         ОДИН токен-аббревиатура (точки, части <=2 буквы): B.T.P., Mk.II
      2) составное имя ассета/меша (2-3 токена, в каждом _ или цифра или CamelCase,
         где-то есть _ или цифра): "MarketStall Grouped01_Mask"
      3) флаг/атрибут поведения AI Kenshi: "@Shopping -fluff", "@x +y" (@-атрибут + флаги)
      4) строка-имя меша/пропса любой длины (до 6 токенов), где есть _ и цифра:
         "Wall Level 01_METAL-FENCE 01"
    """
    if not isinstance(s, str):
        return False
    t = [x for x in PLACEHOLDER_RE.sub(" ", s or "").split() if x]
    if not t:
        return False
    if len(t) == 1:
        tok = t[0]
        if ("_" in tok) or (any(c.isdigit() for c in tok)):
            return True
        if "-" in tok:
            # 2026-09-20: дефис — НЕ всегда код. Имена NPC-типа с КАПСОМ
            # «Ex-Servant», «Anti-Slaver», «No-Face» — ДИСПЛЕЙНЫЕ имена,
            # пользователь хочет их перевести (LLM). Настоящие коды/кейсы
            # содержат цифры (KAR-98, house03-base), начинается со строчной
            # (snake/kebab: anti-aliasing) или underscore — остаёмся ID.
            parts = [x for x in re.split(r"[-]+", tok) if x]
            if parts and all(x[0].isupper() and x.isalpha() for x in parts):
                return False   # имя с КАПСоМ — переводим
            return True
        # аббревиатура: точки + короткие латинские части (B.T.P., Mk.II)
        if "." in tok:
            parts = [p for p in re.split(r"[^A-Za-zА-Яа-яЁё]+", tok) if p]
            if parts and all(1 <= len(p) <= 2 for p in parts):
                return True
        # 5) entry/record-ID мода (2026-09-19, NewRecruits 4922/4923:
        #    «ZInterestingRecruitsStobe'sGardenEntry») — CamelCase-связка +
        #    суффикс Entry = второстепенный ключ записи мода, НЕ переводимый
        #    текст. LLM правомерно не даёт перевода; раньше «empty -> чинить»
        #    зацикливал фиксер. Правило: один токен, >=2 заглавные внутри,
        #    суффикс «Entry», только буквы/цифры/'/$.
        if tok.endswith("Entry") and len(tok) >= 6:
            caps = sum(1 for ch in tok if ch.isupper())
            if caps >= 2 and re.match(r"^[A-Za-z0-9'$]+$", tok):
                return True
        return False
    # 4) имя меша/пропса: underscore + цифра в составе (до 6 токенов)
    if len(t) <= 6 and any("_" in tok for tok in t) and any(any(c.isdigit() for c in tok) for tok in t):
        return True
    # kaizo (2026-09-19): /TAG/ emote-теги Kenshi (tone/anger markup) — НЕ
    # переводятся намеренно. Помечаются идентификатором, чтобы не считать их
    # «эхом». Строка считается emote, если содержит хотя бы один /TAG/ и НЕ
    # содержит «живых» английских/русскаких слов-длина (реальные слова вроде
    # "bandits" в "/GETLOST/, /GODDAMN/ /DIRTY/ bandits!" — НЕ emote, модель
    # их правильно переводит).
    has_emote = any(re.fullmatch(r"/[A-Za-z0-9_]{2,40}/[A-Za-z0-9!.,'\u2019;:\-]*", tok) for tok in t)
    if has_emote and all(
        re.fullmatch(r"/[A-Za-z0-9_]{2,40}/[A-Za-z0-9!.,'\u2019;:\-]*", tok)
        or re.fullmatch(r"[|/!.,\-…\s]+", tok)
        or re.fullmatch(r"[А-Яа-яЁё]{1,6}", tok)
        for tok in t
    ):
        return True
    ident_like = lambda tok: ("_" in tok) or ("-" in tok) or any(c.isdigit() for c in tok)
    # 3) @-атрибуты AI (Kenshi behavior flags): "@Shopping -fluff"
    if any(tok.startswith("@") for tok in t) and all(ident_like(tok) or len(tok) <= 10 for tok in t):
        return True
    # 2) составные имена мешей/пропсов: "MarketStall Grouped01_Mask"
    if any("_" in tok for tok in t) and all(ident_like(tok) or re.match(r"^[A-Z][a-z]+[A-Z]", tok) for tok in t):
        return True
    return False


def is_display_name(s):
    """Имя NPC/фракции с дефисом и КАПСом: «Ex-Servant», «Anti-Slaver»,
    «No-Face». Это ДИСПЛЕЙНЫЙ текст — LLM имеет право перевести ИЛИ оставить
    (эхо). Эхо = 'ok' (не фиксить), как у onomatopoeia (2026-09-20) — иначе
    фиксер зацикливается на строке, которую LLM сознательно не переводит."""
    if not isinstance(s, str):
        return False
    t = [x for x in (s or "").split() if x]
    return len(t) == 1 and "-" in t[0] and all(
        re.fullmatch(r"[A-Z0-9][A-Za-z0-9]*", p) for p in re.split(r"-+", t[0]) if p
    )


def already_russian(s):
    """True если оригинал строки уже по-русски (кириллица >= латыни) —
    тогда ничего переводить не надо и совпадение перевода с оригиналом ок."""
    if not isinstance(s, str):
        return False
    c = sum(1 for ch in s if "\u0400" <= ch <= "\u04ff")
    l = sum(1 for ch in s if "a" <= ch.lower() <= "z")
    return c > 0 and c >= l


def cyrillic_words(s):
    """Число настоящих русских слов (>=2 кириллические буквы)."""
    if not isinstance(s, str):
        return 0
    return len(CYRILLIC_WORD_RE.findall(s or ""))


def has_real_russian(s):
    """True если строка УЖЕ содержит реальный русский текст (>=5 слов),
    даже если есть и английский — двуязычные описания автора:
    «Простинкий мод на нижнее бельё... This mod in Russian language...».
    В таком случае оставить как есть (ru==en) — корректно, а не «эхо»."""
    return cyrillic_words(s) >= 5


def is_onomatopoeia(en):
    """Чистое «возду» / онотопоэзия — звук, а не слово (2026-09-19, Bounties Galore:
    «So- So- SooooOOOooooRRRRrrrYY!», «WHYYYYYYYYY!!!??», «ssss ssSStttOOOOOPP»).
    LLM ПРАВОмерно не переводит их; раньше классификатор метил их «empty -> чинить»,
    фиксер звал LLM — LLM снова «пусто» — цикл «находит–нечинит». Правило:
    мало разнообразия букв (<=0.40) И есть «затянутая» буква (3+ подряд) = звук.
    Реальные фразы («Attack at dawn» 0.58, «Kill the dragon» 0.92) — НЕ попадают.

    2026-09-19 (переделано): надёжный дискриминационный признак — ЧИСЛО РАЗНЫХ
    БУКВ (≤5). Звук строится из 2–4 букв (no={n,o}, WHYYYY={w,h,y}, RRRR={r}),
    как бы ни был длинным («no,no,…×20» = 179 симв., но ≤5 букв). У ЛЮБОЙ прозы
    12+ разных букв (даже при «низком div»). Старое правило (div<=0.40 И тройка
    подряд) ложно срабатывало на описаниях: div у длинного текста всегда мал
    (25/774=0.03), и любая тройка (still→lll, coffee→fff) давала «свист» — из-за
    этого ~35 описаний v17-модов (Stronger Barkeepers и др.) остались без
    перевода. Сейчас: (растянутая буква 3+ подряд ИЛИ заикание корня ×4+)
    И ОГРАНИЧЕНИЕ ≤5 разных букв. Проза (15+ букв) больше не попадает."""
    s = re.sub(r"[^A-Za-zА-Яа-яЁё]", "", (en or "").lower())
    if not s:
        return False
    if len(set(s)) > 5:
        return False
    stretch = any(s[i] == s[i+1] == s[i+2]
                  for i in range(len(s) - 2))
    if stretch:
        return True
    roots = re.findall(r"[a-zа-яё]{2,}", (en or "").lower())
    if roots:
        most = max(roots, key=roots.count)
        if roots.count(most) >= 4:
            return True
    return False


_SLAH_TAG_RE = re.compile(r"/[^\s/]+/")

def slash_tags(s):
    """Все /TAG/ вхождения в строке (слова движка: /HOLYGREET/, /PATRON/, /OI/).

    2026-09-20: LLM перевела /FAVORITE/ → /ЛУБЯЩЕЕ/, /PATRON/ → /КЛИЕНТ/ (мод
    Talk-to-shopkeepers) и т.п. — движок не распознаёт кириллические ключи и
    диалог в игре теряет смысл. Правило: содержимое /TAG/ — ТОЛЬКО латиница,
    цифры, _ и - ; кириллица/CJK/пробелы внутри = сломан тег."""
    if not s:
        return []
    out = []
    for m in _SLAH_TAG_RE.finditer(s):
        t = m.group()
        if re.search(r"[\u0400-\u04FF\u3040-\u9FFF\uAC00-\uD7AF]", t):
            out.append(t)
    return out

# Строгий тег движка: /[A-Za-z0-9_-]+/ (только ASCII внутри, без пробелов,
# без «/а1/», «/аяый/» и другого авторского). Это ТО-самый токен, который
# подставляет движок Kenshi (название NPC, приветствие, профессия…).
_TAG_ASCII = re.compile(r"/[A-Za-z0-9_\-]+/")

def tag_set(s):
    """Множество строгих ASCII-тегов движка в строке (нижний регистр)."""
    if not s:
        return frozenset()
    return frozenset(t.lower() for t in _TAG_ASCII.findall(s))

def classify_row(en, ru):
    """ЕДИНЫЙ источник правды: нужно ли FIX-ить строку.

    Вёрнит статус:
      ok         — перевод корректен (или строка не требует перевода)
      already_ru — оригинал и так русский, оставлен как есть (ок, не фиксить)
      identifier — имя ассета/кода, оставлен как есть (ок, не фиксить)
      empty      — перевод пуст, а в оригинале есть текст (FIX)
      ph_lost    — потерян плейсхолдер (%s, {0}, ...) (FIX)
      echo       — перевод побуквенно == оригиналу (FIX)
      latin      — перевод без кириллицы, >=2 слова (FIX)

    `ru` может быть None (нет в маппинге) — это тоже рассматриваем.
    Используется и проверкой (verify) и фиксом (repair) — гарантия, что
    fix чинит ровно то, что check пометил.
    """
    en = en or ""
    en_w = words(en)
    en_ph = placeholders(en)
    # -- пустой/отсутствующий перевод --
    if ru is None or not str(ru).strip():
        if is_onomatopoeia(en):
            return "ok"          # звук/возду — переведти нечего (LLM правомерно не дает)
        if is_identifier(en):
            return "identifier"  # asset/entry-ID — не переводится намеренно (Z…Entry, asset name)
        if en_w or en_ph:
            return "empty"
        return "ok"               # обе пустые/только знаки — нечего переводить
    ru = str(ru)
    # -- оригинал уже русский / идентификатор: не фиксим --
    if already_russian(en):
        return "already_ru"
    if is_identifier(en):
        return "identifier"
    # 2026-09-20: крики/звуки (onomatopoeia) — LLM может вернуть:
    #   (a) правильный RU  ("Aaargh!" → "Ааааа!")  — отлично
    #   (b) ЭХО            ("Aaargh!" → "Aaargh!")  — тоже ОК, это звук
    # Раньше (b) падало в "echo" (norm(ru)==norm(en), len>=2 words) → фиксер бесконечно чинил.
    # Теперь: любой RU для onomatopoeia = "ok".
    if is_onomatopoeia(en):
        return "ok"
    # -- двуязычное описание (автор сам вставил русский): ru==en корректно --
    # 2026-09-20: слэш-теги движка (/HOLYGREET/, /PATRON/..., /DISGUISEDNAME/) —
    # ВСТАВКИ ДВИЖКА (подставляются динамически: имя NPC, приветствие, раса…).
    # Три вида поломки (все → tag_break = FIX):
    #   (а) кириллица ВНУТРИ тега в RU:  /FAVORITE/ → /ЛУБЯЩЕЕ/,  /INSULT/ → /ОБРАЗА/;
    #   (б) тег есть в EN, но ПРОПАЛ в RU:  «/DISGUISEDNAME/, you're back!» → «Наконец-то, …» (тега нет);
    #   (в) RU пустое, а в EN были теги движка («сдалась»);
    #   (г) EN пустое, а в RU НЕТ тегов движка (пустой ответ + тег утерян).
    # Детект срабатывает ТОЛЬКО когда в ЛЮБОМ из EN/RU есть строгий ASCII-тег движка
    # (/[A-Za-z0-9_-]+/), поэтому НЕ трогает авторские скобки в русском тексте
    # («уверен/а1/», «смел/аяый/») — они не имеют ASCII-тег.
    # Критично: если в RU есть правильный ASCII-тег (не кириллица внутри), и EN пусто —
    # это НОРМАЛЬНО (движок возьмёт из RU), НЕ брaк.
    any_en_or_ru_tag = tag_set(en) or tag_set(ru)
    if any_en_or_ru_tag:
        # (а) кириллица в тегах RU (реальный брак)
        if slash_tags(ru):
            return "tag_break"
        # (б) есть тег в EN, но пропал в RU
        en_tags = tag_set(en)
        if en_tags and (en_tags - tag_set(ru)):
            return "tag_break"
        # (в) RU пустое, а EN несёт теги движка («сдалась»)
        if not ru.strip() and en_tags:
            return "tag_break"
        # (г) EN пустое, а RU несёт кириллицу без тегов (тег движка утерян)
        if not en.strip():
            ru_has_cyr = any('\u0400' <= c <= '\u04ff' for c in (ru or ''))
            if ru_has_cyr and not tag_set(ru):
                # RU есть (кириллица), но ни одного ASCII-тега — утерян тег
                return "tag_break"
    if has_real_russian(en):
        return "already_ru"
    # -- твёрдые проблемы --
    if en_ph:
        ok, _ = _placeholder_subset_ok(en, ru)
        if not ok:
            return "ph_lost"
    if en_w and len(en_w) >= 2 and not is_display_name(en) and norm(ru) == norm(en):
        return "echo"
    # opeshka (mixed script): настоящий русский текст, в котором «ролeвают»
    # латинские буквы или иероглифы CJK — типичный LLM-артефакт: «Ворхaнцы»,
    # «Пomощь», «Китайскиe руины». Правило: >=2 кириллич. слова И >=1 «вкрапленное»
    # слово (одновременно кириллица + латынь/CJK). Чистая латынь без кириллицы
    # всё ещё идёт в 'latin'; отдельное лат. слово («AI», «C++») не считается
    # (в нем нет кириллицы — это нормальный технический термин).
    if cyrillic_words(ru) >= 2 and _mixed_script_words(ru) >= 1:
        return "mixed"
    if en_w and len(en_w) >= 2 and not is_display_name(en) and not has_cyrillic(ru):
        return "latin"
    return "ok"

_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]+")

def _mixed_script_words(s):
    """Кол-во «вкрапленных» слов: и кириллица, и латынь или CJK в ОДНОМ токе
    — именно так выглядит опечатка-артефакта («Ворхaнцы», «Пomощь»).»
    ВАЖНО (2026-09-19): сначала снимаем BBCode/[url=...] теги — тег, приклеенный
    к русскому слову («[M][Чёрная]», «[h1]ОБО[/h1]»), ложно даёт «кирил+латынь»
    и превращает корректный перевод в ложный 'mixed' (fix зря пере-переводил,
    HatedMekkr 157/157 — все ложные). Реальная опечатка ВНУТРИ слова остаётся.»
    """
    if not isinstance(s, str):
        return 0
    # 2026-09-19 (по просьбе пользователя): снимаем BOTH markup:
    #  [..]        — BBCode/Kenshi теги ([M][Чёрная], [h1]..[/h1], [url=..]..)
    #  /AAA/       — слэш-теги движка/модов: /PROCESSORSOUND/ /FAVORITE/ /DISGUISEDNAME/
    #               /FUCK/ /OI/ и т.п. — СПЕЦИАЛЬНЫЕ ВСТАВКИ ДВИЖКА, не «опечатки».
    # До этого строка с корректным переводом (тег + кириллица) ложно шла в 'mixed'
    # и фиксер ОТСЕКАЛ ПРАВИЛЬНЫЙ ответ LLM (PAK_Unit: «авторизация не распознана»).
    s = re.sub(r"\[[^\[\]]*\]|/[A-Za-z0-9_]{2,40}/", " ", s)
    n = 0
    for t in (s or "").split():
        has_cyr = any("\u0400" <= ch <= "\u04ff" for ch in t)
        has_lat = any("a" <= ch.lower() <= "z" for ch in t)
        has_cjk = bool(_CJK_RE.search(t))
        if has_cyr and (has_lat or has_cjk):
            n += 1
    return n

def has_cyrillic(s):
    return bool(CYRILLIC_RE.search(s or ""))

def placeholders(s):
    return PLACEHOLDER_RE.findall(s or "")

def norm(s):
    return re.sub(r"\s+", " ", (s or "").strip()).lower()

def _placeholder_subset_ok(en, ru):
    need = Counter(placeholders(en))
    have = Counter(placeholders(ru))
    lost = need - have
    return not any(lost.values()), list(lost.elements())

def check_row(en, ru):
    """LLM-ответ по одной строке: "ok" | "echo" | "warn" | "error".

    Единый источник правды — classify_row; сюда добавляются 2 твёрдых LLM-бага,
    которые корректные правила classify_row не покрывают:
      * ru не является строкой (модель дала dict/число)
      * ru = ТОЛЬКО знаки, хотя в оригинале были слова и плейсхолдеры
        (напр. "!!!", "..." из нормального текста) — модель потеряла слова.
        (Короткий оригинал из одних знаков, "!!!", "...", "—" — легитимный
        passthrough, НЕ ошибка: там и переводить нечего.)
    """
    if not isinstance(ru, str):
        return "error"
    en_w = words(en)
    if ru and not re.search(r"[A-Za-zА-Яа-яЁё0-9]", ru):
        # только знаки: ошибка, если в оригинале были слова или плейсхолдеры;
        # иначе — короткая строка из знаков (passthrough).
        if en_w or placeholders(en):
            return "error"
        return "ok"
    lvl = classify_row(en, ru)
    if lvl in ("empty", "ph_lost", "mixed", "latin", "tag_break"):
        # ПЛОХО по определению детектора (FIX_BAD_LEVELS) → фиксер отбраковывает LLM-ответ.
        # tag_break (2026-09-20): LLM перевела /TAG/ (/FAVORITE/ → /ЛУБЯЩЕЕ/).
        return "error"
    if lvl == "echo":
        return "echo"
    # ok / already_ru / identifier are fine
    # one-word passthrough on a Latin original (e.g. "MkII") -> warn
    if lvl == "ok" and not has_cyrillic(ru) and len(words(en)) >= 1 and not is_identifier(en):
        # 2026-09-19: чистое «возду» (SOOOO!, Aaargh!) — НЕ «1-словный код»,
        # classify_row уже сказал ok; не заворачиваем в warn.
        if is_onomatopoeia(en):
            return "ok"
        # already handled: latin>=2 words is 'latin'; 1 word w/o digit is a legit code
        if len(words(en)) == 1:
            return "warn"
    return "ok"


def audit_map(entries, done):
    """Summarise a translation map before apply (no LLM).

    Single source of truth: classify_row. Returns counts so both verify
    and translate_one agree exactly on what counts as bad.
    """
    counts = {"ok": 0, "already_ru": 0, "identifier": 0,
              "empty": 0, "echo": 0, "latin": 0, "ph_lost": 0, "mixed": 0}
    echo_rows = []
    for e in entries:
        i = str(e["i"])
        ru = (done.get(i) or "").strip()
        lvl = classify_row(e.get("original") or "", ru or None)
        counts[lvl] = counts.get(lvl, 0) + 1
        if lvl == "echo":
            echo_rows.append(i)
    filled = counts["ok"] + counts["already_ru"] + counts["identifier"]
    return {
        "filled": filled,
        "empty": counts["empty"],
        "echo": counts["echo"],
        "latin": counts["latin"],
        "ph_lost": counts["ph_lost"],
        "filled_real": filled,          # back-compat key translate_one uses
        "echo_rows": echo_rows,
        "identifiers": counts["identifier"],
        "already_ru": counts["already_ru"],
    }

def validate_batch(strings, rows):
    """Вернуть report dict:
       {hard: bool, reason: str, n: int, error: int, echo: int, warn: int}
    hard=True => llm_call отбраковывает чанк.
    """
    rep = {"hard": False, "reason": "", "n": len(strings), "error": 0, "echo": 0, "warn": 0}
    if rows is None or not isinstance(rows, (list, tuple)):
        rep["hard"] = True
        rep["reason"] = "model returned no array"
        return rep
    if len(rows) != len(strings):
        rep["hard"] = True
        rep["reason"] = f"length mismatch: {len(rows)}/{len(strings)}"
        return rep
    for en, ru in zip(strings, rows):
        lvl = check_row(en, ru)
        if lvl == "error":
            rep["error"] += 1
        elif lvl == "echo":
            rep["echo"] += 1
        elif lvl == "warn":
            rep["warn"] += 1
    # hard: есть хоть одна настоящая ошибка ИЛИ большинство строк — эхо
    if rep["error"] > 0:
        rep["hard"] = True
        rep["reason"] = f"{rep['error']} строка(й) с ошибкой (пусто/мусор/плейсхолдер)"
    elif rep["echo"] > rep["n"] * 0.5 and rep["n"] > 0:
        rep["hard"] = True
        rep["reason"] = f"эхо: {rep['echo']}/{rep['n']} строк не переведены (повтор оригинала)"
    return rep


