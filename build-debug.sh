#!/bin/bash

# Build with detailed output to debug compilation issues
echo "Building Docker image with debug output..."

docker build --progress=plain -t mcp-logic-image . 2>&1 | tee build_log.txt

if [ $? -eq 0 ]; then
  echo "Build successful! Running container..."
  
  # Kill any existing container with the same name
  docker kill mcp-logic 2>/dev/null || true
  docker rm mcp-logic 2>/dev/null || true
  
  docker run -it --rm \
    -e MCP_PROXY_DEBUG=true \
    -p 8080:8080 \
    -v "$(pwd)/src:/app/src" \
    --name mcp-logic \
    mcp-logic-image
else
  echo "Build failed. See build_log.txt for details."
fi
