import os
import imaplib
import smtplib
import email
import re
from email.message import EmailMessage
from typing import Dict, List, Any, Optional
from firebase_config import db as firestore_db
from dotenv import load_dotenv
from langchain.text_splitter import CharacterTextSplitter
from langchain_community.document_loaders import TextLoader, DirectoryLoader
from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain.prompts import ChatPromptTemplate
from langchain.schema.output_parser import StrOutputParser
from langchain.tools import tool
from collections import defaultdict
# from response_templates import response_templates
from extract_placeholders import extract_placeholders
from langchain_core.tools import tool
import json

load_dotenv()

# Environment and configuration setup
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")

# Directory setup for document storage and retrieval
documents_dir = "documents/"
db_dir = "db/"
persistent_directory = os.path.join(db_dir, "chroma_db_hr_docs")

# Initialize the LLM
model = ChatOpenAI(model="gpt-4o")

# Vector store initialization
def initialize_vectorstore():
    """Initialize or rebuild the vector store with document embeddings."""
    loader = DirectoryLoader(
        documents_dir, 
        glob="**/*.txt", 
        loader_cls=TextLoader
    )
    documents = loader.load()

    # Split and embed
    text_splitter = CharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
    texts = text_splitter.split_documents(documents)

    embedding = OpenAIEmbeddings(model="text-embedding-3-small")

    # Create and persist vectorstore
    vectorstore = Chroma.from_documents(
        documents=texts,
        embedding=embedding,
        persist_directory=persistent_directory
    )

    print("Vectorstore initialized successfully.")
    return vectorstore

# Initialize vector database
vectorstore = initialize_vectorstore()
retriever = vectorstore.as_retriever(search_type="similarity", search_kwargs={"k": 3})

# Define Tools for the Agent

@tool
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

@tool
def retrieve_relevant_documents(query: str) -> List[str]:
    """
    Retrieve relevant documents from the knowledge base based on the query.
    Args:
        query: The query to search for in the knowledge base
    Returns:
        A list of relevant document contents
    """
    docs = retriever.invoke(query)
    return [doc.page_content for doc in docs]

@tool
def get_thread_history(thread_id: str) -> str:
    """
    Retrieve the email thread history for a given thread ID.
    Args:
        thread_id: The ID of the thread to retrieve history for
    Returns:
        A string containing the thread history
    """
    from database import get_email_thread_history
    return get_email_thread_history(thread_id)

@tool
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

@tool
def generate_response(email_text: str, category: str, context_docs: List[str], history: str = "") -> str:
    """
    Generate a response based on the email category, context documents, and history.
    Args:
        email_text: The content of the email to respond to
        category: The category of the email (leave_request, job_inquiry, onboarding, escalate)
        context_docs: List of relevant document contents to use as context
        history: Optional previous conversation history
    Returns:
        Generated response text
    """
    def load_response_templates():
        if os.path.exists('response_templates.json'):
            with open('response_templates.json', 'r') as f:
                return json.load(f)
        return {}
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

    # Use SafeDict to avoid KeyError
    safe_placeholders = defaultdict(str, placeholders)

    response_template_raw = response_templates.get(category, {})
    filled_template = {
        key: value.format(**safe_placeholders)
        for key, value in response_template_raw.items()
    }

    rag_prompt = ChatPromptTemplate.from_messages([
        ("system", 
         "You are an HR executive writing professional, helpful email replies.\n\n"
         "Use the following JSON structure to frame your reply:\n\n{response_template}\n\n"
         "But the response should be as human like as possible even for thread replies."
         "Fill in the placeholders with information from the email and previous conversation.\n"
         "Only generate the main email body, no subject line or headers."
        ),
        ("human", 
         "Documentation:\n{context}\n\n"
         "Previous conversation:\n{history}\n\n"
         "Current email:\n{email}")
    ])

    context = "\n\n".join(context_docs)
    chain = rag_prompt | model | StrOutputParser()
    
    result = chain.invoke({
        "context": context,
        "email": email_text,
        "history": history,
        "response_template": filled_template
    })
    
    return result

@tool
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


@tool
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


@tool
def store_email_in_database(email_data: Dict[str, Any], response: str, classification: str, state: str, thread_id: str) -> Dict[str, str]:
    """
    Store email and response in the database.
    Args:
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
        email_data, response, classification, state=state, thread_id=thread_id
    )
    return {"doc_id": doc_id, "thread_id": stored_thread_id}

@tool
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

@tool
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

@tool
def send_email_reply(to_email: str, subject: str, body: str, message_id: str, thread_id: str) -> bool:
    """
    Send an email reply.
    Args:
        to_email: Recipient email address
        subject: Email subject
        body: Email body
        message_id: Original message ID to reply to
        thread_id: Thread ID
    Returns:
        True if successful, False otherwise
    """
    signature = "\n\nAI-AGENT\nHR Department\nhairagent88@gmail.com"
    
    # Remove existing signature if present
    signature_patterns = [
        r"\n*AI-AGENT.*?(?=\n*$)",
        r"\n*Regards,.*?(?=\n*$)",
    ]
    cleaned_body = body
    for pattern in signature_patterns:
        cleaned_body = re.sub(pattern, '', cleaned_body, flags=re.DOTALL | re.IGNORECASE)
    
    final_body = cleaned_body.strip() + signature

    msg = EmailMessage()
    msg["Subject"] = "Re: " + subject if not subject.startswith("Re: ") else subject
    msg["From"] = EMAIL_USER
    msg["To"] = to_email
    msg["In-Reply-To"] = message_id
    msg["References"] = message_id
    msg.set_content(final_body)

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(EMAIL_USER, EMAIL_PASSWORD)
            smtp.send_message(msg)
        return True
    except Exception as e:
        print(f"Error sending email: {e}")
        return False

@tool
def normalize_message_id(msg_id: str) -> str:
    """
    Normalize message IDs by removing angle brackets and whitespace.
    Args:
        msg_id: Message ID to normalize
    Returns:
        Normalized message ID
    """
    return msg_id.strip().replace("<", "").replace(">", "") if msg_id else ""

@tool
def determine_thread_id(message_data: Dict[str, Any]) -> Dict[str, str]:
    """
    Determine the correct thread_id for an email.
    Args:
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
        ref_doc_query = firestore_db.collection("email_history").where("message_id", "==", in_reply_to).limit(1).stream()
        for doc in ref_doc_query:
            thread_id = doc.to_dict().get("thread_id", in_reply_to)
            return {"message_id": message_id, "thread_id": thread_id}

    if references:
        ref_ids = [normalize_message_id(ref.strip()) for ref in references.split()]
        for ref_id in ref_ids:
            ref_doc_query = firestore_db.collection("email_history").where("message_id", "==", ref_id).limit(1).stream()
            for doc in ref_doc_query:
                thread_id = doc.to_dict().get("thread_id", ref_id)
                return {"message_id": message_id, "thread_id": thread_id}

    # New thread if nothing found
    return {"message_id": message_id, "thread_id": message_id}


# Use a regular function rather than a tool for fetch_emails to avoid the tool invocation issue
def fetch_emails() -> List[Dict[str, Any]]:
    """
    Fetch unread emails from the inbox.
    Returns:
        List of dictionaries containing email data
    """
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(EMAIL_USER, EMAIL_PASSWORD)
    mail.select("inbox")
    status, messages = mail.search(None, '(UNSEEN)')
    email_data = []

    for num in messages[0].split():
        status, msg_data = mail.fetch(num, "(RFC822)")
        for response_part in msg_data:
            if isinstance(response_part, tuple):
                msg = email.message_from_bytes(response_part[1])
                sender = email.utils.parseaddr(msg["From"])[1]
                subject = msg["Subject"]
                message_id = msg["Message-ID"]
                in_reply_to = msg["In-Reply-To"]
                references = msg["References"]
                body = ""

                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == "text/plain":
                            body = part.get_payload(decode=True).decode()
                            break
                else:
                    body = msg.get_payload(decode=True).decode()

                email_data.append({
                    "from": sender,
                    "subject": subject,
                    "body": body,
                    "message_id": message_id,
                    "in_reply_to": in_reply_to,
                    "references": references
                })
        mail.store(num, '+FLAGS', '\\Seen')  # mark as read
    mail.logout()
    return email_data