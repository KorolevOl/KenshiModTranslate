"""Канонический резолвер путей из config.json.

Правило: относительные пути из config.json — относительные к ПАПКЕ ПРОЕКТА
(каталог, где лежит config.json / .py), а НЕ к текущему CWD. Абсолютные не трогаем.

Так `state` = "state", `modtranslate_cli` = "bin/Release/...dll", `dotnet` =
"../dotnet9/dotnet.exe" работают одинаково из любого CWD и из любого .bat.
"""
import os
import json
import shutil

_HERE = os.path.dirname(os.path.abspath(__file__))


def config_dir() -> str:
    return _HERE


def load_config() -> dict:
    with open(os.path.join(_HERE, "config.json"), encoding="utf-8") as f:
        return json.load(f)


def resolve(path: str) -> str:
    """Относительный → абсолютный (относительно папки проекта).
    Absolute / пустой → как есть.

    Для каталога, который должен содержать исполняемый файл (dotnet.exe и т.п.),
    дополнительно проверяем существование: если файла по config-пути нет,
    пробуем PATH; если и там нет — возвращаем config-путь (чтобы ошибка
    была на месте использования, а не молчаливая).
    """
    if not path:
        return path
    if os.path.isabs(path):
        resolved = path
    else:
        resolved = os.path.normpath(os.path.join(_HERE, path))
    # Fallback: если файла нет, попробуем базовое имя в PATH
    if not os.path.exists(resolved):
        base = os.path.basename(resolved)
        on_path = shutil.which(base)
        if on_path:
            return on_path
    return resolved


def paths(cfg: dict) -> dict:
    """Вернуть блок paths с уже распущенными (абсолютными) путями."""
    raw = cfg.get("paths", {})
    return {k: resolve(v) for k, v in raw.items()}
