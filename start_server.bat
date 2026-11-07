@echo off
rem ===========================================================
rem  Start the lost-and-found server and keep it running.
rem  - Production mode: no --reload (code changes need a restart).
rem  - If the server stops for any reason, it starts again in 10 seconds.
rem  - Server messages are saved to logs\server.log (open with Notepad).
rem  How to stop: close this window (or press Ctrl+C, then Y).
rem ===========================================================
cd /d "%~dp0"
if not exist logs mkdir logs
set PYTHONUTF8=1

:loop
echo [%date% %time%] starting server... (log: logs\server.log)
echo [%date% %time%] starting server >> logs\server.log
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8000 >> logs\server.log 2>&1
echo [%date% %time%] server stopped. restarting in 10 seconds... >> logs\server.log
echo server stopped. restarting in 10 seconds... (close this window to stop)
timeout /t 10 /nobreak > nul
goto loop
