# Dockerfile for mcp-logic with Prover9
FROM python:3.12-slim

# Install basic dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy application
COPY . .

# Create Python virtual environment in the correct location
RUN pip install uv
RUN uv venv .venv
ENV PATH="/app/.venv/bin:$PATH"

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
RUN echo '#!/bin/bash' > /usr/local/prover9-mount/prover9.exe && \
    echo '/usr/local/prover9-mount/prover9 "$@"' >> /usr/local/prover9-mount/prover9.exe && \
    chmod +x /usr/local/prover9-mount/prover9.exe

# Set environment variables
ENV DOCKER_HOST=unix:///var/run/docker.sock

# Expose ports - try multiple ports in case some are in use
EXPOSE 8888 8889 8890 8891 8892

# Command to run the server
CMD ["sh", "-c", "uv --directory /app/src/mcp_logic run mcp_logic --prover-path /usr/local/prover9-mount"]
