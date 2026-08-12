#!/bin/bash

set -euo pipefail

echo "Cleaning up Docker containers and images..."

ID_DIR="$(mktemp -d)"
trap 'rm -rf "${ID_DIR}"' EXIT

# Stop and remove all containers with mcp-logic in the name
echo "Stopping and removing containers..."
docker ps -aq --filter "name=mcp-logic" >"${ID_DIR}/containers"
mapfile -t CONTAINER_IDS <"${ID_DIR}/containers"
if ((${#CONTAINER_IDS[@]})); then
	docker rm -f "${CONTAINER_IDS[@]}"
fi

# Remove all images with mcp-logic in the name
echo "Removing images..."
docker images -q --filter "reference=*mcp-logic*" >"${ID_DIR}/images"
mapfile -t IMAGE_IDS <"${ID_DIR}/images"
if ((${#IMAGE_IDS[@]})); then
	docker rmi -f "${IMAGE_IDS[@]}"
fi

# Show current status
echo "Current docker containers:"
docker ps -a

echo "Current docker images:"
docker images

echo "Cleanup complete!"
