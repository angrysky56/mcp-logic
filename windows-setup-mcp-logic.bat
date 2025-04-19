@echo off
setlocal EnableDelayedExpansion

echo [MCP-LOGIC SETUP] Starting setup...

:: Check dependencies
echo [MCP-LOGIC SETUP] Checking dependencies...

:: Check for git
where git >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Git is not installed. Please install it and try again.
    exit /b 1
)

:: Check for cmake
where cmake >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo [ERROR] CMake is not installed. Please install it and try again.
    exit /b 1
)

:: Check for Python
where python >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Python is not installed. Please install it and try again.
    exit /b 1
)

:: Get the current directory
set "MCP_LOGIC_ROOT=%CD%"

:: Setup LADR (Prover9)
echo [MCP-LOGIC SETUP] Setting up LADR (Prover9)...

:: Check if LADR directory already exists
if exist "%MCP_LOGIC_ROOT%\ladr" (
    echo [WARNING] LADR directory already exists at %MCP_LOGIC_ROOT%\ladr
    set /p CHOICE="Do you want to remove it and clone again? (y/n) "
    if /i "%CHOICE%"=="y" (
        rd /s /q "%MCP_LOGIC_ROOT%\ladr"
    ) else (
        echo [MCP-LOGIC SETUP] Using existing LADR directory.
        goto :SkipLADR
    )
)

:: Clone the LADR repository
echo [MCP-LOGIC SETUP] Cloning LADR repository...
git clone https://github.com/laitep/ladr.git "%MCP_LOGIC_ROOT%\ladr"

:: Build LADR
echo [MCP-LOGIC SETUP] Building LADR...
cd "%MCP_LOGIC_ROOT%\ladr"

:: Create build directory
mkdir build
cd build

:: Run CMake
cmake ..
cmake --build . --config Release

:: Check if prover9 was successfully built
if exist "%MCP_LOGIC_ROOT%\ladr\bin\prover9.exe" (
    echo [MCP-LOGIC SETUP] LADR (Prover9) built successfully!
) else if exist "%MCP_LOGIC_ROOT%\ladr\bin\prover9" (
    echo [MCP-LOGIC SETUP] Creating prover9.exe symlink for Windows compatibility
    :: Windows doesn't have native symlinks like Linux; copy the file instead
    copy "%MCP_LOGIC_ROOT%\ladr\bin\prover9" "%MCP_LOGIC_ROOT%\ladr\bin\prover9.exe"
) else (
    echo [ERROR] Failed to build LADR (Prover9). Please check the build logs.
    exit /b 1
)

:SkipLADR

:: Return to the MCP-Logic root directory
cd "%MCP_LOGIC_ROOT%"

:: Setup virtual environment
echo [MCP-LOGIC SETUP] Setting up Python virtual environment...

:: Check if virtual environment already exists
if exist "%MCP_LOGIC_ROOT%\.venv" (
    echo [WARNING] Virtual environment already exists at %MCP_LOGIC_ROOT%\.venv
    set /p CHOICE="Do you want to remove it and create a new one? (y/n) "
    if /i "%CHOICE%"=="y" (
        rd /s /q "%MCP_LOGIC_ROOT%\.venv"
    ) else (
        echo [MCP-LOGIC SETUP] Using existing virtual environment.
        goto :SkipVenv
    )
)

:: Create virtual environment
echo [MCP-LOGIC SETUP] Creating virtual environment...
pip install uv
uv venv

:: Activate virtual environment and install dependencies
echo [MCP-LOGIC SETUP] Installing dependencies...
call .venv\Scripts\activate.bat
uv pip install -e .

echo [MCP-LOGIC SETUP] Virtual environment setup complete.

:SkipVenv

:: Create Docker files and configurations
echo [MCP-LOGIC SETUP] Creating configuration files...

:: Create Dockerfile
echo [MCP-LOGIC SETUP] Creating Dockerfile...
(
echo # Dockerfile for mcp-logic with Prover9
echo FROM python:3.12-slim
echo.
echo # Install basic dependencies
echo RUN apt-get update ^&^& apt-get install -y \
echo     git \
echo     cmake \
echo     build-essential \
echo     ^&^& apt-get clean \
echo     ^&^& rm -rf /var/lib/apt/lists/*
echo.
echo # Set working directory
echo WORKDIR /app
echo.
echo # Copy application
echo COPY . .
echo.
echo # Create Python virtual environment in the correct location
echo RUN pip install uv
echo RUN uv venv .venv
echo ENV PATH="/app/.venv/bin:$PATH"
echo.
echo # Install Python dependencies with specific versions
echo RUN pip install --upgrade pip
echo RUN pip install -e .
echo.
echo # Clone and build LADR (Prover9)
echo RUN git clone https://github.com/laitep/ladr.git /app/ladr
echo WORKDIR /app/ladr
echo RUN mkdir -p build && cd build && cmake .. && make
echo RUN ln -s /app/ladr/bin/prover9 /app/ladr/bin/prover9.exe
echo.
echo # Return to app directory
echo WORKDIR /app
echo.
echo # Expose ports - try multiple ports in case some are in use
echo EXPOSE 8888 8889 8890 8891 8892
echo.
echo # Command to run the server
echo CMD ["sh", "-c", "uv --directory /app/src/mcp_logic run mcp_logic --prover-path /app/ladr/bin"]
) > "%MCP_LOGIC_ROOT%\Dockerfile"

:: Create Windows run script
echo [MCP-LOGIC SETUP] Creating run-mcp-logic.bat...
(
echo @echo off
echo setlocal EnableDelayedExpansion
echo.
echo :: Port selection - try several ports
echo set PORT=8888
echo.
echo :: Path to local Prover9 installation
echo set PROVER9_PATH=%%CD%%\ladr\bin
echo.
echo :: Show info
echo echo Using port %%PORT%%
echo echo Using Prover9 from %%PROVER9_PATH%%
echo.
echo :: Build the Docker image
echo echo Building Docker image...
echo docker build -t mcp-logic .
echo.
echo if %%ERRORLEVEL%% EQU 0 ^(
echo   echo Build successful! Running container on port %%PORT%%...
echo   
echo   :: Kill any existing container with the same name
echo   docker kill mcp-logic 2^>nul
echo   docker rm mcp-logic 2^>nul
echo   
echo   :: Run the container with the local Prover9 binaries mounted
echo   :: Convert Windows paths to Docker paths
echo   set DOCKER_SRC=%%CD%%\src
echo   set DOCKER_SRC=!DOCKER_SRC:\=/!
echo   
echo   set DOCKER_PROVER9=%%PROVER9_PATH%%
echo   set DOCKER_PROVER9=!DOCKER_PROVER9:\=/!
echo   
echo   docker run -it --rm ^^^
echo     -p %%PORT%%:8888 ^^^
echo     -v !DOCKER_SRC!:/app/src ^^^
echo     -v !DOCKER_PROVER9!:/usr/local/prover9-mount ^^^
echo     --name mcp-logic ^^^
echo     mcp-logic
echo ^) else ^(
echo   echo Build failed. Check the logs above for details.
echo ^)
) > "%MCP_LOGIC_ROOT%\run-mcp-logic.bat"

:: Create Claude app config for direct non-Docker use
echo [MCP-LOGIC SETUP] Creating claude-app-config.json...
(
echo {
echo   "mcpServers": {
echo     "mcp-logic": {
echo       "command": "uv",
echo       "args": [
echo         "--directory", 
echo         "%MCP_LOGIC_ROOT:\=/%/src/mcp_logic",
echo         "run", 
echo         "mcp_logic", 
echo         "--prover-path", 
echo         "%MCP_LOGIC_ROOT:\=/%/ladr/bin"
echo       ]
echo     }
echo   }
echo }
) > "%MCP_LOGIC_ROOT%\claude-app-config.json"

echo [MCP-LOGIC SETUP] Configuration files created successfully!
echo [MCP-LOGIC SETUP] Setup completed successfully!
echo [MCP-LOGIC SETUP] To run the MCP-Logic server with Docker, use: run-mcp-logic.bat
echo [MCP-LOGIC SETUP] For Claude Desktop integration, use the configuration in claude-app-config.json

endlocal