"""cli.py — единый запущик C# CLI (kenshi-modtranslate.dll).

До этого в проекте было ДУЕ wrapper'ов:
  * translate_mods.run_dotnet(args) -> returns CompletedProcess (raises on non-zero)
  * overlay.run_cli(args)           -> returns (rc, stdout+stderr) (no raise)

Один модуль, один стиль (rc+log). Кто хотел exception — оборачивает сам.

Использование (единый вход):
    import cli
    rc, log = cli.run(["extract", modfile, outfile.json])
    rc, log = cli.run(["apply", modfile, mapping.json, out_mod, keepOnly])
    # rc == 0: ok; log = stdout+stderr (utf-8, replace)
    # rc != 0: rc + log

Там же mod_hash + find_mod (единый источник для overlay.py, search_mods.py,
rebuild_mods.py) — раньше было 4 копии.
"""
from __future__ import annotations
import json
import os
import shutil
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import kmt_paths  # noqa: E402
_resolve = kmt_paths.resolve

_CFG = json.load(open(os.path.join(_HERE, "config.json"), encoding="utf-8"))
_P = _CFG.get("paths", {})
DOTNET = _resolve(_P.get("dotnet", "../dotnet9/dotnet.exe"))
CLI = _resolve(_P.get("modtranslate_cli", "bin/Release/net9.0-windows/kenshi-modtranslate.dll"))
WORKSHOP = _resolve(_CFG.get("paths", {}).get("workshop", "E:/SteamLibrary/steamapps/workshop/content/233860"))


def run(args: list[str], timeout: int = 300) -> tuple[int, str]:
    """Запуск C# CLI. Возвращает (rc, log). НЕ падает на rc!=0 — вызывающий решает.

    log — stdout+stderr склеены. rc != 0 — проверять по тексту log.
    timeout — сек; по умолчанию 300 (extract/apply быстрые, но на огромных модах
    лучше не торопиться).
    """
    try:
        r = subprocess.run([DOTNET, CLI] + args,
                           capture_output=True, timeout=timeout, cwd=_HERE)
    except subprocess.TimeoutExpired as e:
        return (1, f"TIMEOUT ({timeout}s): {args}\n" + (e.stderr or b"").decode("utf-8", "replace"))
    out = (r.stdout or b"").decode("utf-8", "replace")
    err = (r.stderr or b"").decode("utf-8", "replace")
    return (r.returncode, out + err)


def run_or_raise(args: list[str], timeout: int = 300) -> str:
    """Как run(), но бросает RuntimeError при rc!=0. Для тех, кто хотел старый run_dotnet."""
    rc, log = run(args, timeout)
    if rc != 0:
        raise RuntimeError(f"dotnet CLI failed (rc={rc}): {log[:2000]}")
    return log


# --- shared helpers (дубль убран, один источник) ---------------------------

def mod_hash(modfile: str, fallback_md5: bool = True) -> str | None:
    """hash EN-бэкапа (.orig_<h>.backup рядом) — совпадает с кэш-именем в state/.

    fallback_md5 (default True) — если .orig_<h>.backup рядом нет, md5(файла)[:12]
    (это поведение было в search_mods._hash_for_mod; overlay не использует фолбэк,
    поэтому в overlay вызов без fallback — но мы просто игнорируем при fallback=True,
    т.к. md5-хэш не используется в overlay-контексте. Для совместимости:
    overlay передаёт fallback_md5=False).
    """
    base = os.path.basename(modfile)
    d = os.path.dirname(modfile)
    try:
        for f in os.listdir(d):
            if f.startswith(base + ".orig_") and f.endswith(".backup"):
                return f[len(base) + 6: len(f) - len(".backup")]
    except (FileNotFoundError, NotADirectoryError):
        pass
    if not fallback_md5:
        return None
    import hashlib
    try:
        with open(modfile, "rb") as fh:
            return hashlib.md5(fh.read()).hexdigest()[:12]
    except OSError:
        return None


def find_mod(query: str) -> list[tuple[str, str, str, str]]:
    """Workshop-моды по id или (части) имени -> [(appid, dir, name, modfile), ...].

    Пропускает имена, заканчивающиеся на 'rus' (кейс-независимо) — это уже
    RU-оверлеи (наши, чужие), не кандидаты на перевод.
    """
    q = (query or "").strip()
    ql = q.lower()
    out = []
    if not os.path.isdir(WORKSHOP):
        return out
    for appid in sorted(os.listdir(WORKSHOP), key=lambda x: int(x) if x.isdigit() else 0):
        d = os.path.join(WORKSHOP, appid)
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            if not f.lower().endswith(".mod"):
                continue
            name = f[:-4]
            if name.lower().endswith("rus"):
                continue
            if appid == q or (ql and (ql in name.lower() or name.lower() in ql)):
                out.append((appid, d, name, os.path.join(d, f)))
    return out
