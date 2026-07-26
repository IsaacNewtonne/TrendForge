@echo off
cd /d "%~dp0"
echo Starting TrendForge AI Video Generator...

set "PYTHONDONTWRITEBYTECODE=1"
set "TEMP=%CD%\temp\runtime"
set "TMP=%CD%\temp\runtime"
set "TMPDIR=%CD%\temp\runtime"
if not exist "%TEMP%" mkdir "%TEMP%"

if "%HTTP_PROXY%"=="http://127.0.0.1:9" set "HTTP_PROXY="
if "%HTTPS_PROXY%"=="http://127.0.0.1:9" set "HTTPS_PROXY="
if "%ALL_PROXY%"=="http://127.0.0.1:9" set "ALL_PROXY="
if "%http_proxy%"=="http://127.0.0.1:9" set "http_proxy="
if "%https_proxy%"=="http://127.0.0.1:9" set "https_proxy="
if "%all_proxy%"=="http://127.0.0.1:9" set "all_proxy="

set "PYTHON_EXE=python"
if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=.venv\Scripts\python.exe"
    echo Using .venv Python.
) else (
    echo Using system Python. Create .venv for a pinned GPU runtime.
)

echo Checking and installing startup dependencies...
"%PYTHON_EXE%" -B bootstrap.py
if errorlevel 1 (
    echo TrendForge startup stopped because dependency setup failed.
    pause
    exit /b 1
)

REM Check if --skip-ui flag is passed (for CLI mode)
if /I not "%~1"=="--skip-ui" goto launch_ui
set "CLI_ARGS=%*"
set "CLI_ARGS=%CLI_ARGS:~9%"
if "%CLI_ARGS:~0,1%"==" " set "CLI_ARGS=%CLI_ARGS:~1%"
"%PYTHON_EXE%" -B main.py %CLI_ARGS%
exit /b %errorlevel%

REM Default: Open FastAPI server for the new UI
:launch_ui
set "TRENDFORGE_PORT=8510"
echo Opening TrendForge UI...
start "" "http://127.0.0.1:%TRENDFORGE_PORT%"
"%PYTHON_EXE%" -B server.py
