# Angelique validation

The project uses three complementary checks:

1. `python -m pytest -q --disable-warnings --maxfail=1` exercises deterministic unit/integration regressions.
2. `scripts/validate_all.sh` imports every Python module under `skills/` and runs the functional skill matrix under Xvfb when available.
3. The GUI check verifies the original desktop interface can render at 1920x1080 and that its primary controls and Trading Hub controls are present.

The functional suite deliberately mocks external or destructive operations such as live MT5 orders, WhatsApp delivery, and cloud model responses. A passing suite proves the interfaces and failure handling; it does not pretend to have executed a real live trade or real WhatsApp message.
