import os
import json
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler
from algoliasearch.search.client import SearchClientSync
from firebase_config import db
from hr_main import main as process_inbox
from hr_tools import send_email_reply, fetch_emails
from auth import User
from datetime import datetime, timedelta
from collections import Counter, defaultdict
from google.cloud import firestore
import re
from document_storage import DocumentStorage

# Load environment variables
load_dotenv()

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'your-secret-key')
app.config['DEBUG'] = True

# Configure Flask to ignore system files
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0

# Configure the reloader to ignore system files
extra_files = []
ignored_files = [
    r'C:\\Users\\dell\\anaconda3\\envs\\etb_final_project\\Lib\\*.py',
    r'C:\\Users\\dell\\Documents\\Purdue\\Spring_25\\full_semester\\ETB\\Archive (2)\\gcloud\\google-cloud-sdk\\lib\\*.py'
]

if app.debug:
    from werkzeug._reloader import _iter_module_paths
    extra_files = [f for f in _iter_module_paths() if not any(re.match(pattern, f) for pattern in ignored_files)]

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

def load_templates():
    """Load templates from Firebase for the current user"""
    if not current_user.is_authenticated:
        return {}
    
    templates_ref = db.collection('users').document(current_user.id).collection('templates')
    templates = {}
    
    # Get all template documents
    docs = templates_ref.stream()
    for doc in docs:
        templates[doc.id] = doc.to_dict()
    
    return templates

def save_templates(data):
    """Save templates to Firebase for the current user"""
    if not current_user.is_authenticated:
        return
    
    templates_ref = db.collection('users').document(current_user.id).collection('templates')
    
    # Delete existing templates
    existing_docs = templates_ref.stream()
    for doc in existing_docs:
        doc.reference.delete()
    
    # Save new templates
    for category, template_data in data.items():
        templates_ref.document(category).set(template_data)

@app.route("/", methods=["GET"])
def index():
    if not current_user.is_authenticated:
        return redirect(url_for('login'))
    if current_user.is_authenticated and not current_user.has_complete_email_config():
        flash("Please configure your email settings to continue.", "warning")
        return redirect(url_for('email_config'))
    return render_template("index.html")

@app.route("/home", methods=["GET"])
@login_required
def home():
    if not current_user.has_complete_email_config():
        flash("Please configure your email settings to continue.", "warning")
        return redirect(url_for('email_config'))
    return render_template("index.html")

@app.route("/contact", methods=["GET"])
@login_required
def contact():
    if not current_user.has_complete_email_config():
        flash("Please configure your email settings to continue.", "warning")
        return redirect(url_for('email_config'))
    return render_template("contact.html")

@app.route("/search", methods=["GET"])
@login_required
def search_page():
    if not current_user.has_complete_email_config():
        flash("Please configure your email settings to continue.", "warning")
        return redirect(url_for('email_config'))
    print('here')
    query = request.args.get("query", "").strip()
    classification_filter = request.args.get("classification", "").strip()
    status_filter = request.args.get("status", "").strip()
    show_all = request.args.get("show_all", "").strip() == "true"
    templates = load_templates()
    results = []

    filters = []
    if classification_filter:
        filters.append(f"classification:'{classification_filter}'")
    if status_filter:
        filters.append(f"status:'{status_filter}'")
    filter_string = " AND ".join(filters)

    # Only search if something is provided or show_all is true
    should_run_search = any([query, classification_filter, status_filter, show_all])

    if should_run_search:
        print(f"🔍 Searching for: {query or '[no query]'}")
        try:
            # Search in user's email history
            email_history_ref = db.collection('users').document(current_user.id).collection("email_history")
            
            # Apply filters only if not showing all
            if not show_all:
                if classification_filter:
                    email_history_ref = email_history_ref.where("classification", "==", classification_filter)
                if status_filter:
                    email_history_ref = email_history_ref.where("status", "==", status_filter)
            
            # Get all matching documents
            docs = email_history_ref.stream()
            
            # Filter by query if provided and not showing all
            for doc in docs:
                data = doc.to_dict()
                if show_all or not query or query.lower() in data.get("subject", "").lower() or query.lower() in data.get("body", "").lower():
                    results.append({
                        "objectID": doc.id,
                        "sender": data.get("sender", ""),
                        "status": data.get("status", ""),
                        "classification": data.get("classification", ""),
                        "subject": data.get("subject", ""),
                        "body": data.get("body", ""),
                        "response": data.get("response", "")
                    })
            
        except Exception as e:
            print(f"⚠️ Search error: {e}")

    return render_template("search.html", templates=templates, query=query,
                           results=results, selected_classification=classification_filter,
                           selected_status=status_filter)

@app.route("/templates", methods=["GET"])
@login_required
def template_manager():
    if not current_user.has_complete_email_config():
        flash("Please configure your email settings before accessing templates.", "warning")
        return redirect(url_for('email_config'))
    templates = load_templates()
    return render_template("templates.html", templates=templates)

@app.route('/add', methods=['POST'])
@login_required
def add_category():
    if not current_user.has_complete_email_config():
        flash("Please configure your email settings to continue.", "warning")
        return redirect(url_for('email_config'))
    
    category = request.form['category'].strip().lower().replace(" ", "_")
    templates = load_templates()
    
    if category not in templates:
        # Create new template in Firebase
        templates_ref = db.collection('users').document(current_user.id).collection('templates')
        templates_ref.document(category).set({
            "greeting": "",
            "acknowledgement": "",
            "info": "",
            "next_steps": "",
            "closing": ""
        })
        flash("Template category added successfully!", "success")
    else:
        flash("Template category already exists!", "warning")
    
    return redirect(url_for('template_manager'))

@app.route("/update_email_fields", methods=["POST"])
@login_required
def update_email_fields():
    if not current_user.has_complete_email_config():
        flash("Please configure your email settings to continue.", "warning")
        return redirect(url_for('email_config'))
    doc_id = request.form.get("doc_id", "").strip()
    new_status = request.form.get("status")
    new_classification = request.form.get("classification")

    if not doc_id:
        print("❌ No document ID provided. Cannot update.")
        return redirect(url_for("search_page"))

    try:
        # Update in Firestore
        db.collection('users').document(current_user.id).collection("email_history").document(doc_id).update({
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
    if not current_user.has_complete_email_config():
        flash("Please configure your email settings to continue.", "warning")
        return redirect(url_for('email_config'))
    
    templates_ref = db.collection('users').document(current_user.id).collection('templates')
    template_doc = templates_ref.document(category)
    
    if template_doc.get().exists:
        template_data = {
            "greeting": request.form.get("greeting", ""),
            "acknowledgement": request.form.get("acknowledgement", ""),
            "info": request.form.get("info", ""),
            "next_steps": request.form.get("next_steps", ""),
            "closing": request.form.get("closing", "")
        }
        template_doc.set(template_data)
        flash("Template updated successfully!", "success")
    else:
        flash("Template category not found!", "error")
    
    return redirect(url_for('template_manager'))

@app.route('/delete/<category>', methods=['POST'])
@login_required
def delete_category(category):
    if not current_user.has_complete_email_config():
        flash("Please configure your email settings to continue.", "warning")
        return redirect(url_for('email_config'))
    
    templates_ref = db.collection('users').document(current_user.id).collection('templates')
    template_doc = templates_ref.document(category)
    
    if template_doc.get().exists:
        template_doc.delete()
        flash("Template category deleted successfully!", "success")
    else:
        flash("Template category not found!", "error")
    
    return redirect(url_for('template_manager'))

@app.route("/send_reply", methods=["POST"])
@login_required
def send_reply():
    if not current_user.has_complete_email_config():
        flash("Please configure your email settings to continue.", "warning")
        return redirect(url_for('email_config'))
    print('here in send reply')

    to_email = request.form.get("to_email")
    subject = request.form.get("subject")
    thread_id = request.form.get("thread_id")
    reply_body = request.form.get("reply_body")
    custom_signature = request.form.get("signature", "").strip()

    print(f"🔄 Sending reply to {to_email} with subject '{subject}'")

    try:
        # Use your existing send_email_reply function
        reply_status = send_email_reply(
            to_email=to_email,
            subject=subject,
            body=reply_body,
            message_id=thread_id,
            thread_id=thread_id,
            user_id=current_user.id,
            signature=custom_signature
        )

        if reply_status:
            flash("Reply sent successfully!", "success")
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
            
        try:
            # Create user
            user = User(None, email, None)
            user.set_password(password)
            user.save()
            
            # Initialize default template categories
            templates_ref = db.collection('users').document(user.id).collection('templates')
            
            default_templates = {
                "leave_request": {
                    "greeting": "Hi {employee_name},",
                    "acknowledgement": "Thank you for submitting your leave request for {leave_dates}.",
                    "decision": "Your request for {number_of_days} days of casual leave has been {approved/denied} based on our leave policy.",
                    "policy_reminder": "As per our HR policy, employees are eligible for up to 3 casual leave days per calendar year.",
                    "instructions": "Please ensure your responsibilities are appropriately handed over before your leave.",
                    "closing": "If you have any questions or need further assistance, feel free to reach out.\n\nRegards,\nHR Department"
                },
                "job_inquiry": {
                    "greeting": "Hello {applicant_name},",
                    "acknowledgement": "Thank you for your interest in career opportunities at {company_name}.",
                    "info": "Currently, we have openings for the following roles: {list_of_open_roles}.",
                    "next_steps": "We encourage you to apply via our Careers Portal at {careers_portal_link}.",
                    "instructions": "After submitting your application, our Talent Acquisition team will review it and get back to you shortly.",
                    "closing": "We appreciate your enthusiasm and wish you the best in your job search.\n\nBest regards,\nHR Team"
                },
                "onboarding": {
                    "greeting": "Hi {new_employee_name},",
                    "welcome": "Welcome to {company_name}! We are excited to have you onboard.",
                    "instructions": "Please complete the onboarding documents provided and submit them by {submission_deadline}.",
                    "next_steps": "You will also receive an invite for the orientation session scheduled for {orientation_date}.",
                    "support": "If you have any questions or need help, please contact {hr_contact_name} at {hr_contact_email}.",
                    "closing": "Looking forward to a great journey together!\n\nWarm regards,\nHR Department"
                },
                "escalation": {
                    "greeting": "Hi {employee_name},",
                    "acknowledgement": "Thank you for reaching out.",
                    "info": "Your query requires further review by our HR leadership team.",
                    "next_steps": "We have escalated your request and you will hear back from us shortly.",
                    "closing": "We appreciate your patience.\n\nRegards,\nHR Department"
                }
            }
            
            # Save default templates
            for category, template_data in default_templates.items():
                templates_ref.document(category).set(template_data)
            
            login_user(user)
            flash("Account created successfully! Please configure your email settings and upload required documents.", "success")
            return redirect(url_for('email_config'))
            
        except Exception as e:
            # If any error occurs during the process, clean up the user
            if user.delete():
                flash(f"Account creation failed: {str(e)}", "danger")
            else:
                flash("Error cleaning up failed account. Please contact support.", "danger")
            return render_template("signup.html")
        
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
        
        if config_type == 'documents':
            # Initialize document storage
            doc_storage = DocumentStorage(current_user.id)
            
            # Get the category being saved
            save_category = request.form.get('save_category')
            if not save_category:
                flash('No category specified for document upload', 'error')
                return redirect(url_for('email_config', tab='documents'))
            
            # Check if a file was uploaded for this category
            if save_category not in request.files:
                flash(f'No file selected for {save_category.replace("_", " ").title()}', 'error')
                return redirect(url_for('email_config', tab='documents'))
                
            file = request.files[save_category]
            if file.filename == '':
                flash(f'No file selected for {save_category.replace("_", " ").title()}', 'error')
                return redirect(url_for('email_config', tab='documents'))
                
            try:
                # Validate file type
                if not file.filename.lower().endswith('.pdf'):
                    flash(f"Only PDF files are supported for {save_category.replace('_', ' ').title()}", "danger")
                    return redirect(url_for('email_config', tab='documents'))
                    
                # Read file content as bytes
                file_content = file.read()
                
                # Process and store document
                result = doc_storage.process_and_store_document(file_content, file.filename, save_category)
                print(f"✅ Document processed for {save_category}: {result['filename']}")
                flash(f'Document uploaded successfully for {save_category.replace("_", " ").title()}', 'success')
                
            except Exception as e:
                print(f"❌ Error processing document for {save_category}: {str(e)}")
                flash(f"Error processing document for {save_category.replace('_', ' ').title()}: {str(e)}", "danger")
            
            return redirect(url_for('email_config', tab='documents'))
            
        elif config_type == 'escalation':
            escalation_email = request.form.get('escalation_email')
            if not escalation_email:
                flash('Escalation email is required', 'error')
                return redirect(url_for('email_config', tab='escalation'))
                
            try:
                # Validate email format
                if '@' not in escalation_email or '.' not in escalation_email:
                    flash('Invalid email format', 'error')
                    return redirect(url_for('email_config', tab='escalation'))
                    
                current_user.update_email_config('escalation', {'escalation_email': escalation_email})
                flash('Escalation email updated successfully', 'success')
                # Move to documents tab after escalation
                return redirect(url_for('email_config', tab='documents'))
            except Exception as e:
                print(f"❌ Error updating escalation email: {str(e)}")
                flash(f'Error updating escalation email: {str(e)}', 'error')
                return redirect(url_for('email_config', tab='escalation'))
            
        elif config_type in ['incoming', 'outgoing']:
            config_data = {
                'email': request.form.get('email'),
                'password': request.form.get('password'),
                'server': request.form.get('server'),
                'port': request.form.get('port'),
                'use_ssl': 'use_ssl' in request.form
            }
            
            # Log the configuration attempt (excluding password)
            print(f"\n📧 Attempting to configure {config_type} email:")
            print(f"Email: {config_data['email']}")
            print(f"Server: {config_data['server']}")
            print(f"Port: {config_data['port']}")
            print(f"SSL: {config_data['use_ssl']}")
            print(f"Password length: {len(config_data['password']) if config_data['password'] else 0} characters")
            
            try:
                current_user.update_email_config(config_type, config_data)
                flash(f'{config_type.capitalize()} email configuration updated successfully', 'success')
                
                # Determine next tab based on current config_type
                if config_type == 'incoming':
                    return redirect(url_for('email_config', tab='outgoing'))
                elif config_type == 'outgoing':
                    return redirect(url_for('email_config', tab='escalation'))
                    
            except Exception as e:
                print(f"❌ Error updating email configuration: {str(e)}")
                flash(f'Error updating email configuration: {str(e)}', 'error')
                return redirect(url_for('email_config', tab=config_type))
            
        else:
            flash('Invalid configuration type', 'error')
            return redirect(url_for('email_config'))
            
    # Get the current tab from query parameters, default to 'incoming'
    current_tab = request.args.get('tab', 'incoming')
    
    # Get existing configuration
    user_doc = db.collection('users').document(current_user.id).get()
    user_data = user_doc.to_dict() if user_doc.exists else {}
    
    # Load templates for the documents tab
    templates = load_templates()
    
    # Get list of uploaded documents
    doc_storage = DocumentStorage(current_user.id)
    docs_ref = db.collection('users').document(current_user.id).collection('documents')
    documents = []
    for doc in docs_ref.stream():
        data = doc.to_dict()
        documents.append({
            'filename': data.get('filename', ''),
            'upload_date': data.get('created_at', ''),
            'document_id': doc.id,
            'category': data.get('category', '')
        })
    
    return render_template('email_config.html', 
                         templates=templates, 
                         current_tab=current_tab,
                         incoming_config=user_data.get('email_config_incoming', {}),
                         outgoing_config=user_data.get('email_config_outgoing', {}),
                         escalation_email=user_data.get('escalation_email', ''),
                         documents=documents)

# Initialize scheduler
scheduler = BackgroundScheduler()
scheduler.add_job(func=process_inbox, trigger="interval", minutes=5)
scheduler.start()

import atexit
atexit.register(lambda: scheduler.shutdown())

def calculate_email_metrics(user_id: str) -> dict:
    """
    Calculate various email metrics for the dashboard.
    """
    # Get all emails from the last 3 days
    three_days_ago = datetime.now() - timedelta(days=3)
    
    # Query emails from Firestore
    emails_ref = db.collection('users').document(user_id).collection("email_history")
    emails = emails_ref.stream()
    
    # Initialize metrics
    metrics = {
        'total_emails': 0,
        'daily_emails': defaultdict(int),
        'category_counts': defaultdict(int),
        'status_counts': defaultdict(int),
        'successful_replies': 0,
        'escalated_cases': 0,
        'sender_counts': Counter(),
        'avg_response_time': 0,
        'total_response_time': 0,
        'response_count': 0
    }
    
    # Process each email
    for email in emails:
        email_data = email.to_dict()
        timestamp = email_data.get('timestamp')
        
        # Skip if no timestamp
        if not timestamp:
            continue
            
        # Convert Firestore timestamp to datetime
        email_date = timestamp.replace(tzinfo=None)
        
        # Only include emails from last 3 days
        if email_date < three_days_ago:
            continue
            
        metrics['total_emails'] += 1
        metrics['daily_emails'][email_date.strftime('%Y-%m-%d')] += 1
        
        # Category metrics
        category = email_data.get('classification', 'unknown')
        metrics['category_counts'][category] += 1
        
        # Status metrics
        status = email_data.get('status', 'new')
        metrics['status_counts'][status] += 1
        
        # Reply metrics
        if email_data.get('reply_status'):
            metrics['successful_replies'] += 1
            
        # Escalation metrics
        if category == 'escalate':
            metrics['escalated_cases'] += 1
            
        # Sender metrics
        sender = email_data.get('sender', 'unknown')
        metrics['sender_counts'][sender] += 1
        
        # Response time metrics
        if email_data.get('response'):
            metrics['response_count'] += 1
            # Add to total response time (placeholder for now)
            metrics['total_response_time'] += 1
    
    # Calculate averages and percentages
    if metrics['response_count'] > 0:
        metrics['avg_response_time'] = metrics['total_response_time'] / metrics['response_count']
    
    # Calculate percentages
    total = metrics['total_emails']
    if total > 0:
        metrics['category_percentages'] = {
            category: (count / total) * 100 
            for category, count in metrics['category_counts'].items()
        }
        metrics['status_percentages'] = {
            status: (count / total) * 100 
            for status, count in metrics['status_counts'].items()
        }
        metrics['reply_success_rate'] = (metrics['successful_replies'] / total) * 100
    else:
        metrics['category_percentages'] = {}
        metrics['status_percentages'] = {}
        metrics['reply_success_rate'] = 0
    
    # Convert daily_emails to sorted list
    metrics['daily_emails'] = [
        {'date': date, 'count': count}
        for date, count in sorted(metrics['daily_emails'].items())
    ]
    
    # Get top 5 senders
    metrics['top_senders'] = metrics['sender_counts'].most_common(5)
    
    return metrics

@app.route("/dashboard", methods=["GET"])
@login_required
def dashboard():
    if not current_user.has_complete_email_config():
        flash("Please configure your email settings to continue.", "warning")
        return redirect(url_for('email_config'))
        
    metrics = calculate_email_metrics(current_user.id)
    return render_template("dashboard.html", metrics=metrics)

# Add delete document route
@app.route('/documents/delete/<document_id>', methods=['POST'])
@login_required
def delete_document(document_id):
    if not current_user.has_complete_email_config():
        flash("Please configure your email settings to continue.", "warning")
        return redirect(url_for('email_config'))
        
    try:
        # Initialize document storage
        doc_storage = DocumentStorage(current_user.id)
        
        # Delete document
        doc_storage.delete_document(document_id)
        flash('Document deleted successfully', 'success')
    except Exception as e:
        flash(f'Error deleting document: {str(e)}', 'error')
        
    return redirect(url_for('email_config', tab='documents'))

if __name__ == '__main__':
    app.run(debug=True)
