"""Lesen/Schreiben der JSON-Dateien im Datenspeicher."""
import json
import os
from pathlib import Path

from . import config


def _path(kind: str, name: str) -> Path:
    base = config.STATE if kind == "state" else config.PUBLIC
    return base / f"{name}.json"


def load(kind: str, name: str, default=None):
    p = _path(kind, name)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def save(kind: str, name: str, data) -> None:
    p = _path(kind, name)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    indent = 1 if kind == "public" else None
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=indent, default=str), encoding="utf-8")
    os.replace(tmp, p)
