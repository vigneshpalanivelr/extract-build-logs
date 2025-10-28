# GitLab Pipeline Log Extraction System - Dockerfile
# Single-stage build for simplicity

FROM python:3.11-slim

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
COPY monitor_dashboard.py ./

# Create non-root user for security
RUN groupadd -r appuser && \
    useradd -r -g appuser -u 1000 appuser && \
    chown -R appuser:appuser /app

# Create logs directory and set permissions
RUN mkdir -p /app/logs && \
    chown -R appuser:appuser /app/logs

# Switch to non-root user
USER appuser

# Expose webhook port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=40s \
    CMD curl -f http://localhost:8000/health || exit 1

# Start the FastAPI server
CMD ["uvicorn", "src.webhook_listener:app", "--host", "0.0.0.0", "--port", "8000"]
