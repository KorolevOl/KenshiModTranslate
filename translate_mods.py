"""Kenshi mod RU-translator: workshop/mods -> extract -> LLM -> .mod (RU).

Config: config.json (same dir). CLI:
  translate_mods.py [MOD ...]
  translate_mods.py --list-file mods.txt
  translate_mods.py            (interactive: offer 'translate ALL N mods')
  translate_mods.py --force MOD      re-translate even if cached
  translate_mods.py --include-excluded MOD   override exclude rules for this mod

MOD = Workshop id (digits), mod name / partial name, or path to .mod / its folder.
mods.txt: one MOD per line, '#' = comment.
Progress: TWO tqdm bars - 'ALL' (selected mods) + 'NOW' (strings in current mod).
Ctrl+C safe: progress saved after every chunk, rerun the same command to resume.

Thinking (reasoning) control — two independent levers:
  • PRIMARY: top-level `reasoning_effort` (config: translate.reasoning_effort,
    default "low"). This is the same mechanism Hermes Agent uses for OpenAI-
    compatible Kimi / TokenHub / LM Studio providers
    (hermes-agent/agent/transports/chat_completions.py:409). Confirmed by A/B
    test on qwen3.8:27b via ollama.weldbook.ru: ~45% fewer completion tokens,
    ~35% faster, all arrays intact at "low". Value "none" is faster still but
    sometimes lazy (skips short strings) — prefer "low" for translation.
  • SECONDARY: `chat_template_kwargs.enable_thinking` (config:
    translate.enable_thinking). Qwen-template flag; ignored by qwen3.8:27b
    but harmless and useful if the model is ever switched to vanilla qwen3.
"""
import json, os, re, shutil, sys, time, urllib.request
import subprocess
from validate_translation import validate_batch, audit_map, check_row, BAD_FIX_LEVELS, classify_row
import prefilter

def _needs_translation(en):
    """Единый источник правды «нужна ли LLM-перевода эта строка, когда перевода нет».

    2026-09-19 (корень «находит N — не чинит»): раньше фиксер/переводчик
    спрашивали LLM о ВСЕЙ строке даже когда по классификации она НЕ требует
    перевода (onomatopoeia 4688 «no,no,no...» → 'ok'; entry-ID 4922/4923 →
    'identifier'; уже-русский текст → 'already_ru'). LLM захлёбывается на
    squeal-строке и роняет ВЕСЬ чанк (len mismatch), унося с собой соседние
    РЕАЛЬНО битые строки. Теперь: строка входит в «нужно перевести» только
    если classify_row(en, None) ∈ BAD_FIX_LEVELS (empty/echo/latin/ph_lost/mixed).

    2026-09-20: КРИКИ (onomatopoeia) снова идём LLM (было: skip RU=EN).
    Причина: classify_row теперь принимает ЭХО крика как 'ok' (эхо = ЛЛМ
    «не стала» переводить звук — это правомерно, фиксер больше не чинит).
    Значит и risk «LLM роняет чанк на squeal» больше не бьёт — даже если
    LLM ответит эхом, это 'ok'. А если LLM перевела крик — даже лучше
    («Aaargh!» → «Ааааа!», 6/6 в live-тесте 2026-09-20).
    """
    if not isinstance(en, str) or not en.strip():
        return False
    from validate_translation import is_onomatopoeia
    if is_onomatopoeia(en):
        return True  # крик → спрашиваем LLM; эхо = ok (2026-09-20)
    lvl = classify_row(en, None)
    return lvl in BAD_FIX_LEVELS

HERE = os.path.dirname(os.path.abspath(__file__))

# Единый резолвер путей: относительные → к папке проекта, не к CWD.
# kmt_paths.py — общий хелпер, чтобы все скрипты (translate, verify, rebuild, search)
# согласованным образом резолвили пути из config.json.
import kmt_paths
_resolve = kmt_paths.resolve

CFG = json.load(open(os.path.join(HERE, "config.json"), encoding="utf-8"))
P, L, T = CFG["paths"], CFG["llm"], CFG["translate"]
GAME     = _resolve(P["game"])                # обычно абсолютный (E:)
WORKSHOP = _resolve(P["workshop"])            # обычно абсолютный (E:)
STATE    = _resolve(P["state"])               # 'state' → <HERE>/state
MODS_DIR = (P.get("mods_dir") and _resolve(P["mods_dir"])) or os.path.join(GAME, "mods")
DOTTNET  = _resolve(P["dotnet"])              # 'dotnet' или '../dotnet9/dotnet.exe'
CLI_DOTS = _resolve(P["modtranslate_cli"])    # 'bin/Release/...dll'

# ---------------- dynamic RU-LOCALES HINTS (po_files.json) ----------------
import po_hints
_PO_LOCALES_DIR = P.get("locales_dir") or os.path.join(GAME, "locale", "ru_RU")
_PO_HINTS_MAX = int(T.get("po_hints_max", 30))
_PO_HINTS_ENABLED = bool(T.get("po_hints", True))
po_hints.configure([
    os.path.join(_PO_LOCALES_DIR, "gamedata.po"),
    os.path.join(_PO_LOCALES_DIR, "LC_MESSAGES", "main.po"),
])
BATCH      = int(T.get("max_batch_lines", 500))
MIN_CHUNK  = max(1, int(T.get("min_chunk", 4)))
MAX_TOKENS = int(T["max_tokens"])
# --- Динамический батч по токен-бюджету контекста (2026-09-19) ---
# Окно провайдера (вход+выход) и потолок строк в одном запросе. Чанк собирается
# до токен-бюджета: короткие строки дают много строк (до потолка), длинные —
# токены ужимают число строк, чтобы не упереться в лимит контекста/вывода.
CONTEXT_WIN   = int(T.get("context_window", 200000))   # токенов (вход+выход)
MAX_BATCH_LN  = int(T.get("max_batch_lines", 500))     # потолок строк в чанке
CHARS_PER_TOK = 1.8   # консервативно: 1 токен ≈ 1.8 символа (микс RU/EN)
MAX_OUT_TOK   = int(T.get("max_output_tokens", 100000)) # запас под RU-вывод
HTTP_TO    = int(L.get("http_timeout_s", 240))
RETRIES    = int(T.get("http_retries", 3))
FORCE      = bool(T.get("force_retranslate", False)) or "--force" in sys.argv
NO_CACHE   = os.environ.get("KENSHI_NO_CACHE") == "1"
NO_LLM     = bool(T.get("no_llm", False)) or "--no-llm" in sys.argv  # 2026-09-21: только CSV, без LLM

# Thinking (reasoning) off — the same mechanism as Hermes Agent (extra_body →
# chat_template_kwargs). Token-neutral: model spends no budget on reasoning,
# all goes into `content`. `false` is ignored harmlessly by non-thinking models.
# Disable this if you ever want to switch to a model where thinking helps.
THINKING_OFF = bool(T.get("enable_thinking", False) is False)

# ---- Prompt source file (RU, separated from code) ----
PROMPT_FILE = T.get("prompt_file", "prompt.txt")
if not os.path.isabs(PROMPT_FILE):
    PROMPT_FILE = os.path.join(HERE, PROMPT_FILE)
def load_prompt():
    # Parse the two-section prompt file into (system, user_template).
    txt = open(PROMPT_FILE, encoding="utf-8").read()
    # Split on the [USER] marker; everything before it = system.
    # Find the line that starts the user section exactly.
    user_marker = "\n[USER]\n"
    idx = txt.find(user_marker)
    if idx < 0:
        raise RuntimeError(f"prompt file missing [USER] section: {PROMPT_FILE}")
    system = txt[:idx].replace("[SYSTEM]", "").strip()
    user   = txt[idx + len(user_marker):].strip()
    # Strip lines starting with '#' (comment lines), but keep placeholder lines.
    def _strip_comments(s):
        out = []
        for line in s.splitlines():
            if line.startswith("#"):
                continue
            out.append(line)
        return "\n".join(out)
    return _strip_comments(system), _strip_comments(user)

SYS_PROMPT, USER_PROMPT_TMPL = load_prompt()

# ---- Dictionary (UI terms etc.) ----
DICT_PATH  = T.get("dict", "dict.json")
if not os.path.isabs(DICT_PATH):
    DICT_PATH = os.path.join(HERE, DICT_PATH)
DICT = {"exact": {}, "words": {}}
if os.path.isfile(DICT_PATH):
    d = json.load(open(DICT_PATH, encoding="utf-8-sig"))
    DICT["exact"] = {k.lower().strip(): v for k, v in (d.get("exact") or {}).items()}
    DICT["words"] = {k.lower().strip(): v for k, v in (d.get("words") or {}).items()}

# ---- Pre-LLM filter (СЛОЙ 1 regex + СЛОЙ 2 reuse) ----
# СЛОЙ 2: пул готовых EN->RU переводов — dict.json exact (канон) > .po игры >
# кеш ранее переведённых модев (state\). Строится один раз при старте.
# Отключить: config.json → translate "prefilter": false (обойдём оба слоя).
PRE_FILTER_ENABLED = bool(T.get("prefilter", True))
_PRE_PO_PATHS = [
    os.path.join(_PO_LOCALES_DIR, "gamedata.po"),
    os.path.join(_PO_LOCALES_DIR, "LC_MESSAGES", "main.po"),
]
if PRE_FILTER_ENABLED:
    prefilter.configure(DICT_PATH, _PRE_PO_PATHS, STATE)


# ---------- exclusion patterns ----------
EXCL_PATH = T.get("exclude_file", "exclude.txt")
if not os.path.isabs(EXCL_PATH):
    EXCL_PATH = os.path.join(HERE, EXCL_PATH)
EXCLUDE_RES = []
if os.path.isfile(EXCL_PATH):
    for ln in open(EXCL_PATH, encoding="utf-8-sig", errors="replace"):
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        try:
            EXCLUDE_RES.append(re.compile(ln, re.IGNORECASE))
        except re.error as ex:
            print(f"[warn] bad exclude regex skipped: {ln!r} ({ex})", file=sys.stderr)

def is_excluded(name, modfile=None):
    """True if the mod name (or .mod filename) matches any exclusion pattern."""
    texts = [name or ""]
    if modfile:
        texts.append(os.path.basename(modfile))
        texts.append(os.path.basename(modfile)[:-4])
    # variant with common separators normalized to spaces so \b works on "RecruitPrisoners_RUS"
    for t in list(texts):
        texts.append(re.sub(r"[_\-().]+", " ", t))
    for rx in EXCLUDE_RES:
        for t in texts:
            if t and rx.search(t):
                return True
    return False

LLM_BASE   = L["base_url"]
LLM_MODEL  = L["model"]
LLM_KEY    = L.get("api_key")
INCLUDE_EXCLUDED = os.environ.get("KENSHI_INCLUDE_EXCLUDED") == "1"

os.makedirs(STATE, exist_ok=True)
CUR = {"mapfile": None, "mapref": None}

# ---------------- console (tqdm-based) + log file ----------------
from progress import Progress

# --- log file: logs/translate_YYYY-MM-DD_HH-MM.log, capped at LOG_MAX_LINES ---
import datetime as _dt
LOG_DIR = os.path.join(HERE, T.get("log_dir", "logs"))
LOG_MAX_LINES = int(T.get("log_max_lines", 500))
os.makedirs(LOG_DIR, exist_ok=True)
LOG_PATH = os.path.join(
    LOG_DIR,
    "translate_" + _dt.datetime.now().strftime("%Y-%m-%d_%H-%M") + ".log",
)

def _log_trim(path):
    """Keep only the last LOG_MAX_LINES lines; drop the oldest beyond cap."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except (OSError, FileNotFoundError):
        return
    if len(lines) > LOG_MAX_LINES:
        keep = lines[-LOG_MAX_LINES:]
        with open(path, "w", encoding="utf-8") as f:
            f.write("…(старые строки обрезаны: сохранены последние %d)…\n" % LOG_MAX_LINES)
            f.writelines(keep)

def _log_file(msg):
    ts = _dt.datetime.now().strftime("%H:%M:%S")
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {msg}\n")
    _log_trim(LOG_PATH)
def log(msg):
    # console + file
    s = "" if msg is None else str(msg).strip("\n")
    _log_file(s) if s.strip() else None
    if PROGRESS.get("progress") is not None:
        PROGRESS["progress"].log(msg)
    else:
        tqdm_print(msg)
def tqdm_print(msg):
    tqdm_write(msg)
def tqdm_write(msg):
    from tqdm import tqdm
    tqdm.write("" if msg is None else str(msg))
PROGRESS = {"progress": None}

# ---------------- dictionary ----------------
def dict_block_for_prompt():
    lines = []
    if DICT["exact"]:
        lines.append("ОБЯЗАТЕЛЬНЫЕ ТОЧНЫЕ СТРОКИ — если английская строка входа равна одному из этих ключей (без учёта регистра), русское значение ДОЛЖНО быть ровно это:")
        for en, ru in sorted(DICT["exact"].items()):
            lines.append(f'  "{en}" => "{ru}"')
    if DICT["words"]:
        lines.append("ОБЯЗАТЕЛЬНЫЕ ТЕРМИНЫ — когда этот английский (или близкий) термин встречается ВНУТРИ строки, в русском выводе используй ровно это слово/фразу (не придумывай другое) для того термина:")
        for en, ru in sorted(DICT["words"].items()):
            lines.append(f'  "{en}" => "{ru}"')
    return "\n".join(lines) if lines else "(пусто)"

def apply_dict(en_original, ru_translated):
    """Post-fix: enforce dictionary so UI keys/categories stay consistent.
    1) exact: whole EN string is a dictionary key -> return its RU (guaranteed match).
    2) words: EN word present in RU string left untranslated -> replace by term RU.
    """
    low = en_original.strip().lower()
    if low in DICT["exact"]:
        return DICT["exact"][low]
    out = ru_translated
    for en, ru in DICT["words"].items():
        if not en:
            continue
        # word-boundary replacement, case-insensitive (covers "Smithing", "smithing", "Smithing,")
        # (?![a-z']) — НЕ подхватить внутри слова (приставка, апостроф-множественное)
        # (?![A-Za-z]) — не подхватить внутри бОльшего EN-токена (Fishmen ≠ Fishman)
        pat = re.compile(r"(?<![A-Za-z])" + re.escape(en) + r"(?![A-Za-z])", re.IGNORECASE)
        out = pat.sub(ru, out)
    return out

# ---------------- discovery ----------------
def workshop_mods():
    out = []
    if not os.path.isdir(WORKSHOP):
        return out
    for d in sorted(os.listdir(WORKSHOP)):
        p = os.path.join(WORKSHOP, d)
        if not os.path.isdir(p) or not d.isdigit():
            continue
        name = None
        info = [f for f in os.listdir(p) if f.startswith("_") and f.endswith(".info")]
        if info:
            try:
                txt = open(os.path.join(p, info[0]), encoding="utf-8", errors="replace").read()
                m = re.search(r"<name>(.*?)</name>", txt, re.DOTALL)
                if m:
                    name = m.group(1).strip()
            except Exception:
                pass
        modfiles = [f for f in os.listdir(p) if f.lower().endswith(".mod")]
        if not name:
            name = (modfiles[0] if modfiles else d)[:-4]
        out.append({"id": d, "name": name, "dir": p,
                    "modfile": os.path.join(p, modfiles[0]) if modfiles else None})
    return out

def game_mods():
    """Встроенные моды ИГРЫ (2026-09-23):
      • kenshi\\data\\*.mod  — базовая локализация (rebirth.mod, Dialogue.mod, Newwworld.mod);
      • kenshi\\mods\\<sub>\\*.mod — вручную установленные (не Workshop).
    id человекочитаемый (`game:rebirth`, `game:FCS_extended/x`) — resolve_mod
    подхватывает его по подсстроке, если имя неоднозначно.
    Искусственные файлы (наши .backup/.revert_) — игнорируются."""
    out = []
    seen = set()
    def add(p, idval, gk):
        p = os.path.abspath(p)
        key = os.path.normcase(p)
        if key in seen:
            return
        seen.add(key)
        base = os.path.basename(p)
        out.append({"id": idval, "name": base[:-4],
                    "dir": os.path.dirname(p), "modfile": p,
                    "kind": "game", "gk": gk})
    data_dir = os.path.join(GAME, "data")
    if os.path.isdir(data_dir):
        for f in sorted(os.listdir(data_dir)):
            if not f.lower().endswith(".mod") or not os.path.isfile(os.path.join(data_dir, f)):
                continue
            if any(tag in f for tag in (".backup", ".orig_", ".revert_", ".prev", ".new", ".broken")):
                continue
            add(os.path.join(data_dir, f), f"game:{f[:-4]}", "data")
    mods_root = os.path.join(GAME, "mods")
    if os.path.isdir(mods_root):
        for d in sorted(os.listdir(mods_root)):
            dp = os.path.join(mods_root, d)
            if not os.path.isdir(dp):
                continue
            for f in sorted(os.listdir(dp)):
                if not f.lower().endswith(".mod") or not os.path.isfile(os.path.join(dp, f)):
                    continue
                if any(tag in f for tag in (".backup", ".orig_", ".revert_", ".prev", ".new", ".broken")):
                    continue
                add(os.path.join(dp, f), f"game:{d}/{f[:-4]}", "mods")
    return out

def resolve_mod(query, all_mods):
    q = query.strip()
    if os.path.isfile(q) and q.lower().endswith(".mod"):
        return {"id": "-", "name": os.path.basename(q)[:-4], "dir": os.path.dirname(q), "modfile": q}
    if os.path.isdir(q):
        mf = [os.path.join(q, f) for f in os.listdir(q) if f.lower().endswith(".mod")]
        if mf:
            if os.path.abspath(q).lower().startswith(WORKSHOP.lower()):
                parent = os.path.basename(os.path.dirname(q))
                for m in all_mods:
                    if m["id"] == parent:
                        return m
            return {"id": "-", "name": os.path.basename(os.path.normpath(q)), "dir": q, "modfile": mf[0]}
    if q.isdigit():
        for m in all_mods:
            if m["id"] == q:
                return m
        return None
    ql = q.lower()
    # 1) ТОЧНОЕ имя (case-insensitive) — primary: кэш/verify дают точные заголовки.
    #    Раньше тут был только substring-поиск, и «Tents»+«Tents RUS» давали 2 kanda
    #    -> resolve=None -> fix молча пропускал мод (2026-09-19, баг fix_translations).
    exact = [m for m in all_mods if (m["name"] or "").lower() == ql]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        log(f"[!] несколько мода с ИДЕНТИЧНЫМ именем '{q}' — неоднозначно, уточни id:")
        for i, m in enumerate(exact[:8]):
            log(f"    {i}: {m['name']}  (id {m['id']})  {os.path.basename(m['modfile'] or '')}")
        return None
    # 2) нет точного совпадения — substring (для ручного CLI-запуска по куску имени)
    def hay(m):
        return " ".join([m["name"] or "", m["id"], os.path.basename(m["modfile"] or "")]).lower()
    cands = [m for m in all_mods if ql in hay(m) or ql.replace(" ", "") in hay(m).replace(" ", "")]
    cands.sort(key=lambda m: len(m["name"] or ""))
    if len(cands) == 1:
        return cands[0]
    if len(cands) > 1:
        log(f"[!] несколько мода подходят для '{q}':")
        for i, m in enumerate(cands[:8]):
            log(f"    {i}: {m['name']}  (id {m['id']})")
        log("    выбери один: перезапусти командой с точным именем или id")
        return None
    return None

def ensure_target(m):
    """Целевой .mod для перевода.
    Workshop-мод -> его СОБСТВЕННЫЙ файл (in-place, без копии в mods\\).
    Файлы игры (kenshi\\data\\*.mod, kenshi\\mods\\*.mod) -> тоже in-place
      (2026-09-21: добавлено — теперь можно переводить и встроенные в игру строки
       через поиск search_mods.py → ввод номеров → запуск перевода).
    Ручной мод (в ином месте) -> старое поведение: копия в mods\\."""
    src = m["modfile"]
    if not src or not os.path.isfile(src):
        return None
    p = os.path.normcase(os.path.abspath(src))
    # in-place: файлы workshop ИЛИ файлы внутри каталога игры
    for base in (WORKSHOP, GAME):
        try:
            b = os.path.normcase(os.path.abspath(base)) + os.sep
            if p.startswith(b):
                return src
        except Exception:
            pass
    # ручной мод (вне workshop, вне игры) — копируем в mods\ (старое поведение)
    target_dir = os.path.join(MODS_DIR, m["name"])
    target = os.path.join(target_dir, os.path.basename(src))
    if os.path.isfile(target) and os.path.getsize(target) == os.path.getsize(src):
        return target
    os.makedirs(target_dir, exist_ok=True)
    for f in os.listdir(m["dir"]):
        sp = os.path.join(m["dir"], f)
        dp = os.path.join(target_dir, f)
        if os.path.isfile(sp) and not os.path.exists(dp):
            shutil.copy2(sp, dp)
        elif os.path.isdir(sp) and not os.path.exists(dp):
            shutil.copytree(sp, dp)
    return target if os.path.isfile(target) else None

# ---------------- LLM ----------------
REASONING_EFFORT = T.get("reasoning_effort", "low")
TEMPERATURE = float(T.get("temperature", 0.7))

def llm_call(strings):
    """Translate a chunk of strings via the OpenAI-compatible proxy.

    Reasoning control (2026-09-19, прояснено живой матрицей на RecruitPrisoners):
      - Qwen3-27b с reasoning_effort='low' на БОЛЬШИХ чанках (250–500 строк)
        тратит 20–40k символов на рассуждения и возвращает ПУСТОЙ/усечённый
        content (1 строка из 500). Это НЕ лимит max_tokens (потрачено 10–20k из
        200k, finish_reason=stop) — это расход reasoning-режима.
      - reasoning_effort='none' — чанки 250/500 сдают 100% (0 символов reasoning).
    Стратегия:
      1) Пробуем заданный `REASONING_EFFORT` (default 'low') — он лучше для
         стиля/юмора на маленьких чанках.
      2) Если ответ пустой / не распарсился / len mismatch — АУТО-повтор с
         `reasoning_effort='none'` (без рассуждений). Один повтор, не зацикливаем.
    Parse: Qwen при reasoning-режиме склоняется к JSON-массиву в markdown
        ```` ```json ... ``` ````. Парсер: 1) снять markdown-ограждения,
        2) попытаться json.loads, 3) fallback на построчный (строка = 1 перевод,
        ТОЛЬКО при точном совпадении длины).
    """
    def _one_attempt(effort):
        user = USER_PROMPT_TMPL.replace("{{COUNT}}", str(len(strings)))
        system = SYS_PROMPT.replace("{{DICT}}", dict_block_for_prompt())
        # Динамические подсказки из RU-локализации игры под ЭТОТ батч
        # (только то, что не покрывается dict.json + только релевантное к строкам батча —
        #  не раздуваем промпт статично)
        if _PO_HINTS_ENABLED:
            try:
                hbk = po_hints.hints_block(
                    strings,
                    dict_keys=set(DICT["exact"].keys()) | {k for k in DICT["words"].keys()},
                    max_hints=_PO_HINTS_MAX,
                )
                if hbk:
                    system = system + "\n\n" + hbk
            except Exception as e:
                log(f"[warn] po_hints: {e}")
        body = {
            "model": LLM_MODEL,
            "max_tokens": MAX_TOKENS,
            "reasoning_effort": effort,
            "temperature": TEMPERATURE,
            "chat_template_kwargs": {"enable_thinking": not bool(THINKING_OFF)},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user",   "content": user + "\n\n" + json.dumps(strings, ensure_ascii=False)},
            ],
        }
        headers = {"Content-Type": "application/json; charset=utf-8"}
        if LLM_KEY:
            headers["Authorization"] = "Bearer " + LLM_KEY
        req = urllib.request.Request(
            LLM_BASE + "/chat/completions",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=HTTP_TO) as r:
            d = json.loads(r.read().decode("utf-8"))
        ch = d["choices"][0]
        content = (ch["message"].get("content") or "").strip()
        truncated = ch.get("finish_reason") == "length"
        usage = d.get("usage") or {}

        # 2026-09-19: qwen3.8:27b на длинных описаниях галлюцинирует:
        #  (a) оборачивает верный перевод в объект  {"text": "[h1]Привет!…"};
        #  (b) выдумывает API-ошибку               {"error": {"message": "…"}}
        #      (это НЕ ответ сервера — сервер вернул 200, «ошибка» в content).
        # Нормализация: (a) достаём field.text как строку; (b) поднимаем
        # Transient('model-hallucinated-error'), чтобы вызывающий повторил запрос.
        def _unwrap(text):
            t = text.lstrip()
            if t.startswith("{"):
                try:
                    obj = json.loads(t)
                except Exception:
                    # не валидный объект — пробуем вытащить "text": "..."
                    mt = re.search(r'"text"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
                    if mt:
                        try:
                            return json.loads('"' + mt.group(1) + '"')
                        except Exception:
                            return mt.group(1)
                    return None
                if isinstance(obj, dict) and "error" in obj:
                    return "__MODEL_HALLUCINATED_ERROR__"
                if isinstance(obj, dict) and isinstance(obj.get("text"), str) and len(obj) <= 3:
                    return obj["text"]
            return None
        unwrapped = _unwrap(content)
        if unwrapped == "__MODEL_HALLUCINATED_ERROR__":
            log("  [модель] выдумала API-ошибку вместо перевода — повтор")
            raise Transient(f"model hallucinated an error object (effort={effort})")
        if unwrapped is not None:
            content = unwrapped

        def _strip_md(s):
            s = s.strip()
            m = re.match(r"^```[a-zA-Z+*-]*\n?(.*?)\n?```$", s, re.DOTALL)
            if m:
                s = m.group(1).strip()
            s = re.sub(r"^\s*//.*$", "", s, flags=re.MULTILINE)
            return s

        cleaned = _strip_md(content)
        arr = None
        m = re.search(r"\[.*\]", cleaned, re.DOTALL)
        if m:
            candidate = m.group(0)
            try:
                arr = json.loads(candidate)
            except Exception:
                pass
        # -- извлекаем строки по порядку (устойчиво к обрывам и лишним) --
        # ищем ВЕСЬ текст после первой "[", не требуем закрывающей "]"
        if arr is None and cleaned.lstrip().startswith("["):
            body = cleaned[cleaned.index("[") + 1:]
            strs_found = re.findall(r'"((?:[^"\\]|\\.)*)"', body)
            if strs_found:
                arr = strs_found
                log(f"  [парсер] извлёк по порядку {len(arr)} строк (валидного JSON не было)")
        # -- запасной построчный парс --
        if arr is None:
            lines = [l.strip() for l in content.splitlines() if l.strip()]
            if len(lines) == len(strings):
                arr = lines
                log(f"  [парсер] JSON не распарсился → построчный ответ ({len(lines)} строк)")
        n = len(strings)
        if arr is not None and isinstance(arr, list) and arr:
            if len(arr) > n:
                log(f"  [парсер] лишние строки в ответе ({len(arr)}) — обрезаю до {n}")
                arr = arr[:n]
            elif len(arr) < n and len(arr) >= max(4, n // 3):
                # обрван в хвосте: передняя часть доверена (JSON в том же порядке) —
                # спасаем её, хвост (отсутствующие) уйдёт в допериод
                miss = n - len(arr)
                log(f"  [salvage-prefix] ответ обрезан: сдаю {len(arr)}, в допериод {miss} строк (хвост)")
                pad = list(arr) + [""] * miss
                bad = [i for i, (en, ru) in enumerate(zip(strings, pad))
                       if check_row(en, ru) in ("error", "echo")]
                bad = sorted(set(bad))
                out = [str(x) if i < len(arr) else "" for i, x in enumerate(pad)]
                return out, bad
            elif len(arr) < n:
                # ответ значительно короче нужного (не salvage-обломок) — перекинуть/дробить
                log(f"  [чанк] ответ {len(arr)}/{n} строк (слишком короткий) — ретрай")
                raise Transient(
                    f"len mismatch {len(arr)} != {n} (effort={effort}, "
                    f"usage={usage}) - first 80 chars: {content[:80]!r}")
            # == n  → норма, идём в validate_batch ниже
        else:
            if not content:
                raise Transient(
                    f"empty content (effort={effort}, finish_reason={ch.get('finish_reason')}, "
                    f"usage={usage}) - модель утащила ответ в рассуждения")
            raise Transient(
                f"unparseable response (effort={effort}, usage={usage}) - "
                f"first 80 chars: {content[:80]!r}")
        rep = validate_batch(strings, arr)
        if rep["hard"]:
            bad = [i for i, (en, ru) in enumerate(zip(strings, arr)) if check_row(en, ru) in ("error", "echo")]
            where = f" row {bad[:6]}" + (f" (+{len(bad)-6} more)" if len(bad) > 6 else "")
            log(f"  [salvage] отбираю хорошие, дорабатываю {len(bad)} ({rep['reason'][:38]}{where})")
            # САЛВЕЙДЖ: переводимые строки — принимаем; битые — помечаем пустым
            # и возвращаем индексы, чтобы вызывающий отправил только их в допериод.
            tr = [("" if i in set(bad) else str(x)) for i, x in enumerate(arr)]
            return tr, bad
        if rep["echo"] or rep["warn"]:
            log(f"  [audit] {rep['echo']} echo, {rep['warn']} warn (one-word passthrough / no Cyrillic)")
        return [apply_dict(s, str(x)) for s, x in zip(strings, arr)], []

    # 1) основной режим
    try:
        return _one_attempt(REASONING_EFFORT)
    except Transient as ex:
        reason = str(ex)
        # 2) авто-fallback: если ответ пуст/не распарсился/не та длина — пробуем без рассуждений
        triggers = ("empty content", "unparseable response", "len mismatch", "hallucinated an error")
        if REASONING_EFFORT != "none" and any(t in reason for t in triggers):
            log(f"  [auto-fallback] чанк {len(strings)} строк с effort='{REASONING_EFFORT}' → "
                f"повторяю с reasoning_effort='none' (reason: {reason[:58]})")
            time.sleep(2.0)
            try:
                return _one_attempt("none")
            except Transient as ex2:
                # финальный сбой — пробрасываем, чтобы _fix_chunk мог дальше дробить
                log(f"  [auto-fallback] effort='none' тоже не сдал: {str(ex2)[:80]}")
                raise ex2
        raise

class Transient(Exception):
    pass

def save_map():
    """Save the in-progress done_map to disk (resumable).
    2026-09-22: НЕ фильтруем здесь — это raw intermediate state для resume.
    Финальный save (в translate_one, перед apply и export_mod_csv) применяет
    keep_row — там «готовый» mapping. save_map вызывается каждые N чанков и
    должен быть дешёвым + не терять данные mid-flight (если строка ещё в
    процессе — не отбрасываем её сейчас, пусть финальный save решит).
    """
    if CUR["mapfile"] and CUR["mapref"] is not None:
        m = CUR["mapref"]
        with open(CUR["mapfile"], "w", encoding="utf-8") as f:
            json.dump([{"i": int(k), "ru": v} for k, v in sorted(m.items())],
                      f, ensure_ascii=False)

# --- Динамический батч по токен-бюджету контекста -------------------------------
# Окно провайдера: вход+выход. Из него вычитаем промт (система+dict+шаблон),
# запас на reasoning и ВЫХОД (RU≈1.2x вход по символам). Коэффициент
# CHARS_PER_TOK ≈ 2.2 (1 токен ≈ 2.2 символа на миксе RU/EN, консервативно).
def sys_overhead_ch():
    """Объём промпта (prompt.txt + dict.json + обёртка) в символах."""
    n = 0
    for f in (PROMPT_FILE,):
        try:
            n += os.path.getsize(f)
        except Exception:
            pass
    try:
        n += os.path.getsize(DICT_PATH)
    except Exception:
        pass
    return n + 2000   # +2k на user-шаблон/инструкции

def plan_chunk(prefix, ovh, start=0, cap_limit=None):
    """Максимальное число строк, начиная с индекса `start`, укладывающихся
    в CONTEXT_WIN по входу и в MAX_OUT_TOK по выходу.
    prefix = префикс-суммы [0, len0, len0+len1, ...] (абсолютные индексы);
    строка с индексом `k` (0-based) учитывается как prefix[k+1].
    cap_limit: потолок строк в этом чанке (обычно total-start или MAX_BATCH_LN)."""
    n_avail = len(prefix) - 1 - start
    if n_avail <= 0:
        return MIN_CHUNK
    hard_cap = cap_limit if cap_limit is not None else MAX_BATCH_LN
    cap = min(hard_cap, n_avail)
    best = MIN_CHUNK
    lo, hi = MIN_CHUNK, cap
    while lo <= hi:
        mid = (lo + hi) // 2
        # строки [start, start+mid) → prefix[start] .. prefix[start+mid]
        chars_chunk = prefix[start + mid] - prefix[start]
        est_in = (chars_chunk + ovh) / CHARS_PER_TOK
        est_out = (chars_chunk * 1.2) / CHARS_PER_TOK
        if est_in + est_out <= CONTEXT_WIN and est_out <= MAX_OUT_TOK:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    # пол = 1, а не MIN_CHUNK: если строки длинные и окно узкое — лучше 1 строка,
    # чем 4 не помещающиеся в контекст (провайдер упрётся в лимит).
    return max(1, best)

def translate_entries(entries, done_map, name, ctx):
    """Перевод оставшихся строк (батченно, resumable).

    Стратегия (2026-09-19, по просьбе пользователя):
    • динамический размер чанка: пакет строится до токен-бюджета CONTEXT_WIN
      (короткие строки → больше строк в чанке, упирается в MAX_BATCH_LN потолок
      — твоя цифра «до 500»; длинные → токены ужимают число строк);
    • прогрессбар меряется в ТОКЕНАХ (вход=символы строки / CHARS_PER_TOK),
      а не в строках — т.к. батчи динамические; бар advances только за
      УСПЕШНО переведённые (упавшие чанки не «списываются» вперёд);
    • упавший чанк (empty / len mismatch / отбраковка audit) НЕ ретраится
      по-кусочному в цикле — его строки откладываются в failed и ПОСЛЕ
      основного прохода мода уходят LLM отдельным проходом (ДОПЕРИОД)
      со своим прогрессбаром FIX (в токенах) в том же слоте, что и NOW-бар;
    • если строки всё равно не сданы — пустыми; подхватят verify --fix / resume.
    """
    todo = [e for e in entries if str(e["i"]) not in done_map]
    # 2026-09-19: оставляем ТОЛЬКО строки, которым по единому классификатору
    # НУЖЕН перевод (empty/echo/latin/ph_lost/mixed при пустом RU). Пустые
    # onomatopoeia/entry-ID/already_ru ЛЛМ НЕ переведёт (rightfully) — раньше
    # они входили в чанк, захлёбывали squeal/LM и роняли ВЕСЬ чанк (len
    # mismatch), унося с собой соседние РЕАЛЬНО битые строки (NewRecruits:
    # 813/4689 упали из-за 4688 squeal + 4922/4923 entry-ID).
    todo = [e for e in todo if _needs_translation(e.get("original") or "")]
    # ---- ПРЕ-LLM ФИЛЬТР (2026-09-21, по просьбе пользователя) ----
    # Два слоя до отправки батча LLM:
    #   СЛОЙ 1 — «нечего переводить» (regex): чистая кириллица/знаки/числа/
    #            CJK (после чистки BBCode+[h1]...[/h1] и слэш-тегов /AAA/) —
    #            в ней нет ни одной латинской буквы → нечего LLM «давать».
    #            Passthrough: в .mod останется оригинал. Не входит в батч.
    #   СЛОЙ 2 — «уже переведено»: готовый RU из dict.json/.по игры/кешей
    #            ранее переведённых модов. Подставляем, НЕ спрашиваем LLM
    #            (экономим токены+время, держим консистентное написание).
    # Эхо (RU==EN) и грязный RU (кириллица в /.../) — НЕ считаем готовым.
    n_passthrough = n_reused = 0
    if PRE_FILTER_ENABLED:
        keep = []
        for e in todo:
            en = e.get("original") or ""
            if prefilter.nothing_to_translate(en):
                n_passthrough += 1
                # 2026-09-22: passthrough (RU=EN) НЕ пишем в кэш — строка
                # «ничего не переводить»: кириллица/знаки/CJK/пусто. В .mod
                # оригинал и так останется (строка без перевода не меняется).
                continue
            ru, src = prefilter.lookup(en)
            if ru:
                n_reused += 1
                # apply_dict: если en в exact — берём канон RU; иначе подставляем как есть
                done_map[str(e["i"])] = apply_dict(en, ru)
                continue
            keep.append(e)
        todo = keep
        if n_passthrough:
            log(f"  [pre-LLM: нечего переводить] {n_passthrough} строк (кириллица/знаки/CJK) — passthrough, не спрашиваю LLM")
        if n_reused:
            log(f"  [pre-LLM: уже переведено] {n_reused} строк (dict/game.po/ранее перевед.моды) — беру готовый RU, не спрашиваю LLM")
        if n_passthrough or n_reused:
            save_map()
    total_rows = len(todo)
    if total_rows == 0:
        log(f"  все строки обработаны (passthrough {n_passthrough} + reuse {n_reused}) → перехожу к apply")
        return done_map
    ovh = sys_overhead_ch()
    # префикс-суммы: символов (для plan_chunk) и токенов (для прогрессбара)
    lens = [max(1, len(str(e.get("original") or ""))) for e in todo]
    s_pref = [0]     # символы
    for x in lens:
        s_pref.append(s_pref[-1] + x)
    def tokens(i0, i1):
        return (s_pref[i1] - s_pref[i0]) / CHARS_PER_TOK
    total_tok = round(tokens(0, total_rows))
    log(f"  перевожу {total_rows} строк ≈ {total_tok} tok "
        f"(динам.чанк: окно {CONTEXT_WIN} tok, потолок {MAX_BATCH_LN} строк; "
        f"прогресс в токенах; упавшие — в допериод)")
    t_start = time.time()
    PR = PROGRESS["progress"]
    if PR is not None:
        PR.begin_mod(name, total_tok, done=0, unit="ток")
    failed = []
    i = 0
    while i < total_rows:
        cap = min(MAX_BATCH_LN, total_rows - i)
        nch = max(1, plan_chunk(s_pref, ovh, start=i, cap_limit=cap))
        chunk = todo[i:i + nch]
        ok_tokens = 0
        try:
            strs = [e["original"] for e in chunk]
            tr, bad = llm_call(strs)
            if len(tr) != len(chunk):
                raise Transient(f"len mismatch {len(tr)}!={len(chunk)}")
            badset = set(bad or ())
            for j, (e, t) in enumerate(zip(chunk, tr)):
                if j not in badset and str(t).strip():
                    done_map[str(e["i"])] = t
                    ok_tokens += max(1, len(str(e.get("original") or "")))
            if bad:
                # САЛВЕЙДЖ: хорошие уже в done_map; битые — в допериод (FIX), не глутим
                fb = [chunk[j] for j in bad]
                failed.extend(fb)
                log(f"  [чанк {nch}: {len(chunk)-len(bad)} ok, {len(bad)} стр. → допериод]")
        except Exception as ex:
            # не дробим и не ретраим по одной: уводим в допериод
            failed.extend(chunk)
            ok_tokens = 0
            log(f"  [чанк {nch} строки упал: {str(ex)[:58]}]")
        i += len(chunk)
        save_map()
        if PR is not None and ok_tokens:
            PR.step_strings(round(ok_tokens / CHARS_PER_TOK))
    # --- ДОПЕРИОД: все упавшие строки мода — своим баром FIX (в токенах) ---
    # Новый подход (2026-09-19): если пачка упала с «empty content» — делим её
    # пополам и повторяем. При «len mismatch» — сразу пробуем половину (модель
    # дала лишнюю/недодала — уменьшаем, чтобы влезть в окно). Рекурсия ≤ 6.
    def _fix_chunk(ch, depth=0):
        """Дорабатываем упавший кусок. Стратегия (2026-09-19, против зацикливания):
        1) пробуем размер как есть, при сбое — ЕЩЁ ОДИН повтор того же размера
           (сбой неопределённый: unparseable/len mismatch — повтор часто проходит);
        2) не прошло — делим пополам и повторяем на halves (рекурсия ≤ 5,
           нижняя граница 8 строк). SALVAGE: если llm_call сдал часть строк,
           плохие уходят глубже, а хорошие уже в done_map — нет зряшних вызовов."""
        if depth > 5 or len(ch) < 8:
            # последняя попытка как есть (salvage отработает), результат принимаем
            strs = [e["original"] for e in ch]
            try:
                tr, _ = llm_call(strs)
                for e, t in zip(ch, tr):
                    if str(t).strip():
                        done_map[str(e["i"])] = t
            except Exception as ex:
                log(f"  [допериод/глубина] {len(ch)} строк: сдался ({str(ex)[:40]})")
            return []
        strs = [e["original"] for e in ch]
        last_err = None
        for attempt in (1, 2):  # два раза тот же размер, потом делить
            try:
                tr, _ = llm_call(strs)
                if len(tr) != len(ch):
                    raise Transient(f"len mismatch {len(tr)}!={len(ch)}")
                for e, t in zip(ch, tr):
                    if str(t).strip():
                        done_map[str(e["i"])] = t
                return tr
            except Exception as ex:
                last_err = ex
                reason = str(ex).split('(')[0].strip()
                if attempt == 1:
                    time.sleep(2.0)  # повтор того же размера
                    continue
                log(f"  [чанк {len(ch)} строк: 2 попытки упали ({reason[:44]}) → делю пополам]")
        half = max(4, len(ch) // 2)
        l, r = ch[:half], ch[half:]
        return _fix_chunk(l, depth + 1) + _fix_chunk(r, depth + 1)

    # --- ДОПЕРИОД: все упавшие строки мода — своим баром FIX (в токенах) ---
    if failed:
        f_chars = sum(max(1, len(str(e.get("original") or ""))) for e in failed)
        f_tok = round(f_chars / CHARS_PER_TOK)
        log(f"  [допериод] {len(failed)} строк с ошибками ≈ {f_tok} tok — "
            f"перевожу отдельным баром (FIX), дроблю при сбое")
        if PR is not None:
            PR.begin_repair(name, f_tok, done=0, unit="ток")
        done_tokens = set()   # индекс (e["i"]) тех, что реально сданы
        i_failed = list(range(len(failed)))
        # итеративно: берём кусок по MAX_BATCH_LN, если не сдал — дробим
        while i_failed:
            cap = min(MAX_BATCH_LN, len(i_failed))
            cur = i_failed[:cap]
            i_failed = i_failed[cap:]
            ch = [failed[idx] for idx in cur]
            result = _fix_chunk(ch, depth=0)
            # результат: список строк (переводы) — но может быть короче ch,
            # если модель всё ещё не сдала часть (глубина исчерпана).
            # Те, что сданы, вычли из i_failed; те, что не сданы — возвращаем.
            done_n = sum(1 for e in ch if str(e["i"]) in done_tokens) or len(result)
            # (успех определяется по тому, сколько строки появилось в done_map
            # относительно их изначального state: но мы не храним исходное —
            # упрощаем: если _fix_chunk вернул список — считаем все ch сданными)
            if result:
                done_tokens.update(str(e["i"]) for e in ch)
            save_map()
            if PR is not None and result:
                step = round(sum(max(1, len(str(e.get("original") or ""))) for e in ch) / CHARS_PER_TOK)
                PR.step_strings(step)
    ctx["t_llm"] = ctx.get("t_llm", 0.0) + (time.time() - t_start)
    return done_map

def done_n_frac(name, done_map, entries):
    return sum(1 for v in done_map.values() if v) / max(1, len(entries))

def export_mod_csv(target, entries, done):
    """Пишет <папка .mod>/<имя-мода>.translate.csv: оригинал|перевод (UTF-8 BOM, разделитель |).
   Имя файла = имя .mod без расширения + .translate.csv (2026-09-21: раньше просто
   translate.csv — в папке с НЕСКОЛЬКИМИ .mod они затирали друг друга, напр.
   kenshi\\data\\: rebirth.mod/Dialogue.mod/Newwworld.mod). Старые translate.csv
   по-прежнему читаются csv_mod.py как fallback.

   2026-09-22 (по просьбе пользователя): строки, определённые как СИСТЕМНЫЕ
   (identifier/onomatopoeia/уже-русский/passthrough), НЕ пишутся в CSV и в кэш —
   они не «перевод» (единый источник = validate_translation.finished_row /
   is_translatable_text). Пустые ПЕРЕВОДИМЫЕ строки (LLM не дала) пишутся в CSV
   пустыми — user заполняет в Excel; в кэш они НЕ попадают (has_real_translation)."""
    import csv as _csv
    from validate_translation import finished_row
    base = os.path.basename(target)
    if base.lower().endswith(".mod"):
        base = base[:-4]
    out = os.path.join(os.path.dirname(target), base + ".translate.csv")
    n_filled = 0
    n_skipped = 0
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        w = _csv.writer(f, delimiter="|", quoting=_csv.QUOTE_MINIMAL)
        for e in entries:
            i = str(e.get("i"))
            orig = (e.get("original") or "").strip()
            ru = (done.get(i) or "").strip()
            # finished_row: реальный перевод ИЛИ пустая переводимая строка (для Excel)
            if not finished_row(orig, ru or None):
                n_skipped += 1
                continue
            w.writerow([orig, ru])
            if ru:
                n_filled += 1
    if n_skipped:
        log(f"  [csv] записано {n_filled} заполнен. строк; пропущено {n_skipped} системных/непереводимых")
    return out, len(entries), n_filled
# ---------------- dotnet CLI ----------------
def run_dotnet(args):
    r = subprocess.run([DOTTNET, CLI_DOTS] + args, capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        raise RuntimeError("dotnet CLI failed:\n" + (r.stderr or r.stdout)[:2000])
    return r

# ---------------- one mod ----------------
def translate_one(m, index, total_mods, ctx, drop_ids=None):
    """Translate a mod and apply the .mod (RU).

    drop_ids: optional iterable of entry indices to DROP from the resume
    cache before translating — surgical re-translation of exactly those rows
    (verify_translations --fix uses this so that already-good rows are NOT
    re-asked from the LLM and not re-shuffled). drop_ids=None = normal flow.
    """
    name = m["name"]
    log(f"\n--- [{index}/{total_mods}] МОД: {name} (id {m['id']}) ---")
    PR = PROGRESS["progress"]
    src = m["modfile"]
    if not os.path.isfile(src or ""):
        log("  [!] нет .mod в исходном каталоге - пропускаю")
        return False
    target = ensure_target(m)
    if not target:
        log("  [!] не могу подготовить целевой .mod - пропускаю")
        return False
    in_place = (os.path.normcase(os.path.abspath(target)) == os.path.normcase(os.path.abspath(src)))
    _t = os.path.normcase(os.path.abspath(target))
    _ws = os.path.normcase(os.path.abspath(WORKSHOP)) + os.sep
    _gp = os.path.normcase(os.path.abspath(GAME)) + os.sep
    if in_place:
        where = "in-place, workshop" if _t.startswith(_ws) else ("in-place, игра" if _t.startswith(_gp) else "in-place")
    else:
        where = "копия в mods"
    log(f"  цель: {target}  ({where})")
    import hashlib
    # Якорь кеша — MD5 ОРИГИНАЛА (EN). Если рядом уже лежит наш бэкап .orig_<h>.backup —
    # берём h из его имени (файл после перевода отличается: RU), иначе md5(target).
    h = None
    base = os.path.basename(target)
    for f in os.listdir(os.path.dirname(target)):
        if f.startswith(base + ".orig_") and f.endswith(".backup"):
            h = f[len(base) + 6:-len(".backup")]
            break
    if not h:
        h = hashlib.md5(open(target, "rb").read()).hexdigest()[:12]
        backup = target + f".orig_{h}.backup"
        if not os.path.exists(backup):
            shutil.copy2(target, backup)
            log(f"  бэкап EN: {os.path.basename(backup)}")
    else:
        backup = target + f".orig_{h}.backup"
        log(f"  бэкап EN: {os.path.basename(backup)} (уже есть — перевод уже делался)")
    efile = os.path.join(STATE, f"{h}_entries.json")
    mfile = os.path.join(STATE, f"{h}_mapping.json")
    CUR.update({"mapfile": mfile, "mapref": None})
    # 1. extract (cached per content hash)
    if not NO_CACHE and os.path.exists(efile):
        entries = json.load(open(efile, encoding="utf-8"))
        log(f"  entries кеш: {len(entries)}")
        if not entries:
            # 2026-09-19 (баг «находит 32 — не чинит»): СТАРЫЙ пустой кеш _entries.json
            # (C# extract когда-то сдал 0 строк). Пустой файл — НЕ валидный кеш:
            # молча гасит мод («mapping отсутствует»). Пересобираем извлечением.
            log(f"  [!] кеш ПУСТО (_entries.json = []) — пересобираю извлечение")
            os.remove(efile)
            if PR is not None: PR.busy("extract…")
            run_dotnet(["extract", target, efile])
            entries = json.load(open(efile, encoding="utf-8"))
            if PR is not None: PR.idle()
            log(f"  извлечено заново: {len(entries)} строк")
            if not entries:
                log(f"  [!] и после пересборки 0 строк — пропускаю (в .mod нет переводимого текста)")
                return False
    else:
        if PR is not None: PR.busy("extract…")
        run_dotnet(["extract", target, efile])
        entries = json.load(open(efile, encoding="utf-8"))
        if PR is not None: PR.idle()
        log(f"  извлечено: {len(entries)} строк")
    # 2. translate (resume; drop previously-failed empty rows)
    done = {}
    if FORCE:
        # 2026-09-20 (fix «прерванный force не резюмабелен»): старый код удалял
        # mfile при FORCE и начинал перевод с нуля — прерванный force-проход
        # (Ctrl+C, таймаут) терял ВСЁ: повторный запуск без FORCE не резюмабил,
        # потому что кеш уже пустой, и LLM пере-переводила ВСЕ строки заново.
        # Теперь:
        #   • .prev — полный backup старого кеша (откат/ручная подстановка);
        #   • mfile — перезаписан как ПУСТОЙ список (не удалён);
        #   • done остаётся ПУСТЫМ (force = «пере-переведи всё» — LLM спросит о каждой
        #     строке, todo строится на 586-й; _needs_translation на 593-й отфильтрует
        #     не-переводимое);
        #   • повторный запуск БЕЗ --force — resume подхватит частичный mfile и
        #     продолжит с места сбоя (строки с пустым RU не в done, попадут в todo).
        if os.path.exists(mfile):
            old = mfile + ".prev"
            shutil.copy2(mfile, old)
            log(f"  [force] старый кеш-маппинг сохранён в {os.path.basename(old)}"
                + f" (откат/подстановка); перевожу ВСЕ строки заново; "
                  f"при повторном запуске БЕЗ --force — resume подхватит частичный прогресс")
        # перезаписываем mfile ПУСТЫМ списком (не удаляем!) — чтобы LLM-ответы
        # попадали в чистый файл, а повторный запуск мог его читать (resume).
        json.dump([], open(mfile, "w", encoding="utf-8"), ensure_ascii=False)
    if not FORCE and os.path.exists(mfile):
        prev = {str(x["i"]): x["ru"] for x in json.load(open(mfile, encoding="utf-8"))}
        done = {k: v for k, v in prev.items() if v}
        if drop_ids:
            drop = {str(x) for x in drop_ids}
            removed = [k for k in drop if k in done]
            for k in removed:
                done.pop(k, None)
            if removed:
                log(f"  [fix] пере-переведу ТОЛЬКО {len(removed)} проблемных строк "
                    f"(остальные {len(done)} хороших сохранены)")
        if done:
            log(f"  resume: {len(done)}/{len(entries)} уже готово")
    CUR["mapref"] = done
    # 2026-09-21: --no-llm — режим «только CSV»: извлекаем строки, заполняем
    # доступное из кеша/prefilter (локально, 0 LLM) и пишем <имя>.translate.csv
    # — пользователь переводит сам (Excel), потом assemble_mod.bat. НЕ применяем.
    if NO_LLM:
        if PRE_FILTER_ENABLED:
            from validate_translation import is_translatable_text
            reused = 0
            for e in entries:
                if str(e["i"]) in done and (done[str(e["i"])] or ""):
                    continue
                en = e.get("original") or ""
                if not is_translatable_text(en):
                    continue
                ru, _src = prefilter.lookup(en)
                if ru and str(ru).strip() and str(ru).strip().lower() != en.strip().lower():
                    done[str(e["i"])] = str(ru)
                    reused += 1
            if reused:
                log(f"  [no-llm] prefill из локальных источников: {reused} строк")
        filled = sum(1 for v in done.values() if v and str(v).strip())
        # 2026-09-23 fix: --no-llm prefill должен сохраняться в кэш (mapping.json),
        # иначе csv_mod.py export/import не сможет восстановить перевод.
        # Применяем тот же has_real_translation, что и LLM-ветка, чтобы в кэш
        # не попадали системные / пустые / эхо строки.
        if filled:
            from validate_translation import has_real_translation as _hr
            _e_by_i = {str(e.get("i")): (e.get("original") or "").strip() for e in entries}
            _kept = [(k, v) for k, v in done.items() if _hr(_e_by_i.get(k, ""), str(v))]
            json.dump([{"i": int(k), "ru": v} for k, v in sorted(_kept, key=lambda kv: int(kv[0]))],
                      open(mfile, "w", encoding="utf-8"), ensure_ascii=False)
            log(f"  [no-llm] кэш: {len(_kept)} строк сохранено в {os.path.basename(mfile)}")
        try:
            export_mod_csv(target, entries, done)
            log(f"  [no-llm] CSV готов: {os.path.basename(target)[:-4]}.translate.csv "
                f"({filled}/{len(entries)} заполнено из кеша — остальное пусто, переведи сам; "
                f"системные строки в CSV не вошли)")
            log(f"  [no-llm] после правки: assemble_mod.bat \"{name}\"")
        except Exception as ex:
            log(f"  [no-llm/csv] не смог записать: {ex}")
            return False
        return True
    if len(done) < len(entries):
        ctx["nmods_done"] = index - 1
        translate_entries(entries, done, name, ctx)
    else:
        # everything already translated — show a full bar for one beat (в токенах)
        if PR is not None:
            _tok = round(sum(max(1, len(str(e.get("original") or ""))) for e in entries)
                         / CHARS_PER_TOK)
            PR.begin_mod(name, _tok, done=_tok, unit="ток")
    CUR["mapref"] = None
    filled = sum(1 for v in done.values() if v)
    unfilled = len(entries) - filled
    log(f"  coverage: {filled}/{len(entries)}" + (f"  ({unfilled} пропущено)" if unfilled else ""))
    if filled == 0:
        log("  [!] ничего не переведено - НЕ применяю (оригинальный .mod не тронут)")
        return False
    # --- финальный аудит (без LLM): есть ли РЕАЛЬНО валидные переводы? ---
    # audit_map (единый источник = classify_row): filled = валидные (ok + уже-русские +
    # идентификаторы), а echo/latin/ph_lost/empty — непересекающиеся проблемные классы.
    a = audit_map(entries, done)
    if a["echo"]:
        log(f"  [audit] ЭХО (перевод==оригинал): {a['echo']} стр. {a['echo_rows'][:6]}"
            + (f" …(+{len(a['echo_rows'])-6} ещё)" if len(a['echo_rows']) > 6 else ""))
    if a["latin"]:
        log(f"  [audit] без кириллицы (возможно нетранслировано): {a['latin']} строк")
    if a["ph_lost"]:
        log(f"  [audit] потеряны плейсхолдеры: {a['ph_lost']} строк")
    if a["empty"]:
        log(f"  [audit] пустые переводы: {a['empty']} строк")
    if a["already_ru"]:
        log(f"  [audit] уже русский (корректно, не переведено): {a['already_ru']} строк")
    if a["filled"] == 0:
        log("  [ABORT] нет ни одного валидного перевода (все строки — эхо/пустые/латынь) — "
            "НЕ применяю, .mod не тронут")
        return False
    # 3. apply (only filled rows) + safety check
    CUR["mapref"] = done
    # 2026-09-22: в кэш (mapping.json) попадают ТОЛЬКО реальные переводы
    # (has_real_translation: RU непустой и НЕ эхо оригинала). Системные строки
    # (identifier/onomatopoeia/уже-русский/passthrough) и недопереводённые
    # (пустые/эхо) в кэш НЕ идут — при apply «строкa не в маппинге» =
    # сохранение оригинала (apply не трогает её), что и нужно.
    from validate_translation import has_real_translation
    _e_by_i = {str(e.get("i")): (e.get("original") or "").strip() for e in entries}
    _kept = [(k, v) for k, v in done.items() if has_real_translation(_e_by_i.get(k, ""), str(v))]
    json.dump([{"i": int(k), "ru": v} for k, v in sorted(_kept, key=lambda kv: int(kv[0]))],
              open(mfile, "w", encoding="utf-8"), ensure_ascii=False)
    _dropped_n = len(done) - len(_kept)
    if _dropped_n:
        log(f"  [кэш] {len(_kept)} реал. переводов в кэш; {_dropped_n} строк (системные/пустые/эхо) вынесены из кэша и CSV")
    CUR["mapref"] = None
    if PR is not None: PR.busy("apply .mod…")
    run_dotnet(["apply", target, mfile, target + ".new"])
    if PR is not None: PR.idle()
    newb = open(target + ".new", "rb").read().decode("utf-8", "ignore")
    if not any("\u0400" <= c <= "\u04ff" for c in newb):
        os.remove(target + ".new")
        log("  [ABORT] apply не дал кириллицы - оригинальный .mod не тронут")
        return False
    os.replace(target + ".new", target)
    log(f"  [OK] RU-мод записан: {target}")
    # персист translate.csv в папке мода (оригинал|перевод) — для ручной правки
    try:
        export_mod_csv(target, entries, done)
    except Exception as ex:
        log(f"  [csv] не смог записать <имя-мода>.translate.csv: {ex}")
    return True

# ---------------- main ----------------
def translate_file(path, query_hint="", force=None, label=None):
    """Перевести ОДИН .mod-файл (workshop mod ИЛИ кенши игра: kenshi\\data\\*.mod, kenshi\\mods\\*.mod)
    — публичная обёртка для search_mods.py и CLI:
       • path     — абсолютный путь к .mod
       • label    — человекочитаемое имя (default: basename)
       • force    — override FORCE (True/None)
    Возвращает True/False (успех/сбой).
    Работает в рамках одного progress (внешний бар — на 1 мод)."""
    assert os.path.isfile(path), f"file not found: {path}"
    if force is not None:
        _set_force(force)
    label = label or os.path.basename(path)
    m = {
        "name":  label,                       # display name
        "id":    "game" if os.path.normcase(os.path.abspath(path)).startswith(
                os.path.normcase(os.path.abspath(GAME)) + os.sep) else "mod",
        "modfile": path,
        "dir":   os.path.dirname(path),
    }
    with Progress(1) as PR:
        PROGRESS["progress"] = PR
        try:
            r = translate_one(m, index=1, total_mods=1, ctx={"nmods_done": 0, "total_mods": 1})
        finally:
            PROGRESS["progress"] = None
    log(f"  [translate_file {label}] => {'OK' if r else 'FAIL'}")
    return bool(r)

def _set_force(flag):
    """Local FORCE override (no global mutation — uses env trick)."""
    # FORCE is module-level; simplest path: set sys.argv (already scanned). We
    # need to flip module global in a safe way. Use exec-style:
    globals()["FORCE"] = bool(flag)

def parse_list_file(path):
    out = []
    for ln in open(path, encoding="utf-8-sig", errors="replace"):
        ln = ln.strip()
        if ln and not ln.startswith("#"):
            out.append(ln)
    return out

def main():
    global INCLUDE_EXCLUDED
    if "--force" in sys.argv:
        sys.argv.remove("--force")
    if "--no-llm" in sys.argv:
        sys.argv.remove("--no-llm")
    if "--include-excluded" in sys.argv:
        sys.argv.remove("--include-excluded")
        INCLUDE_EXCLUDED = True
    # 2026-09-23: --steam / --mods — явные выборки подкаталогов.
    #   --steam : ТОЛЬКО Steam Workshop (workshop\content\233860\<id>)
    #   --mods  : ТОЛЬКО kenshi\mods\<mod>\*.mod (ручные, НЕ Workshop)
    # Без флага (default) — Steam Workshop.
    # ВСТРОЕННЫЕ моды игры (kenshi\data\*.mod: rebirth/Dialogue/Newwworld)
    # в «ВСЕ» НИКОГДА не входят — ТОЛЬКО по явном имени.
    SCOPE = None  # None = Steam (default), "steam", "mods", "all"
    if "--steam" in sys.argv:
        sys.argv.remove("--steam")
        SCOPE = "steam"
    if "--mods" in sys.argv:
        sys.argv.remove("--mods")
        SCOPE = "mods"
    if "--all" in sys.argv:
        sys.argv.remove("--all")
        SCOPE = "all"
    args = [a for a in sys.argv[1:] if a]
    # 2026-09-21: --file <path> --label <label> — перевести произвольный .mod
    # напрямую (workshop mod, kenshi\data\*.mod, kenshi\mods\<mod>\*.mod — любой путь).
    # Возврат: 0 = ok, 2 = арг. ошибка, 3 = fail.
    if "--file" in args:
        i = args.index("--file")
        if i + 1 >= len(args) or not args[i + 1]:
            print("--file needs a path")
            return 2
        fp = args[i + 1]
        args = args[:i] + args[i + 2:]
        label = None
        if "--label" in args:
            j = args.index("--label")
            if j + 1 < len(args) and args[j + 1]:
                label = args[j + 1]
                args = args[:j] + args[j + 2:]
            else:
                print("--label needs a value")
                return 2
        try:
            ok = translate_file(fp, label=label)
        except Exception as ex:
            log(f"  [!] --file error: {ex}")
            return 3
        return 0 if ok else 3
    queries = []
    if "--list-file" in args:
        i = args.index("--list-file")
        if i + 1 >= len(args):
            print("--list-file needs a path")
            return 2
        queries = parse_list_file(args[i + 1])
        args = args[:i] + args[i + 2:]
    queries += args

    all_mods = workshop_mods()
    game = game_mods()
    all_mods = all_mods + game
    log(f"модов видно: workshop={len(all_mods) - len(game)} + игра(data\\, mods\\)={len(game)}")
    skipped_excl = []
    mods = []
    orphan_skipped = []
    for q in queries:
        m = resolve_mod(q, all_mods)
        if not m:
            log(f"[!] не найдено: {q}")
            continue
        if not m.get("modfile"):
            log(f"[orphan] {m['name']!r} (#{m['id']}) — .mod удалён из Workshop, остались только бэкапы")
            log(f"         (очистка: revert_mods.py --list --clean-orphans)")
            orphan_skipped.append(m)
            continue
        if is_excluded(m["name"], m["modfile"]) and not INCLUDE_EXCLUDED:
            skipped_excl.append(m)
        else:
            mods.append(m)
    if not queries:
        # 2026-09-23: «все моды» — по SCOPE (требование пользователя):
        #   ./translate_mods.bat          → ТОЛЬКО Steam Workshop (default)
        #   ./translate_mods.bat --steam  → ТОЛЬКО Steam Workshop (явный)
        #   ./translate_mods.bat --mods   → ТОЛЬКО kenshi\mods\<mod>\*.mod
        #   ./translate_mods.bat --all    → Steam Workshop + kenshi\mods\<mod>\*.mod
        # ВСТРОЕННЫЕ (kenshi\data\*.mod: rebirth/Dialogue/Newwworld) НИКОГДА
        # не в «все» — только по явном имени:
        #   ./translate_mods.bat "rebirth"  "Dialogue"  "Newwworld"
        ws    = [m for m in all_mods if m.get("kind") != "game"]
        gmods = [m for m in all_mods if m.get("kind") == "game" and m.get("gk") == "mods"]
        if SCOPE == "mods":
            pool      = gmods;  scope_lbl = "папка kenshi\\mods"
        elif SCOPE == "all":
            pool      = ws + gmods; scope_lbl = "Steam Workshop + папка kenshi\\mods"
        else:  # None (default) или "steam" — одинаково: Steam Workshop
            pool      = ws;     scope_lbl = "Steam Workshop"
        mods = [m for m in pool
                if m.get("modfile") and not is_excluded(m["name"], m["modfile"])]
        skipped_excl = [m for m in pool
                        if m.get("modfile") and is_excluded(m["name"], m["modfile"])]
        orphan_skipped = [m for m in pool if not m.get("modfile")]
        if orphan_skipped:
            log(f"[orphan] {len(orphan_skipped)} папок(и) без .mod (мод удалён) — пропущено(ы)")
            log(f"         (узнать детали: revert_mods.py --list; чистка: --clean-orphans)")
        n_mods = len([m for m in all_mods if m.get("kind") == "game" and m.get("gk") == "mods"])
        if SCOPE == "mods" and not pool:
            log(f"[!] папка kenshi\\mods\\ пуста или нет мода с .mod — нечего переводить")
        log(f"[i] «все моды» = {scope_lbl}: всего {len(pool) + len(orphan_skipped)}, пройдёт {len(mods)}.")
        if SCOPE in (None, "steam"):
            log(f"    (папка kenshi\\mods: {n_mods} шт. — отдельно: --mods; вместе: --all)")
        log(f"[ ] ВСТРОЕННЫЕ (kenshi\\data\\: rebirth/Dialogue/Newwworld) НИКОГДА не в «все» — "
            f"только по имени: ./translate_mods.bat \"rebirth\"")
    if skipped_excl:
        log(f"[exclude] {EXCL_PATH}: {len(skipped_excl)} пропущено: "
            f"{', '.join(m['name'] for m in skipped_excl[:8])}"
            + (f" ...(+{len(skipped_excl)-8} ещё)" if len(skipped_excl) > 8 else "")
            + ("  (override: --include-excluded)" if not INCLUDE_EXCLUDED else ""))
        if not mods:
            log("    все запрошенные моды в исключениях - используй --include-excluded для принудительного запуска")
    if queries:
        log(f"выбрано: {len(mods)} мод(ов)")
    else:
        if not mods:
            log(f"все моды в выбранной группе ({scope_lbl}) в исключениях — нечего делать")
            return 1
        log(f"[?] список мода не указан. {len(mods)} eligible ({scope_lbl}); {len(skipped_excl)} в исключениях.")
        log("    перевести ВСЕ? Одна LLM-полоса, 200+ модов - долго.")
        ans = input("    Перевести все [y/N]: ").strip().lower()
        if ans not in ("y", "yes", "д", "да"):
            log("    прерываю (ничего не выбрано)")
            return 1
    if not mods:
        log("нечего делать")
        return 1

    log(f"\nконфиг: динам.батч (окно {CONTEXT_WIN} tok, потолок {MAX_BATCH_LN} строк, "
        f"output<= {MAX_OUT_TOK} tok)  min_chunk={MIN_CHUNK}  max_tokens={MAX_TOKENS}  "
        f"model={LLM_MODEL} @ {LLM_BASE}")
    log(f"retry={RETRIES}  force_retranslate={'ON' if FORCE else 'off'}  "
        f"reasoning_effort={REASONING_EFFORT}  temperature={TEMPERATURE}  "
        f"enable_thinking={'ON' if not THINKING_OFF else 'OFF'}")
    log(f"dict={ ('+' + str(len(DICT['exact'])) + ' exact / +' + str(len(DICT['words'])) + ' terms (' + DICT_PATH + ')') if (DICT['exact'] or DICT['words']) else 'off'}")
    log(f"po_hints={'ON' if _PO_HINTS_ENABLED else 'OFF'} (до {_PO_HINTS_MAX} редких пар из {GAME}/locale/ru_RU под текущий чанк)")
    _ps = prefilter.pool_size()
    log(f"prefilter={'ON' if PRE_FILTER_ENABLED else 'OFF'} (пул готовых переводов: {_ps} пар из dict.json/.по игры/кешей модев — reuse вместо LLM)")
    log(f"prompt: {PROMPT_FILE}")
    log(f"state: {STATE}\n")

    ok = fail = 0
    ctx = {"nmods_done": 0, "total_mods": len(mods)}
    t0 = time.time()
    ctx["t_llm"] = 0.0  # accumulated seconds of real LLM work
    import hashlib
    def _cache_filled(m):
        """Кэш есть, если у workshop-файла лежит наш .orig_<h>.backup (перевод уже сделан)
        или в state\\ есть маппинг по md5 файла (ручной/ещё не переведённый)."""
        try:
            src = m["modfile"]
            base = os.path.basename(src)
            d = os.path.dirname(src)
            for f in os.listdir(d):
                if f.startswith(base + ".orig_") and f.endswith(".backup"):
                    h = f[len(base) + 6:-len(".backup")]
                    if os.path.isfile(os.path.join(STATE, h + "_mapping.json")):
                        return True
            h = hashlib.md5(open(src, "rb").read()).hexdigest()[:12]
            return os.path.exists(os.path.join(STATE, f"{h}_mapping.json"))
        except Exception:
            return False
    need_llm = sum(1 for m in mods if not _cache_filled(m))
    if need_llm:
        log(f"  (первый запуск: {need_llm} мод(ов) нужны LLM, {len(mods)-need_llm} из кеша)")

    # 2026-09-21: PROBE LLM-сервера ДО старта. Если LLM нужен (есть недоделанные
    # строки) и сервер из config.json недоступен — не сжигать время на ретраи,
    # а сразу сказать пользователю и предложить --no-llm (только CSV, без ИИ).
    if need_llm and not NO_LLM:
        import urllib.request, urllib.error
        # Пробуем GET <base>/models: живой сервер ОТВЕТИТ (2xx/4xx),
        # мёртвый — ConnectionRefused/timeout. Любой HTTP-ответ = сервер жив.
        probe_target = LLM_BASE.rstrip("/") + "/models"
        down = False
        err = ""
        try:
            headers = {"Accept": "application/json"}
            if LLM_KEY:
                headers["Authorization"] = "Bearer " + LLM_KEY
            req = urllib.request.Request(probe_target, headers=headers)
            with urllib.request.urlopen(req, timeout=8) as r:
                pass  # 2xx — сервер жив
        except urllib.error.HTTPError as he:
            err = f"HTTP {he.code} (сервер отвечает — продолжаю)"  # жив, просто нет /models или нет ключа
        except Exception as ex:
            down = True
            err = str(ex)
        if down:
            log(f"\n[!] LLM-сервер НЕДОСТУПЕН: {LLM_BASE}  ({err})")
            log(f"    model: {LLM_MODEL}")
            log(f"    Без ИИ нечем переводить — {need_llm} мод(ов) ждут перевода.")
            try:
                ans = input("    Продолжить в режиме --no-llm (только CSV, переведёшь сам)? [y/N]: ").strip().lower()
            except EOFError:
                ans = "y"
            if ans in ("y", "д", "да", "yes"):
                globals()["NO_LLM"] = True
                log("    -> переключаюсь на --no-llm: создам только CSV-файлы (0 запросов к LLM)")
            else:
                log("    прерываю. Запусти: translate_mods.bat --no-llm <моды>  (или подними LLM-сервер)")
                return 1
        elif err:
            log(f"  (LLM-проба: {err})")


    # Enter Progress context (two tqdm bars live here)
    with Progress(len(mods)) as PR:
        PROGRESS["progress"] = PR
        try:
            for n, m in enumerate(mods, 1):
                try:
                    r = translate_one(m, n, len(mods), ctx)
                    ctx["nmods_done"] = n
                    if r:
                        ok += 1
                    else:
                        fail += 1
                except Exception as ex:
                    log(f"  [ERROR MOD] {ex}")
                    fail += 1
                PR.finish_mod()
                dt = time.time() - t0
                remaining = mods[n:]
                llm_left = sum(1 for m in remaining if not _cache_filled(m))
                if ctx["t_llm"] > 0 and llm_left:
                    eta = (ctx["t_llm"] / max(n, 1)) * llm_left
                else:
                    eta = 0
                def fmt_eta(sec):
                    if sec is None: return "--"
                    m2, s2 = divmod(int(sec), 60)
                    if m2 >= 60: return f"{m2//60}h{m2%60:02d}m"
                    return f"{m2}m{s2:02d}s"
                log(f"  => global {n}/{len(mods)}  elapsed {fmt_eta(dt)}  "
                    f"~left {fmt_eta(eta)} ({llm_left} need LLM, {len(remaining)-llm_left} cached)")
        except KeyboardInterrupt:
            log("\nостановлено пользователем (Ctrl+C). Прогресс сохранён - перезапусти ту же команду для resume.")
            return 130
        log(f"=== DONE: ok={ok}  fail={fail}  total={len(mods)}  elapsed {time.time()-t0:.0f}s ===")
    PROGRESS["progress"] = None
    log(f"state/cache: {STATE}")
    return 0 if fail == 0 else 3

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nпрервано пользователем")
        sys.exit(130)
