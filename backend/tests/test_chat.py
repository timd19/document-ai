import pytest  
from fastapi.testclient import TestClient  
from sqlalchemy import create_engine  
from sqlalchemy.orm import sessionmaker  
import os  
import io  
import json  

from main import app  
from db.database import Base, get_db  
from db.models import Document, ChatHistory  

# Create a test database  
SQLALCHEMY_DATABASE_URL = "sqlite:///./test.db"  
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})  
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)  

# Override dependencies  
def override_get_db():  
    db = TestingSessionLocal()  
    try:  
        yield db  
    finally:  
        db.close()  

app.dependency_overrides[get_db] = override_get_db  

# Mock OpenAI client  
class MockOpenAIClient:  
    async def chat_completion(self, messages, temperature=0.7, stream=False):  
        if stream:  
            async def mock_stream():  
                response = "This is a mock assistant response."  
                for char in response:  
                    yield char  
            return mock_stream()  
        else:  
            return {  
                "content": "This is a mock assistant response.",  
                "finish_reason": "stop"  
            }  
    
    def prepare_messages_for_document(self, user_message, chat_history, document_text=None):  
        return [  
            {"role": "system", "content": "You are a helpful assistant."},  
            {"role": "user", "content": user_message}  
        ]  

# Import here to make the mock work  
from routers import chat  
chat.openai_client = MockOpenAIClient()  
chat.blob_storage = MockAzureBlobStorage()  

@pytest.fixture  
def test_db():  
    # Create the database tables  
    Base.metadata.create_all(bind=engine)  
    yield  
    # Drop the database tables  
    Base.metadata.drop_all(bind=engine)  

@pytest.fixture  
def client(test_db):  
    with TestClient(app) as client:  
        yield client  

def test_chat(client):  
    # Create a chat request  
    chat_data = {  
        "message": "Hello, how can you help me with documents?",  
        "history": []  
    }  
    
    # Send the chat request  
    response = client.post("/chat", json=chat_data)  
    assert response.status_code == 200  
    
    # The response should contain the mock assistant response  
    assert b"This is a mock assistant response." in response.content  

def test_chat_with_document(client):  
    # Create a new document  
    document_data = {  
        "document_text": "This is a test document",  
        "document_name": "test.md"  
    }  
    
    # Create the document  
    response = client.post("/documents/create", json=document_data)  
    document_id = response.json()["document_id"]  
    
    # Create a chat request with the document  
    chat_data = {  
        "message": "What does my document contain?",  
        "history": [],  
        "document_id": document_id  
    }  
    
    # Send the chat request  
    response = client.post("/chat", json=chat_data)  
    assert response.status_code == 200  
    
    # The response should contain the mock assistant response  
    assert b"This is a mock assistant response." in response.content  

def test_get_chat_history(client):  
    # Create a document  
    document_data = {  
        "document_text": "This is a test document",  
        "document_name": "test.md"  
    }  
    
    response = client.post("/documents/create", json=document_data)  
    document_id = response.json()["document_id"]  
    
    # Create a chat  
    chat_data = {  
        "message": "What does my document contain?",  
        "history": [],  
        "document_id": document_id  
    }  
    
    client.post("/chat", json=chat_data)  
    
    # Get chat history  
    response = client.get(f"/chat/history?document_id={document_id}")  
    assert response.status_code == 200  
    
    # There should be a history entry  
    history = response.json()["history"]  
    assert len(history) > 0  
    assert history[0]["user_message"] == "What does my document contain?"