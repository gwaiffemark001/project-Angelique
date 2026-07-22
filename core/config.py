import os
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

# --- LLM Configuration ---
OLLAMA_URL = "http://localhost:11434/api/chat"
#OLLAMA_MODEL = "llama3.1"
# Change this line:
OLLAMA_MODEL = "qwen2.5-coder:7b" 

BLUESMINDS_API_KEY = os.getenv("BLUESMINDS_API_KEY", "")
BLUESMINDS_BASE_URL = os.getenv("BLUESMINDS_BASE_URL", "https://api.bluesminds.com/v1")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
API_PRIORITY = os.getenv("API_PRIORITY", "ollama,bluesminds,gemini").split(",")

# --- Database Configuration ---
DB_PATH = os.path.join("data", "angelique.db")