@echo off
echo ========================================
echo    Shayra AI TTS - Production Server
echo ========================================
echo.

REM Change to script directory
cd /d "%~dp0"

REM Set production environment
set FLASK_ENV=production
set HOST=0.0.0.0
set PORT=5000

REM Check if virtual environment exists
if exist "venv\Scripts\activate.bat" (
    echo Activating virtual environment...
    call venv\Scripts\activate.bat
)

REM Install/upgrade dependencies
echo Installing dependencies...
pip install -r requirements.txt --quiet

echo.
echo Starting production server on http://%HOST%:%PORT%
echo Press Ctrl+C to stop the server
echo.

python app.py
