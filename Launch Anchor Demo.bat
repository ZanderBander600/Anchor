@echo off
setlocal
cd /d "%~dp0"

rem Runs Anchor against the demo database (data\demo.db) instead of data\anchor.db.
rem Backup:  copy /Y "data\demo.db" "data\demo.backup.db"
rem Restore: close both Anchor windows first, then
rem          copy /Y "data\demo.backup.db" "data\demo.db"

set "ANCHOR_DB_PATH=%~dp0data\demo.db"

if not exist "%ANCHOR_DB_PATH%" (
    echo Demo database not found: %ANCHOR_DB_PATH%
    echo Run: .venv\Scripts\python.exe seed_demo_deal.py
    pause
    exit /b 1
)

rem Refuse to start if another Anchor backend already holds port 8000; the
rem browser would otherwise talk to that backend and its database.
netstat -ano | findstr /R /C:":8000 .*LISTENING" >nul && (
    echo Port 8000 is already in use. Close the other Anchor backend window and try again.
    pause
    exit /b 1
)

echo Starting Anchor Demo using %ANCHOR_DB_PATH%

start "Anchor Demo Backend" ".venv\Scripts\python.exe" -m uvicorn anchor.api:app

start "Anchor Demo Frontend" /D "%~dp0web" "%ProgramFiles%\nodejs\npm.cmd" run dev

echo Waiting for Anchor...

for /L %%i in (1,1,20) do (
    curl.exe -s -f http://localhost:5173/ >nul 2>&1 && goto ready
    timeout /t 1 /nobreak >nul
)

:ready
start "" http://localhost:5173

exit
