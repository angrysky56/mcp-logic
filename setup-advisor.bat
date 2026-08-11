@echo off
REM setup-advisor.bat — Install the onboard logic advisor (TwIL-LM3) on Windows
REM
REM Auto-detects NVIDIA GPU and installs llama-cpp-python with CUDA or CPU.
REM
REM Usage:
REM   setup-advisor.bat              Auto-detect GPU
REM   setup-advisor.bat --cpu        Force CPU-only
REM   setup-advisor.bat --skip-download  Skip model download

setlocal EnableDelayedExpansion

set "FORCE_CPU=false"
set "SKIP_DOWNLOAD=false"

:parse_args
if "%~1"=="" goto :end_parse
if /I "%~1"=="--cpu" set "FORCE_CPU=true"
if /I "%~1"=="--skip-download" set "SKIP_DOWNLOAD=true"
if /I "%~1"=="--help" goto :show_help
if /I "%~1"=="-h" goto :show_help
shift
goto :parse_args

:show_help
echo Usage: %~nx0 [--cpu] [--skip-download]
echo   --cpu            Force CPU-only (no GPU acceleration)
echo   --skip-download  Install deps only, skip model download
exit /b 0

:end_parse

set "PROJECT_DIR=%~dp0"
set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"

echo [ADVISOR SETUP] Detecting platform...

REM ── Detect NVIDIA GPU ────────────────────────────────────────────────
set "CMAKE_ARGS="
set "ACCEL_NAME=CPU (no acceleration)"

if "%FORCE_CPU%"=="true" (
    echo   CPU-only mode forced via --cpu flag
) else (
    where nvidia-smi >nul 2>&1
    if !ERRORLEVEL! equ 0 (
        set "CMAKE_ARGS=-DGGML_CUDA=on"
        set "ACCEL_NAME=CUDA (NVIDIA GPU)"
        for /f "tokens=*" %%g in ('nvidia-smi --query-gpu=name --format=csv,noheader 2^>nul') do (
            echo   Detected NVIDIA GPU: %%g
        )
        echo   Using CUDA acceleration
    ) else (
        echo   No NVIDIA GPU detected, using CPU-only mode
    )
)

echo [ADVISOR SETUP] Acceleration: %ACCEL_NAME%

REM ── Check for uv ────────────────────────────────────────────────────
where uv >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] 'uv' is not installed. Install it first:
    echo   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    exit /b 1
)

REM ── Ensure venv exists ──────────────────────────────────────────────
if not exist "%PROJECT_DIR%\.venv" (
    echo [ADVISOR SETUP] Creating virtual environment...
    uv venv --directory "%PROJECT_DIR%"
)

REM ── Install llama-cpp-python ────────────────────────────────────────
echo [ADVISOR SETUP] Installing llama-cpp-python (this may take several minutes to compile)...

if defined CMAKE_ARGS (
    if not "%CMAKE_ARGS%"=="" (
        echo   CMAKE_ARGS=%CMAKE_ARGS%
        set "CMAKE_ARGS=%CMAKE_ARGS%"
    )
)

uv pip install --directory "%PROJECT_DIR%" --reinstall-package llama-cpp-python "llama-cpp-python>=0.3.0"

REM ── Install huggingface-hub ─────────────────────────────────────────
echo [ADVISOR SETUP] Installing huggingface-hub...
uv pip install --directory "%PROJECT_DIR%" "huggingface-hub>=0.24.0"

REM ── Download model ──────────────────────────────────────────────────
set "MODEL_DIR=%USERPROFILE%\.cache\mcp-logic\models"
set "MODEL_FILE=%MODEL_DIR%\TwIL-LM3-Q8_0.gguf"

if "%SKIP_DOWNLOAD%"=="true" (
    echo [WARNING] Skipping model download. Model will auto-download on first use.
    goto :done
)

if exist "%MODEL_FILE%" (
    echo [ADVISOR SETUP] Model already downloaded: %MODEL_FILE%
    goto :done
)

echo [ADVISOR SETUP] Downloading TwIL-LM3-Q8_0.gguf (~3.3 GB)...
echo   Destination: %MODEL_DIR%\
if not exist "%MODEL_DIR%" mkdir "%MODEL_DIR%"

uv run --directory "%PROJECT_DIR%" python -c "from huggingface_hub import hf_hub_download; hf_hub_download(repo_id='webAI-Official/TwIL-LM3', filename='TwIL-LM3-Q8_0.gguf', local_dir=r'%MODEL_DIR%', local_dir_use_symlinks=False); print('Download complete!')"

:done
echo.
echo [ADVISOR SETUP] Logic advisor setup complete!
echo.
echo   Acceleration:  %ACCEL_NAME%
if exist "%MODEL_FILE%" (
    echo   Model:         %MODEL_FILE%
) else (
    echo   Model:         Will auto-download on first use
)
echo.
echo   The advisor is now available as the 'ask_logic_advisor' MCP tool.
echo   To disable it, add --no-advisor when starting the server.
echo.

endlocal
