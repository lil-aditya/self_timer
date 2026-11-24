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


def week_insights(events, prev_events, days):
    out = []
    total = sum(e["d"] for e in events)
    if not total:
        return out, {}
    prev_total = sum(e["d"] for e in prev_events)
    focus = sum(e["d"] for e in events if e["cat"] in PRODUCTIVE)
    prev_focus = sum(e["d"] for e in prev_events if e["cat"] in PRODUCTIVE)
    fmt = _fmt

    if prev_total:
        diff = total - prev_total
        pct = round(abs(diff) / prev_total * 100)
        out.append({"title": "Screen time " + ("up" if diff > 0 else "down"), "tone": "bad" if diff > 0 else "good",
                    "text": f"{fmt(total)} this week, {fmt(abs(diff))} {'more' if diff > 0 else 'less'} than the week before ({pct}%)."})
    else:
        out.append({"title": "Screen time", "tone": "neutral",
                    "text": f"{fmt(total)} this week. Next week you'll see how it compares."})

    share = round(focus / total * 100)
    if prev_total:
        pshare = round(prev_focus / prev_total * 100)
        out.append({"title": "Focus share", "tone": "good" if share >= pshare else "bad",
                    "text": f"{share}% of your screen time was focused work, against {pshare}% the week before."})
    else:
        out.append({"title": "Focus share", "tone": "neutral", "text": f"{share}% of your screen time was focused work."})

    cats, pcats = {}, {}
    for e in events:
        _add(cats, e["cat"], e["d"])
    for e in prev_events:
        _add(pcats, e["cat"], e["d"])
    if prev_total:
        movers = sorted(((c, cats.get(c, 0) - pcats.get(c, 0)) for c in CATEGORIES
                         if max(cats.get(c, 0), pcats.get(c, 0)) >= 1800), key=lambda kv: -abs(kv[1]))
        for c, delta in movers[:2]:
            if abs(delta) >= 900:
                good = (delta > 0) == (c in PRODUCTIVE)
                out.append({"title": f"{c} {'up' if delta > 0 else 'down'}", "tone": "good" if good else "bad",
                            "text": f"{c} took {fmt(cats.get(c, 0))}, {fmt(abs(delta))} {'more' if delta > 0 else 'less'} than the week before."})

    # best focus day, and the longest streak of the week
    per_day = {}
    for e in events:
        if e["cat"] in PRODUCTIVE:
            _add(per_day, time.strftime("%Y-%m-%d", time.localtime(e["t0"])), e["d"])
    if per_day:
        best_day, secs = max(per_day.items(), key=lambda kv: kv[1])
        out.append({"title": "Best focus day", "tone": "neutral",
                    "text": f"{date.fromisoformat(best_day).strftime('%A')}, with {fmt(secs)} of focused work."})
    streak, start = longest_streak(events)
    if streak >= 600:
        out.append({"title": "Longest focus session", "tone": "neutral",
                    "text": f"{fmt(streak)} on {time.strftime('%A from %I:%M %p', time.localtime(start)).replace(' 0', ' ')}."})

    hours = by_hour_of_day(events)
    fh = max(range(24), key=lambda h: sum(v for c, v in hours[h].items() if c in PRODUCTIVE))
    dh = max(range(24), key=lambda h: sum(v for c, v in hours[h].items() if c in DISTRACTING))
    label = lambda h: f"{(h % 12) or 12} {'AM' if h < 12 else 'PM'}"
    if sum(v for c, v in hours[fh].items() if c in PRODUCTIVE) > 0:
        out.append({"title": "Your focus hour", "tone": "neutral",
                    "text": f"You get the most focused work done around {label(fh)}."})
    if sum(v for c, v in hours[dh].items() if c in DISTRACTING) >= 900:
        out.append({"title": "Distraction peak", "tone": "neutral",
                    "text": f"Entertainment and social media peak around {label(dh)}."})

    # late nights: activity between midnight and 5 AM
    nights, latest = set(), None
    for e in events:
        lt = time.localtime(e["t1"] - 1)
        if lt.tm_hour < 5:
            nights.add(time.strftime("%Y-%m-%d", lt))
            mins = lt.tm_hour * 60 + lt.tm_min
            if latest is None or mins > latest[0]:
                latest = (mins, e["t1"])
    if nights:
        out.append({"title": "Late nights", "tone": "bad" if len(nights) >= 3 else "neutral",
                    "text": f"On your laptop after midnight on {len(nights)} of 7 nights; the latest was "
                            f"{time.strftime('%I:%M %p', time.localtime(latest[1])).lstrip('0')}."})

    compare = {c: {"now": round(cats.get(c, 0)), "prev": round(pcats.get(c, 0))} for c in CATEGORIES
               if cats.get(c, 0) or pcats.get(c, 0)}
    return out, compare


def _fmt(secs):
    secs = int(round(secs))
    if secs < 60:
        return f"{secs}s"
    m = round(secs / 60)
    if m < 60:
        return f"{m}m"
    h, r = divmod(m, 60)
    return f"{h}h {r}m" if r else f"{h}h"


def export_rows(conn, rules, t0, t1):
    yield ["start", "end", "seconds", "app", "category", "browser", "website", "project_or_window", "title"]
    for e in load_events(conn, t0, t1, rules):
        yield [time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(e["t0"])),
               time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(e["t1"])),
               round(e["d"]), e["app"], e["cat"], e["browser"] or "", e["site_name"] or "",
               "" if e["browser"] else e["detail"], e["page"]]


def summarize(events, rules=None):
    total = sum(e["d"] for e in events)
    cats = {c: 0.0 for c in CATEGORIES}
    apps, sites = {}, {}
    for e in events:
        cats[e["cat"]] += e["d"]
        a = apps.setdefault(e["app"], {"name": e["app"], "exe": e["exe"], "secs": 0.0, "browser": bool(e["browser"]),
                                       "cats": {}, "details": {}, "detail_cat": {}, "pages": defaultdict(dict)})
        a["secs"] += e["d"]
        _add(a["cats"], e["cat"], e["d"])
        _add(a["details"], e["detail"], e["d"])
        a["detail_cat"][e["detail"]] = e["cat"]
        if e["page"] and e["page"] != e["detail"]:
            _add(a["pages"][e["detail"]], e["page"], e["d"])
        if e["browser"]:
            sk = e["site"] or ""
            s = sites.setdefault(sk, {"key": e["site"], "name": e["site_name"], "secs": 0.0, "cats": {},
                                      "browsers": {}, "pages": {}})
            s["secs"] += e["d"]
            _add(s["cats"], e["cat"], e["d"])
            _add(s["browsers"], e["browser"], e["d"])
            if e["page"] and e["page"] != e["site_name"]:
                _add(s["pages"], e["page"], e["d"])

    app_list = []
    for a in sorted(apps.values(), key=lambda x: -x["secs"]):
        details = []
        for name, secs in sorted(a["details"].items(), key=lambda kv: -kv[1])[:12]:
            details.append({"name": name, "secs": round(secs), "cat": a["detail_cat"][name],
                            "pages": _top(a["pages"].get(name, {}), 5) if a["browser"] else []})
        app_list.append({
            "name": a["name"], "exe": a["exe"], "secs": round(a["secs"]), "browser": a["browser"],
            "cat": max(a["cats"].items(), key=lambda kv: kv[1])[0], "cats": {k: round(v) for k, v in a["cats"].items()},
            "details": details,
        })
    site_list = []
    for s in sorted(sites.values(), key=lambda x: -x["secs"]):
        site_list.append({
            "key": s["key"], "name": s["name"], "secs": round(s["secs"]),
            # the site's own category (what the dropdown changes); title rules may still split its time
            "cat": (rules.site_category(s["key"]) if rules and s["key"] else None)
                   or max(s["cats"].items(), key=lambda kv: kv[1])[0],
            "cats": {k: round(v) for k, v in s["cats"].items()},
            "browsers": _top(s["browsers"], 6), "pages": _top(s["pages"], 6),
        })

    switches = sum(1 for a, b in zip(events, events[1:]) if a["app"] != b["app"])
    longest, _ = longest_streak(events)
    return {
        "total": round(total),
        "categories": {k: round(v) for k, v in cats.items()},
        "focus": round(sum(cats[c] for c in PRODUCTIVE)),
        "distraction": round(sum(cats[c] for c in DISTRACTING)),
        "longest_focus": round(longest),
        "switches": switches,
        "first": events[0]["t0"] if events else None,
        "last": events[-1]["t1"] if events else None,
        "apps": app_list,
        "sites": site_list,
    }
