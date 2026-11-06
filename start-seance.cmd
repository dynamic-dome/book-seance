@echo off
rem Starts Book Seance and opens the start page. Double-click to run.
title Book Seance
cd /d "%~dp0"
set URL=http://127.0.0.1:8642
curl -s -f -m 2 -o nul %URL%/api/backends && goto open
where uv >nul 2>nul || (echo uv was not found, see README.md. & pause & exit /b 1)
start "Book Seance server - close this window to stop" /min cmd /c "uv run uvicorn server:app --host 127.0.0.1 --port 8642"
echo Opening the book, this takes about 20 seconds ...
set /a tries=0
:wait
ping -n 2 127.0.0.1 >nul
curl -s -f -m 2 -o nul %URL%/api/backends && goto open
set /a tries+=1
if %tries% lss 90 goto wait
echo The server did not start. Is something else using port 8642?
pause
exit /b 1
:open
start "" %URL%/
