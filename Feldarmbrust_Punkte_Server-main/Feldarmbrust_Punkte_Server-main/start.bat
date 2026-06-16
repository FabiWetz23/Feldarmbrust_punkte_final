@echo off
REM Start script for Feldarmbrust Punkte Server
REM Uses the virtual environment python directly

pushd "%~dp0"
if not exist "venv\Scripts\python.exe" (
    echo Virtual environment not found! Please run setup first.
    pause
    exit /b 1
)

echo Starting server...
venv\Scripts\python.exe start_server.py
if errorlevel 1 pause
popd
