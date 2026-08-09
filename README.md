# Angelique

Angelique is an autonomous AI agent and productivity assistant built in Python. It combines a cognitive loop, memory, tool routing, self-evolution, multimedia handling, trading integration, and a voice-enabled interface.

## Key Features

- Self-evolution: generate and execute Python skills on demand via `skills/self_evolution/code_generator.py`
- Deterministic tool routing and fallback heuristics in `brain/cognitive_loop.py`
- Chat and memory tools with ChromaDB-based semantic recall
- Voice wake-word support using `skills/voice/wake_word_system.py`
- MT5 trading bridge connectivity via `skills/trading/engine/connection_manager.py`
- WebM→MP4 conversion fallback with ffmpeg and execution timeout protection
- Modular skill registry in `core/tools.py`

## Repository Layout

- `main.py` – entry point for the Angelique runtime and audio loop
- `brain/` – core cognition, memory, and self-evolution logic
- `core/` – configuration, tool registry, and router logic
- `skills/` – skill implementations for voice, vision, trading, OS control, messaging, and more
- `data/` – generated skills, logs, ChromaDB memory, and runtime artifacts
- `tests/` – unit tests and integration checks

## Getting Started

1. Create and activate a Python virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Run Angelique:

```bash
python3 launcher.py
```

This will launch Angelique's native desktop app in GUI mode by default. Use `python3 launcher.py --terminal` to start the terminal interface.

## Self-Evolution Workflow

Angelique can generate and execute ad-hoc Python skills:

- `skills/self_evolution/code_generator.py` handles generation, markdown cleanup, execution, and fallback logic.
- `core/tools.py` registers `create_and_execute_skill` as a callable tool.
- `brain/cognitive_loop.py` routes user requests through the tool registry and returns direct tool results when appropriate.

### Example commands

- Get current date/time:
  - `What is the current date and time?`
- Convert a WebM file to MP4:
  - `Convert '/path/to/source.webm' to '/path/to/output.mp4'`

## Trading and MT5 Bridge

- `skills/trading/engine/connection_manager.py` manages persistent MT5 bridge connectivity.
- Bridge host and port configuration is stored in `core/config.py`.
- `brain/cognitive_loop.py` can call trading tools directly when the LLM decides a tool action is needed.

## Notes

- The system is designed to avoid hallucination by using strict tool JSON responses and deterministic heuristics when LLM output is unclear.
- Wake-word activation is handled in `main.py` with `skills/voice/wake_word_system.py`.
- Multimedia conversions and self-evolved Python execution are sandboxed and time-limited.

## Contributing

- Review `README.md` and `core/tools.py` to understand available tools.
- Add new skills under `skills/` and register them in `core/tools.py`.
- Keep self-evolution fallback rules in `skills/self_evolution/code_generator.py`.
