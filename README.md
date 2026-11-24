# Pulse

Digital Wellbeing for your Windows laptop. Pulse notes which window is in front of you once a second and shows where your day went: each app, each website in each browser, and each coding project.

Everything stays on this laptop. Nothing is uploaded anywhere.

## Start

| Do this | To |
|---|---|
| Double-click **Install Pulse.bat** | Start Pulse with Windows, add a **Pulse** shortcut to your desktop and open the dashboard. Do this once. |
| Double-click **Start Pulse.bat** | Start Pulse now (if it isn't running) and open the dashboard |
| Double-click **Stop Pulse.bat** | Stop tracking until next sign-in |
| Double-click **Uninstall Pulse.bat** | Stop starting with Windows. Your history is kept. |

Dashboard: <http://127.0.0.1:7317>

## What it records

- **Apps**, such as Antigravity IDE, VS Code, Acrobat or WhatsApp, with their windows.
- **Projects** in code editors. Antigravity, VS Code, Cursor, Windsurf and JetBrains IDEs show time per project folder.
- **Websites** in Chrome, Edge, Brave, Firefox, Opera and Vivaldi. Pulse reads the real address from the address bar, so YouTube in Chrome and YouTube in Edge are counted separately and then added together.
- **Categories**: Coding, Study, AI, Productivity, Communication, Entertainment, Social and Other.
  - *Focus* is Coding + Study + AI + Productivity.
  - *Distraction* is Entertainment + Social.
- **YouTube lectures count as Study.** A video whose title has words like *lecture, tutorial, NPTEL, DSA, course* or *exam* is counted as Study. Other videos count as Entertainment.

## Tray icon

Pulse puts a heartbeat icon next to the clock. It turns grey while paused. If you don't see it, check the **^** overflow arrow; you can drag it onto the taskbar.

- **Hover:** today's screen time and focus time.
- **Click:** open the dashboard.
- **Right-click:** Open dashboard, Weekly report, Pause/Resume tracking, Quit Pulse.

## Limits and a focus goal

In the dashboard, under **Today's limits and focus goal**:

- **Limit** a website (YouTube), an app, or a whole category (Social) to so many minutes a day. Pulse sends a Windows notification 5 minutes before the limit, another when you reach it, and another every 15 minutes you stay on it after that.
- **Set a daily focus goal**, for example 4 hours. You get a notification when you reach it.
- **Send a test notification** checks that Windows shows Pulse's alerts. If nothing appears, turn off *Do not disturb* in Windows notification settings.

Limits reset at midnight.

## Weekly report

Switch the dashboard to **Week**, or right-click the tray icon and choose **Weekly report**. It shows:

- screen time and focus share compared with the week before
- which categories went up or down
- your best focus day and longest focus session
- the hour you focus best, and when distraction peaks
- how many nights you were up past midnight

Every Sunday after 8 PM, a notification sums up your week. Click it to open the report.

## Export and cleanup

- **Download as CSV:** the link at the bottom of the dashboard downloads the day or week on screen. It opens in Excel or Google Sheets.
- **Delete old history automatically:** set `"keep_days": 90` in `rules.json` to keep only the last 90 days. The default `0` keeps everything.

## "Still there?" check

When you haven't touched the mouse or keyboard for 3 minutes, a small card appears in the bottom-right corner:

- **I'm here, keep counting:** the quiet minutes count. Pulse won't ask again for 15 minutes while you stay on the same thing, which helps when you're reading or thinking.
- **I was away**, or no answer within 2 minutes: the quiet minutes don't count. Pulse resumes when you're back.

For videos and PDFs the card waits 30 minutes, since you're watching or reading.

**It never asks during meetings or tests,** and keeps counting there instead:

- Google Meet, Teams, Zoom and Webex
- assessment and OA sites: HackerRank, HackerEarth, CodeSignal, Codility, Mettl, iMocha, AMCAT, SHL, TCS iON and others
- Google Forms and Microsoft Forms quizzes, and LeetCode and Codeforces contests
- Safe Exam Browser and LockDown Browser
- any page whose title says *assessment, proctored, exam, quiz, contest* or *OA*

**The card never gets in your way.** It doesn't take keyboard focus, so you can keep typing, and it's hidden from screen sharing and recordings, including proctoring software.

To change the wait times or add a test site, edit `idle_check` and `no_idle_check` in `rules.json`, then restart Pulse. To turn the card off and simply stop counting after 3 quiet minutes, set `"enabled": false`.

## What it skips

- **Idle time.** After 3 minutes with no mouse or keyboard input, Pulse stops counting, and it trims the time back to your last input.
- **Watching and reading.** For videos, meetings and PDF readers, Pulse allows 30 minutes without input before it stops counting, because you're watching or reading.
- **Locked screen and sleep** are never counted.
- **Pause.** The **Pause** button in the dashboard stops recording until you press **Resume**.

## Change the categories

- **In the dashboard:** use the dropdown on any app or website. Your whole history is re-colored immediately.
- **For bigger changes:** edit `rules.json`. It holds the app and site lists, the YouTube study keywords and the idle limits. Then restart Pulse with Stop, then Start.

## Files

| File | What it is |
|---|---|
| `pulse.py` | Starts everything; also install, uninstall, stop and open |
| `tracker.py` | Reads the window in front once a second (Win32 API, plus UI Automation for browser URLs) |
| `categorize.py` | Turns windows into apps, sites, projects and categories |
| `report.py` | Day and week numbers |
| `server.py` | The local dashboard server; it only answers this computer |
| `tray.py` | Tray icon, menu and Windows notifications (the icon is drawn in code) |
| `wellbeing.py` | Limits, the focus goal, alerts and the Sunday report reminder |
| `data/limits.json` | Your limits and goal |
| `dashboard/index.html` | The dashboard |
| `data/pulse.db` | Your history (SQLite) |
| `data/overrides.json` | Categories you changed in the dashboard |
| `data/pulse.log` | Log file, if something goes wrong |
