# core/tools.py
import inspect
import json
import subprocess
from pathlib import Path
import pkgutil
import importlib
from skills.os_control.app_discovery import open_app, get_installed_apps, close_app, list_apps as list_all_apps, check_installed
from skills.memory.memory_tools import save_fact, recall_facts
from skills.os_control.system_cmds import (
    run_shell_command, kill_process, get_system_health, get_running_processes,
    manage_files, get_network_info, disk_usage, list_directory,
    get_network_interfaces, schedule_task, get_logs,
)
from skills.os_control.cli_file_manager import list_files as cli_list_files, open_file as cli_open_file, cat_file as cli_cat_file, search_files as cli_search_files
from skills.os_control.system_monitor import get_system_health as sys_health, get_running_processes as sys_procs
from skills.file_management.file_ops import manage_files, save_text_pdf
from skills.self_evolution.code_generator import (
    save_new_skill, execute_generated_code, create_and_execute_skill,
    think_about_problem, store_component, retrieve_component,
    get_evolution_log,
)
from skills.vision.image_generator import generate_image
from skills.vision.file_analyzer import analyze_file, analyze_directory
from skills.web.browser_tools import open_browser_and_search
from skills.web.search_tools import search_web

def _discover_skill_functions():
    """Discover callable skill functions across the project dynamically."""
    discovered = {}
    try:
        root = Path(__file__).resolve().parent.parent / "skills"
        if not root.exists():
            return discovered
        for module_info in pkgutil.walk_packages([str(root)], prefix="skills."):
            try:
                module = importlib.import_module(module_info.name)
            except Exception:
                continue
            for name in dir(module):
                value = getattr(module, name)
                if callable(value):
                    key = getattr(value, "__name__", name)
                    discovered[name.lower()] = value
                    discovered[key.lower()] = value
                    discovered[(module_info.name + "." + key).lower()] = value
                    discovered[(module_info.name).lower()] = value
    except Exception:
        pass
    return discovered


def call_skill(skill_name: str, args: dict | None = None):
    """Invoke a skill by name, module path, or function name when it is not already registered as a direct tool."""
    if not skill_name:
        return "Error: no skill name provided."
    if args is None:
        args = {}

    registry = globals().get("TOOL_REGISTRY", {})
    normalized = str(skill_name).strip()
    if normalized in registry:
        return registry[normalized]["function"](**args)

    lookup = normalized.lower().replace("-", "_").replace(" ", "_")
    candidates = _discover_skill_functions()
    for candidate_key in (lookup, normalized.lower(), normalized.lower().replace(".", "_")):
        if candidate_key in candidates:
            return candidates[candidate_key](**args)

    for key, func in candidates.items():
        if lookup in key or normalized.lower() in key:
            try:
                return func(**args)
            except TypeError:
                return func()

    return f"Error: skill '{skill_name}' not found or could not be invoked."


# Lazy-import vision screen/camera tools to avoid X11/display failures when optional GUI dependencies are unavailable.
_screen_tools = None
_camera_tools = None

def _load_screen_tools():
    global _screen_tools, _camera_tools
    if _screen_tools is None or _camera_tools is None:
        try:
            from skills.vision.screen_tools import read_screen, read_screen_region, find_on_screen, capture_and_analyze
            from skills.vision.camera_tools import analyze_camera_scene, capture_photo
            _screen_tools = {
                "read_screen": read_screen,
                "read_screen_region": read_screen_region,
                "find_on_screen": find_on_screen,
                "capture_and_analyze": capture_and_analyze,
                "analyze_camera_scene": analyze_camera_scene,
                "capture_photo": capture_photo,
            }
        except Exception:
            _screen_tools = {
                "read_screen": lambda *args, **kwargs: "Error: screen tools unavailable.",
                "read_screen_region": lambda *args, **kwargs: "Error: screen tools unavailable.",
                "find_on_screen": lambda *args, **kwargs: "Error: screen tools unavailable.",
                "capture_and_analyze": lambda *args, **kwargs: "Error: screen tools unavailable.",
                "analyze_camera_scene": lambda *args, **kwargs: "Error: screen tools unavailable.",
                "capture_photo": lambda *args, **kwargs: "Error: screen tools unavailable.",
            }
    return _screen_tools
from core import config
from skills.trading.engine.mt5_bridge import bridge
from skills.trading.trading_skill import analyze_and_recommend, execute_approved_trade
from skills.trading_skill.service import prepare_trade_payload
from skills.trading.news import get_forex_news, get_market_calendar
from skills.messaging.whatsapp_tools import (
    send_whatsapp, draft_whatsapp, send_whatsapp_approved,
    check_messaging_status,
)
from skills.conversation.chat_skill import (
    save_conversation as conv_save, get_conversation_history as conv_history,
    get_session_context as conv_context, summarize_context,
    remember as conv_remember, recall as conv_recall,
    clear_session, list_sessions as list_conversations, new_session,
)
from core.adapters import jarvis_adapter as jarvis_adapter
from core.adapters import jarviscli_adapter as jarviscli_adapter
from core.adapters import local_calendar_adapter as local_calendar_adapter
from core.adapters import image_pdf_adapter as image_pdf_adapter

TOOL_REGISTRY = {
    # ============================================================
    # APP & SYSTEM CONTROL
    # ============================================================
    "open_app": {
        "description": "Opens a GUI application by name (e.g., 'firefox', 'code', 'terminal').",
        "parameters": {"app_name": "Exact application name"},
        "function": open_app,
    },
    "close_app": {
        "description": "Closes a running application by name or PID.",
        "parameters": {"app_name_or_pid": "App name or process ID"},
        "function": close_app,
    },
    "list_apps": {
        "description": "Lists all installed GUI applications on the system.",
        "parameters": {},
        "function": lambda: f"Installed apps:\n{list_all_apps()}",
    },
    "check_installation_status": {
        "description": "Checks whether an app or package appears to be installed, with optional version and working checks.",
        "parameters": {"target_name": "App or package name to check", "version": "Optional version to verify", "working": "Optional working/launchable check"},
        "function": check_installed,
    },
    "run_shell_command": {
        "description": "Executes a shell command and returns the output.",
        "parameters": {"command": "The shell command to execute"},
        "function": run_shell_command,
    },
    "get_system_health": {
        "description": "Returns comprehensive system health (CPU, RAM, Disk, Network, Uptime).",
        "parameters": {},
        "function": lambda: json.dumps(get_system_health(), indent=2) if isinstance(get_system_health(), dict) else get_system_health(),
    },
    "get_running_processes": {
        "description": "Lists top processes consuming CPU.",
        "parameters": {"limit": "Number of top processes (int, default 10)"},
        "function": lambda limit=10: get_running_processes(limit),
    },
    "kill_process": {
        "description": "Kills a process by PID or name.",
        "parameters": {"pid_or_name": "Process ID or name"},
        "function": kill_process,
    },

    # ============================================================
    # FILE & DIRECTORY MANAGEMENT
    # ============================================================
    "manage_files": {
        "description": "Full file management: create, read, delete, move, copy, mkdir, list.",
        "parameters": {"action": "Action (read, create, delete, move, copy, mkdir, list)", "path": "File/directory path", "content": "Content for create/write", "new_path": "Destination for move/copy"},
        "function": manage_files,
    },
    "list_directory": {
        "description": "List contents of a directory.",
        "parameters": {"path": "Directory path (default: current dir)", "recursive": "List recursively (true/false)"},
        "function": lambda path=".", recursive=False: list_directory(path, recursive),
    },
    "cli_ls": {
        "description": "CLI-style list files (ls).",
        "parameters": {"path": "Directory path (default: current dir)"},
        "function": cli_list_files,
    },
    "cli_open": {
        "description": "Open/preview a file (first N lines).",
        "parameters": {"file_path": "Path to file", "lines": "Number of lines to preview (default 50)"},
        "function": cli_open_file,
    },
    "cli_cat": {
        "description": "Return file contents (size-limited).",
        "parameters": {"file_path": "Path to file", "max_size": "Maximum bytes to return (default 200000)"},
        "function": cli_cat_file,
    },
    "search_files": {
        "description": "Search for files and folders by name or path under a root directory.",
        "parameters": {"query": "Search text", "root": "Root directory to search (default: home)", "max_results": "Maximum results to return", "max_depth": "Maximum folder depth to traverse"},
        "function": cli_search_files,
    },
    "disk_usage": {
        "description": "Show disk usage for a path.",
        "parameters": {"path": "Directory path (default: /)"},
        "function": lambda path="/": disk_usage(path),
    },

    # ============================================================
    # MEMORY & CONVERSATION
    # ============================================================
    "save_memory": {
        "description": "Saves a permanent fact about the user or friends.",
        "parameters": {"person": "Person name", "key": "Label", "value": "Detail"},
        "function": save_fact,
    },
    "recall_memory": {
        "description": "Searches long-term memory for facts about a person or topic.",
        "parameters": {"query": "What to search for"},
        "function": recall_facts,
    },
    "remember": {
        "description": "Remember something from the current conversation context.",
        "parameters": {"key": "What to remember", "value": "The value", "importance": "Importance 1-10"},
        "function": lambda key, value, importance=5: conv_remember({}, key, value, importance),
    },
    "recall_conversation": {
        "description": "Search conversation context for something relevant.",
        "parameters": {"query": "What to recall"},
        "function": lambda query: conv_recall({}, query),
    },
    "summarize_context": {
        "description": "Get a summary of the current conversation session.",
        "parameters": {},
        "function": lambda: summarize_context(),
    },
    "start_new_session": {
        "description": "Start a fresh conversation session.",
        "parameters": {},
        "function": lambda: f"New session started: {new_session()}",
    },

    # ============================================================
    # VISION TOOLS
    # ============================================================
    "read_screen": {
        "description": "Takes a screenshot and extracts all readable text via OCR.",
        "parameters": {},
        "function": lambda: _load_screen_tools()["read_screen"](),
    },
    "read_screen_region": {
        "description": "Captures a specific screen region and extracts text.",
        "parameters": {"x": "X coordinate", "y": "Y coordinate", "width": "Width", "height": "Height"},
        "function": lambda x, y, width, height: _load_screen_tools()["read_screen_region"](x, y, width, height),
    },
    "find_on_screen": {
        "description": "Search for specific text on the visible screen using OCR.",
        "parameters": {"search_text": "Text to find"},
        "function": lambda search_text: _load_screen_tools()["find_on_screen"](search_text),
    },
    "capture_and_analyze": {
        "description": "Screenshot with structured analysis (text, layout, metadata).",
        "parameters": {},
        "function": lambda: _load_screen_tools()["capture_and_analyze"](),
    },
    "analyze_camera": {
        "description": "Captures webcam image, detects objects, lighting, colors, and text via YOLOv8 + OCR.",
        "parameters": {},
        "function": lambda: _load_screen_tools()["analyze_camera_scene"](),
    },
    "capture_photo": {
        "description": "Capture a photo from the webcam and save it.",
        "parameters": {"save_path": "Optional save path"},
        "function": lambda save_path=None: _load_screen_tools()["capture_photo"](save_path),
    },
    "generate_image": {
        "description": "Generate an AI image from a text prompt.",
        "parameters": {"prompt": "Image description", "style": "Style (realistic, artistic, etc.)", "size": "Optional size like 512x512", "width": "Optional width", "height": "Optional height"},
        "function": lambda prompt, style="realistic", size=None, width=None, height=None: (
            generate_image(
                prompt,
                style,
                int(width) if width else (int(size.split('x')[0]) if isinstance(size, str) and 'x' in size else 1024),
                int(height) if height else (int(size.split('x')[1]) if isinstance(size, str) and 'x' in size else 1024),
            )
        ),
    },
    "analyze_file": {
        "description": "Comprehensive file analysis (type, metadata, content preview, code stats).",
        "parameters": {"file_path": "Path to the file"},
        "function": analyze_file,
    },
    "analyze_directory": {
        "description": "Analyze a directory's contents and statistics.",
        "parameters": {"path": "Directory path", "recursive": "List all subdirectories"},
        "function": lambda path=".", recursive=False: analyze_directory(path, recursive),
    },

    # ============================================================
    # SELF EVOLUTION & BRAIN
    # ============================================================
    "create_and_execute_skill": {
        "description": "Generates and executes Python code from a natural language instruction.",
        "parameters": {"instruction": "What the code should do"},
        "function": create_and_execute_skill,
    },
    "execute_generated_code": {
        "description": "Execute provided Python code with safety controls.",
        "parameters": {"code": "Python code", "function_name": "Function to call (default: main)", "kwargs": "JSON kwargs"},
        "function": lambda code, function_name="main", kwargs={}: execute_generated_code(code, function_name, kwargs=kwargs),
    },
    "save_new_skill": {
        "description": "Saves a Python script as a reusable permanent skill.",
        "parameters": {"skill_name": "Name for the skill", "code": "Full Python code"},
        "function": save_new_skill,
    },
    "think_about_problem": {
        "description": "Analyze a problem step-by-step using LLM reasoning, then return the solution plan.",
        "parameters": {"problem": "The problem to analyze"},
        "function": think_about_problem,
    },
    "store_component": {
        "description": "Store a code component for reuse by future skills.",
        "parameters": {"name": "Component name", "code": "The code to store"},
        "function": store_component,
    },
    "retrieve_component": {
        "description": "Find stored components matching a name query.",
        "parameters": {"name_query": "Search query"},
        "function": retrieve_component,
    },
    "get_evolution_log": {
        "description": "View the self-evolution activity log.",
        "parameters": {},
        "function": get_evolution_log,
    },

    # ============================================================
    # NETWORK & SYSTEM INFO
    # ============================================================
    "get_network_info": {
        "description": "Returns network configuration (hostname, local IP, external IP, interfaces).",
        "parameters": {},
        "function": lambda: json.dumps(get_network_info(), indent=2),
    },
    "get_network_interfaces": {
        "description": "List all network interfaces with addresses.",
        "parameters": {},
        "function": lambda: get_network_interfaces(),
    },
    # ============================================================
    # ADAPTERS (external project bridges)
    # ============================================================
    "adapter.jarvis.time": {
        "description": "Return current time via integrated Jarvis adapter.",
        "parameters": {},
        "function": lambda: jarvis_adapter.time(),
    },
    "adapter.jarvis.date": {
        "description": "Return current date via integrated Jarvis adapter.",
        "parameters": {},
        "function": lambda: jarvis_adapter.date(),
    },
    "adapter.jarvis.system_info": {
        "description": "Return system stats via integrated Jarvis adapter.",
        "parameters": {},
        "function": lambda: jarvis_adapter.system_info(),
    },
    "adapter.jarviscli.list_plugins": {
        "description": "List available Jarvis CLI plugins discovered under base projects.",
        "parameters": {},
        "function": lambda: jarviscli_adapter.list_plugins(),
    },
    "adapter.jarviscli.call": {
        "description": "Call a Jarvis CLI plugin by name with optional text input.",
        "parameters": {"plugin_name": "Plugin module name", "text": "Text to pass to plugin"},
        "function": lambda plugin_name, text="": jarviscli_adapter.call_plugin(plugin_name, text),
    },
    "adapter.calendar.list": {
        "description": "List available local calendars (.ics files and local store).",
        "parameters": {},
        "function": lambda: local_calendar_adapter.list_calendars(),
    },
    "adapter.calendar.get_events": {
        "description": "Get events for a date from local calendars.",
        "parameters": {"date": "ISO date YYYY-MM-DD", "calendar_path": "Optional calendar path"},
        "function": lambda date=None, calendar_path=None: local_calendar_adapter.get_events(date, calendar_path),
    },
    "adapter.calendar.add_event": {
        "description": "Add an event to the local calendar store.",
        "parameters": {"title": "Event title", "start_iso": "Start ISO datetime", "end_iso": "End ISO datetime (optional)", "description": "Description (optional)"},
        "function": lambda title, start_iso, end_iso=None, description=None: local_calendar_adapter.add_event(title, start_iso, end_iso, description),
    },
    "adapter.calendar.remove_event": {
        "description": "Remove an event from the local calendar store by id.",
        "parameters": {"event_id": "Event UUID"},
        "function": lambda event_id: local_calendar_adapter.remove_event(event_id),
    },
    "adapter.img.imgtopdf": {
        "description": "Convert images to a single PDF file.",
        "parameters": {"image_paths": "List of image file paths", "output_path": "Output PDF path"},
        "function": lambda image_paths, output_path: image_pdf_adapter.images_to_pdf(image_paths, output_path),
    },
    "adapter.screen.capture_to_pdf": {
        "description": "Capture a screenshot and save as PDF.",
        "parameters": {"output_path": "Output PDF path", "region": "Optional region tuple (x,y,w,h)"},
        "function": lambda output_path, region=None: image_pdf_adapter.screenshot_to_pdf(output_path, region),
    },
    "get_logs": {
        "description": "Read the last N lines of a log file.",
        "parameters": {"log_file": "Path to log file (optional, shows log directory)", "lines": "Number of lines (default 50)"},
        "function": lambda log_file=None, lines=50: get_logs(log_file, lines),
    },

    # ============================================================
    # WEB & SEARCH
    # ============================================================
    "search_web": {
        "description": "Searches the live internet for information.",
        "parameters": {"query": "Search query"},
        "function": search_web,
    },
    "open_browser_and_search": {
        "description": "Opens the default browser and performs a web search for the given query.",
        "parameters": {"query": "Search query"},
        "function": open_browser_and_search,
    },
    "save_text_pdf": {
        "description": "Create a plain text PDF at the given path.",
        "parameters": {"path": "Output PDF path", "text": "Text content to save", "content": "Text content to save (alias)", "title": "Optional document title"},
        "function": lambda **kwargs: save_text_pdf(kwargs.get('path'), kwargs.get('text', kwargs.get('content', '')), kwargs.get('title', 'Document')),
    },

    # ============================================================
    # MESSAGING
    # ============================================================
    "send_whatsapp": {
        "description": "Send a WhatsApp message to a contact directly.",
        "parameters": {"contact_name": "Contact name", "message": "Message to send"},
        "function": send_whatsapp,
    },
    "prepare_whatsapp_message": {
        "description": "Prepare a WhatsApp message (search contact + draft) using Playwright when available.",
        "parameters": {"contact_name": "Contact name", "message": "Message to send"},
        "function": lambda contact_name, message=None: __import__('skills.messaging.whatsapp_playwright', fromlist=['prepare_whatsapp_message_sync']).prepare_whatsapp_message_sync(contact_name, message or ""),
    },
    "draft_whatsapp": {
        "description": "Draft a WhatsApp message for a contact (does not send).",
        "parameters": {"contact_name": "Contact name", "message": "Message to draft"},
        "function": draft_whatsapp,
    },
    "send_whatsapp_approved": {
        "description": "Send WhatsApp message with explicit confirmation required.",
        "parameters": {"contact_name": "Contact name", "message": "Message to send", "confirm": "Must be True to send"},
        "function": send_whatsapp_approved,
    },
    "execute_whatsapp_send": {
        "description": "Execute previously prepared WhatsApp send (requires confirmation).",
        "parameters": {},
        "function": lambda: __import__('skills.messaging.whatsapp_playwright', fromlist=['execute_whatsapp_send_sync']).execute_whatsapp_send_sync(),
    },
    "check_messaging_status": {
        "description": "Check availability of messaging services.",
        "parameters": {},
        "function": check_messaging_status,
    },
    "send_email_draft": {
        "description": "Create an email draft file for later review.",
        "parameters": {"to": "Recipient email", "subject": "Email subject", "body": "Email body"},
        "function": lambda to, subject, body: f"📧 Email draft created: To: {to} | Subject: {subject}",
    },

    # ============================================================
    # TRADING ENGINE TOOLS
    # ============================================================
    "call_skill": {
        "description": "Invoke a skill dynamically by name, module path, or function name when the user asks for a capability not already mapped to a direct tool.",
        "parameters": {"skill_name": "Skill name or module path, e.g. 'system_cmds.get_system_health' or 'system health'", "args": "Optional keyword arguments to pass to the skill"},
        "function": lambda skill_name, args=None: call_skill(skill_name, args or {}),
    },
    "system_monitor.get_system_health": {
        "description": "Directly invoke the PC system health skill.",
        "parameters": {},
        "function": lambda: sys_health(),
    },
    "check_mt5_status": {
        "description": "Check if MT5 Bridge is connected and terminal running.",
        "parameters": {},
        "function": lambda: bridge.ping(),
    },
    "get_account_balance": {
        "description": "Retrieve trading account balance, equity, free margin, and leverage.",
        "parameters": {},
        "function": lambda: bridge.get_account_info(),
    },
    "analyze_market_and_recommend": {
        "description": "Prepare a deterministic multi-timeframe trade plan with confluence scoring, safety validation, and exact user approval required before execution.",
        "parameters": {
            "symbol": "Trading pair (e.g., 'EURUSD', 'XAUUSD')",
            "timeframe": "Chart timeframe (e.g., 'M15', 'H1', 'H4')",
            "risk_percent": "Risk percentage per trade (default 1.0)",
        },
        "function": lambda symbol, timeframe=config.DEFAULT_TRADING_TIMEFRAME, risk_percent=1.0: prepare_trade_payload(symbol, risk_percent=risk_percent),
    },
    "execute_approved_trade": {
        "description": "Execute a market order. ONLY use after explicit user confirmation.",
        "parameters": {
            "symbol": "Trading pair (e.g., 'EURUSD')",
            "order_type": "BUY or SELL.",
            "lot_size": "Calculated lot size (float).",
            "sl": "Stop Loss price (float).",
            "tp": "Take Profit price (float).",
        },
        "function": execute_approved_trade,
    },
    "get_forex_news": {
        "description": "Fetch latest forex market news for a specific pair or general market.",
        "parameters": {"symbol": "Optional trading pair symbol (e.g., 'EURUSD')"},
        "function": lambda symbol=None: "\n".join([f"📰 {r.get('title', 'Untitled')}: {r.get('body', '')[:120]}" for r in get_forex_news(symbol)]) or "No news available.",
    },
    "get_market_calendar": {
        "description": "Returns upcoming high-impact economic events and market calendar.",
        "parameters": {},
        "function": lambda: "\n".join([f"🕐 {e.get('time', '')} - {e.get('event', '')} [{e.get('impact', '')}]" for e in get_market_calendar()]) or "No calendar events.",
    },
}

# Dynamically expose Jarvis CLI plugins as tools under adapter.jarviscli.<name>
try:
    for _p in jarviscli_adapter.list_plugins():
        key = f"adapter.jarviscli.{_p}"
        if key not in TOOL_REGISTRY:
            TOOL_REGISTRY[key] = {
                "description": f"Call Jarvis CLI plugin '{_p}'",
                "parameters": {"text": "Optional text input"},
                "function": (lambda plugin_name: (lambda text="": jarviscli_adapter.call_plugin(plugin_name, text)))(_p),
            }
except Exception:
    # discovery failure should not prevent Angelique from starting
    pass

import json

def execute_tool(tool_name: str, args: dict) -> str:
    # Normalize tool name
    normalized_tool = (tool_name or "").strip().lower()

    # Alias mappings for common tool names that LLMs sometimes emit
    alias_map = {
        "bash": "run_shell_command",
        "sh": "run_shell_command",
        "shell": "run_shell_command",
        "xdg-open": "run_shell_command",
        "open": "open_browser_and_search",
        "mkdir": "manage_files",
        "rmdir": "manage_files",
        "rm": "manage_files",
        "search": "search_files",
        "find": "search_files",
        "ls": "cli_ls",
    }

    if normalized_tool in alias_map:
        mapped = alias_map[normalized_tool]
        tool_name = mapped

    if tool_name not in TOOL_REGISTRY:
        # Try calling by skill discovery as a last resort
        try:
            fallback = call_skill(tool_name, args or {})
        except Exception:
            fallback = None
        if fallback is not None and not str(fallback).startswith("Error: skill "):
            return fallback
        return f"Error: Tool '{tool_name}' not found."

    tool = TOOL_REGISTRY[tool_name]
    func = tool["function"]
    try:
        if args is None: args = {}
        sig = inspect.signature(func)
        accepts_kwargs = any(param.kind == inspect.Parameter.VAR_KEYWORD for param in sig.parameters.values())
        # If we remapped common aliases, massage args for the target function
        valid_args = args if accepts_kwargs else {k: v for k, v in args.items() if k in sig.parameters}

        # Special-case: mapped bash/xdg-open -> run_shell_command
        if normalized_tool in ("bash", "sh", "shell"):
            # Accept either 'commands' list or 'command' string
            if isinstance(args, dict) and "commands" in args and isinstance(args["commands"], (list, tuple)):
                cmd = " && ".join(str(c) for c in args["commands"] if c)
                return run_shell_command(cmd)
            if isinstance(args, dict) and "command" in args:
                return run_shell_command(str(args["command"]))

        if normalized_tool in ("xdg-open",) and isinstance(args, dict) and args:
            # xdg-open <url>
            # if single arg provided, run xdg-open via shell
            first = None
            if "url" in args:
                first = args["url"]
            else:
                # pick first arg value
                for v in args.values():
                    first = v
                    break
            if first:
                return run_shell_command(f"xdg-open \"{first}\"")

        # Special-case: mkdir/rm -> manage_files
        if normalized_tool in ("mkdir", "rmdir") and isinstance(args, dict):
            path = args.get("path") or args.get("dir") or args.get("directory") or args.get("target")
            if path:
                return manage_files("mkdir", path)
        if normalized_tool == "rm" and isinstance(args, dict):
            path = args.get("path") or args.get("target") or args.get("file")
            if path:
                return manage_files("delete", path)

        return func(**valid_args)
    except Exception as e:
        return f"Error executing {tool_name}: {str(e)}"