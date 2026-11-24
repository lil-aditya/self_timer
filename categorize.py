"""Turns raw window data (exe, title, url) into something a person reads:
which app, which website, which project, and which category it belongs to.

Categorisation happens when the dashboard asks, not when activity is recorded,
so changing a category in the dashboard re-colours your whole history.
"""
import json
import os
import re
import threading

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
RULES_PATH = os.path.join(BASE, "rules.json")
OVERRIDES_PATH = os.path.join(DATA, "overrides.json")

CATEGORIES = ["Coding", "Entertainment", "Study", "Social", "Communication", "Productivity", "AI", "Other"]
PRODUCTIVE = {"Coding", "Study", "Productivity", "AI"}
DISTRACTING = {"Entertainment", "Social"}

BROWSERS = {
    "chrome.exe": "Chrome", "msedge.exe": "Edge", "brave.exe": "Brave", "firefox.exe": "Firefox",
    "opera.exe": "Opera", "opera_gx.exe": "Opera GX", "vivaldi.exe": "Vivaldi", "arc.exe": "Arc",
    "zen.exe": "Zen", "thorium.exe": "Thorium",
}

# Editors whose title reads "file - project - App" (VS Code family, Antigravity, Cursor ...)
VSCODE_LIKE = {"code.exe": "Visual Studio Code", "code - insiders.exe": "Visual Studio Code - Insiders",
               "antigravity ide.exe": "Antigravity IDE", "antigravity.exe": "Antigravity",
               "cursor.exe": "Cursor", "windsurf.exe": "Windsurf", "zed.exe": "Zed"}
# Editors whose title starts with the project name (JetBrains family, Visual Studio)
PROJECT_FIRST = {"pycharm64.exe", "idea64.exe", "webstorm64.exe", "clion64.exe", "goland64.exe",
                 "studio64.exe", "devenv.exe", "rstudio.exe"}

KNOWN_APPS = {
    "chrome.exe": "Google Chrome", "msedge.exe": "Microsoft Edge", "brave.exe": "Brave", "firefox.exe": "Firefox",
    "code.exe": "VS Code", "antigravity ide.exe": "Antigravity IDE", "antigravity.exe": "Antigravity",
    "explorer.exe": "File Explorer", "windowsterminal.exe": "Terminal", "powershell.exe": "PowerShell",
    "pwsh.exe": "PowerShell", "cmd.exe": "Command Prompt", "acrobat.exe": "Adobe Acrobat",
    "acrord32.exe": "Adobe Reader", "winword.exe": "Word", "excel.exe": "Excel", "powerpnt.exe": "PowerPoint",
    "whatsapp.exe": "WhatsApp", "whatsapp.root.exe": "WhatsApp", "spotify.exe": "Spotify", "notepad.exe": "Notepad",
    "searchhost.exe": "Windows Search", "startmenuexperiencehost.exe": "Start menu",
    "shellexperiencehost.exe": "Windows shell", "systemsettings.exe": "Settings", "taskmgr.exe": "Task Manager",
    "applicationframehost.exe": "Windows app", "olk.exe": "Outlook", "ms-teams.exe": "Microsoft Teams",
}

SITE_NAMES = {
    "youtube.com": "YouTube", "music.youtube.com": "YouTube Music", "open.spotify.com": "Spotify",
    "github.com": "GitHub", "gitlab.com": "GitLab", "classroom.google.com": "Google Classroom",
    "mail.google.com": "Gmail", "docs.google.com": "Google Docs", "drive.google.com": "Google Drive",
    "meet.google.com": "Google Meet", "calendar.google.com": "Google Calendar", "google.com": "Google Search",
    "colab.research.google.com": "Google Colab", "scholar.google.com": "Google Scholar",
    "gemini.google.com": "Gemini", "aistudio.google.com": "Google AI Studio", "notebooklm.google.com": "NotebookLM",
    "web.whatsapp.com": "WhatsApp Web", "chatgpt.com": "ChatGPT", "chat.openai.com": "ChatGPT",
    "claude.ai": "Claude", "perplexity.ai": "Perplexity", "copilot.microsoft.com": "Copilot",
    "instagram.com": "Instagram", "facebook.com": "Facebook", "x.com": "X", "twitter.com": "X",
    "reddit.com": "Reddit", "linkedin.com": "LinkedIn", "netflix.com": "Netflix", "primevideo.com": "Prime Video",
    "hotstar.com": "JioHotstar", "leetcode.com": "LeetCode", "codeforces.com": "Codeforces",
    "codechef.com": "CodeChef", "geeksforgeeks.org": "GeeksforGeeks", "stackoverflow.com": "Stack Overflow",
    "kaggle.com": "Kaggle", "wikipedia.org": "Wikipedia", "notion.so": "Notion", "coursera.org": "Coursera",
    "nptel.ac.in": "NPTEL", "udemy.com": "Udemy", "localhost": "localhost", "127.0.0.1": "localhost",
    "twitch.tv": "Twitch", "discord.com": "Discord", "canva.com": "Canva", "figma.com": "Figma",
    "outlook.live.com": "Outlook", "outlook.office.com": "Outlook", "huggingface.co": "Hugging Face",
    "overleaf.com": "Overleaf", "chess.com": "Chess.com", "web.telegram.org": "Telegram",
}

# Last-resort site detection from a page title, when the address bar can't be read.
TITLE_SITES = {
    "youtube": "youtube.com", "spotify": "open.spotify.com", "instagram": "instagram.com",
    "whatsapp": "web.whatsapp.com", "gmail": "mail.google.com", "github": "github.com", "chatgpt": "chatgpt.com",
    "claude": "claude.ai", "gemini": "gemini.google.com", "leetcode": "leetcode.com",
    "classroom": "classroom.google.com", "netflix": "netflix.com", "reddit": "reddit.com",
    "linkedin": "linkedin.com", "x": "x.com", "google docs": "docs.google.com", "google search": "google.com",
    "stack overflow": "stackoverflow.com", "codeforces": "codeforces.com", "geeksforgeeks": "geeksforgeeks.org",
    "wikipedia": "wikipedia.org", "notion": "notion.so", "google drive": "drive.google.com",
    "perplexity": "perplexity.ai", "facebook": "facebook.com", "coursera": "coursera.org",
}

_SEP = re.compile(r"\s+[-–—|·]\s+")
_BROWSER_SUFFIX = re.compile(
    r"\s+[-–—]\s+(Google Chrome|Microsoft​?\s?Edge|Brave|Mozilla Firefox|Firefox|Opera|Vivaldi|Arc|Zen Browser|Thorium)"
    r"(\s*\(Incognito\)|\s*\(InPrivate\))?\s*$", re.I)
_EDGE_EXTRA = re.compile(r"\s+and \d+ more pages?$", re.I)
_EDGE_PROFILE = re.compile(r"\s+[-–—]\s+(Personal|Work|Profile \d+|InPrivate)\s*$", re.I)
_BADGE = re.compile(r"^\(\d+\+?\)\s*")
_DIRTY = re.compile(r"^[●•*]\s*")


class Rules:
    """Loaded from rules.json plus the dashboard's overrides.json. Thread-safe."""

    def __init__(self):
        self._lock = threading.Lock()
        self.load()

    def load(self):
        with open(RULES_PATH, encoding="utf-8") as f:
            cfg = json.load(f)
        overrides = {"apps": {}, "sites": {}}
        if os.path.exists(OVERRIDES_PATH):
            try:
                with open(OVERRIDES_PATH, encoding="utf-8") as f:
                    o = json.load(f)
                overrides["apps"].update(o.get("apps", {}))
                overrides["sites"].update(o.get("sites", {}))
            except (OSError, ValueError):
                pass
        app_cat, site_cat, suffix_cat, contains_cat = {}, {}, [], []
        for cat, spec in cfg.get("categories", {}).items():
            for a in spec.get("apps", []):
                app_cat[a.lower()] = cat
            for s in spec.get("sites", []):
                s = s.lower()
                if s.startswith("."):
                    suffix_cat.append((s, cat))
                elif "." not in s and s != "localhost":
                    contains_cat.append((s, cat))     # e.g. "moodle" matches moodle.anything
                else:
                    site_cat[s] = cat
        title_rules = []
        for r in cfg.get("title_rules", []):
            try:
                title_rules.append(({s.lower() for s in r.get("sites", [])},
                                    {a.lower() for a in r.get("apps", [])},
                                    re.compile(r["pattern"]), r["category"]))
            except (re.error, KeyError):
                pass
        known = set(SITE_NAMES) | set(site_cat) | set(TITLE_SITES.values())
        with self._lock:
            self.cfg = cfg
            self.app_cat, self.site_cat = app_cat, site_cat
            self.suffix_cat, self.contains_cat = suffix_cat, contains_cat
            self.title_rules = title_rules
            self.overrides = overrides
            self.known_sites = sorted(known, key=len, reverse=True)
            self.passive_apps = {a.lower() for a in cfg.get("passive", {}).get("apps", [])}
            self.passive_sites = {s.lower() for s in cfg.get("passive", {}).get("sites", [])}
            ne = cfg.get("no_idle_check", {})
            self.exempt_apps = {a.lower() for a in ne.get("apps", [])}
            self.exempt_sites = [s.lower() for s in ne.get("sites", [])]
            self.exempt_urls = [u.lower() for u in ne.get("url_contains", [])]
            try:
                self.exempt_title = re.compile(ne["title_pattern"]) if ne.get("title_pattern") else None
            except re.error:
                self.exempt_title = None
            self._cache = {}

    # ---- settings -------------------------------------------------------
    def get(self, key, default=None):
        return self.cfg.get(key, default)

    def set_override(self, kind, key, category):
        if kind not in ("apps", "sites") or not key:
            raise ValueError("kind must be 'apps' or 'sites'")
        if category not in CATEGORIES and category is not None:
            raise ValueError("unknown category")
        os.makedirs(DATA, exist_ok=True)
        o = {"apps": dict(self.overrides["apps"]), "sites": dict(self.overrides["sites"])}
        if category is None:
            o[kind].pop(key.lower(), None)
        else:
            o[kind][key.lower()] = category
        tmp = OVERRIDES_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(o, f, indent=2)
        os.replace(tmp, OVERRIDES_PATH)
        self.load()

    # ---- sites ----------------------------------------------------------
    def site_key(self, host):
        """Group subdomains: www.youtube.com / m.youtube.com -> youtube.com, but keep music.youtube.com."""
        if not host:
            return None
        for k in self.known_sites:
            if host == k or host.endswith("." + k):
                return k
        return host

    @staticmethod
    def site_name(key):
        if not key:
            return "Other pages"
        if key in SITE_NAMES:
            return SITE_NAMES[key]
        if key == "file":
            return "Local files"
        return key

    def is_passive(self, exe, host):
        if exe in self.passive_apps:
            return True
        key = self.site_key(host)
        return bool(key and key in self.passive_sites)

    def is_exempt(self, exe, host, url, title, cat):
        """Meetings and online assessments: never ask 'Still there?' and keep counting."""
        if exe in self.exempt_apps:
            return True
        if host and any(host == s or host.endswith("." + s) for s in self.exempt_sites):
            return True
        u = (url or "").lower()
        if u and any(p in u for p in self.exempt_urls):
            return True
        # title words only count on real pages, not videos or feeds (an "exam tips" video is still a video)
        if (title and self.exempt_title and cat not in ("Entertainment", "Social")
                and not self.is_passive(exe, host) and self.exempt_title.search(title)):
            return True
        return False

    def idle_check(self):
        c = self.cfg.get("idle_check", {}) or {}
        return {"enabled": bool(c.get("enabled", True)),
                "answer": 60 * float(c.get("answer_within_minutes", 2)),
                "confirm": 60 * float(c.get("after_confirm_minutes", 15))}

    # ---- categories -----------------------------------------------------
    def _site_category(self, key, host):
        if not key:
            return None
        if key in self.overrides["sites"]:
            return self.overrides["sites"][key]
        if key in self.site_cat:
            return self.site_cat[key]
        h = host or key
        for k, cat in self.site_cat.items():
            if h.endswith("." + k):
                return cat
        for suf, cat in self.suffix_cat:
            if h.endswith(suf):
                return cat
        for word, cat in self.contains_cat:
            if word in h:
                return cat
        return None

    def site_category(self, key):
        return self._site_category(key, key) or "Other"

    def classify(self, exe, site_key, host, title):
        for sites, apps, pat, cat in self.title_rules:
            if ((site_key and site_key in sites) or exe in apps) and title and pat.search(title):
                return cat
        if site_key:
            return self._site_category(site_key, host) or "Other"
        if exe in self.overrides["apps"]:
            return self.overrides["apps"][exe]
        return self.app_cat.get(exe, "Other")
