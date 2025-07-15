# Use Python 3.11 slim image as base
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    YAMS_PORT=40041 \
    YAMS_CONFIG_PATH=/app/clusters/clusters.json

# Set work directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    openssh-client \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY enhanced_mcp_server.py .
COPY clusters/clusters.json ./clusters-default.json
COPY README.md .

# Create directories for configuration and SSH keys
RUN mkdir -p /app/clusters /app/.ssh /app/kubeconfigs

# Copy default config as fallback config
RUN cp clusters-default.json /app/clusters/clusters.json

# Create entrypoint script for flexible configuration
RUN echo '#!/bin/bash\n\
set -e\n\
\n\
# Create clusters directory if mounted volume is empty\n\
if [ ! -f "/app/clusters/clusters.json" ]; then\n\
    echo "No clusters.json found, using default configuration..."\n\
    cp /app/clusters-default.json /app/clusters/clusters.json\n\
fi\n\
\n\
# Check SSH key permissions (but do not try to change them on read-only mounts)\n\
if [ -d "/app/.ssh" ] && [ "$(ls -A /app/.ssh 2>/dev/null)" ]; then\n\
    echo "SSH keys found in /app/.ssh"\n\
    # Check if SSH keys have correct permissions and warn if not\n\
    for key_file in /app/.ssh/*; do\n\
        if [ -f "$key_file" ]; then\n\
            perms=$(stat -c "%a" "$key_file" 2>/dev/null || stat -f "%A" "$key_file" 2>/dev/null || echo "unknown")\n\
            if [ "$perms" != "600" ] && [ "$perms" != "unknown" ]; then\n\
                echo "WARNING: SSH key $key_file has permissions $perms (should be 600)"\n\
                echo "Please run: chmod 600 $key_file on the host system"\n\
            fi\n\
        fi\n\
    done\n\
fi\n\
\n\
# Start the server\n\
exec python enhanced_mcp_server.py --port "${YAMS_PORT}" --clusters-config "${YAMS_CONFIG_PATH}"\n\
' > /app/entrypoint.sh && chmod +x /app/entrypoint.sh

# Create non-root user for security
RUN useradd -m -u 1000 yams && \
    chown -R yams:yams /app
USER yams

# Expose the default port
EXPOSE 40041

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:${YAMS_PORT:-40041}/health || exit 1

# Use entrypoint script
ENTRYPOINT ["/app/entrypoint.sh"]
