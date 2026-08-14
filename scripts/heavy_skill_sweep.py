#!/usr/bin/env python3
import json, traceback
from pathlib import Path
OUT = Path('data') / 'heavy_skill_test_results.json'
results = {}

try:
    from core import tools, config
    from pathlib import Path
    def safe_call(key, **kwargs):
        try:
            fn = tools.TOOL_REGISTRY.get(key, {}).get('function')
            if not fn:
                return 'NOT FOUND'
            try:
                return fn(**kwargs)
            except TypeError:
                try:
                    return fn(*kwargs.values())
                except Exception:
                    return 'TYPE_ERROR: ' + traceback.format_exc()
        except Exception:
            return 'ERROR: ' + traceback.format_exc()

    # LLM-backed image generation (may use local HF if configured)
    try:
        results['generate_image'] = safe_call('generate_image', prompt='Autotest image of a red circle', style='minimal')
    except Exception as e:
        results['generate_image'] = 'EXCEPTION: ' + str(e)

    # Web search
    try:
        results['search_web'] = safe_call('search_web', query='Angelique project local repo summary')
    except Exception as e:
        results['search_web'] = 'EXCEPTION: ' + str(e)

    # Playwright WhatsApp prepare (does not send)
    try:
        results['prepare_whatsapp'] = safe_call('prepare_whatsapp_message', contact_name='Test Contact', message='Automated test - do not send')
    except Exception as e:
        results['prepare_whatsapp'] = 'EXCEPTION: ' + str(e)

    # Try to search user's home directory for a common file (README.md), then optionally root '/'
    try:
        home = str(Path.home())
        results['search_home_readme'] = safe_call('search_files', query='README.md', root=home, max_results=20)
    except Exception as e:
        results['search_home_readme'] = 'EXCEPTION: ' + str(e)
    try:
        # Only attempt full-root search if explicitly allowed via env var to avoid long ops
        import os
        if os.environ.get('ANGELIQUE_ALLOW_ROOT_SEARCH','0') == '1':
            results['search_root_readme'] = safe_call('search_files', query='README.md', root='/', max_results=50)
        else:
            results['search_root_readme'] = 'SKIPPED: root search not allowed (set ANGELIQUE_ALLOW_ROOT_SEARCH=1 to enable)'
    except Exception as e:
        results['search_root_readme'] = 'EXCEPTION: ' + str(e)

except Exception:
    results['exception'] = traceback.format_exc()

OUT.parent.mkdir(parents=True, exist_ok=True)
with open(OUT,'w') as f:
    json.dump(results, f, default=str, indent=2)
print('WROTE', OUT)
print(json.dumps(results, indent=2))
