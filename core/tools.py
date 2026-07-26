# core/tools.py
import inspect
import subprocess
from skills.os_control.app_discovery import open_app, get_installed_apps
from skills.memory.memory_tools import save_fact, recall_facts
from skills.vision.screen_tools import read_screen
from skills.vision.camera_tools import analyze_camera_scene
from skills.web.search_tools import search_web
from skills.messaging.whatsapp_tools import prepare_whatsapp_message, execute_whatsapp_send
from skills.os_control.system_monitor import get_system_health, get_running_processes
from skills.file_management.file_ops import manage_files
from skills.self_evolution.code_generator import save_new_skill, execute_generated_code
from skills.self_evolution.code_generator import create_and_execute_skill as create_and_execute_skill
from skills.trading.engine.mt5_bridge import bridge
from skills.trading.trading_skill import analyze_and_recommend, execute_approved_trade

TOOL_REGISTRY = {
    "open_app": {
        "description": "Opens a GUI application. Pass the EXACT app name.",
        "parameters": {"app_name": "The exact name of the application (string)."},
        "function": open_app
    },
    "list_apps": {
        "description": "Returns a list of all installed applications.",
        "parameters": {},
        "function": lambda: f"Installed apps: {', '.join(sorted(get_installed_apps().keys()))}"
    },
    "save_memory": {
        "description": "Saves a permanent fact about the user or friends.",
        "parameters": {"person": "Person", "key": "Label", "value": "Detail"},
        "function": save_fact
    },
    "recall_memory": {
        "description": "Searches long-term memory.",
        "parameters": {"query": "Topic or person to search"},
        "function": recall_facts
    },
    "read_screen": {
        "description": "Takes a screenshot and extracts text via OCR.",
        "parameters": {},
        "function": read_screen
    },
    "analyze_camera": {
        "description": "Captures webcam image, detects objects and text.",
        "parameters": {},
        "function": analyze_camera_scene
    },
    "search_web": {
        "description": "Searches the live internet.",
        "parameters": {"query": "Search query"},
        "function": search_web
    },
    "prepare_whatsapp_message": {
        "description": "STEP 1 OF 2: Searches WhatsApp Web for a contact by name, extracts their phone number, and drafts the message. DOES NOT SEND.",
        "parameters": {"contact_name": "Contact name", "message": "Message to draft"},
        "function": prepare_whatsapp_message
    },
    "execute_whatsapp_send": {
        "description": "STEP 2 OF 2: Actually types and sends the message in the already open WhatsApp Web session. ONLY use this AFTER the user has explicitly confirmed.",
        "parameters": {"contact_name": "Contact name", "message": "Message to send"},
        "function": execute_whatsapp_send
    },
    "get_system_health": {
        "description": "Checks CPU, RAM, Disk usage, and OS info.",
        "parameters": {},
        "function": get_system_health
    },
    "get_running_processes": {
        "description": "Lists top processes consuming CPU.",
        "parameters": {"limit": "Number of top processes (int)"},
        "function": get_running_processes
    },
    "manage_files": {
        "description": "Creates, reads, deletes, moves, or lists files and folders.",
        "parameters": {"action": "Action", "path": "Path", "content": "Content", "new_path": "New Path"},
        "function": manage_files
    },
    "run_shell_command": {
        "description": "Executes a safe shell command on the user's Linux system.",
        "parameters": {"command": "The exact shell command to run"},
        "function": lambda command: subprocess.run(command, shell=True, capture_output=True, text=True, timeout=15).stdout.strip() or "Command executed with no output."
    },
    "save_new_skill": {
        "description": "Saves a Python script as a new permanent skill for future use.",
        "parameters": {"skill_name": "Name of the skill", "code": "The full Python code"},
        "function": save_new_skill
    },
    "execute_generated_code": {
        "description": "Writes and executes Python code on the fly to solve a novel problem.",
        "parameters": {"code": "The complete Python script", "function_name": "Function name to call", "kwargs": "Keyword arguments"},
        "function": execute_generated_code
    },
    "create_and_execute_skill": {
        "description": "Generates and executes a Python skill from a natural language instruction.",
        "parameters": {"instruction": "Instruction describing the task to solve"},
        "function": create_and_execute_skill
    },
    # --- TRADING ENGINE TOOLS ---
    "check_mt5_status": {
        "description": "Checks if the MT5 Bridge is connected and the terminal is running.",
        "parameters": {},
        "function": lambda: bridge.ping()
    },
    "get_account_balance": {
        "description": "Retrieves current trading account balance, equity, free margin, and leverage.",
        "parameters": {},
        "function": lambda: bridge.get_account_info()
    },
    "analyze_market_and_recommend": {
        "description": "Analyzes a specific trading pair using the Angelique 10-Rule Constitution. Fetches market data, calculates indicators, checks risk, and returns a detailed trade recommendation or rejection. Use this when the user asks to 'analyze EURUSD' or 'should I buy Gold'.",
        "parameters": {
            "symbol": "The trading pair (e.g., 'EURUSD', 'XAUUSD').",
            "timeframe": "The chart timeframe (e.g., 'M15', 'H1', 'H4').",
            "risk_percent": "Risk percentage per trade (default 1.0)."
        },
        "function": lambda symbol, timeframe="H1", risk_percent=1.0: analyze_and_recommend(symbol, timeframe, risk_percent)
    },
    "execute_approved_trade": {
        "description": "Executes a market order. ONLY use this after the user has explicitly confirmed the trade recommendation.",
        "parameters": {
            "symbol": "The trading pair (e.g., 'EURUSD').",
            "order_type": "BUY or SELL.",
            "lot_size": "The calculated lot size (float).",
            "sl": "Stop Loss price (float).",
            "tp": "Take Profit price (float)."
        },
        "function": execute_approved_trade
    }
}

def execute_tool(tool_name: str, args: dict) -> str:
    if tool_name not in TOOL_REGISTRY:
        return f"Error: Tool '{tool_name}' not found."
    tool = TOOL_REGISTRY[tool_name]
    func = tool["function"]
    try:
        if args is None: args = {}
        sig = inspect.signature(func)
        valid_args = {k: v for k, v in args.items() if k in sig.parameters}
        return func(**valid_args)
    except Exception as e:
        return f"Error executing {tool_name}: {str(e)}"

# Expose helper for dynamic skill creation (used by cognitive loop)
# `create_and_execute_skill(instruction: str) -> str`