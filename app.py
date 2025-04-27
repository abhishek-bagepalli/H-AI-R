from flask import Flask, render_template, request, redirect, url_for
import json
import os
from hr_ai_agent_project import main as process_inbox
from apscheduler.schedulers.background import BackgroundScheduler

app = Flask(__name__)
TEMPLATES_FILE = 'response_templates.json'

# Helper to load templates
def load_templates():
    if not os.path.exists(TEMPLATES_FILE):
        return {}
    with open(TEMPLATES_FILE, 'r') as f:
        return json.load(f)

# Helper to save templates
def save_templates(data):
    with open(TEMPLATES_FILE, 'w') as f:
        json.dump(data, f, indent=2)

@app.route('/')
def index():
    templates = load_templates()
    return render_template('index.html', templates=templates)

@app.route('/add', methods=['POST'])
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

@app.route('/update/<category>', methods=['POST'])
def update_template(category):
    templates = load_templates()
    if category in templates:
        for key in templates[category].keys():
            templates[category][key] = request.form.get(key, "")
        save_templates(templates)
    return redirect(url_for('index'))

@app.route('/delete/<category>', methods=['POST'])
def delete_category(category):
    templates = load_templates()
    if category in templates:
        del templates[category]
        save_templates(templates)
    return redirect(url_for('index'))

scheduler = BackgroundScheduler()

# Schedule process_inbox() to run every 5 minutes
scheduler.add_job(func=process_inbox, trigger="interval", minutes=5)

scheduler.start()

import atexit
atexit.register(lambda: scheduler.shutdown())

if __name__ == '__main__':
    app.run(debug=True)
