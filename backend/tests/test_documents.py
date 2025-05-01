import pytest  
from fastapi.testclient import TestClient  
from sqlalchemy import create_engine  
from sqlalchemy.orm import sessionmaker  
import os  
import io  

from main import app  
from db.database import Base, get_db  
from db.models import Document  

# Create a test database  
SQLALCHEMY_DATABASE_URL = "sqlite:///./test.db"  
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})  
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)  

# Mock Azure Blob Storage  
class MockAzureBlobStorage:  
    def __init__(self):  
        self.documents = {}  
    
    def upload_document(self, document_id, filename, content):  
        key = f"{document_id}/{filename}"  
        self.documents[key] = content  
        return key  
    
    def download_document(self, document_id, filename):  
        key = f"{document_id}/{filename}"  
        return self.documents.get(key, b"")  
    
    def get_document_text(self, document_id, filename):  
        content = self.download_document(document_id, filename)  
        if isinstance(content, bytes):  
            return content.decode('utf-8')  
        return content  
    
    def delete_document(self, document_id, filename):  
        key = f"{document_id}/{filename}"  
        if key in self.documents:  
            del self.documents[key]  
        return True  

# Override dependencies  
def override_get_db():  
    db = TestingSessionLocal()  
    try:  
        yield db  
    finally:  
        db.close()  

app.dependency_overrides[get_db] = override_get_db  

# Import here to make the mock work  
from routers import documents  
documents.blob_storage = MockAzureBlobStorage()  

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

def test_upload_document(client):  
    # Create a test file  
    content = b"Test document content"  
    file = {"file": ("test.txt", content)}  
    
    # Upload the document  
    response = client.post("/documents/upload", files=file)  
    assert response.status_code == 200  
    assert "document_id" in response.json()  

def test_create_document(client):  
    # Create a new document  
    document_data = {  
        "document_text": "This is a test document",  
        "document_name": "test.md"  
    }  
    
    # Create the document  
    response = client.post("/documents/create", json=document_data)  
    assert response.status_code == 200  
    assert "document_id" in response.json()  
    
    # Get the document  
    document_id = response.json()["document_id"]  
    response = client.get(f"/documents/{document_id}")  
    assert response.status_code == 200  
    assert response.json()["content"] == "This is a test document"  

def test_update_document(client):  
    # Create a new document  
    document_data = {  
        "document_text": "This is a test document",  
        "document_name": "test.md"  
    }  
    
    # Create the document  
    response = client.post("/documents/create", json=document_data)  
    document_id = response.json()["document_id"]  
    
    # Update the document  
    update_data = {  
        "document_text": "This is an updated document"  
    }  
    
    response = client.put(f"/documents/{document_id}", json=update_data)  
    assert response.status_code == 200  
    
    # Get the updated document  
    response = client.get(f"/documents/{document_id}")  
    assert response.status_code == 200  
    assert response.json()["content"] == "This is an updated document"  

def test_delete_document(client):  
    # Create a new document  
    document_data = {  
        "document_text": "This is a test document",  
        "document_name": "test.md"  
    }  
    
    # Create the document  
    response = client.post("/documents/create", json=document_data)  
    document_id = response.json()["document_id"]  
    
    # Delete the document  
    response = client.delete(f"/documents/{document_id}")  
    assert response.status_code == 200  
    
    # Verify the document is deleted  
    response = client.get(f"/documents/{document_id}")  
    assert response.status_code == 404