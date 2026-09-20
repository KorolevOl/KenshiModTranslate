# -*- coding: utf-8 -*-
"""Тест извлечения строк из LLM-ответа (устойчиво к обрывам, markdown, лишнему).
Тестирует ТО ЖЕ выражение, что в translate_mods.py."""
import re, json

def extract(content):
    s = content.strip()
    m = re.match(r"^```[a-zA-Z+*-]*\n?(.*?)\n?\s*```$", s, re.DOTALL)
    if m:
        s = m.group(1).strip()
    s = re.sub(r"^\s*//.*$", "", s, flags=re.MULTILINE)
    arr = None
    m2 = re.search(r"\[.*\]", s, re.DOTALL)
    if m2:
        try:
            arr = json.loads(m2.group(0))
        except Exception:
            pass
    if arr is None and s.lstrip().startswith("["):
        body = s[s.index("[") + 1:]
        found = re.findall(r'"((?:[^"\\]|\\.)*)"', body)
        if found:
            arr = found
    return arr

cases = {
    "1 нормальный JSON": json.dumps(["Привет", "Пока"], ensure_ascii=False),
    "2 обрыв в конце (кавычка открыта)": '["Привет", "Пока", "три слова здесь", "об',
    "3 markdown-обёртка + обрыв": "```json\n[\"Привет\", \"Пока\", \"Три\"\n```",
    "4 пояснение перед массивом": "Вот переводы:\n\n[\"Один\", \"Два\", \"Три\"]",
    "5 экранированные кавычки": '["He said \\"hi\\"", "OK"]',
    "6 обрыв без закр(массив)": '["Слово одно", "Второе слово", "Третье',
}
fails = 0
for name, c in cases.items():
    r = extract(c)
    n = len(r) if r else 0
    print(f"[OK ] {name} -> {n} строк: {r[:4] if r is not None else None}")
    if r is None:
        print("     [FAIL] не распарсилось")
        fails += 1
print(f"\n{fails} FAIL из {len(cases)}")
