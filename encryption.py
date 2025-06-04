from cryptography.fernet import Fernet
from base64 import b64encode, b64decode
import os
from dotenv import load_dotenv

print("\nLoading environment variables...")
load_dotenv()
print("✅ Environment variables loaded")

# Get encryption key from environment variable or generate a new one
def get_encryption_key():
    key = os.getenv('ENCRYPTION_KEY')
    print(f"\nChecking encryption key...")
    if not key:
        print("❌ ENCRYPTION_KEY not found in environment variables")
        print("Current environment variables:", os.environ.keys())
        raise ValueError("ENCRYPTION_KEY not found in environment variables. Please add it to your .env file.")
    
    print(f"✅ Found ENCRYPTION_KEY in environment")
    print(f"Key length: {len(key)} characters")
    try:
        # Try to decode the key to verify it's valid base64
        if isinstance(key, str):
            key = key.encode()
        # Verify it's a valid Fernet key
        Fernet(key)
        print("✅ Encryption key is valid")
        return key
    except Exception as e:
        print(f"❌ Invalid encryption key format: {str(e)}")
        raise ValueError(f"Invalid encryption key format: {str(e)}")

# Initialize Fernet with the key
try:
    print("\nInitializing Fernet...")
    fernet = Fernet(get_encryption_key())
    print("✅ Fernet initialized successfully")
except Exception as e:
    print(f"❌ Failed to initialize Fernet: {str(e)}")
    raise

def encrypt_data(data):
    """
    Encrypt sensitive data before storing in Firebase
    """
    if not data:
        return None
    try:
        print(f"\nEncrypting data...")
        # Convert data to bytes if it's a string
        if isinstance(data, str):
            data = data.encode()
        # Encrypt the data
        encrypted_data = fernet.encrypt(data)
        # Convert to string for storage
        result = b64encode(encrypted_data).decode()
        print("✅ Data encrypted successfully")
        return result
    except Exception as e:
        print(f"❌ Error encrypting data: {str(e)}")
        return None

def decrypt_data(encrypted_data):
    """
    Decrypt data retrieved from Firebase
    """
    if not encrypted_data:
        print("❌ No data to decrypt")
        return None
    try:
        print(f"\nDecrypting data...")
        # Convert string back to bytes
        encrypted_bytes = b64decode(encrypted_data)
        # Decrypt the data
        decrypted_data = fernet.decrypt(encrypted_bytes)
        print("✅ Data decrypted successfully")
        # Return bytes instead of converting to string
        return decrypted_data
    except Exception as e:
        print(f"❌ Error decrypting data: {str(e)}")
        return None 