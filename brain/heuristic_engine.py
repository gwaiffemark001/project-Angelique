# brain/heuristic_engine.py
"""
Comprehensive heuristic engine for deterministic command routing.
Maps natural language to tool actions without LLM dependency for critical commands.
"""
import os
import re
from core import config


def extract_command_heuristically(text: str) -> tuple[str, dict] | tuple[None, dict]:
    """
    Heuristically extract command and args from user text.
    Returns (tool_name, args) or (None, {}) if no match.
    """
    normalized = text.strip().lower()
    if not normalized:
        return None, {}

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
    browser_match = re.search(r'\b(?:open|launch|start|run|execute)\s+(?:a|an|the)??\s*(?:browser|chrome|firefox|web browser)\b', normalized)
    if browser_match:
        return 'open_app', {'app_name': 'firefox'}

    open_app_match = re.search(r'\b(?:open|launch|start|run|execute)\s+(?:the\s+)?([a-zA-Z0-9\s\-]+?)(?:\s+(?:app|application|program|browser|editor))?\b', normalized)
    if open_app_match:
        app_name = open_app_match.group(1).strip().lower()
        if app_name in {'a', 'an', 'the'}:
            return None, {}
        return 'open_app', {'app_name': app_name}

    # ============================================================
    # GENERIC SKILL DISPATCH
    # ============================================================
    skill_call_patterns = [
        r'\b(?:use|call|run|invoke)\s+(?:the\s+)?(.+?)\s+skill\b',
        r'\b(?:use|call|run|invoke)\s+(?:the\s+)?([a-zA-Z0-9_\.\-]+)\b',
        r'\b(?:activate|start|open)\s+(?:the\s+)?([a-zA-Z0-9_\.\-]+)\b',
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
    create_folder_patterns = [
        r'\b(?:create|make)\s+(?:a|an)?\s*(?:folder|directory)\s+(?:named|called)?\s*([\w\-\. ]+)',
        r'\b(?:create|make)\s+(?:a|an)?\s*(?:folder|directory)\s+on\s+(?:my\s+)?(?:desktop|computer|pc)\b',
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
            return 'prepare_whatsapp_message', {'contact_name': contact.strip(), 'message': msg.strip()}

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
