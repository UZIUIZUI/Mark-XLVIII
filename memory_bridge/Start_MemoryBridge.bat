@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
title Jarvis - Memory Bridge

echo ============================================
echo   Jarvis Memory Bridge (optional)
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

if not exist "..\browser_extension\node_modules" (
    echo [Setup] Installiere Abhaengigkeiten fuer browser_extension ^(wird fuer die Sprachausgabe benoetigt^) ...
    pushd "..\browser_extension"
    call npm install
    popd
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

if not exist "memory_token.txt" (
    echo [Setup] Erzeuge Sicherheits-Token ...
    for /f "delims=" %%T in ('node -e "console.log(require(\"crypto\").randomBytes(24).toString(\"hex\"))"') do set NEWTOKEN=%%T
    echo !NEWTOKEN! > "memory_token.txt"
)
set /p JARVIS_MEMORY_TOKEN=<memory_token.txt

echo.
echo Starte Memory Bridge ^(WebSocket: 8090, HTTP: 3200^) ...
echo.
node server.js

echo.
echo Memory Bridge wurde beendet.
pause
