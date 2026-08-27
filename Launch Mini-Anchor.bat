@echo off
cd /d "%~dp0"

echo Starting Mini-Anchor...

start "Mini-Anchor Backend" ".venv\Scripts\python.exe" -m uvicorn mini_anchor.api:app

start "Mini-Anchor Frontend" /D "%~dp0web" "%ProgramFiles%\nodejs\npm.cmd" run dev

echo Waiting for Mini-Anchor...

for /L %%i in (1,1,20) do (
    curl.exe -s -f http://localhost:5173/ >nul 2>&1 && goto ready
    timeout /t 1 /nobreak >nul
)

:ready
start "" http://localhost:5173

exit