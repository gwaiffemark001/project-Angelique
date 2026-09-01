import hashlib
import sqlite3
import uuid
from pathlib import Path
from core import config
from core.local_ai_router import get_local_router

# --- Optional Heavy Dependencies ---
try:
    import numpy as np
except Exception as e:
    print(f"⚠️ [Memory] numpy import failed: {e}")
    np = None

try:
    from sentence_transformers import SentenceTransformer
except Exception as e:
    print(f"⚠️ [Memory] sentence-transformers import failed: {e}")
    SentenceTransformer = None

try:
    import chromadb
    from chromadb.config import Settings
    from chromadb.utils import embedding_functions
except Exception as e:
    print(f"⚠️ [Memory] chromadb import failed: {e}")
    chromadb = None
    Settings = None
    embedding_functions = None

DEVICE = "cpu"
EMBEDDING_DIM = int(getattr(config, "MEMORY_EMBEDDING_DIM", 768))
EMBEDDING_MODEL = None
_chroma_client = None
_memory_collection = None

class HashFallbackEmbeddingModel:
    """Deterministic fallback embedding model for offline ChromaDB persistence."""

    def __init__(self, dim: int = EMBEDDING_DIM):
        self.dim = dim

    def encode(self, texts):
        if isinstance(texts, str):
            texts = [texts]
        vectors = []
        for text in texts:
            if text is None:
                text = ""
            digest = hashlib.sha256(text.encode("utf-8")).digest()
            arr = np.frombuffer(digest, dtype=np.uint8).astype(np.float32)
            if arr.size < self.dim:
                repeat_count = int(np.ceil(self.dim / arr.size))
                arr = np.tile(arr, repeat_count)
            arr = arr[: self.dim]
            arr = arr - 128.0
            norm = np.linalg.norm(arr)
            if norm == 0.0:
                norm = 1.0
            vectors.append(arr / norm)
        return np.vstack(vectors)

class EmbeddingModelAdapter:
    def __init__(self, impl):
        self.impl = impl

    def encode(self, texts):
        if isinstance(texts, str):
            texts = [texts]
        if hasattr(self.impl, "encode"):
            result = self.impl.encode(texts)
        else:
            result = self.impl(texts)
        return np.asarray(result, dtype=np.float32)

# --- Lazy Loading for Embedding Model ---
def _onnx_model_available() -> bool:
    if embedding_functions is None:
        return False
    try:
        model_cls = embedding_functions.ONNXMiniLM_L6_V2
        cache_dir = Path(model_cls.DOWNLOAD_PATH) / model_cls.EXTRACTED_FOLDER_NAME
        return (cache_dir / "model.onnx").exists()
    except Exception:
        return False


def _get_embedding_model():
    global EMBEDDING_MODEL
    if EMBEDDING_MODEL is not None:
        return EMBEDDING_MODEL

    # Prefer the installed Nomic model through Angelique's local tri-model
    # router. This keeps semantic search local and uses the model the user
    # actually installed instead of silently downloading another encoder.
    try:
        router = get_local_router()
        state = router.discover_models()
        if state.embedder:
            class _NomicAdapter:
                def encode(self, texts):
                    values = [texts] if isinstance(texts, str) else list(texts)
                    vectors = router.embed(values)
                    if not vectors:
                        raise RuntimeError("Nomic embedding request failed")
                    return np.asarray(vectors, dtype=np.float32)[0] if isinstance(texts, str) else np.asarray(vectors, dtype=np.float32)
            EMBEDDING_MODEL = _NomicAdapter()
            return EMBEDDING_MODEL
    except Exception as e:
        print(f"[Memory] Nomic router embedding unavailable; using local fallback: {e}")

    if SentenceTransformer is not None:
        try:
            model = SentenceTransformer('all-MiniLM-L6-v2', device=DEVICE)
            EMBEDDING_MODEL = EmbeddingModelAdapter(model)
            return EMBEDDING_MODEL
        except Exception as e:
            print(f"⚠️ [Memory] SentenceTransformer load failed: {e}")

    if chromadb is not None and embedding_functions is not None:
        try:
            st_impl = embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name='all-MiniLM-L6-v2', device=DEVICE
            )
            EMBEDDING_MODEL = EmbeddingModelAdapter(st_impl)
            return EMBEDDING_MODEL
        except Exception as e:
            print(f"⚠️ [Memory] chromadb SentenceTransformerEmbeddingFunction failed: {e}")

        if _onnx_model_available():
            try:
                onnx_impl = embedding_functions.ONNXMiniLM_L6_V2()
                EMBEDDING_MODEL = EmbeddingModelAdapter(onnx_impl)
                return EMBEDDING_MODEL
            except Exception as e:
                print(f"⚠️ [Memory] ONNXMiniLM_L6_V2 load failed: {e}")
        else:
            print("⚠️ [Memory] ONNXMiniLM_L6_V2 skipped because no local ONNX model is cached.")

    if np is not None:
        EMBEDDING_MODEL = HashFallbackEmbeddingModel(dim=EMBEDDING_DIM)
        return EMBEDDING_MODEL

    print("⚠️ [Memory] No embedding model available for ChromaDB. Vector persistence disabled.")
    return None

# --- Lazy Loading for ChromaDB (Uses Absolute Path from Config) ---
def _get_memory_collection():
    global _chroma_client, _memory_collection
    if _memory_collection is not None:
        return _memory_collection
    if chromadb is None or Settings is None:
        return None

    path = Path(config.CHROMA_DB_PATH)
    path.mkdir(parents=True, exist_ok=True)
    try:
        _chroma_client = chromadb.Client(Settings(
            persist_directory=str(path),
            is_persistent=True,
            anonymized_telemetry=False,
        ))
        _memory_collection = _chroma_client.get_or_create_collection(name=getattr(config, "MEMORY_SEMANTIC_COLLECTION_NAME", config.MEMORY_COLLECTION_NAME))
        print(f"✅ [Memory] ChromaDB initialized at {path}")
    except Exception as e:
        print(f"⚠️ [Memory] ChromaDB init failed: {e}")
        _memory_collection = None
    return _memory_collection

# --- SQLite Functions ---
def get_connection():
    Path(config.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    conn.execute('''CREATE TABLE IF NOT EXISTS memory_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        entity TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL,
        is_active INTEGER DEFAULT 1, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_entity_key_active ON memory_log(entity, key, is_active)')
    try: conn.execute("ALTER TABLE memory_log ADD COLUMN importance_score INTEGER DEFAULT 5")
    except sqlite3.OperationalError: pass
    try: conn.execute("ALTER TABLE memory_log ADD COLUMN context TEXT DEFAULT ''")
    except sqlite3.OperationalError: pass
    conn.commit()
    conn.close()

def get_top_memory_facts(min_importance: int = 8, limit: int = 5) -> list:
    init_db()
    conn = get_connection()
    cursor = conn.execute('''
        SELECT entity, key, value, importance_score, context
        FROM memory_log WHERE is_active = 1 AND importance_score >= ?
        ORDER BY importance_score DESC, timestamp DESC LIMIT ?
    ''', (min_importance, limit))
    facts = []
    for row in cursor.fetchall():
        fact = dict(row)
        fact["importance"] = fact.get("importance_score", fact.get("importance", 5))
        facts.append(fact)
    conn.close()
    return facts

def save_fact_to_db(entity: str, key: str, value: str, importance: int = 5, context: str = ""):
    init_db()
    conn = get_connection()
    conn.execute('UPDATE memory_log SET is_active = 0 WHERE entity = ? AND key = ? AND is_active = 1', (entity, key))
    conn.execute('INSERT INTO memory_log (entity, key, value, is_active, importance_score, context) VALUES (?, ?, ?, 1, ?, ?)', (entity, key, value, importance, context))
    conn.commit()
    conn.close()
    
    print(f"💾 [Memory] SAVED to SQLite: {entity} -> {key} = '{value}' (Importance: {importance})")
    save_to_vector_db(entity, key, value, importance, context)

def save_conversation_memory(session_id: str, role: str, text: str, importance: int = 5, context: str = "conversation"):
    if not text or not isinstance(text, str):
        return
    save_to_vector_db(role, "conversation", text, importance, context, item_type="conversation", session_id=session_id)

# --- ChromaDB Vector Functions ---
def save_to_vector_db(entity: str, key: str, value: str, importance: int = 5, context: str = "", item_type: str = "fact", session_id: str = None):
    model = _get_embedding_model()
    col = _get_memory_collection()
    if model is None or col is None:
        return
    try:
        if item_type == "conversation":
            combined_text = value
            doc_id = f"conversation_{session_id or 'unknown'}_{uuid.uuid4().hex}"
            metadata = {"entity": entity, "key": key, "value": value, "importance": importance, "context": context, "type": "conversation", "session_id": session_id or "unknown"}
        else:
            combined_text = f"{entity}'s {key} is {value}. Context: {context}"
            doc_id = f"fact_{entity.lower()}_{key.replace(' ', '_').lower()}_{int(importance)}"
            metadata = {"entity": entity, "key": key, "value": value, "importance": importance, "context": context, "type": "fact"}

        # Entity tags are part of the embedded text so semantic retrieval has
        # a hard lexical identity anchor in addition to metadata filtering.
        if item_type != "conversation":
            try:
                combined_text = get_local_router().tagged_fact(entity, key, value, context)
            except Exception:
                pass
        embedding = model.encode(combined_text)
        if hasattr(embedding, "tolist"):
            embedding = embedding.tolist()

        if not isinstance(embedding, list):
            embedding = [embedding]

        if isinstance(embedding[0], (int, float)):
            embeddings = [embedding]
        else:
            embeddings = embedding

        col.upsert(
            ids=[doc_id],
            embeddings=embeddings,
            metadatas=[metadata],
            documents=[combined_text],
        )
        print(f"✅ [Memory] SAVED to ChromaDB: {key}")
    except Exception as e:
        print(f"❌ [Memory] ChromaDB save failed: {e}")

def search_memory(query: str, top_k: int = 5, include_conversation: bool = True, entity: str | None = None) -> list:
    col = _get_memory_collection()
    if col is None:
        return []
    try:
        model = _get_embedding_model()
        if model is None:
            return []

        query_embedding = model.encode(query)
        if hasattr(query_embedding, "tolist"):
            query_embedding = query_embedding.tolist()

        if isinstance(query_embedding, list) and len(query_embedding) == 1 and isinstance(query_embedding[0], list):
            query_embedding = query_embedding[0]

        where = None
        if entity:
            where = {"entity": str(entity).strip()}
        results = col.query(query_embeddings=[query_embedding], n_results=top_k * 2, where=where) if where else col.query(query_embeddings=[query_embedding], n_results=top_k * 2)
        
        formatted = []
        if results and results.get("metadatas"):
            for metadata_list in results["metadatas"]:
                for metadata in metadata_list:
                    formatted.append(dict(metadata))
        formatted.sort(key=lambda x: x.get("importance", 5), reverse=True)
        
        if include_conversation:
            return formatted[:top_k]
        return [item for item in formatted if item.get("type") == "fact"][:top_k]
    except Exception as e:
        print(f"⚠️ [Memory] Search failed: {e}")
        return []

def search_conversation_memory(query: str, top_k: int = 3) -> list:
    return [item for item in search_memory(query, top_k=top_k * 2, include_conversation=True) if item.get("type") == "conversation"][:top_k]

def semantic_search(query: str, top_k: int = 5) -> list:
    return search_memory(query, top_k=top_k, include_conversation=False)


# -- Explicit, clear wrappers to separate conversation vs fact memory queries --
def query_conversation_memory(query: str, top_k: int = 5) -> list:
    """Query conversation memory only (explicit wrapper)."""
    return search_conversation_memory(query, top_k=top_k)


def query_fact_memory(query: str, top_k: int = 5, entity: str | None = None) -> list:
    """Query fact/knowledge memory only (explicit wrapper)."""
    return search_memory(query, top_k=top_k, include_conversation=False, entity=entity)


def save_fact(entity: str, key: str, value: str, importance: int = 5, context: str = "") -> None:
    """Helper to save a fact to both SQLite and vector DB (explicit API)."""
    save_fact_to_db(entity, key, value, importance, context)

# --- Entity Lookup (Fixed Syntax & Keys) ---
def get_facts_for_entity(entity: str) -> dict:
    init_db()
    conn = get_connection()
    current_cursor = conn.execute('''
        SELECT key, value, importance_score, context, timestamp 
        FROM memory_log WHERE entity = ? AND is_active = 1
        ORDER BY importance_score DESC
    ''', (entity,))
    current_facts = []
    for row in current_cursor.fetchall():
        fact = dict(row)
        fact["importance"] = fact.get("importance_score", fact.get("importance", 5))
        current_facts.append(fact)
    
    history_cursor = conn.execute('''
        SELECT key, value, timestamp FROM memory_log 
        WHERE entity = ? AND is_active = 0 ORDER BY timestamp DESC
    ''', (entity,))
    history_facts = [f"{row['key']} was {row['value']} (on {row['timestamp']})" for row in history_cursor.fetchall()]
    conn.close()
    
    # NO TRAILING SPACES IN KEYS
    return {"current": current_facts, "history": history_facts}