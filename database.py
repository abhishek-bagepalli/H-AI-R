from firebase_config import db
from firebase_admin import firestore
from dotenv import load_dotenv
import smtplib
from email.message import EmailMessage
import os

load_dotenv()
HR_ADMIN_EMAIL = "hairagent88@gmail.com"
HR_EMAIL_USER = os.getenv("HR_EMAIL_USER")
HR_EMAIL_PASSWORD = os.getenv("HR_EMAIL_PASSWORD")

def normalize_id(msg_id: str) -> str:
    # Normalize message IDs by removing angle brackets and whitespace.
    return msg_id.strip().replace("<", "").replace(">", "") if msg_id else ""

def get_email_thread_history(thread_id: str):
    # Get the entire conversation history for a thread.
    thread_id = normalize_id(thread_id)
    docs = (
        db.collection("email_history")
        .where("thread_id", "==", thread_id)
        .order_by("timestamp", direction=firestore.Query.ASCENDING)
        .stream()
    )
    history = []
    for doc in docs:
        data = doc.to_dict()
        history.append(f"User: {data['body']}\nAgent: {data.get('response', '')}")
    return "\n\n".join(history)

def store_email_result(mail, result, classification, state="new", thread_id=None):
    # Store email and response in Firestore with proper threading.
    message_id = normalize_id(mail["message_id"])
    thread_id = normalize_id(thread_id or message_id)
    
    email_data = {
        "sender": mail["from"],
        "subject": mail["subject"],
        "body": mail["body"],
        "response": result,
        "classification": classification,
        "status": state,
        "timestamp": firestore.SERVER_TIMESTAMP,
        "message_id": message_id,
        "thread_id": thread_id,
        "in_reply_to": normalize_id(mail.get("in_reply_to") or ""),
        "references": normalize_id(mail.get("references") or "")
    }
    doc_ref = db.collection("email_history").add(email_data)
    return doc_ref[1].id, email_data["thread_id"]

def get_latest_thread_state(thread_id: str):
    # Get the most recent state of a thread.
    thread_id = normalize_id(thread_id)
    docs = (
        db.collection("email_history")
        .where("thread_id", "==", thread_id)
        .order_by("timestamp", direction=firestore.Query.DESCENDING)
        .limit(1)
        .stream()
    )
    for doc in docs:
        return doc.id, doc.to_dict().get("status", "new")
    return None, "new"

def update_email_state(doc_id: str, new_state: str):
    # Update the state of an email in the database
    db.collection("email_history").document(doc_id).update({"status": new_state})

def store_admin_feedback(email_doc_id: str, feedback: str):
    #Store feedback from admin about how an email was handled
    feedback_data = {
        "email_id": email_doc_id,
        "feedback": feedback,
        "timestamp": firestore.SERVER_TIMESTAMP
    }
    db.collection("admin_feedback").add(feedback_data)

def store_admin_escalation(mail):
    # Store and notify about emails that need human attention
    escalation_data = {
        "sender": mail["from"],
        "subject": mail["subject"],
        "body": mail["body"],
        "status": "pending",
        "timestamp": firestore.SERVER_TIMESTAMP,
        "message_id": normalize_id(mail["message_id"]),
        "in_reply_to": normalize_id(mail.get("in_reply_to") or ""),
        "references": normalize_id(mail.get("references") or "")
    }
    doc_ref = db.collection("admin_escalations").add(escalation_data)

    # Notify HR Admin via email
    notify_hr_admin(mail)

    return doc_ref[1].id

def notify_hr_admin(mail):
    # Send notification email to HR admin about escalated issues
    msg = EmailMessage()
    msg["Subject"] = f"[Escalation Alert] New Email from {mail['from']}"
    msg["From"] = HR_EMAIL_USER
    msg["To"] = HR_ADMIN_EMAIL
    msg.set_content(
        f"New escalated email received:\n\n"
        f"From: {mail['from']}\n"
        f"Subject: {mail['subject']}\n\n"
        f"Body:\n{mail['body']}"
    )

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(HR_EMAIL_USER, HR_EMAIL_PASSWORD)
        smtp.send_message(msg)

def is_duplicate_message(message_id: str) -> bool:
    if not message_id:
        return False  # defensive check

    query = db.collection("email_history") \
        .where("message_id", "==", message_id.strip()) \
        .limit(1) \
        .stream()

    return any(True for _ in query)
