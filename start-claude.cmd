@echo off
rem Starts the seance with Claude through your own subscription. Double-click to run.
cd /d "%~dp0"
set SEANCE_LLM=claude
start "" "http://127.0.0.1:8642/"
uv run uvicorn server:app --host 127.0.0.1 --port 8642
