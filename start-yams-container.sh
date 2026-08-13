#!/bin/bash

# YAMS MCP Server - Simple Container Run Script
# Standalone Docker or Podman deployment
# Uses MCP 2.0 Streamable HTTP transport (enhanced_mcp_server.py)

set -e

IMAGE_NAME="yams-mcp-server"
CONTAINER_NAME="yams-mcp-server"
PORT="40041"

echo "📦 YAMS MCP Server - Simple Container Setup"
echo "==========================================="

# Function to check if command exists
command_exists() {
 
    command -v "$1" >/dev/null 2>&1
}

# Auto-detect container runtime (Docker or Podman)
if command_exists docker; then
    RUNTIME="docker"
elif command_exists podman; then
    RUNTIME="podman"
else
    echo "❌ Neither Docker nor Podman is installed. Please install a container runtime first."
    exit 1
fi

echo "✅ Container runtime available: $RUNTIME"

# Stop and remove existing container if it exists
if "$RUNTIME" ps -a --format 'table {{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo "🛑 Stopping and removing existing container..."
    "$RUNTIME" stop "${CONTAINER_NAME}" >/dev/null 2>&1 || true
    "$RUNTIME" rm "${CONTAINER_NAME}" >/dev/null 2>&1 || true
fi

# Build the image
echo "🔨 Building YAMS MCP Server image using $RUNTIME..."
"$RUNTIME" build --no-cache -t "${IMAGE_NAME}" .

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

# Prepare volume mounts with an engine-agnostic variable
CONTAINER_VOLUMES=""

# Always mount config directory
CONTAINER_VOLUMES="${CONTAINER_VOLUMES} -v $(pwd)/clusters:/app/clusters"

# Mount SSH keys if directory exists and has content
if [ -d "sshkeys" ] && [ "$(ls -A sshkeys 2>/dev/null)" ]; then
    CONTAINER_VOLUMES="${CONTAINER_VOLUMES} -v $(pwd)/sshkeys:/app/.ssh:ro"
    echo "🔑 Mounting SSH keys from ./sshkeys"
fi

# Mount kubeconfig if directory exists and has content
if [ -d "kubeconfigs" ] && [ "$(ls -A kubeconfigs 2>/dev/null)" ]; then
    CONTAINER_VOLUMES="${CONTAINER_VOLUMES} -v $(pwd)/kubeconfigs:/app/kubeconfigs:ro"
    echo "⚙️  Mounting kubeconfigs from ./kubeconfigs"
fi

# Run the container
echo "🚀 Starting YAMS MCP Server container..."
"$RUNTIME" run -d \
    --name "${CONTAINER_NAME}" \
    -p "${PORT}:${PORT}" \
    ${CONTAINER_VOLUMES} \
    -e YAMS_PORT="${PORT}" \
    --restart unless-stopped \
    "${IMAGE_NAME}"

echo "⏳ Waiting for service to start..."
sleep 5

# Check if container is running
if "$RUNTIME" ps --format 'table {{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo "✅ YAMS MCP Server is running!"
    echo "🌐 Server: http://localhost:${PORT}"
    echo "🔌 MCP endpoint (streamable-http): http://localhost:${PORT}/mcp"
    echo ""
    echo "📂 Configuration directories:"
    echo "  Clusters:     ./clusters/"
    echo "  SSH keys:     ./sshkeys/"
    echo "  Kubeconfigs:  ./kubeconfigs/"
    echo ""
    echo "📖 Useful commands:"
    echo "  View logs:    $RUNTIME logs -f ${CONTAINER_NAME}"
    echo "  Stop:         $RUNTIME stop ${CONTAINER_NAME}"
    echo "  Remove:       $RUNTIME rm ${CONTAINER_NAME}"
    echo "  Shell:        $RUNTIME exec -it ${CONTAINER_NAME} /bin/bash"
else
    echo "❌ Failed to start container. Check logs:"
    "$RUNTIME" logs "${CONTAINER_NAME}"
    exit 1
fi
