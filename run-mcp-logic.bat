@echo off
setlocal EnableDelayedExpansion

:: Port selection - try several ports
set PORTS=8888 8889 8890 8891 8892
set PORT=0

:: Find an available port (Windows doesn't have an easy way to check ports)
:: We'll just use 8888 for simplicity, the Docker service will tell us if it's in use
set PORT=8888

:: Path to local Prover9 installation - convert to Windows path format
set PROVER9_PATH=%CD%\ladr\bin

:: Show info
echo Using port %PORT%
echo Using Prover9 from %PROVER9_PATH%

:: Build the Docker image
echo Building Docker image...
docker build -t mcp-logic .

if %ERRORLEVEL% EQU 0 (
  echo Build successful! Running container on port %PORT%...
  
  :: Kill any existing container with the same name
  docker kill mcp-logic 2>nul
  docker rm mcp-logic 2>nul
  
  :: Run the container with the local Prover9 binaries mounted
  :: Convert Windows paths to Docker paths
  set DOCKER_SRC=%CD%\src
  set DOCKER_SRC=!DOCKER_SRC:\=/!
  
  set DOCKER_PROVER9=%PROVER9_PATH%
  set DOCKER_PROVER9=!DOCKER_PROVER9:\=/!
  
  docker run -it --rm ^
    -p %PORT%:8888 ^
    -v !DOCKER_SRC!:/app/src ^
    -v !DOCKER_PROVER9!:/usr/local/prover9-mount ^
    --name mcp-logic ^
    mcp-logic
) else (
  echo Build failed. Check the logs above for details.
)
