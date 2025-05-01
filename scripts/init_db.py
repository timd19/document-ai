import os  
import sys  
from sqlalchemy import create_engine  
from sqlalchemy.orm import sessionmaker  
import time  

# Add the parent directory to the Python path  
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  

from backend.db.database import Base  
from backend.db.models import Document, ChatHistory  

def init_db():  
    # Get database URL from environment variables  
    database_url = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@db:5432/docai")  
    
    # Create SQLAlchemy engine and session  
    engine = None  
    max_retries = 30  
    retry_interval = 2  
    
    # Wait for PostgreSQL to be ready  
    for i in range(max_retries):  
        try:  
            engine = create_engine(database_url)  
            engine.connect()  
            break  
        except Exception as e:  
            print(f"Database connection attempt {i+1}/{max_retries} failed: {e}")  
            if i < max_retries - 1:  
                print(f"Retrying in {retry_interval} seconds...")  
                time.sleep(retry_interval)  
            else:  
                print("Failed to connect to the database after multiple attempts.")  
                raise  
    
    # Create tables  
    Base.metadata.create_all(bind=engine)  
    print("Database tables created successfully.")  

if __name__ == "__main__":  
    init_db()