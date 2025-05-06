# hr-ai-agent

An AI-powered HR email response agent for automating and managing HR email workflows, built with Flask, LangChain, Firebase, and Algolia. It features stateful thread management, customizable response templates, admin-in-the-loop learning, and a modern web UI.

---

## Features

- **Automated Email Classification**: Classifies incoming emails (e.g., Leave Request, Job Inquiry, Onboarding, Escalation) using LLMs.
- **Contextual Response Generation**: Generates professional, context-aware replies using LangChain and customizable templates.
- **Thread & State Management**: Maintains conversation history and tracks the state of each email thread.
- **Document Retrieval (RAG)**: Retrieves relevant HR policy documents for informed responses.
- **Admin-in-the-Loop**: Allows manual review, editing, and escalation of responses.
- **Search & Filter**: Search and filter emails by category and status via a web interface.
- **Template Management**: Add, edit, or delete response templates for each category.
- **Modern Web UI**: Clean, responsive interface for HR teams.
- **Firebase Integration**: Stores email history, thread states, and admin feedback in Firestore.
- **Algolia Search**: Fast, scalable search over email history.
- **Dockerized**: Easy deployment with Docker and Gunicorn.

---

## Project Structure

```
├── app.py                  # Flask web app (main entry point)
├── hr_main.py              # Main email processing logic
├── hr_tools.py             # Email classification, response generation, utilities
├── database.py             # Firestore database operations
├── firebase_config.py      # Firebase initialization
├── response_templates.json # Customizable response templates
├── requirements.txt        # Python dependencies
├── Dockerfile              # Containerization setup
├── templates/              # Jinja2 HTML templates
├── static/                 # CSS and static assets
├── documents/              # HR policy/reference documents
├── db/                     # Vector DB for document retrieval
├── .env                    # Environment variables (not committed)
└── ...
```

---

## Quick Start

### 1. Clone the Repository

```bash
git clone <repo-url>
cd hr-ai-agent
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Set Up Environment Variables

Create a `.env` file in the project root with the following variables:

```
OPENAI_API_KEY=your-openai-key
EMAIL_USER=your-email@gmail.com
EMAIL_PASSWORD=your-app-password
HR_EMAIL_USER=your-hr-email@gmail.com
HR_EMAIL_PASSWORD=your-hr-app-password
IMAP_SERVER=imap.gmail.com
ALGOLIA_APP_ID=your-algolia-app-id
ALGOLIA_API_KEY=your-algolia-api-key
ALGOLIA_INDEX_NAME=email_history
FIREBASE_CONFIG=... (optional, or use hair-firebase.json)
```

Or place your Firebase service account JSON as `hair-firebase.json` in the root directory.

### 4. Run the App (Development)

```bash
python app.py
```

Visit [http://localhost:5000](http://localhost:5000) in your browser.

### 5. Run with Docker (Production)

```bash
docker build -t hr-ai-agent .
docker run -p 8080:8080 --env-file .env hr-ai-agent
```

---

## Usage

- **Home**: Project overview and navigation.
- **Search Emails**: Search, filter, and manage incoming emails. Update classification/status, send replies, or escalate.
- **Manage Templates**: Add/edit/delete response templates for each category.
- **Contact Us**: Project contact/support page.

---

## Customizing Response Templates

Edit `response_templates.json` or use the web UI to manage templates for each category (e.g., leave_request, job_inquiry, onboarding, escalation). Placeholders (e.g., `{employee_name}`) are auto-filled from email content.

---

## Environment Variables

- `OPENAI_API_KEY`, `GEMINI_API_KEY`: LLM API keys
- `EMAIL_USER`, `EMAIL_PASSWORD`: Email account for sending/receiving
- `HR_EMAIL_USER`, `HR_EMAIL_PASSWORD`: Admin escalation email
- `IMAP_SERVER`: IMAP server for email fetching
- `ALGOLIA_APP_ID`, `ALGOLIA_API_KEY`, `ALGOLIA_INDEX_NAME`: Algolia search config
- `FIREBASE_CONFIG` or `hair-firebase.json`: Firebase credentials

---

## Deployment

- **Docker**: See above for Docker instructions.
- **Cloud Run/Heroku**: Use the Dockerfile for cloud deployment. Set environment variables as needed.

---

## License

MIT License. See [LICENSE](LICENSE) for details.

---

## Acknowledgements

- [LangChain](https://langchain.com/)
- [Firebase](https://firebase.google.com/)
- [Algolia](https://www.algolia.com/)
- [OpenAI](https://openai.com/)
- [Flask](https://flask.palletsprojects.com/)
