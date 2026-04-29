@echo off
cd /d "%~dp0"
echo Starting TrendForge AI Video Generator...

set "PYTHON_EXE=python"
if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=.venv\Scripts\python.exe"
    echo Using .venv Python.
) else (
    echo Using system Python. Create .venv for a pinned GPU runtime.
)

REM Check if --skip-ui flag is passed (for CLI mode)
if /I not "%~1"=="--skip-ui" goto launch_ui
set "CLI_ARGS=%*"
set "CLI_ARGS=%CLI_ARGS:~9%"
if "%CLI_ARGS:~0,1%"==" " set "CLI_ARGS=%CLI_ARGS:~1%"
"%PYTHON_EXE%" main.py %CLI_ARGS%
exit /b %errorlevel%

REM Default: Open FastAPI server for the new UI
:launch_ui
set "TRENDFORGE_PORT=8510"
echo Opening TrendForge UI...
start "" "http://127.0.0.1:%TRENDFORGE_PORT%"
"%PYTHON_EXE%" server.py
