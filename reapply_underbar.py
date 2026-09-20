"""
reapply_all.py — пере-apply всем .mod, чьё имя содержит _.
Баг: DoApply использовал IndexOf('_'), а не LastIndexOf('_') —
если имя мода имеет _, то idPart режется на первый _ (внутри имени),
record не находит → перевод молча пропускается.
Фикс: LastIndexOf в Program.cs (закоммитить позже).
"""
import os, json, re, subprocess

WORKSHOP = r"E:\steamlibrary\steamapps\workshop\content\233860"
DOTNET   = r"H:\dotnet9\dotnet.exe"
CLI      = r"H:\KenshiModTranslate\bin\Release\net9.0-windows\kenshi-modtranslate.dll"
STATE    = r"H:\KenshiModTranslate\state"

fixed = failed = skipped_no_change = 0

for appid in sorted(os.listdir(WORKSHOP)):
    d = os.path.join(WORKSHOP, appid)
    if not os.path.isdir(d):
        continue
    # find .mod files with _ in name
    for f in os.listdir(d):
        if not f.endswith(".mod"):
            continue
        base = os.path.splitext(f)[0]
        if "_" not in base:
            continue
        # find backup file to get hash
        target_hash = None
        for f2 in os.listdir(d):
            m2 = re.match(r"^.+\.orig_([a-f0-9]+)\.backup$", f2)
            if m2:
                target_hash = m2.group(1)
                break
        if not target_hash:
            continue
        mapping = os.path.join(STATE, f"{target_hash}_mapping.json")
        if not os.path.exists(mapping):
            continue
        raw = json.load(open(mapping, encoding="utf-8"))
        if not raw or not any(x.get("ru") for x in raw):
            continue
        # run apply
        mod_path = os.path.join(d, f)
        out_path = mod_path + ".reapply"
        r = subprocess.run([DOTNET, CLI, "apply", mod_path, mapping, out_path],
                           capture_output=True, text=True, timeout=120)
        applied = 0
        m3 = re.search(r"applied:\s*(\d+)", r.stderr or "")
        if m3: applied = int(m3.group(1))
        old_cyr = sum(1 for c in open(mod_path, "rb").read().decode("utf-8","ignore")
                      if '\u0400' <= c <= '\u04ff')
        new_cyr = sum(1 for c in open(out_path, "rb").read().decode("utf-8","ignore")
                      if '\u0400' <= c <= '\u04ff')
        if new_cyr > old_cyr:
            os.replace(out_path, mod_path)
            fixed += 1
            print(f"  [FIXED {appid}] {f}  кириллица {old_cyr}→{new_cyr}  (applied {applied}/{len(raw)})")
        else:
            if os.path.exists(out_path):
                os.remove(out_path)
            skipped_no_change += 1
print(f"\nИтог: пере-apply {fixed} модов, без изменений {skipped_no_change}")
