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

if [ $PORT -eq 0 ]; then
    echo "Error: All ports are in use. Please free up one of these ports: ${PORTS[*]}"
    exit 1
fi

# Path to local Prover9 installation
PROVER9_PATH="/home/ty/Repositories/mcp-logic/ladr/bin"

# Show info
echo "Using port $PORT"
echo "Using Prover9 from $PROVER9_PATH"

# Build the Docker image
echo "Building Docker image..."
docker build -t mcp-logic .

if [ $? -eq 0 ]; then
  echo "Build successful! Running container on port $PORT..."
  
  # Kill any existing container with the same name
  docker kill mcp-logic 2>/dev/null || true
  docker rm mcp-logic 2>/dev/null || true
  
  # Run the container with the local Prover9 binaries mounted
  docker run -it --rm \
    -p $PORT:8888 \
    -v "$(pwd)/src:/app/src" \
    -v "$PROVER9_PATH:/usr/local/prover9-mount" \
    --name mcp-logic \
    mcp-logic
else
  echo "Build failed. Check the logs above for details."
fi
