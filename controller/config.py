from __future__ import annotations

import json
import os


def project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_config(path: str = "config.json") -> dict:
    if not os.path.isabs(path) and not os.path.exists(path):
        path = os.path.join(project_root(), path)
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)
