from firebase_config import db
from werkzeug.security import generate_password_hash
import getpass

def update_user_password(email):
    # Find user by email
    users_ref = db.collection('users')
    query = users_ref.where('email', '==', email).limit(1)
    results = query.get()
    
    if not results:
        print(f"No user found with email {email}")
        return False
        
    user_doc = results[0]
    user_data = user_doc.to_dict()
    
    # Get new password
    new_password = getpass.getpass("Enter new password: ")
    confirm_password = getpass.getpass("Confirm new password: ")
    
    if new_password != confirm_password:
        print("Passwords do not match!")
        return False
    
    # Generate new hash
    new_hash = generate_password_hash(new_password, method='pbkdf2:sha256')
    
    # Update user document
    user_doc.reference.update({
        'password_hash': new_hash
    })
    
    print(f"Password updated successfully for {email}")
    return True

if __name__ == "__main__":
    email = input("Enter user email: ")
    update_user_password(email) 