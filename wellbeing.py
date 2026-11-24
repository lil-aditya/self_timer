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


def used_for(limit, u):
    kind, key = limit["kind"], limit["key"]
    if kind == "goal":
        return u["focus"]
    if kind == "category":
        return u["cats"].get(key, 0)
    if kind == "site":
        return u["sites"].get(key, 0)
    return u["apps"].get(key, 0)


def limit_status(limit, used):
    cap = limit["minutes"] * 60
    if limit["kind"] == "goal":
        return {"state": "done" if used >= cap else "progress",
                "text": "Goal reached" if used >= cap else f"{fmt(cap - used)} to go"}
    if used >= cap:
        return {"state": "over", "text": f"Over by {fmt(used - cap)}" if used - cap >= 60 else "Limit reached"}
    if used >= cap - min(5 * 60, cap * 0.2):
        return {"state": "near", "text": f"{fmt(cap - used)} left"}
    return {"state": "ok", "text": f"{fmt(cap - used)} left"}


class Monitor(threading.Thread):
    """Every few seconds: keep the tray icon and tooltip current.
    Every 30 seconds: check limits and the focus goal and send notifications."""

    def __init__(self, db_path, rules, limits, tracker, tray, url):
        super().__init__(name="monitor", daemon=True)
        self.db_path, self.rules, self.limits = db_path, rules, limits
        self.tracker, self.tray, self.url = tracker, tray, url
        self.stop_event = threading.Event()
        self.state = _read_json(STATE_PATH, {})
        self.today_usage = None

    def stop(self):
        self.stop_event.set()

    def run(self):
        conn = sqlite3.connect(self.db_path, timeout=10)
        last_heavy, last_prune = 0.0, 0.0
        while not self.stop_event.is_set():
            now = time.time()
            try:
                if self.tray:
                    self.tray.set_icon("paused" if self.tracker.paused else "active")
                if now - last_heavy >= 30:
                    last_heavy = now
                    self.check(conn, now)
                if now - last_prune >= 6 * 3600:
                    last_prune = now
                    self.prune(conn)
            except Exception:
                log.exception("monitor tick failed")
            self.stop_event.wait(5)
        conn.close()

    # ---- helpers -----------------------------------------------------------------
    def _save(self):
        _write_json(STATE_PATH, self.state)

    def _notify(self, title, text, url=None):
        if self.tray:
            self.tray.notify(title, text, url)

    def _current(self):
        st = self.tracker.state()
        if st.get("status") != "tracking" or not st.get("exe"):
            return None
        info = self.rules.enrich(st["exe"], st["app"], st["title"], st["host"], st["browser"])
        return {"exe": st["exe"], "site": info["site"], "cat": info["cat"]}

    def _active_on(self, limit, cur):
        if not cur:
            return False
        k = limit["kind"]
        return ((k == "site" and cur["site"] == limit["key"]) or (k == "app" and cur["exe"] == limit["key"])
                or (k == "category" and cur["cat"] == limit["key"]))
