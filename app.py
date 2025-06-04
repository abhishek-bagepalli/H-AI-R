import os
import json
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler
from algoliasearch.search.client import SearchClientSync
from firebase_config import db
from hr_main import main as process_inbox
from hr_tools import send_email_reply, fetch_emails
from auth import User
from document_manager import DocumentManager
load_dotenv()

# Flask app initialization
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "qwertypeepee")

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
            # Search in user's email history
            email_history_ref = db.collection('users').document(current_user.id).collection("email_history")
            
            # Apply filters
            if classification_filter:
                email_history_ref = email_history_ref.where("classification", "==", classification_filter)
            if status_filter:
                email_history_ref = email_history_ref.where("status", "==", status_filter)
            
            # Get all matching documents
            docs = email_history_ref.stream()
            
            # Filter by query if provided
            for doc in docs:
                data = doc.to_dict()
                if not query or query.lower() in data.get("subject", "").lower() or query.lower() in data.get("body", "").lower():
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
            
        try:
            # Create user
            user = User(None, email, None)
            user.set_password(password)
            user.save()
            
            # Initialize default template categories
            templates_ref = db.collection('users').document(user.id).collection('templates')
            
            default_templates = {
                "leave_request": {
                    "greeting": "Dear {name},",
                    "acknowledgement": "Thank you for your leave request.",
                    "info": "Your request for {number_of_days} days of leave has been {approved/denied}.",
                    "next_steps": "Please ensure to complete your handover before your leave.",
                    "closing": "Best regards,"
                },
                "job_inquiry": {
                    "greeting": "Dear {name},",
                    "acknowledgement": "Thank you for your interest in our company.",
                    "info": "We have received your application for the {position} position.",
                    "next_steps": "Our team will review your application and get back to you within 5 business days.",
                    "closing": "Best regards,"
                },
                "onboarding": {
                    "greeting": "Dear {name},",
                    "acknowledgement": "Welcome to our team!",
                    "info": "We are excited to have you join us as {position}.",
                    "next_steps": "Please complete the onboarding documents attached and bring your ID documents on your first day.",
                    "closing": "Best regards,"
                },
                "escalation": {
                    "greeting": "Dear {name},",
                    "acknowledgement": "Thank you for your email.",
                    "info": "Your request requires additional attention and has been escalated to our team.",
                    "next_steps": "A team member will review your case and get back to you shortly.",
                    "closing": "Best regards,"
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
            # Initialize document manager
            doc_manager = DocumentManager(current_user.id)
            
            # Get all template categories
            templates = load_templates()
            upload_success = True
            
            # Handle document uploads for each category
            for category in templates.keys():
                if category not in request.files:
                    continue  # Skip if no file provided for this category
                    
                file = request.files[category]
                if file.filename == '':
                    continue  # Skip if no file selected
                    
                try:
                    # Read file content as bytes
                    file_content = file.read()
                    if not doc_manager.upload_document(file_content, file.filename):
                        flash(f"Error uploading document for {category.replace('_', ' ').title()}", "danger")
                        upload_success = False
                except Exception as e:
                    flash(f"Error processing document for {category.replace('_', ' ').title()}: {str(e)}", "danger")
                    upload_success = False
            
            if upload_success:
                # Mark email configuration as complete
                current_user.update_email_config('complete', {'is_complete': True})
                flash("Configuration completed successfully!", "success")
                return redirect(url_for('home'))
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
    
    return render_template('email_config.html', 
                         templates=templates, 
                         current_tab=current_tab,
                         incoming_config=user_data.get('email_config_incoming', {}),
                         outgoing_config=user_data.get('email_config_outgoing', {}),
                         escalation_email=user_data.get('escalation_email', ''))

@app.route('/documents', methods=['GET'])
@login_required
def document_list():
    if not current_user.has_complete_email_config():
        flash("Please configure your email settings to continue.", "warning")
        return redirect(url_for('email_config'))
        
    doc_manager = DocumentManager(current_user.id)
    documents = doc_manager.list_documents()
    return render_template('documents.html', documents=documents)

@app.route('/documents/upload', methods=['POST'])
@login_required
def upload_document():
    if not current_user.has_complete_email_config():
        flash("Please configure your email settings to continue.", "warning")
        return redirect(url_for('email_config'))
        
    if 'document' not in request.files:
        flash('No file selected', 'error')
        return redirect(url_for('document_list'))
        
    file = request.files['document']
    if file.filename == '':
        flash('No file selected', 'error')
        return redirect(url_for('document_list'))
        
    if file:
        try:
            content = file.read().decode('utf-8')
            doc_manager = DocumentManager(current_user.id)
            if doc_manager.upload_document(content, file.filename):
                flash('Document uploaded successfully', 'success')
            else:
                flash('Error uploading document', 'error')
        except Exception as e:
            flash(f'Error processing file: {str(e)}', 'error')
            
    return redirect(url_for('document_list'))

@app.route('/documents/delete/<filename>', methods=['POST'])
@login_required
def delete_document(filename):
    if not current_user.has_complete_email_config():
        flash("Please configure your email settings to continue.", "warning")
        return redirect(url_for('email_config'))
        
    doc_manager = DocumentManager(current_user.id)
    if doc_manager.delete_document(filename):
        flash('Document deleted successfully', 'success')
    else:
        flash('Error deleting document', 'error')
        
    return redirect(url_for('document_list'))

@app.route('/documents/edit/<filename>', methods=['GET', 'POST'])
@login_required
def edit_document(filename):
    if not current_user.has_complete_email_config():
        flash("Please configure your email settings to continue.", "warning")
        return redirect(url_for('email_config'))
        
    doc_manager = DocumentManager(current_user.id)
    
    if request.method == 'POST':
        content = request.form.get('content')
        if doc_manager.update_document(filename, content):
            flash('Document updated successfully', 'success')
            return redirect(url_for('document_list'))
        else:
            flash('Error updating document', 'error')
            
    content = doc_manager.get_document_content(filename)
    if content is None:
        flash('Document not found', 'error')
        return redirect(url_for('document_list'))
        
    return render_template('edit_document.html', filename=filename, content=content)

# Initialize scheduler
scheduler = BackgroundScheduler()
scheduler.add_job(func=process_inbox, trigger="interval", minutes=5)
scheduler.start()

import atexit
atexit.register(lambda: scheduler.shutdown())

if __name__ == '__main__':
    app.run(debug=True)
