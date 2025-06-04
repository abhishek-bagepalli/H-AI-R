from cryptography.fernet import Fernet

# Generate a new Fernet key
key = Fernet.generate_key()

# Print the key in a format ready to copy to .env file
print("\nAdd this line to your .env file:")
print(f"ENCRYPTION_KEY={key.decode()}") 