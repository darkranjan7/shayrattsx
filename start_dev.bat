@echo off
echo ========================================
echo    Shayra AI TTS - Development Server
echo ========================================
echo.

REM Change to script directory
cd /d "%~dp0"

REM Set development environment
set FLASK_ENV=development
set HOST=127.0.0.1
set PORT=5000

REM Check if virtual environment exists
if exist "venv\Scripts\activate.bat" (
    echo Activating virtual environment...
    call venv\Scripts\activate.bat
)

echo.
echo Starting development server on http://%HOST%:%PORT%
echo Press Ctrl+C to stop the server
echo.

python app.py
