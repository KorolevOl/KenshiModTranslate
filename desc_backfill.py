"""desc_backfill.py — вернуть в кэш ПОТЕРЯННОЕ описание (description) у v17-модов,
где оно осталось английским (сброшено старым C# ExtractEntries, FileType==16).

Логику:
  1) EN-описание достаём ИЗ БЭКАПА (EN-оригинал — там description ещё на EN);
  2) entries-кэш = [description @ i=0] + старые записи (сдвиг i → i+1);
     индексация СОВПАДАЕТ с новым C# extract (description всегда первым);
  3) mapping-кэш переклеиваем i→i+1;
  4) TM.translate_one: resume увидит 1 незакрытую строку (description) →
     LLM переведёт ТОЛЬКО её (1 вызов) → apply запишет Description в .mod.

dry-run: показывает, что будет — с кэшами не трогает.
"""
import sys, os, json, re, shutil, subprocess, struct
sys.path.insert(0, 'H:/KenshiModTranslate')
import translate_mods as TM
import importlib
importlib.reload(TM)
DOTT = TM.P["dotnet"]; DLL = TM.P["modtranslate_cli"]
STATE = 'H:/KenshiModTranslate/state'

def log(*a): print(*a, flush=True)

def find_mod(name):
    for m in TM.workshop_mods():
        if m['name'].lower() == name.lower() and os.path.isfile(m.get('modfile') or ''):
            return m
    return None

def find_backup(src):
    d = os.path.dirname(src); base = os.path.basename(src)
    for f in os.listdir(d):
        if f.startswith(base + ".orig_") and f.endswith(".backup"):
            return os.path.join(d, f)
    return None

def hash_from_backup(bk):
    b = os.path.basename(bk)
    h = b[b.index(".orig_") + 6: b.rindex(".backup")]
    return h

def extract_desc_from(bk):
    out = 'T:/bf_desc.json'
    subprocess.run([DOTT, DLL, 'extract', bk, out], capture_output=True, text=True, timeout=60)
    es = json.load(open(out, encoding='utf-8'))
    for e in es:
        if e.get('key') == 'description' and (e.get('original') or '').strip():
            return e['original']
    return None

def process(name, dry=True):
    m = find_mod(name)
    if not m: log(f"  [!] {name}: не найден в workshop"); return False
    src = m['modfile']; bk = find_backup(src)
    if not bk: log(f"  [!] {name}: нет бэкапа EN — описание не восстановить"); return False
    h = hash_from_backup(bk)
    efile = os.path.join(STATE, h + '_entries.json')
    mfile = os.path.join(STATE, h + '_mapping.json')
    if not os.path.isfile(efile):
        log(f"  [!] {name}: нет кеша-записей {h}"); return False
    old_entries = json.load(open(efile, encoding='utf-8'))
    if any(e.get('key') == 'description' for e in old_entries):
        log(f"  (=) {name}: description уже в кэше — пропускаю"); return True
    desc_en = extract_desc_from(bk)
    if not desc_en: log(f"  [!] {name}: в бэкапе нет description"); return False
    old_map = []
    if os.path.isfile(mfile):
        old_map = json.load(open(mfile, encoding='utf-8'))
    new_idx = {str(e["i"]) for e in old_entries}
    remapped = 0; dropped = 0
    mapped = []
    for r in old_map:
        # сдвиг i→i+1 ВСЕГДА валиден: new_entries = [description@0] + старые (i+1),
        # т.е. индексы 1..N существуют гарантированно (2026-09-19: проверял по
        # старым entries и ошибочно выкидывал последнюю строку мода)
        mapped.append({'i': int(r['i']) + 1, 'ru': r.get('ru')}); remapped += 1
    if dropped:
        log(f"  [warn] {dropped} строк выкинуто из mapping")
    new_entries = [{'i': 0, 'key': 'description', 'original': desc_en}]
    for e in old_entries:
        e2 = dict(e); e2['i'] = e['i'] + 1; new_entries.append(e2)
    log(f"  [OK] {name}: description='{desc_en[:50]}…' | entries {len(old_entries)}→{len(new_entries)} | mapping {len(old_map)}→{len(mapped)} (+{dropped} выкинуто)")
    if not dry:
        tmp_e = efile + '.new'; tmp_m = mfile + '.new'
        json.dump(new_entries, open(tmp_e, 'w', encoding='utf-8'), ensure_ascii=False)
        json.dump(mapped, open(tmp_m, 'w', encoding='utf-8'), ensure_ascii=False)
        os.replace(tmp_e, efile); os.replace(tmp_m, mfile)
        # 4) translate_one: переведёт только description и запишет .mod
        ctx = {'nmods_done': 0, 'total_mods': 1, 't_llm': 0.0}
        TM.PROGRESS['progress'] = None
        ok = TM.translate_one(m, 1, 1, ctx, drop_ids=None)
        log(f"  translate_one: {'OK' if ok else 'FAIL'}")
    return True

if __name__ == '__main__':
    dry = '--run' not in sys.argv
    names = [a for a in sys.argv[1:] if a not in ('--run', '--file')]
    if '--file' in sys.argv or not names:
        lf = 'T:/en_desc_mods.txt'
        if os.path.isfile(lf):
            names = [l.strip() for l in open(lf, encoding='utf-8') if l.strip()]
    log(f"Режим: {'dry-run' if dry else 'RUN'} | {len(names)} мод(ов)")
    ok = 0
    for n in names:
        try:
            if process(n, dry): ok += 1
        except Exception as ex:
            log(f"  [!] {n}: {ex}")
    log(f"Итого: {ok}/{len(names)}")
