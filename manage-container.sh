#!/bin/bash

# GitLab Pipeline Log Extractor - Container Management Script
# This script manages the Docker container lifecycle

set -e

# Configuration
IMAGE_NAME="gitlab-pipeline-extractor"
CONTAINER_NAME="gitlab-pipeline-extractor"
PORT="8000"
LOGS_DIR="./logs"
ENV_FILE=".env"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Print colored message
print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if Docker is installed
check_docker() {
    if ! command -v docker &> /dev/null; then
        print_error "Docker is not installed. Please install Docker first."
        exit 1
    fi
}

# Check if .env file exists
check_env_file() {
    if [ ! -f "$ENV_FILE" ]; then
        print_error ".env file not found!"
        print_info "Please create .env file from .env.example:"
        echo "  cp .env.example .env"
        echo "  # Edit .env and set GITLAB_URL and GITLAB_TOKEN"
        exit 1
    fi
}

# Build Docker image
build() {
    print_info "Building Docker image: $IMAGE_NAME"
    docker build -t $IMAGE_NAME .
    print_success "Image built successfully!"
}

# Start container
start() {
    check_env_file

    # Check if container already exists
    if [ "$(docker ps -aq -f name=$CONTAINER_NAME)" ]; then
        print_warning "Container $CONTAINER_NAME already exists."

        # Check if it's running
        if [ "$(docker ps -q -f name=$CONTAINER_NAME)" ]; then
            print_info "Container is already running."
            print_info "Use './manage-container.sh restart' to restart it."
            return 0
        else
            print_info "Starting existing container..."
            docker start $CONTAINER_NAME
            print_success "Container started!"
            return 0
        fi
    fi

    # Create logs directory if it doesn't exist
    mkdir -p $LOGS_DIR

    print_info "Starting new container: $CONTAINER_NAME"
    docker run -d \
        --name $CONTAINER_NAME \
        -p $PORT:8000 \
        -v "$(pwd)/$LOGS_DIR:/app/logs" \
        -v "$(pwd)/$ENV_FILE:/app/.env:ro" \
        --restart unless-stopped \
        $IMAGE_NAME

    print_success "Container started successfully!"
    print_info "Webhook endpoint: http://localhost:$PORT/webhook"
    print_info "Health check: http://localhost:$PORT/health"
    print_info "API docs: http://localhost:$PORT/docs"
}

# Stop container
stop() {
    if [ ! "$(docker ps -q -f name=$CONTAINER_NAME)" ]; then
        print_warning "Container $CONTAINER_NAME is not running."
        return 0
    fi

    print_info "Stopping container: $CONTAINER_NAME"
    docker stop $CONTAINER_NAME
    print_success "Container stopped!"
}

# Restart container
restart() {
    print_info "Restarting container: $CONTAINER_NAME"
    stop
    sleep 2
    start
}

# View container logs
logs() {
    if [ ! "$(docker ps -aq -f name=$CONTAINER_NAME)" ]; then
        print_error "Container $CONTAINER_NAME does not exist."
        return 1
    fi

    print_info "Showing logs for container: $CONTAINER_NAME"
    print_info "Press Ctrl+C to exit"
    echo ""
    docker logs -f $CONTAINER_NAME
}

# Show container status
status() {
    print_info "Container status:"
    echo ""

    if [ ! "$(docker ps -aq -f name=$CONTAINER_NAME)" ]; then
        print_warning "Container does not exist. Use './manage-container.sh start' to create it."
        return 0
    fi

    if [ "$(docker ps -q -f name=$CONTAINER_NAME)" ]; then
        print_success "Container is RUNNING"
        echo ""
        docker ps -f name=$CONTAINER_NAME --format "table {{.ID}}\t{{.Status}}\t{{.Ports}}"
        echo ""

        # Check health status
        HEALTH=$(docker inspect --format='{{.State.Health.Status}}' $CONTAINER_NAME 2>/dev/null || echo "none")
        if [ "$HEALTH" != "none" ]; then
            print_info "Health status: $HEALTH"
        fi

        # Show resource usage
        print_info "Resource usage:"
        docker stats --no-stream --format "table {{.Container}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}" $CONTAINER_NAME
    else
        print_warning "Container exists but is NOT RUNNING"
        echo ""
        docker ps -a -f name=$CONTAINER_NAME --format "table {{.ID}}\t{{.Status}}"
        echo ""
        print_info "Use './manage-container.sh start' to start it."
    fi
}

# Execute shell in container
shell() {
    if [ ! "$(docker ps -q -f name=$CONTAINER_NAME)" ]; then
        print_error "Container $CONTAINER_NAME is not running."
        return 1
    fi

    print_info "Opening shell in container..."
    docker exec -it $CONTAINER_NAME /bin/bash
}

# Remove container
remove() {
    print_warning "This will remove the container (logs will be preserved in $LOGS_DIR)"
    read -p "Are you sure? (y/N): " -n 1 -r
    echo

    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        print_info "Cancelled."
        return 0
    fi

    stop

    if [ "$(docker ps -aq -f name=$CONTAINER_NAME)" ]; then
        print_info "Removing container: $CONTAINER_NAME"
        docker rm $CONTAINER_NAME
        print_success "Container removed!"
    else
        print_warning "Container does not exist."
    fi
}

# Clean up everything (container and image)
cleanup() {
    print_warning "This will remove both container and image (logs will be preserved in $LOGS_DIR)"
    read -p "Are you sure? (y/N): " -n 1 -r
    echo

    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        print_info "Cancelled."
        return 0
    fi

    remove

    if [ "$(docker images -q $IMAGE_NAME)" ]; then
        print_info "Removing image: $IMAGE_NAME"
        docker rmi $IMAGE_NAME
        print_success "Image removed!"
    else
        print_warning "Image does not exist."
    fi
}

# View monitoring dashboard
monitor() {
    if [ ! "$(docker ps -q -f name=$CONTAINER_NAME)" ]; then
        print_error "Container $CONTAINER_NAME is not running."
        return 1
    fi

    print_info "Opening monitoring dashboard..."
    docker exec -it $CONTAINER_NAME python monitor_dashboard.py "$@"
}

# Export monitoring data
export_data() {
    if [ ! "$(docker ps -q -f name=$CONTAINER_NAME)" ]; then
        print_error "Container $CONTAINER_NAME is not running."
        return 1
    fi

    EXPORT_FILE="${1:-monitoring_export.csv}"
    print_info "Exporting monitoring data to: $EXPORT_FILE"

    # Export via API and save to host
    curl -s "http://localhost:$PORT/monitor/export/csv" -o "$EXPORT_FILE"
    print_success "Data exported to: $EXPORT_FILE"
}

# Test webhook endpoint
test_webhook() {
    if [ ! "$(docker ps -q -f name=$CONTAINER_NAME)" ]; then
        print_error "Container $CONTAINER_NAME is not running."
        return 1
    fi

    print_info "Testing webhook endpoint with sample payload..."

    # Sample GitLab pipeline webhook payload
    SAMPLE_PAYLOAD='{
  "object_kind": "pipeline",
  "object_attributes": {
    "id": 12345,
    "status": "success",
    "stages": ["build", "test"],
    "created_at": "2024-01-01 10:00:00 UTC",
    "finished_at": "2024-01-01 10:15:00 UTC"
  },
  "project": {
    "id": 100,
    "name": "test-project",
    "web_url": "https://gitlab.com/test/project"
  },
  "builds": [
    {
      "id": 1001,
      "name": "build-job",
      "stage": "build",
      "status": "success"
    },
    {
      "id": 1002,
      "name": "test-job",
      "stage": "test",
      "status": "success"
    }
  ]
}'

    echo "$SAMPLE_PAYLOAD" | curl -X POST \
        -H "Content-Type: application/json" \
        -H "X-Gitlab-Event: Pipeline Hook" \
        -d @- \
        "http://localhost:$PORT/webhook"

    echo ""
    print_success "Test webhook sent!"
    print_info "Check logs with: ./manage-container.sh logs"
}

# Show usage
usage() {
    cat << EOF
GitLab Pipeline Log Extractor - Container Management Script

Usage: ./manage-container.sh [command] [options]

Commands:
    build               Build the Docker image
    start               Start the container
    stop                Stop the container
    restart             Restart the container
    status              Show container status and resource usage
    logs                View container logs (live tail)
    shell               Open a shell inside the container
    remove              Remove the container (keeps logs)
    cleanup             Remove container and image (keeps logs)

    monitor [options]   View monitoring dashboard
                        Options: --hours 24, --recent 50, --pipeline ID
    export [file]       Export monitoring data to CSV
                        Default file: monitoring_export.csv
    test                Send a test webhook to the container

Examples:
    # First time setup
    ./manage-container.sh build
    ./manage-container.sh start

    # View status and logs
    ./manage-container.sh status
    ./manage-container.sh logs

    # Monitoring
    ./manage-container.sh monitor
    ./manage-container.sh monitor --hours 48
    ./manage-container.sh export data.csv

    # Testing
    ./manage-container.sh test

    # Maintenance
    ./manage-container.sh restart
    ./manage-container.sh cleanup

Endpoints:
    Webhook:    http://localhost:$PORT/webhook
    Health:     http://localhost:$PORT/health
    API Docs:   http://localhost:$PORT/docs
    Monitoring: http://localhost:$PORT/monitor/summary

Data Persistence:
    Logs and monitoring database are stored in: $LOGS_DIR/
    Data persists even when container is removed.

EOF
}

# Main script
main() {
    check_docker

    COMMAND=${1:-usage}

    case $COMMAND in
        build)
            build
            ;;
        start)
            start
            ;;
        stop)
            stop
            ;;
        restart)
            restart
            ;;
        logs)
            logs
            ;;
        status)
            status
            ;;
        shell)
            shell
            ;;
        remove)
            remove
            ;;
        cleanup)
            cleanup
            ;;
        monitor)
            shift
            monitor "$@"
            ;;
        export)
            shift
            export_data "$@"
            ;;
        test)
            test_webhook
            ;;
        help|--help|-h|usage)
            usage
            ;;
        *)
            print_error "Unknown command: $COMMAND"
            echo ""
            usage
            exit 1
            ;;
    esac
}

# Run main function
main "$@"
