import sys, os, json, struct, subprocess
sys.path.insert(0,'H:/KenshiModTranslate')
import importlib, translate_mods as TM
importlib.reload(TM)
DOTT=TM.P["dotnet"]; DLL=TM.P["modtranslate_cli"]
state='H:/KenshiModTranslate/state'

def stats(s):
    c=sum(1 for ch in (s or "") if '\u0400'<=ch<='\u04ff')
    lat=sum(1 for ch in (s or "") if 'a'<=ch.lower()<='z')
    return c,lat

def mostly_cyr(s):
    c,lat=stats(s); return c>0 and c>=lat and c>=4

mods=[m for m in TM.workshop_mods() if m.get('modfile') and os.path.isfile(m['modfile'])]

en_desc=[]; ru_desc=[]; no_desc=[]
for m in mods:
    mf=m['modfile']
    try:
        ft=struct.unpack('<I',open(mf,'rb').read(4))[0]
    except Exception:
        continue
    if ft!=17: continue
    out='T:/descchk1.json'
    try:
        subprocess.run([DOTT,DLL,'extract',mf,out],capture_output=True,text=True,timeout=45)
        es=json.load(open(out,encoding='utf-8'))
    except Exception:
        continue
    d=[e for e in es if e.get('key')=='description']
    if not d or not (d[0].get('original') or '').strip():
        no_desc.append(m['name']); continue
    txt=d[0]['original']
    (ru_desc if mostly_cyr(txt) else en_desc).append(m['name'])

# кэши: есть ли у этого мода description в mapping.json
name2hash={}
for fn in sorted(os.listdir(state)):
    if fn.endswith('_entries.json'):
        h=fn[:12]
        ep=os.path.join(state,h+'_entries.json')
        mp=os.path.join(state,h+'_mapping.json')
        try:
            es=json.load(open(ep,encoding='utf-8'))
            mm=json.load(open(mp,encoding='utf-8')) if os.path.isfile(mp) else []
        except Exception:
            continue
        for e in es:
            if e.get('key')=='description':
                row=next((x for x in mm if str(x.get('i'))==str(e.get('i'))),None)
                ru=(row or {}).get('ru') or ''
                name2hash.setdefault(None,{}).setdefault(m_name,None) if False else None

# проще: по каталогу workshop — имя через TM
import importlib, verify_translations as VT
importlib.reload(VT)
nm=VT.build_name_map()
h2name={v[0]:k for k,v in nm.items()}
desc_in_cache={}
for fn in sorted(os.listdir(state)):
    if not fn.endswith('_entries.json'): continue
    h=fn[:12]
    ep=os.path.join(state,h+'_entries.json'); mp=os.path.join(state,h+'_mapping.json')
    try:
        es=json.load(open(ep,encoding='utf-8'))
    except Exception:
        continue
    if not any(e.get('key')=='description' for e in es): continue
    name=h2name.get(h)
    if not name: continue
    mm=[]
    if os.path.isfile(mp):
        try: mm=json.load(open(mp,encoding='utf-8'))
        except: pass
    row=None
    for e in es:
        if e.get('key')=='description':
            row=next((x for x in mm if str(x.get('i'))==str(e.get('i'))),None)
    ru=(row or {}).get('ru') or ''
    desc_in_cache[name]=bool(mostly_cyr(ru))

print(f"v17 с описанием: EN={len(en_desc)}, RU={len(ru_desc)}, без описаний={len(no_desc)}")
miss=[n for n in en_desc if not desc_in_cache.get(n)]
print(f"\n{len(en_desc)} модов с ЕЩЁ АНГЛИЙСКИМ описанием; из них без RU-описания в кэше: {len(miss)}")
print("Пример (первые 15):")
for n in miss[:15]: print("  ✗",n)
# и у RU-модов тоже проверить наличие RU в кэше (контроль)
ru_ok=[n for n in ru_desc if desc_in_cache.get(n)]
print(f"\n[контроль] среди {len(ru_desc)} 'RU-модов': у {len(ru_ok)} RU-описание есть в кэше")
