# Document AI Assistant  

A production-ready document AI assistant that allows users to chat with their documents using Azure OpenAI.  

## Features  

- Chat with documents using Azure OpenAI  
- Support for PDF, Word, and Markdown files  
- Document creation, modification, and export  
- Real-time document preview and editing  
- Storage of documents in Azure Blob Storage  
- Chat history persistence in PostgreSQL  

## Architecture  

- Frontend: Gradio UI with streaming chat  
- Backend: FastAPI application  
- Storage: PostgreSQL for metadata and chat history, Azure Blob for document files  
- AI: Azure OpenAI for document understanding and generation  
- Deployment: Docker-based containerization for easy scaling  

## Getting Started  

1. Clone this repository  
2. Create a `.env` file with your Azure credentials  
3. Run `docker-compose up -d`  
4. Access the UI at http://localhost:7860 or the API at http://localhost:8000/docs  

## Environment Variables  

- `AZURE_STORAGE_CONNECTION_STRING`: Azure Blob Storage connection string  
- `AZURE_OPENAI_API_KEY`: Azure OpenAI API key  
- `AZURE_OPENAI_ENDPOINT`: Azure OpenAI endpoint URL  

## API Documentation  

The API documentation is available at http://localhost:8000/docs when the application is running.