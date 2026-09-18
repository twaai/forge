@echo off
setlocal EnableExtensions
set "ROOT=%~dp0"
set "VENV_PY=%ROOT%.venv\Scripts\python.exe"
set "READY=%ROOT%.venv\.forge-ready"

if defined FORGE_PYTHON (
    if not exist "%FORGE_PYTHON%" goto :python_missing
    set "VENV_PY=%FORGE_PYTHON%"
    goto :launch
)

if exist "%VENV_PY%" goto :install

call :find_python
if not defined PY_KIND goto :portable

echo [FORGE 3.0] Creating the local Python environment...
if "%PY_KIND%"=="launcher" (
    py -3 -m venv "%ROOT%.venv"
) else (
    python -m venv "%ROOT%.venv"
)
if errorlevel 1 goto :venv_failed
if not exist "%VENV_PY%" goto :venv_failed

:install
if exist "%READY%" goto :launch
echo [FORGE 3.0] Installing required packages...
"%VENV_PY%" -m pip install --disable-pip-version-check -r "%ROOT%requirements.txt"
if errorlevel 1 goto :install_failed
>"%READY%" echo FORGE 3.0 dependencies installed

:launch
if /I "%~1"=="--setup-only" (
    "%VENV_PY%" -c "import forge3.web_main; print('FORGE 3.0 setup verified')"
    exit /b %ERRORLEVEL%
)
pushd "%ROOT%"
"%VENV_PY%" -m forge3.web_main %*
set "CODE=%ERRORLEVEL%"
popd
exit /b %CODE%

:find_python
set "PY_KIND="
where py.exe >nul 2>nul
if not errorlevel 1 (
    py -3 -c "import sys; raise SystemExit(sys.version_info < (3,10))" >nul 2>nul
    if not errorlevel 1 set "PY_KIND=launcher"
)
if defined PY_KIND exit /b 0
where python.exe >nul 2>nul
if not errorlevel 1 (
    python -c "import sys; raise SystemExit(sys.version_info < (3,10))" >nul 2>nul
    if not errorlevel 1 set "PY_KIND=python"
)
exit /b 0

:portable
set "PORTABLE_DIR=%LOCALAPPDATA%\Forge-3.0"
set "PORTABLE_EXE=%PORTABLE_DIR%\Forge-3.0.exe"
set "DOWNLOAD=%PORTABLE_EXE%.download"
set "SUMS=%PORTABLE_DIR%\SHA256SUMS.txt"
set "RELEASE=https://github.com/twaai/forge/releases/latest/download"
if exist "%PORTABLE_EXE%" goto :portable_launch

echo [FORGE 3.0] Python 3.10+ was not found.
echo [FORGE 3.0] Downloading the verified Windows application instead...
if not exist "%PORTABLE_DIR%" mkdir "%PORTABLE_DIR%"
curl.exe -fL --retry 3 "%RELEASE%/Forge-3.0-windows-x64.exe" -o "%DOWNLOAD%"
if errorlevel 1 goto :python_missing
curl.exe -fL --retry 3 "%RELEASE%/SHA256SUMS.txt" -o "%SUMS%"
if errorlevel 1 goto :python_missing
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
  "$line=(Select-String -LiteralPath '%SUMS%' -Pattern 'Forge-3.0-windows-x64.exe').Line; if(-not $line){exit 1}; $expected=($line -split '\s+')[0].ToLowerInvariant(); $actual=(Get-FileHash -Algorithm SHA256 -LiteralPath '%DOWNLOAD%').Hash.ToLowerInvariant(); if($actual -ne $expected){exit 2}"
if errorlevel 1 goto :checksum_failed
move /Y "%DOWNLOAD%" "%PORTABLE_EXE%" >nul

:portable_launch
if /I "%~1"=="--setup-only" (
    echo FORGE 3.0 portable build verified
    exit /b 0
)
"%PORTABLE_EXE%" %*
exit /b %ERRORLEVEL%

:venv_failed
echo [FORGE 3.0] Failed to create .venv with Python 3.10 or newer.
exit /b 1

:install_failed
echo [FORGE 3.0] Dependency installation failed. Check the connection and rerun forge.bat.
exit /b 1

:checksum_failed
del /Q "%DOWNLOAD%" 2>nul
echo [FORGE 3.0] The downloaded application failed SHA-256 verification.
exit /b 1

:python_missing
del /Q "%DOWNLOAD%" 2>nul
echo [FORGE 3.0] Install Python 3.10+ or download Forge-3.0-windows-x64.exe from:
echo https://github.com/twaai/forge/releases/latest
exit /b 1
