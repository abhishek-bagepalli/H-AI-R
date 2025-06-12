import firebase_admin
from firebase_admin import credentials, firestore
import os
import json

# Initialize Firebase App
firebase_app = None
if os.getenv('FIREBASE_CONFIG'):
    firebase_config_json = json.loads(os.getenv('FIREBASE_CONFIG'))
    cred = credentials.Certificate(firebase_config_json)
    # Get bucket name from config if available
    bucket_name = firebase_config_json.get('storageBucket') or os.getenv('FIREBASE_STORAGE_BUCKET')
    if not bucket_name:
        raise ValueError("Storage bucket name not found in Firebase config or environment variables")
    # Remove gs:// prefix if present
    if bucket_name.startswith('gs://'):
        bucket_name = bucket_name[5:]
    firebase_app = firebase_admin.initialize_app(cred, {
        'storageBucket': bucket_name
    })
else:
    # Local development fallback
    cred = credentials.Certificate('hair-firebase.json')
    # Read bucket name from local config
    with open('hair-firebase.json', 'r') as f:
        config = json.load(f)
        bucket_name = config.get('storageBucket')
        if not bucket_name:
            raise ValueError("Storage bucket name not found in local Firebase config")
        # Remove gs:// prefix if present
        if bucket_name.startswith('gs://'):
            bucket_name = bucket_name[5:]
    firebase_app = firebase_admin.initialize_app(cred, {
        'storageBucket': bucket_name
    })

# Initialize Firestore
db = firestore.client(app=firebase_app)