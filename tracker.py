"""Background loop: once a second, look at the window in front and record it.

Uses only the Win32 API through ctypes. Browser URLs come from the address bar via
Windows UI Automation (the `uiautomation` package); without it, sites are guessed
from the page title.
"""
import ctypes
import ctypes.wintypes as wt
import logging
import os
import sqlite3
import threading
import time
from collections import OrderedDict

from categorize import BROWSERS, KNOWN_APPS, parse_host

log = logging.getLogger("pulse.tracker")

try:
    import uiautomation as auto
    HAVE_UIA = True
except Exception:  # pragma: no cover - optional dependency
    auto = None
    HAVE_UIA = False

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
version = ctypes.WinDLL("version", use_last_error=True)

user32.GetForegroundWindow.restype = wt.HWND
user32.GetWindowTextLengthW.argtypes = [wt.HWND]
user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
user32.GetWindowThreadProcessId.restype = wt.DWORD
kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
kernel32.OpenProcess.restype = wt.HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = [wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)]
kernel32.CloseHandle.argtypes = [wt.HANDLE]
kernel32.GetTickCount.restype = wt.DWORD
version.GetFileVersionInfoSizeW.argtypes = [wt.LPCWSTR, ctypes.POINTER(wt.DWORD)]
version.GetFileVersionInfoW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.c_void_p]
version.VerQueryValueW.argtypes = [ctypes.c_void_p, wt.LPCWSTR, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wt.UINT)]

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
EnumChildProc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
user32.EnumChildWindows.argtypes = [wt.HWND, EnumChildProc, wt.LPARAM]


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wt.UINT), ("dwTime", wt.DWORD)]


def idle_seconds():
    lii = LASTINPUTINFO()
    lii.cbSize = ctypes.sizeof(lii)
    if not user32.GetLastInputInfo(ctypes.byref(lii)):
        return 0.0
    return ((kernel32.GetTickCount() - lii.dwTime) & 0xFFFFFFFF) / 1000.0


def window_title(hwnd):
    n = user32.GetWindowTextLengthW(hwnd)
    if n <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def window_pid(hwnd):
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def process_path(pid):
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return None
    try:
        size = wt.DWORD(1024)
        buf = ctypes.create_unicode_buffer(1024)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return buf.value
    finally:
        kernel32.CloseHandle(h)
    return None


def uwp_child_pid(hwnd, host_pid):
    """Store apps live inside ApplicationFrameHost; the real app is a child window."""
    found = []

    def cb(child, _):
        pid = window_pid(child)
        if pid != host_pid:
            found.append(pid)
            return False
        return True

    user32.EnumChildWindows(hwnd, EnumChildProc(cb), 0)
    return found[0] if found else None


_desc_cache = {}


def file_description(path):
    if path in _desc_cache:
        return _desc_cache[path]
    desc = None
    try:
        size = version.GetFileVersionInfoSizeW(path, None)
        if size:
            buf = ctypes.create_string_buffer(size)
            if version.GetFileVersionInfoW(path, 0, size, buf):
                ptr, ln = ctypes.c_void_p(), wt.UINT()
                langs = []
                if version.VerQueryValueW(buf, r"\VarFileInfo\Translation", ctypes.byref(ptr), ctypes.byref(ln)) and ln.value >= 4:
                    arr = ctypes.cast(ptr, ctypes.POINTER(ctypes.c_ushort))
                    langs.append((arr[0], arr[1]))
                langs += [(0x0409, 0x04B0), (0x0409, 0x04E4)]
                for lang, cp in langs:
                    key = "\\StringFileInfo\\%04x%04x\\FileDescription" % (lang, cp)
                    if version.VerQueryValueW(buf, key, ctypes.byref(ptr), ctypes.byref(ln)) and ln.value:
                        s = ctypes.wstring_at(ptr, ln.value).rstrip("\x00").strip()
                        if s:
                            desc = s
                            break
    except Exception:
        desc = None
    _desc_cache[path] = desc
    return desc


def friendly_name(exe, path):
    if exe in KNOWN_APPS:
        return KNOWN_APPS[exe]
    desc = file_description(path) if path else None
    if desc and len(desc) <= 40:
        return desc
    return os.path.splitext(exe)[0].replace("_", " ").title()


class Tracker(threading.Thread):
    FLUSH_EVERY = 5       # seconds between writes of the open activity's end time
    MAX_GAP = 15          # a pause longer than this (sleep, hibernate) splits the activity

    def __init__(self, db_path, rules, interval=1.0):
        super().__init__(name="tracker", daemon=True)
        self.db_path, self.rules, self.interval = db_path, rules, interval
        self.stop_event = threading.Event()
        self.paused = False
        self._state_lock = threading.Lock()
        self._state = {"status": "starting"}
        self._url_cache = OrderedDict()
        # "Still there?" check
        self.prompt = None          # the tray, once it exists: ask_idle(), hide_idle(), can_prompt()
        self._asking = None         # {"last_input", "deadline", "resumed_at"} while the card is showing
        self._answer = None         # "here" / "away", set from the tray thread
        self._latched = None        # last-input time after "away" or no answer: don't count until new input
        self._confirmed_key = None  # the activity you said "I'm here" to: asked less often while it lasts

    # ---- public --------------------------------------------------------
    def state(self):
        with self._state_lock:
            return dict(self._state)

    def answer(self, ans):
        """Called by the tray when you press a button on the 'Still there?' card."""
        if ans in ("here", "away"):
            self._answer = ans

    # ---- idle handling ------------------------------------------------------
    def _end_prompt(self):
        self._asking = None
        self._answer = None
        if self.prompt:
            self.prompt.hide_idle()

    def _idle_policy(self, snap, idle, now):
        """Returns (action, status, stop_at, resume_at).
        action: 'count' keep recording; 'stop' end the activity at stop_at;
                'split' end it at stop_at and start a new one at resume_at."""
        r = self.rules
        last_input = now - idle
        info = r.enrich(snap["exe"], snap["app"], snap["title"], snap["host"], snap["browser"])
        exempt = r.is_exempt(snap["exe"], snap["host"], snap["url"], snap["title"], info["cat"])
        key = (snap["exe"], snap["title"])
        check = r.idle_check()
        if exempt:
            limit = 60 * r.get("exempt_idle_minutes", 180)
        else:
            limit = 60 * r.get("passive_idle_minutes" if r.is_passive(snap["exe"], snap["host"]) else "idle_minutes", 3)
            if self._confirmed_key == key:
                limit = max(limit, check["confirm"])
        if self._confirmed_key and self._confirmed_key != key:
            self._confirmed_key = None

        # 1. the "Still there?" card is showing
        a = self._asking
        if a:
            ans, self._answer = self._answer, None
            if last_input > a["last_input"] + 0.5 and a["resumed_at"] is None:
                a["resumed_at"] = last_input            # you came back (without answering yet)
            if exempt:                                  # switched into a meeting or test: never leave it up
                self._end_prompt()
                return "count", "tracking", None, None
            if ans == "here":
                self._end_prompt()
                self._confirmed_key = key
                return "count", "tracking", None, None
            if ans == "away" or now >= a["deadline"]:
                self._end_prompt()
                if a["resumed_at"] is not None or ans == "away":
                    # you're back: drop the quiet minutes, carry on from when you returned
                    return "split", "tracking", a["last_input"], a["resumed_at"] or now
                self._latched = a["last_input"]
                return "stop", "idle", a["last_input"], None
            return "count", "asking", None, None

        # 2. after an unanswered card: nothing counts until you touch the mouse or keyboard
        if self._latched is not None:
            if last_input <= self._latched + 0.5:
                return "stop", "idle", self._latched, None
            self._latched = None

        if idle < limit:
            return "count", "tracking", None, None

        # 3. quiet for too long: ask, or (meetings, tests, or no tray) stop quietly
        if not exempt and check["enabled"] and self.prompt and self.prompt.can_prompt():
            self._asking = {"last_input": last_input, "deadline": now + check["answer"], "resumed_at": None}
            self._answer = None
            label = info["site_name"] if snap["browser"] else (
                f'{snap["app"]} · {info["detail"]}' if info["detail"] and info["detail"] != snap["app"] else snap["app"])
            self.prompt.ask_idle(label, idle, self._asking["deadline"])
            return "count", "asking", None, None
        self._latched = last_input
        return "stop", "idle", last_input, None

    def stop(self):
        self.stop_event.set()

    # ---- browser URL -------------------------------------------------------
    def browser_url(self, hwnd, title):
        if not (HAVE_UIA and self.rules.get("read_browser_urls", True)):
            return None
        key = (int(hwnd), title)
        now = time.time()
        hit = self._url_cache.get(key)
        if hit and now - hit[1] < (20 if hit[0] else 3):
            return hit[0]
        url = None
        try:
            win = auto.ControlFromHandle(hwnd)
            edit = win.EditControl(searchDepth=14)
            if edit.Exists(maxSearchSeconds=0.4, searchIntervalSeconds=0.05):
                val = edit.GetValuePattern().Value
                if val and parse_host(val):
                    url = val.strip()[:500]
        except Exception as e:  # window closed mid-read, access denied, etc.
            log.debug("url read failed: %s", e)
        if url is None and hit and hit[0]:
            url = hit[0]      # e.g. you're typing in the address bar; keep the page you were on
        self._url_cache[key] = (url, now)
        self._url_cache.move_to_end(key)
        while len(self._url_cache) > 300:
            self._url_cache.popitem(last=False)
        return url

    # ---- one look at the screen ------------------------------------------
