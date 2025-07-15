#!/bin/bash

# YAMS MCP Server - Simple Docker Run Script
# Standalone Docker deployment

set -e

IMAGE_NAME="yams-mcp-server"
CONTAINER_NAME="yams-mcp-server"
PORT="40041"

echo "🐳 YAMS MCP Server - Simple Docker Setup"
echo "========================================"

# Function to check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Check if Docker is available
if ! command_exists docker; then
    echo "❌ Docker is not installed. Please install Docker first."
    exit 1
fi

echo "✅ Docker is available"

# Stop and remove existing container if it exists
if docker ps -a --format 'table {{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo "🛑 Stopping and removing existing container..."
    docker stop "${CONTAINER_NAME}" >/dev/null 2>&1 || true
    docker rm "${CONTAINER_NAME}" >/dev/null 2>&1 || true
fi

# Build the image
echo "🔨 Building YAMS MCP Server image..."
docker build -t "${IMAGE_NAME}" .

echo "✅ Image built successfully"

# Create config directory if it doesn't exist
if [ ! -d "clusters" ]; then
    echo "📁 Creating clusters directory..."
    mkdir -p clusters
fi

# Create sshkeys directory if it doesn't exist
if [ ! -d "sshkeys" ]; then
    echo "📁 Creating sshkeys directory..."
    mkdir -p sshkeys
fi

# Create kubeconfigs directory if it doesn't exist
if [ ! -d "kubeconfigs" ]; then
    echo "📁 Creating kubeconfigs directory..."
    mkdir -p kubeconfigs
fi

# Prepare docker run command with optional volume mounts
DOCKER_VOLUMES=""

# Always mount config directory
DOCKER_VOLUMES="${DOCKER_VOLUMES} -v $(pwd)/clusters:/app/clusters"

# Mount SSH keys if directory exists and has content
if [ -d "sshkeys" ] && [ "$(ls -A sshkeys 2>/dev/null)" ]; then
    DOCKER_VOLUMES="${DOCKER_VOLUMES} -v $(pwd)/sshkeys:/app/.ssh:ro"
    echo "🔑 Mounting SSH keys from ./sshkeys"
fi

# Mount kubeconfig if directory exists and has content
if [ -d "kubeconfigs" ] && [ "$(ls -A kubeconfigs 2>/dev/null)" ]; then
    DOCKER_VOLUMES="${DOCKER_VOLUMES} -v $(pwd)/kubeconfigs:/app/kubeconfigs:ro"
    echo "⚙️  Mounting kubeconfigs from ./kubeconfigs"
fi

# Run the container
echo "🚀 Starting YAMS MCP Server..."
docker run -d \
    --name "${CONTAINER_NAME}" \
    -p "${PORT}:${PORT}" \
    ${DOCKER_VOLUMES} \
    --restart unless-stopped \
    "${IMAGE_NAME}"

echo "⏳ Waiting for service to start..."
sleep 5

# Check if container is running
if docker ps --format 'table {{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo "✅ YAMS MCP Server is running!"
    echo "🌐 Server: http://localhost:${PORT}"
    echo "🏥 Health: http://localhost:${PORT}/health"
    echo ""
    echo "� Configuration directories:"
    echo "  Clusters:     ./clusters/"
    echo "  SSH keys:     ./sshkeys/"
    echo "  Kubeconfigs:  ./kubeconfigs/"
    echo ""
    echo "�📖 Useful commands:"
    echo "  View logs:    docker logs -f ${CONTAINER_NAME}"
    echo "  Stop:         docker stop ${CONTAINER_NAME}"
    echo "  Remove:       docker rm ${CONTAINER_NAME}"
    echo "  Shell:        docker exec -it ${CONTAINER_NAME} /bin/bash"
else
    echo "❌ Failed to start container. Check logs:"
    docker logs "${CONTAINER_NAME}"
    exit 1
fi
