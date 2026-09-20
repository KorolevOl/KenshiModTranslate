"""Канонический резолвер путей из config.json.

Правило: относительные пути из config.json — относительные к ПАПКЕ ПРОЕКТА
(каталог, где лежит config.json / .py), а НЕ к текущему CWD. Абсолютные не трогаем.

Так `state` = "state", `modtranslate_cli` = "bin/Release/...dll", `dotnet` =
"../dotnet9/dotnet.exe" работают одинаково из любого CWD и из любого .bat.
"""
import os
import json

_HERE = os.path.dirname(os.path.abspath(__file__))


def config_dir() -> str:
    return _HERE


def load_config() -> dict:
    with open(os.path.join(_HERE, "config.json"), encoding="utf-8") as f:
        return json.load(f)


def resolve(path: str) -> str:
    """Относительный → абсолютный (относительно папки проекта).
    Absolute / пустой → как есть."""
    if not path:
        return path
    if os.path.isabs(path):
        return path
    return os.path.normpath(os.path.join(_HERE, path))


def paths(cfg: dict) -> dict:
    """Вернуть блок paths с уже распущенными (абсолютными) путями."""
    raw = cfg.get("paths", {})
    return {k: resolve(v) for k, v in raw.items()}
