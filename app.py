import os
import json
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler
from algoliasearch.search.client import SearchClientSync
from firebase_config import db
from hr_main import main as process_inbox
from hr_tools import send_email_reply
from auth import User
load_dotenv()

# Flask app initialization
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "qwertypeepee")
TEMPLATES_FILE = 'response_templates.json'

# Flask-Login setup
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please log in to access this page.'
login_manager.login_message_category = 'info'

@login_manager.user_loader
def load_user(user_id):
    return User.get(user_id)

# Algolia configuration
ALGOLIA_APP_ID = os.getenv("ALGOLIA_APP_ID")
ALGOLIA_API_KEY = os.getenv("ALGOLIA_API_KEY")
ALGOLIA_INDEX_NAME = os.getenv("ALGOLIA_INDEX_NAME")

# Initialize Algolia client
algolia_client = SearchClientSync(app_id=ALGOLIA_APP_ID, api_key=ALGOLIA_API_KEY)

# Helper functions to load and save templates
def load_templates():
    if not os.path.exists(TEMPLATES_FILE):
        return {}
    with open(TEMPLATES_FILE, 'r') as f:
        return json.load(f)

def save_templates(data):
    with open(TEMPLATES_FILE, 'w') as f:
        json.dump(data, f, indent=2)

@app.route("/", methods=["GET"])
def index():
    if not current_user.is_authenticated:
        return redirect(url_for('login'))
    return render_template("index.html")

@app.route("/home", methods=["GET"])
@login_required
def home():
    return render_template("index.html")

@app.route("/contact", methods=["GET"])
@login_required
def contact():
    return render_template("contact.html")

@app.route("/search", methods=["GET"])
@login_required
def search_page():
    print('here')
    query = request.args.get("query", "").strip()
    classification_filter = request.args.get("classification", "").strip()
    status_filter = request.args.get("status", "").strip()
    templates = load_templates()
    results = []

    filters = []
    if classification_filter:
        filters.append(f"classification:'{classification_filter}'")
    if status_filter:
        filters.append(f"status:'{status_filter}'")
    filter_string = " AND ".join(filters)

    # Only search if something is provided
    should_run_search = any([query, classification_filter, status_filter])

    if should_run_search:
        print(f"🔍 Searching for: {query or '[no query]'}")
        try:
            search_response = algolia_client.search_single_index(
                index_name=ALGOLIA_INDEX_NAME,
                search_params={
                    "query": query or "",  # empty string if query is blank
                    "filters": filter_string
                }
            )
            hits = search_response.hits
            for hit in hits:
                results.append({
                    "objectID": hit.message_id,
                    "sender": hit.sender,
                    "status": hit.status,
                    "classification": hit.classification,
                    "subject": hit.subject,
                    "body": hit.body,
                    "response": hit.response
                })
        except Exception as e:
            print(f"⚠️ Algolia search error: {e}")

    return render_template("search.html", templates=templates, query=query,
                           results=results, selected_classification=classification_filter,
                           selected_status=status_filter)

@app.route("/templates", methods=["GET"])
@login_required
def template_manager():
    templates = load_templates()
    return render_template("templates.html", templates=templates)

@app.route('/add', methods=['POST'])
@login_required
def add_category():
    category = request.form['category'].strip().lower().replace(" ", "_")
    templates = load_templates()
    if category not in templates:
        templates[category] = {
            "greeting": "",
            "acknowledgement": "",
            "info": "",
            "next_steps": "",
            "closing": ""
        }
        save_templates(templates)
    return redirect(url_for('index'))

@app.route("/update_email_fields", methods=["POST"])
@login_required
def update_email_fields():
    doc_id = request.form.get("doc_id", "").strip()
    new_status = request.form.get("status")
    new_classification = request.form.get("classification")

    if not doc_id:
        print("❌ No document ID provided. Cannot update.")
        return redirect(url_for("search_page"))

    try:
        # Update in Firestore
        db.collection("email_history").document(doc_id).update({
            "status": new_status,
            "classification": new_classification
        })

        # Update in Algolia - Error occuring here, fix later
        # algolia_index = algolia_client.init_index(ALGOLIA_INDEX_NAME)
        # algolia_index.partial_update_object({
        #     "objectID": doc_id,
        #     "status": new_status,
        #     "classification": new_classification
        # })

        print(f"✅ Email fields updated: {doc_id}")
        flash("✅ Email fields updated successfully!", "success")

    except Exception as e:
        print(f"❌ Failed to update email fields: {e}")

    return redirect(url_for("search_page", query=request.form.get("query", ""),
                        classification=request.form.get("classification", ""),
                        status=request.form.get("status", "")))

@app.route('/update/<category>', methods=['POST'])
@login_required
def update_template(category):
    templates = load_templates()
    if category in templates:
        for key in templates[category].keys():
            templates[category][key] = request.form.get(key, "")
        save_templates(templates)
    return redirect(url_for('template_manager'))

@app.route('/delete/<category>', methods=['POST'])
@login_required
def delete_category(category):
    templates = load_templates()
    if category in templates:
        del templates[category]
        save_templates(templates)
    return redirect(url_for('template_manager'))

@app.route("/send_reply", methods=["POST"])
@login_required
def send_reply():
    print('here in send reply')

    to_email = request.form.get("to_email")
    subject = request.form.get("subject")
    thread_id = request.form.get("thread_id")
    reply_body = request.form.get("reply_body")

    print(f"🔄 Sending reply to {to_email} with subject '{subject}'")

    try:
        # Use your existing send_email_reply function
        reply_status = send_email_reply(
            to_email=to_email,
            subject=subject,
            body=reply_body,
            message_id=thread_id,
            thread_id=thread_id
        )

        if reply_status:
            flash("Reply sent successfully.", "success")
        else:
            flash("Failed to send reply.", "error")

    except Exception as e:
        print(f"❌ Error sending reply: {e}")
        flash("Error sending reply.", "error")

    return redirect(url_for("search_page", query=request.args.get("query", "")))

@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('home'))
        
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")
        
        user = User.get_by_email(email)
        if user and user.check_password(password):
            login_user(user)
            next_page = request.args.get('next')
            return redirect(next_page or url_for('home'))
        else:
            flash("Invalid email or password", "danger")
            
    return render_template("login.html")

@app.route("/signup", methods=["GET", "POST"])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for('home'))
        
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")
        confirm_password = request.form.get("confirm_password")
        
        if password != confirm_password:
            flash("Passwords do not match", "danger")
            return render_template("signup.html")
            
        if User.get_by_email(email):
            flash("Email already registered", "danger")
            return render_template("signup.html")
            
        user = User(None, email, None)
        user.set_password(password)
        user.save()
        
        login_user(user)
        flash("Account created successfully!", "success")
        return redirect(url_for('home'))
        
    return render_template("signup.html")

@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/email-config', methods=['GET', 'POST'])
@login_required
def email_config():
    if request.method == 'POST':
        config_type = request.form.get('config_type')
        if config_type not in ['incoming', 'outgoing']:
            flash('Invalid configuration type', 'error')
            return redirect(url_for('email_config'))
            
        config_data = {
            'email': request.form.get('email'),
            'password': request.form.get('password'),
            'server': request.form.get('server'),
            'port': request.form.get('port'),
            'use_ssl': request.form.get('use_ssl') == 'true'
        }
        
        try:
            current_user.update_email_config(config_type, config_data)
            flash(f'{config_type.capitalize()} email configuration updated successfully', 'success')
        except Exception as e:
            flash(f'Error updating email configuration: {str(e)}', 'error')
            
        return redirect(url_for('email_config'))
        
    return render_template('email_config.html')

# Scheduler to process inbox every 5 minutes
scheduler = BackgroundScheduler()
scheduler.add_job(func=process_inbox, trigger="interval", minutes=5)
scheduler.start()

import atexit
atexit.register(lambda: scheduler.shutdown())

if __name__ == '__main__':
    app.run(debug=True)
