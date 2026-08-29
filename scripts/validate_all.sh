#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
python -m pytest -q --disable-warnings --maxfail=1
python - <<'PY'
from pathlib import Path
import importlib, sys
sys.path.insert(0, '.')
fails=[]; count=0
for p in Path('skills').rglob('*.py'):
    if '__pycache__' in p.parts: continue
    count += 1
    try: importlib.import_module('.'.join(p.with_suffix('').parts))
    except Exception as exc: fails.append((str(p), str(exc)))
print(f'IMPORT_SCAN modules={count} failures={len(fails)}')
for item in fails: print(item)
raise SystemExit(bool(fails))
PY
if command -v Xvfb >/dev/null 2>&1; then
  display_num=:99
  Xvfb "$display_num" -screen 0 1920x1080x24 >/tmp/angelique-xvfb.log 2>&1 &
  xvfb_pid=$!
  trap 'kill "$xvfb_pid" >/dev/null 2>&1 || true' EXIT
  sleep 1
  DISPLAY="$display_num" python scripts/validate_skills.py
else
  echo 'Xvfb not installed; GUI functional check must be run under a graphical session.' >&2
fi
