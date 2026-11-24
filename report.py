"""Reads recorded events and builds the numbers the dashboard shows."""
import sqlite3
import time
from collections import defaultdict
from datetime import date, datetime, timedelta

from categorize import CATEGORIES, DISTRACTING, PRODUCTIVE

SCHEMA = """
CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY,
  t0 REAL NOT NULL, t1 REAL NOT NULL,
  exe TEXT, app TEXT, title TEXT, url TEXT, host TEXT, browser TEXT
);
CREATE INDEX IF NOT EXISTS events_t1 ON events(t1);
CREATE INDEX IF NOT EXISTS events_t0 ON events(t0);
"""

FOCUS_GAP = 120        # seconds of non-focus allowed inside a focus streak
FOCUS_BREAK = 60       # a distraction longer than this ends the streak


def init_db(path):
    conn = sqlite3.connect(path, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


def midnight(d):
    return time.mktime(datetime(d.year, d.month, d.day).timetuple())


def load_events(conn, t0, t1, rules, live=None):
    rows = conn.execute(
        "SELECT t0,t1,exe,app,title,host,browser FROM events WHERE t1>? AND t0<? ORDER BY t0",
        (t0, t1)).fetchall()
    out = []
    for a, b, exe, app, title, host, browser in rows:
        a, b = max(a, t0), min(b, t1)
        if b - a <= 0:
            continue
        info = rules.enrich(exe, app, title, host, browser)
        out.append({"t0": a, "t1": b, "d": b - a, "exe": exe, "app": app, "browser": browser, **info})
    return out


def _add(d, k, v):
    d[k] = d.get(k, 0) + v


def _top(d, n):
    return [{"name": k, "secs": round(v)} for k, v in sorted(d.items(), key=lambda kv: -kv[1])[:n]]


def longest_streak(events):
    """Longest run of focus work, allowing gaps up to FOCUS_GAP and distractions up to FOCUS_BREAK.
    Returns (seconds, start time)."""
    best, best_start = 0.0, None
    start = end = None
    for e in events:
        if e["cat"] in PRODUCTIVE:
            if start is None or e["t0"] - end > FOCUS_GAP:
                start = e["t0"]
            end = e["t1"]
            if end - start > best:
                best, best_start = end - start, start
        elif e["d"] > FOCUS_BREAK:
            start = None
    return best, best_start


def usage(conn, rules, t0, t1):
    """Totals for limits and the tray: by category, site key and exe."""
    u = {"total": 0.0, "focus": 0.0, "cats": {}, "sites": {}, "apps": {}}
    for e in load_events(conn, t0, t1, rules):
        u["total"] += e["d"]
        _add(u["cats"], e["cat"], e["d"])
        _add(u["apps"], e["exe"], e["d"])
        if e["site"]:
            _add(u["sites"], e["site"], e["d"])
        if e["cat"] in PRODUCTIVE:
            u["focus"] += e["d"]
    return u


def by_hour_of_day(events):
    """Seconds per clock hour (0-23), across however many days the events span."""
    hours = [{} for _ in range(24)]
    for e in events:
        a = e["t0"]
        while a < e["t1"]:
            lt = time.localtime(a)
            b = min(e["t1"], a - (lt.tm_min * 60 + lt.tm_sec + (a % 1)) + 3600)
            _add(hours[lt.tm_hour], e["cat"], b - a)
            a = b
    return hours
