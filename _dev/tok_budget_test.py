# -*- coding: utf-8 -*-
"""Диагностика 'empty content': меряем РЕАЛЬНЫЙ расход токенов (usage)
и наличие рассуждений в ответе. Один вызов на упавшем чанке, 3 повтора.
Печатает каждый ключ ответа — чтобы видеть, куда уходят токены."""
import json, time, urllib.request

with open('T:/test_350.json', 'r', encoding='utf-8') as f:
    strings = json.load(f)

prompt = open('prompt.txt', 'r', encoding='utf-8').read()
d = json.load(open('dict.json', 'r', encoding='utf-8'))
sys_prompt = prompt + "\n\nСловарь термина (строго следуй):\n" + json.dumps(d, ensure_ascii=False)
user = ("Переведи строки на русский. Ответ: ТОЛЬКО строки перевода, в том же порядке.\n\n"
        + "\n".join(f"{i+1}|{s}" for i, s in enumerate(strings)))

def call(max_tokens, extra=None, label=""):
    body = {
        "model": "qwen3.8:27b",
        "max_tokens": max_tokens,
        "reasoning_effort": "low",
        "temperature": 0.7,
        "stream": False,
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user},
        ],
    }
    if extra:
        body.update(extra)
    req = urllib.request.Request(
        "http://localhost:11234/v1/chat/completions",
        data=json.dumps(body).encode('utf-8'),
        headers={"Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            resp = json.load(r)
    except Exception as e:
        print(f"[{label}] HTTP-ошибка {str(e)[:120]} after {time.time()-t0:.0f}s")
        return
    dt = time.time() - t0
    ch = resp["choices"][0]
    msg = ch.get("message", {})
    content = (msg.get("content") or "").strip()
    reasoning = msg.get("reasoning_content") or msg.get("reasoning") or ""
    usage = resp.get("usage", {})
    nlines = content.count("\n") + 1 if content else 0
    print(f"--- [{label}] max_tokens={max_tokens} extra={extra or {}}")
    print(f"    {dt:.1f}s  finish_reason={ch.get('finish_reason')}")
    print(f"    content_lines={nlines}/350   reasoning_len={len(reasoning)}")
    print(f"    usage={json.dumps(usage)}")
    # ВСЕ ключи message, чтобы ничего не пропустить
    print(f"    message keys={list(msg.keys())}")
    if content:
        print(f"    первая: {content.splitlines()[0][:70]!r}")
    if reasoning:
        print(f"    reasoning[:120]={reasoning.strip()[:120]!r}")
    print()

print("== вызов 1/3: текущий конфиг (max_tokens=200000, reasoning=low) ==")
call(200000, label="cur")
print("== вызов 2/3: увеличенный ответ (max_tokens=600000) ==")
call(600000, label="bigger-answer")
print("== вызов 3/3: thinking выключен жёстко (/no_think в системном промпте) ==")
call(200000, extra={"reasoning_effort": "none"}, label="no-think")
