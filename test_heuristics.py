#!/usr/bin/env python3
"""Test expanded deterministic heuristics."""
from brain.cognitive_loop import resolve_user_query

test_cases = [
    # Messaging
    'send hello to Jerome', 'message Alice say hello world', 'text Bob this is a test',
    'send whatsapp to Sarah with hello', 'tell John that im here',
    # Image generation
    'generate an image of a sunset', 'create image red car 512x512', 'draw a dog',
    'paint an astronaut', 'render a galaxy 1024x1024',
    # Voice/TTS
    'say hello world', 'speak this is a test', 'announce meeting at 3pm',
    'read aloud: the quick brown fox', 'voice: hello there',
    # File operations
    'open README.md', 'show data/test.txt', 'read /etc/hosts',
    'list files in data', 'show me the files in /tmp', 'what files are in .',
    'create folder my_project', 'make directory test_dir', 'new folder backup',
    'delete file /tmp/test.txt', 'remove data/old.txt', 'rm backup.bak',
    'move data/a.txt to data/b.txt', 'rename old.txt new.txt',
    'copy file1.txt to file2.txt', 'duplicate config.json to config.bak',
    # Apps
    'open firefox', 'launch chrome', 'start code', 'run terminal',
    'begin libreoffice', 'execute vlc',
    # System
    'check system health', 'show computer performance', 'get pc status',
    # Web search
    'search for python tutorials', 'google what is machine learning',
    'find information about ai', 'look up weather',
    # Memory
    'recall what you know about me', 'remember my birthday',
    'tell me about john', 'remind me about the meeting',
    # Screenshots
    'take a screenshot', 'screenshot', 'capture screen',
    'read screen', 'show what on screen',
    # Camera
    'camera', 'webcam check', 'analyze camera', 'what do you see',
]

results = {'passed': 0, 'failed': 0, 'errors': 0, 'examples': []}
for text in test_cases:
    try:
        res = resolve_user_query(text, session_id='test')
        source = res.get('source') if isinstance(res, dict) else None
        tool = res.get('details', {}).get('tool') if isinstance(res, dict) else None
        if source == 'tool':
            results['passed'] += 1
            results['examples'].append({'text': text, 'tool': tool, 'status': 'routed'})
        else:
            results['failed'] += 1
            results['examples'].append({'text': text, 'source': source, 'status': 'missed'})
    except Exception as e:
        results['errors'] += 1
        results['examples'].append({'text': text, 'error': str(e)[:100]})

print(f"✅ Routed to tools: {results['passed']}")
print(f"❌ Missed (sent to LLM): {results['failed']}")
print(f"⚠️  Errors: {results['errors']}")
print(f"\nHit rate: {results['passed']}/{len(test_cases)} ({100*results['passed']//len(test_cases)}%)")
print("\nMisses and errors:")
for ex in results['examples']:
    if ex['status'] != 'routed':
        print(f"  - {ex['text'][:80]} → {ex.get('source', 'ERROR')}")
