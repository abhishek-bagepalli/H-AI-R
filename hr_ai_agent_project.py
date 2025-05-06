import json
import os
from typing import Dict, Any
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain.prompts import ChatPromptTemplate
from langchain.agents import AgentExecutor, create_openai_tools_agent
from langchain_core.utils.function_calling import convert_to_openai_tool  # Updated import

# Import all tools from the tools file
from hr_tools import (
    classify_email, retrieve_relevant_documents, get_thread_history,
    get_thread_state, generate_response, determine_next_state,
    store_email_with_context, update_thread_state, store_escalation,
    send_email_reply, normalize_message_id, determine_thread_id,
    fetch_emails  # Import as a regular function
)

load_dotenv()

# Initialize the LLM
model = ChatOpenAI(model="gpt-4o")

# Collect all tools - remove fetch_emails as it's not a tool now
tools = [
    classify_email,
    retrieve_relevant_documents,
    get_thread_history,
    get_thread_state,
    generate_response,
    determine_next_state,
    store_email_with_context,
    update_thread_state,
    store_escalation,
    send_email_reply,
    normalize_message_id,
    determine_thread_id
]

# Convert tools to OpenAI format - Using the updated function
openai_tools = [convert_to_openai_tool(t) for t in tools]

# Define the agent prompt
agent_prompt = ChatPromptTemplate.from_messages([
    ("system", 
     """
You are an intelligent HR email assistant that processes emails and generates appropriate responses.

You will receive:
- input (email body and metadata)
- message_data (headers for threading)
- raw_email_data (original email dictionary)

Follow these steps strictly:
1. Call determine_thread_id using message_data.
2. Call classify_email using the input.
3. Retrieve relevant documents.
4. Retrieve thread history.
5. Generate a response based on category, history, and documents.
6. Determine next_state based on email and response.
7. **Before calling store_email_with_context:**
   - Construct a dictionary called `context` with these fields:
     - email_data = raw_email_data
     - response = (your generated email response)
     - classification = (your determined category)
     - state = (your determined next_state)
     - thread_id = (the thread_id from determine_thread_id)
8. Pass this `context` into store_email_with_context.
9. Send the email reply using send_email_reply.

Strictly follow this order.

"""),
    ("human", "{input}"),
    ("placeholder", "{agent_scratchpad}"),
])



# Create the agent
agent = create_openai_tools_agent(model, tools, agent_prompt)
agent_executor = AgentExecutor(
    agent=agent,
    tools=tools,
    verbose=True,
    handle_parsing_errors=True,
    max_iterations=10
)

def process_email(email_data: Dict[str, Any]):
    return agent_executor.invoke({
        "input": f"""
        Process this email:

        From: {email_data['from']}
        Subject: {email_data['subject']}
        Body: {email_data['body']}

        Message Metadata:
        Message-ID: {email_data.get('message_id', '')}
        In-Reply-To: {email_data.get('in_reply_to', '')}
        References: {email_data.get('references', '')}
        """,
        "message_data": {
            "message_id": email_data.get('message_id', ''),
            "in_reply_to": email_data.get('in_reply_to', ''),
            "references": email_data.get('references', '')
        },
        "raw_email_data": email_data  # <--- VERY IMPORTANT: pass as "raw_email_data"
    })


# Main execution function
def main():
    print("Checking inbox...")
    unread_emails = fetch_emails()  # Call directly as a function, not as a tool

    if not unread_emails:
        print("No new emails.")
    else:
        print(f"Found {len(unread_emails)} new emails. Processing...")
        
        for email in unread_emails:
            print(f"Processing email from: {email['from']}")
            try:
                result = process_email(email)
                print(f"Email processed successfully:\n{json.dumps(result, indent=2)}")
            except Exception as e:
                print(f"Error processing email: {e}")

if __name__ == "__main__":
    main()