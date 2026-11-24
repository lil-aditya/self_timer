"""Daily limits, a daily focus goal, nudges when you go over, and the Sunday weekly-report reminder."""
import json
import logging
import os
import sqlite3
import threading
import time
import uuid
from datetime import date, datetime, timedelta

import report
from categorize import CATEGORIES, DATA

log = logging.getLogger("pulse.wellbeing")
LIMITS_PATH = os.path.join(DATA, "limits.json")
STATE_PATH = os.path.join(DATA, "state.json")
KINDS = ("site", "app", "category", "goal")


def fmt(secs):
    secs = int(round(secs))
    if secs < 60:
        return f"{secs}s"
    m = round(secs / 60)
    if m < 60:
        return f"{m}m"
    h, r = divmod(m, 60)
    return f"{h}h {r}m" if r else f"{h}h"


def _read_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


class Limits:
    def __init__(self):
        self._lock = threading.Lock()
        self.items = _read_json(LIMITS_PATH, [])

    def all(self):
        with self._lock:
            return [dict(x) for x in self.items]

    def set(self, kind, key, label, minutes):
        if kind not in KINDS:
            raise ValueError("kind must be one of " + ", ".join(KINDS))
        if kind == "goal":
            key, label = "focus", "Focus"
        if kind == "category" and key not in CATEGORIES:
            raise ValueError("unknown category")
        if not key:
            raise ValueError("pick what to limit")
        key = str(key).lower() if kind in ("site", "app") else key
        with self._lock:
            self.items = [x for x in self.items if not (x["kind"] == kind and x["key"] == key)]
            if minutes and float(minutes) > 0:
                self.items.append({"id": uuid.uuid4().hex[:8], "kind": kind, "key": key,
                                   "label": (label or key)[:60], "minutes": int(float(minutes))})
            _write_json(LIMITS_PATH, self.items)
