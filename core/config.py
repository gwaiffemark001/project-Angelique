import os
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    print("⚠️ [Config] python-dotenv is not installed; environment variables will be read from the system environment only.")

# --- LLM Configuration ---
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
PRIMARY_MODEL = os.getenv("PRIMARY_MODEL", "llama3.1")
CODER_MODEL = os.getenv("CODER_MODEL", "qwen2.5-coder:7b")

BLUESMINDS_API_KEY = os.getenv("BLUESMINDS_API_KEY", "")
BLUESMINDS_BASE_URL = os.getenv("BLUESMINDS_BASE_URL", "https://api.bluesminds.com/v1")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")

NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY", "")

API_PRIORITY = os.getenv("API_PRIORITY", "openrouter,nvidia,bluesminds,gemini,ollama").split(",")

# --- MT5 Bridge / Trading Configuration ---
MT5_BRIDGE_HOST = os.getenv("ANGELIQUE_MT5_BRIDGE_HOST", "127.0.0.1")
MT5_BRIDGE_PORT = int(os.getenv("ANGELIQUE_MT5_BRIDGE_PORT", "10001"))
MT5_BRIDGE_CONNECT_TIMEOUT = float(os.getenv("ANGELIQUE_MT5_CONNECT_TIMEOUT", "10.0"))
MT5_BRIDGE_RECONNECT_INTERVAL = float(os.getenv("ANGELIQUE_MT5_RECONNECT_INTERVAL", "1.0"))
MT5_BRIDGE_HEALTH_CHECK_INTERVAL = float(os.getenv("ANGELIQUE_MT5_HEALTH_CHECK_INTERVAL", "5.0"))

TRADING_MIN_FREE_MARGIN = float(os.getenv("ANGELIQUE_TRADING_MIN_FREE_MARGIN", "100.0"))
TRADING_MIN_RR_RATIO = float(os.getenv("ANGELIQUE_TRADING_MIN_RR_RATIO", "2.0"))
TRADING_MAX_SPREAD = float(os.getenv("ANGELIQUE_TRADING_MAX_SPREAD", "3.0"))
TRADING_CONFIDENCE_THRESHOLD = float(os.getenv("ANGELIQUE_TRADING_CONFIDENCE_THRESHOLD", "80.0"))
TRADING_RSI_MIN = float(os.getenv("ANGELIQUE_TRADING_RSI_MIN", "30.0"))
TRADING_RSI_MAX = float(os.getenv("ANGELIQUE_TRADING_RSI_MAX", "70.0"))
TRADING_EMA_FAST = int(os.getenv("ANGELIQUE_TRADING_EMA_FAST", "50"))
TRADING_EMA_SLOW = int(os.getenv("ANGELIQUE_TRADING_EMA_SLOW", "200"))
TRADING_RSI_PERIOD = int(os.getenv("ANGELIQUE_TRADING_RSI_PERIOD", "14"))
TRADING_ATR_PERIOD = int(os.getenv("ANGELIQUE_TRADING_ATR_PERIOD", "14"))
TRADING_BBANDS_PERIOD = int(os.getenv("ANGELIQUE_TRADING_BBANDS_PERIOD", "20"))
TRADING_DEFAULT_RISK_PERCENT = float(os.getenv("ANGELIQUE_TRADING_DEFAULT_RISK_PERCENT", "1.0"))

# --- Database Configuration ---
DB_PATH = os.path.join("data", "angelique.db")