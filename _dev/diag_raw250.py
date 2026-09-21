import json, re, time, urllib.request
BASE='H:/KenshiModTranslate/'
d=json.load(open(BASE+'state/8e39195cb736_entries.json',encoding='utf-8'))
strs=[str(e['original']) for e in d[1000:1250]]
print("строки:",len(strs)," символы:",sum(len(s) for s in strs))
sysp=open(BASE+'prompt.txt',encoding='utf-8').read()
sysblock=sysp.split('[SYSTEM]')[1].split('[USER]')[0].strip().replace('{{DICT}}','')
user=("Переведи этот JSON-массив игровых строк на русский.\n"+
"Ответ - ТОЛЬКО переведенный JSON-массив (та же длина, %d элементов; порядок и заполнители сохранены):\n"%len(strs)+
json.dumps(strs,ensure_ascii=False))
body={"model":"qwen3.8:27b","max_tokens":200000,"reasoning_effort":"none","temperature":0.8,
"messages":[{"role":"system","content":sysblock},{"role":"user","content":user}]}
req=urllib.request.Request("http://localhost:11234/v1/chat/completions",
data=json.dumps(body,ensure_ascii=False).encode("utf-8"),
headers={"Content-Type":"application/json; charset=utf-8"},method="POST")
t0=time.time()
dct=json.loads(urllib.request.urlopen(req,timeout=600).read().decode("utf-8"))
dt=time.time()-t0
ch=dct["choices"][0]
content=(ch["message"].get("content") or "").strip()
print("время %.0fs  fr=%s  usage=%s"%(dt,ch.get('finish_reason'),dct.get('usage')))
print("длина контента символов:",len(content))
print("--- НАЧАЛО ---"); print(content[:450]); print("--- КОНЕЦ ---"); print(content[-250:])
cleaned=content
m=re.match(r"^```[a-zA-Z+*-]*\n?(.*?)\n?```$", cleaned, re.DOTALL)
if m: cleaned=m.group(1).strip()
aa=None
m2=re.search(r"\[.*\]", cleaned, re.DOTALL)
if m2:
    try:
        aa=json.loads(m2.group(0)); print("JSON распарсен: элементом",len(aa))
    except Exception as e:
        print("JSON не распарсился:",str(e)[:120])
if aa is None:
    lines=[l.strip() for l in content.splitlines() if l.strip()]
    print("строк в тексте:",len(lines))
    print("первые 6 строк:")
    for l in lines[:6]: print("   ",repr(l[:90]))
open('T:/raw_nr_250.txt','w',encoding='utf-8').write(content)
print("OK saved T:/raw_nr_250.txt")
