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
