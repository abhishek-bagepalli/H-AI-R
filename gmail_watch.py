from googleapiclient.discovery import build
import pickle

# Load Gmail API credentials
with open("token.json", "rb") as token:
    creds = pickle.load(token)

service = build("gmail", "v1", credentials=creds)

# Replace with your actual Pub/Sub topic name
topic_name = "projects/hair-agent88-455618/topics/gmail-notifications"

watch_request = {
    "labelIds": ["INBOX"],
    "topicName": topic_name
}

response = service.users().watch(userId='me', body=watch_request).execute()
print("🔔 Gmail watch set successfully!")
print(response)
