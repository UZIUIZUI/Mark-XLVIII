@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
title Jarvis - Browser Bridge

echo ============================================
echo   Jarvis Browser Bridge (optional)
echo ============================================
echo.

where node >nul 2>nul
if errorlevel 1 (
    echo [FEHLER] Node.js wurde nicht gefunden.
    echo Installiere es von https://nodejs.org und starte diese Datei erneut.
    echo.
    pause
    exit /b 1
)

if not exist "node_modules" (
    echo [Setup] Installiere Abhaengigkeiten ^(einmalig, kann dauern^) ...
    call npm install
    if errorlevel 1 (
        echo [FEHLER] npm install fehlgeschlagen.
        pause
        exit /b 1
    )
)

if not exist "bridge_token.txt" (
    echo [Setup] Erzeuge Sicherheits-Token ...
    for /f "delims=" %%T in ('node -e "console.log(require(\"crypto\").randomBytes(24).toString(\"hex\"))"') do set NEWTOKEN=%%T
    echo !NEWTOKEN! > "bridge_token.txt"
    echo.
    echo Dein Bridge-Token wurde erzeugt und in bridge_token.txt gespeichert:
    echo !NEWTOKEN!
    echo Trage ihn in der Chrome-Extension ^(Popup^) ein, damit sie sich verbinden kann.
    echo.
)

set /p JARVIS_BRIDGE_TOKEN=<bridge_token.txt

echo.
echo Starte Browser Bridge auf ws://localhost:8080 ...
echo ^(Token in bridge_token.txt - fuer die Chrome-Extension benoetigt^)
echo.
node server.js

echo.
echo Browser Bridge wurde beendet.
pause
