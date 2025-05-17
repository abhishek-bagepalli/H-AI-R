import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from hr_tools import *
from database import *

def main():
    # Load environment variables
    load_dotenv()
    EMAIL_USER = os.getenv("EMAIL_USER")
    EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")

    # Directory setup
    documents_dir = "documents/"
    db_dir = "db/"
    persistent_directory = os.path.join(db_dir, "chroma_db_hr_docs")

    # Initialize the LLM
    model = ChatOpenAI(model="gpt-3.5-turbo")

    try:
        emails = fetch_emails()
        print(f"\n📬 {len(emails)} unread emails fetched.")

        for i, mail in enumerate(emails, 1):
            print(f"\n{'=' * 40}")
            print(f"✉️  Email #{i}")
            print(f"From        : {mail['from']}")
            print(f"Subject     : {mail['subject']}")
            print(f"Message-ID  : {mail['message_id']}")
            print(f"Body        : {mail['body'][:100]}...")
            print(f"In-Reply-To : {mail.get('in_reply_to', 'N/A')}")
            print(f"References  : {mail.get('references', 'N/A')}")

            # Step 1: Determine thread
            thread_info = determine_thread_id2(
                message_id=mail.get("message_id"),
                in_reply_to=mail.get("in_reply_to"),
                references=mail.get("references")
            )
            print(f"\n🧵 Thread mapping → {thread_info}")

            # Step 2: Classify email
            category = classify_email(mail["body"])
            print(f"\n🏷️  Classification → {category}")

            # Step 3: Retrieve relevant documents
            relevant_docs = retrieve_relevant_documents(mail["body"])[0]
            print(f"\n📚 Relevant documents →\n{relevant_docs}")

            # Step 4: Get thread history
            history = get_thread_history(thread_info["thread_id"])
            print(f"\n📜 Thread history →\n{history}")

            # Step 5: Generate response
            response = generate_response(
                email_text=mail["body"],
                category=category,
                context_docs=[""],
                history=history
            )
            print(f"\n💬 Generated response →\n{response}")

            # Step 6: Get current state
            current_state = get_latest_thread_state(thread_info["thread_id"])[1]
            print(f"\n🗂️  Current state → {current_state}")

            # Step 7: Determine next state
            next_state = determine_next_state(current_state, mail["body"], response)
            print(f"\n➡️  Next state → {next_state}")

            # Step 8: Send email reply
            reply_status = send_email_reply(
                to_email=mail["from"],
                subject=mail["subject"],
                body=response,
                message_id=mail["message_id"],
                thread_id=thread_info["thread_id"]
            )
            if reply_status:
                print(f"\n✅ Email sent to {mail['from']}")
            else:
                print(f"\n❌ Failed to send email to {mail['from']}")

            # Step 9: Store email result
            result = store_email_in_database(
                email_data=mail,
                response=response,
                classification=category,
                state=next_state,
                thread_id=thread_info["thread_id"],
                reply_status=reply_status
            )
            print(f"\n📦 Email stored → {result}")

            print(f"{'=' * 40}")

    except Exception as e:
        print(f"\n❌ Error during execution: {e}")
