import logging
import os
import uuid
from datetime import datetime
from typing import Dict, List, Any, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from db import crud
from db.database import get_db
from utils.azure_blob import AzureBlobStorage
from utils.document_processor import DocumentProcessor

router = APIRouter(
    prefix="/documents",
    tags=["documents"],
    responses={404: {"description": "Not found"}},
)

blob_storage = AzureBlobStorage()

def get_original_blob(filename):
    return f"original/{filename}"

def get_canonical_md_blob():
    return "canonical.md"

@router.get("/{document_id}/download/original/{filename}")
async def download_original_document(document_id: str, filename: str, db: Session = Depends(get_db)):
    """
    Download the original document.
    """
    try:
        # Get document info to use original name in the export
        document = crud.get_document(db, document_id)
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")
        
        orig_blob = get_original_blob(document.name)
        content = blob_storage.download_document(document_id, orig_blob)
        
        return Response(
            content=content,
            media_type=document.mime_type or "application/octet-stream",
            headers={"Content-Disposition": f"attachment; filename={document.name}"}
        )
    except Exception as e:
        logging.error(f"Error downloading original document: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error downloading original document: {str(e)}")

@router.get("/{document_id}/download/exports/{filename}")
async def download_export_document(document_id: str, filename: str, db: Session = Depends(get_db)):
    """
    Download an exported document version.
    """
    try:
        # Get document info to use original name in the export
        document = crud.get_document(db, document_id)
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")
        
        export_blob = f"exports/{filename}"
        content = blob_storage.download_document(document_id, export_blob)
        
        # Determine content type based on extension
        ext = filename.split(".")[-1].lower()
        content_types = {
            "md": "text/markdown",
            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "pdf": "application/pdf",
            "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        }
        
        content_type = content_types.get(ext, "application/octet-stream")
        
        # Get original document name for better download filename
        original_name = document.name.rsplit(".", 1)[0]
        download_filename = f"{original_name}_{filename}"
        
        return Response(
            content=content,
            media_type=content_type,
            headers={"Content-Disposition": f"attachment; filename={download_filename}"}
        )
    except Exception as e:
        logging.error(f"Error downloading export document: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error downloading export document: {str(e)}")

@router.get("/", response_model=Dict[str, List[Dict[str, Any]]])
async def get_user_documents(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """Get all documents (metadata only)."""
    documents = crud.get_documents(db, skip=skip, limit=limit)
    return {
        "documents": [
            {
                "id": doc.id,
                "name": doc.name,
                "created_at": doc.created_at,
                "updated_at": doc.updated_at
            } for doc in documents
        ]
    }

@router.get("/{document_id}", response_model=Dict[str, Any])
async def get_document(document_id: str, db: Session = Depends(get_db)):
    """Get a specific document's canonical markdown for editing/AI."""
    document = crud.get_document(db, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    try:
        content = blob_storage.get_document_text(document_id, document.canonical_md or get_canonical_md_blob())
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving document: {str(e)}")
    
    return {
        "id": document.id,
        "name": document.name,
        "content": content,
        "created_at": document.created_at,
        "updated_at": document.updated_at
    }

@router.post("/upload", response_model=Dict[str, str])
async def upload_document(
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """Upload a document file."""
    try:
        # Read the file content
        file_content = await file.read()
        filename = file.filename
        
        # Create a new document entry in the database
        document = crud.create_document(db, name=filename, mime_type=file.content_type)
        document_id = document.id
        
        # Upload the original file to blob storage
        orig_blob = get_original_blob(filename)
        blob_storage.upload_document(document_id, orig_blob, file_content)
        
        # Process the document to extract text and convert to markdown
        result = DocumentProcessor.process_document(file_content, filename)
        
        # Upload the markdown version
        md_blob = get_canonical_md_blob()
        markdown = result.get("text", "")
        blob_storage.upload_document(document_id, md_blob, markdown)
        document.canonical_md = md_blob
        db.commit()
        
        return {"document_id": document_id}
    except Exception as e:
        logging.error(f"Exception in upload_document:\n{str(e)}")
        raise HTTPException(status_code=500, detail=f"Error uploading document: {str(e)}")

@router.put("/{document_id}", response_model=Dict[str, str])
async def update_document(
    document_id: str,
    request: Dict[str, Any],
    db: Session = Depends(get_db)
):
    """Update a document's content."""
    try:
        document = crud.get_document(db, document_id)
        if not document:
            raise HTTPException(404, "Document not found")
        
        # Update the document content
        document_text = request.get("document_text", "")
        md_blob = document.canonical_md or "canonical.md"
        blob_storage.upload_document(document_id, md_blob, document_text)
        crud.update_document(db, document_id)
        
        # Generate a new export with timestamp
        timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        original_ext = document.name.rsplit(".", 1)[-1].lower()
        
        # Create a docx export
        DocumentProcessor.markdown_to_docx(
            document_id,
            document_text,
            f"exports/{timestamp}.docx",
            blob_storage
        )
        
        return {"message": "Document updated successfully; export in progress"}
    except Exception as e:
        logging.error(f"Error updating document: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error updating document: {str(e)}")

@router.delete("/{document_id}", response_model=Dict[str, str])
async def delete_document(document_id: str, db: Session = Depends(get_db)):
    """Delete a document (all blobs and DB entry)."""
    try:
        document = crud.get_document(db, document_id)
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")
        
        # Delete all blobs for this document
        blobs = blob_storage.list_documents(document_id)
        for blob in blobs:
            blob_storage.delete_document(document_id, blob)
        # Delete document from database
        crud.delete_document(db, document_id)
        return {"message": "Document deleted successfully"}
    except Exception as e:
        logging.error(f"Error deleting document: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error deleting document: {str(e)}")

@router.get("/{document_id}/versions", response_model=Dict[str, List[Dict[str, Any]]])
async def get_document_versions(document_id: str, db: Session = Depends(get_db)):
    """Get all available versions of a document (original and exports)."""
    try:
        document = crud.get_document(db, document_id)
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")
        
        # List all blobs for this document
        blobs = blob_storage.list_documents(document_id)
        
        versions = []
        
        # Add original document
        versions.append({
            "type": "original",
            "filename": "Original",
            "display_name": f"Original ({document.name})",
            "timestamp": document.created_at.isoformat()
        })
        
        # Add exports
        for blob in blobs:
            if blob.startswith("exports/"):
                filename = blob.replace("exports/", "")
                # Parse timestamp from filename (assuming format: YYYYMMDDHHMMSS.ext)
                try:
                    timestamp_str = filename.split(".")[0]
                    if len(timestamp_str) == 14:  # YYYYMMDDHHMMSS
                        year = int(timestamp_str[0:4])
                        month = int(timestamp_str[4:6])
                        day = int(timestamp_str[6:8])
                        hour = int(timestamp_str[8:10])
                        minute = int(timestamp_str[10:12])
                        second = int(timestamp_str[12:14])
                        
                        timestamp = datetime(year, month, day, hour, minute, second).isoformat()
                        
                        # Get extension for display
                        ext = filename.split(".")[-1].upper()
                        
                        versions.append({
                            "type": "export",
                            "filename": filename,
                            "display_name": f"Export {timestamp} ({ext})",
                            "timestamp": timestamp
                        })
                except Exception as e:
                    logging.warning(f"Error parsing timestamp from filename {filename}: {e}")
                    versions.append({
                        "type": "export",
                        "filename": filename,
                        "display_name": f"Export {filename}",
                        "timestamp": document.updated_at.isoformat()
                    })
        
        # Sort versions by timestamp (newest first)
        versions.sort(key=lambda x: x["timestamp"], reverse=True)
        
        return {"versions": versions}
    except Exception as e:
        logging.error(f"Error retrieving document versions: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error retrieving document versions: {str(e)}")

@router.get("/{document_id}/download/{filename}")
async def download_document_version(document_id: str, filename: str, db: Session = Depends(get_db)):
    """
    Download a specific version of a document.
    """
    try:
        document = crud.get_document(db, document_id)
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")
        
        content = blob_storage.download_document(document_id, filename)
        
        # Determine content type based on extension
        ext = filename.split(".")[-1].lower() if "." in filename else ""
        content_types = {
            "md": "text/markdown",
            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "pdf": "application/pdf",
            "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        }
        
        content_type = content_types.get(ext, "application/octet-stream")
        
        # Get original document name for better download filename
        original_name = document.name.rsplit(".", 1)[0]
        
        if filename == "canonical.md":
            download_filename = f"{original_name}.md"
        else:
            # For exports, use timestamp in the filename
            original_ext = document.name.split(".")[-1]
            if filename.startswith("exports/"):
                download_filename = f"{original_name}_{filename.replace('exports/', '')}"
            else:
                download_filename = document.name
        
        return Response(
            content=content,
            media_type=content_type,
            headers={"Content-Disposition": f"attachment; filename={download_filename}"}
        )
    except Exception as e:
        logging.error(f"Error downloading document version: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error downloading document version: {str(e)}")

@router.get("/{document_id}/download")
async def download_document(document_id: str, db: Session = Depends(get_db)):
    """
    Download the original document.
    """
    try:
        document = crud.get_document(db, document_id)
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")
        
        orig_blob = get_original_blob(document.name)
        content = blob_storage.download_document(document_id, orig_blob)
        
        return Response(
            content=content,
            media_type=document.mime_type or "application/octet-stream",
            headers={"Content-Disposition": f"attachment; filename={document.name}"}
        )
    except Exception as e:
        logging.error(f"Error downloading original document: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error downloading original document: {str(e)}")

@router.get("/{document_id}/export")
async def export_document(
    document_id: str,
    format: str = "md",
    db: Session = Depends(get_db)
):
    """
    Export the document to a specific format.
    """
    try:
        document = crud.get_document(db, document_id)
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")
        
        md_blob = document.canonical_md or get_canonical_md_blob()
        md_content = blob_storage.get_document_text(document_id, md_blob)
        
        if format == "md":
            # Return the markdown directly
            return Response(
                content=md_content,
                media_type="text/markdown",
                headers={"Content-Disposition": f"attachment; filename={document.name.rsplit('.',1)[0]}.md"}
            )
        
        # For other formats, convert and return
        timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        export_blob = f"exports/{timestamp}.{format}"
        
        if format == "docx":
            content = DocumentProcessor.markdown_to_docx(document_id, md_content, export_blob, blob_storage)
            content_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        elif format == "pdf":
            content = DocumentProcessor.markdown_to_pdf(document_id, md_content, export_blob, blob_storage)
            content_type = "application/pdf"
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported export format: {format}")
        
        # Upload the export for future reference
        blob_storage.upload_document(document_id, export_blob, content)
        
        original_name = document.name.rsplit('.',1)[0]
        download_filename = f"{original_name}.{format}"
        
        return Response(
            content=content,
            media_type=content_type,
            headers={"Content-Disposition": f"attachment; filename={download_filename}"}
        )
    except Exception as e:
        logging.error(f"Error exporting document: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error exporting document: {str(e)}")

@router.post("/create", response_model=Dict[str, str])
async def create_document(
    request: Dict[str, Any],
    db: Session = Depends(get_db)
):
    """Create a new document from text."""
    try:
        document_text = request.get("document_text", "")
        document_name = request.get("document_name", "document.md")
        
        # Create a new document entry in the database
        document = crud.create_document(db, name=document_name, mime_type="text/markdown")
        document_id = document.id
        
        # Upload the markdown version
        md_blob = get_canonical_md_blob()
        blob_storage.upload_document(document_id, md_blob, document_text)
        document.canonical_md = md_blob
        db.commit()
        
        # Also create a docx version as the "original"
        docx_content = DocumentProcessor.markdown_to_docx(document_id, document_text, None, None)
        orig_blob = get_original_blob(document_name.replace(".md", ".docx"))
        blob_storage.upload_document(document_id, orig_blob, docx_content)
        
        return {"document_id": document_id}
    except Exception as e:
        logging.error(f"Exception in create_document:\n{str(e)}")
        raise HTTPException(status_code=500, detail=f"Error creating document: {str(e)}")

