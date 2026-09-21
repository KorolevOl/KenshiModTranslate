# -*- coding: utf-8 -*-
"""
install.py — one-click installer для KenshiModTranslate.

Что делает (в этом порядке, с понятными сообщениями):
  1. Проверяет наличие Python (всегда есть — запускать через него)
  2. Ставит зависимости из requirements.txt (tqdm)
  3. Проверяет .NET 9 Desktop Runtime (открывает страницу д/л если нет)
  4. Авто-находит каталог Kenshi и Workshop content/233860 (по 6 типовым
     местам на дисках C..G) и вписывает их в config.json
  5. Печатает итог: «готово, запускайте translate_mods.bat»

Безопасность:
  - ничего не удаляет, только дописывает поля в config.json
  - если каталоги не найдены — не падает, а просит заполнить вручную
  - идемпотентен: повторный запуск безопасно перепишет те же значения

Использование:
  python install.py          # все проверки + setup
  python install.py --check  # только проверки (не правит config.json)
  python install.py --skip-net  # не проверять .NET (если известно, что есть)
"""

import json
import os
import platform
import shutil
import stat
import subprocess
import sys
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "config.json"

# 6 типовых мест Steam на Windows (по популярности)
STEAM_ROOTS = [
    r"C:\Program Files (x86)\Steam",
    r"C:\Program Files\Steam",
    r"C:\SteamLibrary",
    r"C:\steamlibrary",
    r"C:\Games\SteamLibrary",
    r"C:\ProgramData\Steam",
]
for d in "CDEFG":
    for base in [
        rf"{d}:\Program Files (x86)\Steam",
        rf"{d}:\Program Files\Steam",
        rf"{d}:\SteamLibrary",
        rf"{d}:\steamlibrary",
        rf"{d}:\Games\SteamLibrary",
        rf"{d}:\ProgramData\Steam",
        rf"{d}:\Steam",
    ]:
        if base not in STEAM_ROOTS:
            STEAM_ROOTS.append(base)


def ok(msg): print(f"  [ OK ] {msg}")
def bad(msg): print(f"  [ !! ] {msg}")
def info(msg): print(f"  [..] {msg}")


def step_python():
    print("\n[1/4] Python")
    ver = platform.python_version()
    major, minor = (int(x) for x in ver.split(".")[:2])
    if (major, minor) < (3, 10):
        bad(f"Python {ver} — нужен 3.10+")
        return False
    ok(f"Python {ver}")
    # зависимости
    if not _have("tqdm"):
        info("устанавливаю tqdm ...")
        r = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--quiet",
             "--disable-pip-version-check", "-r", str(ROOT / "requirements.txt")],
            cwd=str(ROOT),
        )
        if r.returncode != 0:
            bad("pip install не удался. Попробуйте вручную: python -m pip install tqdm")
            return False
        ok("tqdm установлена")
    else:
        ok("tqdm уже установлена")
    return True


def _have(module):
    try:
        __import__(module)
        return True
    except ImportError:
        return False


LOCAL_DOTNET_DIR = ROOT / "dotnet-local"   # автоскачанный рантайм (без админа)


def _find_dotnet():
    """Поиск dotnet.exe: 1) config.json, 2) dotnet-local/ (автоскачан), 3) PATH, 4) Program Files."""
    try:
        d = json.loads(CONFIG.read_text(encoding="utf-8"))
        rel = (d.get("paths") or {}).get("dotnet")
        if rel:
            cand = Path(rel) if os.path.isabs(rel) else (ROOT / rel)
            if cand.exists():
                return str(cand), "config.json"
    except Exception:
        pass
    cand = LOCAL_DOTNET_DIR / "dotnet.exe"
    if cand.exists():
        return str(cand), "dotnet-local/ (автоскачан)"
    exe = shutil.which("dotnet")
    if exe:
        return exe, "PATH"
    cand = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "dotnet" / "dotnet.exe"
    if cand.exists():
        return str(cand), "Program Files"
    return None, None


def _has_desktop9(exe):
    try:
        out = subprocess.run([str(exe), "--list-runtimes"],
                             capture_output=True, text=True, timeout=15).stdout
    except Exception:
        return False
    return any(l.startswith("Microsoft.WindowsDesktop.App 9.") for l in out.splitlines())


def _install_dotnet_local():
    """Скачивает .NET Desktop Runtime 9 (x64, ~50 МБ) в <проект>\dotnet-local — без админ-прав."""
    info("скачиваю .NET Desktop Runtime 9 в папку проекта (~50 МБ, без админ-прав) ...")
    cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
           "iex (irm 'https://builds.dotnet.microsoft.com/dotnet/scripts/v1/dotnet-install.ps1') "
           f"-Channel 9.0 -Runtime dotnet -InstallDir '{LOCAL_DOTNET_DIR}'"]
    r = subprocess.run(cmd, timeout=1200)
    exe = LOCAL_DOTNET_DIR / "dotnet.exe"
    return (r.returncode == 0) and exe.exists() and _has_desktop9(exe)


def step_dotnet(apply=True):
    print("\n[2/4] .NET 9 Desktop Runtime")
    dotnet, source = _find_dotnet()
    if not dotnet and apply:
        bad(".NET runtime не найден в системе")
        try:
            ask = input("  Скачаю автоматически в папку проекта (~50 МБ)? [Y/n] ").strip().lower()
        except EOFError:
            ask = "y"
        if ask in ("", "y", "yes", "да"):
            if _install_dotnet_local():
                ok(f"установлено в {LOCAL_DOTNET_DIR}")
                dotnet, source = str(LOCAL_DOTNET_DIR / "dotnet.exe"), "dotnet-local/ (автоскачан)"
                _global_dotnet_path = dotnet
                return True
            bad("автоскачивание не удалось — установите вручную: https://dotnet.microsoft.com/download/dotnet/9.0")
        return False
    if not dotnet:
        bad(".NET runtime не найден (режим --check: ничего не устанавливаю)")
        info("нужен «.NET Desktop Runtime 9» (x64): https://dotnet.microsoft.com/download/dotnet/9.0")
        return False
    if not _has_desktop9(dotnet):
        # есть dotnet, но без 9.x → попробуем автоскачать локальный
        bad("есть .NET, но нет WindowsDesktop.App 9.x")
        if apply:
            if _install_dotnet_local():
                ok(f"дополнительно установлено в {LOCAL_DOTNET_DIR}")
                _global_dotnet_path = str(LOCAL_DOTNET_DIR / "dotnet.exe")
                return True
        return False
    ok(f"найдён (.NET 9 Desktop Runtime, источник: {source})")
    _global_dotnet_path = dotnet
    return True


_global_dotnet_path = None


def _try_open(url):
    try:
        webbrowser.open(url)
    except Exception:
        pass


def find_kenshi():
    """Ищем каталог Kenshi (kenshi.exe или kenshi_x64.exe) и рядом workshop/content/233860."""
    for root in STEAM_ROOTS:
        p = Path(root)
        kdir = p / "steamapps" / "common" / "kenshi"
        if not kdir.is_dir():
            continue
        if (kdir / "kenshi.exe").exists() or (kdir / "kenshi_x64.exe").exists():
            wdir = p / "steamapps" / "workshop" / "content" / "233860"
            return str(kdir), str(wdir)
    return None, None


def step_paths(apply=True):
    print("\n[3/4] Путь к игре и к Workshop-модам")
    kdir, wdir = find_kenshi()
    if not kdir:
        bad("Kenshi не найден в типовых местах Steam")
        info("вручную заполните в config.json блок paths.game и paths.workshop")
        return False
    ok(f"игра:     {kdir}")
    ok(f"workshop: {wdir}")
    if not apply:
        return True
    # читаем config
    d = json.load(open(CONFIG, encoding="utf-8"))
    d.setdefault("paths", {})
    prev_game = d["paths"].get("game")
    prev_w = d["paths"].get("workshop")
    d["paths"]["game"] = kdir
    d["paths"]["workshop"] = wdir
    # dotnet в конфиге: не затираем, если текущий уже годный (9.x runtime внутри)
    existing_dotnet = d["paths"].get("dotnet")
    existing_ok = False
    if existing_dotnet:
        cand = Path(existing_dotnet) if os.path.isabs(existing_dotnet) else (ROOT / existing_dotnet)
        existing_ok = cand.is_file() and _has_desktop9(cand)
    if existing_ok:
        ok(f"dotnet уже в config: {existing_dotnet} (годный, не трогаю)")
    elif _global_dotnet_path:
        d["paths"]["dotnet"] = _global_dotnet_path
        ok(f"dotnet прописан в config: {_global_dotnet_path}")
    tmp = CONFIG.with_suffix(".json.tmp")
    json.dump(d, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    os.replace(tmp, CONFIG)  # атомарная замена
    changed = []
    if prev_game != kdir: changed.append("game")
    if prev_w != wdir: changed.append("workshop")
    if changed:
        ok(f"config.json обновлён: {', '.join(changed)}")
    else:
        ok("config.json уже имел эти пути, ничего не менял")
    return True


def step_final():
    print("\n[4/4] Финальные проверки")
    # 1) DLL в репо
    dll = ROOT / "bin" / "Release" / "net9.0-windows" / "kenshi-modtranslate.dll"
    if dll.exists():
        ok(f"kenshi-modtranslate.dll — {dll}")
    else:
        bad(f"нет {dll}. Это критично — DLL должна быть в репозитории!")
        return False
    # 2) ключевые файлы
    req = ["translate_mods.bat", "translate_mods.py", "config.json", "prompt.txt",
           "dict.json", "kenshi-modtranslate.csproj", "Program.cs"]
    missing = [f for f in req if not (ROOT / f).exists()]
    if missing:
        bad(f"не хватает файлов в корне проекта: {missing}")
        return False
    ok(f"ключевые файлы ({len(req)}) на месте")
    return True


def main():
    check_only = "--check" in sys.argv
    skip_net = "--skip-net" in sys.argv

    print("=" * 60)
    print("  Kenshi RU Mod Translate — установка")
    print("=" * 60)
    print(f"  Каталог проекта: {ROOT}")
    print(f"  Python:          {platform.python_version()} ({sys.executable})")

    results = []
    results.append(("Python + tqdm", step_python()))
    if not skip_net:
        results.append((".NET 9 Desktop Runtime", step_dotnet(apply=not check_only)))
    results.append(("Пути (game/workshop)", step_paths(apply=not check_only)))
    results.append(("Ключевые файлы", step_final()))

    print("\n" + "=" * 60)
    print("  ИТОГ")
    print("=" * 60)
    all_ok = True
    for name, ok_flag in results:
        mark = "OK" if ok_flag else "FAIL"
        print(f"   [{mark}] {name}")
        all_ok = all_ok and ok_flag

    print()
    if all_ok:
        print("  Установлено. Можно запускать:")
        print()
        print("     double-click:   translate_mods.bat")
        print()
    else:
        print("  Есть проблемы. Прочитайте сообщения выше, устраните и")
        print("  повторяйте:  python install.py")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
