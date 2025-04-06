import os
import imaplib
import smtplib
import email
import re
from firebase_config import db as firestore_db
from email.message import EmailMessage
from dotenv import load_dotenv
from langchain.text_splitter import CharacterTextSplitter
from langchain_community.document_loaders import TextLoader
from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain.prompts import ChatPromptTemplate
from langchain.schema.output_parser import StrOutputParser
from langchain.schema.runnable import RunnableBranch, RunnableLambda
from database import store_email_result, get_latest_thread_state, store_admin_escalation, get_email_thread_history, update_email_state
from firebase_admin import firestore
from langchain_core.runnables import Runnable
# from pub_sub_handler import 

load_dotenv()
EMAIL_USER = os.getenv("EMAIL_ADDRESS")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
model = ChatOpenAI(model="gpt-3.5-turbo")
# documents_dir = "/Users/krithi/Desktop/EBT/documents"
# db_dir = "/Users/krithi/Desktop/EBT/db"
# persistent_directory = os.path.join(db_dir, "chroma_db_hr_docs")

db = Chroma(persist_directory="/documents",
            embedding_function=OpenAIEmbeddings(model="text-embedding-3-small"))
retriever = db.as_retriever(search_type="similarity", search_kwargs={"k": 3})

classification_prompt = ChatPromptTemplate.from_messages([
    ("system", "You are an HR assistant. Use both the current email and previous context to classify the email as one of the following: Leave Policy, Job Inquiry, Onboarding, Remote Work Policy, Data Privacy Policy. If you are not able to categorize it as above three categorize it as Escalate."),
    ("human", "Previous conversation (if any):\n{history}\n\nCurrent email:\n{email}")
])
classification_chain = classification_prompt | model | StrOutputParser()

rag_prompt = ChatPromptTemplate.from_messages([
    ("system", "You are an HR executive writing professional, helpful email replies. Only generate the response body – do not include a subject line or headers. Consider ALL previous conversation history when responding."),
    ("human", "Refer to the following documentation and email content to write a professional reply.\n\nDocumentation:\n{context}\n\nPrevious conversation:\n{history}\n\nCurrent email:\n{email}")
])
def get_rag_chain():
    return RunnableLambda(lambda input: (
        rag_prompt.invoke({
            "context": "\n\n".join([doc.page_content for doc in retriever.invoke(input["email"])]),
            "email": input["email"],
            "history": input["history"]
        })
    )) | model | StrOutputParser()

escalation_prompt = ChatPromptTemplate.from_messages([
    ("system", "You are an HR assistant."),
    ("human", "This email could not be confidently classified. Flag it for admin review:\n\n{email}")
])

full_chain = (
    RunnableLambda(lambda input: {
        "email": input["email"],
        "history": input["history"],
        "category": classification_chain.invoke({
            "email": input["email"],
            "history": input["history"]
        }).strip().lower().replace(" ", "_")
    })
    | RunnableLambda(lambda input: input)
    | RunnableBranch(
        (lambda x: x["category"] == "leave_policy", get_rag_chain()),
        (lambda x: x["category"] == "job_inquiry", get_rag_chain()),
        (lambda x: x["category"] == "onboarding", get_rag_chain()),
        (lambda x: x["category"] == "data_privacy_policy", get_rag_chain()),
        (lambda x: x["category"] == "remote_work_policy", get_rag_chain()),
        escalation_prompt | model | StrOutputParser()
    )
)

def normalize_id(msg_id: str) -> str:
    #Normalize message IDs by removing angle brackets and whitespace
    return msg_id.strip().replace("<", "").replace(">", "") if msg_id else ""

def fetch_unread_emails():
    #Fetch unread emails from Gmail inbox
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

def remove_existing_signature(body):
    #Remove AI agent signature from email body."""
    signature_patterns = [
        r"\n*AI-AGENT.*?(?=\n*$)",
        r"\n*Regards,.*?(?=\n*$)",
    ]
    for pattern in signature_patterns:
        body = re.sub(pattern, '', body, flags=re.DOTALL | re.IGNORECASE)
    return body

def send_reply(to_email, subject, body, original_msg_id, thread_id=None):
    #Send email reply with proper threading."""
    signature = "\n\nAI-AGENT\nHR Department\nhairagent88@gmail.com"
    cleaned_body = remove_existing_signature(body)
    final_body = cleaned_body.strip() + signature

    msg = EmailMessage()
    msg["Subject"] = "Re: " + subject
    msg["From"] = EMAIL_USER
    msg["To"] = to_email
    msg["In-Reply-To"] = original_msg_id
    msg["References"] = original_msg_id
    msg.set_content(final_body)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(EMAIL_USER, EMAIL_PASSWORD)
        smtp.send_message(msg)

def process_email_threading(mail):
    """
    Determine the correct thread_id for an email.
    If it's a reply, find the original thread.
    If it's a new thread, create a new thread_id.
    """
    message_id = normalize_id(mail["message_id"])
    
    # Check for In-Reply-To or References headers to identify thread
    in_reply_to = normalize_id(mail.get("in_reply_to") or "")
    references = normalize_id(mail.get("references") or "")
    
    # Try to find the thread in our database
    if in_reply_to:
        ref_doc_query = firestore_db.collection("email_history").where("message_id", "==", in_reply_to).limit(1).stream()
        for doc in ref_doc_query:
            thread_id = doc.to_dict().get("thread_id", in_reply_to)
            return message_id, thread_id
    
    # If not found by in_reply_to, try references
    if references:
        # References might contain multiple message IDs
        ref_ids = [normalize_id(ref.strip()) for ref in references.split()]
        for ref_id in ref_ids:
            ref_doc_query = firestore_db.collection("email_history").where("message_id", "==", ref_id).limit(1).stream()
            for doc in ref_doc_query:
                thread_id = doc.to_dict().get("thread_id", ref_id)
                return message_id, thread_id
    
    # If no thread is found or this is the first email, create a new thread
    return message_id, message_id

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

# LLM chain for classification
state_classification_chain: Runnable = state_classification_prompt | model | StrOutputParser()

# Function that wraps the chain
def infer_next_state(current_state: str, email_text: str, response_text: str) -> str:
    #Determine the next conversation state based on email content and response."""
    return state_classification_chain.invoke({
        "current_state": current_state,
        "email_text": email_text,
        "response_text": response_text
    })

def handle_incoming_email(mail):
    email_text = mail["body"]

    # Threading
    message_id, thread_id = process_email_threading(mail)

    # Get previous state & history
    latest_doc_id, prev_state = get_latest_thread_state(thread_id)
    history_text = get_email_thread_history(thread_id)

    # Classification
    classification = classification_chain.invoke({
        "email": email_text,
        "history": history_text
    }).strip().lower().replace(" ", "_")

    print('*'*40)
    print(classification)
    print('*'*40)
    
    # Escalation or response
    if classification == "escalate":
        store_admin_escalation(mail)
        response_text = "Your request has been escalated to our HR team. They will get back to you shortly."
        new_state = "escalated"
    else:
        response = full_chain.invoke({"email": email_text, "history": history_text})
        response_text = response if isinstance(response, str) else response.get("output", "")
        new_state = infer_next_state(prev_state, email_text, response_text)

    # Store result and send reply
    doc_id, stored_thread_id = store_email_result(mail, response_text, classification, state=new_state, thread_id=thread_id)
    send_reply(mail["from"], mail["subject"], response_text, mail["message_id"], thread_id)

    # Optional state update
    if latest_doc_id and new_state == "in_progress" and prev_state == "awaiting_info":
        update_email_state(latest_doc_id, "in_progress")

    print(f"✅ Replied to: {mail['from']} | Classification: {classification} | State: {new_state}")


if __name__ == "__main__":
    print("Checking inbox...")
    unread_emails = fetch_unread_emails()

    if not unread_emails:
        print("No new emails.")
    else:
        for mail in unread_emails:
            print(f"Processing email from: {mail['from']}")

            email_text = mail["body"]
            
            # Determine the correct thread_id for this email
            message_id, thread_id = process_email_threading(mail)

            # Get previous thread state from Firestore
            latest_doc_id, prev_state = get_latest_thread_state(thread_id)

            # Fetch thread history for context
            history_text = get_email_thread_history(thread_id)

            # print(history_text)
            
            # Classify email
            classification = classification_chain.invoke({
                "email": email_text,
                "history": history_text
            }).strip().lower().replace(" ", "_")

            # print(classification)
            
            # Generate response or escalate
            if classification == "escalate":
                store_admin_escalation(mail)
                response_text = "Your request has been escalated to our HR team. They will get back to you shortly."
                new_state = "escalated"
            else:
                response = full_chain.invoke({"email": email_text, "history": history_text})
                response_text = response if isinstance(response, str) else response.get("output", "")
                new_state = infer_next_state(prev_state, email_text, response_text)

            # Store result and send reply
            doc_id, stored_thread_id = store_email_result(mail, response_text, classification, state=new_state, thread_id=thread_id)
            send_reply(mail["from"], mail["subject"], response_text, mail["message_id"], thread_id)

            # Update previous thread state if needed
            if latest_doc_id and new_state == "in_progress" and prev_state == "awaiting_info":
                update_email_state(latest_doc_id, "in_progress")

            print(f"Replied to: {mail['from']} | Classification: {classification} | State: {new_state}")