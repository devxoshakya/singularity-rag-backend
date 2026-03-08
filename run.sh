#!/bin/bash

# RAGBot Docker Management Script

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if .env file exists
check_env() {
    if [ ! -f .env ]; then
        print_warning ".env file not found. Creating from template..."
        cp .env.example .env
        print_error "Please edit .env file and add your GEMINI_API_KEY before running the application."
        exit 1
    fi
}

# Function to build and run the application
run_production() {
    print_status "Starting RAGBot in production mode..."
    check_env
    docker compose up --build -d
    print_status "RAGBot is running at http://localhost:8000"
    print_status "API documentation available at http://localhost:8000/docs"
}

# Function to run in development mode
run_development() {
    print_status "Starting RAGBot in development mode..."
    check_env
    docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
}

# Function to stop the application
stop() {
    print_status "Stopping RAGBot..."
    docker compose down
    print_status "RAGBot stopped."
}

# Function to view logs
logs() {
    docker compose logs -f ragbot
}

# Function to clean up everything
clean() {
    print_warning "This will remove all containers, volumes, and images. Are you sure? (y/N)"
    read -r response
    if [[ "$response" =~ ^[Yy]$ ]]; then
        docker compose down -v
        docker rmi $(docker images ragbot* -q) 2>/dev/null || true
        print_status "Cleanup completed."
    else
        print_status "Cleanup cancelled."
    fi
}

# Function to show help
show_help() {
    echo "RAGBot Docker Management Script"
    echo ""
    echo "Usage: $0 [COMMAND]"
    echo ""
    echo "Commands:"
    echo "  start, run     Start the application in production mode"
    echo "  dev           Start the application in development mode"
    echo "  stop          Stop the application"
    echo "  logs          View application logs"
    echo "  clean         Clean up containers, volumes, and images"
    echo "  help          Show this help message"
    echo ""
}

# Main script logic
case "${1:-run}" in
    start|run)
        run_production
        ;;
    dev)
        run_development
        ;;
    stop)
        stop
        ;;
    logs)
        logs
        ;;
    clean)
        clean
        ;;
    help|--help|-h)
        show_help
        ;;
    *)
        print_error "Unknown command: $1"
        show_help
        exit 1
        ;;
esac
