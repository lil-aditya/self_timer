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
