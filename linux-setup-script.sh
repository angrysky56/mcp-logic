#!/bin/bash

# Color codes for pretty output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

# Print colorized message
function print_message() {
    echo -e "${GREEN}[MCP-LOGIC SETUP]${NC} $1"
}

function print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

function print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if dependencies are installed
function check_dependencies() {
    print_message "Checking dependencies..."
    
    # Check for git
    if ! command -v git &> /dev/null; then
        print_error "Git is not installed. Please install it with: sudo apt-get install git"
        exit 1
    fi
    
    # Check for docker
    if ! command -v docker &> /dev/null; then
        print_error "Docker is not installed. Please follow the instructions at https://docs.docker.com/engine/install/"
        exit 1
    fi
    
    # Check for cmake
    if ! command -v cmake &> /dev/null; then
        print_error "CMake is not installed. Please install it with: sudo apt-get install cmake"
        exit 1
    fi
    
    # Check for build essentials
    if ! command -v g++ &> /dev/null; then
        print_error "Build tools are not installed. Please install them with: sudo apt-get install build-essential"
        exit 1
    fi
    
    print_message "All dependencies are installed."
}

# Clone and build LADR (Prover9)
function setup_ladr() {
    print_message "Setting up LADR (Prover9)..."
    
    # Get the current directory (MCP-Logic project root)
    MCP_LOGIC_ROOT="$(pwd)"
    
    # Check if LADR directory already exists
    if [ -d "$MCP_LOGIC_ROOT/ladr" ]; then
        print_warning "LADR directory already exists at $MCP_LOGIC_ROOT/ladr"
        read -p "Do you want to remove it and clone again? (y/n) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            rm -rf "$MCP_LOGIC_ROOT/ladr"
        else
            print_message "Using existing LADR directory."
            return
        fi
    fi
    
    # Clone the LADR repository
    print_message "Cloning LADR repository..."
    git clone https://github.com/laitep/ladr.git "$MCP_LOGIC_ROOT/ladr"
    
    # Build LADR
    print_message "Building LADR..."
    cd "$MCP_LOGIC_ROOT/ladr" || exit
    
    # Check if run_cmake.sh exists
    if [ -f "./run_cmake.sh" ]; then
        chmod +x ./run_cmake.sh
        ./run_cmake.sh
    else
        # Manual build if script doesn't exist
        mkdir -p build
        cd build || exit
        cmake ..
        make
        make install
    fi
    
    # Check if prover9 was successfully built
    if [ -f "$MCP_LOGIC_ROOT/ladr/bin/prover9" ]; then
        print_message "LADR (Prover9) built successfully!"
        
        # Create a symlink for Windows compatibility if it doesn't exist
        if [ ! -f "$MCP_LOGIC_ROOT/ladr/bin/prover9.exe" ]; then
            ln -s "$MCP_LOGIC_ROOT/ladr/bin/prover9" "$MCP_LOGIC_ROOT/ladr/bin/prover9.exe"
            print_message "Created prover9.exe symlink for Windows compatibility"
        fi
    else
        print_error "Failed to build LADR (Prover9). Please check the build logs."
        exit 1
    fi
    
    # Return to the MCP-Logic root directory
    cd "$MCP_LOGIC_ROOT" || exit
}

# Setup virtual environment
function setup_venv() {
    print_message "Setting up Python virtual environment..."
    
    # Get the current directory (MCP-Logic project root)
    MCP_LOGIC_ROOT="$(pwd)"
    
    # Check if virtual environment already exists
    if [ -d "$MCP_LOGIC_ROOT/.venv" ]; then
        print_warning "Virtual environment already exists at $MCP_LOGIC_ROOT/.venv"
        read -p "Do you want to remove it and create a new one? (y/n) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            rm -rf "$MCP_LOGIC_ROOT/.venv"
        else
            print_message "Using existing virtual environment."
            return
        fi
    fi
    
    # Create virtual environment
    print_message "Creating virtual environment..."
    cd "$MCP_LOGIC_ROOT" || exit
    pip install uv
    uv venv
    
    # Activate virtual environment and install dependencies
    print_message "Installing dependencies..."
    # shellcheck disable=SC1091
    source "$MCP_LOGIC_ROOT/.venv/bin/activate"
    uv pip install -e .
    
    print_message "Virtual environment setup complete."
}

# Create Docker files
function create_docker_files() {
    print_message "Creating Docker files..."
    
    # Get the current directory (MCP-Logic project root)
    MCP_LOGIC_ROOT="$(pwd)"
    LADR_BIN_PATH="$MCP_LOGIC_ROOT/ladr/bin"
    
    # Create Dockerfile
    cat > "$MCP_LOGIC_ROOT/Dockerfile" << EOF
# Dockerfile for mcp-logic with Prover9
FROM python:3.12-slim

# Install basic dependencies
RUN apt-get update && apt-get install -y \\
    git \\
    curl \\
    && apt-get clean \\
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy application
COPY . .

# Create Python virtual environment in the correct location
RUN pip install uv
RUN uv venv .venv
ENV PATH="/app/.venv/bin:\$PATH"

# Install Python dependencies with specific versions
RUN pip install --upgrade pip
RUN pip install -e .
RUN pip install requests==2.31.0
RUN pip install docker>=7.0.0

# Install other requirements if they exist
RUN if [ -f requirements.txt ]; then pip install -r requirements.txt; fi

# Create a directory to mount the local Prover9 binaries
RUN mkdir -p /usr/local/prover9-mount

# Create a wrapper script for Windows compatibility
RUN echo '#!/bin/bash' > /usr/local/prover9-mount/prover9.exe && \\
    echo '/usr/local/prover9-mount/prover9 "\$@"' >> /usr/local/prover9-mount/prover9.exe && \\
    chmod +x /usr/local/prover9-mount/prover9.exe

# Set environment variables
ENV DOCKER_HOST=unix:///var/run/docker.sock

# Expose ports - try multiple ports in case some are in use
EXPOSE 8888 8889 8890 8891 8892

# Command to run the server
CMD ["sh", "-c", "uv --directory /app/src/mcp_logic run mcp_logic --prover-path /usr/local/prover9-mount"]
EOF
    
    # Create Linux run script
    cat > "$MCP_LOGIC_ROOT/run-mcp-logic.sh" << EOF
#!/bin/bash

# Port selection - try several ports in case some are in use
PORTS=(8888 8889 8890 8891 8892)
PORT=0

# Find an available port
for test_port in "\${PORTS[@]}"; do
    if ! ss -tulpn | grep -q ":\$test_port "; then
        PORT=\$test_port
        break
    fi
done

if [ \$PORT -eq 0 ]; then
    echo "Error: All ports are in use. Please free up one of these ports: \${PORTS[*]}"
    exit 1
fi

# Path to local Prover9 installation
PROVER9_PATH="$LADR_BIN_PATH"

# Show info
echo "Using port \$PORT"
echo "Using Prover9 from \$PROVER9_PATH"

# Build the Docker image
echo "Building Docker image..."
docker build -t mcp-logic .

if [ \$? -eq 0 ]; then
  echo "Build successful! Running container on port \$PORT..."
  
  # Kill any existing container with the same name
  docker kill mcp-logic 2>/dev/null || true
  docker rm mcp-logic 2>/dev/null || true
  
  # Run the container with the local Prover9 binaries mounted
  docker run -it --rm \\
    -p \$PORT:8888 \\
    -v "\$(pwd)/src:/app/src" \\
    -v "\$PROVER9_PATH:/usr/local/prover9-mount" \\
    --name mcp-logic \\
    mcp-logic
else
  echo "Build failed. Check the logs above for details."
fi
EOF
    
    # Create Windows run script
    cat > "$MCP_LOGIC_ROOT/run-mcp-logic.bat" << EOF
@echo off
setlocal EnableDelayedExpansion

:: Port selection - try several ports
set PORTS=8888 8889 8890 8891 8892
set PORT=0

:: Find an available port (Windows doesn't have an easy way to check ports)
:: We'll just use 8888 for simplicity, the Docker service will tell us if it's in use
set PORT=8888

:: Path to local Prover9 installation - convert to Windows path format
set PROVER9_PATH=%CD%\\ladr\\bin

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
  set DOCKER_SRC=%CD%\\src
  set DOCKER_SRC=!DOCKER_SRC:\\=/!
  
  set DOCKER_PROVER9=%PROVER9_PATH%
  set DOCKER_PROVER9=!DOCKER_PROVER9:\\=/!
  
  docker run -it --rm ^
    -p %PORT%:8888 ^
    -v !DOCKER_SRC!:/app/src ^
    -v !DOCKER_PROVER9!:/usr/local/prover9-mount ^
    --name mcp-logic ^
    mcp-logic
) else (
  echo Build failed. Check the logs above for details.
)
EOF
    
    # Create local run script (non-Docker)
    cat > "$MCP_LOGIC_ROOT/run-mcp-logic-local.sh" << EOF
#!/bin/bash

# Port selection - try several ports in case some are in use
PORTS=(8888 8889 8890 8891 8892)
PORT=0

# Find an available port
for test_port in "\${PORTS[@]}"; do
    if ! ss -tulpn | grep -q ":\$test_port "; then
        PORT=\$test_port
        break
    fi
done

if [ \$PORT -eq 0 ]; then
    echo "Error: All ports are in use. Please free up one of these ports: \${PORTS[*]}"
    exit 1
fi

# Project and Prover9 paths
PROJECT_PATH="$MCP_LOGIC_ROOT"
PROVER9_PATH="\$PROJECT_PATH/ladr/bin"

# Show info
echo "Using port \$PORT"
echo "Using Prover9 from \$PROVER9_PATH"

# Create and activate virtual environment if it doesn't exist
if [ ! -d "\$PROJECT_PATH/.venv" ]; then
    echo "Creating virtual environment..."
    cd "\$PROJECT_PATH"
    pip install uv
    uv venv
    source "\$PROJECT_PATH/.venv/bin/activate"
    uv pip install -e .
else
    source "\$PROJECT_PATH/.venv/bin/activate"
fi

# Run the server
echo "Starting MCP-Logic server..."
cd "\$PROJECT_PATH"
uv --directory "\$PROJECT_PATH/src/mcp_logic" run mcp_logic --prover-path "\$PROVER9_PATH"
EOF
    
    # Create Claude app config for direct non-Docker use
    cat > "$MCP_LOGIC_ROOT/claude-app-config.json" << EOF
{
  "mcpServers": {
    "mcp-logic": {
      "command": "uv",
      "args": [
        "--directory", 
        "$MCP_LOGIC_ROOT/src/mcp_logic",
        "run", 
        "mcp_logic", 
        "--prover-path", 
        "$MCP_LOGIC_ROOT/ladr/bin"
      ]
    }
  }
}
EOF
    
    # Make the run scripts executable
    chmod +x "$MCP_LOGIC_ROOT/run-mcp-logic.sh"
    chmod +x "$MCP_LOGIC_ROOT/run-mcp-logic-local.sh"
    
    print_message "Configuration files created successfully!"
}

# Main setup function
function setup() {
    print_message "Starting MCP-Logic setup..."
    
    # Check dependencies
    check_dependencies
    
    # Setup LADR (Prover9)
    setup_ladr
    
    # Setup virtual environment
    setup_venv
    
    # Create Docker files
    create_docker_files
    
    print_message "Setup completed successfully!"
    print_message "To run the MCP-Logic server with Docker, use: ./run-mcp-logic.sh"
    print_message "For Claude Desktop integration, use the configuration in claude-app-config.json"
}

# Run the setup
setup