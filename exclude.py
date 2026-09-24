"""exclude.py — правила исключений (exclude.txt) + флаг INCLUDE_EXCLUDED.

Вынесено из translate_mods.py (2026-09-24), чтобы revert_mods.py и
verify_translations.py резолвили «исключён ли мод?» напрямую, не таща
тяжёлый граф translate_mods (prefilter, po_hints, progress, overlay).

Ключевой mutable:
  * EXCLUDE_RES — список re.Pattern, из исключений.
  * INCLUDE_EXCLUDED — глобальный флаг (default: из env KENSHI_INCLUDE_EXCLUDED
    = "1"; revert_mods.py может переопределить на лету через CLI "--include-excluded").

API:
  exclude.EXCLUDE_RES          # list[re.Pattern]
  exclude.EXCL_PATH            # abs path к exclude.txt
  exclude.INCLUDE_EXCLUDED     # bool
  exclude.is_excluded(name, modfile=None)  # bool

Совместимость: translate_mods.py и revert_mods.py продолжают писать в
TM.is_excluded / TM.INCLUDE_EXCLUDED — через re-export ниже.
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


EXCL_PATH = T.get("exclude_file", "exclude.txt")
if not os.path.isabs(EXCL_PATH):
    EXCL_PATH = os.path.join(_HERE, EXCL_PATH)

EXCLUDE_RES = []
if os.path.isfile(EXCL_PATH):
    for _ln in open(EXCL_PATH, encoding="utf-8-sig", errors="replace"):
        _ln = _ln.strip()
        if not _ln or _ln.startswith("#"):
            continue
        try:
            EXCLUDE_RES.append(re.compile(_ln, re.IGNORECASE))
        except re.error as ex:
            print(f"[warn] bad exclude regex skipped: {_ln!r} ({ex})", file=sys.stderr)


INCLUDE_EXCLUDED = os.environ.get("KENSHI_INCLUDE_EXCLUDED") == "1"


def is_excluded(name, modfile=None):
    """True if the mod name (or .mod filename) matches any exclusion pattern."""
    texts = [name or ""]
    if modfile:
        texts.append(os.path.basename(modfile))
        texts.append(os.path.basename(modfile)[:-4])
    # variant with common separators normalized to spaces so \b works on "RecruitPrisoners_RUS"
    for _t in list(texts):
        texts.append(re.sub(r"[_\-().]+", " ", _t))
    for rx in EXCLUDE_RES:
        for _t in texts:
            if _t and rx.search(_t):
                return True
    return False


def set_include_excluded(flag: bool):
    """Переключить флаг на лету (для CLI-операций типа revert_mods --include-excluded)."""
    global INCLUDE_EXCLUDED
    INCLUDE_EXCLUDED = bool(flag)
