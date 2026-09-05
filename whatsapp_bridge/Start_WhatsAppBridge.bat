@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
title Jarvis - WhatsApp Bridge

echo ============================================
echo   Jarvis WhatsApp Bridge (optional)
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

if not exist "owner_number.txt" (
    echo.
    set /p OWNERNUM="Deine eigene WhatsApp-Nummer (z.B. 015568810689): "
    echo !OWNERNUM! > "owner_number.txt"
)
set /p JARVIS_WA_OWNER_NUMBER=<owner_number.txt

if not exist "http_token.txt" (
    echo [Setup] Erzeuge Sicherheits-Token fuer die HTTP-API ...
    for /f "delims=" %%T in ('node -e "console.log(require(\"crypto\").randomBytes(24).toString(\"hex\"))"') do set NEWTOKEN=%%T
    echo !NEWTOKEN! > "http_token.txt"
)
set /p JARVIS_WA_HTTP_TOKEN=<http_token.txt

echo.
echo Eigene Nummer: %JARVIS_WA_OWNER_NUMBER%
echo HTTP-Token:    siehe http_token.txt
echo.
echo Beim ersten Start erscheint ein QR-Code - scanne ihn mit
echo WhatsApp (Einstellungen - Verknuepfte Geraete).
echo.
node JarvisWhatsApp.js

echo.
echo WhatsApp Bridge wurde beendet.
pause
