"""System-tray icon for Pulse: hover for today's time, click for the dashboard,
right-click for a menu, and Windows notifications for limits and reports.

Pure Win32 through ctypes, so nothing extra to install. The icon is drawn in code.
"""
import ctypes
import ctypes.wintypes as wt
import logging
import math
import os
import struct
import threading
import webbrowser

log = logging.getLogger("pulse.tray")

user32 = ctypes.WinDLL("user32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)

WM_DESTROY, WM_CLOSE, WM_APP = 0x0002, 0x0010, 0x8000
WM_LBUTTONUP, WM_RBUTTONUP, WM_CONTEXTMENU = 0x0202, 0x0205, 0x007B
NIN_BALLOONUSERCLICK = 0x0405
NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_INFO = 0x1, 0x2, 0x4, 0x10
NIIF_USER, NIIF_LARGE_ICON = 0x4, 0x20
MF_STRING, MF_GRAYED, MF_SEPARATOR = 0x0, 0x1, 0x800
TPM_RIGHTBUTTON, TPM_RETURNCMD, TPM_NONOTIFY = 0x2, 0x100, 0x80
IMAGE_ICON, LR_LOADFROMFILE = 1, 0x10
SM_CXSMICON, SM_CYSMICON = 49, 50


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [("cbSize", wt.UINT), ("style", wt.UINT), ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int), ("hInstance", wt.HINSTANCE),
                ("hIcon", wt.HICON), ("hCursor", wt.HANDLE), ("hbrBackground", wt.HBRUSH),
                ("lpszMenuName", wt.LPCWSTR), ("lpszClassName", wt.LPCWSTR), ("hIconSm", wt.HICON)]


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wt.DWORD), ("Data2", wt.WORD), ("Data3", wt.WORD), ("Data4", ctypes.c_ubyte * 8)]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("hWnd", wt.HWND), ("uID", wt.UINT), ("uFlags", wt.UINT),
                ("uCallbackMessage", wt.UINT), ("hIcon", wt.HICON), ("szTip", wt.WCHAR * 128),
                ("dwState", wt.DWORD), ("dwStateMask", wt.DWORD), ("szInfo", wt.WCHAR * 256),
                ("uTimeoutOrVersion", wt.UINT), ("szInfoTitle", wt.WCHAR * 64), ("dwInfoFlags", wt.DWORD),
                ("guidItem", GUID), ("hBalloonIcon", wt.HICON)]


user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.DefWindowProcW.restype = LRESULT
user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
user32.RegisterClassExW.restype = wt.ATOM
user32.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID]
user32.CreateWindowExW.restype = wt.HWND
user32.LoadImageW.argtypes = [wt.HINSTANCE, wt.LPCWSTR, wt.UINT, ctypes.c_int, ctypes.c_int, wt.UINT]
user32.LoadImageW.restype = wt.HANDLE
user32.CreatePopupMenu.restype = wt.HMENU
user32.AppendMenuW.argtypes = [wt.HMENU, wt.UINT, ctypes.c_size_t, wt.LPCWSTR]
user32.SetMenuDefaultItem.argtypes = [wt.HMENU, wt.UINT, wt.UINT]
user32.TrackPopupMenu.argtypes = [wt.HMENU, wt.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.HWND, wt.LPVOID]
user32.TrackPopupMenu.restype = ctypes.c_int
user32.DestroyMenu.argtypes = [wt.HMENU]
user32.GetCursorPos.argtypes = [ctypes.POINTER(wt.POINT)]
user32.SetForegroundWindow.argtypes = [wt.HWND]
user32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.DestroyWindow.argtypes = [wt.HWND]
user32.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT]
user32.TranslateMessage.argtypes = [ctypes.POINTER(wt.MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wt.MSG)]
user32.RegisterWindowMessageW.argtypes = [wt.LPCWSTR]
user32.RegisterWindowMessageW.restype = wt.UINT
user32.UnregisterClassW.argtypes = [wt.LPCWSTR, wt.HINSTANCE]
kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]
kernel32.GetModuleHandleW.restype = wt.HMODULE
shell32.Shell_NotifyIconW.argtypes = [wt.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
shell32.Shell_NotifyIconW.restype = wt.BOOL


# ---- the "Still there?" card ---------------------------------------------------
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
try:
    dwmapi = ctypes.WinDLL("dwmapi")
except OSError:
    dwmapi = None

WM_PAINT, WM_ERASEBKGND, WM_TIMER, WM_SETCURSOR = 0x000F, 0x0014, 0x0113, 0x0020
WM_MOUSEMOVE, WM_LBUTTONUP_, WM_MOUSELEAVE, WM_MOUSEACTIVATE = 0x0200, 0x0202, 0x02A3, 0x0021
MA_NOACTIVATE = 3
WS_POPUP = 0x80000000
WS_EX_TOPMOST, WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = 0x8, 0x80, 0x08000000
CS_DROPSHADOW = 0x00020000
SW_HIDE = 0
SWP_NOACTIVATE, SWP_SHOWWINDOW = 0x10, 0x40
HWND_TOPMOST = wt.HWND(-1)
SPI_GETWORKAREA = 0x30
DT_CENTER, DT_VCENTER, DT_SINGLELINE, DT_WORDBREAK, DT_NOPREFIX, DT_END_ELLIPSIS = 0x1, 0x4, 0x20, 0x10, 0x800, 0x8000
TME_LEAVE = 0x2
IDC_ARROW, IDC_HAND = 32512, 32649
WDA_EXCLUDEFROMCAPTURE = 0x11


class PAINTSTRUCT(ctypes.Structure):
    _fields_ = [("hdc", wt.HDC), ("fErase", wt.BOOL), ("rcPaint", wt.RECT), ("fRestore", wt.BOOL),
                ("fIncUpdate", wt.BOOL), ("rgbReserved", ctypes.c_byte * 32)]


class TRACKMOUSEEVENT(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("dwFlags", wt.DWORD), ("hwndTrack", wt.HWND), ("dwHoverTime", wt.DWORD)]


user32.BeginPaint.argtypes = [wt.HWND, ctypes.POINTER(PAINTSTRUCT)]
user32.BeginPaint.restype = wt.HDC
user32.EndPaint.argtypes = [wt.HWND, ctypes.POINTER(PAINTSTRUCT)]
user32.GetClientRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
user32.FillRect.argtypes = [wt.HDC, ctypes.POINTER(wt.RECT), wt.HBRUSH]
user32.DrawTextW.argtypes = [wt.HDC, wt.LPCWSTR, ctypes.c_int, ctypes.POINTER(wt.RECT), wt.UINT]
user32.InvalidateRect.argtypes = [wt.HWND, ctypes.c_void_p, wt.BOOL]
user32.SetTimer.argtypes = [wt.HWND, ctypes.c_size_t, wt.UINT, ctypes.c_void_p]
user32.KillTimer.argtypes = [wt.HWND, ctypes.c_size_t]
user32.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.UINT]
user32.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
user32.SystemParametersInfoW.argtypes = [wt.UINT, wt.UINT, ctypes.c_void_p, wt.UINT]
user32.TrackMouseEvent.argtypes = [ctypes.POINTER(TRACKMOUSEEVENT)]
user32.LoadCursorW.argtypes = [wt.HINSTANCE, ctypes.c_void_p]
user32.LoadCursorW.restype = wt.HANDLE
user32.SetCursor.argtypes = [wt.HANDLE]
user32.SetWindowDisplayAffinity.argtypes = [wt.HWND, wt.DWORD]
gdi32.CreateFontW.argtypes = [ctypes.c_int] * 5 + [wt.DWORD] * 8 + [wt.LPCWSTR]
gdi32.CreateFontW.restype = wt.HFONT
gdi32.CreateSolidBrush.argtypes = [wt.COLORREF]
gdi32.CreateSolidBrush.restype = wt.HBRUSH
gdi32.CreatePen.argtypes = [ctypes.c_int, ctypes.c_int, wt.COLORREF]
gdi32.CreatePen.restype = wt.HPEN
gdi32.SelectObject.argtypes = [wt.HDC, wt.HGDIOBJ]
gdi32.SelectObject.restype = wt.HGDIOBJ
gdi32.DeleteObject.argtypes = [wt.HGDIOBJ]
gdi32.SetBkMode.argtypes = [wt.HDC, ctypes.c_int]
gdi32.SetTextColor.argtypes = [wt.HDC, wt.COLORREF]
gdi32.RoundRect.argtypes = [wt.HDC] + [ctypes.c_int] * 6
if dwmapi:
    dwmapi.DwmSetWindowAttribute.argtypes = [wt.HWND, wt.DWORD, ctypes.c_void_p, wt.DWORD]


def _rgb(hexstr):
    h = hexstr.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return r | (g << 8) | (b << 16)


THEMES = {
    "light": {k: _rgb(v) for k, v in {"bg": "#fcfcfb", "ink": "#0b0b0b", "ink2": "#52514e", "muted": "#7d7b75",
              "pri": "#2a78d6", "pri_hover": "#256abf", "pri_ink": "#ffffff", "sec": "#ecebe6", "sec_hover": "#e1e0d9",
              "border": "#d9d8d2"}.items()},
    "dark": {k: _rgb(v) for k, v in {"bg": "#232322", "ink": "#f0efec", "ink2": "#c3c2b7", "muted": "#8f8d86",
             "pri": "#3987e5", "pri_hover": "#5598e7", "pri_ink": "#ffffff", "sec": "#3a3a37", "sec_hover": "#464642",
             "border": "#3d3d3a"}.items()},
}


def _windows_theme():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            return "light" if winreg.QueryValueEx(k, "AppsUseLightTheme")[0] else "dark"
    except OSError:
        return "light"


# ---- icon drawn in code: a heartbeat line on a disc -------------------------
_BEAT = [(0.12, 0.54), (0.34, 0.54), (0.43, 0.30), (0.55, 0.76), (0.64, 0.44), (0.70, 0.54), (0.88, 0.54)]


def _seg_dist(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _render(size, bg, fg):
    ss = 3
    half_w = 0.052 if size <= 20 else 0.042
    rows = []
    for y in range(size - 1, -1, -1):            # BMP rows run bottom-up
        row = bytearray()
        for x in range(size):
            disc = line = 0
            for sy in range(ss):
                for sx in range(ss):
                    u, v = (x + (sx + .5) / ss) / size, (y + (sy + .5) / ss) / size
                    if math.hypot(u - .5, v - .5) <= .48:
                        disc += 1
                        if min(_seg_dist(u, v, *_BEAT[i], *_BEAT[i + 1]) for i in range(len(_BEAT) - 1)) <= half_w:
                            line += 1
            n = ss * ss
            a, l = disc / n, (line / disc if disc else 0)
            r, g, b = (round(bg[i] * (1 - l) + fg[i] * l) for i in range(3))
            row += bytes((b, g, r, round(a * 255)))
        rows.append(bytes(row))
    return b"".join(rows)


def make_icon(path, bg, fg=(255, 255, 255), sizes=(16, 20, 24, 32, 48)):
    images = [(s, _render(s, bg, fg)) for s in sizes]
    header = struct.pack("<HHH", 0, 1, len(images))
    entries, blobs, offset = b"", b"", 6 + 16 * len(images)
    for s, px in images:
        bih = struct.pack("<IiiHHIIiiII", 40, s, s * 2, 1, 32, 0, 0, 0, 0, 0, 0)
        data = bih + px + b"\x00" * (((s + 31) // 32) * 4 * s)
        entries += struct.pack("<BBBBHHII", s, s, 0, 0, 1, 32, len(data), offset)
        blobs += data
        offset += len(data)
    with open(path, "wb") as f:
        f.write(header + entries + blobs)


def _open(url):
    threading.Thread(target=webbrowser.open, args=(url,), daemon=True).start()


class Tray(threading.Thread):
    """menu_status() -> str shown greyed at the top of the menu.
    on_pause_toggle() flips pause; is_paused() reports it; on_quit() stops Pulse."""

    WM_TRAY = WM_APP + 1
    WM_PROMPT_SHOW = WM_APP + 3
    WM_PROMPT_HIDE = WM_APP + 4
    CMD_OPEN, CMD_PAUSE, CMD_WEEK, CMD_QUIT = 1, 2, 3, 9
    on_idle_answer = None       # set by pulse.py: receives "here" or "away"

    def __init__(self, url, icon_dir, menu_status, is_paused, on_pause_toggle, on_quit):
        super().__init__(name="tray", daemon=True)
        self.url, self.icon_dir = url, icon_dir
        self.menu_status, self.is_paused = menu_status, is_paused
        self.on_pause_toggle, self.on_quit = on_pause_toggle, on_quit
        self.hwnd = None
        self.ready = threading.Event()
        self._tip = "Pulse"
        self._icon_name = "active"
        self._balloon_url = None
        self._lock = threading.Lock()

    # ---- thread ----------------------------------------------------------------
    def run(self):
        try:
            self._run()
        except Exception:
            log.exception("tray failed")
            self.ready.set()

    def _run(self):
        try:   # crisp text on high-DPI screens
            user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        except Exception:
            pass
        self.prompt_hwnd = None
        self._prompt_info = None
        self._hover = -1
        os.makedirs(self.icon_dir, exist_ok=True)
        paths = {"active": os.path.join(self.icon_dir, "pulse.ico"),
                 "paused": os.path.join(self.icon_dir, "pulse-paused.ico")}
        if not os.path.exists(paths["active"]):
            make_icon(paths["active"], (42, 120, 214))
        if not os.path.exists(paths["paused"]):
            make_icon(paths["paused"], (143, 141, 134))
        cx, cy = user32.GetSystemMetrics(SM_CXSMICON), user32.GetSystemMetrics(SM_CYSMICON)
        self.icons = {k: user32.LoadImageW(None, p, IMAGE_ICON, cx, cy, LR_LOADFROMFILE) for k, p in paths.items()}
        self.large_icon = user32.LoadImageW(None, paths["active"], IMAGE_ICON, 48, 48, LR_LOADFROMFILE)

        hinst = kernel32.GetModuleHandleW(None)
        self._proc_ref = WNDPROC(self._proc)
        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
        wc.lpfnWndProc = self._proc_ref
        wc.hInstance = hinst
        wc.lpszClassName = "PulseTrayWindow"
        user32.RegisterClassExW(ctypes.byref(wc))
        self.hwnd = user32.CreateWindowExW(0, "PulseTrayWindow", "Pulse", 0, 0, 0, 0, 0, None, None, hinst, None)
        self.WM_TASKBAR = user32.RegisterWindowMessageW("TaskbarCreated")
        self._shell(NIM_ADD, NIF_MESSAGE | NIF_ICON | NIF_TIP)
        self.ready.set()
        msg = wt.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        user32.UnregisterClassW("PulseTrayWindow", hinst)

    def _nid(self, flags):
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self.hwnd
        nid.uID = 1
        nid.uFlags = flags
        nid.uCallbackMessage = self.WM_TRAY
        nid.hIcon = self.icons.get(self._icon_name)
        nid.szTip = self._tip[:127]
        return nid

    def _shell(self, op, flags, nid=None):
        if not self.hwnd:
            return False
        with self._lock:
            return bool(shell32.Shell_NotifyIconW(op, ctypes.byref(nid or self._nid(flags))))

    def _proc(self, hwnd, msg, wparam, lparam):
        try:
            if msg == self.WM_TRAY:
                ev = lparam & 0xFFFF
                if ev == WM_LBUTTONUP:
                    _open(self.url)
                elif ev in (WM_RBUTTONUP, WM_CONTEXTMENU):
                    self._menu()
                elif ev == NIN_BALLOONUSERCLICK:
                    _open(self._balloon_url or self.url)
                return 0
            if msg == getattr(self, "WM_TASKBAR", -1):      # Explorer restarted: put the icon back
                self._shell(NIM_ADD, NIF_MESSAGE | NIF_ICON | NIF_TIP)
                return 0
            if msg == self.WM_PROMPT_SHOW:
                self._show_prompt()
                return 0
            if msg == self.WM_PROMPT_HIDE:
                self._hide_prompt()
                return 0
            if msg == WM_CLOSE:
                if self.prompt_hwnd:
                    user32.DestroyWindow(self.prompt_hwnd)
                    self.prompt_hwnd = None
                user32.DestroyWindow(hwnd)
                return 0
            if msg == WM_DESTROY:
                self._shell(NIM_DELETE, 0)
                self.hwnd = None
                user32.PostQuitMessage(0)
                return 0
        except Exception:
            log.exception("tray message failed")
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _menu(self):
        m = user32.CreatePopupMenu()
        try:
            user32.AppendMenuW(m, MF_STRING, self.CMD_OPEN, "Open dashboard")
            user32.SetMenuDefaultItem(m, self.CMD_OPEN, 0)
            user32.AppendMenuW(m, MF_STRING, self.CMD_WEEK, "Weekly report")
            user32.AppendMenuW(m, MF_SEPARATOR, 0, None)
            try:
                status = self.menu_status()
            except Exception:
                status = None
            if status:
                user32.AppendMenuW(m, MF_STRING | MF_GRAYED, 0, status)
            user32.AppendMenuW(m, MF_STRING, self.CMD_PAUSE, "Resume tracking" if self.is_paused() else "Pause tracking")
            user32.AppendMenuW(m, MF_SEPARATOR, 0, None)
            user32.AppendMenuW(m, MF_STRING, self.CMD_QUIT, "Quit Pulse")
            pt = wt.POINT()
            user32.GetCursorPos(ctypes.byref(pt))
            user32.SetForegroundWindow(self.hwnd)
            cmd = user32.TrackPopupMenu(m, TPM_RIGHTBUTTON | TPM_RETURNCMD | TPM_NONOTIFY, pt.x, pt.y, 0, self.hwnd, None)
            user32.PostMessageW(self.hwnd, 0, 0, 0)
        finally:
            user32.DestroyMenu(m)
        if cmd == self.CMD_OPEN:
            _open(self.url)
        elif cmd == self.CMD_WEEK:
            _open(self.url + "#week")
        elif cmd == self.CMD_PAUSE:
            self.on_pause_toggle()
            self.set_icon("paused" if self.is_paused() else "active")
        elif cmd == self.CMD_QUIT:
            threading.Thread(target=self.on_quit, daemon=True).start()

    # ---- "Still there?" card (runs on the tray thread) ------------------------------
    def _create_prompt(self):
        hinst = kernel32.GetModuleHandleW(None)
        self._prompt_proc_ref = WNDPROC(self._prompt_proc)
        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
        wc.style = CS_DROPSHADOW
        wc.lpfnWndProc = self._prompt_proc_ref
        wc.hInstance = hinst
        wc.hCursor = user32.LoadCursorW(None, ctypes.c_void_p(IDC_ARROW))
        wc.lpszClassName = "PulseStillThere"
        user32.RegisterClassExW(ctypes.byref(wc))
        self.prompt_hwnd = user32.CreateWindowExW(
            WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE, "PulseStillThere", "Pulse: still there?",
            WS_POPUP, 0, 0, 10, 10, None, None, hinst, None)
        try:   # keep it out of screen shares, recordings and proctoring captures
            user32.SetWindowDisplayAffinity(self.prompt_hwnd, WDA_EXCLUDEFROMCAPTURE)
        except Exception:
            pass
        if dwmapi:
            pref = ctypes.c_int(2)  # rounded corners on Windows 11
            dwmapi.DwmSetWindowAttribute(self.prompt_hwnd, 33, ctypes.byref(pref), 4)

    def _show_prompt(self):
        info = self._prompt_info
        if not info:
            return
        if not self.prompt_hwnd:
            self._create_prompt()
        try:
            dpi = user32.GetDpiForSystem()
        except Exception:
            dpi = 96
        s = dpi / 96.0
        self._scale = s
        self._theme = THEMES[_windows_theme()]
        if dwmapi:
            border = wt.DWORD(self._theme["border"])
            dwmapi.DwmSetWindowAttribute(self.prompt_hwnd, 34, ctypes.byref(border), 4)
        if not getattr(self, "_fonts", None) or self._fonts[0] != s:
            mk = lambda px, weight: gdi32.CreateFontW(-round(px * s), 0, 0, 0, weight, 0, 0, 0, 1, 0, 0, 5, 0, "Segoe UI")
            self._fonts = (s, mk(19, 600), mk(14.5, 400), mk(13, 400), mk(14, 600))
        W, H = round(380 * s), round(178 * s)
        P, bh, by = round(18 * s), round(36 * s), round(126 * s)
        split = round(204 * s)
        self._btns = [("I'm here, keep counting", (P, by, split, by + bh)),
                      ("I was away", (split + round(10 * s), by, W - P, by + bh))]
        self._hover = -1
        wa = wt.RECT()
        user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(wa), 0)
        x, y = wa.right - W - round(16 * s), wa.bottom - H - round(16 * s)
        user32.SetWindowPos(self.prompt_hwnd, HWND_TOPMOST, x, y, W, H, SWP_NOACTIVATE | SWP_SHOWWINDOW)
        user32.SetTimer(self.prompt_hwnd, 1, 1000, None)
        user32.InvalidateRect(self.prompt_hwnd, None, True)

    def _hide_prompt(self):
        if self.prompt_hwnd:
            user32.KillTimer(self.prompt_hwnd, 1)
            user32.ShowWindow(self.prompt_hwnd, SW_HIDE)
        self._prompt_info = None

    def _hit(self, lparam):
        x = ctypes.c_short(lparam & 0xFFFF).value
        y = ctypes.c_short((lparam >> 16) & 0xFFFF).value
        for i, (_, (l, t, r, b)) in enumerate(getattr(self, "_btns", [])):
            if l <= x < r and t <= y < b:
                return i
        return -1

    def _prompt_proc(self, hwnd, msg, wparam, lparam):
        try:
            if msg == WM_MOUSEACTIVATE:
                return MA_NOACTIVATE           # clicking the card never takes focus from your test or editor
            if msg == WM_ERASEBKGND:
                return 1
            if msg == WM_PAINT:
                self._paint_prompt(hwnd)
                return 0
            if msg == WM_TIMER:
                user32.InvalidateRect(hwnd, None, False)
                return 0
            if msg == WM_MOUSEMOVE:
                h = self._hit(lparam)
                if h != self._hover:
                    self._hover = h
                    user32.InvalidateRect(hwnd, None, False)
                tme = TRACKMOUSEEVENT(ctypes.sizeof(TRACKMOUSEEVENT), TME_LEAVE, hwnd, 0)
                user32.TrackMouseEvent(ctypes.byref(tme))
                return 0
            if msg == WM_MOUSELEAVE:
                if self._hover != -1:
                    self._hover = -1
                    user32.InvalidateRect(hwnd, None, False)
                return 0
            if msg == WM_SETCURSOR and self._hover != -1:
                user32.SetCursor(user32.LoadCursorW(None, ctypes.c_void_p(IDC_HAND)))
                return 1
            if msg == WM_LBUTTONUP_:
                h = self._hit(lparam)
                if h != -1:
                    self._hide_prompt()
                    if self.on_idle_answer:
                        self.on_idle_answer("here" if h == 0 else "away")
                return 0
        except Exception:
            log.exception("prompt message failed")
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _paint_prompt(self, hwnd):
        ps = PAINTSTRUCT()
        hdc = user32.BeginPaint(hwnd, ctypes.byref(ps))
        try:
            th, s = self._theme, self._scale
            _, f_title, f_body, f_small, f_btn = self._fonts
            rc = wt.RECT()
            user32.GetClientRect(hwnd, ctypes.byref(rc))
            bg = gdi32.CreateSolidBrush(th["bg"])
            user32.FillRect(hdc, ctypes.byref(rc), bg)
            gdi32.DeleteObject(bg)
            gdi32.SetBkMode(hdc, 1)

            def text(t, font, color, box, flags):
                old = gdi32.SelectObject(hdc, font)
                gdi32.SetTextColor(hdc, color)
                r = wt.RECT(*box)
                user32.DrawTextW(hdc, t, -1, ctypes.byref(r), flags | DT_NOPREFIX)
                gdi32.SelectObject(hdc, old)

            info = self._prompt_info or {"label": "", "idle": 0, "deadline": 0}
            P, W = round(18 * s), rc.right
            mins = max(1, round(info["idle"] / 60))
            text("Still there?", f_title, th["ink"], (P, round(14 * s), W - P, round(42 * s)), DT_SINGLELINE)
            text(f"No mouse or keyboard for {mins} min. Pulse is counting this as {info['label']}.",
                 f_body, th["ink2"], (P, round(44 * s), W - P, round(88 * s)), DT_WORDBREAK | DT_END_ELLIPSIS)
            import time as _t
            left = max(0, int(info["deadline"] - _t.time()))
            text(f"No answer in {left // 60}:{left % 60:02d} and those quiet minutes won't count.",
                 f_small, th["muted"], (P, round(92 * s), W - P, round(114 * s)), DT_SINGLELINE | DT_END_ELLIPSIS)
            rad = round(16 * s)
            for i, (label, (l, t, r, b)) in enumerate(self._btns):
                primary = i == 0
                fill = th[("pri" if primary else "sec") + ("_hover" if self._hover == i else "")]
                brush, pen = gdi32.CreateSolidBrush(fill), gdi32.CreatePen(0, 1, fill)
                ob, op = gdi32.SelectObject(hdc, brush), gdi32.SelectObject(hdc, pen)
                gdi32.RoundRect(hdc, l, t, r, b, rad, rad)
                gdi32.SelectObject(hdc, ob)
                gdi32.SelectObject(hdc, op)
                gdi32.DeleteObject(brush)
                gdi32.DeleteObject(pen)
                text(label, f_btn, th["pri_ink"] if primary else th["ink"], (l, t, r, b),
                     DT_CENTER | DT_VCENTER | DT_SINGLELINE)
        finally:
            user32.EndPaint(hwnd, ctypes.byref(ps))

    # ---- called from any thread -------------------------------------------------
    def can_prompt(self):
        return bool(self.hwnd)

    def ask_idle(self, label, idle_secs, deadline):
        self._prompt_info = {"label": label, "idle": idle_secs, "deadline": deadline}
        if self.hwnd:
            user32.PostMessageW(self.hwnd, self.WM_PROMPT_SHOW, 0, 0)

    def hide_idle(self):
        if self.hwnd:
            user32.PostMessageW(self.hwnd, self.WM_PROMPT_HIDE, 0, 0)

    def set_tooltip(self, text):
        if text != self._tip:
            self._tip = text
            self._shell(NIM_MODIFY, NIF_TIP)

    def set_icon(self, name):
        if name != self._icon_name and name in getattr(self, "icons", {}):
            self._icon_name = name
            self._shell(NIM_MODIFY, NIF_ICON)

    def notify(self, title, text, url=None):
        """Shows a Windows notification. Clicking it opens `url` (default: the dashboard)."""
        if not self.hwnd:
            log.info("notification (no tray): %s - %s", title, text)
            return False
        self._balloon_url = url
        nid = self._nid(NIF_INFO)
        nid.szInfoTitle = title[:63]
        nid.szInfo = text[:255]
        nid.dwInfoFlags = NIIF_USER | NIIF_LARGE_ICON
        nid.hBalloonIcon = getattr(self, "large_icon", None) or self.icons.get("active")
        log.info("notify: %s - %s", title, text)
        return self._shell(NIM_MODIFY, NIF_INFO, nid)

    def stop(self):
        if self.hwnd:
            user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)
