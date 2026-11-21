@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto dependencies
where py >nul 2>nul
if errorlevel 1 goto fallback
py -3 -m venv .venv
if errorlevel 1 goto failed
goto dependencies

:fallback
where python >nul 2>nul
if errorlevel 1 goto missing
python -m venv .venv
if errorlevel 1 goto failed

:dependencies
".venv\Scripts\python.exe" -c "import tkinter, numpy, sounddevice, serial, websocket" >nul 2>nul
if not errorlevel 1 goto run
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto failed

:run
".venv\Scripts\python.exe" -m cw_rig_desk
if errorlevel 1 goto failed
exit /b 0

:missing
echo Install Python 3.12 or 3.13 for Windows from https://www.python.org/downloads/windows/
echo Enable the Python launcher or Add Python to PATH.
pause
exit /b 1

:failed
echo CW Rig Desk could not start. See the error above.
pause
exit /b 1
