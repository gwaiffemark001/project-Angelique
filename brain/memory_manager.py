import sqlite3
from pathlib import Path
from sentence_transformers import SentenceTransformer
import chromadb
from chromadb.config import Settings
from core import config

# 🔥 FORCE CPU to prevent CUDA errors on older GPUs
EMBEDDING_MODEL = SentenceTransformer('all-MiniLM-L6-v2', device="cpu")

# ChromaDB for vector storage
CHROMA_PATH = Path("data/chroma_memory")
CHROMA_PATH.mkdir(parents=True, exist_ok=True)

chroma_client = chromadb.Client(Settings(
    persist_directory=str(CHROMA_PATH),
    anonymized_telemetry=False
))

# Create or get the collection
memory_collection = chroma_client.get_or_create_collection(name="angelique_memory")

def get_connection():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS facts (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    ''')
    conn.commit()
    conn.close()

def save_fact_to_db(key: str, value: str):
    """Saves a fact to SQLite and also indexes it in the vector database."""
    init_db()
    conn = get_connection()
    conn.execute('INSERT OR REPLACE INTO facts (key, value) VALUES (?, ?)', (key, value))
    conn.commit()
    conn.close()
    
    # Also save to vector database for semantic search
    save_to_vector_db(key, value)

def save_to_vector_db(key: str, value: str):
    """Saves fact to ChromaDB with embeddings for semantic search."""
    combined_text = f"{key}: {value}"
    embedding = EMBEDDING_MODEL.encode(combined_text).tolist()
    
    memory_collection.upsert(
        ids=[f"fact_{key.replace(' ', '_').lower()}"],
        embeddings=[embedding],
        metadatas=[{"key": key, "value": value}],
        documents=[combined_text]
    )

def search_facts_in_db(query: str) -> dict:
    """Semantic search using vector embeddings."""
    query_embedding = EMBEDDING_MODEL.encode(query).tolist()
    
    results = memory_collection.query(
        query_embeddings=[query_embedding],
        n_results=5  # Return top 5 most relevant facts
    )
    
    if not results['metadatas'] or not results['metadatas'][0]:
        return {}
    
    facts = {}
    for metadata in results['metadatas'][0]:
        facts[metadata['key']] = metadata['value']
    
    return facts

def get_all_facts() -> dict:
    """Retrieve all facts from SQLite."""
    init_db()
    conn = get_connection()
    cursor = conn.execute('SELECT key, value FROM facts')
    facts = {row['key']: row['value'] for row in cursor.fetchall()}
    conn.close()
    return facts