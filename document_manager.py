import os
import json
from datetime import datetime
from typing import List, Dict, Optional
from firebase_config import db
from hr_tools import get_user_directories, ensure_user_directories
import PyPDF2
import io

class DocumentManager:
    def __init__(self, user_id: str):
        self.user_id = user_id
        self.directories = get_user_directories(user_id)
        ensure_user_directories(user_id)
        
    def _extract_text_from_pdf(self, file_content: bytes) -> str:
        """Extract text content from PDF bytes."""
        try:
            pdf_file = io.BytesIO(file_content)
            pdf_reader = PyPDF2.PdfReader(pdf_file)
            text = ""
            for page in pdf_reader.pages:
                text += page.extract_text() + "\n"
            return text
        except Exception as e:
            print(f"Error extracting text from PDF: {str(e)}")
            raise
            
    def upload_document(self, file_content: bytes, filename: str) -> bool:
        """Upload a document for the user.
        
        Args:
            file_content: The content of the file in bytes
            filename: The name of the file
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Ensure filename ends with .txt or .pdf
            if not (filename.endswith('.txt') or filename.endswith('.pdf')):
                print("Error: Only .txt and .pdf files are supported")
                return False
                
            # Extract text content based on file type
            if filename.endswith('.pdf'):
                text_content = self._extract_text_from_pdf(file_content)
            else:
                text_content = file_content.decode('utf-8')
                
            # Save the text content to a .txt file
            txt_filename = os.path.splitext(filename)[0] + '.txt'
            file_path = os.path.join(self.directories['documents'], txt_filename)
            
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(text_content)
                
            # Update document metadata in Firebase
            doc_ref = db.collection('users').document(self.user_id).collection('documents').document(txt_filename)
            doc_ref.set({
                'filename': txt_filename,
                'original_filename': filename,
                'upload_date': datetime.now().isoformat(),
                'file_path': file_path
            })
            
            return True
            
        except Exception as e:
            print(f"Error uploading document: {str(e)}")
            return False
            
    def delete_document(self, filename: str) -> bool:
        """Delete a document.
        
        Args:
            filename: The name of the file to delete
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            if not filename.endswith('.txt'):
                print("Error: Can only delete .txt files")
                return False
                
            file_path = os.path.join(self.directories['documents'], filename)
            
            # Delete file if it exists
            if os.path.exists(file_path):
                os.remove(file_path)
                
            # Delete document metadata from Firebase
            doc_ref = db.collection('users').document(self.user_id).collection('documents').document(filename)
            doc_ref.delete()
            
            return True
            
        except Exception as e:
            print(f"Error deleting document: {str(e)}")
            return False
            
    def list_documents(self) -> List[Dict[str, str]]:
        """List all documents for the user.
        
        Returns:
            List[Dict[str, str]]: List of document metadata
        """
        try:
            docs_ref = db.collection('users').document(self.user_id).collection('documents')
            docs = docs_ref.stream()
            
            documents = []
            for doc in docs:
                data = doc.to_dict()
                documents.append({
                    'filename': data.get('filename', ''),
                    'original_filename': data.get('original_filename', ''),
                    'upload_date': data.get('upload_date', ''),
                    'file_path': data.get('file_path', '')
                })
                
            return documents
            
        except Exception as e:
            print(f"Error listing documents: {str(e)}")
            return []
            
    def get_document_content(self, filename: str) -> Optional[str]:
        """Get the content of a document.
        
        Args:
            filename: The name of the file to read
            
        Returns:
            Optional[str]: The content of the file, or None if not found
        """
        try:
            if not filename.endswith('.txt'):
                print("Error: Can only read .txt files")
                return None
                
            file_path = os.path.join(self.directories['documents'], filename)
            
            if not os.path.exists(file_path):
                return None
                
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()
                
        except Exception as e:
            print(f"Error reading document: {str(e)}")
            return None
            
    def update_document(self, filename: str, new_content: str) -> bool:
        """Update the content of a document.
        
        Args:
            filename: The name of the file to update
            new_content: The new content to write
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            if not filename.endswith('.txt'):
                print("Error: Can only update .txt files")
                return False
                
            file_path = os.path.join(self.directories['documents'], filename)
            
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(new_content)
                
            # Update last modified timestamp in Firebase
            doc_ref = db.collection('users').document(self.user_id).collection('documents').document(filename)
            doc_ref.update({
                'last_modified': datetime.now().isoformat()
            })
            
            return True
            
        except Exception as e:
            print(f"Error updating document: {str(e)}")
            return False 