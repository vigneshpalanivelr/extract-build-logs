# GitLab Pipeline Log Extraction System - Dockerfile
# Single-stage build for simplicity

FROM python:3.8-slim

# Create logs directory
RUN mkdir -p /app/logs /app/src /app/scripts && chmod 755 /app

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/ ./src/
COPY scripts/ ./scripts/
COPY log-extractor-entrypoint.sh ./

# Make entrypoint script executable
RUN chmod +x log-extractor-entrypoint.sh

# Switch to non-root user
USER appuser

# Expose webhook port (default 8000, can be changed via WEBHOOK_PORT env var)
EXPOSE 8000

# Health check (uses default port 8000, override via WEBHOOK_PORT if needed)
# Note: Docker HEALTHCHECK doesn't support env vars, so using shell wrapper
HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=40s \
    CMD curl -f http://localhost:${WEBHOOK_PORT:-8000}/health || exit 1

# Start the FastAPI server with dynamic port from environment
CMD ["./log-extractor-entrypoint.sh"]
