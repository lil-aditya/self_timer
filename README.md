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
