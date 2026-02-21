@echo off
REM Polymarket Trading Agent - Single Run
REM Directories are auto-created by config/paths.py on import.
REM Set WORKSPACE_DIR in .env to change workspace location.

cd /d %~dp0

REM === Run Agent ===
python -m agent.scheduler --once
