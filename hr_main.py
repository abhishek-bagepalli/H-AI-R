import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from hr_tools import *
from database import *
import imaplib
import email
from typing import Dict, Any
from auth import User
from encryption import decrypt_data

def process_email(user_id: str, mail: Dict[str, Any]) -> None:
    """
    Process a single email.
    Args:
        user_id: The ID of the user who owns this email
        mail: Dictionary containing email data
    """
    print(f"Processing email from: {mail['from']}")
    
    try:
        email_text = mail["body"]
        
        # Determine the correct thread_id for this email
        thread_info = determine_thread_id(user_id, mail)
        message_id = thread_info["message_id"]
        thread_id = thread_info["thread_id"]
        
        # Get previous thread state
        latest_doc_id, prev_state = get_latest_thread_state(user_id, thread_id)
        
        # Fetch thread history for context
        history_text = get_thread_history(user_id, thread_id)
        
        # Classify email
        classification = classify_email(email_text, history_text)
        
        # Generate response or escalate
        if classification == "escalate":
            store_admin_escalation(user_id, mail)
            response_text = "Your request has been escalated to our HR team. They will get back to you shortly."
            new_state = "escalated"
        else:
            # Get relevant documents for context
            context_docs = retrieve_relevant_documents(email_text)
            
            # Generate response
            response_text = generate_response(
                email_text=email_text,
                category=classification,
                context_docs=context_docs,
                history=history_text,
                user_id=user_id
            )
            new_state = determine_next_state(prev_state, email_text, response_text)
        
        # Store result and send reply
        doc_id, stored_thread_id = store_email_in_database(
            user_id=user_id,
            email_data=mail,
            response=response_text,
            classification=classification,
            state=new_state,
            thread_id=thread_id,
            reply_status=True
        )
        
        # Send reply
        send_email_reply(
            to_email=mail["from"],
            subject=mail["subject"],
            body=response_text,
            message_id=message_id,
            thread_id=thread_id,
            user_id=user_id
        )
        
        # Update previous thread state if needed
        if latest_doc_id and new_state == "in_progress" and prev_state == "awaiting_info":
            update_email_state(user_id, latest_doc_id, "in_progress")
            
    finally:
        # Clean up resources
        if 'context_docs' in locals():
            del context_docs
        if 'history_text' in locals():
            del history_text
        if 'email_text' in locals():
            del email_text
        if 'response_text' in locals():
            del response_text
        import gc
        gc.collect()  # Force garbage collection

def main():
    """
    Main function to process unread emails.
    """
    print("Checking inbox...")
    
    # Get all users with email configurations
    users_ref = db.collection('users').stream()
    
    # Use a start date of 1 month ago
    from datetime import datetime, timedelta
    start_date = (datetime.now() - timedelta(days=2)).strftime('%d-%b-%Y')
    
    for user_doc in users_ref:
        user_data = user_doc.to_dict()
        user_id = user_doc.id

        print(f"\nProcessing user: {user_id}")
        
        # Get user object which has decrypted configurations
        user = User.get(user_id)
        if not user:
            print(f"No user found for ID: {user_id}")
            continue
        if not user.incoming_email_config:
            print(f"No incoming email configuration for user: {user_id}")
            continue
            
        # Use the decrypted configuration from the User object
        email_config = user.incoming_email_config
        print(f"Email config for {user_id}:")
        print(f"- Email: {email_config.get('email')}")
        print(f"- Server: {email_config.get('server')}")
        print(f"- Port: {email_config.get('port')}")
        print(f"- SSL: {email_config.get('use_ssl')}")
        
        try:
            # Fetch emails using user's configuration
            print(f"\nAttempting to fetch emails for {email_config.get('email')}...")
            emails = fetch_emails(
                email=email_config['email'],
                password=email_config['password'],  # Already decrypted by User.get()
                server=email_config['server'],
                start_date=start_date
            )
            
            if emails:
                print(f"📬 {len(emails)} unread emails fetched for user {user_id}.")
                
                for email_data in emails:
                    # Process the email
                    process_email(user_id, email_data)
            else:
                print(f"No unread emails found for user {user_id}")
            
        except Exception as e:
            print(f"Error processing emails for user {user_id}: {e}")
            continue

if __name__ == "__main__":
    main() 