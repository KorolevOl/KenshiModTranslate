"""cache.py — mod discovery (workshop_mods, game_mods, resolve_mod).

Вынесено из translate_mods.py (2026-09-24), чтобы:
  * csv_mod.py / revert_mods.py / verify_translations.py могли резолвить мод
    НЕ через тяжёлый translate_mods (тянет prefilter, po_hints, progress, overlay);
  * единый источник правил: игнор .backup/.orig_/.revert_/.prev/.new/.broken;
    kind "game" + gk "data"/"mods"; WORKSHOP-дерево.

API:
  cache.workshop_mods()  -> list[dict]
  cache.game_mods()      -> list[dict]
  cache.all_mods()       -> workshop_mods() + game_mods()
  cache.resolve_mod(query, all_mods, log=print)  -> dict | None

Формат элемента:
  {"id": "12345"|"game:rebirth"|"game:FCS_ext/x",
   "name": "Mod Name",
   "dir": "C:/path/to/mod_dir",
   "modfile": "C:/path/to/ModName.mod",   # None для некоторых workshop-модов
   "kind": "workshop"|"game",          # (game-моды)
   "gk": "data"|"mods"}                # (game-моды: где лежит)

Зависимости: kmt_paths. Без translate_mods, prefilter, po_hints, progress.
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
P = _CFG.get("paths", {})

GAME     = _resolve(P.get("game", ""))
WORKSHOP = _resolve(P.get("workshop", ""))

# Искусственные файлы — НЕ моды (бэкапы, кэш, промежуточные артефакты)
_SKIP_TAGS = (".backup", ".orig_", ".revert_", ".prev", ".new", ".broken", ".rebuild")


def workshop_mods():
    """Workshop-моды: Workshop/<appid>/<ModName.mod> (+<.info> для display name)."""
    out = []
    if not os.path.isdir(WORKSHOP):
        return out
    for d in sorted(os.listdir(WORKSHOP)):
        p = os.path.join(WORKSHOP, d)
        if not os.path.isdir(p) or not d.isdigit():
            continue
        name = None
        info = [f for f in os.listdir(p) if f.startswith("_") and f.endswith(".info")]
        if info:
            try:
                txt = open(os.path.join(p, info[0]), encoding="utf-8", errors="replace").read()
                m = re.search(r"<name>(.*?)</name>", txt, re.DOTALL)
                if m:
                    name = m.group(1).strip()
            except Exception:
                pass
        modfiles = [f for f in os.listdir(p) if f.lower().endswith(".mod")]
        if not name:
            name = (modfiles[0] if modfiles else d)[:-4]
        out.append({"id": d, "name": name, "dir": p,
                    "modfile": os.path.join(p, modfiles[0]) if modfiles else None})
    return out


def game_mods():
    """Встроенные моды ИГРЫ (2026-09-23):
      • kenshi\\data\\*.mod  — базовая локализация (rebirth.mod, Dialogue.mod, Newwworld.mod);
      • kenshi\\mods\\<sub>\\*.mod — вручную установленные (не Workshop).
    id человекочитаемый (`game:rebirth`, `game:FCS_extended/x`) — resolve_mod
    подхватывает его по подсстроке, если имя неоднозначно.
    Искусственные файлы (наши .backup/.revert_ и пр.) — игнорируются."""
    out = []
    seen = set()

    def add(p, idval, gk):
        p = os.path.abspath(p)
        key = os.path.normcase(p)
        if key in seen:
            return
        seen.add(key)
        base = os.path.basename(p)
        out.append({"id": idval, "name": base[:-4],
                    "dir": os.path.dirname(p), "modfile": p,
                    "kind": "game", "gk": gk})

    data_dir = os.path.join(GAME, "data")
    if os.path.isdir(data_dir):
        for f in sorted(os.listdir(data_dir)):
            if not f.lower().endswith(".mod") or not os.path.isfile(os.path.join(data_dir, f)):
                continue
            if any(tag in f for tag in _SKIP_TAGS):
                continue
            add(os.path.join(data_dir, f), f"game:{f[:-4]}", "data")
    mods_root = os.path.join(GAME, "mods")
    if os.path.isdir(mods_root):
        for d in sorted(os.listdir(mods_root)):
            dp = os.path.join(mods_root, d)
            if not os.path.isdir(dp):
                continue
            for f in sorted(os.listdir(dp)):
                if not f.lower().endswith(".mod") or not os.path.isfile(os.path.join(dp, f)):
                    continue
                if any(tag in f for tag in _SKIP_TAGS):
                    continue
                add(os.path.join(dp, f), f"game:{d}/{f[:-4]}", "mods")
    return out


def all_mods():
    """workshop_mods() + game_mods() — единый список."""
    return workshop_mods() + game_mods()


def resolve_mod(query, all_mods, log=print):
    """Резолв query в мод из all_mods.

    Порядок:
      1. Путь к .mod (абс. или относ.) — сразу.
      2. Каталог — ищем .mod внутри; если под Workshop-деревом — пытаемся
         найти по id родителя (appid).
      3. workshop-id (цифры).
      4. ТОЧНОЕ имя (case-insensitive) — primary.
      5. Substring match (для ручного запуска по куску имени).
    """
    q = query.strip()
    if os.path.isfile(q) and q.lower().endswith(".mod"):
        return {"id": "-", "name": os.path.basename(q)[:-4], "dir": os.path.dirname(q),
                "modfile": q}
    if os.path.isdir(q):
        mf = [os.path.join(q, f) for f in os.listdir(q) if f.lower().endswith(".mod")]
        if mf:
            if WORKSHOP and os.path.abspath(q).lower().startswith(WORKSHOP.lower()):
                parent = os.path.basename(os.path.dirname(q))
                for m in all_mods:
                    if m["id"] == parent:
                        return m
            return {"id": "-", "name": os.path.basename(os.path.normpath(q)),
                    "dir": q, "modfile": mf[0]}
    if q.isdigit():
        for m in all_mods:
            if m["id"] == q:
                return m
        return None
    ql = q.lower()
    # 1) ТОЧНОЕ имя (case-insensitive) — primary: кэш/verify дают точные заголовки.
    exact = [m for m in all_mods if (m["name"] or "").lower() == ql]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        log(f"[!] несколько мода с ИДЕНТИЧНЫМ именем '{q}' — неоднозначно, уточни id:")
        for i, m in enumerate(exact[:8]):
            log(f"    {i}: {m['name']}  (id {m['id']})  {os.path.basename(m['modfile'] or '')}")
        return None
    # 2) нет точного совпадения — substring
    def hay(m):
        return " ".join([m["name"] or "", m["id"], os.path.basename(m["modfile"] or "")]).lower()
    cands = [m for m in all_mods
             if ql in hay(m) or ql.replace(" ", "") in hay(m).replace(" ", "")]
    cands.sort(key=lambda m: len(m["name"] or ""))
    if len(cands) == 1:
        return cands[0]
    if len(cands) > 1:
        log(f"[!] несколько мода подходят для '{q}':")
        for i, m in enumerate(cands[:8]):
            log(f"    {i}: {m['name']}  (id {m['id']})")
        log("    выбери один: перезапусти командой с точным именем или id")
    return None
