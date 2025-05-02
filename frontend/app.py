import gradio as gr
import requests
import os
import json
import uuid
import tempfile
import time
from datetime import datetime
from functools import partial

# API Configuration
API_URL = os.environ.get("API_URL", "http://localhost:8000")

# Session management
sessions = {}

def get_session_state(session_id):
    if session_id not in sessions:
        sessions[session_id] = {"document_id": None, "document_data": {}}
    return sessions[session_id]

def safe_api_call(method, url, **kwargs):
    try:
        response = requests.request(method, url, **kwargs)
        response.raise_for_status()
        return response
    except requests.exceptions.RequestException as e:
        print(f"API Error: {e}")
        # Return a mock response object with status_code attribute
        class MockResponse:
            def __init__(self):
                self.status_code = 500
                self.text = str(e)
            def json(self):
                return {"error": str(e)}
        return MockResponse()

def create_app():
    with gr.Blocks(title="Document AI Assistant", theme=gr.themes.Base(), css_paths="style.css") as app:
        session_id = gr.State(str(uuid.uuid4()))
        
        gr.Markdown("# Document AI Assistant")
        document_state, current_document_id, editor_content = gr.State({}), gr.State(None), gr.State("")
        
        # --- Document Management Tab ---
        with gr.TabItem("Document Management"):
            (document_upload, document_selector, document_preview, status_text,
             active_document_display, refresh_button, version_selector, download_button) = build_document_management_ui()
            
            # Refresh documents list
            refresh_button.click(
                fn=refresh_documents,
                inputs=[current_document_id, session_id],
                outputs=[document_selector, status_text]
            ).then(
                fn=update_active_document_display,
                inputs=[current_document_id, session_id],
                outputs=[active_document_display]
            )
            
            # Update version selector when document is selected
            document_selector.change(
                fn=get_document_versions,
                inputs=[document_selector, session_id],
                outputs=[version_selector]
            )
            
            # Download document version
            download_button.click(
                fn=download_document_version,
                inputs=[document_selector, version_selector, session_id],
                outputs=[gr.File(label="Downloaded Document")]
            )
            
        # --- Chat with Document Tab ---
        with gr.TabItem("Chat with Document"):
            chat_examples = [
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
                fn=partial(chat_with_document, session_id=session_id),
                title="Document AI Chat",
                examples=chat_examples,
                retry_btn=None,
                undo_btn=None,
                clear_btn="Clear Chat",
            )
            
        # --- Edit Document Tab ---
        with gr.TabItem("Edit Document"):
            document_editor = gr.Textbox(
                label="Document Editor", lines=25, max_lines=25, interactive=True, elem_classes=['scrollable-preview'])
            
            with gr.Row():
                reload_button = gr.Button("Reload Original", elem_classes=["orange-button"])
                save_button = gr.Button("Save Changes", elem_classes=["green-button"])
                apply_chat_button = gr.Button("Apply Latest Chat Response", elem_classes=["blue-button"])
                
            edit_status = gr.Textbox(label="Status", interactive=False)
            
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
            fn=lambda x: x,
            inputs=[editor_content],
            outputs=[document_editor]
        ).then(
            fn=update_active_document_display,
            inputs=[current_document_id, session_id],
            outputs=[active_document_display]
        ).then(
            fn=get_document_versions,
            inputs=[current_document_id, session_id],
            outputs=[version_selector]
        )
        
        document_selector.change(
            fn=load_document_preview_and_update_state,
            inputs=[document_selector, session_id],
            outputs=[document_preview, document_state, editor_content, current_document_id, status_text]
        ).then(
            fn=lambda x: x,
            inputs=[editor_content],
            outputs=[document_editor]
        ).then(
            fn=update_active_document_display,
            inputs=[current_document_id, session_id],
            outputs=[active_document_display]
        ).then(
            fn=get_document_versions,
            inputs=[current_document_id, session_id],
            outputs=[version_selector]
        )
        
        # --- Event Bindings (Edit Document) ---
        apply_chat_button.click(
            fn=apply_latest_chat_to_editor,
            inputs=[chat_interface.chatbot, current_document_id, session_id],
            outputs=[document_editor, edit_status]
        )
        
        reload_button.click(
            fn=reload_original_document,
            inputs=[current_document_id, session_id],
            outputs=[document_editor, edit_status]
        )
        
        save_button.click(
            fn=save_document_changes,
            inputs=[current_document_id, document_editor, session_id],
            outputs=[document_preview, edit_status, document_state]
        ).then(
            fn=get_document_versions,
            inputs=[current_document_id, session_id],
            outputs=[version_selector]
        )
    
    return app

def chat_with_document(message, history, session_id):
    session = get_session_state(session_id)
    document_id = session.get("document_id")
    document_data = session.get("document_data", {})
    if not document_id:
        yield "No document selected. Please go to the Document Management tab and select or upload a document first."
        return
    
    document_text = document_data.get("content", "")
    
    # Prepare the chat request
    chat_request = {
        "message": message,
        "history": [
            {
                "user_message": h[0],
                "assistant_response": h[1]
            } for h in history
        ]
    }
    
    # Add document context if available
    if document_id:
        chat_request["document_id"] = document_id
        chat_request["document_text"] = document_text
    
    # Stream the response
    response = safe_api_call("POST", f"{API_URL}/chat/stream", json=chat_request, stream=True)
    
    if response.status_code != 200:
        yield f"Error: {response.text}"
        return
    
    collected_response = ""
    for line in response.iter_lines():
        if line:
            chunk = json.loads(line.decode('utf-8'))
            content = chunk.get("content", "")
            collected_response += content
            yield collected_response

def build_document_management_ui():
    """Create the document management UI components."""
    
    document_upload = gr.File(
        label="Upload Document", file_types=[".md", ".docx", ".pdf"], type="filepath"
    )
    
    active_document_display = gr.Textbox(
        label="Active Document", value="No document selected", interactive=False
    )
    
    refresh_button = gr.Button("Refresh Documents", elem_classes=["orange-button"])
    
    version_selector = gr.Dropdown(
        label="Select Version",
        choices=["Current Working Version (Markdown)"],
        value="Current Working Version (Markdown)",
    )
    
    download_button = gr.Button("Download Document", elem_classes=["green-button"])
    
    document_selector = gr.Dropdown(
        label="Select Document",
        choices=["Select Document"] + get_documents_list(),
        value="Select Document",
        elem_classes=['document-selector']
    )
    
    document_preview = gr.Textbox(
        label="Document Preview",
        lines=20,
        max_lines=20,
        interactive=False,
        elem_classes=['scrollable-preview', 'document-preview']
    )
    
    status_text = gr.Textbox(label="Status", interactive=False)
    
    return document_upload, document_selector, document_preview, status_text, active_document_display, refresh_button, version_selector, download_button

def get_documents_list():
    response = safe_api_call("GET", f"{API_URL}/documents")
    if response.status_code != 200:
        return []
    documents = response.json().get("documents", [])
    return [(f"{doc['name']} (ID: {doc['id']})", doc['id']) for doc in documents]

def update_active_document_display(document_id, session_id):
    if not document_id:
        return "No document selected"
    response = safe_api_call("GET", f"{API_URL}/documents/{document_id}")
    if response.status_code == 200:
        document_data = response.json()
        document_name = document_data.get("name", "Unnamed")
        return f"Name: {document_name} | ID: {document_id}"
    return f"ID: {document_id}"

def reload_original_document(document_id, session_id):
    if isinstance(document_id, list):
        document_id = document_id[0] if document_id else None
    if not document_id:
        return "", "No document selected."
    response = safe_api_call("GET", f"{API_URL}/documents/{document_id}")
    if response.status_code == 200:
        document_data = response.json()
        document_text = document_data.get("content", "")
        session = get_session_state(session_id)
        session["document_data"] = document_data
        return document_text, "Original document loaded successfully."
    return "", "Error loading original document."

def apply_latest_chat_to_editor(chat_history, document_id, session_id):
    if isinstance(document_id, list):
        document_id = document_id[0] if document_id else None
    if not document_id:
        return "", "No document selected."
    if not chat_history or len(chat_history) == 0:
        return "", "No chat history available."
    
    # Get the latest assistant response
    latest_response = chat_history[-1][1]
    return latest_response, "Applied latest chat response to editor."

def upload_document(file_path, session_id):
    """Upload a document to the API."""
    if not file_path:
        return "No file selected.", None
    
    try:
        # Get the file name from the path
        file_name = os.path.basename(file_path)
        
        # Read the file content
        with open(file_path, "rb") as f:
            file_content = f.read()
        
        # Create a temporary file to send
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file_name)[1]) as temp_file:
            temp_file.write(file_content)
            temp_file_path = temp_file.name
        
        # Send the file to the API
        files = {"file": (file_name, open(temp_file_path, "rb"))}
        response = safe_api_call("POST", 
            f"{API_URL}/documents/upload",
            files=files
        )
        
        # Clean up the temporary file
        os.unlink(temp_file_path)
        
        if response.status_code != 200:
            return "Error uploading document.", None
        
        result = response.json()
        doc_id = result.get("document_id")
        
        # Update session state
        session = get_session_state(session_id)
        session["document_id"] = doc_id
        
        doc_response = safe_api_call("GET", f"{API_URL}/documents/{doc_id}")
        if doc_response.status_code == 200:
            session["document_data"] = doc_response.json()
        
        return f"Document uploaded successfully. ID: {doc_id}", doc_id
    except Exception as e:
        return f"Error uploading document: {str(e)}", None

def update_after_upload(document_id, session_id):
    if not document_id:
        return gr.update(), "", {}, ""
    
    # Get the document data
    doc_response = safe_api_call("GET", f"{API_URL}/documents/{document_id}")
    if doc_response.status_code == 200:
        doc_data = doc_response.json()
        doc_content = doc_data.get("content", "")
        doc_name = doc_data.get("name", "Unnamed")
        
        # Update session state
        session = get_session_state(session_id)
        session["document_id"] = document_id
        session["document_data"] = doc_data
        
        # Get updated document list
        documents_list = get_documents_list()
        display_name = f"{doc_name} (ID: {document_id})"
        
        # Create choices list with tuples (display_name, id)
        all_choices = [("Select Document", "Select Document")] + documents_list
        
        return gr.update(choices=all_choices, value=(display_name, document_id)), doc_content, doc_data, doc_content
    
    # If there was an error, still try to update the dropdown
    documents_list = get_documents_list()
    all_choices = [("Select Document", "Select Document")] + documents_list
    return gr.update(choices=all_choices, value=("Select Document", "Select Document")), "Error loading document content", {}, ""

def refresh_documents(current_id=None, session_id=None):
    response = safe_api_call("GET", f"{API_URL}/documents")
    if response.status_code == 200:
        documents = response.json().get("documents", [])
        # Create a list of tuples with (display_name, id) for the dropdown
        document_list = [(f"{doc.get('name')} (ID: {doc.get('id')})", doc.get('id')) for doc in documents]
        all_choices = [("Select Document", "Select Document")] + document_list
        
        # Find the current document in the list to maintain selection
        current_display_name = None
        if current_id:
            for display_name, doc_id in document_list:
                if doc_id == current_id:
                    current_display_name = display_name
                    break
        
        if current_id and current_display_name:
            if session_id: get_session_state(session_id)["document_id"] = current_id
            return gr.update(choices=all_choices, value=(current_display_name, current_id)), "Document list refreshed."
        if session_id: get_session_state(session_id)["document_id"] = None
        return gr.update(choices=all_choices, value=("Select Document", "Select Document")), "Document list refreshed. No document selected."
    return gr.update(), "Error refreshing documents."

def load_document_preview_and_update_state(document_id, session_id):
    # Handle tuple format from dropdown (display_name, id)
    if isinstance(document_id, tuple):
        document_id = document_id[1]  # Extract the ID from the tuple
    
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
    if response.status_code == 200:
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
    try:
        response = safe_api_call("PUT", 
            f"{API_URL}/documents/{document_id}",
            json={"document_text": document_content}
        )
        if response.status_code == 200:
            doc_response = safe_api_call("GET", f"{API_URL}/documents/{document_id}")
            if doc_response.status_code == 200:
                document_data = doc_response.json()
                document_text = document_data.get("content", "")
                session = get_session_state(session_id)
                session["document_data"] = document_data
                return document_text, "Document saved successfully!", document_data
            return document_content, "Document saved, but could not refresh preview.", {}
    except Exception as e:
        print(f"Error saving document: {e}")
    return document_content, "Error saving document.", {}

def download_document_version(document_id, version_filename, session_id):
    """Download a specific version of a document."""
    # Handle tuple format from dropdown (display_name, id)
    if isinstance(document_id, tuple):
        document_id = document_id[1]  # Extract the ID from the tuple
    
    if document_id == "Select Document":
        return None
    
    if isinstance(document_id, list):
        document_id = document_id[0] if document_id else None
    
    if not document_id:
        return None
    
    try:
        # If version is "Current Working Version", download the current document
        if version_filename == "Current Working Version (Markdown)":
            response = safe_api_call("GET", f"{API_URL}/documents/{document_id}/export")
        elif version_filename == "Original":
            response = safe_api_call("GET", f"{API_URL}/documents/{document_id}/download/original/{document_id}")
        else:
            # For exports, use the exports path
            response = safe_api_call("GET", f"{API_URL}/documents/{document_id}/download/exports/{version_filename}")
        
        if response.status_code == 200:
            # Get the document name for better filename
            filename_response = safe_api_call("GET", f"{API_URL}/documents/{document_id}")
            filename = "document.txt"
            if filename_response.status_code == 200:
                doc_data = filename_response.json()
                original_name = doc_data.get("name", "document").rsplit(".", 1)[0]
                
                if version_filename == "Current Working Version (Markdown)":
                    filename = f"{original_name}.md"
                elif version_filename == "Original":
                    filename = doc_data.get("name", "document")
                else:
                    # For exports, use timestamp in the filename
                    ext = version_filename.split(".")[-1]
                    timestamp = version_filename.split(".")[0]
                    filename = f"{original_name}_{timestamp}.{ext}"
            
            # Save the content to a temporary file
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=f"_{filename}")
            temp_file.write(response.content)
            temp_file.close()
            
            return temp_file.name
    except Exception as e:
        print(f"Error downloading document: {e}")
    return None

def get_document_versions(document_id, session_id):
    """Get all available versions of a document."""
    # Handle tuple format from dropdown (display_name, id)
    if isinstance(document_id, tuple):
        document_id = document_id[1]  # Extract the ID from the tuple
    
    if document_id == "Select Document":
        return gr.update(choices=["Current Working Version (Markdown)"], value="Current Working Version (Markdown)")
    
    if isinstance(document_id, list):
        document_id = document_id[0] if document_id else None
    
    if not document_id:
        return gr.update(choices=["Current Working Version (Markdown)"], value="Current Working Version (Markdown)")
    
    try:
        response = safe_api_call("GET", f"{API_URL}/documents/{document_id}/versions")
        if response.status_code == 200:
            versions = response.json().get("versions", [])
            choices = ["Current Working Version (Markdown)", "Original"]
            
            # Add export versions
            for version in versions:
                if version.get("type") == "export":
                    choices.append(version.get("filename"))
            
            return gr.update(choices=choices, value="Current Working Version (Markdown)")
    except Exception as e:
        print(f"Error getting document versions: {e}")
    
    return gr.update(choices=["Current Working Version (Markdown)"], value="Current Working Version (Markdown)")

# Create and launch the app
app = create_app()

if __name__ == "__main__":
    app.launch(server_name="0.0.0.0", server_port=7860)
