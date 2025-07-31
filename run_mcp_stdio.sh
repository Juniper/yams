#!/bin/bash

# Enhanced MCP Server - stdio transport wrapper for VS Code
# Usage: run_mcp_stdio.sh [WORK_DIR] [CLUSTERS_CONFIG] [VENV_PATH]

# Get parameters or use defaults
WORK_DIR="${1:-$(dirname "$0")}"
CLUSTERS_CONFIG="${2:-$WORK_DIR/clusters/clusters.json}"
VENV_PATH="${3:-}"

# Change to working directory
cd "$WORK_DIR"

# Activate virtual environment
if [ -n "$VENV_PATH" ]; then
    # Use specified venv
    source "$VENV_PATH/bin/activate"
elif [ -d "venv" ]; then
    # Auto-detect venv
    source venv/bin/activate
elif [ -d ".venv" ]; then
    # Auto-detect .venv
    source .venv/bin/activate
fi

# Run the MCP server with stdio transport
exec python3 enhanced_mcp_server.py \
    --transport stdio \
    --clusters-config "$CLUSTERS_CONFIG"
