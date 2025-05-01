from fastapi import APIRouter, Depends, HTTPException, File, UploadFile, BackgroundTasks, Form  
from fastapi.responses import StreamingResponse, JSONResponse  
from sqlalchemy.orm import Session  
from typing import List, Dict, Any, Optional  
import io  
import httpx  
import datetime  
import chardet  

import logging
import sys
import os

logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)

from db.database import get_db, SessionLocal 
from db import crud, models  
from utils.azure_blob import AzureBlobStorage  

router = APIRouter(  
    prefix="/documents",  
    tags=["documents"],  
    responses={404: {"description": "Not found"}},  
)  

blob_storage = AzureBlobStorage()  

CONVERTER_MICROSERVICE_URL = os.environ.get("CONVERTER_MICROSERVICE_URL")

# background‐task helper
async def _convert_markdown_and_upload(  
    document_id: str,  
    target_ext: str,  
    blob_storage: AzureBlobStorage,  
    converter_url: str  
):  
    # 1) Download the canonical.md  
    md_bytes = blob_storage.download_document(document_id, "canonical.md")  

    # 2) Call converter microservice  
    async with httpx.AsyncClient(timeout=120.0) as client:  
        files = {"file": ("canonical.md", md_bytes, "text/markdown")}  
        resp = await client.post(  
            f"{converter_url}/convert/from-md?target={target_ext}",  
            files=files  
        )  
        resp.raise_for_status()  
        converted = resp.content  

    # 3) Upload under e.g. exports/  
    ts = datetime.datetime.utcnow().strftime("%Y%m%d%H%M%S")  
    export_blob = f"exports/{ts}.{target_ext}"  
    blob_storage.upload_document(document_id, export_blob, converted)

# versioning helper

async def _convert_and_record_version(  
    document_id: str,  
    version: int,  
    source_md_blob: str,  
    original_ext: str,  
    blob_storage: AzureBlobStorage,  
    converter_url: str  
):  
    try:  
        # 1) download that version's markdown  
        md_bytes = blob_storage.download_document(document_id, source_md_blob)  

        # 2) convert via Pandoc microservice  
        async with httpx.AsyncClient(timeout=120.0) as client:  
            files = {"file": (source_md_blob, md_bytes, "text/markdown")}  
            resp = await client.post(  
                f"{converter_url}/convert/from-md?target={original_ext}",  
                files=files  
            )  
            resp.raise_for_status()  
            converted = resp.content  

        # 3) upload the new export blob  
        export_blob = f"document-v{version}.{original_ext}"  
        blob_storage.upload_document(document_id, export_blob, converted)  

        # 4) record in the DB  
        db = SessionLocal()  
        try:  
            crud.create_document_version(db,  
              document_id=document_id,  
              version=version,  
              md_blob=source_md_blob,  
              export_blob=export_blob  
            )  
            # Optionally update the document's last_export field  
            doc = crud.get_document(db, document_id)  
            if doc:  
                doc.last_export = export_blob  
                db.commit()  
        finally:  
            db.close()  
    except Exception as e:  
        # Log the error  
        logging.error(f"Error in version conversion: {str(e)}")


# Helper: Generate canonical blob names  
def get_canonical_md_blob():  
    return "canonical.md"  

def get_original_blob(filename: str):  
    return f"original/{filename}"  

def get_export_blob(extension: str):  
    ts = datetime.datetime.utcnow().strftime("%Y%m%d%H%M%S")  
    return f"exports/{ts}.{extension}"  

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
    """Upload a file (DOCX, PPTX, PDF, MD); automatically convert to markdown for editing/AI."""  
    try:  
        filename = file.filename  
        ext = filename.rsplit(".", 1)[-1].lower()  
        file_content = await file.read()  

        # Create a new document entry in the database  
        document = crud.create_document(db, name=filename, mime_type=file.content_type)  
        document_id = document.id  

        # Save original file (with extension!)  
        orig_blob = f'original/{filename}'  
        blob_storage.upload_document(document_id, orig_blob, file_content)  

        # Check file type and handle accordingly  
        if ext in ("md", "markdown", "txt"):  
            # For text files, check encoding  
            import chardet  
            encoding_info = chardet.detect(file_content)  
            encoding = encoding_info.get('encoding', 'utf-8')  
            if encoding is None:  
                logging.error("Detected encoding is None; reverting to default UTF-8")  
                encoding = 'utf-8'  
            # Only normalize if it's not already UTF-8  
            if encoding.lower() != 'utf-8':  
                file_content = file_content.decode(encoding).encode('utf-8')  
            markdown = file_content  
        else:  
            # For binary files like DOCX/PPTX/PDF  
            # Directly send the binary to Pandoc for conversion  
            async with httpx.AsyncClient(timeout=120.0) as client:  
                files = {'file': (filename, file_content, file.content_type)}  
                logging.debug(f"Sending to Pandoc: {filename}, size: {len(file_content)} bytes")  # Log the file being sent  
                resp = await client.post(f"{CONVERTER_MICROSERVICE_URL}/convert/to-md", files=files)
                if resp.status_code != 200:  
                    logging.error(f"Pandoc microservice error: {resp.text}")  
                    raise HTTPException(status_code=500, detail=f"Conversion to markdown failed: {resp.text}")  
                markdown = resp.content  # Get the resulting markdown  

        # Store canonical markdown as 'canonical.md'  
        md_blob = "canonical.md"  
        blob_storage.upload_document(document_id, md_blob, markdown)  
        document.canonical_md = md_blob  
        db.commit()  

        return {"document_id": document_id}  
    except Exception as e:  
        logging.error(f"Exception in upload_document:\n{str(e)}")  
        raise HTTPException(status_code=500, detail=f"Error uploading document: {str(e)}")  

@router.put("/{document_id}", response_model=Dict[str,str])  
async def update_document(  
    document_id: str,  
    request: Dict[str, str],  
    background_tasks: BackgroundTasks,  
    db: Session = Depends(get_db)  
):  
    doc = crud.get_document(db, document_id)  
    if not doc:  
        raise HTTPException(404, "Document not found")  

    # Determine next version number  
    latest = crud.get_latest_version(db, document_id)  
    new_version = latest + 1  

    # Upload new version of the document  
    text = request.get("document_text", "")  
    md_blob = f"document-v{new_version}.md"  
    blob_storage.upload_document(document_id, md_blob, text)  

    # Update the canonical document  
    blob_storage.upload_document(document_id, "canonical.md", text)  
    crud.update_document(db, document_id)  # just bumps updated_at  
    
    # Determine original format (from the original filename)  
    original_filename = doc.name  
    original_ext = original_filename.rsplit('.', 1)[-1].lower() if '.' in original_filename else 'docx'  
    
    # Add background task to convert and record version  
    background_tasks.add_task(  
        _convert_and_record_version,  
        document_id=document_id,  
        version=new_version,  
        source_md_blob=md_blob,  
        original_ext=original_ext,  
        blob_storage=blob_storage,  
        converter_url=CONVERTER_MICROSERVICE_URL  
    )  

    return {"message": f"Saved as version {new_version}; export enqueued"}     

@router.delete("/{document_id}", response_model=Dict[str, str])  
async def delete_document(document_id: str, db: Session = Depends(get_db)):  
    """Delete a document (all blobs and DB entry)."""  
    document = crud.get_document(db, document_id)  
    if not document:  
        raise HTTPException(status_code=404, detail="Document not found")  
    try:  
        # Delete all blobs for this document  
        blobs = blob_storage.list_documents(document_id)  
        for blob in blobs:  
            blob_storage.delete_document(document_id, blob)  
        # Delete document from database  
        crud.delete_document(db, document_id)  
        return {"message": "Document deleted successfully"}  
    except Exception as e:  
        raise HTTPException(status_code=500, detail=f"Error deleting document: {str(e)}")  

@router.get("/{document_id}/download")  
async def download_document(document_id: str, db: Session = Depends(get_db)):  
    """  
    Download the original uploaded file (not markdown/export).  
    """  
    document = crud.get_document(db, document_id)  
    if not document:  
        raise HTTPException(status_code=404, detail="Document not found")  
    try:  
        orig_blob = get_original_blob(document.name)  
        content = blob_storage.download_document(document_id, orig_blob)  
        return StreamingResponse(  
            io.BytesIO(content),  
            media_type=document.mime_type or "application/octet-stream",  
            headers={"Content-Disposition": f"attachment; filename={document.name}"}  
        )  
    except Exception as e:  
        raise HTTPException(status_code=500, detail=f"Error downloading original document: {str(e)}")  

@router.get("/{document_id}/export")  
async def export_document(  
    document_id: str,  
    target: str = "docx",  
    db: Session = Depends(get_db)  
):  
    """  
    Export the canonical markdown as the requested format.  
    target: one of 'docx', 'pptx', 'pdf', 'md', etc. (Pandoc supported).  
    """  
    document = crud.get_document(db, document_id)  
    if not document:  
        raise HTTPException(status_code=404, detail="Document not found")  
    try:  
        md_blob = document.canonical_md or get_canonical_md_blob()  
        md_content = blob_storage.get_document_text(document_id, md_blob)  
        # MD format -- convert via Pandoc if needed, else just return this  
        if target == "md":  
            return StreamingResponse(  
                io.BytesIO(md_content.encode('utf-8') if isinstance(md_content, str) else md_content),  
                media_type="text/markdown",  
                headers={"Content-Disposition": f"attachment; filename={document.name.rsplit('.',1)[0]}.md"}  
            )  
        else:  
            async with httpx.AsyncClient() as client:  
                files = {'file': (md_blob, md_content)}  
                resp = await client.post(  
                    f"{CONVERTER_MICROSERVICE_URL}/convert/from-md?target={target}",  
                    files=files  
                )  
                if resp.status_code != 200:  
                    raise Exception(f"Conversion from markdown failed: {resp.content}")  
                content = resp.content  
            # Optionally archive export  
            export_blob = get_export_blob(target)  
            blob_storage.upload_document(document_id, export_blob, content)  
            return StreamingResponse(  
                io.BytesIO(content),  
                media_type="application/octet-stream",  
                headers={"Content-Disposition": f"attachment; filename={document.name.rsplit('.',1)[0]}.{target}"}  
            )  
    except Exception as e:  
        raise HTTPException(status_code=500, detail=f"Error exporting document: {str(e)}")
    
@router.get("/{document_id}/version/{version}")  
async def download_version(  
    document_id: str,  
    version: int,  
    format: str = None,  # Optional parameter to request a different format  
    db: Session = Depends(get_db)  
):  
    doc = crud.get_document(db, document_id)  
    if not doc:  
        raise HTTPException(404, "Document not found")  

    vv = (  
        db.query(models.DocumentVersion)  
        .filter_by(document_id=document_id, version=version)  
        .first()  
    )  
    if not vv:  
        raise HTTPException(404, "Version not found")  
    
    if format == "md":  
        # Return markdown version  
        content = blob_storage.get_document_text(document_id, vv.md_blob)  
        return StreamingResponse(  
            io.BytesIO(content.encode('utf-8')),  
            media_type="text/markdown",  
            headers={"Content-Disposition": f"attachment; filename={doc.name.rsplit('.',1)[0]}-v{version}.md"}  
        )  
    else:  
        # Return exported version  
        blob_name = vv.export_blob  
        mime = doc.mime_type  
        filename = f"{doc.name.rsplit('.',1)[0]}-v{version}.{doc.name.rsplit('.',1)[1]}"  
        
        content = blob_storage.download_document(document_id, blob_name)  
        return StreamingResponse(  
            io.BytesIO(content),  
            media_type=mime or "application/octet-stream",  
            headers={"Content-Disposition": f"attachment; filename={filename}"}  
        )

@router.get("/{document_id}/versions", response_model=List[Dict[str, Any]])  
async def get_versions(document_id: str, db: Session = Depends(get_db)):  
    doc = crud.get_document(db, document_id)  
    if not doc:  
        raise HTTPException(404, "Document not found")  
    
    versions = crud.list_document_versions(db, document_id)  
    return [  
        {  
            "version": v.version,  
            "md_blob": v.md_blob,  
            "export_blob": v.export_blob,  
            "created_at": v.created_at,  
        }  
        for v in versions  
    ]