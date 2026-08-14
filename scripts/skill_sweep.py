#!/usr/bin/env python3
import json, traceback
from core import tools, config
from pathlib import Path
OUT = Path(config.DATA_DIR) / 'skill_test_results.json'
results = {}

def safe_call(key, **kwargs):
    try:
        entry = tools.TOOL_REGISTRY.get(key, {})
        fn = entry.get('function')
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

try:
    # File management
    results['mkdir_data'] = safe_call('manage_files', action='mkdir', path=str(Path(config.DATA_DIR)/'skill_test_dir'))
    results['create_file'] = safe_call('manage_files', action='create', path=str(Path(config.DATA_DIR)/'skill_test_dir'/'hello.txt'), content='hello')
    results['read_file'] = safe_call('manage_files', action='read', path=str(Path(config.DATA_DIR)/'skill_test_dir'/'hello.txt'))
    results['save_pdf'] = safe_call('save_text_pdf', path=str(Path(config.DATA_DIR)/'skill_test_dir'/'hello.pdf'), content='hello pdf')
    results['run_shell'] = safe_call('run_shell_command', command=f"echo shell_test > {str(Path(config.DATA_DIR)/'shell_test.txt')}")
    results['list_dir'] = safe_call('list_directory', path=str(Path(config.DATA_DIR)/'skill_test_dir'))

    # Calendar
    results['calendar_add'] = safe_call('adapter.calendar.add_event', title='skill_test_event', start_iso='2026-08-14T12:00:00', end_iso='2026-08-14T12:05:00', description='from automated test')
    results['calendar_list'] = safe_call('adapter.calendar.list')

    # Image->PDF
    img_src = '/home/gwaiffemark/Desktop/Projects/smartgurd_pro/web/favicon.png'
    results['imgtopdf'] = safe_call('adapter.img.imgtopdf', image_paths=[img_src], output_path=str(Path(config.DATA_DIR)/'imgtest.pdf'))

    # Messaging
    results['messaging_status'] = safe_call('check_messaging_status')
    results['draft_whatsapp'] = safe_call('draft_whatsapp', contact_name='Test Contact', message='Hello from automated test')

    # Trading checks
    results['mt5_ping'] = safe_call('check_mt5_status')
    results['get_account'] = safe_call('get_account_balance')

    # Voice (may be offline)
    try:
        from skills.voice.voice_interface import speak
        speak('Automated TTS test from skill sweep')
        results['speak'] = 'invoked'
    except Exception as e:
        results['speak'] = 'ERROR: ' + str(e)

    # Self evolution
    results['think_problem'] = safe_call('think_about_problem', problem='Add two numbers 2+2 and return result plan')

    # Conversation: remember/recall
    results['remember'] = safe_call('remember', key='autotest_key', value='autotest_value', importance=3)
    results['recall'] = safe_call('recall_conversation', query='autotest_key')

except Exception:
    results['exception'] = traceback.format_exc()

# Save results
try:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT,'w') as f:
        json.dump(results, f, default=str, indent=2)
    print('WROTE', OUT)
except Exception:
    print('FAILED WRITE', traceback.format_exc())

print(json.dumps(results, default=str, indent=2))
