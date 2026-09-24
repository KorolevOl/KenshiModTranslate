"""game_localization.py — ЕДИНЫЙ источник «переведёт ли игра строку сама».

Модель (2026-09-24, по факту gamedata.po + BeakThingEggFoods):
  • Игра локализует объекты по OBJECT-ID записи (строки ``#: id-module`` в .po),
    а НЕ по тексту. Запись ``50606-BeakThingEggFoods.mod`` НЕ локализуется,
    даже если её текст («Beak Thing Egg») есть в .po — там он привязан к
    ``4029-gamedata.base``. ID переиспользуется между модами, поэтому ключ
    сравнения = парная ссылка ``id-module``.
  • Встроенные моды ядра (kenshi\\data\\*.mod: rebirth, Newwworld, Dialogue)
    рассматриваются как ИГРОВОЕ пространство: их записи игра знает и
    переводит сама по .po (и наоборот — их .po-переводы не надо дублировать
    оверлеем).
  • Строка считается «переведётся игрой» только если ЕЁ object-ID (id из key)
    реально перечислен в ``#:``-ссылках .po ЦЕЛЕВОГО языка.

Используется: translate_mods.py (GAME_SKIP + счёт «нужно перевести»),
prefilter.py (API), search_mods.py (таблицы + «можно перевести»),
csv_mod.py (export), verify_translations.py.
"""
import os
import re

# ---- встроенные моды ядра (kenshi\ data\*.mod) — игровое пространство ----
# Источник: каталог игры. Пересобирается при каждом вызове _base_modules()
# (дешево: 3-5 файлов), чтобы при переносе игры список был актуален.
_BASE_DIR_MEMO = {}

def base_modules(game_dir=None):
    """Множество имён .mod в kenshi\\data (rebirth.mod, Newwworld.mod, ...).

    Это встроенные моды ядра: их записи игра знает и переводит сама по .po.
    ``game_dir`` — путь к папке игры (config paths.game). Кэш по normcase.
    """
    game_dir = game_dir or os.environ.get("KENSHI_GAME_DIR", "")
    k = game_dir or ""
    if k in _BASE_DIR_MEMO:
        return _BASE_DIR_MEMO[k]
    mods = set()
    ddata = os.path.join(game_dir, "data") if game_dir else ""
    if ddata and os.path.isdir(ddata):
        try:
            for f in os.listdir(ddata):
                if f.lower().endswith(".mod"):
                    mods.add(f[: -len(".mod")].lower())
        except Exception:
            pass
    _BASE_DIR_MEMO[k] = mods
    return mods


# ---- record-ID парсинг из key записи ----
# Формат key (C# extract): record{ID}-<owner>[_<field>]
#   record4011-gamedata.base_name            → id=4011, owner=gamedata.base
#   record50606-BeakThingEggFoods.mod_name   → id=50606, owner=BeakThingEggFoods.mod
#   record5263-lanterns_otto.mod             → id=5263, owner=lanterns_otto.mod
#   record{ID}_name (старый кеш, без owner)  → id=NNNN, owner=None
# Owner ВНИМАНИЕ: сам содержит _ (lanterns_otto) — отделяем по РАСШИРЕНИЮ
# (.base/.mod), а не по последнему подчёркиванию.
_KEY_ID_RE = re.compile(r"^record(\d+)(?:-(.+))?$", re.I)

def record_ref_of_key(key):
    """``record50606-BeakThingEggFoods.mod_name`` → ``('50606','beakthingeggfoods.mod')``.

    Возвращает (record_id, owner_lower); любой None — key без record/id
    (топ-уровневое поле 'description' и т.п.).
    """
    if not key:
        return None, None
    k = (key or "").strip()
    if not k.lower().startswith("record"):
        return None, None
    m = _KEY_ID_RE.match(k)
    if not m:
        return None, None
    rid = m.group(1)
    rest = m.group(2)
    if not rest:
        return rid, None
    owner = None
    low = rest.lower()
    for ext in (".base", ".mod"):
        idx = low.rfind(ext)
        if idx >= 0:
            cand = rest[: idx + len(ext)]
            if owner is None or len(cand) > len(owner):
                owner = cand
    if owner is None:
        # расширения нет (старый формат) — поле после последнего '_'
        owner = rest.rsplit("_", 1)[0]
    return rid, owner.lower()

def mod_of_key(key):
    """Модуль-владелец записи из key (для проверки «своя/чужая/ядро»)."""
    _, mod = record_ref_of_key(key)
    return (mod or "").lower() or None

def is_mod_own(entry_or_key, mod_name):
    """True, если запись из СВОЕГО модуля мода (mod_name = имя .mod без ext,
    напр. 'BeakThingEggFoods'). Своя = та, которой нужен оверлей-перевод."""
    if isinstance(entry_or_key, dict):
        key = entry_or_key.get("key") or ""
    else:
        key = entry_or_key or ""
    mod = mod_of_key(key)
    if not mod or not mod_name:
        return False
    mm = (mod_name or "").lower()
    if mm.endswith(".mod"):
        mm = mm[: -4]
    return mod == mm


def is_base_entry(entry_or_key, mods_dict):
    """True, если запись из встроенного мода ядра (rebirth/Newwworld/...)."""
    if isinstance(entry_or_key, dict):
        mod = mod_of_key(entry_or_key.get("key") or "")
    else:
        mod = mod_of_key(entry_or_key)
    if not mod or not mods_dict:
        return False
    return mod[: -4] in mods_dict


# ---- .po record-refs (общее чтение) ----
import textutil  # parse_po_refs (единый парсер)

_PO_REFS_MEMO = {}
_GLOBAL_PO_PATHS = []

def configure(po_paths=None, game_dir=None):
    """Одноразовая настройка: список .po целевого языка + путь к игре.
    После вызова game_localizes()/should_translate() работают без аргументов."""
    global _GLOBAL_PO_PATHS
    _GLOBAL_PO_PATHS = list(po_paths or [])

def po_record_refs(po_paths=None):
    """Сет record-ссылок {id-module} из .po-файлов (мемо по кортежу путей)."""
    paths = _GLOBAL_PO_PATHS if po_paths is None else list(po_paths)
    key = tuple(sorted(paths or ()))
    if key in _PO_REFS_MEMO:
        return _PO_REFS_MEMO[key]
    refs = set()
    for p in key:
        try:
            refs |= textutil.parse_po_refs(p)
        except Exception:
            pass
    _PO_REFS_MEMO[key] = refs
    return refs

def game_localizes(entry_or_key, po_paths=None):
    """ГЛАВНЫЙ вопрос: «локализирует ли сама игра ЭТУ запись (object-ID)?»

    Критерий: пара (id, module) из key записи ∈ ``#:``-ссылкам .po ЦЕЛЕВОГО
    языка. Точно (по object-ID, не по тексту). Возвращает bool."""
    key = entry_or_key if not isinstance(entry_or_key, dict) else (entry_or_key.get("key") or "")
    rid, mod = record_ref_of_key(key)
    if not rid or not mod:
        return False
    refs = po_record_refs(po_paths)
    return ("%s-%s" % (rid, mod)) in refs

# ---- «описание МОДА» (топ-уровневое описательное поле) ----
def is_mod_description(entry_or_key):
    """True, если строка = описание САМОГО МОДА (топ-уровневое поле
    'description', не description рекорда). По key: ровно 'description'
    (без recordID). Именно эти строки игнорирует 'ignore_mod_description'."""
    if isinstance(entry_or_key, dict):
        key = (entry_or_key.get("key") or "").strip()
    else:
        key = (entry_or_key or "").strip()
    return key.lower() == "description"


def should_translate(entry_or_key, ignore_mod_description=True):
    """ЕДИНЫЙ предикат: «переводить ли ЭТУ строку мод-переводчиком».

    False (НЕ переводить — игра сама или настройка):
      • запись локализует сама игра (её object-ID ∈ #: ссылки .po ЦЕЛЕВОГО языка);
      • строка = описание САМОГО МОДА и включён ignore_mod_description.
    True — остальное (игровой текст из чужих/своих ID, записи мода и т.д.).
    Аргумент entry_or_key принимает dict entry ({'key':...}) или строку key.
    """
    if ignore_mod_description and is_mod_description(entry_or_key):
        return False
    return not game_localizes(entry_or_key)


if __name__ == "__main__":
    # smoke-тест (python game_localization.py "E:/...kenshi")
    import json, sys
    gdir = sys.argv[1] if len(sys.argv) > 1 else ""
    po = [os.path.join(gdir, "locale", "ru_RU", "gamedata.po")] if gdir else []
    mods = base_modules(gdir)
    po_refs = po_record_refs(po)
    print("base mods:", sorted(x + ".mod" for x in mods))
    print("po refs:", len(po_refs))
    for key in ["record4011-gamedata.base_name",
                "record50606-BeakThingEggFoods.mod_name",
                "record43954-rebirth.mod_name"]:
        print("  %-42s → %s" % (key, game_localizes(key, po)))
