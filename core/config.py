import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    # Avoid printing non-ASCII characters when running under Wine's default
    # ANSI codepage to prevent UnicodeEncodeError observed in bridge startup.
    try:
        print("[Config] python-dotenv is not installed; environment variables will be read from the system environment only.")
    except Exception:
        # If printing still fails, silently continue — env vars can be provided
        # via the host environment or installed into Wine's Python.
        pass

# --- Project Root & Directories (ABSOLUTE PATHS) ---
DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# --- LLM Configuration ---
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_REQUEST_TIMEOUT_S = float(os.getenv("OLLAMA_REQUEST_TIMEOUT_S", "8"))
PRIMARY_MODEL = os.getenv("PRIMARY_MODEL", "qwen2.5:3b")
CODER_MODEL = os.getenv("CODER_MODEL", "qwen2.5-coder:7b")
LOCAL_FALLBACK_MODEL = os.getenv("LOCAL_FALLBACK_MODEL", "qwen2.5:3b")

BLUESMINDS_API_KEY = os.getenv("BLUESMINDS_API_KEY", "")
BLUESMINDS_BASE_URL = os.getenv("BLUESMINDS_BASE_URL", "https://api.bluesminds.com/v1")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY", "")
NVIDIA_API_URL = os.getenv("NVIDIA_API_URL", "https://integrate.api.nvidia.com/v1/chat/completions")
API_PRIORITY = os.getenv("API_PRIORITY", "openrouter,nvidia,bluesminds,gemini,ollama").split(",")
FOREX_FACTORY_URLS = [s.strip() for s in os.getenv("FOREX_FACTORY_URLS", "https://www.forexfactory.com/ffcal/calendar.php,https://www.forexfactory.com/calendar/").split(",") if s.strip()]
FOREX_FACTORY_BASE_URL = os.getenv("FOREX_FACTORY_BASE_URL", "https://www.forexfactory.com")
WHATSAPP_API_URL = os.getenv("WHATSAPP_API_URL", "")
WHATSAPP_API_TOKEN = os.getenv("WHATSAPP_API_TOKEN", "")
WHATSAPP_PROVIDER = os.getenv("WHATSAPP_PROVIDER", "meta")
WHATSAPP_GRAPH_VERSION = os.getenv("WHATSAPP_GRAPH_VERSION", "v23.0")
WHATSAPP_ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
WHATSAPP_CONTACTS_FILE = Path(os.getenv("WHATSAPP_CONTACTS_FILE", str(PROJECT_ROOT / "skills" / "messaging" / "contacts.csv")))
if not WHATSAPP_CONTACTS_FILE.is_absolute(): WHATSAPP_CONTACTS_FILE = (PROJECT_ROOT / WHATSAPP_CONTACTS_FILE).resolve()
# By default do not use Playwright automation unless explicitly enabled

# --- MT5 Bridge / Trading Configuration ---
MT5_BRIDGE_HOST_ENV = os.getenv("ANGELIQUE_MT5_BRIDGE_HOST_ENV", "ANGELIQUE_MT5_BRIDGE_HOST")
MT5_BRIDGE_PORT_ENV = os.getenv("ANGELIQUE_MT5_BRIDGE_PORT_ENV", "ANGELIQUE_MT5_BRIDGE_PORT")
MT5_BRIDGE_FD_ENV = os.getenv("ANGELIQUE_MT5_BRIDGE_FD_ENV", "ANGELIQUE_MT5_BRIDGE_FD")
MT5_BRIDGE_HOST = os.getenv(MT5_BRIDGE_HOST_ENV, "127.0.0.1")
MT5_BRIDGE_PORT = int(os.getenv(MT5_BRIDGE_PORT_ENV, "10011"))
MT5_BRIDGE_RESERVED_PORTS = [int(p.strip()) for p in os.getenv("ANGELIQUE_MT5_BRIDGE_RESERVED_PORTS", "10011").split(",") if p.strip().isdigit()]
TRADING_VALETAX_BRIDGE_PORT = int(os.getenv("ANGELIQUE_VALETAX_BRIDGE_PORT", "10011"))
MT5_BRIDGE_LAUNCHER = os.getenv("ANGELIQUE_MT5_BRIDGE_LAUNCHER", "wine cmd /c python")
MT5_WINE_PREFIX = os.getenv("ANGELIQUE_MT5_WINE_PREFIX", "")
MT5_BRIDGE_CONNECT_TIMEOUT = float(os.getenv("ANGELIQUE_MT5_CONNECT_TIMEOUT", "10.0"))
MT5_BRIDGE_RECONNECT_INTERVAL = float(os.getenv("ANGELIQUE_MT5_RECONNECT_INTERVAL", "1.0"))
MT5_BRIDGE_HEALTH_CHECK_INTERVAL = float(os.getenv("ANGELIQUE_MT5_HEALTH_CHECK_INTERVAL", "5.0"))

TRADING_MIN_FREE_MARGIN = float(os.getenv("ANGELIQUE_TRADING_MIN_FREE_MARGIN", "0.0"))
TRADING_MIN_FREE_MARGIN_PERCENT = float(os.getenv("TRADING_MIN_FREE_MARGIN_PERCENT", "10.0"))
# Canonical account-equity risk policy: every trade targets 1% and may never exceed 1%.
TRADING_RISK_PER_TRADE_PERCENT = 1.0
TRADING_MAX_RISK_PERCENT = 1.0
TRADING_DAILY_LOSS_LIMIT_PERCENT = float(os.getenv("TRADING_DAILY_LOSS_LIMIT_PERCENT", "2.0"))
TRADING_WEEKLY_LOSS_LIMIT_PERCENT = float(os.getenv("TRADING_WEEKLY_LOSS_LIMIT_PERCENT", "5.0"))
TRADING_MIN_RR = float(os.getenv("TRADING_MIN_RR", "2.5"))
TRADING_PREFERRED_RR = float(os.getenv("TRADING_PREFERRED_RR", "3.0"))
TRADING_MAX_SIMULTANEOUS_TRADES = int(os.getenv("TRADING_MAX_SIMULTANEOUS_TRADES", "1"))
TRADING_STRICT_SHARED_CURRENCY_BLOCK = os.getenv("TRADING_STRICT_SHARED_CURRENCY_BLOCK", "true").lower() in ("1", "true", "yes")
TRADING_CORRELATION_CHECK_ENABLED = os.getenv("TRADING_CORRELATION_CHECK_ENABLED", "true").lower() in ("1", "true", "yes")
TRADING_CORRELATION_LOOKBACK = int(os.getenv("TRADING_CORRELATION_LOOKBACK", "100"))
TRADING_CORRELATION_THRESHOLD = float(os.getenv("TRADING_CORRELATION_THRESHOLD", "0.75"))
TRADING_MAX_METAL_POSITIONS = int(os.getenv("TRADING_MAX_METAL_POSITIONS", "1"))
TRADING_AMD_LOOKBACK = int(os.getenv("TRADING_AMD_LOOKBACK", "30"))
TRADING_AMD_ACCUMULATION_CANDLES = int(os.getenv("TRADING_AMD_ACCUMULATION_CANDLES", "20"))
TRADING_MIN_SWING_CONFIRMATION = int(os.getenv("TRADING_MIN_SWING_CONFIRMATION", "2"))
TRADING_POSITION_CLOSE_VERIFY_SECONDS = float(os.getenv("TRADING_POSITION_CLOSE_VERIFY_SECONDS", "2.0"))
TRADING_POSITION_CLOSE_VERIFY_INTERVAL = float(os.getenv("TRADING_POSITION_CLOSE_VERIFY_INTERVAL", "0.2"))
TRADING_MINIMUM_LOT_PROTECTION = os.getenv("TRADING_MINIMUM_LOT_PROTECTION", "true").lower() in ("1", "true", "yes")
TRADING_MARGIN_PROTECTION = os.getenv("TRADING_MARGIN_PROTECTION", "true").lower() in ("1", "true", "yes")
TRADING_MARTINGALE_ENABLED = os.getenv("TRADING_MARTINGALE_ENABLED", "false").lower() in ("1", "true", "yes")
TRADING_MAX_DRAWDOWN_PERCENT = float(os.getenv("TRADING_MAX_DRAWDOWN_PERCENT", "8.0"))
TRADING_MAX_CONSECUTIVE_LOSSES = int(os.getenv("TRADING_MAX_CONSECUTIVE_LOSSES", "3"))
TRADING_AUTO_EXECUTION = os.getenv("TRADING_AUTO_EXECUTION", "false").lower() in ("1", "true", "yes")
TRADING_LIVE_AUTO_EXECUTION = os.getenv("TRADING_LIVE_AUTO_EXECUTION", "false").lower() in ("1", "true", "yes")
TRADING_SWING_EXPECTED_HOLD_DAYS = int(os.getenv("TRADING_SWING_EXPECTED_HOLD_DAYS", "7"))
TRADING_SWING_ALLOW_WEEKEND_HOLDING = os.getenv("TRADING_SWING_ALLOW_WEEKEND_HOLDING", "true").lower() in ("1", "true", "yes")
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
TRADING_SYMBOLS = [s.strip().upper() for s in os.getenv("ANGELIQUE_TRADING_SYMBOLS", "EURUSD,GBPUSD,AUDUSD,USDJPY,XAUUSD,BTCUSD,ETHUSD").split(",") if s.strip()]
TRADING_TIMEFRAMES = [s.strip().upper() for s in os.getenv("ANGELIQUE_TRADING_TIMEFRAMES", "M1,M5,M15,M30,H1,H4,D1,W1,MN").split(",") if s.strip()]
DEFAULT_TRADING_SYMBOL = os.getenv("ANGELIQUE_DEFAULT_TRADING_SYMBOL", TRADING_SYMBOLS[0] if TRADING_SYMBOLS else "EURUSD").upper()
DEFAULT_TRADING_TIMEFRAME = os.getenv("ANGELIQUE_DEFAULT_TRADING_TIMEFRAME", TRADING_TIMEFRAMES[0] if TRADING_TIMEFRAMES else "H1").upper()



# --- Database Configuration (ABSOLUTE PATHS) ---
DB_PATH = str(DATA_DIR / "angelique.db")
CHROMA_DB_PATH = str(DATA_DIR / "chroma_memory")

# --- Runtime directories and data paths ---
LOG_DIR = DATA_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

NEWS_CACHE_DIR = DATA_DIR / "news_cache"
NEWS_CACHE_DIR.mkdir(parents=True, exist_ok=True)

GENERATED_SKILLS_DIR = DATA_DIR / "generated_skills"
GENERATED_SKILLS_DIR.mkdir(parents=True, exist_ok=True)
EVOLUTION_LOG = GENERATED_SKILLS_DIR / "evolution_log.json"
COMPONENT_CACHE = GENERATED_SKILLS_DIR / "component_cache.json"

GENERATED_IMAGES_DIR = DATA_DIR / "generated_images"
GENERATED_IMAGES_DIR.mkdir(parents=True, exist_ok=True)

CAMERA_CAPTURE_DIR = DATA_DIR / "camera_captures"
CAMERA_CAPTURE_DIR.mkdir(parents=True, exist_ok=True)

TRADING_JOURNAL_PATH = DATA_DIR / "trading_journal.json"

MEMORY_COLLECTION_NAME = os.getenv("ANGELIQUE_MEMORY_COLLECTION_NAME", "angelique_memory")

WEB_SEARCH_BASE_URL = os.getenv("WEB_SEARCH_BASE_URL", "https://www.google.com/search?q=")

HUGGINGFACE_API_KEY = os.getenv("HUGGINGFACE_API_KEY", "")
HUGGINGFACE_MODEL_URL = os.getenv("HUGGINGFACE_MODEL_URL", "https://api-inference.huggingface.co/models/stabilityai/stable-diffusion-xl-base-1.0")
HUGGINGFACE_LOCAL_MODEL_ID = os.getenv("HUGGINGFACE_LOCAL_MODEL_ID", "")

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "98f6HmuJM9hLdz4dHpfb")
ELEVENLABS_MODEL = os.getenv("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2")
EDGE_TTS_VOICE = os.getenv("ANGELIQUE_EDGE_TTS_VOICE", "en-US-AriaNeural")

# --- External service API keys provided by user/environment ---
OPENWEATHERMAP_API_KEY = os.getenv("OPENWEATHERMAP_API_KEY", "")
WOLFRAM_APPID = os.getenv("WOLFRAM_APPID", "")
# Allow local HuggingFace model usage (prefer local if present)
HUGGINGFACE_LOCAL = os.getenv("HUGGINGFACE_LOCAL", "true").lower() in ("1", "true", "yes")

# WhatsApp: prefer server-side API if configured, otherwise use local libraries/browser
WHATSAPP_FALLBACKS = []  # browser/desktop fallbacks are deliberately disabled

# TTS preference: 'edge' | 'elevenlabs' | 'local'
ANGELIQUE_TTS_PREFERENCE = os.getenv("ANGELIQUE_TTS_PREFERENCE", os.getenv("ANGELIQUE_TTS_PROVIDER", "edge"))
ANGELIQUE_UI_WORKERS = int(os.getenv("ANGELIQUE_UI_WORKERS", "8"))
ANGELIQUE_UI_POLL_MS = int(os.getenv("ANGELIQUE_UI_POLL_MS", "80"))

OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "qwen/qwen-2.5-coder-32b-instruct")
BLUESMINDS_MODEL = os.getenv("BLUESMINDS_MODEL", "meta/llama-3.1-8b-instruct")
NVIDIA_MODEL = os.getenv("NVIDIA_MODEL", "meta/llama-3.1-70b-instruct")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
GEMINI_BASE_URL = os.getenv("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta")
_OLLAMA_CONFIGURED_MODELS = os.getenv("OLLAMA_MODEL_CANDIDATES", "").strip()
_OLLAMA_DEFAULT_MODELS = f"{LOCAL_FALLBACK_MODEL},{PRIMARY_MODEL},{CODER_MODEL},qwen2.5:3b,llama3.1"
OLLAMA_MODEL_CANDIDATES = [
    s.strip() for s in (_OLLAMA_CONFIGURED_MODELS or _OLLAMA_DEFAULT_MODELS).split(",") if s.strip()
]
API_DEFAULT_REFERER = os.getenv("API_DEFAULT_REFERER", "http://localhost")
API_CLIENT_TITLE = os.getenv("API_CLIENT_TITLE", "Angelique AI")
ANGELIQUE_DEFAULT_MODE_ENV = os.getenv("ANGELIQUE_DEFAULT_MODE_ENV", "ANGELIQUE_DEFAULT_MODE")
ANGELIQUE_LAUNCHED_ENV = os.getenv("ANGELIQUE_LAUNCHED_ENV", "ANGELIQUE_LAUNCHED")
NETWORK_CHECK_HOST = os.getenv("ANGELIQUE_NETWORK_CHECK_HOST", "8.8.8.8")
NETWORK_CHECK_PORT = int(os.getenv("ANGELIQUE_NETWORK_CHECK_PORT", "53"))
DEFAULT_HTTP_USER_AGENT = os.getenv("ANGELIQUE_DEFAULT_HTTP_USER_AGENT", "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36")
EXTERNAL_IP_LOOKUP_URL = os.getenv("ANGELIQUE_EXTERNAL_IP_LOOKUP_URL", "https://api.ipify.org")

# Identity / question detection phrases (move hard-coded patterns here so they can be configured)
# Comma-separated list of short phrases to detect identity-style queries. These are used
# by the cognitive loop to recognize questions like "what is your name" or "who are you".
IDENTITY_QUESTION_PHRASES = [s.strip().lower() for s in os.getenv(
    "ANGELIQUE_IDENTITY_QUESTION_PHRASES",
    "what is your name,who are you,what should i call you,what is your identity",
).split(",") if s.strip()]

# Memory trigger phrases (used to decide when to consult short-term or long-term memory)
MEMORY_TRIGGER_PHRASES = [s.strip().lower() for s in os.getenv(
    "ANGELIQUE_MEMORY_TRIGGER_PHRASES",
    "remember,recall,what is my,what's my,who is my,what do i,what did i,what have i,do you know",
).split(",") if s.strip()]

# Training directive markers (phrases that indicate the user wants the assistant to learn or store rules)
TRAINING_DIRECTIVE_MARKERS = [s.strip().lower() for s in os.getenv(
    "ANGELIQUE_TRAINING_DIRECTIVE_MARKERS",
    "memorize,remember,learn,training,train,from now on",
).split(",") if s.strip()]

# Ensure ChromaDB directory exists
Path(CHROMA_DB_PATH).mkdir(parents=True, exist_ok=True)

# Avoid printing non-ASCII symbols during headless/Wine bridge startup; use ASCII messages
try:
    print(f"[Config] SQLite DB: {DB_PATH}")
    print(f"[Config] ChromaDB Path: {CHROMA_DB_PATH}")
except Exception:
    # If printing fails under Wine's codepage, silently continue.
    pass
