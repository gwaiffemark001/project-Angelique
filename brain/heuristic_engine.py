# brain/heuristic_engine.py
"""
Comprehensive heuristic engine for deterministic command routing.
Maps natural language to tool actions without LLM dependency for critical commands.
"""
import re


def extract_command_heuristically(text: str) -> tuple[str, dict] | tuple[None, dict]:
    """
    Heuristically extract command and args from user text.
    Returns (tool_name, args) or (None, {}) if no match.
    """
    normalized = text.strip().lower()
    if not normalized:
        return None, {}

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
    # SYSTEM MONITORING
    # ============================================================
    system_monitor_patterns = [
        r'\b(?:cpu|ram|memory|disk|load|system|performance|health|telemetry|monitoring)\b',
        r'\b(?:how.*?(?:cpu|ram|memory|resources).*?(?:used|used up))\b',
        r'\b(?:top\s+)?processes\b',
    ]
    if any(re.search(p, normalized) for p in system_monitor_patterns):
        return 'get_system_health', {}

    # ============================================================
    # APP DISCOVERY & OPENING
    # ============================================================
    open_app_match = re.search(r'\b(?:open|launch|start|run|execute)\s+(?:the\s+)?([a-zA-Z0-9\s\-]+?)(?:\s+(?:app|application|program|browser|editor))?\b', normalized)
    if open_app_match:
        app_name = open_app_match.group(1).strip().title()
        return 'open_app', {'app_name': app_name}

    # ============================================================
    # FILE MANAGEMENT
    # ============================================================
    file_patterns = [
        (r'\b(?:create|write|save)\s+(?:file|document).*?(?:at|to)\s+([/\w\-\. ]+)', 'create'),
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
    # MARKET ANALYSIS & TRADING
    # ============================================================
    trading_symbols = ['eurusd', 'gbpusd', 'audusd', 'usdjpy', 'xauusd', 'btcusd', 'ethusd', 'linkusd', 'aaveusd']
    for symbol in trading_symbols:
        if symbol in normalized:
            timeframe_match = re.search(r'\b(m1|m5|m15|m30|h1|h4|d1|w1)\b', normalized)
            timeframe = timeframe_match.group(1).upper() if timeframe_match else 'H1'
            risk_match = re.search(r'(?:risk|bet)\s+(\d+(?:\.\d+)?)\s*%?', normalized)
            risk_percent = float(risk_match.group(1)) / 100 if risk_match else 1.0
            return 'analyze_market_and_recommend', {
                'symbol': symbol.upper(),
                'timeframe': timeframe,
                'risk_percent': risk_percent
            }

    chart_patterns = [
        r'\b(?:chart|candle|candlestick|rsi|ema|moving\s+average|indicator|analysis)\b',
        r'\b(?:show|display|plot|draw)\s+(?:chart|graph|candle)\b',
    ]
    if any(re.search(p, normalized) for p in chart_patterns):
        symbol_match = re.search(r'\b(eurusd|gbpusd|audusd|usdjpy|xauusd|btcusd|ethusd|linkusd|aaveusd)\b', normalized)
        symbol = symbol_match.group(1).upper() if symbol_match else 'EURUSD'
        timeframe_match = re.search(r'\b(m1|m5|m15|m30|h1|h4|d1|w1)\b', normalized)
        timeframe = timeframe_match.group(1).upper() if timeframe_match else 'H1'
        return 'analyze_market_and_recommend', {'symbol': symbol, 'timeframe': timeframe, 'risk_percent': 1.0}

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
