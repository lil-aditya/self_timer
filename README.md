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
