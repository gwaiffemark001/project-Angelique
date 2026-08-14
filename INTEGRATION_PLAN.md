Integration Plan: Merge base projects into Angelique

Overview

This plan integrates components from the "base projects" folder into Angelique to consolidate features and avoid duplication. Integration will be incremental and non-destructive: new code will be added under `skills/` or `core/adapters/` and existing APIs preserved.

Discovered base projects

- JARVIS (base projects/JARVIS) — voice assistant with system info, file management, image/pdf conversion, web/weather, email sending, games, utilities, GUI.
- Jarvis (base projects/Jarvis) — mature plugin-based assistant with many utilities, plugins, installer and test scripts.
- Jarvis-Desktop-Voice-Assistant — (not yet inspected in-depth)
- OpenJarvis — (not yet inspected in-depth)

High-level mapping (initial)

- Voice & Wake-word features -> `skills/voice/` (merge Jarvis voice plugins as skill adapters)
- System info, OS utilities, file management -> `skills/os_control/` and `skills/file_management/`
- Image processing, screenshot, camera -> `skills/vision/` and `skills/file_management/`
- PDF & html conversion -> `skills/file_management/pdf_utils.py` (or existing `save_text_pdf` enhancements)
- Web/weather, news, search -> `skills/web/` and `skills/messaging/`
- Games & utilities -> optionally include under `skills/misc/` or `skills/cli_tools/`
- Plugin system from Jarvis -> implement an adapter loader `core/plugin_adapter.py` to wrap Jarvis plugin definitions into Angelique `Skill` interface

Integration approach

1. Inventory each base project for reusable modules and assets.
2. For each reusable module, write a thin adapter in `core/adapters/` or `skills/<category>/adapters/` that translates Jarvis plugin signatures to Angelique skill signatures.
3. Add automated unit tests for adapters to ensure no regressions.
4. Merge non-conflicting dependencies into `requirements.txt` and gate heavy/optional deps behind feature flags.
5. Incrementally enable adapters (one feature set at a time) and run Angelique tests.
6. Update `README.md` and `tools/run_demo.py` to showcase merged features.

First integration milestones (short-term)

- Create `core/adapters/jarvis_adapter.py` to load Jarvis plugins as Angelique skills (proof of concept: one plugin, e.g., `time` / `date` or `system status`).
- Add unit tests that call adapter-registered skills and compare outputs with Jarvis originals.
- Merge Jarvis `image to pdf` feature into `skills/file_management/image_pdf.py` and ensure `manage_files('image_pdf')` works.

Safety and non-destructive rules

- All new code will be added, not replaced, unless the user explicitly asks to refactor.
- We will run `pytest` after each major integration step and fix any regressions before proceeding.
- Heavy optional features (GUI, Playwright, MT5) will be disabled behind environment flags by default.

Next steps (I'll proceed unless you instruct otherwise)

1. Deep-scan each base project folder (`Jarvis`, `JARVIS`, `Jarvis-Desktop-Voice-Assistant`, `OpenJarvis`) to enumerate key modules and candidate functions.
2. Produce a per-project component list with suggested adapters and estimated effort.

If that's good, I'll start deep-scanning `base projects/JARVIS` files to enumerate its `Jarvis/` features and plugin list.
