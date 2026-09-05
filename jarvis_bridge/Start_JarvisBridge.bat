@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
title Jarvis Bridge

echo ============================================
echo   Jarvis Bridge (Browser + WhatsApp + Memory)
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
    echo Dein Bridge-Token wurde erzeugt und in bridge_token.txt gespeichert.
    echo Trage ihn in der Chrome-Extension ^(extension\-Ordner laden, dann Popup^) ein.
    echo.
)
set /p JARVIS_TOKEN=<bridge_token.txt

if not exist "owner_number.txt" (
    echo.
    echo WhatsApp ist optional. Leer lassen und Enter druecken, um es zu ueberspringen.
    set /p OWNERNUM="Deine WhatsApp-Nummer (z.B. 015568810689) oder leer: "
    echo !OWNERNUM! > "owner_number.txt"
)
set /p JARVIS_WA_OWNER_NUMBER=<owner_number.txt

echo.
echo Browser-Bridge:  ws://localhost:8080  (Token in bridge_token.txt)
echo HTTP-API:        http://localhost:3000  (gleicher Token)
if not "%JARVIS_WA_OWNER_NUMBER%"=="" (
    echo WhatsApp:        aktiviert fuer %JARVIS_WA_OWNER_NUMBER% - beim ersten Start QR-Code scannen
) else (
    echo WhatsApp:        deaktiviert ^(owner_number.txt ist leer^)
)
echo.
node server.js

echo.
echo Jarvis Bridge wurde beendet.
pause
