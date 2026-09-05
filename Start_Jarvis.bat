@echo off
setlocal
cd /d "%~dp0"
title J.A.R.V.I.S.

echo ============================================
echo   J.A.R.V.I.S. - Mark XLVIII
echo ============================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [FEHLER] Python wurde nicht gefunden.
    echo Bitte installiere Python 3.11+ von https://python.org und stelle
    echo sicher, dass beim Setup "Add Python to PATH" aktiviert war.
    echo.
    pause
    exit /b 1
)

if not exist "config\api_keys.json" (
    echo [HINWEIS] config\api_keys.json wurde nicht gefunden.
    echo Kopiere config\api_keys.example.json nach config\api_keys.json
    echo und trage zumindest deinen gemini_api_key ein, bevor du fortfaehrst.
    echo.
    pause
)

if not exist ".venv\Scripts\python.exe" (
    echo [Setup] Erstelle virtuelle Umgebung ".venv" ...
    python -m venv .venv
    if errorlevel 1 (
        echo [FEHLER] Virtuelle Umgebung konnte nicht erstellt werden.
        pause
        exit /b 1
    )
)

call ".venv\Scripts\activate.bat"

if not exist ".venv\.requirements_installed" (
    echo [Setup] Installiere Python-Abhaengigkeiten ^(einmalig, kann dauern^) ...
    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [FEHLER] Installation der Abhaengigkeiten fehlgeschlagen.
        pause
        exit /b 1
    )
    python -m playwright install
    echo done > ".venv\.requirements_installed"
)

echo.
echo Starte J.A.R.V.I.S. ...
echo.
python main.py

echo.
echo J.A.R.V.I.S. wurde beendet.
pause
