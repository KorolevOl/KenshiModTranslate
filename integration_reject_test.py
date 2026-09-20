"""Интеграционный тест веток отбраковки (без сети: llm_call подменяется)."""
import sys, os, io, contextlib
sys.path.insert(0, r"H:\KenshiModTranslate")
os.chdir(r"H:\KenshiModTranslate")
ctx = sys.argv

import translate_mods as t

t.log = lambda m: print("  LOG:", m)

CASES = {
    "empty_row": (["A long english sentence here", "Another full sentence now"],
                  ["", "Другое полностью предложение"],      # одна пустая -> hard
                  True),
    "all_echo":  (["First long sentence", "Second long sentence", "Third long sentence"],
                  ["First long sentence", "Second long sentence", "Third long sentence"],
                  True),                                        # >50% эхо -> hard
    "garbage":   (["Some english text"], {"not": "a list"}, True),
    "placeholder_lost": (["Value of %d points"], ["Баллы"], True),
    "ok":        (["Some english text", "Another phrase here"],
                  ["Некоторый английский текст", "Ещё одна фраза здесь"],
                  False),
}

fails = 0
for name, (strings, rows, expected_hard) in CASES.items():
    rep = t.validate_batch(strings, rows)
    ok = (rep["hard"] == expected_hard)
    if not ok:
        fails += 1
    print(f"[{'OK ' if ok else 'FAIL'}] {name:16} hard={rep['hard']} (want {expected_hard})  -> {rep['reason']}")

# audit_map: all-echo -> ABORT condition must trigger
entries = [{"i": 0, "original": "Sentence one here"}, {"i": 1, "original": "Sentence two here"}]
a = t.audit_map(entries, {str(e["i"]): e["original"] for e in entries})
abort = (a["filled"] == 0) or (a["filled"] == a["echo"])
print(f"[{'OK ' if abort else 'FAIL'}] all-echo audit -> ABORT={abort}")
if not abort:
    fails += 1

print()
print("FAILURES:", fails)
sys.exit(1 if fails else 0)
