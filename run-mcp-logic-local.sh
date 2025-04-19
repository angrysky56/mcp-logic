#!/bin/bash

# Port selection - try several ports in case some are in use
PORTS=(8888 8889 8890 8891 8892)
PORT=0

# Find an available port
for test_port in "${PORTS[@]}"; do
    if ! ss -tulpn | grep -q ":$test_port "; then
        PORT=$test_port
        break
    fi
done

if [ "$PORT" -eq 0 ]; then
    echo "Error: All ports are in use. Please free up one of these ports: ${PORTS[*]}"
    exit 1
fi

# Project and Prover9 paths
PROJECT_PATH="/home/ty/Repositories/mcp-logic"
PROVER9_PATH="$PROJECT_PATH/ladr/bin"

# Show info
echo "Using port $PORT"
echo "Using Prover9 from $PROVER9_PATH"

# Create and activate virtual environment if it doesn't exist
if [ ! -d "$PROJECT_PATH/.venv" ]; then
    echo "Creating virtual environment..."
    cd "$PROJECT_PATH" || exit 1
    pip install uv
    uv venv
    # shellcheck disable=SC1091
    source "$PROJECT_PATH/.venv/bin/activate"
    uv pip install -e .
else
    # shellcheck disable=SC1091
    source "$PROJECT_PATH/.venv/bin/activate"
fi

# Run the server
echo "Starting MCP-Logic server..."
cd "$PROJECT_PATH" || exit 1
uv --directory "$PROJECT_PATH/src/mcp_logic" run mcp_logic --prover-path "$PROVER9_PATH"
