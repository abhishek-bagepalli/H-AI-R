from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from firebase_config import db
from encryption import encrypt_data, decrypt_data

class User(UserMixin):
    def __init__(self, user_id, email, password_hash, incoming_email_config=None, outgoing_email_config=None):
        self.id = user_id
        self.email = email
        self.password_hash = password_hash
        self.incoming_email_config = incoming_email_config or {}
        self.outgoing_email_config = outgoing_email_config or {}
        self.escalation_email = None

    @staticmethod
    def get(user_id):
        user_doc = db.collection('users').document(user_id).get()
        if user_doc.exists:
            user_data = user_doc.to_dict()
            # Decrypt email configurations
            incoming_config = user_data.get('email_config_incoming', {})
            outgoing_config = user_data.get('email_config_outgoing', {})
            
            if incoming_config and 'password' in incoming_config:
                incoming_config['password'] = decrypt_data(incoming_config['password'])
            if outgoing_config and 'password' in outgoing_config:
                outgoing_config['password'] = decrypt_data(outgoing_config['password'])
            
            user = User(
                user_id=user_id,
                email=user_data['email'],
                password_hash=user_data['password_hash'],
                incoming_email_config=incoming_config,
                outgoing_email_config=outgoing_config
            )
            user.escalation_email = user_data.get('escalation_email')
            return user
        return None

    @staticmethod
    def get_by_email(email):
        users_ref = db.collection('users')
        query = users_ref.where('email', '==', email).limit(1)
        results = query.get()
        
        if not results:
            return None
            
        user_doc = results[0]
        user_data = user_doc.to_dict()
        
        # Decrypt email configurations
        incoming_config = user_data.get('email_config_incoming', {})
        outgoing_config = user_data.get('email_config_outgoing', {})
        
        if incoming_config and 'password' in incoming_config:
            incoming_config['password'] = decrypt_data(incoming_config['password'])
        if outgoing_config and 'password' in outgoing_config:
            outgoing_config['password'] = decrypt_data(outgoing_config['password'])
        
        user = User(
            user_id=user_doc.id,
            email=user_data['email'],
            password_hash=user_data['password_hash'],
            incoming_email_config=incoming_config,
            outgoing_email_config=outgoing_config
        )
        user.escalation_email = user_data.get('escalation_email')
        return user

    def save(self):
        # Create a copy of configurations for encryption
        incoming_config = self.incoming_email_config.copy() if self.incoming_email_config else {}
        outgoing_config = self.outgoing_email_config.copy() if self.outgoing_email_config else {}
        
        # Encrypt passwords in configurations
        if incoming_config and 'password' in incoming_config:
            incoming_config['password'] = encrypt_data(incoming_config['password'])
        if outgoing_config and 'password' in outgoing_config:
            outgoing_config['password'] = encrypt_data(outgoing_config['password'])
        
        user_data = {
            'email': self.email,
            'password_hash': self.password_hash,
            'email_config_incoming': incoming_config,
            'email_config_outgoing': outgoing_config,
            'escalation_email': self.escalation_email
        }
        
        if self.id:
            db.collection('users').document(self.id).set(user_data, merge=True)
        else:
            new_user_ref = db.collection('users').document()
            self.id = new_user_ref.id
            new_user_ref.set(user_data)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password, method='pbkdf2:sha256')

    def check_password(self, password):
        try:
            return check_password_hash(self.password_hash, password)
        except ValueError as e:
            if "unsupported hash type scrypt" in str(e):
                # If scrypt fails, try to rehash with pbkdf2
                new_hash = generate_password_hash(password, method='pbkdf2:sha256')
                # Update the hash in the database
                db.collection('users').document(self.id).update({
                    'password_hash': new_hash
                })
                # Update the instance
                self.password_hash = new_hash
                return True
            raise

    def update_email_config(self, config_type: str, config_data: dict) -> None:
        """Update email configuration for the user.
        
        Args:
            config_type: Type of configuration ('incoming', 'outgoing', 'escalation', or 'complete')
            config_data: Configuration data to update
        """
        try:
            if config_type == 'complete':
                # Update completion status
                db.collection('users').document(self.id).update({
                    'email_config_complete': True
                })
            elif config_type == 'escalation':
                # Update escalation email
                db.collection('users').document(self.id).update({
                    'escalation_email': config_data.get('escalation_email')
                })
            else:
                # Create a copy of the config data
                config_copy = config_data.copy()
                
                # Encrypt the password if it exists
                if 'password' in config_copy:
                    config_copy['password'] = encrypt_data(config_copy['password'])
                
                # Update specific email configuration
                config_field = f'email_config_{config_type}'
                db.collection('users').document(self.id).update({
                    config_field: config_copy
                })
        except Exception as e:
            print(f"Error updating email configuration: {str(e)}")
            raise

    def has_complete_email_config(self):
        """Check if user has complete email configuration"""
        user_doc = db.collection('users').document(self.id).get()
        if not user_doc.exists:
            return False
            
        user_data = user_doc.to_dict()
        return all([
            user_data.get('email_config_incoming'),
            user_data.get('email_config_outgoing'),
            user_data.get('escalation_email'),
            user_data.get('email_config_complete', False)
        ])

    def delete(self):
        """Delete the user and all associated data from Firebase"""
        if not self.id:
            return False
            
        try:
            # Delete user document and all subcollections
            user_ref = db.collection('users').document(self.id)
            
            # Delete templates
            templates = user_ref.collection('templates').stream()
            for template in templates:
                template.reference.delete()
                
            # Delete documents
            documents = user_ref.collection('documents').stream()
            for doc in documents:
                doc.reference.delete()
                
            # Delete email history
            emails = user_ref.collection('email_history').stream()
            for email in emails:
                email.reference.delete()
                
            # Delete admin feedback
            feedback = user_ref.collection('admin_feedback').stream()
            for fb in feedback:
                fb.reference.delete()
                
            # Finally delete the user document
            user_ref.delete()
            
            return True
        except Exception as e:
            print(f"Error deleting user: {str(e)}")
            return False