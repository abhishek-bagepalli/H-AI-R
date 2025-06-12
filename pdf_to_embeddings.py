import os
from typing import List, Dict
import PyPDF2
from langchain.text_splitter import CharacterTextSplitter
from langchain_openai import OpenAIEmbeddings
from langchain_chroma import Chroma
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class PDFProcessor:
    def __init__(self):
        """Initialize the PDF processor with OpenAI embeddings."""
        self.embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
        self.text_splitter = CharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200,
            separator="\n"
        )
        
    def extract_text_from_pdf(self, pdf_path: str) -> str:
        """Extract text content from a PDF file."""
        try:
            with open(pdf_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                text = ""
                for page in pdf_reader.pages:
                    # Extract text and clean it up
                    page_text = page.extract_text()
                    # Remove multiple newlines and spaces
                    page_text = ' '.join(page_text.split())
                    # Add a single newline between pages
                    text += page_text + "\n"
                return text.strip()
        except Exception as e:
            print(f"Error extracting text from PDF: {str(e)}")
            raise

    def create_embeddings(self, text: str) -> List[Dict]:
        """Create embeddings from text and return as a list of dictionaries."""
        try:
            # Split text into chunks
            chunks = self.text_splitter.split_text(text)
            print(f"Split text into {len(chunks)} chunks")
            print("\nFirst chunk preview:")
            print(chunks[0][:200] + "...")  # Show preview of first chunk
            
            # Create embeddings for each chunk
            embeddings = []
            for i, chunk in enumerate(chunks):
                print(f"Creating embedding for chunk {i+1}/{len(chunks)}")
                embedding = self.embeddings.embed_query(chunk)
                embeddings.append({
                    "text": chunk,
                    "embedding": embedding
                })
            
            return embeddings
        except Exception as e:
            print(f"Error creating embeddings: {str(e)}")
            raise

    def search_embeddings(self, query: str, embeddings: List[Dict], top_k: int = 3) -> List[Dict]:
        """Search through embeddings using a query string."""
        try:
            # Create query embedding
            query_embedding = self.embeddings.embed_query(query)
            
            # Calculate cosine similarity for each embedding
            results = []
            for doc in embeddings:
                similarity = self._cosine_similarity(query_embedding, doc["embedding"])
                results.append({
                    "text": doc["text"],
                    "similarity": similarity
                })
            
            # Sort by similarity and return top k results
            results.sort(key=lambda x: x["similarity"], reverse=True)
            return results[:top_k]
        except Exception as e:
            print(f"Error searching embeddings: {str(e)}")
            raise

    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """Calculate cosine similarity between two vectors."""
        import numpy as np
        dot_product = np.dot(vec1, vec2)
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)
        return dot_product / (norm1 * norm2)

def main():
    # Example usage
    processor = PDFProcessor()
    
    # Get PDF path from user
    pdf_path = "documents/job_inquiry.pdf"
    if not os.path.exists(pdf_path):
        print("File not found!")
        return
    
    try:
        # Extract text from PDF
        print("Extracting text from PDF...")
        text = processor.extract_text_from_pdf(pdf_path)
        print("Text extraction complete")
        
        # Create embeddings
        print("Creating embeddings...")
        embeddings = processor.create_embeddings(text)
        print("Embeddings created successfully")
        
        # Interactive search
        while True:
            query = input("\nEnter your search query (or 'quit' to exit): ")
            if query.lower() == 'quit':
                break
                
            print("\nSearching...")
            results = processor.search_embeddings(query, embeddings)
            
            print("\nTop results:")
            for i, result in enumerate(results, 1):
                print(f"\n{i}. Similarity: {result['similarity']:.4f}")
                print(f"Text: {result['text']}...")  # Show first 200 chars
                
    except Exception as e:
        print(f"An error occurred: {str(e)}")

if __name__ == "__main__":
    main() 