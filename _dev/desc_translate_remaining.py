"""desc_translate_remaining v2 — перевести description у модов, у которых он пуст/EN.
Длинное описание (>~780 симв.) small-Qwen «роняет» ("invalid JSON"), поэтому
разрезаю по строкам/абзацам на куски <=500 симв. и шлю их ОДНИМ вызовом
TM.llm_call ([кусок1, кусок2, ...] -> [RU1, RU2, ...]) — battle-tested pipeline.
"""
import sys, os, json, importlib, re, time
sys.path.insert(0, 'H:/KenshiModTranslate')

# --- injected by move_to_dev: let us import core modules from parent ---
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
# --- end injected prologue ---

import translate_mods as TM, validate_translation as V
importlib.reload(TM); importlib.reload(V)
import verify_translations as VT; importlib.reload(VT)
STATE = 'H:/KenshiModTranslate/state'
nm = VT.build_name_map()
def log(*a): print(*a, flush=True)

def split_desc(text, maxn=500):
    # разбиваю на строки (\r\n / \n), группирую до maxn, не резю посередине строки
    lines = re.split(r"(\r\n|\n)", text)          # разделители остаются отдельными элементами
    chunks, cur = [], ""
    for seg in lines:
        if len(cur) + len(seg) > maxn and cur:
            chunks.append(cur); cur = seg
        else:
            cur += seg
    if cur.strip():
        chunks.append(cur)
    return [c for c in chunks if c.strip()] or [text]

names = [l.strip() for l in open(sys.argv[1] if len(sys.argv) > 1 else 'T:/need_desc_translation.txt', encoding='utf-8') if l.strip()]
ok = skip = fail = 0
for name in names:
    mods = [x for x in TM.workshop_mods() if x['name'].lower() == name.lower() and os.path.isfile(x.get('modfile') or '')]
    if not mods: log(f"  [!] {name}: не найден"); fail += 1; continue
    m = mods[0]
    hs = [k for k, v in nm.items() if v[0] == name]
    if not hs: log(f"  [!] {name}: нет в name_map"); fail += 1; continue
    h = hs[0]
    efile = f'{STATE}/{h}_entries.json'; mfile = f'{STATE}/{h}_mapping.json'
    entries = json.load(open(efile, encoding='utf-8'))
    mapping = json.load(open(mfile, encoding='utf-8')) if os.path.isfile(mfile) else []
    d = next((e for e in entries if e.get('key') == 'description'), None)
    if not d: log(f"  [!] {name}: нет description в кэше"); fail += 1; continue
    en = d.get('original') or ''
    if not en.strip(): continue
    row = next((x for x in mapping if str(x['i']) == str(d['i'])), None)
    cur = (row or {}).get('ru') or ''
    if any('\u0400' <= c <= '\u04ff' for c in cur) and len(cur) >= 10:
        skip += 1; continue
    chunks = split_desc(en, 500)
    res_chunks = None
    last_ex = None
    for _attempt in range(3):
        try:
            res = TM.llm_call(chunks)
            arr = res[0] if isinstance(res, tuple) and isinstance(res[0], list) else (res if isinstance(res, list) else [])
            if not isinstance(arr, list) or len(arr) != len(chunks):
                raise TM.Transient(f"len mismatch {len(arr) if isinstance(arr, list) else '?'} != {len(chunks)}")
            bad = sum(1 for c, r in zip(chunks, arr) if V.classify_row(c, r) in V.BAD_FIX_LEVELS)
            if bad:
                raise TM.Transient(f"{bad} кусков с ошибками")
            res_chunks = arr
            break
        except Exception as ex:
            last_ex = ex
            time.sleep(1.5)
    if res_chunks is None:
        log(f"  [!] {name}: 3 попытки не сдано ({str(last_ex)[:60]}…"); fail += 1; continue
    joined = "".join(str(x) for x in res_chunks)
    # записать
    mapping = [x for x in mapping if str(x['i']) != str(d['i'])]
    mapping.append({'i': d['i'], 'ru': joined})
    json.dump(mapping, open(mfile, 'w', encoding='utf-8'), ensure_ascii=False)
    TM.PROGRESS['progress'] = None
    ctx = {'nmods_done': 0, 'total_mods': 1, 't_llm': 0.0}
    TM.translate_one(m, 1, 1, ctx, drop_ids=None)
    log(f"  [OK] {name}: куски={len(chunks)} → {joined[:45]}…")
    ok += 1
log(f"ИТОГО: OK={ok}  уже-было={skip}  fail={fail}  из {len(names)}")
