"""Serves the dashboard and a small JSON API on 127.0.0.1 only."""
import csv
import io
import json
import logging
import os
import sqlite3
import threading
import time
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from categorize import CATEGORIES, DISTRACTING, PRODUCTIVE, Rules
import report

log = logging.getLogger("pulse.server")
BASE = os.path.dirname(os.path.abspath(__file__))
DASHBOARD = os.path.join(BASE, "dashboard", "index.html")


def make_server(port, db_path, rules: Rules, tracker, on_quit, limits, notify=None):
    from wellbeing import limit_status, used_for

    def limits_payload():
        conn = sqlite3.connect(db_path, timeout=10)
        try:
            u = report.usage(conn, rules, report.midnight(date.today()), time.time())
        finally:
            conn.close()
        out = []
        for lim in limits.all():
            used = used_for(lim, u)
            out.append({**lim, "used": round(used), "status": limit_status(lim, used)})
        order = {"goal": 0, "category": 1, "site": 2, "app": 3}
        out.sort(key=lambda x: (order[x["kind"]], -x["used"]))
        return {"limits": out}

    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    class Handler(BaseHTTPRequestHandler):
        server_version = "Pulse/1.0"

        def log_message(self, fmt, *args):
            log.debug("%s - %s", self.address_string(), fmt % args)

        # -- helpers --
        def _send(self, code, body, ctype="application/json; charset=utf-8"):
            if isinstance(body, (dict, list)):
                body = json.dumps(body, ensure_ascii=False).encode("utf-8")
            elif isinstance(body, str):
                body = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _host_ok(self):
            # blocks DNS-rebinding: only our own address may talk to us
            return self.headers.get("Host", "") in allowed_hosts

        def _parse_date(self, q):
            try:
                return date.fromisoformat(q.get("date", [""])[0])
            except ValueError:
                return date.today()

        # -- routes --
        def do_GET(self):
            if not self._host_ok():
                return self._send(403, {"error": "forbidden host"})
            url = urlparse(self.path)
            q = parse_qs(url.query)
            try:
                if url.path in ("/", "/index.html"):
                    with open(DASHBOARD, "rb") as f:
                        return self._send(200, f.read(), "text/html; charset=utf-8")
                if url.path == "/api/summary":
                    d = self._parse_date(q)
                    view = q.get("view", ["day"])[0]
                    conn = sqlite3.connect(db_path, timeout=10)
                    try:
                        data = report.week_report(conn, rules, d) if view == "week" else report.day_report(conn, rules, d)
                    finally:
                        conn.close()
                    data["today"] = date.today().isoformat()
                    return self._send(200, data)
                if url.path == "/api/now":
                    st = tracker.state()
                    if st.get("exe"):
                        st.update(rules.enrich(st["exe"], st["app"], st["title"], st["host"], st["browser"]))
                    st["now"] = time.time()
                    st["paused"] = tracker.paused
                    return self._send(200, st)
                if url.path == "/api/limits":
                    return self._send(200, limits_payload())
                if url.path == "/api/export.csv":
                    d = self._parse_date(q)
                    days = 7 if q.get("view", ["day"])[0] == "week" else 1
                    first = d - timedelta(days=days - 1)
                    conn = sqlite3.connect(db_path, timeout=10)
                    try:
                        buf = io.StringIO()
                        csv.writer(buf).writerows(report.export_rows(
                            conn, rules, report.midnight(first), report.midnight(d + timedelta(days=1))))
                    finally:
                        conn.close()
                    body = ("﻿" + buf.getvalue()).encode("utf-8")   # BOM so Excel reads it as UTF-8
                    name = f"pulse-{first.isoformat()}" + (f"-to-{d.isoformat()}" if days > 1 else "") + ".csv"
                    self.send_response(200)
                    self.send_header("Content-Type", "text/csv; charset=utf-8")
                    self.send_header("Content-Disposition", f'attachment; filename="{name}"')
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return None
                if url.path == "/api/meta":
                    return self._send(200, {"categories": CATEGORIES, "productive": sorted(PRODUCTIVE),
                                            "distracting": sorted(DISTRACTING)})
                return self._send(404, {"error": "not found"})
            except Exception as e:
                log.exception("GET %s failed", self.path)
                return self._send(500, {"error": str(e)})

        def do_POST(self):
            # The custom header can't be sent cross-site without a CORS preflight we never answer.
            if not self._host_ok() or self.headers.get("X-Pulse") != "1":
                return self._send(403, {"error": "forbidden"})
            url = urlparse(self.path)
            try:
                n = int(self.headers.get("Content-Length", "0") or 0)
                body = json.loads(self.rfile.read(n) or b"{}") if n else {}
                if url.path == "/api/override":
                    rules.set_override(body.get("kind"), body.get("key"), body.get("category"))
                    return self._send(200, {"ok": True})
                if url.path == "/api/limits":
                    limits.set(body.get("kind"), body.get("key"), body.get("label"), body.get("minutes"))
                    return self._send(200, limits_payload())
                if url.path == "/api/test-notification":
                    ok = bool(notify and notify("Pulse notifications work",
                                                "Limit alerts and your weekly report will look like this."))
                    return self._send(200, {"ok": ok})
                if url.path == "/api/pause":
                    tracker.paused = bool(body.get("paused"))
                    return self._send(200, {"ok": True, "paused": tracker.paused})
                if url.path == "/api/reload-rules":
                    rules.load()
                    return self._send(200, {"ok": True})
                if url.path == "/api/quit":
                    self._send(200, {"ok": True})
                    threading.Thread(target=on_quit, daemon=True).start()
                    return None
                return self._send(404, {"error": "not found"})
            except ValueError as e:
                return self._send(400, {"error": str(e)})
            except Exception as e:
                log.exception("POST %s failed", self.path)
                return self._send(500, {"error": str(e)})

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)
