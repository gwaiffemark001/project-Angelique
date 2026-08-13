import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Point to local mock WhatsApp
os.environ['WHATSAPP_API_URL'] = 'http://127.0.0.1:5006/send'

from skills.conversation.chat_skill import handle_user_message

commands = [
    "create a folder named fox on the desktop",
    "send a message to jerome on whatsapp saying yoooo",
    "create a pdf of all the images on my desktop and name it images",
    "system diagnostics",
    "what is the time",
    "search my laptop for all files having Angelique in the file name",
]

for cmd in commands:
    print('='*60)
    print('USER:', cmd)
    res = handle_user_message('default', cmd)
    print('SOURCE:', res.get('source'))
    print('ANSWER:', res.get('answer'))
    print('DETAILS:', res.get('details'))
    time.sleep(0.3)
