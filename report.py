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
