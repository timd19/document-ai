from fastapi import FastAPI, Depends  
from fastapi.middleware.cors import CORSMiddleware  
from fastapi.responses import JSONResponse  
import os  
from dotenv import load_dotenv  

from db.database import engine, Base  
from routers import documents, chat  

# Load environment variables  
load_dotenv()  

# Create the FastAPI app  
app = FastAPI(  
    title="Document AI Assistant API",  
    description="API for the Document AI Assistant",  
    version="1.0.0",  
)  

# Add CORS middleware  
app.add_middleware(  
    CORSMiddleware,  
    allow_origins=["*"],  
    allow_credentials=True,  
    allow_methods=["*"],  
    allow_headers=["*"],  
)  

# Include routers  
app.include_router(documents.router)  
app.include_router(chat.router)  

@app.on_event("startup")  
async def startup():  
    # Create database tables  
    Base.metadata.create_all(bind=engine)  
    
    # Print environment info for debugging  
    print(f"Database URL: {os.environ.get('DATABASE_URL')}")  
    print(f"Azure OpenAI Endpoint: {os.environ.get('AZURE_OPENAI_ENDPOINT')}")  
    print(f"Azure Storage Container: {os.environ.get('AZURE_STORAGE_CONTAINER')}")
    print(f"Converter Service URL: {os.environ.get('CONVERTER_MICROSERVICE_URL')}")

@app.get("/")  
async def root():  
    return {"message": "Welcome to the Document AI Assistant API"}  

@app.get("/health")  
async def health_check():  
    return JSONResponse(content={"status": "healthy"}, status_code=200)  

if __name__ == "__main__":  
    import uvicorn  
    uvicorn.run(app, host="0.0.0.0", port=8000)