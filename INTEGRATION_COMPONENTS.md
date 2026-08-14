Integration Components Summary

This file lists discovered components in each `base projects/*` folder and suggests adapter approaches for integrating them into Angelique.

1) JARVIS (base projects/JARVIS)
  - Components discovered (path: `base projects/JARVIS/Jarvis/features`):
    - `date_time.py` — time/date utilities
    - `system_stats.py` — CPU, memory, battery info via `psutil`
    - `launch_app.py`, `website_open.py`, `weather.py`, `wikipedia.py`, `news.py`, `send_email.py`, `google_search.py`, `google_calendar.py`, `note.py`, `youtube_search.py`
  - Adapter suggestion:
    - `core/adapters/jarvis_adapter.py` (POC implemented) to wrap `JarvisAssistant` methods and `features.*` functions.
    - Register selected wrappers as tools in `core/tools.py` behind feature flags.

2) Jarvis (base projects/Jarvis)
  - Components discovered (path: `base projects/Jarvis/custom`, top-level `jarviscli`):
    - Plugin system (`plugin` decorator, `custom` plugins)
    - CLI runner, installer scripts
  - Adapter suggestion:
    - Implement `core/adapters/jarviscli_adapter.py` that discovers plugin files and exposes plugin callables as Angelique skills using a thin translation layer.
    - Provide safe execution wrappers to prevent blocking/malicious plugins.

3) Jarvis-Desktop-Voice-Assistant (base projects/Jarvis-Desktop-Voice-Assistant)
  - Components discovered:
    - `jarvis.py` — standalone voice assistant script with `time()`, `date()`, `screenshot()`, `play_music()`, `search_wikipedia()` etc.
  - Adapter suggestion:
    - Create adapter that maps simple functions (`time`, `date`, `screenshot`) to Angelique `skills/voice/` and `skills/vision/` wrappers.

4) OpenJarvis (base projects/OpenJarvis)
  - Components discovered:
    - Large framework for local-first agents, skills catalog, builtin agents, Rust components, `pyproject.toml`, and many docs.
  - Adapter suggestion:
    - Treat OpenJarvis as a heavyweight optional integration: import specific skill packages or reuse the `skills` spec. Implement a bridge `core/adapters/openjarvis_bridge.py` that can register OpenJarvis skills and optionally run `uv` commands in a subprocess for heavier workloads.

Integration priorities

- Short-term (POC): `JARVIS` and `Jarvis-Desktop-Voice-Assistant` — surface `time`, `date`, `system_info`, `screenshot` features via `core/adapters/jarvis_adapter.py` and small wrappers.
- Medium-term: `Jarvis` plugin loader integration and safe plugin sandboxing.
- Long-term: `OpenJarvis` skill bridge, selective skill import, or optional submodule integration.

Notes

- Adapters should not overwrite existing Angelique skills; they should register under namespaced tool names like `jarvis.time` or `adapter.jarvis.system_info`.
- Optional runtime dependencies (e.g., `pyttsx3`, `psutil`, `speech_recognition`) must be optional in `requirements.txt` and gated via `core/config.py` flags.

Next steps performed:

- Created `core/adapters/jarvis_adapter.py` (POC).
- Added tests `tests/test_jarvis_adapter.py` (skips gracefully if Jarvis not importable).
