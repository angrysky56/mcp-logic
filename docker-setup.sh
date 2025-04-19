#!/bin/bash

echo "Setting up Docker environment..."

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "Docker not found. Installing Docker..."
    
    # Remove old versions if any
    for pkg in docker.io docker-doc docker-compose docker-compose-v2 podman-docker containerd runc; do
        sudo apt-get remove -y $pkg || true
    done
    
    # Install prerequisites
    sudo apt-get update
    sudo apt-get install -y ca-certificates curl gnupg
    
    # Add Docker's official GPG key
    sudo install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    sudo chmod a+r /etc/apt/keyrings/docker.gpg
    
    # Add the repository to Apt sources
    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
      $(./etc/os-release && echo "$VERSION_CODENAME") stable" | \
      sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
    
    # Install Docker
    sudo apt-get update
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi

# Ensure Docker is running
if ! systemctl is-active --quiet docker; then
    echo "Starting Docker service..."
    sudo systemctl start docker
    sudo systemctl enable docker
fi

# Add user to docker group if not already added
if ! groups "$(whoami)" | grep -q docker; then
    echo "Adding user to docker group..."
    sudo usermod -aG docker "$(whoami)"
    echo "Please log out and log back in for group changes to take effect"
    echo "Alternatively, run 'newgrp docker' to update group membership without logging out"
fi

# Create a Python virtual environment with correct dependencies
echo "Setting up Python virtual environment with correct Docker dependencies..."
python3 -m venv docker-env
# shellcheck disable=SC1091
source docker-env/bin/activate
pip install --upgrade pip
pip install "requests==2.31.0" "docker>=7.0.0,<8.0.0"

echo "Docker environment setup complete!"
echo "Try running 'docker ps' to test if Docker is working correctly"
echo "For Docker Python client, use the docker-env virtual environment"
