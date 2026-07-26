# brain/memory_manager.py
import sqlite3
from pathlib import Path
from core import config

# Optional heavy dependencies: fall back to SQLite-only behavior if they cannot be imported.
try:
    from sentence_transformers import SentenceTransformer
except Exception as e:
    print(f"⚠️ [Memory] sentence_transformers not found: {e}")
    SentenceTransformer = None

try:
    import chromadb
    from chromadb.config import Settings
except Exception as e:
    print(f"⚠️ [Memory] ChromaDB not installed or unavailable: {e}")
    chromadb = None
    Settings = None

try:
    import torch  # noqa: F401
except Exception:
    torch = None

# Force CPU to prevent CUDA errors on older GPUs
DEVICE = "cpu"
EMBEDDING_MODEL = None

# Defer instantiation of SentenceTransformer until needed to avoid heavy imports at startup
def _get_embedding_model():
    global EMBEDDING_MODEL
    if EMBEDDING_MODEL is None and SentenceTransformer is not None:
        try:
            EMBEDDING_MODEL = SentenceTransformer('all-MiniLM-L6-v2', device=DEVICE)
        except Exception:
            EMBEDDING_MODEL = None
    return EMBEDDING_MODEL

CHROMA_PATH = Path("data/chroma_memory")
CHROMA_PATH.mkdir(parents=True, exist_ok=True)

memory_collection = None
chroma_client = None
if chromadb is not None and Settings is not None:
    try:
        chroma_client = chromadb.Client(Settings(
            persist_directory=str(CHROMA_PATH),
            anonymized_telemetry=False
        ))
        memory_collection = chroma_client.get_or_create_collection(name="angelique_memory")
    except Exception as e:
        print(f"⚠️ [Memory] Failed to initialize ChromaDB: {e}")
        chroma_client = None
        memory_collection = None
else:
    print("⚠️ [Memory] Skipping ChromaDB initialization because the dependency is unavailable.")

def get_connection():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    # 1. Create base table
    conn.execute('''
        CREATE TABLE IF NOT EXISTS memory_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity TEXT NOT NULL,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            is_active INTEGER DEFAULT 1,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_entity_key_active ON memory_log(entity, key, is_active)')
    
    # 2. SAFE MIGRATION: Add new columns for Episodic & Emotional memory if they don't exist
    try:
        conn.execute("ALTER TABLE memory_log ADD COLUMN importance_score INTEGER DEFAULT 5")
    except sqlite3.OperationalError:
        pass  # Column already exists
    
    try:
        conn.execute("ALTER TABLE memory_log ADD COLUMN context TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass  # Column already exists
        
    conn.commit()
    conn.close()

def save_fact_to_db(entity: str, key: str, value: str, importance: int = 5, context: str = ""):
    """Archives old facts and saves the new one as active, with emotional/episodic metadata."""
    init_db()
    conn = get_connection()
    
    # 1. Archive all previous active facts for this entity and key
    conn.execute('''
        UPDATE memory_log 
        SET is_active = 0 
        WHERE entity = ? AND key = ? AND is_active = 1
    ''', (entity, key))
    
    # 2. Insert the new active fact with importance and context
    conn.execute('''
        INSERT INTO memory_log (entity, key, value, is_active, importance_score, context) 
        VALUES (?, ?, ?, 1, ?, ?)
    ''', (entity, key, value, importance, context))
    
    conn.commit()
    conn.close()
    
    # Update vector DB
    save_to_vector_db(entity, key, value, importance, context)

def save_to_vector_db(entity: str, key: str, value: str, importance: int = 5, context: str = ""):
    """Save fact to ChromaDB for semantic search."""
    model = _get_embedding_model()
    if model is None or memory_collection is None:
        return

    try:
        combined_text = f"{entity}'s {key} is {value}. Context: {context}"
        embedding = model.encode(combined_text).tolist()

        memory_collection.upsert(
            ids=[f"fact_{entity.lower()}_{key.replace(' ', '_').lower()}_{int(importance)}"],
            embeddings=[embedding],
            metadatas={
                "entity": entity,
                "key": key,
                "value": value,
                "importance": importance,
                "context": context
            },
            documents=[combined_text]
        )
    except Exception as e:
        print(f"⚠️ [Memory] Vector storage failed: {e}")
        return

def semantic_search(query: str, top_k: int = 5) -> list[dict]:
    """
    Search memory semantically using ChromaDB.
    Returns list of matching facts sorted by importance.
    """
    if memory_collection is None:
        return []

    try:
        model = _get_embedding_model()
        if model is None:
            return []

        query_embedding = model.encode(query).tolist()
        results = memory_collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k
        )

        formatted_results = []
        if results and results.get("metadatas"):
            for metadata_list in results["metadatas"]:
                for metadata in metadata_list:
                    formatted_results.append({
                        "entity": metadata.get("entity"),
                        "key": metadata.get("key"),
                        "value": metadata.get("value"),
                        "importance": metadata.get("importance", 5),
                        "context": metadata.get("context", "")
                    })

        # Sort by importance descending
        formatted_results.sort(key=lambda x: x.get("importance", 5), reverse=True)
        return formatted_results[:top_k]
    except Exception as e:
        print(f"⚠️ [Memory] Semantic search failed: {e}")
        return []

def get_facts_for_entity(entity: str) -> dict:
    """Retrieves current and historical facts, sorted by importance."""
    init_db()
    conn = get_connection()
    
    # Get current active facts (Ordered by importance descending)
    current_cursor = conn.execute('''
        SELECT key, value, importance_score, context, timestamp 
        FROM memory_log 
        WHERE entity = ? AND is_active = 1
        ORDER BY importance_score DESC
    ''', (entity,))
    
    current_facts = []
    for row in current_cursor.fetchall():
        current_facts.append({
            "key": row['key'],
            "value": row['value'],
            "importance": row['importance_score'],
            "context": row['context'],
            "timestamp": row['timestamp']
        })

    # Get historical (archived) facts
    history_cursor = conn.execute('''
        SELECT key, value, timestamp FROM memory_log 
        WHERE entity = ? AND is_active = 0
        ORDER BY timestamp DESC
    ''', (entity,))
    history_facts = [f"{row['key']} was {row['value']} (on {row['timestamp']})" for row in history_cursor.fetchall()]
    
    conn.close()
    return {"current": current_facts, "history": history_facts}