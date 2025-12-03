@echo off
REM Simple run script for MCP-Logic server (Windows)
REM This runs the server directly without Docker

setlocal

REM Get project path
set PROJECT_PATH=%~dp0
set PROVER9_PATH=%PROJECT_PATH%ladr\bin

echo MCP-Logic Server
echo ================
echo Project: %PROJECT_PATH%
echo LADR binaries: %PROVER9_PATH%
echo.

REM Create and activate virtual environment if it doesn't exist
if not exist "%PROJECT_PATH%.venv" (
    echo Creating virtual environment...
    pip install uv
    uv venv
    call "%PROJECT_PATH%.venv\Scripts\activate.bat"
    uv pip install -e .
) else (
    call "%PROJECT_PATH%.venv\Scripts\activate.bat"
)

REM Run the server
echo Starting MCP-Logic server...
uv --directory "%PROJECT_PATH%src\mcp_logic" run mcp_logic --prover-path "%PROVER9_PATH%"

endlocal
