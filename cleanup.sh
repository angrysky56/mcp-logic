#!/bin/bash

echo "Cleaning up Docker containers and images..."

# Stop and remove all containers with mcp-logic in the name
echo "Stopping and removing containers..."
docker ps -a | grep mcp-logic | awk '{print $1}' | xargs -r docker rm -f

# Remove all images with mcp-logic in the name
echo "Removing images..."
docker images | grep mcp-logic | awk '{print $3}' | xargs -r docker rmi -f

# Show current status
echo "Current docker containers:"
docker ps -a

echo "Current docker images:"
docker images

echo "Cleanup complete!"
