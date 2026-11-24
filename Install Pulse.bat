@echo off
cd /d "%~dp0"
echo Setting up Pulse...
python -m pip install --user --quiet uiautomation
python pulse.py --install
echo.
pause
