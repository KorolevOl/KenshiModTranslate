# -*- coding: utf-8 -*-
"""Симуляция _fix_chunk: mock llm_call — первая попытка (350 строк) падают
«empty content», половинки сдают. Проверяю, что рекурсия доходит до конца
и все строки попали в done_map."""
import unittest.mock as mock
import translate_mods as TM

# создаём 350 фейковых энтри
entries = [{"i": i, "original": f"English line {i}" } for i in range(350)]
done_map = {}

# mock LLM: большой чанк (>=200 строк) падает с «empty content», маленькие сдают
def mock_llm_call(strings):
    if len(strings) >= 200:
        raise TM.Transient("empty content (finish_reason=stop) - model returned empty response")
    return [f"Русский перевод {i}" for i in range(len(strings))], False

with mock.patch.object(TM, "llm_call", side_effect=mock_llm_call):
    # вызываем translate_entries
    ctx = {}
    TM.CUR["mapfile"] = None
    TM.CUR["mapref"] = None
    TM.PROGRESS["progress"] = None
    TM.translate_entries(entries, done_map, "TEST_MOD", ctx)

succeeded = sum(1 for i in range(350) if str(i) in done_map and done_map[str(i)].strip())
print(f"Результат: {succeeded}/350 строк переведено")
assert succeeded == 350, f"ожидалось 350, получено {succeeded}"
print("✓ _fix_chunk: самозалечивание через дробление работает")
print(f"  пример перевода: {done_map['0']!r} (для «English line 0»)")
print(f"  пример перевода: {done_map['175']!r} (для «English line 175»)")
