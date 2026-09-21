# -*- coding: utf-8 -*-
"""Матрица: размер чанка (500/250) x reasoning (low/none) на СТРОКАХ RecruitPrisoners.
Для каждого: 2 попытки, меряем success + usage + reasoning_len."""
import json, time, urllib.request

strs = json.load(open('T:/recprisoners_full.json', 'r', encoding='utf-8'))
prompt = open('prompt.txt', 'r', encoding='utf-8').read()
d = json.load(open('dict.json', 'r', encoding='utf-8'))
sys_prompt = prompt.replace("{{DICT}}", json.dumps(d, ensure_ascii=False))
sys_prompt = sys_prompt.replace("{{COUNT}}", "N")

def call(chunk, effort, label):
    body = {
        "model": "qwen3.8:27b",
        "max_tokens": 200000,
        "reasoning_effort": effort,
        "temperature": 0.8,
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": "Переведи. Ответ: ТОЛЬКО JSON-массив строк, той же длины." + json.dumps(chunk, ensure_ascii=False)},
        ],
    }
    req = urllib.request.Request(
        "http://localhost:11234/v1/chat/completions",
        data=json.dumps(body).encode('utf-8'),
        headers={"Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=900) as r:
            resp = json.load(r)
    except Exception as e:
        print(f"  [{label}] HTTP {str(e)[:80]} ({time.time()-t0:.0f}s)", flush=True)
        return
    dt = time.time() - t0
    ch = resp["choices"][0]
    content = (ch["message"].get("content") or "").strip()
    reasoning = ch["message"].get("reasoning_content") or ch["message"].get("reasoning") or ""
    usage = resp.get("usage", {})
    n = len(content.splitlines()) if content else 0
    print(f"  [{label}] {dt:.0f}s fr={ch.get('finish_reason')} content_lines={n}/{len(chunk)} "
          f"reasoning={len(reasoning)}B usage={usage}", flush=True)

print("== Матрица: RecruitPrisoners (первые N строк) =", flush=True)
for n in (500, 250):
    for effort in ("low", "none"):
        label = f"{n}x{effort}"
        print(f"-- {n} строк, reasoning_effort={effort}", flush=True)
        for k in range(2):
            call(strs[:n], effort, f"{label}#{k+1}")
print("== КОНЕЦ мат...", flush=True)
