import os  
from openai import AsyncAzureOpenAI  
from typing import List, Dict, Any, AsyncGenerator, Union  
import json  

class OpenAIClient:  
    def __init__(self):  
        """Initialize Azure OpenAI client."""  
        self.api_key = os.environ.get("AZURE_OPENAI_API_KEY")  
        self.endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")  
        self.api_version = os.environ.get("AZURE_OPENAI_API_VERSION")  
        self.model = os.environ.get("AZURE_OPENAI_MODEL")  
        self.default_temperature = 1  

        if not self.api_key or not self.endpoint:  
            raise ValueError("AZURE_OPENAI_API_KEY and AZURE_OPENAI_ENDPOINT must be set")  
        
        self.client = AsyncAzureOpenAI(  
            api_key=self.api_key,  
            api_version=self.api_version,  
            azure_endpoint=self.endpoint  
        )  
    
    async def chat_completion_stream(  
        self,  
        messages: List[Dict[str, str]],  
        temperature: float = None  
    ) -> AsyncGenerator[str, None]:  
        """Stream chat completion responses."""  
        temp = temperature if temperature is not None else self.default_temperature  
        
        try:  
            completion = await self.client.chat.completions.create(  
                model=self.model,  
                messages=messages,  
                temperature=temp,  
                stream=True  
            )  
            
            async for chunk in completion:  
                if hasattr(chunk, 'choices') and chunk.choices and len(chunk.choices) > 0:  
                    if hasattr(chunk.choices[0], 'delta') and hasattr(chunk.choices[0].delta, 'content'):  
                        if chunk.choices[0].delta.content:  
                            yield chunk.choices[0].delta.content  
        except Exception as e:  
            print(f"Error in streaming completion: {str(e)}")  
            yield f"Error: {str(e)}"  
    
    async def chat_completion_sync(  
        self,  
        messages: List[Dict[str, str]],  
        temperature: float = None  
    ) -> Dict[str, Any]:  
        """Get chat completion as a single response."""  
        temp = temperature if temperature is not None else self.default_temperature  
        
        try:  
            completion = await self.client.chat.completions.create(  
                model=self.model,  
                messages=messages,  
                temperature=temp  
            )  
            
            if hasattr(completion, 'choices') and completion.choices and len(completion.choices) > 0:  
                return {  
                    "content": completion.choices[0].message.content,  
                    "finish_reason": completion.choices[0].finish_reason  
                }  
            else:  
                print("Warning: No choices in completion response")  
                return {  
                    "content": "I'm sorry, I couldn't generate a response. Please try again.",  
                    "finish_reason": "error"  
                }  
        except Exception as e:  
            print(f"Error in sync completion: {str(e)}")  
            return {  
                "content": f"Error: {str(e)}",  
                "finish_reason": "error"  
            }  
    
    async def chat_completion(  
        self,  
        messages: List[Dict[str, str]],  
        temperature: float = None,  
        stream: bool = False  
    ) -> Union[AsyncGenerator[str, None], Dict[str, Any]]:  
        """Call the OpenAI API for chat completion."""  
        print(f"Sending messages to OpenAI API: {json.dumps(messages, indent=2)}")  
        
        if stream:  
            return self.chat_completion_stream(messages, temperature)  
        else:  
            return await self.chat_completion_sync(messages, temperature)  
    
    def prepare_messages_for_document(  
        self,  
        user_message: str,  
        chat_history: List = None,  
        document_text: str = None  
    ) -> List[Dict[str, str]]:  
        """Prepare messages for document-based chat."""  
        messages = []  
        
        # Enhanced system message for document editing  
        system_message = """You are a helpful document AI assistant that can help users create, modify, and improve documents.  
        
        When asked to update or edit a document:  
        1. Provide clear explanations of your suggested changes  
        2. Return the full updated document with all changes incorporated  
        3. Format the document to maintain its original structure  
        4. Keep all headings, tables, and formatting consistent  
        
        Your goal is to provide a complete updated version that the user can directly use.  
        """  
        
        if document_text:  
            system_message += "\n\nThe user is working with the following document:\n\n"  
            if len(document_text) > 2000:  
                system_message += document_text[:2000] + "...\n\n(Document continues)"  
            else:  
                system_message += document_text  
        
        messages.append({"role": "system", "content": system_message})  
        
        if chat_history:  
            for entry in chat_history:  
                # Handle different possible formats safely  
                if isinstance(entry, (list, tuple)):  
                    if len(entry) >= 2:  
                        user_msg, assistant_msg = entry[0], entry[1]  
                        if user_msg is not None:  
                            messages.append({"role": "user", "content": user_msg})  
                        if assistant_msg is not None:  
                            messages.append({"role": "assistant", "content": assistant_msg})  
                elif isinstance(entry, dict):  
                    user_msg = entry.get('user_message') or entry.get('user')  
                    assistant_msg = entry.get('assistant_response') or entry.get('assistant')  
                    if user_msg is not None:  
                        messages.append({"role": "user", "content": user_msg})  
                    if assistant_msg is not None:  
                        messages.append({"role": "assistant", "content": assistant_msg})  
        
        # Add current message with specific editing instructions if needed  
        if "edit" in user_message.lower() or "update" in user_message.lower() or "revise" in user_message.lower():  
            enhanced_message = f"""  
            {user_message}  
            
            Important: Please provide the full updated document content. Your response should contain the complete revised document that I can use to replace the original.  
            """  
            messages.append({"role": "user", "content": enhanced_message})  
        else:  
            messages.append({"role": "user", "content": user_message})  
        
        return messages