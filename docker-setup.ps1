# Docker setup script for Windows
Write-Host "Setting up Docker environment..."

# Check if Docker is installed
$dockerInstalled = $null
try {
    $dockerInstalled = Get-Command docker -ErrorAction Stop
} catch {
    Write-Host "Docker not found. Please install Docker Desktop from https://www.docker.com/products/docker-desktop/"
    Write-Host "After installing Docker Desktop, restart your computer and run this script again."
    exit
}

# Check if Docker is running
try {
    $dockerRunning = docker info
} catch {
    Write-Host "Docker is not running. Please start Docker Desktop and try again."
    exit
}

Write-Host "Docker is installed and running."

# Create a Python virtual environment with correct dependencies
Write-Host "Setting up Python virtual environment with correct Docker dependencies..."
python -m venv docker-env
.\docker-env\Scripts\Activate.ps1
pip install --upgrade pip
pip install "requests==2.31.0" "docker>=7.0.0,<8.0.0"

Write-Host "Docker environment setup complete!"
Write-Host "Try running 'docker ps' to test if Docker is working correctly"
Write-Host "For Docker Python client, use the docker-env virtual environment"
