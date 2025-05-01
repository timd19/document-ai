from azure.storage.blob import BlobServiceClient  
import os  
from typing import Optional, BinaryIO, List  
import io

class AzureBlobStorage:  
    def __init__(self):  
        """Initialize Azure Blob Storage client."""  
        connection_string = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
        self.container_name = os.environ.get("AZURE_STORAGE_CONTAINER")  
        
        if not connection_string:  
            raise ValueError("AZURE_STORAGE_CONNECTION_STRING environment variable not set")  
        
        self.blob_service_client = BlobServiceClient.from_connection_string(connection_string)  
        self.container_client = self.blob_service_client.get_container_client(self.container_name)  
        
        # Create container if it doesn't exist  
        if not self.container_client.exists():  
            self.container_client.create_container()  
    
    def upload_document(self, document_id: str, filename: str, content: bytes or str) -> str:  
        blob_path = f"{document_id}/{filename}"  
        blob_client = self.container_client.get_blob_client(blob_path)  
        # Ensure we have bytes  
        if isinstance(content, str):  
            content = content.encode('utf-8')  
        blob_client.upload_blob(io.BytesIO(content), overwrite=True)  
        return blob_path
    
    def download_document(self, document_id: str, filename: str) -> bytes:  
        """Download a document from Azure Blob Storage."""  
        blob_path = f"{document_id}/{filename}"  
        blob_client = self.container_client.get_blob_client(blob_path)  
        
        return blob_client.download_blob().readall()  
    
    def get_document_text(self, document_id: str, filename: str) -> str:  
        """Get document content as text."""  
        content = self.download_document(document_id, filename)  
        return content.decode('utf-8')  
    
    def delete_document(self, document_id: str, filename: str) -> bool:  
        """Delete a document from Azure Blob Storage."""  
        blob_path = f"{document_id}/{filename}"  
        blob_client = self.container_client.get_blob_client(blob_path)  
        
        blob_client.delete_blob()  
        return True  
    
    def list_documents(self, document_id: str) -> List[str]:  
        """List all blobs for a document."""  
        prefix = f"{document_id}/"  
        blobs = self.container_client.list_blobs(name_starts_with=prefix)  
        return [blob.name.replace(prefix, '') for blob in blobs]