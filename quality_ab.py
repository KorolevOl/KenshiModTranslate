# -*- coding: utf-8 -*-
"""A/B low vs none на 16 репликах с юмором — сравним КАЧЕСТВО (нюансы, emote,
каламбуры), а не только стабильность."""
import json, time, urllib.request

strs = json.load(open('T:/dialogue_test.json','r',encoding='utf-8'))
# берём первые 16 уникальных
seen=set(); uniq=[]
for s in strs:
    if s not in seen: seen.add(s); uniq.append(s)
strs = uniq[:16]

prompt = open('prompt.txt','r',encoding='utf-8').read()
d = json.load(open('dict.json','r',encoding='utf-8'))
sys_prompt = prompt.replace("{{DICT}}", json.dumps(d, ensure_ascii=False))

def call(effort, label):
    body = {
        "model": "qwen3.8:27b",
        "max_tokens": 200000,
        "reasoning_effort": effort,
        "temperature": 0.8,
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": "Переведи. Ответ: ТОЛЬКО JSON-массив строк." + json.dumps(strs, ensure_ascii=False)},
        ],
    }
    req = urllib.request.Request("http://localhost:11234/v1/chat/completions",
        data=json.dumps(body).encode('utf-8'), headers={"Content-Type": "application/json"})
    t0=time.time()
    with urllib.request.urlopen(req, timeout=600) as r:
        resp = json.load(r)
    dt=time.time()-t0
    ch = resp["choices"][0]
    content = (ch["message"].get("content") or "").strip()
    usage = resp.get("usage", {})
    m = __import__('re').search(r"\[.*\]", content, __import__('re').DOTALL)
    if m: content = m.group(0)
    try: arr = json.loads(content)
    except Exception: arr = content.splitlines()
    print(f"--- [{label}] {dt:.0f}s usage={usage}")
    for i, (en, ru) in enumerate(zip(strs, arr)):
        print(f"  {i:2d} {en!r:55s} → {ru!r}")
    print()
    return arr

low1  = call("low",  "low#1")
time.sleep(3)
none1 = call("none", "none#1")
