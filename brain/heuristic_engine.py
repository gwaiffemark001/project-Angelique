# brain/heuristic_engine.py
"""
Comprehensive heuristic engine for deterministic command routing.
Maps natural language to tool actions without LLM dependency for critical commands.
"""
import os
import re
import shutil
from pathlib import Path
from core import config


def _find_case_insensitive_child(base_dir: str, name: str) -> str | None:
    if not os.path.isdir(base_dir):
        return None
    lower_name = name.lower()
    try:
        for child in os.listdir(base_dir):
            if child.lower() == lower_name:
                return os.path.join(base_dir, child)
    except Exception:
        pass
    return None


def _normalize_path_candidate(candidate: str, desktop_only: bool = False, allow_desktop_fallback: bool = False) -> tuple[str, bool]:
    candidate = (candidate or '').strip()
    if not candidate:
        return candidate, False

    desktop_root = getattr(config, 'DESKTOP_PATH', os.path.expanduser('~/Desktop'))
    if desktop_only:
        desktop_path = os.path.join(desktop_root, candidate)
        if os.path.exists(desktop_path):
            return desktop_path, True
        case_path = _find_case_insensitive_child(desktop_root, candidate)
        if case_path:
            return case_path, True
        return desktop_path, False

    expanded = os.path.expanduser(candidate)
    if os.path.isabs(expanded) or candidate.startswith(('.', '~')):
        return expanded, os.path.exists(expanded)

    cwd_path = os.path.abspath(expanded)
    if os.path.exists(cwd_path):
        return cwd_path, True
    case_path = _find_case_insensitive_child(os.path.dirname(cwd_path) or '.', os.path.basename(cwd_path))
    if case_path:
        return case_path, True

    if not _looks_like_path(candidate):
        current_dir = os.path.abspath(os.getcwd())
        target_name = os.path.basename(cwd_path).lower()
        ancestor = current_dir
        while True:
            if os.path.basename(ancestor).lower() == target_name:
                return ancestor, True
            parent = os.path.dirname(ancestor)
            if parent == ancestor:
                break
            ancestor = parent

        ancestor = current_dir
        while True:
            if os.path.basename(ancestor).lower() == candidate.lower():
                return ancestor, True
            parent = os.path.dirname(ancestor)
            if parent == ancestor:
                break
            ancestor = parent

    home_path = os.path.expanduser(expanded)
    if os.path.exists(home_path):
        return home_path, True
    case_path = _find_case_insensitive_child(os.path.dirname(home_path) or os.path.expanduser('~'), os.path.basename(home_path))
    if case_path:
        return case_path, True

    if allow_desktop_fallback:
        desktop_path = os.path.join(desktop_root, candidate)
        if os.path.exists(desktop_path):
            return desktop_path, True
        case_path = _find_case_insensitive_child(desktop_root, candidate)
        if case_path:
            return case_path, True

    return cwd_path, False


def _looks_like_path(candidate: str) -> bool:
    return bool(re.search(r'[\\/]|~', candidate))


def _looks_like_app_name(name: str) -> bool:
    if not name:
        return False
    known_gui_markers = {'chrome', 'firefox', 'browser', 'code', 'vscode', 'terminal', 'nautilus', 'files', 'thunderbird', 'libreoffice', 'vlc', 'gimp'}
    name = name.lower()
    if any(marker in name for marker in known_gui_markers):
        return True
    return shutil.which(name) is not None


def _resolve_folder_target(candidate: str, desktop_only: bool = False) -> tuple[str, bool]:
    path, exists = _normalize_path_candidate(candidate, desktop_only=desktop_only)
    if exists:
        return path, True
    if desktop_only:
        return path, True
    if _looks_like_path(candidate):
        return path, False
    return path, False


def extract_command_heuristically(text: str) -> tuple[str, dict] | tuple[None, dict]:
    """
    Heuristically extract command and args from user text.
    Returns (tool_name, args) or (None, {}) if no match.
    """
    normalized = text.strip().lower()
    if not normalized:
        return None, {}

    # Quick CLI-style shorthands: 'ls', 'dir', 'cat <file>'
    if normalized == 'ls' or normalized.startswith('ls '):
        path = normalized[3:].strip() or '.'
        return 'cli_ls', {'path': path}
    if normalized == 'dir' or normalized.startswith('dir '):
        path = normalized[4:].strip() or '.'
        return 'cli_ls', {'path': path}
    if normalized.startswith('cat '):
        target = text.strip()[4:].strip()
        return 'cli_cat', {'file_path': target}

    def _clean_install_target(candidate: str) -> str:
        cleaned = candidate.strip()
        cleaned = re.sub(r'\b(?:and\s+)?working\b.*$', '', cleaned).strip()
        cleaned = re.sub(r'\b(?:installed|check|verify|confirm|whether|if|is|are|was)\b', '', cleaned).strip()
        cleaned = re.sub(r'\s+', ' ', cleaned).strip(' ?.,')
        return cleaned

    def _split_install_target_and_version(candidate: str) -> tuple[str, str | None]:
        cleaned = _clean_install_target(candidate)
        version_match = re.search(r'\bversion\s+([vV]?\d+(?:\.\d+)+(?:[-+~][\w.]+)?)\b', cleaned)
        if version_match:
            version = version_match.group(1).lstrip('vV')
            target = re.sub(r'\bversion\s+[vV]?\d+(?:\.\d+)+(?:[-+~][\w.]+)?\b', '', cleaned).strip()
            return _clean_install_target(target), version

        parts = cleaned.split()
        if len(parts) >= 2 and re.fullmatch(r'[vV]?\d+(?:\.\d+)+(?:[-+~][\w.]+)?', parts[-1]):
            return ' '.join(parts[:-1]).strip(), parts[-1].lstrip('vV')

        return cleaned, None

    # ============================================================
    # ACCOUNT & BALANCE CHECKING
    # ============================================================
    balance_patterns = [
        r'\b(?:check|get|what.*?)(?:my\s+)?(?:account\s+)?balance\b',
        r'\b(?:what|how much).*?(?:balance|equity|margin|money)\b',
        r'\bmt5\s+(?:account|status|balance)\b',
        r'\b(?:my|my\s+)?(?:account|trading|mt5)\b',
    ]
    if any(re.search(p, normalized) for p in balance_patterns):
        return 'get_account_balance', {}

    # ============================================================
    # MT5 / TRADING TERMINAL
    # ============================================================
    if re.search(r'\b(?:open|start|launch).*?(?:mt5|metatrader\s+5|trading\s+terminal|exness)\b', normalized):
        return 'open_app', {'app_name': 'MetaTrader 5 Exness'}

    # ============================================================
    # SCREEN READING & OCR
    # ============================================================
    if re.search(r'\b(?:read|look at|check|show|what).*?(?:screen|monitor|display|window)\b', normalized):
        return 'read_screen', {}
    if re.search(r'\b(?:take|grab|screenshot|capture)\b', normalized):
        return 'read_screen', {}

    # ============================================================
    # CAMERA & VISION
    # ============================================================
    if re.search(r'\b(?:camera|webcam|see|what.*?see|look.*?camera|real world)\b', normalized):
        return 'analyze_camera', {}

    # ============================================================
    # APP DISCOVERY & OPENING
    # ============================================================
    # Handle explicit shell commands first so 'run shell command echo hello' is not misrouted.
    shell_command = re.search(r'\b(?:run|execute|do)\s+(?:the\s+)?(?:shell\s+command|command)\s+(.+)', normalized)
    if shell_command:
        return 'run_shell_command', {'command': shell_command.group(1).strip()}

    browser_search_match = re.search(
        r'\b(?:open|launch|start|run|execute)\s+(?:a|an|the)?\s*(?:browser|chrome|firefox|web browser)\b.*\b(?:search|find|look(?:\s+up)?|google)\b',
        normalized,
    )
    if browser_search_match:
        query_match = re.search(
            r'\b(?:search|find|look(?:\s+up)?|google)\s+(?:for\s+)?(.+?)(?:\s+(?:online|on\s+web|internet|using|with)\b.*|$)',
            normalized,
        )
        query = query_match.group(1).strip() if query_match else normalized
        return 'open_browser_and_search', {'query': query}

    browser_match = re.search(r'\b(?:open|launch|start|run|execute)\s+(?:a|an|the)?\s*(?:browser|chrome|firefox|web browser)\b', normalized)
    if browser_match:
        return 'open_app', {'app_name': 'firefox'}

    desktop_requested = bool(re.search(r'\bon\s+my\s+desktop|\bon\s+desktop|\bdesktop\b', normalized))

    # Whole laptop / home directory search intent.
    laptop_search_match = re.search(
        r"\b(?:search|find|locate|look(?:\s+for)?)\b.*\b(?:my\s+)?(?:whole\s+)?(?:laptop|computer|machine|filesystem|home\s+directory|home\s+folder|disk|hard\s+drive)\b",
        normalized,
    )
    if laptop_search_match:
        query_match = re.search(r"\b(?:for|about)\b\s+(.+?)(?:\s+(?:on|in|under|within)\b.*)?$", text, re.IGNORECASE)
        query = query_match.group(1).strip() if query_match else text.strip()
        if query:
            return 'search_files', {'query': query, 'root': os.path.expanduser('~')}

    # Natural language listing: 'what files are in X', 'show me the files in X'
    nl_list_match = re.search(r"\b(?:what\s+files\s+are\s+in|show\s+me\s+the\s+files\s+in|what's\s+in|what\s+is\s+in|show\s+me\s+what\s+is\s+in)\s+(?:the\s+)?([\w\-\. ]+?)(?:\s+on\s+my\s+desktop|\s+on\s+desktop)?(?:\s|$)", normalized)
    if nl_list_match:
        folder = nl_list_match.group(1).strip()
        folder = re.sub(r'\s+(?:folder|directory)$', '', folder).strip()
        path, exists = _normalize_path_candidate(folder, desktop_only=desktop_requested, allow_desktop_fallback=True)
        if exists:
            return 'list_directory', {'path': path}

    # Open file requests: route file paths before generic app launch handling.
    file_open_match = re.search(r"\b(?:open|read|view|show|display)\s+([\w\-\.\~/\\ ]+\.[a-zA-Z0-9]+)\b", text)
    if file_open_match:
        return 'cli_open', {'file_path': file_open_match.group(1).strip()}

    if re.search(r"\b(?:open|show|launch|browse)\s+(?:the\s+)?(?:file\s+manager|file\s+explorer|file\s+browser)\b", normalized):
        return 'open_app', {'app_name': 'files'}

    # Open folder requests with explicit folder/directory phrasing.
    folder_match = re.search(r"\b(?:open|show|launch|display|browse)\s+(?:the\s+)?([\w\-\. ]+?)\s*(?:folder|directory)(?:\s+on\s+my\s+desktop|\s+on\s+desktop)?(?:\s|$)", normalized)
    if folder_match:
        folder = folder_match.group(1).strip()
        path, exists = _normalize_path_candidate(folder, desktop_only=desktop_requested, allow_desktop_fallback=desktop_requested)
        if desktop_requested and not exists:
            path = os.path.join(getattr(config, 'DESKTOP_PATH', os.path.expanduser('~/Desktop')), folder)
        return 'run_shell_command', {'command': f'xdg-open "{path}"'}

    # Attempt to open a named folder from the desktop or current context.
    plain_folder_match = re.search(r"\b(?:open|show|browse|launch)\s+(.+?)(?:\s+on\s+my\s+desktop|\s+on\s+desktop|$)", text, re.IGNORECASE)
    if plain_folder_match:
        folder = plain_folder_match.group(1).strip()
        if folder.lower() not in {'a', 'an', 'the', 'browser', 'file', 'folder', 'directory', 'app', 'application', 'program', 'terminal', 'command'}:
            path, exists = _normalize_path_candidate(folder, desktop_only=desktop_requested, allow_desktop_fallback=desktop_requested)
            if exists or not _looks_like_app_name(folder):
                return 'run_shell_command', {'command': f'xdg-open "{path}"'}

    open_app_match = re.search(r'\b(?:open|launch|start|run|execute)\s+(?:the\s+)?([a-zA-Z0-9\s\-]+?)(?:\s+(?:app|application|program|browser|editor))?\b', normalized)
    if open_app_match:
        app_name = open_app_match.group(1).strip().lower()
        if app_name in {'a', 'an', 'the'} or 'folder' in normalized or 'directory' in normalized or 'file' in normalized or 'command' in normalized:
            return None, {}
        if 'browser' in app_name or 'chrome' in app_name or 'firefox' in app_name or _looks_like_app_name(app_name):
            return 'open_app', {'app_name': app_name}
        return None, {}

    # ============================================================
    # GENERIC SKILL DISPATCH
    # ============================================================
    skill_call_patterns = [
        r'\b(?:use|call|run|invoke)\s+(?:the\s+)?(.+?)\s+skill\b',
        r'\b(?:use|call|run|invoke)\s+(?:the\s+)?([a-zA-Z0-9_\.\-]+)\b',
    ]
    for pattern in skill_call_patterns:
        match = re.search(pattern, normalized)
        if match:
            name = match.group(1).strip()
            if name.lower() not in {"app", "browser", "terminal", "command"}:
                return 'call_skill', {'skill_name': name, 'args': {}}

    if re.search(r'\b(?:system\s+monitor|diagnostics|health check|pc health|system health)\b', normalized):
        return 'call_skill', {'skill_name': 'system_monitor.get_system_health', 'args': {}}

    # ============================================================
    # SYSTEM MONITORING
    # ============================================================
    install_check_patterns = [
        r'\b(?:check|see|tell me|find out|verify|confirm)\s+(?:if|whether)\s+(.+?)\s+(?:version\s+[vV]?\d+(?:\.\d+)+(?:[-+~][\w.]+)?\s+)?is\s+installed(?:\s+and\s+working)?\b',
        r'\b(?:check|see|tell me|find out|verify|confirm)\b.*\b(?:if|whether)\b.*\b(?:installed|installed\s+or\s+not)\b',
        r'\b(?:is|was|are)\s+(.+?)\s+installed\b',
        r'\b(?:check|verify|confirm)\s+(?:if\s+)?(.+?)\s+is\s+installed\b',
    ]
    for pattern in install_check_patterns:
        match = re.search(pattern, normalized)
        if match:
            target = match.group(1).strip() if match.groups() else normalized
            target, version = _split_install_target_and_version(target)
            if target:
                args = {'target_name': target}
                if version:
                    args['version'] = version
                if 'working' in normalized:
                    args['working'] = True
                return 'check_installation_status', args

    system_monitor_patterns = [
        r'\b(?:cpu|ram|memory|disk|load|system|performance|health|telemetry|monitoring)\b',
        r'\b(?:how.*?(?:cpu|ram|memory|resources).*?(?:used|used up))\b',
        r'\b(?:top\s+)?processes\b',
    ]
    if any(re.search(p, normalized) for p in system_monitor_patterns):
        return 'get_system_health', {}

    # ============================================================
    # FILE MANAGEMENT
    # ============================================================
    # Natural language listing: "what files are in X", "show me the files in X"
    nl_list_match = re.search(r"\b(?:what\s+files\s+are\s+in|show\s+me\s+the\s+files\s+in|what's\s+in|what\s+is\s+in)\s+(?:the\s+)?([\w\-\. ]+?)(?:\s+on\s+my\s+desktop|\s+on\s+desktop)?\b", normalized)
    if nl_list_match:
        folder = nl_list_match.group(1).strip()
        # If user referred to 'projects' on desktop
        if 'desktop' in normalized or 'on my desktop' in text.lower() or 'on desktop' in text.lower():
            path = os.path.expanduser(f"~/Desktop/{folder}")
        else:
            path = folder
        return 'list_directory', {'path': path}

    # Open folder requests: prefer xdg-open via run_shell_command for GUI
    nl_open_match = re.search(r"\b(?:open|show|launch|display)\s+(?:the\s+)?([\w\-\. ]+?)(?:\s+folder|\s+directory)?(?:\s+on\s+my\s+desktop|\s+on\s+desktop)?\b", normalized)
    if nl_open_match:
        folder = nl_open_match.group(1).strip()
        if 'desktop' in normalized or 'on my desktop' in text.lower() or 'on desktop' in text.lower():
            path = os.path.expanduser(f"~/Desktop/{folder}")
        else:
            path = folder
        # Use xdg-open to open the folder in the user's file manager
        return 'run_shell_command', {'command': f'xdg-open "{path}"'}

    create_folder_patterns = [
        r'\b(?:create|make|new)\s+(?:a|an)?\s*(?:folder|directory)\s+(?:named|called)?\s*([\w\-\. ]+)',
        r'\b(?:create|make|new)\s+(?:a|an)?\s*(?:folder|directory)\s+on\s+(?:my\s+)?(?:desktop|computer|pc)\b',
        r'\bnew\s+folder\s+named\s+([\w\-\. ]+)(?:\s+on\s+my\s+desktop|\s+on\s+desktop)?\b',
        r'\bnew\s+folder\s+([\w\-\. ]+)(?:\s+on\s+my\s+desktop|\s+on\s+desktop)?\b',
    ]
    for pattern in create_folder_patterns:
        match = re.search(pattern, normalized)
        if match:
            folder_name = match.group(1).strip() if match.groups() else 'new_folder'
            folder_name = re.sub(r'\s+(?:on|in|for|at|to)\b.*$', '', folder_name).strip()
            folder_name = re.sub(r'\s+', '_', folder_name).strip(' ._') or 'new_folder'
            desktop_root = getattr(config, 'DESKTOP_PATH', None) or os.path.expanduser('~/Desktop')
            return 'manage_files', {'action': 'mkdir', 'path': os.path.join(desktop_root, folder_name)}

    file_patterns = [
        (r'\b(?:read|open|view|show|display)\s+(?:file|document)\s+([/\w\-\. ]+)', 'read'),
        (r'\b(?:delete|remove)\s+(?:file|document)\s+([/\w\-\. ]+)', 'delete'),
        (r'\b(?:move|copy)\s+([/\w\-\. ]+)\s+(?:to|into)\s+([/\w\-\. ]+)', 'move'),
        (r'\b(?:list|show|ls)\s+(?:files|directory|folder)\s+([/\w\-\. ]+)', 'list'),
    ]
    for pattern, action in file_patterns:
        match = re.search(pattern, normalized)
        if match:
            if action == 'move' and match.groups().__len__() >= 2:
                return 'manage_files', {'action': action, 'path': match.group(1), 'new_path': match.group(2)}
            else:
                return 'manage_files', {'action': action, 'path': match.group(1) if match.groups() else ''}

    open_app_match = re.search(r'\b(?:open|launch|start|run|execute)\s+(?:the\s+)?([a-zA-Z0-9\s\-]+?)(?:\s+(?:app|application|program|browser|editor))?\b', normalized)
    if open_app_match:
        app_name = open_app_match.group(1).strip().lower()
        if app_name in {'a', 'an', 'the'} or 'folder' in normalized or 'directory' in normalized or 'file' in normalized or 'command' in normalized:
            return None, {}
        if 'browser' in app_name or 'chrome' in app_name or 'firefox' in app_name or _looks_like_app_name(app_name):
            return 'open_app', {'app_name': app_name}
        return None, {}

    # ============================================================
    # WEB SEARCH
    # ============================================================
    search_match = re.search(r'\b(?:search|find|look(?:\s+up)?|query|google|ask|research)\s+(?:for\s+|about\s+)?(.+?)(?:\s+(?:online|on\s+web|internet))?\b', normalized)
    if search_match:
        query = search_match.group(1).strip()
        return 'search_web', {'query': query}

    # ============================================================
    # MEMORY / RECALL
    # ============================================================
    memory_patterns = [
        r'\b(?:recall|remember|tell me about|what.*?know|do you remember|remind me)\b',
        r'\b(?:who|what|where|when|why).*?(?:user|me|my|friend|contact)\b',
    ]
    if any(re.search(p, normalized) for p in memory_patterns):
        query_match = re.search(r'(?:about|of|regarding|tell me about)\s+(.+?)(?:\?|$)', normalized)
        query = query_match.group(1).strip() if query_match else normalized
        return 'recall_memory', {'query': query}

    # ============================================================
    # SAVE MEMORY / FACTS
    # ============================================================
    save_memory_patterns = [
        r'\b(?:remember|save|store|note|log).*?(?:that|my|me)\b',
        r'\b(?:my|i)\s+(?:am|is|have|like|love|hate|enjoy|prefer)\b',
    ]
    if any(re.search(p, normalized) for p in save_memory_patterns):
        # Extract key=value patterns
        value_match = re.search(r'(?:is|am|have|like|love|hate|enjoy|prefer)\s+(.+?)(?:\?|$)', normalized)
        if value_match:
            return 'save_memory', {'person': 'User', 'key': 'detail', 'value': value_match.group(1).strip()}

    # ============================================================
    # WHATSAPP MESSAGING
    # ============================================================
    whatsapp_patterns = [
        r'\b(?:send|message|text|whatsapp)\s+(.+?)\s+(?:message|text|to)\s+(.+?)\b',
        r'\b(?:message|text)\s+(.+?)\s+(?:saying|with|that)\s+(.+?)\b',
    ]
    for pattern in whatsapp_patterns:
        match = re.search(pattern, normalized)
        if match:
            contact = match.group(1) if match.groups().__len__() == 2 else match.group(2)
            msg = match.group(2) if match.groups().__len__() == 2 else match.group(1)
            return 'send_whatsapp', {'contact_name': contact.strip(), 'message': msg.strip()}

    # ============================================================
    # TRADING NEWS & MARKET CALENDAR
    # ============================================================
    news_patterns = [
        r'\b(?:news|forex news|market news|latest news|current events)\b',
        r'\b(?:economic calendar|market calendar|events today|events this week)\b',
        r'\b(?:what.*?happening|what.*?going on|what.*?news)\b',
        r'\b(?:currency news|fx news|crypto news)(?:\s+for\s+(\w+))?\b',
    ]
    if any(re.search(p, normalized) for p in news_patterns):
        symbol_match = re.search(r'(?:news|currency news|fx news|crypto news)\s+(?:for\s+)?(\w+)', normalized)
        symbol = symbol_match.group(1).upper() if symbol_match else None
        return 'get_forex_news', {'symbol': symbol}

    calendar_patterns = [
        r'\b(?:calendar|economic events|high impact events|market events|schedule|what.*?happening today|what.*?today)\b',
        r'\b(?:calendar|events)\b',
    ]
    if any(re.search(p, normalized) for p in calendar_patterns):
        return 'get_market_calendar', {}

    # ============================================================
    # MARKET ANALYSIS & TRADING
    # ============================================================
    trading_symbols = [s.lower() for s in config.TRADING_SYMBOLS]
    timeframe_regex = '|'.join([s.lower() for s in config.TRADING_TIMEFRAMES])
    for symbol in trading_symbols:
        if symbol in normalized:
            timeframe_match = re.search(r"\b(" + timeframe_regex + r")\b", normalized)
            timeframe = timeframe_match.group(1).upper() if timeframe_match else None
            risk_match = re.search(r'(?:risk|bet)\s+(\d+(?:\.\d+)?)\s*%?', normalized)
            risk_percent = float(risk_match.group(1)) / 100 if risk_match else 1.0
            args = {'symbol': symbol.upper(), 'risk_percent': risk_percent}
            if timeframe is not None:
                args['timeframe'] = timeframe
            return 'analyze_market_and_recommend', args

    chart_patterns = [
        r'\b(?:chart|candle|candlestick|rsi|ema|moving\s+average|indicator|analysis)\b',
        r'\b(?:show|display|plot|draw)\s+(?:chart|graph|candle)\b',
    ]
    if any(re.search(p, normalized) for p in chart_patterns):
        symbol_match = re.search(r"\b(" + '|'.join(trading_symbols) + r")\b", normalized)
        if not symbol_match:
            return None, {}
        symbol = symbol_match.group(1).upper()
        timeframe_match = re.search(r"\b(" + timeframe_regex + r")\b", normalized)
        args = {'symbol': symbol, 'risk_percent': 1.0}
        if timeframe_match:
            args['timeframe'] = timeframe_match.group(1).upper()
        return 'analyze_market_and_recommend', args

    # ============================================================
    # APP LISTING
    # ============================================================
    app_patterns = [
        r'\b(?:list|show|what).*\b(?:apps|applications|programs|software|installed)\b',
        r'\b(?:what|which|list).*\b(?:apps?|applications?|programs?)\b.*(?:on|of|in|my|laptop|system|computer)\b',
        r'\b(?:installed|running)\s+(?:apps?|applications?|programs?|software)',
        r'\blist\s+(?:of\s+)?apps?\b',
    ]
    if any(re.search(p, normalized) for p in app_patterns):
        return 'list_apps', {}

    # ============================================================
    # SKILL GENERATION & CODE EXECUTION
    # ============================================================
    skill_patterns = [
        r'\b(?:convert|transform|generate|create|build|write|code)\s+(.+?)(?:\s+(?:to|into|as)\s+)?(.+?)\b',
        r'\b(?:can you|please|write a script|generate code)\s+(.+?)\b',
    ]
    for pattern in skill_patterns:
        match = re.search(pattern, normalized)
        if match:
            instruction = ' '.join(match.groups()).strip()
            if instruction:
                return 'create_and_execute_skill', {'instruction': instruction}

    # ============================================================
    # DEFAULT: NO MATCH
    # ============================================================
    return None, {}
