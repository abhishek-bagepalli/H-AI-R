import os
import imaplib
import smtplib
import email as email_module
import re
from email.message import EmailMessage
from typing import Dict, List, Any, Optional
from firebase_config import db
from dotenv import load_dotenv
from langchain.text_splitter import CharacterTextSplitter
from langchain_community.document_loaders import TextLoader, DirectoryLoader
from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain.prompts import ChatPromptTemplate
from langchain.schema.output_parser import StrOutputParser
from langchain_core.documents import Document
from langchain.tools import tool
from collections import defaultdict
# from response_templates import response_templates
from extract_placeholders import extract_placeholders
from langchain_core.tools import tool
import json
from auth import User
from google.cloud.firestore import FieldFilter
import firebase_admin
import numpy as np

load_dotenv()

# Environment and configuration setup
# EMAIL_USER = os.getenv("EMAIL_USER")
# EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")

# Directory setup for document storage and retrieval
BASE_DOCUMENTS_DIR = "documents/"
BASE_DB_DIR = "db/"

def get_user_directories(user_id: str) -> Dict[str, str]:
    """Get user-specific directory paths."""
    return {
        'documents': os.path.join(BASE_DOCUMENTS_DIR, user_id),
        'db': os.path.join(BASE_DB_DIR, f"chroma_db_{user_id}")
    }

def ensure_user_directories(user_id: str) -> None:
    """Create user-specific directories if they don't exist."""
    dirs = get_user_directories(user_id)
    for dir_path in dirs.values():
        os.makedirs(dir_path, exist_ok=True)

# Initialize the LLM
model = ChatOpenAI(model="gpt-3.5-turbo")

# Vector store initialization
def initialize_vectorstore(user_id: str = None) -> None:
    """Initialize or update document embeddings in Firebase."""
    try:
        if not user_id:
            print("Warning: No user_id provided, skipping vector store initialization")
            return

        # Initialize Firebase Storage and Firestore
        storage = firebase_admin.storage.bucket()
        db = firebase_admin.firestore.client()

        # Get user's documents from Firebase Storage
        print(f"Loading documents for user {user_id} from Firebase Storage...")
        user_docs_ref = storage.list_blobs(prefix=f"users/{user_id}/documents/")
        documents = []

        for blob in user_docs_ref:
            if blob.name.endswith('.pdf'):
                print(f"Processing document: {blob.name}")
                # Download PDF content
                pdf_content = blob.download_as_bytes()
                
                # Extract text from PDF
                text = extract_text_from_pdf(pdf_content)
                
                # Split text into chunks
                text_splitter = CharacterTextSplitter(chunk_size=1000, chunk_overlap=0)
                chunks = text_splitter.split_text(text)
                
                # Create embeddings for each chunk
                embedding = OpenAIEmbeddings(model="text-embedding-3-small")
                embeddings = embedding.embed_documents(chunks)
                
                # Store chunks and embeddings in Firestore
                doc_ref = db.collection('users').document(user_id).collection('embeddings')
                
                for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
                    doc_ref.add({
                        'document_id': blob.name.split('/')[-1],
                        'chunk_index': i,
                        'content': chunk,
                        'embedding': embedding,
                        'created_at': firebase_admin.firestore.SERVER_TIMESTAMP
                    })
                
                print(f"Successfully processed and stored embeddings for {blob.name}")

        print(f"Vector store initialization completed for user {user_id}")
        
    except Exception as e:
        print(f"Error in initialize_vectorstore: {str(e)}")
        print(f"Error type: {type(e)}")
        import traceback
        print(f"Traceback: {traceback.format_exc()}")
        raise

def get_retriever(user_id: str = None) -> Any:
    """Get a retriever for the specified user using Firebase."""
    if not user_id:
        print("Warning: No user_id provided, returning None")
        return None

    try:
        # Initialize Firestore
        db = firebase_admin.firestore.client()
        
        # Check if user has any embeddings
        embeddings_ref = db.collection('users').document(user_id).collection('embeddings')
        if not embeddings_ref.limit(1).get():
            print("No embeddings found for user, returning None")
            return None

        # Create a custom retriever that uses Firebase
        class FirebaseRetriever:
            def __init__(self, user_id: str):
                self.user_id = user_id
                self.db = firebase_admin.firestore.client()
                self.embedding = OpenAIEmbeddings(model="text-embedding-3-small")

            def invoke(self, query: str) -> List[Document]:
                # Convert query to embedding
                query_embedding = self.embedding.embed_query(query)
                
                # Get all embeddings for the user
                embeddings_ref = self.db.collection('users').document(self.user_id).collection('embeddings')
                embeddings = embeddings_ref.stream()
                
                # Calculate cosine similarity and get top matches
                results = []
                for doc in embeddings:
                    doc_data = doc.to_dict()
                    similarity = cosine_similarity(query_embedding, doc_data["embedding"])
                    results.append((similarity, doc_data["text"], doc_data.get("filename", "Unknown")))
                
                # Sort by similarity and get top 3
                results.sort(reverse=True)
                top_results = results[:3]
                
                # Print relevant documents with similarity scores
                print("\n📄 Relevant Documents:")
                for similarity, content, filename in top_results:
                    if similarity > 0.7:  # Only show highly relevant content
                        print(f"\nFrom: {filename}")
                        print(f"Relevance: {similarity:.2%}")
                        print("-" * 50)
                        print(content)
                        print("-" * 50)
                
                # Convert to Document objects
                return [Document(page_content=content) for _, content, _ in top_results]

        return FirebaseRetriever(user_id)
        
    except Exception as e:
        print(f"Error in get_retriever: {str(e)}")
        print(f"Error type: {type(e)}")
        import traceback
        print(f"Traceback: {traceback.format_exc()}")
        return None

def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    """Calculate cosine similarity between two vectors."""
    dot_product = np.dot(v1, v2)
    norm_v1 = np.linalg.norm(v1)
    norm_v2 = np.linalg.norm(v2)
    return dot_product / (norm_v1 * norm_v2)

def extract_text_from_pdf(pdf_content: bytes) -> str:
    """Extract text from PDF content."""
    import io
    from PyPDF2 import PdfReader
    
    try:
        pdf_file = io.BytesIO(pdf_content)
        reader = PdfReader(pdf_file)
        text = ""
        for page in reader.pages:
            text += page.extract_text() + "\n"
        return text
    except Exception as e:
        print(f"Error extracting text from PDF: {str(e)}")
        raise

# Define Tools for the Agent


def classify_email(email_text: str, history: str = "") -> str:
    """
    Classify an email as one of: Leave Request, Job Inquiry, Onboarding, or Escalate.
    Args:
        email_text: The content of the email to classify
        history: Optional previous conversation history
    Returns:
        The classification as a string: leave_request, job_inquiry, onboarding, or escalate
    """
    classification_prompt = ChatPromptTemplate.from_messages([
        ("system", "You are an HR assistant. Use both the current email and previous context to classify the email as one of the following: Leave Request, Job Inquiry, Onboarding. If you are not able to categorize it as above three categorize it as Escalate."),
        ("human", "Previous conversation (if any):\n{history}\n\nCurrent email:\n{email}")
    ])
    
    chain = classification_prompt | model | StrOutputParser()
    
    result = chain.invoke({
        "email": email_text,
        "history": history
    }).strip().lower().replace(" ", "_")
    
    return result


def retrieve_relevant_documents(query: str, user_id: str = None) -> List[str]:
    """
    Retrieve relevant documents from the knowledge base based on the query.
    Args:
        query: The query to search for in the knowledge base
        user_id: Optional user ID for user-specific document retrieval
    Returns:
        A list of relevant document contents
    """
    try:
        # Get retriever
        retriever = get_retriever(user_id)
        if retriever is None:
            print("No retriever available, skipping document retrieval")
            return []
            
        # Get documents
        docs = retriever.invoke(query)
        
        # Print retrieved documents
        print("\n📄 Retrieved Documents:")
        for i, doc in enumerate(docs, 1):
            print(f"\nDocument {i}:")
            print("-" * 50)
            print(doc.page_content)
            print("-" * 50)
        
        # Extract content from documents
        return [doc.page_content for doc in docs]
        
    except Exception as e:
        print(f"Error retrieving documents: {str(e)}")
        print(f"Error type: {type(e)}")
        import traceback
        print(f"Traceback: {traceback.format_exc()}")
        return []


def get_thread_history(user_id: str, thread_id: str) -> str:
    """
    Retrieve the email thread history for a given thread ID.
    Args:
        user_id: The ID of the user who owns this email
        thread_id: The ID of the thread to retrieve history for
    Returns:
        A string containing the thread history
    """
    from database import get_email_thread_history
    return get_email_thread_history(user_id, thread_id)


def get_thread_state(thread_id: str) -> Dict[str, str]:
    """
    Get the current state of an email thread.
    Args:
        thread_id: The ID of the thread to check
    Returns:
        A dictionary with doc_id and state
    """
    from database import get_latest_thread_state
    doc_id, state = get_latest_thread_state(thread_id)
    return {"doc_id": doc_id, "state": state}


def generate_response(email_text: str, category: str, context_docs: List[str], history: str = "", user_id: str = None) -> str:
    """
    Generate a response based on the email category, context documents, and history.
    Args:
        email_text: The content of the email to respond to
        category: The category of the email (leave_request, job_inquiry, onboarding, escalate)
        context_docs: List of relevant document contents to use as context
        history: Optional previous conversation history
        user_id: The ID of the user who owns this email
    Returns:
        Generated response text
    """
    # If no documents are available, proceed without them
    if not context_docs:
        print("No context documents available, generating response without them")
        context_docs = []
    
    def load_response_templates():
        if not user_id:
            return {}
            
        # Get templates from Firebase for this user
        templates_ref = db.collection('users').document(user_id).collection('templates')
        templates = {}
        
        # Get all template documents
        docs = templates_ref.stream()
        for doc in docs:
            templates[doc.id] = doc.to_dict()
            
        return templates

    response_templates = load_response_templates()

    # Extract placeholder values from email
    placeholders = extract_placeholders(email_text)

    # Handle Leave Request decision dynamically
    if category == "leave_request":
        try:
            requested_days = int(placeholders.get("number_of_days", "0"))
            if requested_days <= 3:
                approval_decision = "approved"
            else:
                approval_decision = "denied"
        except ValueError:
            approval_decision = "denied"
        placeholders["approved/denied"] = approval_decision

    # Add name field for backward compatibility
    placeholders["name"] = placeholders.get("employee_name", "Employee")

    # Use SafeDict to avoid KeyError
    safe_placeholders = defaultdict(str, placeholders)

    response_template_raw = response_templates.get(category, {})
    try:
        filled_template = {
            key: value.format(**safe_placeholders)
            for key, value in response_template_raw.items()
        }
    except KeyError as e:
        print(f"Warning: Missing placeholder {e} in template. Using default value.")
        filled_template = {
            key: value.format(**safe_placeholders)
            for key, value in response_template_raw.items()
        }

    # Modify the prompt to handle cases with no context documents
    context_text = "\n".join(context_docs) if context_docs else "No specific documentation available."
    
    rag_prompt = ChatPromptTemplate.from_messages([
    ("system", 
     "You are an HR executive writing professional, helpful email replies.\n\n"
     "You will be given a suggested response template as reference. You do not have to fill all the fields in he structured response template. DO NOT return your response as JSON or a dictionary.\n\n"
     "Instead, use the template as a guide and write a complete, polished email in natural, professional language.\n\n"
     "Incorporate any relevant information from the documentation, previous conversation history, and current email.\n"
     "The final output should sound human and fluid — as if written by a person, not a bot.\n"
     "Only generate the main email body. Do NOT include headers like 'Subject:' or 'From:'."
     "You may ask the candidate for more information if needed.\n\n"
    ),
    ("human", 
     "Documentation:\n{context}\n\n"
     "Previous conversation:\n{history}\n\n"
     "Current email:\n{email}\n\n"
     "Suggested Response Template (for guidance only):\n{response_template}"
    )])

    context = "\n\n".join(context_docs)
    chain = rag_prompt | model | StrOutputParser()
    
    result = chain.invoke({
        "context": context,
        "email": email_text,
        "history": history,
        "response_template": filled_template
    })

    # Combine dict sections into a full email response
    if isinstance(result, dict):
        result = "\n\n".join(value for value in result.values() if value)

    return result


def determine_next_state(current_state: str, email_text: str, response_text: str) -> str:
    """
    Determine the next state of the conversation based on the current state, email, and response.
    Args:
        current_state: Current state of the conversation (new, in_progress, awaiting_info, escalated, resolved)
        email_text: The content of the user's email
        response_text: The generated response
    Returns:
        The next state as a string
    """
    state_classification_prompt = ChatPromptTemplate.from_messages([
        ("system", 
         "You are an intelligent email assistant helping manage HR conversations. "
         "Based on the current state, the user's email, and your response, classify the next state of the conversation. "
         "Valid states: new, in_progress, awaiting_info, escalated, resolved.\n\n"
         "State transition logic:\n"
         "- 'new' → 'in_progress' if it is the first response.\n"
         "- Move to 'awaiting_info' if you asked the user for more info.\n"
         "- Move to 'escalated' if the case was forwarded to HR or higher authority.\n"
         "- Move to 'resolved' if the case is closed or you confirmed resolution.\n"
         "- Otherwise, keep the same state.\n"
         "Respond ONLY with the state name."
        ),
        ("human", 
         "Current state: {current_state}\n\n"
         "User email:\n{email_text}\n\n"
         "Your response:\n{response_text}")
    ])
    
    chain = state_classification_prompt | model | StrOutputParser()
    
    result = chain.invoke({
        "current_state": current_state,
        "email_text": email_text,
        "response_text": response_text
    })
    
    return result



def store_email_with_context(context: Dict[str, Any]) -> Dict[str, str]:
    """
    Wrapper tool to store email in database with correct context.
    """
    from database import store_email_result

    raw_email_data = context["email_data"]

    # Normalize keys
    email_data = {
        "from": raw_email_data.get("From", ""),
        "subject": raw_email_data.get("Subject", ""),
        "body": raw_email_data.get("Body", ""),
        "message_id": raw_email_data.get("Message-ID", ""),
        "in_reply_to": raw_email_data.get("In-Reply-To", ""),
        "references": raw_email_data.get("References", "")
    }

    response = context["response"]
    classification = context["classification"]
    state = context["state"]
    thread_id = context["thread_id"]

    doc_id, stored_thread_id = store_email_result(
        email_data, response, classification, state=state, thread_id=thread_id
    )
    return {"doc_id": doc_id, "thread_id": stored_thread_id}



def store_email_in_database(user_id: str, email_data: Dict[str, Any], response: str, classification: str, state: str, thread_id: str, reply_status:bool) -> Dict[str, str]:
    """
    Store email and response in the database.
    Args:
        user_id: The ID of the user who owns this email
        email_data: Dictionary containing email data
        response: Generated response text
        classification: Email classification
        state: Conversation state
        thread_id: Thread ID
    Returns:
        Dictionary with doc_id and thread_id
    """
    from database import store_email_result
    doc_id, stored_thread_id = store_email_result(
        user_id=user_id,
        mail=email_data,
        result=response,
        classification=classification,
        state=state,
        thread_id=thread_id,
        reply_status=reply_status
    )
    return {"doc_id": doc_id, "thread_id": stored_thread_id}


def update_thread_state(doc_id: str, new_state: str) -> bool:
    """
    Update the state of an email thread.
    Args:
        doc_id: Document ID to update
        new_state: New state to set
    Returns:
        True if successful, False otherwise
    """
    from database import update_email_state
    update_email_state(doc_id, new_state)
    return True


def store_escalation(email_data: Dict[str, Any]) -> bool:
    """
    Store an escalated email for admin review.
    Args:
        email_data: Dictionary containing email data
    Returns:
        True if successful, False otherwise
    """
    from database import store_admin_escalation
    store_admin_escalation(email_data)
    return True


def send_email_reply(to_email: str, subject: str, body: str, message_id: str, thread_id: str, user_id: str = None, signature: str = None) -> bool:
    """
    Send an email reply.
    Args:
        to_email: Recipient email address
        subject: Email subject
        body: Email body
        message_id: Original message ID to reply to
        thread_id: Thread ID
        user_id: The ID of the user whose email configuration to use
        signature: Optional custom signature to use
    Returns:
        True if successful, False otherwise
    """
    if not user_id:
        print("Error: user_id is required to send email reply")
        return False
        
    # Get user's email configuration
    user = User.get(user_id)
    if not user or not user.outgoing_email_config:
        print(f"Error: No outgoing email configuration found for user {user_id}")
        return False
        
    email_config = user.outgoing_email_config
    
    # Use custom signature if provided, otherwise use default
    if signature:
        signature_text = f"\n\n{signature}"
    else:
        signature_text = f"\n\nAI-AGENT\nHR Department\n{email_config['email']}"
    
    # Remove existing signature if present
    signature_patterns = [
        r"\n*AI-AGENT.*?(?=\n*$)",
        r"\n*Regards,.*?(?=\n*$)",
    ]
    cleaned_body = body
    for pattern in signature_patterns:
        cleaned_body = re.sub(pattern, '', cleaned_body, flags=re.DOTALL | re.IGNORECASE)
    
    final_body = cleaned_body.strip() + signature_text

    msg = EmailMessage()
    msg["Subject"] = "Re: " + subject if not subject.startswith("Re: ") else subject
    msg["From"] = email_config['email']
    msg["To"] = to_email
    msg["In-Reply-To"] = message_id
    msg["References"] = message_id
    msg.set_content(final_body)

    try:
        with smtplib.SMTP_SSL(email_config['server'], int(email_config.get('port', 465))) as smtp:
            smtp.login(email_config['email'], email_config['password'].decode())
            smtp.send_message(msg)
        return True
    except Exception as e:
        print(f"Error sending email: {e}")
        return False


def normalize_message_id(msg_id: str) -> str:
    """
    Normalize message IDs by removing angle brackets and whitespace.
    Args:
        msg_id: Message ID to normalize
    Returns:
        Normalized message ID
    """
    return msg_id.strip().replace("<", "").replace(">", "") if msg_id else ""


def determine_thread_id(user_id: str, message_data: Dict[str, Any]) -> Dict[str, str]:
    """
    Determine the correct thread_id for an email.
    Args:
        user_id: The ID of the user who owns this email
        message_data: Dictionary containing message_id, in_reply_to, and references
    Returns:
        Dictionary with message_id and thread_id
    """
    # SAFE GETTER
    def safe_get_and_normalize(field):
        value = message_data.get(field)
        if value is None:
            value = ""
        return normalize_message_id(value)

    message_id = safe_get_and_normalize("message_id")
    in_reply_to = safe_get_and_normalize("in_reply_to")
    references = safe_get_and_normalize("references")

    # Try to find the thread in our database
    if in_reply_to:
        ref_doc_query = db.collection('users').document(user_id).collection("email_history").where("message_id", "==", in_reply_to).limit(1).stream()
        for doc in ref_doc_query:
            thread_id = doc.to_dict().get("thread_id", in_reply_to)
            return {"message_id": message_id, "thread_id": thread_id}

    if references:
        ref_ids = [normalize_message_id(ref.strip()) for ref in references.split()]
        for ref_id in ref_ids:
            ref_doc_query = db.collection('users').document(user_id).collection("email_history").where("message_id", "==", ref_id).limit(1).stream()
            for doc in ref_doc_query:
                thread_id = doc.to_dict().get("thread_id", ref_id)
                return {"message_id": message_id, "thread_id": thread_id}

    # New thread if nothing found
    return {"message_id": message_id, "thread_id": message_id}


def determine_thread_id2(message_id,in_reply_to, references):
    """
    Determine the correct thread_id for an email.
    Args:
        message_data: Dictionary containing message_id, in_reply_to, and references
    Returns:
        Dictionary with message_id and thread_id
    """
    # Try to find the thread in our database
    if in_reply_to:
        ref_doc_query = db.collection("email_history").where("message_id", "==", in_reply_to).limit(1).stream()
        for doc in ref_doc_query:
            thread_id = doc.to_dict().get("thread_id", in_reply_to)
            return {"message_id": message_id, "thread_id": thread_id}

    if references:
        ref_ids = [normalize_message_id(ref.strip()) for ref in references.split()]
        for ref_id in ref_ids:
            ref_doc_query = db.collection("email_history").where("message_id", "==", ref_id).limit(1).stream()
            for doc in ref_doc_query:
                thread_id = doc.to_dict().get("thread_id", ref_id)
                return {"message_id": message_id, "thread_id": ref_id}

    # New thread if nothing found
    return {"message_id": message_id, "thread_id": message_id}


# Use a regular function rather than a tool for fetch_emails to avoid the tool invocation issue
def fetch_emails(email: str, password: bytes, server: str = "imap.gmail.com", start_date: str = None) -> List[Dict[str, Any]]:
    """
    Fetch unread emails from the inbox.
    Args:
        email: Email address to use for login
        password: Password or app password for the email account (as bytes)
        server: IMAP server address (defaults to Gmail)
        start_date: Date string in format 'DD-MMM-YYYY' (e.g., '01-Jan-2024'). If None, fetches all unread emails.
    Returns:
        List of dictionaries containing email data
    """
    import time
    start_time = time.time()
    print(f"🕒 Starting email fetch process at {time.strftime('%H:%M:%S')}")
    
    print(f"Attempting to connect to {server}...")
    connect_start = time.time()
    mail = imaplib.IMAP4_SSL(server)
    print(f"✅ Connected to server in {time.time() - connect_start:.2f} seconds")
    
    print(f"Attempting to login with email: {email}")
    login_start = time.time()
    try:
        mail.login(email, password.decode())  # Decode bytes to string for login
        print(f"✅ Login successful in {time.time() - login_start:.2f} seconds")
    except Exception as e:
        print(f"❌ Login failed: {str(e)}")
        raise
    
    print("Selecting inbox...")
    select_start = time.time()
    mail.select("inbox")
    print(f"✅ Inbox selected in {time.time() - select_start:.2f} seconds")
    
    # Construct search criteria
    search_criteria = '(UNSEEN)'
    if start_date:
        search_criteria = f'(UNSEEN SINCE "{start_date}")'
    
    print(f"Searching for unread messages {f'after {start_date}' if start_date else ''}...")
    search_start = time.time()
    status, messages = mail.search(None, search_criteria)
    if status != 'OK':
        print(f"❌ Search failed with status: {status}")
        return []
    
    message_count = len(messages[0].split())
    print(f"✅ Found {message_count} unread messages in {time.time() - search_start:.2f} seconds")
    if message_count > 100:
        print("⚠️ Warning: Large number of unread messages found. Consider using a more recent start_date.")
    
    email_data = []
    fetch_start = time.time()
    total_messages = message_count
    processed_messages = 0

    for num in messages[0].split():
        message_start = time.time()
        print(f"📧 Processing message {processed_messages + 1}/{total_messages}...")
        status, msg_data = mail.fetch(num, "(RFC822)")
        if status != 'OK':
            print(f"❌ Failed to fetch message {num}")
            continue
            
        for response_part in msg_data:
            if isinstance(response_part, tuple):
                try:
                    # response_part[1] is already bytes, no need to convert
                    msg = email_module.message_from_bytes(response_part[1])
                    sender = email_module.utils.parseaddr(msg["From"])[1]
                    subject = msg["Subject"]
                    message_id = msg["Message-ID"]
                    in_reply_to = msg["In-Reply-To"]
                    references = msg["References"]
                    body = ""

                    if msg.is_multipart():
                        for part in msg.walk():
                            if part.get_content_type() == "text/plain":
                                try:
                                    charset = part.get_content_charset() or 'utf-8'
                                    body = part.get_payload(decode=True).decode(charset, errors='replace')
                                except Exception as e:
                                    print(f"⚠️ Error decoding part: {e}")
                                    body = part.get_payload(decode=True).decode('latin-1', errors='replace')
                                break
                    else:
                        try:
                            charset = msg.get_content_charset() or 'utf-8'
                            body = msg.get_payload(decode=True).decode(charset, errors='replace')
                        except Exception as e:
                            print(f"⚠️ Error decoding message: {e}")
                            body = msg.get_payload(decode=True).decode('latin-1', errors='replace')

                    email_data.append({
                        "from": sender,
                        "subject": subject,
                        "body": body,
                        "message_id": message_id,
                        "in_reply_to": in_reply_to,
                        "references": references
                    })
                    processed_messages += 1
                    print(f"✅ Message {processed_messages}/{total_messages} processed in {time.time() - message_start:.2f} seconds")
                except Exception as e:
                    print(f"❌ Error processing message {num}: {str(e)}")
                    continue
                    
        print(f"Marking message {num} as read...")
        mail.store(num, '+FLAGS', '\\Seen')  # mark as read
        
    print(f"✅ Processed {processed_messages} messages in {time.time() - fetch_start:.2f} seconds")
    print("Logging out...")
    mail.logout()
    
    total_time = time.time() - start_time
    print(f"📊 Email fetch summary:")
    print(f"   - Total time: {total_time:.2f} seconds")
    print(f"   - Messages processed: {processed_messages}/{total_messages}")
    print(f"   - Average time per message: {total_time/processed_messages if processed_messages > 0 else 0:.2f} seconds")
    
    return email_data