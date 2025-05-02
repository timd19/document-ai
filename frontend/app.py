import gradio as gr  
import requests  
import os  
import tempfile  
import uuid  
# --- Configuration ---  
API_URL = os.environ.get("API_URL", "http://backend:8000")  
# --- In-Memory Session State (use Redis or DB for production) ---  
session_states = {}  
# --- Helper for robust API calls ---  
def safe_api_call(method, url, **kwargs):  
    """Wrapper to safely call the API."""  
    try:  
        r = requests.request(method, url, timeout=30, **kwargs)  
        r.raise_for_status()  
        return r  
    except Exception as e:  
        print(f"API call error: {e}")  
        return None 
# --- Utility for per-session state access ---  
def get_session_state(session_id):  
    if session_id not in session_states:  
        session_states[session_id] = {}  
    return session_states[session_id]  
# --- Gradio App Construction ---  
def create_app():  
    with gr.Blocks(title="Document AI Assistant", theme=gr.themes.Base(), css_paths="style.css") as app:  
        session_id = gr.State(str(uuid.uuid4()))  
        gr.Markdown("# Document AI Assistant")  
        document_state, current_document_id, editor_content = gr.State({}), gr.State(None), gr.State("")  
        
        # Define document_editor at the top level, outside of any tabs
        # This ensures it's defined before it's referenced in any event handlers
        document_editor = gr.Textbox(
            label="Document Editor", lines=25, max_lines=25, interactive=True, elem_classes=['scrollable-preview'],
            visible=False  # Initially hidden, will be shown in the Edit Document tab
        )
        
        with gr.Tabs() as tabs:  
            # --- Document Management Tab ---  
            with gr.TabItem("Document Management"):  
                (document_upload, document_selector, document_preview, status_text,  
                 active_document_display, refresh_button, download_button, version_selector) = build_document_management_ui()  
                refresh_button.click(  
                    fn=refresh_documents,  
                    inputs=[current_document_id, session_id],  
                    outputs=[document_selector, status_text]  
                ).then(  
                    fn=update_active_document_display,  
                    inputs=[current_document_id, session_id],  
                    outputs=[active_document_display]  
                )  
                download_button.click(  
                    fn=download_document,  
                    inputs=[document_selector, document_preview, session_id, version_selector],  
                    outputs=[gr.File(label="Downloaded Document")]  
                )  
                # Fetch versions when a document is selected  
                document_selector.change(  
                    fn=fetch_document_versions,  
                    inputs=[document_selector],
                    outputs=[version_selector]  
                )
                
                # Add version selector change event
                version_selector.change(  
                    fn=load_version,  
                    inputs=[document_selector, version_selector],  
                    outputs=[editor_content]  
                ).then(
                    # Update the document preview with the loaded version content
                    fn=lambda content: content,
                    inputs=[editor_content],
                    outputs=[document_preview]
                ).then(
                    # Update the document editor with the loaded version content
                    fn=lambda content: content,
                    inputs=[editor_content],
                    outputs=[document_editor]
                )
                
            # --- Chat Tab ---  
            with gr.TabItem("Chat with Document"):  
                example_prompts = [  
                    ["Summarize this document for me."],  
                    ["What are the key points in this document?"],  
                    ["Suggest improvements to make this document more concise?"],  
                    ["Please proofread this document and identify any errors."],  
                    ["How can I restructure this document to improve its flow?"],  
                    ["Suggest a better title and introduction for this document."],  
                    ["What technical terms in this document might need explanation?"],  
                    ["Can you identify any missing information in this document?"],  
                    ["Format this document according to Softchoice style guidelines."]  
                ]  
                chat_interface = gr.ChatInterface(  
                    fn=process_chat_message,  
                    examples=example_prompts,  
                    title="Document AI Chat",  
                    chatbot=gr.Chatbot(show_copy_button=True, height=400, type="messages"),  
                    additional_inputs=[session_id],  
                    additional_outputs=None  
                )  
            # --- Edit Document Tab ---  
            with gr.TabItem("Edit Document"):
                # Instead of creating a new document_editor, we'll reuse the one defined earlier
                # and make it visible in this tab
                document_editor.visible = True
                
                edit_status = gr.Textbox(label="Status", interactive=False)
                
                with gr.Row():  
                    apply_edits_button = gr.Button("Apply AI Suggestions", elem_classes=["green-button"])  
                    reload_original_button = gr.Button("Reload Original", elem_classes=["orange-button"])  
                    save_edits_button = gr.Button("Save Changes", elem_classes=["save-button"])
        # --- Event Bindings (Document Management) ---  
        document_upload.upload(  
            fn=upload_document,  
            inputs=[document_upload, session_id],  
            outputs=[status_text, current_document_id]  
        ).then(  
            fn=update_after_upload,  
            inputs=[current_document_id, session_id],  
            outputs=[document_selector, document_preview, document_state, editor_content]  
        ).then(  
            fn=lambda content: content,  
            inputs=[editor_content],  
            outputs=[document_editor]  
        ).then(  
            fn=update_active_document_display,  
            inputs=[current_document_id, session_id],  
            outputs=[active_document_display]  
        )  
        document_selector.change(  
            fn=load_document_and_versions,  
            inputs=[document_selector, session_id],  
            outputs=[  
                document_preview,  
                document_state,  
                editor_content,  
                current_document_id,  
                status_text,  
                version_selector  
            ]  
        ).then(  
            fn=lambda content: content,  
            inputs=[editor_content],  
            outputs=[document_editor]  
        ).then(  
            fn=update_active_document_display,  
            inputs=[current_document_id, session_id],  
            outputs=[active_document_display]  
        ) 
        # --- Event Bindings (Editing) ---  
        apply_edits_button.click(  
            fn=apply_latest_chat_to_editor,  
            inputs=[chat_interface.chatbot, current_document_id, session_id],  
            outputs=[document_editor, edit_status]  
        )  
        reload_original_button.click(  
            fn=reload_original_document,  
            inputs=[current_document_id, session_id],  
            outputs=[document_editor, edit_status]  
        )  
        save_edits_button.click(  
            fn=save_document_changes,  
            inputs=[current_document_id, document_editor, session_id],  
            outputs=[document_preview, edit_status, document_state]  
        ).then(  
            fn=lambda doc_content: doc_content,  
            inputs=[document_preview],  
            outputs=[document_editor]  
        )  
        app.load(fn=on_page_load, inputs=None, outputs=[session_id])  
    return app  
def on_page_load():  
    """Regenerate session ID (fresh session) on app load."""  
    return str(uuid.uuid4())  
def process_chat_message(message, history, session_id):  
    """Chat with backend, stream output if possible."""  
    session = get_session_state(session_id)  
    document_id = session.get("document_id")  
    document_data = session.get("document_data", {})  
    if not document_id:  
        yield "No document selected. Please go to the Document Management tab and select or upload a document first."  
        return  
    try:  
        document_text = document_data.get("content", "")  
        formatted_history = []  
        if history:  
            for entry in history:  
                if isinstance(entry, (list, tuple)) and len(entry) == 2:  
                    user_msg, bot_msg = entry  
                    if user_msg is not None:  
                        formatted_history.append({"role": "user", "content": user_msg})  
                    if bot_msg is not None:  
                        formatted_history.append({"role": "assistant", "content": bot_msg})  
                elif isinstance(entry, dict):  
                    role = entry.get("role")  
                    content = entry.get("content")  
                    if role in ("user", "assistant") and content is not None:  
                        formatted_history.append({"role": role, "content": content})  
                
        payload = {  
            "message": message,  
            "history": formatted_history,  
            "document_id": document_id,  
            "document_text": document_text  
        }  
        
        # Streaming  
        with requests.post(f"{API_URL}/chat", json=payload, stream=True, timeout=60) as response:  
            if response.status_code == 200:  
                full_response = ""  
                for chunk in response.iter_content(chunk_size=1024):  
                    if chunk:  
                        text_chunk = chunk.decode('utf-8')  
                        full_response += text_chunk  
                        yield full_response  
                session["last_ai_response"] = full_response  
            else:  
                yield f"Error: {response.status_code} - {response.text}"
    except Exception as e:  
        yield f"Error processing message: {str(e)}"  
def apply_latest_chat_to_editor(chatbot, document_id, session_id):  
    """Apply the latest AI response to the document editor."""  
    session = get_session_state(session_id)  
    last_ai_response = session.get("last_ai_response", "")  
    if not last_ai_response:  
        if chatbot and len(chatbot) > 0:  
            # Try to get the last AI response from the chatbot history  
            last_entry = chatbot[-1]  
            if isinstance(last_entry, (list, tuple)) and len(last_entry) == 2:  
                last_ai_response = last_entry[1] or ""  
    if not last_ai_response:  
        return "", "No AI suggestions available to apply."  
    # Get the current document content  
    document_data = session.get("document_data", {})  
    document_content = document_data.get("content", "")  
    # For now, just replace the content with the AI response  
    # In a real app, you might want to do something more sophisticated  
    return last_ai_response, "AI suggestions applied to editor. Review and save changes if desired."  
def reload_original_document(document_id, session_id):  
    """Reload the original document content into the editor."""  
    session = get_session_state(session_id)  
    document_data = session.get("document_data", {})  
    document_content = document_data.get("content", "")  
    return document_content, "Original document content reloaded."  
def update_active_document_display(document_id, session_id):  
    """Update the active document display with the current document name."""  
    session = get_session_state(session_id)  
    document_data = session.get("document_data", {})  
    document_name = document_data.get("name", "No document")  
    if document_id and document_id != "Select Document":  
        return f"Active: {document_name} (ID: {document_id})"  
    return "No document selected"  
def get_documents_list():  
    """Get list of available documents from the API."""  
    response = safe_api_call("GET", f"{API_URL}/documents")  
    if response:  
        documents = response.json().get("documents", [])  
        return [doc.get("id") for doc in documents]  
    return []  
def upload_document(file_path, session_id):  
    """Upload a document to the API."""  
    if not file_path:  
        return "No file selected.", None  
    try:  
        with open(file_path, "rb") as f:  
            files = {"file": f}  
            response = requests.post(f"{API_URL}/documents/upload", files=files)  
            if response.status_code == 200:  
                document_id = response.json().get("document_id")  
                return f"Document uploaded successfully! ID: {document_id}", document_id  
            return f"Error uploading document: {response.status_code} - {response.text}", None  
    except Exception as e:  
        return f"Error uploading document: {str(e)}", None  
def update_after_upload(document_id, session_id):  
    """Update UI after document upload."""  
    if not document_id:  
        return gr.update(), "", {}, ""  
    documents_list = get_documents_list()  
    if document_id not in documents_list:  
        documents_list.append(document_id)  
    doc_response = safe_api_call("GET", f"{API_URL}/documents/{document_id}")  
    if doc_response:  
        doc_data = doc_response.json()  
        doc_content = doc_data.get("content", "")  
        session = get_session_state(session_id)  
        session["document_id"] = document_id  
        session["document_data"] = doc_data  
        all_choices = ["Select Document"] + documents_list  
        return gr.update(choices=all_choices, value=document_id), doc_content, doc_data, doc_content  
    all_choices = ["Select Document"] + documents_list  
    return gr.update(choices=all_choices, value="Select Document"), "Error loading document content", {}, ""  
def refresh_documents(current_id=None, session_id=None):  
    response = safe_api_call("GET", f"{API_URL}/documents")  
    if response:  
        documents = response.json().get("documents", [])  
        document_list = [doc.get("id") for doc in documents]  
        all_choices = ["Select Document"] + document_list  
        if current_id and current_id in document_list:  
            if session_id: get_session_state(session_id)["document_id"] = current_id  
            return gr.update(choices=all_choices, value=current_id), "Document list refreshed."  
        if session_id: get_session_state(session_id)["document_id"] = None  
        return gr.update(choices=all_choices, value="Select Document"), "Document list refreshed. No document selected."  
    return gr.update(), "Error refreshing documents."
def build_document_management_ui():  
    with gr.Row():  
        with gr.Column(scale=1):  
            document_upload = gr.File(  
                label="Upload Document", file_types=[".md", ".docx", ".pdf"], type="filepath"  
            )  
            status_text = gr.Textbox(label="Status", interactive=False)  
            active_document_display = gr.Textbox(  
                label="Active Document", value="No document selected", interactive=False  
            )  
            refresh_button = gr.Button("Refresh Documents", elem_classes=["orange-button"])  
            download_button = gr.Button("Download Document", elem_classes=["green-button"])  
        with gr.Column(scale=2):  
            document_selector = gr.Dropdown(  
                label="Select Document",  
                choices=["Select Document"] + get_documents_list(),  
                value="Select Document",  
                interactive=True,  
                filterable=True  
            )  
            version_selector = gr.Dropdown(choices=["0"], label="Select Version")  
 
            document_preview = gr.Textbox(  
                label="Document Preview",  
                lines=25,  
                max_lines=25,  
                interactive=False,  
                elem_classes=["scrollable-preview"],  
            )  
    return document_upload, document_selector, document_preview, status_text, active_document_display, refresh_button, download_button, version_selector
def load_document_and_versions(document_id, session_id):
    """Load document content, update state, and fetch versions."""
    preview, state, content, doc_id, status, versions = load_document_preview_and_update_state(document_id, session_id)
    # Fetch versions for the document
    if doc_id:
        version_list = fetch_document_versions(doc_id)
        if version_list:
            return preview, state, content, doc_id, status, gr.update(choices=version_list)
    return preview, state, content, doc_id, status, gr.update(choices=["0"])
def load_document_preview_and_update_state(document_id, session_id):  
    if not document_id or document_id == "Select Document":  
        get_session_state(session_id)["document_id"] = None  
        get_session_state(session_id)["document_data"] = {}  
        return "", {}, "", None, "Please select a document."  
    if isinstance(document_id, list):  
        document_id = document_id[0] if document_id else None  
        if not document_id:  
            get_session_state(session_id)["document_id"] = None  
            get_session_state(session_id)["document_data"] = {}  
            return "", {}, "", None, "No document selected."  
    response = safe_api_call("GET", f"{API_URL}/documents/{document_id}")  
    if response:  
        document_data = response.json()  
        document_text = document_data.get("content", "")  
        document_name = document_data.get("name", "Unnamed")  
        session = get_session_state(session_id)  
        session["document_id"] = document_id  
        session["document_data"] = document_data  
        status_message = f"Document '{document_name}' loaded successfully."  
        return document_text, document_data, document_text, document_id, status_message  
    get_session_state(session_id)["document_id"] = None  
    get_session_state(session_id)["document_data"] = {}  
    return "Error loading document.", {}, "", None, "Error loading document."  
def save_document_changes(document_id, document_content, session_id):  
    if isinstance(document_id, list):  
        document_id = document_id[0] if document_id else None  
    if not document_id or not document_content:  
        return document_content, "No document selected or no content to save.", {}  
    response = safe_api_call(  
        "PUT",  
        f"{API_URL}/documents/{document_id}",  
        json={"document_text": document_content}  
    )  
    if response:  
        doc_response = safe_api_call("GET", f"{API_URL}/documents/{document_id}")  
        if doc_response:  
            document_data = doc_response.json()  
            document_text = document_data.get("content", "")  
            session = get_session_state(session_id)  
            session["document_data"] = document_data  
            return document_text, "Document saved successfully!", document_data  
        else:  
            return document_content, "Document saved, but could not refresh preview.", {}  
    else:  
        return document_content, "Error saving document.", {}  
def fetch_document_versions(document_id):  
    response = safe_api_call("GET", f"{API_URL}/documents/{document_id}/versions")  
    if response:  
        versions = response.json()  
        return [f"{version['version']}" for version in versions]  
    return []  
def load_version(document_id, version):
    # Fix: Use the correct endpoint for document versions
    if version == "0":
        # For the original version, use the standard document endpoint
        response = safe_api_call("GET", f"{API_URL}/documents/{document_id}")
    else:
        # For other versions, use the version-specific endpoint with format=md parameter
        response = safe_api_call("GET", f"{API_URL}/documents/{document_id}/version/{version}?format=md")
    
    if response:
        # Update the session state with the current version
        session_id = list(session_states.keys())[0] if session_states else None
        if session_id:
            session = get_session_state(session_id)
            session["current_version"] = version
            
            # Get the document content based on version
            if version == "0":
                document_content = response.json().get("content", "")
                # Update the document_data in the session state with the current version's content
                if "document_data" in session:
                    session["document_data"]["content"] = document_content
            else:
                # For version endpoint, we need to handle the response differently
                try:
                    document_content = response.content.decode('utf-8')
                    # Update the document_data in the session state with the current version's content
                    if "document_data" in session:
                        session["document_data"]["content"] = document_content
                except:
                    # Fallback if there's an issue with decoding
                    document_content = response.text if hasattr(response, 'text') else ""
                    if "document_data" in session:
                        session["document_data"]["content"] = document_content
            
            return document_content
        
        # If no session_id found, just return the content without updating session
        if version == "0":
            return response.json().get("content", "")
        try:
            return response.content.decode('utf-8')
        except:
            return response.text if hasattr(response, 'text') else ""
    return ""
def download_document(document_id, current_content, session_id, version=None):
    if document_id == "Select Document":
        return None
    if isinstance(document_id, list):
        document_id = document_id[0] if document_id else None
    if not document_id:
        return None
    
    # If a version is specified, use the version-specific endpoint
    if version and version != "0":
        response = safe_api_call("GET", f"{API_URL}/documents/{document_id}/version/{version}?format=md")
        if response:
            filename_response = safe_api_call("GET", f"{API_URL}/documents/{document_id}")
            filename = "document.txt"
            if filename_response:
                doc_data = filename_response.json()
                base_filename = doc_data.get("name", "document").rsplit('.', 1)[0]
                filename = f"{base_filename}_v{version}.md"
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=f"_{filename}")
            temp_file.write(response.content)
            temp_file.close()
            return temp_file.name
    else:
        # For the original version, use the standard download endpoint
        response = safe_api_call("GET", f"{API_URL}/documents/{document_id}/download")
        if response:
            filename_response = safe_api_call("GET", f"{API_URL}/documents/{document_id}")
            filename = "document.txt"
            if filename_response:
                doc_data = filename_response.json()
                filename = doc_data.get("name", filename)
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=f"_{filename}")
            temp_file.write(response.content)
            temp_file.close()
            return temp_file.name
    return None
# --- Run the App ---  
app = create_app()  
if __name__ == "__main__":  
    app.launch(server_name="0.0.0.0", server_port=7860)

