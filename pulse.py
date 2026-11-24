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


def desktop_dir():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders") as k:
            return winreg.QueryValueEx(k, "Desktop")[0]
    except OSError:
        return os.path.join(os.environ.get("USERPROFILE", ""), "Desktop")


def install():
    import winreg
    cmd = f'"{pythonw()}" "{os.path.join(BASE, "pulse.py")}"'
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, cmd)
    print("Pulse will now start automatically when you sign in to Windows.")
    shortcut = os.path.join(desktop_dir(), "Pulse.url")
    try:
        with open(shortcut, "w", encoding="utf-8") as f:
            f.write(f"[InternetShortcut]\nURL={url()}\n")
        print(f"Desktop shortcut: {shortcut}")
    except OSError as e:
        print(f"Could not create the desktop shortcut ({e}). Bookmark {url()} instead.")
    if not is_running():
        print("Starting Pulse in the background...")
        if not start_background():
            print(f"Pulse didn't answer. Check {os.path.join(DATA, 'pulse.log')}")
            return
    print(f"Pulse is running. Dashboard: {url()}")
    webbrowser.open(url())


def uninstall():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, APP_NAME)
        print("Pulse will no longer start with Windows. Your history in data/pulse.db is kept.")
    except FileNotFoundError:
        print("Pulse was not set to start with Windows.")
    stop()


def stop():
    try:
        req = urllib.request.Request(url() + "api/quit", data=b"{}", method="POST",
                                     headers={"X-Pulse": "1", "Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=3)
        print("Pulse stopped.")
    except Exception:
        print("Pulse wasn't running.")


def open_dashboard():
    if not is_running():
        start_background()
    webbrowser.open(url())


def run():
    os.makedirs(DATA, exist_ok=True)
    handler = RotatingFileHandler(os.path.join(DATA, "pulse.log"), maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, handlers=[handler],
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    log = logging.getLogger("pulse")

    # one copy at a time
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    mutex = kernel32.CreateMutexW(None, False, "Local\\PulseActivityTracker")
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        log.info("another Pulse is already running; exiting")
        print(f"Pulse is already running: {url()}")
        return

    from categorize import Rules
    from report import init_db
    from server import make_server
    from tracker import Tracker, HAVE_UIA
    from tray import Tray
    from wellbeing import Limits, Monitor, fmt

    init_db(DB_PATH)
    rules = Rules()
    limits = Limits()
    tracker = Tracker(DB_PATH, rules)
    tracker.start()

    httpd = None
    monitor = None

    def quit_all():
        tracker.stop()
        if monitor:
            monitor.stop()
        tray.stop()
        tracker.join(timeout=5)
        if httpd:
            httpd.shutdown()

    def toggle_pause():
        tracker.paused = not tracker.paused

    def menu_status():
        u = monitor.today_usage if monitor else None
        return f"Today {fmt(u['total'])}  ·  Focus {fmt(u['focus'])}" if u else None

    tray = Tray(url(), DATA, menu_status, lambda: tracker.paused, toggle_pause, quit_all)
    tray.start()
    tray.ready.wait(5)
    tray.on_idle_answer = tracker.answer     # buttons on the "Still there?" card
    tracker.prompt = tray

    try:
        httpd = make_server(port(), DB_PATH, rules, tracker, quit_all, limits, tray.notify)
    except OSError as e:
        log.error("port %s is busy (%s). Change \"port\" in rules.json.", port(), e)
        print(f"Port {port()} is busy. Change \"port\" in rules.json.")
        tracker.stop()
        tray.stop()
        return
    monitor = Monitor(DB_PATH, rules, limits, tracker, tray, url())
    monitor.start()
    log.info("Pulse started on %s (browser URLs: %s)", url(), "on" if HAVE_UIA else "title-only")
    print(f"Pulse is tracking. Dashboard: {url()}  (Ctrl+C to stop)")
    try:
        httpd.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        tracker.stop()
        monitor.stop()
        tray.stop()
        tracker.join(timeout=5)
        log.info("Pulse stopped")
    _ = mutex


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    {"--install": install, "--uninstall": uninstall, "--stop": stop, "--open": open_dashboard}.get(arg, run)()
