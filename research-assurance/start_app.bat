@echo off
setlocal
where py >nul 2>nul
if not errorlevel 1 (
  py -3 "%~dp0desktop_app.py" %*
) else (
  python "%~dp0desktop_app.py" %*
)
