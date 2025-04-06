from flask import Flask, request
import base64, json
from googleapiclient.discovery import build
import pickle
import os
from hr_ai_agent import handle_incoming_email
from database import is_duplicate_message
HR_EMAIL_USER = os.getenv("HR_EMAIL_USER")
# HR_EMAIL_PASS = os.getenv("HR_EMAIL_PASS")
app = Flask(__name__)

# Load saved credentials
with open("token.json", "rb") as token:
    creds = pickle.load(token)

# Build Gmail API client
gmail = build("gmail", "v1", credentials=creds)
HISTORY_FILE = "latest_history.json"

def load_latest_history_id():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r") as f:
            try:
                data = json.load(f)
                return data.get("history_id")
            except json.JSONDecodeError:
                print("⚠️ latest_history.json is empty or malformed. Skipping.")
                return None
    return None

def save_latest_history_id(history_id):
    with open(HISTORY_FILE, "w") as f:
        json.dump({"history_id": history_id}, f)
        print(f"✅ Saved latest history ID: {history_id}")

def process_email(message_id):
    msg = gmail.users().messages().get(userId="me", id=message_id, format="full").execute()

    headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}
    sender = headers.get("From", "")
    # Check if the email was sent by your own HR agent address
    if sender.lower() == HR_EMAIL_USER.lower():
        print(f"🔁 Ignoring email sent by myself: {sender}")
        return
    subject = headers.get("Subject", "")
    message_id_header = headers.get("Message-ID", "")
    in_reply_to = headers.get("In-Reply-To", "")
    references = headers.get("References", "")
    body = ""

    # 🔒 Check for duplicates
    if is_duplicate_message(message_id_header):
        print(f"🔁 Duplicate message ignored: {message_id_header}")
        return

    # Extract the plain text body
    payload = msg.get("payload", {})
    body = extract_email_body(payload)

    email_data = {
        "from": sender,
        "subject": subject,
        "body": body,
        "message_id": message_id_header,
        "in_reply_to": in_reply_to,
        "references": references
    }

    handle_incoming_email(email_data)

def extract_email_body(payload):
    """Extracts the plain text body from the email payload."""
    if "parts" in payload:
        for part in payload["parts"]:
            mime_type = part.get("mimeType", "")
            if mime_type == "text/plain":
                data = part["body"].get("data")
                if data:
                    return base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
            elif mime_type == "multipart/alternative":
                # Nested multiparts (e.g., plain + HTML)
                return extract_email_body(part)
    else:
        # Single-part message
        body_data = payload.get("body", {}).get("data")
        if body_data:
            return base64.urlsafe_b64decode(body_data).decode("utf-8", errors="ignore")
    return "[No plain text content found]"

@app.route("/pubsub-handler", methods=["POST"])
def handle_pubsub():
    envelope = request.get_json()
    if not envelope or "message" not in envelope:
        return "Bad Request", 400

    # Decode base64
    pubsub_message = envelope["message"]
    data = base64.b64decode(pubsub_message["data"]).decode("utf-8")
    print("🔔 Received Gmail notification:", data)

    data_obj = json.loads(data)
    new_history_id = data_obj.get("historyId")

    if new_history_id:
        previous_history_id = load_latest_history_id()

        if previous_history_id is not None:
            fetch_emails_since(previous_history_id)
        else:
            print("⚠️ No previous history ID found. Skipping fetch.")

        # ✅ MUST save the new one AFTER processing is done
        save_latest_history_id(new_history_id)

    return "OK", 200


def fetch_emails_since(history_id):
    print(f"📨 Fetching emails since history ID: {history_id}")

    try:
        history_response = gmail.users().history().list(
            userId="me",
            startHistoryId=history_id,
            historyTypes=["messageAdded"]
        ).execute()

        history_items = history_response.get("history", [])
        # message_count = 0

        for history in history_items:
            messages_added = history.get("messagesAdded", [])
            for msg_added in messages_added:
                message = msg_added.get("message", {})
                message_id = message.get("id")

                if message_id:
                    process_email(message_id)

        # print(f"📬 Processed {message_count} new inbox emails")

    except Exception as e:
        print(f"❌ Error fetching email history: {e}")

if __name__ == "__main__":
    app.run(host='0.0.0.0',port=8080)
