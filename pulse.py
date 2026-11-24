"""Pulse - know where your laptop time goes.

  python pulse.py              run the tracker + dashboard (what Windows starts at login)
  python pulse.py --open       open the dashboard (starts Pulse in the background if needed)
  python pulse.py --install    start Pulse with Windows, add a desktop shortcut, start it now
  python pulse.py --uninstall  stop starting with Windows (your data is kept)
  python pulse.py --stop       stop the running tracker
"""
import ctypes
import json
import logging
import os
import subprocess
import sys
import time
import urllib.request
import webbrowser
from logging.handlers import RotatingFileHandler

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
DATA = os.path.join(BASE, "data")
DB_PATH = os.path.join(DATA, "pulse.db")
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME = "Pulse"


def port():
    try:
        with open(os.path.join(BASE, "rules.json"), encoding="utf-8") as f:
            return int(json.load(f).get("port", 7317))
    except Exception:
        return 7317


def url():
    return f"http://127.0.0.1:{port()}/"


def pythonw():
    exe = sys.executable
    cand = os.path.join(os.path.dirname(exe), "pythonw.exe")
    return cand if os.path.exists(cand) else exe


def is_running():
    try:
        with urllib.request.urlopen(url() + "api/meta", timeout=1.5) as r:
            return r.status == 200
    except Exception:
        return False


def start_background():
    flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([pythonw(), os.path.join(BASE, "pulse.py")], cwd=BASE, creationflags=flags,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(40):
        if is_running():
            return True
        time.sleep(0.25)
    return False
