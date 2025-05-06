import firebase_admin
from firebase_admin import credentials, firestore
import os
import json

# Initialize Firebase App
firebase_app = None
if os.getenv('FIREBASE_CONFIG'):
    firebase_config_json = json.loads(os.getenv('FIREBASE_CONFIG'))
    cred = credentials.Certificate(firebase_config_json)
    firebase_app = firebase_admin.initialize_app(cred)
else:
    # Local development fallback
    cred = credentials.Certificate('hair-firebase.json')
    firebase_app = firebase_admin.initialize_app(cred)

# Initialize Firestore
db = firestore.client(app=firebase_app)