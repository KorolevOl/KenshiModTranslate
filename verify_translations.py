r"""Проверка и (опционально) починка переводов, уже в кеше state/.

ПРОСМОТР (read-only, 0 запросов к LLM):
  Ходит по state/*_entries.json + state/*_mapping.json и сравнивает
  оригинал с переводом построчно через ЕДИНЫЙ классификатор
  validate_translation.classify_row:
    empty     перевод пуст, а в оригинале есть текст        -> чинить
    echo      перевод побуквенно == оригиналу               -> чинить
    latin     перевод без кириллицы (>=2 слова)             -> чинить
    ph_lost   потерян плейсхолдер (%s, {0}, ...)            -> чинить
    ok        корректный перевод                            -> не трогать
    already_ru  оригинал и так русский                     -> не трогать
    identifier  имя ассета/кода (T34, wood_x_pole)         -> не трогать
  Вывод: сводная таблица + список модов с проблемами.

ПОЧИНКА (--fix, пере-перевод ТОЛЬКО битых строк через LLM):
  Для каждого мода с проблемами берём ровно ИХ битые строки и
  пере-запрашиваем у LLM, переиспользуя проверенный пайплайн
  translate_mods.translate_one (extract/resume/chunk-split/retry/аудит/apply).
  Уже хорошие строки НЕ трогаются — не тратим токены и не перемешиваем
  удачные переводы. В конце — повторная read-only проверка «после».

ЧИСТКА ИСКЛЮЧЕНИЙ (сама начинается в --fix, или --purge отдельно):
  Моде, кэши которых попадают под регулярки из exclude.txt (например
  добавлена новая регулярка * после начала перевода), --fix не чинит,
  а **удаляет**:
    1) кеш: state/<hash>_entries.json, <hash>_mapping.json(+.prev);
    2) нашу копию из kenshi\mods\<mод>\ — только если она наша
       (подтверждается маркером .orig_<hash>.backup, который переводчик
       создаёт перед apply); чужие папки (Vortex, ручные) не трогаются:
       удаляются .mod + наш .backup, каталог — если остался пустой.
  --purge — только очистка исключённых, без LLM-фикса остального.

Коды выхода: 0 = чисто, 1 = есть проблемы, 2 = кэш пуст, 3 = были ошибки.

Запуск:
  verify_translations.py                 - просмотр всех модов в кеше
  verify_translations.py "Pocket"        - только совпадающие по имени/id
  verify_translations.py --details       - показать проблемные строки
  verify_translations.py --fix           - ПОЧИНИТЬ битые строки (LLM)
                                          + сначала чистит кэш исключённых мода
  verify_translations.py --purge         - только чистка: кэш + наша копия в mods\\
                                          мода, попадающих под exclude.txt (0 LLM)
  verify_translations.py "Factions" --fix- починить конкретный мод
  verify_translations.py --help          - справка
"""
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(HERE, "config.json"), encoding="utf-8"))
import kmt_paths
_resolve = kmt_paths.resolve
P = CFG["paths"]
WORKSHOP = _resolve(P["workshop"])
GAME = _resolve(P["game"])
STATE = _resolve(P["state"])
MODS_DIR = (P.get("mods_dir") and _resolve(P["mods_dir"])) or os.path.join(GAME, "mods")

from validate_translation import (
    words, has_cyrillic, norm, classify_row, already_russian, is_identifier,
)

from validate_translation import BAD_FIX_LEVELS  # единый источник правды

FIX_BAD_LEVELS = set(BAD_FIX_LEVELS)

# ---------- name resolution: content-hash(mod original) -> display name ----------
def _md5(path):
    try:
        return hashlib.md5(open(path, "rb").read()).hexdigest()[:12]
    except Exception:
        return None

def _wbname(d):
    for f in os.listdir(d):
        if f.startswith("_") and f.endswith(".info"):
            try:
                txt = open(os.path.join(d, f), encoding="utf-8", errors="replace").read()
                m = re.search(r"<name>(.*?)</name>", txt, re.DOTALL)
                if m:
                    return m.group(1).strip()
            except Exception:
                pass
    for f in os.listdir(d):
        if f.lower().endswith(".mod"):
            return f[:-4]
    return os.path.basename(d)

def build_name_map():
    """hash(EN) -> (name, source).
    Source of truth: our .orig_<hash>.backup files (workshop in-place или mods\\).
    Fallback: md5 всех .mod в workshop и mods\\ (для ещё не переведённых)."""
    m = {}
    def scan(d, name, src):
        if not os.path.isdir(d):
            return
        for f in os.listdir(d):
            if ".orig_" in f and f.endswith(".backup"):
                h = f.split(".orig_")[1].split(".backup")[0]
                if h:
                    m.setdefault(h, (name, src))
    if os.path.isdir(WORKSHOP):
        for d in sorted(os.listdir(WORKSHOP)):
            wp = os.path.join(WORKSHOP, d)
            if not (d.isdigit() and os.path.isdir(wp)):
                continue
            scan(wp, _wbname(wp), "workshop")
            # md5 .mod (для непереведённых)
            for f in os.listdir(wp):
                full = os.path.join(wp, f)
                if f.lower().endswith(".mod") and os.path.isfile(full):
                    h = _md5(full)
                    if h:
                        m.setdefault(h, (_wbname(wp), "workshop"))
    if os.path.isdir(MODS_DIR):
        for d in sorted(os.listdir(MODS_DIR)):
            dp = os.path.join(MODS_DIR, d)
            if not os.path.isdir(dp):
                continue
            scan(dp, d, "mods")
            for f in os.listdir(dp):
                full = os.path.join(dp, f)
                if f.lower().endswith(".mod") and os.path.isfile(full):
                    h = _md5(full)
                    if h:
                        m.setdefault(h, (d, "mods"))
    return m

# ---------- audit ----------
def audit_one(entries, mapping):
    """Count rows by classify_row level; collect bad_ids (to fix) and problems."""
    counts = {"ok": 0, "already_ru": 0, "identifier": 0,
              "empty": 0, "echo": 0, "latin": 0, "ph_lost": 0, "mixed": 0}
    bad_ids = []
    problems = []  # (level, i, original, ru)
    for e in entries:
        i = str(e["i"])
        ru = mapping.get(i, None)
        en = e.get("original") or ""
        lvl = classify_row(en, ru)
        counts[lvl] = counts.get(lvl, 0) + 1
        if lvl in FIX_BAD_LEVELS:
            bad_ids.append(i)
            problems.append((lvl, i, en, "" if ru is None else ru))
    return {
        "total": len(entries),
        "done": counts["ok"] + counts["already_ru"] + counts["identifier"],
        "counts": counts, "bad_ids": bad_ids, "problems": problems,
    }

def load_state(h, state):
    epath = os.path.join(state, h + "_entries.json")
    mpath = os.path.join(state, h + "_mapping.json")
    entries = None
    if os.path.isfile(epath):
        entries = json.load(open(epath, encoding="utf-8"))
    mapping = {}
    if os.path.isfile(mpath):
        mapping = {str(x["i"]): x.get("ru") for x in json.load(open(mpath, encoding="utf-8"))}
    return entries, mapping, os.path.isfile(epath), os.path.isfile(mpath)

def game_has_translation(name):
    r"""True если игра увидит РЯ (в place):
    - в mods\<name>\ есть .mod с кириллицей (ручной/копия), ЛИБО
    - в workshop папке мода лежит наш .orig_<h>.backup (перевод in-place).
    Для имён с несовпадением workshop-title vs folder-name — ищем backup по всем папкам."""
    d = os.path.join(MODS_DIR, name)
    if os.path.isdir(d):
        for f in os.listdir(d):
            if f.lower().endswith(".mod"):
                try:
                    t = open(os.path.join(d, f), encoding="utf-8", errors="replace").read()
                    if any("\u0400" <= c <= "\u04ff" for c in t):
                        return True
                except Exception:
                    pass
    # in-place в workshop: наш бэкап рядом с каким-то .mod = перевод стоит
    if os.path.isdir(WORKSHOP):
        for dd in os.listdir(WORKSHOP):
            dp = os.path.join(WORKSHOP, dd)
            if dd.isdigit() and os.path.isdir(dp):
                if any(".orig_" in f and f.endswith(".backup") for f in os.listdir(dp)):
                    if _wbname(dp).lower() == name.lower():
                        return True
    return False

def audit_mod(h, name_map, state):
    name, src = name_map.get(h, (h, "?"))
    entries, mapping, have_e, have_m = load_state(h, state)
    r = {"name": name, "h": h, "have_map": have_m, "in_game": game_has_translation(name)}
    if entries is None:
        r.update({"total": 0, "done": 0, "counts": {}, "bad_ids": [], "problems": []})
        return r
    if not entries:
        # 2026-09-19: кеш есть, но 0 строк = в .mod НЕТ переводимого текста
        # (чистые обёртки: контент в .dll, напр. Dust/NutritiousFood = 46-51 B
        # header-only). Это НЕ «перевод не завершён» — переводить нечего.
        # Раньше is_bad() помечал их 'no mapping - needs full translation'
        # и фиксер зря бил LLM. Чистым считаются (total=0 → нет проблем).
        r.update({"total": 0, "done": 0, "counts": {}, "bad_ids": [], "problems": [],
                  "trivial_empty": True, "have_map": True})
        return r
    a = audit_one(entries, mapping)
    r.update(a)
    return r

def collect(state, name_map, names_q):
    hs = [fn[:12] for fn in sorted(os.listdir(state)) if fn.endswith("_entries.json")]
    out = []
    for h in hs:
        name, src = name_map.get(h, (h, "?"))
        if names_q:
            if not any(q.lower() in name.lower() or q == h
                       or q.lower() in name.lower().replace(" ", "") for q in names_q):
                continue
        out.append(audit_mod(h, name_map, state))
    return out

def is_bad(r):
    if not r.get("have_map"):
        return True
    if not r["in_game"]:
        return True
    c = r["counts"]
    return any(c.get(k, 0) > 0 for k in FIX_BAD_LEVELS)

def why(r):
    why = []
    if not r.get("have_map"):
        return ["no mapping - needs full translation"]
    if not r["in_game"]:
        why.append(".mod не записан в mods\\")
    c = r.get("counts", {})
    if c.get("empty"):
        why.append(f"{c['empty']} пустых")
    if c.get("echo"):
        why.append(f"{c['echo']} эхо")
    if c.get("latin"):
        why.append(f"{c['latin']} без кириллицы")
    if c.get("ph_lost"):
        why.append(f"{c['ph_lost']} потеряны плейсхолдеры")
    if c.get("mixed"):
        why.append(f"{c['mixed']} опечатки/чужие буквы")
    return why

# ---------- purge of excluded mods (cache + our copy in mods\) ----------
def _is_excluded_name(name):
    """True если имя мода попадает под регулярки exclude.txt (единый источник — translate_mods)."""
    if not name:
        return False
    import translate_mods as _TM   # лениво: не таскать модуль при простом просмотре
    try:
        return bool(_TM.is_excluded(name, name + ".mod"))
    except Exception:
        return False

def _our_modfolder(h, name):
    r"""Find the mods\<name> folder WE translated for hash h (by our .orig_<h>.backup marker).
    Returns (folder_path, is_ours). is_ours=False -> external (Vortex/manual) -> never touch."""
    candidates = []
    if name:
        p = os.path.join(MODS_DIR, name)
        if os.path.isdir(p):
            candidates.append(p)
    # fallback: any folder holding a .orig_<h>.backup (name drift between workshop title and folder)
    if not candidates and os.path.isdir(MODS_DIR):
        for d in os.listdir(MODS_DIR):
            dp = os.path.join(MODS_DIR, d)
            if os.path.isdir(dp):
                for f in os.listdir(dp):
                    if f.endswith(f".orig_{h}.backup"):
                        candidates.append(dp)
                        break
    for p in candidates:
        for f in os.listdir(p):
            if f.endswith(f".orig_{h}.backup"):
                return p, True
    return (candidates[0] if candidates else None), False

def purge_excluded(audits, state, dry_run=False):
    """Моде, чей кэш попадает под exclude.txt: вернуть в исходное (EN) состояние.
    Действия (безопасные, по нашей метке .orig_<h>.backup):
      1) если рядом с workshop-файлом лежит наш .orig_<h>.backup -> RESTORE EN
         (перевод снимается, оригинал возвращается на место, бэкап удаляется);
      2) если копия наша в mods\\ -> удалить наш .mod + бэкап (каталог - если опустел);
      3) кэш state\\<h>_*.json - удалить.
    Чужие папки (без нашего .orig_<h>.backup) НЕ трогаются."""
    import translate_mods as TM_BASE   # is_excluded (единый источник правил)
    actions = []

    def _report(kind, path, done=True):
        actions.append((kind, path, dry_run))
        if done and not dry_run:
            pass
        tag = " (dry-run)" if dry_run else ""
        print(f"    {kind}: {path}{tag}")

    for r in audits:
        name, h = r.get("name"), r.get("h")
        if not name or not h or h == name:
            continue
        if not TM_BASE.is_excluded(name, name + ".mod"):
            continue
        print(f"  [purge] {name} ({h}):")
        # --- 3) cache ---
        removed_cache = False
        for fn in sorted(os.listdir(state)):
            if fn.startswith(h):
                p = os.path.join(state, fn)
                if not dry_run:
                    if os.path.isfile(p):
                        os.remove(p); removed_cache = True
                actions.append(("кеш удалён", p, False))
        if not removed_cache and dry_run:
            actions.append(("кеш (dry-run)", f"{state}\\<h>*", True))
        # --- 1) restore EN in workshop (in-place) ---
        handled_spot = False
        if os.path.isdir(WORKSHOP):
            for dd in os.listdir(WORKSHOP):
                dp = os.path.join(WORKSHOP, dd)
                if not (dd.isdigit() and os.path.isdir(dp)):
                    continue
                wname = _wbname(dp)
                if wname.lower() != name.lower():
                    continue
                # our backup рядом -> EN оригинал
                for f in os.listdir(dp):
                    if f.endswith(f".orig_{h}.backup"):
                        modname = f[:-(len(".orig_" + h + ".backup"))]
                        modf = os.path.join(dp, modname + ".mod")
                        bakf = os.path.join(dp, f)
                        if dry_run:
                            print(f"    (dry-run) EN восстановится: {modf}")
                        elif os.path.isfile(bakf) and os.path.isfile(modf):
                            import shutil
                            shutil.copy2(bakf, modf)
                            os.remove(bakf)
                            print(f"    EN восстановлен: {modf}")
                        actions.append(("EN восстановлен (workshop)", modf, True))
                        handled_spot = True
                        break
        # --- 2) mod dir copy (legacy) ---
        folder, ours = _our_modfolder(h, name)
        if folder and ours:
            for f in sorted(os.listdir(folder)):
                fp = os.path.join(folder, f)
                is_our_mod = f.lower().endswith(".mod") and not f.startswith("~")
                is_our_bak = f.endswith(f".orig_{h}.backup")
                if (is_our_mod or is_our_bak) and os.path.isfile(fp):
                    if not dry_run:
                        os.remove(fp)
                    actions.append(("удалено из mods\\", fp, True))
            if not dry_run and os.path.isdir(folder) and not os.listdir(folder):
                os.rmdir(folder)
                actions.append(("пустой каталог удалён", folder, True))
        elif folder and not ours:
            actions.append(("НЕ ТРОНУТО (чужая папка)", folder, True))
            print(f"    чужая папка - НЕ трогать: {folder}")
        if not handled_spot:
            print("    в workshop перевода (бэкапа) не найдено — было только в кеше")
    return actions

# ---------- report ----------
def print_table(audits, details=False):
    header = f"{'MOD':42}{'total':>7}{'done':>6}{'echo':>6}{'latin':>7}{'ph':>4}{'empty':>7}{'mix':>5}  game"
    print(header)
    print("-" * len(header))
    for r in audits:
        c = r.get("counts", {})
        if not r.get("have_map"):
            print(f" *{r['name'][:41]:41}{'?':>7}  (mapping.json отсутствует - перевод не завершён)")
            continue
        in_game = r["in_game"]
        status = "в игре" if in_game else "НЕ в mods\\"
        bad = is_bad(r)
        mark = " " if (not bad and in_game) else "*"
        print(f"{mark}{r['name'][:41]:41}{r.get('total',0):>7}{r.get('done',0):>6}"
              f"{c.get('echo',0):>6}{c.get('latin',0):>7}{c.get('ph_lost',0):>4}"
              f"{c.get('empty',0):>7}{c.get('mixed',0):>7}  {status}")
        if details:
            for lvl, i, en, ru in r.get("problems", [])[:15]:
                print(f"     [{lvl}] (#{i}) {en[:70]!r}")
                print(f"          => {ru[:70]!r}")
            if len(r.get("problems", [])) > 15:
                print(f"     ... ещё {len(r['problems']) - 15} проблемных строк")

# ---------- fix ----------
def run_fix(bad_list, state, name_map):
    """Re-translate only the bad rows via the proven translate_mods pipeline."""
    import translate_mods as TM   # battle-tested: extract/resume/retry/audit/apply
    from progress import Progress

    all_mods = TM.workshop_mods() + getattr(TM, "game_mods", lambda: [])()
    ctx = {"nmods_done": 0, "total_mods": len(bad_list), "t_llm": 0.0}
    results = []
    with Progress(len(bad_list)) as PR:
        TM.PROGRESS["progress"] = PR
        for idx, r in enumerate(bad_list, 1):
            name = r["name"]
            m = TM.resolve_mod(name, all_mods)
            if not m:
                PR.log(f"[fix] НЕ НАЙДЕН в workshop: {name!r} — пропускаю")
                PR.finish_mod()
                results.append((name, "skip", "не найден в workshop"))
                continue
            bad_ids = r.get("bad_ids") or []
            note = (f"пере-переведу {len(bad_ids)} битых строк"
                    if bad_ids else "apply-only / все строки (нет кеша)")
            PR.log(f"\n[fix {idx}/{len(bad_list)}] {name}: {note}")
            try:
                ok = TM.translate_one(m, idx, len(bad_list), ctx, drop_ids=bad_ids)
                results.append((name, "ok" if ok else "fail",
                                "" if ok else "translate_one вернул False"))
            except Exception as ex:
                PR.log(f"[fix][ERROR] {name}: {ex}")
                results.append((name, "error", str(ex)))
            PR.finish_mod()
        PR.log(f"\n[fix] LLM-время на исправления: {ctx.get('t_llm',0):.0f}s")
    TM.PROGRESS["progress"] = None
    return results

def main(argv):
    if any(a in ("-h", "--help") for a in argv):
        print(__doc__.strip())
        return 0
    fix = "--fix" in argv
    purge_only = "--purge" in argv
    details = "--details" in argv
    names_q = [a for a in argv if a not in ("--fix", "--details", "--purge")]

    state = STATE if os.path.isabs(STATE) else os.path.join(HERE, STATE)
    if not os.path.isdir(state):
        print(f"КЭШ ПУСТ: каталог state не найден: {state}")
        return 2
    name_map = build_name_map()
    audits = collect(state, name_map, names_q)
    if not audits:
        print("КЭШ ПУСТ: ни одного *_entries.json в state (или имена не совпали).")
        if names_q:
            print("Совпавших: 0. Список: " + ", ".join(names_q))
        return 2

    # ---- purge: кэши, попавшие под exclude.txt, не чиним — удаляем (кеш + наша копия в mods\)
    excluded = [r for r in audits
                if r.get("h") and not (r.get("h") in ("?",)) and _is_excluded_name(r.get("name"))]
    if excluded and not purge_only:
        excluded_names = ", ".join(r["name"] for r in excluded)
        print(f"[exclude] {len(excluded)} мод(ов) подпадают под exclude.txt и НЕ чинятся: {excluded_names}")
    if purge_only or (fix and excluded):
        print("\n=== ЧИСТКА ИСКЛЮЧЁННЫХ (кеш + EN-восстановление в workshop / удаление из mods\\) ===")
        actions = purge_excluded(audits, state, dry_run=False)
        if purge_only:
            print("\n=== ФИНИШ --purge: LLM не вызывалась ===")
            return 0
        audits = [r for r in audits if r not in excluded]
        excluded_names = ", ".join(r["name"] for r in excluded)
        print(f"  -> из списка фикса исключено: {excluded_names}")
        print()

    bad = [r for r in audits if is_bad(r)]
    print(f"Кэш: {len(audits)} мод(ов)  state: {state}")
    print(f"Проблем: {len(bad)}  |  чисто: {len(audits)-len(bad)}")
    if fix or purge_only:
        print("РЕЖИМ: --fix (пере-переведу только битые строки через LLM)")
    print()
    print_table(audits, details)
    print()

    if not bad:
        print("=== ПРОВЕРКА ПРОЙДЕНА: битых/непереведённых строк нет ===")
        return 0

    print(f"=== НАЙДЕНЫ ПРОБЛЕМЫ в {len(bad)} мод(ах): ===")
    for r in bad:
        print(f"  * {r['name']}  ({', '.join(why(r))})")

    if not fix:
        print()
        print("Починить битые строки (пере-перевод только их, LLM):")
        print("  verify_translations.bat --fix")
        print("Только конкретный:")
        print('  verify_translations.bat --fix "' + bad[0]["name"] + '"')
        return 1

    # ---- FIX ----
    print("\n=== ПОЧИНКА (LLM, только битые строки) ===")
    fix_bad = [r for r in bad]
    results = run_fix(fix_bad, state, name_map)
    print()
    ok = sum(1 for _, s, _ in results if s == "ok")
    print(f"=== ФИНИШ fix: ok={ok}  не-ок={len(results)-ok}  из {len(results)} ===")
    for name, status, note in results:
        mark = {"ok": "  [OK]", "fail": "  [FAIL]", "error": "  [ERR]", "skip": "  [SKIP]"}
        print(f"{mark.get(status,'')} {name}" + (f"  — {note}" if note else ""))

    # ---- re-audit (read-only) to show improvement ----
    print("\n=== ПРОВЕРКА ПОСЛЕ ФИКСА ===")
    audits2 = collect(state, name_map, names_q)
    still = [r for r in audits2 if is_bad(r)]
    print(f"  осталось с проблемами: {len(still)} (было {len(bad)})")
    for r in still:
        print(f"  * {r['name']}  ({', '.join(why(r))})")

    codes = [s for _, s, _ in results]
    if "error" in codes or "fail" in codes:
        return 3
    return 0 if not still else 1

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
