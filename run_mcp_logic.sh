#!/bin/bash
# Simple run script for MCP-Logic server (Linux/macOS)
# This runs the server directly without Docker

# Project and Prover9 paths
PROJECT_PATH="$(cd "$(dirname "$0")" && pwd)"
PROVER9_PATH="$PROJECT_PATH/ladr/bin"

echo "MCP-Logic Server"
echo "================"
echo "Project: $PROJECT_PATH"
echo "LADR binaries: $PROVER9_PATH"
echo ""

# Create and activate virtual environment if it doesn't exist
if [ ! -d "$PROJECT_PATH/.venv" ]; then
    echo "Creating virtual environment..."
    pip install uv
    uv venv
    source "$PROJECT_PATH/.venv/bin/activate"
    uv pip install -e .
else
    source "$PROJECT_PATH/.venv/bin/activate"
fi

# Run the server
echo "Starting MCP-Logic server..."
uv --directory "$PROJECT_PATH/src/mcp_logic" run mcp_logic --prover-path "$PROVER9_PATH"
