from sqlalchemy.orm import Session  
from . import models  
from datetime import datetime  
import uuid  

# Document operations  
def get_document(db: Session, document_id: str):  
    return db.query(models.Document).filter(models.Document.id == document_id).first()  

def get_documents(db: Session, skip: int = 0, limit: int = 100):  
    return db.query(models.Document).offset(skip).limit(limit).all()  

def create_document(db: Session, name: str, mime_type: str = None):  
    document_id = str(uuid.uuid4())  
    db_document = models.Document(  
        id=document_id,  
        name=name,  
        mime_type=mime_type,  
        created_at=datetime.utcnow(),  
        updated_at=datetime.utcnow()  
    )  
    db.add(db_document)  
    db.commit()  
    db.refresh(db_document)  
    return db_document  

def update_document(db: Session, document_id: str):  
    db_document = get_document(db, document_id)  
    if db_document:  
        db_document.updated_at = datetime.utcnow()  
        db.commit()  
        db.refresh(db_document)  
    return db_document  

def delete_document(db: Session, document_id: str):  
    db_document = get_document(db, document_id)  
    if db_document:  
        db.delete(db_document)  
        db.commit()  
        return True  
    return False  

# Chat history operations  
def get_chat_history(db: Session, document_id: str = None, skip: int = 0, limit: int = 100):  
    if document_id:  
        return db.query(models.ChatHistory).filter(  
            models.ChatHistory.document_id == document_id  
        ).offset(skip).limit(limit).all()  
    return db.query(models.ChatHistory).offset(skip).limit(limit).all()  

def create_chat_history(db: Session, user_message: str, assistant_response: str, document_id: str = None):  
    db_chat = models.ChatHistory(  
        id=str(uuid.uuid4()),  
        user_message=user_message,  
        assistant_response=assistant_response,  
        document_id=document_id,  
        created_at=datetime.utcnow()  
    )  
    db.add(db_chat)  
    db.commit()  
    db.refresh(db_chat)  
    return db_chat

# versioning documents

def get_latest_version(db: Session, document_id: str) -> int:  
    row = (  
        db.query(models.DocumentVersion)  
          .filter(models.DocumentVersion.document_id == document_id)  
          .order_by(models.DocumentVersion.version.desc())  
          .first()  
    )  
    return row.version if row else 0  

def create_document_version(  
    db: Session, document_id: str,  
    version: int, md_blob: str, export_blob: str  
):  
    dv = models.DocumentVersion(  
       document_id=document_id,  
       version=version,  
       md_blob=md_blob,  
       export_blob=export_blob  
    )  
    db.add(dv)  
    db.commit()  
    return dv  

def list_document_versions(db: Session, document_id: str):  
    return (  
      db.query(models.DocumentVersion)  
        .filter(models.DocumentVersion.document_id == document_id)  
        .order_by(models.DocumentVersion.version)  
        .all()  
    )  