import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import time
import os

class Handler(BaseHTTPRequestHandler):
    def _send(self, code, data):
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))

    def do_POST(self):
        if self.path != '/send':
            self._send(404, {'error': 'not found'})
            return
        length = int(self.headers.get('Content-Length', '0'))
        body = self.rfile.read(length).decode('utf-8') if length else ''
        try:
            payload = json.loads(body) if body else {}
        except Exception:
            payload = {}
        contact = payload.get('contact_name') or payload.get('contact') or payload.get('to')
        message = payload.get('message') or payload.get('text')
        resp = {
            'status': 'accepted',
            'contact': contact,
            'message': message,
            'message_id': 'localmock123'
        }
        self._send(202, resp)

    def log_message(self, format, *args):
        return

def run_server():
    server = HTTPServer(('127.0.0.1', 5006), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server

if __name__ == '__main__':
    server = run_server()
    print('Local test server listening on http://127.0.0.1:5006/send')
    # give server time to start
    time.sleep(0.5)
    # run the send_whatsapp call
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    os.environ['WHATSAPP_API_URL'] = 'http://127.0.0.1:5006/send'
    from skills.messaging.whatsapp_tools import send_whatsapp
    print(send_whatsapp('Jerome','hello from local test'))
    server.shutdown()
