# -*- coding: utf-8 -*-
"""Small UTF-8-safe helper set for the standalone creative plugin."""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any


def _now_ts() -> float:
    return time.time()


def _single_line(value: Any, limit: int = 500) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[: max(0, int(limit or 0))]


def _path_text(value: Any, limit: int = 1000) -> str:
    text = _single_line(value, limit)
    if not text:
        return ""
    try:
        return str(Path(text))
    except (TypeError, ValueError, OSError):
        return ""


def _safe_int(value: Any, default: int = 0, minimum: int | None = None, maximum: int | None = None) -> int:
    try:
        result = int(float(value))
    except (TypeError, ValueError):
        result = int(default)
    if minimum is not None:
        result = max(int(minimum), result)
    if maximum is not None:
        result = min(int(maximum), result)
    return result


def _safe_float(value: Any, default: float = 0.0, minimum: float | None = None, maximum: float | None = None) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        result = float(default)
    if minimum is not None:
        result = max(float(minimum), result)
    if maximum is not None:
        result = min(float(maximum), result)
    return result


def _text_similarity(left: Any, right: Any) -> float:
    a = re.sub(r"\s+", "", str(left or "")).lower()
    b = re.sub(r"\s+", "", str(right or "")).lower()
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    grams_a = {a[index : index + 2] for index in range(max(0, len(a) - 1))}
    grams_b = {b[index : index + 2] for index in range(max(0, len(b) - 1))}
    return len(grams_a & grams_b) / max(1, len(grams_a | grams_b))
