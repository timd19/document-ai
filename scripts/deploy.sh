#!/bin/bash  

# Deploy document AI assistant to production  

# Load environment variables  
export $(grep -v '^#' .env | xargs)  

# Build and start Docker containers  
docker-compose -f docker-compose.yml build  
docker-compose -f docker-compose.yml up -d  

# Initialize the database  
docker-compose exec backend python -m scripts.init_db  

# Print service status  
docker-compose ps  

echo "Document AI Assistant deployed successfully!"  
echo "Gradio UI: http://localhost:7860"  
echo "API: http://localhost:8000/docs"