import os
from typing import List, Dict, Optional
import PyPDF2
from langchain.text_splitter import CharacterTextSplitter
from langchain_openai import OpenAIEmbeddings
from firebase_admin import storage, firestore
from datetime import datetime
import uuid
from io import BytesIO

class DocumentStorage:
    def __init__(self, user_id: str):
        """Initialize document storage for a specific user."""
        self.user_id = user_id
        self.embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
        self.text_splitter = CharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200,
            separator="\n"
        )
        self.db = firestore.client()
        self.bucket = storage.bucket()

    def process_and_store_document(self, file_content: bytes, filename: str, category: str) -> Dict:
        """Process a document and store it in Firebase."""
        try:
            # Validate file extension
            if not filename.lower().endswith('.pdf'):
                raise ValueError("Only PDF files are supported")
            
            # Generate unique document ID
            doc_id = str(uuid.uuid4())
            
            # Extract text from PDF
            text = self._extract_text_from_pdf(file_content)
            
            # Split text into chunks
            chunks = self.text_splitter.split_text(text)
            
            # Create embeddings for each chunk
            embeddings_data = []
            for i, chunk in enumerate(chunks):
                embedding = self.embeddings.embed_query(chunk)
                embeddings_data.append({
                    "text": chunk,
                    "embedding": embedding,
                    "chunk_index": i
                })
            
            # Store original document in Firebase Storage with original filename
            storage_path = f"users/{self.user_id}/documents/{doc_id}/{filename}"
            blob = self.bucket.blob(storage_path)
            blob.upload_from_string(file_content, content_type='application/pdf')
            
            # Store embeddings in Firestore
            embeddings_ref = self.db.collection('users').document(self.user_id).collection('embeddings')
            for embedding_data in embeddings_data:
                embeddings_ref.add({
                    "document_id": doc_id,
                    "filename": filename,
                    "text": embedding_data["text"],
                    "embedding": embedding_data["embedding"],
                    "chunk_index": embedding_data["chunk_index"],
                    "created_at": datetime.now(),
                    "category": category
                })
            
            # Store document metadata
            doc_ref = self.db.collection('users').document(self.user_id).collection('documents').document(doc_id)
            doc_ref.set({
                "filename": filename,
                "storage_path": storage_path,
                "chunk_count": len(chunks),
                "created_at": datetime.now(),
                "status": "processed",
                "file_type": "pdf",
                "category": category
            })
            
            return {
                "document_id": doc_id,
                "filename": filename,
                "chunk_count": len(chunks),
                "category": category
            }
            
        except Exception as e:
            print(f"Error processing document: {str(e)}")
            raise

    def search_documents(self, query: str, top_k: int = 3) -> List[Dict]:
        """Search through stored documents using a query string."""
        try:
            # Create query embedding
            query_embedding = self.embeddings.embed_query(query)
            
            # Get all embeddings for the user
            embeddings_ref = self.db.collection('users').document(self.user_id).collection('embeddings')
            embeddings = embeddings_ref.stream()
            
            # Calculate similarity for each embedding
            results = []
            for doc in embeddings:
                doc_data = doc.to_dict()
                similarity = self._cosine_similarity(query_embedding, doc_data["embedding"])
                results.append({
                    "document_id": doc_data["document_id"],
                    "filename": doc_data["filename"],
                    "text": doc_data["text"],
                    "similarity": similarity,
                    "chunk_index": doc_data["chunk_index"]
                })
            
            # Sort by similarity and return top k results
            results.sort(key=lambda x: x["similarity"], reverse=True)
            return results[:top_k]
            
        except Exception as e:
            print(f"Error searching documents: {str(e)}")
            raise

    def _extract_text_from_pdf(self, file_content: bytes) -> str:
        """Extract text content from PDF bytes."""
        try:
            # Create a BytesIO object from the bytes
            pdf_file = BytesIO(file_content)
            
            # Use BytesIO object with PdfReader
            pdf_reader = PyPDF2.PdfReader(pdf_file)
            text = ""
            for page in pdf_reader.pages:
                page_text = page.extract_text()
                # Clean up text
                page_text = ' '.join(page_text.split())
                text += page_text + "\n"
            return text.strip()
        except Exception as e:
            print(f"Error extracting text from PDF: {str(e)}")
            raise

    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """Calculate cosine similarity between two vectors."""
        import numpy as np
        dot_product = np.dot(vec1, vec2)
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)
        return dot_product / (norm1 * norm2)

    def get_document(self, document_id: str) -> Optional[Dict]:
        """Retrieve document metadata and content."""
        try:
            # Get document metadata
            doc_ref = self.db.collection('users').document(self.user_id).collection('documents').document(document_id)
            doc = doc_ref.get()
            
            if not doc.exists:
                return None
                
            doc_data = doc.to_dict()
            
            # Get document content from Storage
            blob = self.bucket.blob(doc_data["storage_path"])
            content = blob.download_as_bytes()
            
            return {
                "metadata": doc_data,
                "content": content
            }
            
        except Exception as e:
            print(f"Error retrieving document: {str(e)}")
            raise

    def delete_document(self, document_id: str) -> bool:
        """Delete a document and its associated data."""
        try:
            # Get document metadata
            doc_ref = self.db.collection('users').document(self.user_id).collection('documents').document(document_id)
            doc = doc_ref.get()
            
            if not doc.exists:
                return False
                
            doc_data = doc.to_dict()
            
            # Delete from Storage
            blob = self.bucket.blob(doc_data["storage_path"])
            blob.delete()
            
            # Delete embeddings
            embeddings_ref = self.db.collection('users').document(self.user_id).collection('embeddings')
            embeddings = embeddings_ref.where("document_id", "==", document_id).stream()
            for embedding in embeddings:
                embedding.reference.delete()
            
            # Delete document metadata
            doc_ref.delete()
            
            return True
            
        except Exception as e:
            print(f"Error deleting document: {str(e)}")
            raise 