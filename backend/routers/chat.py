from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks  
from fastapi.responses import StreamingResponse  
from sqlalchemy.orm import Session  
from typing import Dict, Any, List, Optional  
import logging  

from db.database import get_db  
from db import crud, models  
from utils.openai_client import OpenAIClient  
from utils.azure_blob import AzureBlobStorage  

router = APIRouter(  
    prefix="/chat",  
    tags=["chat"],  
    responses={404: {"description": "Not found"}},  
)  

openai_client = OpenAIClient()  
blob_storage = AzureBlobStorage()  
logger = logging.getLogger("uvicorn.error")  

@router.post("")  
async def chat(  
    request: Dict[str, Any],  
    background_tasks: BackgroundTasks,  
    db: Session = Depends(get_db)  
):  
    """Chat with the AI assistant."""  
    message = request.get("message")  
    history = request.get("history", [])  
    document_id = request.get("document_id")  
    document_text = request.get("document_text")  
    if not message:  
        raise HTTPException(status_code=400, detail="Message is required")  

    # Retrieve document text if needed  
    if document_id and not document_text:  
        document = crud.get_document(db, document_id)  
        if document:  
            try:  
                document_text = blob_storage.get_document_text(document_id, document.name)  
            except Exception as e:  
                logger.error(f"Error retrieving document: {e}")  
    messages = openai_client.prepare_messages_for_document(message, history, document_text)  

    async def generate_stream():  
        collected_response = ""  
        try:  
            stream_generator = await openai_client.chat_completion(messages, stream=True)  
            sent_anything = False  
            async for content in stream_generator:  
                collected_response += content  
                sent_anything = True  
                yield content.encode("utf-8")  
            if not sent_anything:  
                # OpenAI failed to generate anything  
                default_error = "I'm sorry, I couldn't generate a response."  
                yield default_error.encode("utf-8")  
            else:  
                background_tasks.add_task(  
                    save_chat_history, db, message, collected_response, document_id  
                )  
        except Exception as e:  
            logger.error(f"Error in chat completion: {e}")  
            error_msg = "I'm sorry, I encountered an error while processing your request."  
            yield error_msg.encode("utf-8")  
    return StreamingResponse(generate_stream(), media_type="text/plain")  

@router.get("/history", response_model=Dict[str, List[Dict[str, Any]]])  
async def get_chat_history(  
    document_id: Optional[str] = None,  
    skip: int = 0,  
    limit: int = 100,  
    db: Session = Depends(get_db)  
):  
    """Get chat history for a document."""  
    history = crud.get_chat_history(db, document_id, skip, limit)  
    return {  
        "history": [  
            {  
                "id": chat.id,  
                "user_message": chat.user_message,  
                "assistant_response": chat.assistant_response,  
                "document_id": chat.document_id,  
                "created_at": chat.created_at  
            } for chat in history  
        ]  
    }  

async def save_chat_history(  
    db: Session,  
    user_message: str,  
    assistant_response: str,  
    document_id: Optional[str] = None  
):  
    """Save chat history to the database."""  
    try:  
        crud.create_chat_history(  
            db,  
            user_message=user_message,  
            assistant_response=assistant_response,  
            document_id=document_id  
        )  
    except Exception as e:  
        logger.error(f"Error saving chat history: {e}")