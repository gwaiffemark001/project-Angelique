# Angelique — machine validation after installation

The source has been statically and functionally validated in an isolated environment.
The following require the actual Ubuntu machine and its live services/hardware:

1. Start Ollama and verify installed models:
   ollama list
   curl -s http://127.0.0.1:11434/api/tags

2. Test GUI:
   source .venv/bin/activate
   python launcher.py --gui

3. MT5:
   - Start the MT5 terminal/bridge used by the project.
   - Confirm the intended account (demo first, then live).
   - Confirm trading is enabled in MT5.
   - Keep live auto-execution disabled until broker connectivity and order-check behaviour have been verified.

4. WhatsApp:
   - Configure the Meta Cloud API credentials (or compatible HTTP gateway).
   - Verify the target person exists uniquely in skills/messaging/contacts.csv.
   - Send a test message to a controlled test contact first.

5. Voice/vision:
   - Verify microphone, speakers, camera and screen capture permissions/devices.

6. Ubuntu privileged commands:
   - Verify the configured sudo/polkit path.
   - Confirm that privileged commands remain asynchronous and do not block the Tk event loop.

The source test suite can be rerun with:

    python -m pytest -q

The grouped functional suites can be rerun with:

    python scripts/validate_skills.py
    python scripts/validate_skill_groups.py
    python scripts/validate_remaining_public_ops.py
