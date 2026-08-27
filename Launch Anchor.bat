@echo off
cd /d "%~dp0"

echo Starting Anchor...

start "Anchor Backend" ".venv\Scripts\python.exe" -m uvicorn anchor.api:app

start "Anchor Frontend" /D "%~dp0web" "%ProgramFiles%\nodejs\npm.cmd" run dev

echo Waiting for Anchor...

for /L %%i in (1,1,20) do (
    curl.exe -s -f http://localhost:5173/ >nul 2>&1 && goto ready
    timeout /t 1 /nobreak >nul
)

:ready
start "" http://localhost:5173

exit