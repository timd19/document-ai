from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Integer
from sqlalchemy.ext.declarative import declarative_base  
from sqlalchemy.orm import relationship  
import uuid  
from datetime import datetime  

from .database import Base  

class Document(Base):  
    __tablename__ = "documents"  
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))  
    name = Column(String, nullable=False)  
    mime_type = Column(String, nullable=True)  
    canonical_md = Column(String, nullable=True)  # NEW: blob name for canonical markdown
    last_export = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)  
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    versions = relationship("DocumentVersion", back_populates="document")
    chat_history = relationship("ChatHistory", back_populates="document")  

class ChatHistory(Base):  
    __tablename__ = "chat_history"  
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))  
    user_message = Column(Text, nullable=False)  
    assistant_response = Column(Text, nullable=False)  
    document_id = Column(String, ForeignKey("documents.id"), nullable=True)  
    created_at = Column(DateTime, default=datetime.utcnow)  
    document = relationship("Document", back_populates="chat_history")

class DocumentVersion(Base):  
    __tablename__ = "document_versions"  
    id = Column(Integer, primary_key=True, index=True)  
    document_id = Column(String, ForeignKey("documents.id"), index=True)  
    version = Column(Integer, nullable=False)  
    md_blob = Column(String, nullable=False)    # e.g. "v2.md"  
    export_blob = Column(String, nullable=False) # e.g. "v2.docx"  
    created_at = Column(DateTime, default=datetime.utcnow)  

    document = relationship("Document", back_populates="versions")  