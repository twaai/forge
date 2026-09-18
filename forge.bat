@echo off
setlocal
set "ROOT=%~dp0"
set "PY=%ROOT%.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
pushd "%ROOT%forge3"
"%PY%" web_main.py %*
set "CODE=%ERRORLEVEL%"
popd
exit /b %CODE%
