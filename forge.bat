@echo off
REM Launch the Forge TUI on Windows without installing.
REM Prefers a local .venv if present, else falls back to python on PATH.
setlocal
set "HERE=%~dp0"
set "PY=%HERE%.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" "%HERE%forge_tui.py" %*
endlocal
