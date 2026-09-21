# -*- coding: utf-8 -*-
"""Воспроизвести 'эхо 353/416' на NewRecruits: первые 416 строк, effort=none.
Считаю НЕСТРОГОЕ en==ru и валидаторный echo. Смотрю, что реально не переведено."""
import json, re, time, urllib.request

# --- injected by move_to_dev: let us import core modules from parent ---
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
# --- end injected prologue ---

from validate_translation import classify_row

strs = json.load(open('state/8e39195cb736_entries.json', encoding='utf-8'))
strs = [e['original'] for e in strs][:416]

prompt = open('prompt.txt', 'r', encoding='utf-8').read()
d = json.load(open('dict.json', 'r', encoding='utf-8'))
sys_prompt = prompt.replace("{{DICT}}", json.dumps(d, ensure_ascii=False))
body = {"model": "qwen3.8:27b", "max_tokens": 200000, "reasoning_effort": "none",
        "temperature": 0.8,
        "messages": [{"role": "system", "content": sys_prompt},
                     {"role": "user", "content": "Переведи. Ответ: ТОЛЬКО JSON-массив строк." + json.dumps(strs, ensure_ascii=False)}]}
req = urllib.request.Request("http://localhost:11234/v1/chat/completions",
    data=json.dumps(body).encode('utf-8'), headers={"Content-Type": "application/json"})
t0 = time.time()
with urllib.request.urlopen(req, timeout=900) as r:
    resp = json.load(r)
dt = time.time() - t0
content = (resp["choices"][0]["message"].get("content") or "").strip()
m = re.search(r"\[.*\]", content, re.DOTALL)
if m: content = m.group(0)
try:
    arr = json.loads(content)
except Exception as e:
    arr = content.splitlines()
    print("JSON не распарсился → построчный:", len(arr))

strict = sum(1 for en, ru in zip(strs, arr) if str(en).strip() == str(ru).strip())
vals = [classify_row(en, ru) for en, ru in zip(strs, arr)]
from collections import Counter
c = Counter(vals)
print(f"{dt:.0f}s lines={len(arr)}/{len(strs)}")
print(f"строго en==ru: {strict}")
print(f"вердикт валидатора: {dict(c)}")
echo_idx = [i for i, v in enumerate(vals) if v == "echo"]
print(f"\n--- настоящие эхо ({len(echo_idx)}) ---")
for i in echo_idx[:30]:
    print(f"  [{i:3d}] {strs[i][:70]!r} → {str(arr[i])[:70]!r}")
