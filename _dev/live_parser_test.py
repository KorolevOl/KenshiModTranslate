# -*- coding: utf-8 -*-
"""Прогон нового llm_call (strip_md + точный len + split) на чанке 350 строк,
который в живом ране упал с 'empty content'. 3 попытки, меряем расход."""
import json, time

# --- injected by move_to_dev: let us import core modules from parent ---
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
# --- end injected prologue ---

import translate_mods as TM

strs = json.load(open('T:/test_350.json', 'r', encoding='utf-8'))
TM.CUR["mapfile"] = None
TM.CUR["mapref"] = None

ok = 0
for i in range(3):
    t0 = time.time()
    try:
        res, trunc = TM.llm_call(strs)
        dt = time.time() - t0
        empty = sum(1 for r in res if not str(r).strip())
        print(f"попытка {i+1}: OK {len(res)}/350, {empty} пустых, {dt:.1f}s, trunc={trunc}")
        print(f"  первый: {res[0][:60]!r}")
        print(f"  последний: {res[-1][:60]!r}")
        ok += 1
    except Exception as e:
        dt = time.time() - t0
        print(f"попытка {i+1}: {str(e)[:150]}  ({dt:.1f}s)")
print(f"\nИтог: {ok}/3 попыток сдало чанк целиком")
